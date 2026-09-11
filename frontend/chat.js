// AI Assistant page.
//
// Flow per message:
//   1. POST /api/assistant with the full conversation + the fields we
//      already hold. The backend asks the LLM to interpret the text and
//      then VALIDATES everything itself (bench, case type code, dates...).
//   2. Render the reply, then a "Search parameters" card showing what is
//      understood so far and what is still missing.
//   3. When the backend says ready, the card shows a Run button. Run posts
//      the validated fields to /api/assistant/run, which picks Quick Search
//      (bench + type + number + year only) or Detailed Search (everything
//      else) and starts the Playwright + Tesseract scraper.
//   4. Progress streams over the same /ws/logs WebSocket the other pages
//      use. On "done" the results are stored under the same sessionStorage
//      key search.html / case-number.html read on load, so "Open in cases
//      view" simply navigates there.
(function () {
  const messagesEl = document.getElementById("chatMessages");
  const formEl = document.getElementById("chatForm");
  const inputEl = document.getElementById("chatInput");
  const sendBtn = document.getElementById("chatSendBtn");
  if (!formEl) return;

  const RESULT_KEYS = { detailed: "detailedSearchResults", quick: "quickSearchResults" };
  const RESULT_PAGES = { detailed: "search.html", quick: "case-number.html" };
  const SESSION_KEY = "assistantSession";

  const history = [];
  let fields = {};
  let paramCard = null;
  let running = false;
  let runMode = null;
  let progressUI = null;
  let ws = null;

  // ----------------------------------------------------------------
  // Session persistence
  // ----------------------------------------------------------------

  function saveSession() {
    try {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify({ history: history, fields: fields }));
    } catch (e) { /* ignore */ }
  }

  function restoreSession() {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (!data) return;
      fields = data.fields || {};
      (data.history || []).forEach(function (m) {
        history.push(m);
        if (m.role === "user" || m.role === "assistant") addMessage(m.role, m.content);
      });
    } catch (e) { /* ignore */ }
  }

  // ----------------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------------

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function renderMarkdown(text) {
    var html = escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/^[ \t]*[\*\-•][ \t]+(.+)$/gm, "<li>$1</li>")
      .replace(/(<li>[\s\S]*?<\/li>)(\n(?!<li>)|$)/g, function (m) {
        return "<ul>" + m.replace(/\n/g, "") + "</ul>";
      })
      .replace(/\n{2,}/g, "</p><p>")
      .replace(/\n/g, "<br>");
    if (!html.startsWith("<")) html = "<p>" + html + "</p>";
    return html;
  }

  function addMessage(role, text) {
    const wrap = document.createElement("div");
    wrap.className = "chat-msg " + (role === "user" ? "chat-msg--user" : "chat-msg--bot");
    const bubble = document.createElement("div");
    bubble.className = "chat-msg__bubble";
    if (role === "user") bubble.textContent = text;
    else bubble.innerHTML = renderMarkdown(text);
    wrap.appendChild(bubble);
    messagesEl.appendChild(wrap);
    scrollToBottom();
    return wrap;
  }

  function addBlock(html, extraClass) {
    const wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg--bot chat-msg--block " + (extraClass || "");
    wrap.innerHTML = html;
    messagesEl.appendChild(wrap);
    scrollToBottom();
    return wrap;
  }

  function addTypingIndicator() {
    const wrap = document.createElement("div");
    wrap.className = "chat-msg chat-msg--bot chat-msg--typing";
    wrap.id = "chatTyping";
    wrap.innerHTML = '<div class="chat-msg__bubble">Thinking…</div>';
    messagesEl.appendChild(wrap);
    scrollToBottom();
  }

  function removeTypingIndicator() {
    const el = document.getElementById("chatTyping");
    if (el) el.remove();
  }

  function refreshIcons() {
    if (window.lucide) lucide.createIcons();
  }

  // ----------------------------------------------------------------
  // Parameter card
  // ----------------------------------------------------------------

  function renderParamCard(data) {
    if (paramCard) paramCard.classList.add("param-card--stale");

    const rows = (data.display || []).map(function (r) {
      return "<tr><th>" + escapeHtml(r.key) + "</th><td>" + escapeHtml(r.value) + "</td></tr>";
    }).join("");

    const missing = (data.missing || []).map(function (m) {
      return "<li>" + escapeHtml(m) + "</li>";
    }).join("");

    const warnings = (data.warnings || []).map(function (w) {
      return "<li>" + escapeHtml(w) + "</li>";
    }).join("");

    const modeLabel = data.mode === "quick" ? "Quick Search" : "Detailed Search";

    const html =
      '<div class="param-card' + (data.ready ? " param-card--ready" : "") + '">' +
        '<div class="param-card__head">' +
          '<span><i data-lucide="list-checks"></i> Search parameters</span>' +
          (data.ready ? '<span class="param-card__mode">' + modeLabel + "</span>" : "") +
        "</div>" +
        (rows ? "<table class=\"param-card__table\">" + rows + "</table>"
              : '<p class="param-card__empty">Nothing understood yet.</p>') +
        (missing ? '<div class="param-card__missing"><strong>Still needed</strong><ul>' + missing + "</ul></div>" : "") +
        (warnings ? '<div class="param-card__warn"><ul>' + warnings + "</ul></div>" : "") +
        '<div class="param-card__actions">' +
          (data.ready
            ? '<button class="btn btn-primary btn-sm" data-act="run"><i data-lucide="play"></i> Run search</button>'
            : "") +
          (rows
            ? '<button class="btn btn-ghost btn-sm" data-act="edit"><i data-lucide="pencil"></i> Edit in form</button>' +
              '<button class="btn btn-ghost btn-sm" data-act="clear"><i data-lucide="x"></i> Start over</button>'
            : "") +
        "</div>" +
      "</div>";

    paramCard = addBlock(html);
    refreshIcons();

    paramCard.querySelectorAll("[data-act]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const act = btn.getAttribute("data-act");
        if (act === "run") runSearch();
        else if (act === "edit") editInForm(data.mode);
        else if (act === "clear") startOver();
      });
    });
  }

  function editInForm(mode) {
    try {
      sessionStorage.setItem("assistantPrefill", JSON.stringify(fields));
    } catch (e) { /* ignore */ }
    location.href = mode === "quick" ? "case-number.html" : "search.html";
  }

  function startOver() {
    fields = {};
    history.length = 0;
    try { sessionStorage.removeItem(SESSION_KEY); } catch (e) { /* ignore */ }
    if (paramCard) paramCard.classList.add("param-card--stale");
    paramCard = null;
    addMessage("bot", "Cleared. What would you like to search for?");
  }

  // ----------------------------------------------------------------
  // Send a message
  // ----------------------------------------------------------------

  async function sendMessage(text) {
    history.push({ role: "user", content: text });
    addMessage("user", text);
    addTypingIndicator();
    sendBtn.disabled = true;

    try {
      const resp = await fetch("/api/assistant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history, fields: fields }),
      });
      const data = await resp.json();
      removeTypingIndicator();

      const reply = data.reply || "Sorry, I didn't get a response.";
      history.push({ role: "assistant", content: reply });
      addMessage("bot", reply);

      if (!data.error) {
        fields = data.fields || {};
        if ((data.display && data.display.length) || (data.missing && data.missing.length && history.length > 2)) {
          renderParamCard(data);
        }
      }

      saveSession();
    } catch (err) {
      removeTypingIndicator();
      addMessage("bot", "Sorry, I couldn't reach the assistant right now.");
      console.error(err);
    } finally {
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  // ----------------------------------------------------------------
  // Run the scraper
  // ----------------------------------------------------------------

  async function runSearch() {
    if (running) {
      addMessage("bot", "A search is already running. Stop it first or wait for it to finish.");
      return;
    }
    if (paramCard) {
      const runBtn = paramCard.querySelector('[data-act="run"]');
      if (runBtn) runBtn.disabled = true;
    }

    let data;
    try {
      const resp = await fetch("/api/assistant/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields: fields }),
      });
      data = await resp.json();
    } catch (err) {
      addMessage("bot", "Couldn't start the search: " + err);
      return;
    }

    if (!data.started) {
      addMessage("bot", data.message || "Couldn't start the search.");
      if (paramCard) {
        const runBtn = paramCard.querySelector('[data-act="run"]');
        if (runBtn) runBtn.disabled = false;
      }
      return;
    }

    running = true;
    runMode = data.mode || "detailed";
    ensureWs();
    showProgress();
  }

  function showProgress() {
    const label = runMode === "quick" ? "Quick Search" : "Detailed Search";
    const el = addBlock(
      '<div class="run-card">' +
        '<div class="run-card__head"><span><i data-lucide="loader"></i> Running ' + label + "…</span>" +
          '<button class="btn btn-danger btn-sm" data-act="stop"><i data-lucide="square"></i> Stop</button></div>' +
        '<div class="run-card__bar"><div class="run-card__fill"></div></div>' +
        '<div class="run-card__status">Starting browser…</div>' +
        '<pre class="run-card__log"></pre>' +
      "</div>"
    );
    refreshIcons();
    progressUI = {
      root: el,
      fill: el.querySelector(".run-card__fill"),
      status: el.querySelector(".run-card__status"),
      log: el.querySelector(".run-card__log"),
      head: el.querySelector(".run-card__head span"),
      stop: el.querySelector('[data-act="stop"]'),
    };
    progressUI.stop.addEventListener("click", async function () {
      progressUI.stop.disabled = true;
      try { await fetch("/api/search/stop", { method: "POST" }); } catch (e) { /* ignore */ }
    });
  }

  function ensureWs() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(proto + "://" + location.host + "/ws/logs");
    ws.onmessage = function (event) {
      let msg;
      try { msg = JSON.parse(event.data); } catch (e) { return; }
      handleWsMessage(msg);
    };
    ws.onclose = function () {
      if (running) setTimeout(ensureWs, 1500);
    };
    ws.onerror = function () { ws.close(); };
  }

  function appendLog(text, isErr) {
    if (!progressUI) return;
    const line = document.createElement("div");
    line.textContent = text;
    if (isErr) line.className = "err";
    progressUI.log.appendChild(line);
    progressUI.log.scrollTop = progressUI.log.scrollHeight;
  }

  function handleWsMessage(msg) {
    if (!running || !progressUI) return;
    if (msg.type === "log") {
      appendLog(msg.payload);
    } else if (msg.type === "progress") {
      const p = msg.payload;
      const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
      progressUI.fill.style.width = pct + "%";
      progressUI.status.textContent = "Processed " + p.done + " of " + p.total + " search job(s)…";
    } else if (msg.type === "case_progress") {
      const p = msg.payload;
      progressUI.status.textContent = "Opening case " + p.done + " of " + p.total + (p.label ? " — " + p.label : "");
    } else if (msg.type === "done") {
      onDone(msg.payload);
    } else if (msg.type === "error") {
      appendLog("Error: " + msg.payload, true);
      finishProgress("Search failed.");
      addMessage("bot", "The search failed: " + msg.payload);
    }
  }

  function finishProgress(text) {
    running = false;
    if (!progressUI) return;
    progressUI.fill.style.width = "100%";
    progressUI.status.textContent = text;
    progressUI.head.innerHTML = '<i data-lucide="check"></i> ' + escapeHtml(text);
    progressUI.stop.remove();
    refreshIcons();
    progressUI = null;
  }

  function onDone(payload) {
    const cases = payload.cases || [];
    const downloadHref = "/outputs/" + encodeURIComponent(payload.output_filename);
    const summaryText = runMode === "quick"
      ? (payload.case_count ? payload.case_count + " case(s) found." : "No case matched that Case Type / Number / Year.")
      : payload.case_count + " unique case(s) found, " + payload.duplicates_skipped + " duplicate(s) skipped.";

    finishProgress(payload.cancelled ? "Stopped — " + summaryText : "Done — " + summaryText);

    try {
      sessionStorage.setItem(RESULT_KEYS[runMode], JSON.stringify({
        cases: cases,
        summary: summaryText,
        downloadHref: downloadHref,
        filename: payload.output_filename,
      }));
    } catch (e) { console.warn("Could not persist results:", e); }

    const previewRows = cases.slice(0, 5).map(function (c) {
      const id = [c.case_type, c.case_no, c.case_year].filter(Boolean).join(" / ");
      const parties = [c.petitioner, c.respondent].filter(Boolean).join(" vs ");
      return "<li><strong>" + escapeHtml(id) + "</strong>" + (parties ? " — " + escapeHtml(parties) : "") + "</li>";
    }).join("");

    const more = cases.length > 5 ? "<li class=\"muted\">…and " + (cases.length - 5) + " more</li>" : "";

    const html =
      '<div class="overview-card">' +
        '<div class="overview-card__head"><i data-lucide="file-check"></i> Results overview</div>' +
        "<p>" + escapeHtml(summaryText) + "</p>" +
        (previewRows ? "<ul class=\"overview-card__list\">" + previewRows + more + "</ul>" : "") +
        '<div class="overview-card__actions">' +
          (cases.length
            ? '<a class="btn btn-primary btn-sm" href="' + RESULT_PAGES[runMode] + '"><i data-lucide="external-link"></i> Open in cases view</a>'
            : "") +
          '<a class="btn btn-outline btn-sm" href="' + downloadHref + '" download><i data-lucide="download"></i> Download Excel</a>' +
        "</div>" +
      "</div>";
    addBlock(html);
    refreshIcons();

    const followUp = cases.length
      ? "Search complete. Open the cases view for filters and full details, or tell me how to refine the search."
      : "Nothing matched. Try widening the date range, checking the spelling of names, or a different bench.";
    history.push({ role: "assistant", content: followUp });
    addMessage("bot", followUp);
    saveSession();
  }

  // ----------------------------------------------------------------
  // Input wiring
  // ----------------------------------------------------------------

  inputEl.addEventListener("input", function () {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
  });

  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      formEl.requestSubmit();
    }
  });

  formEl.addEventListener("submit", function (e) {
    e.preventDefault();
    const text = inputEl.value.trim();
    if (!text) return;
    inputEl.value = "";
    inputEl.style.height = "auto";
    sendMessage(text);
  });

  fetch("/api/search/status").then(function (r) { return r.json(); }).then(function (s) {
    if (s.is_running) addMessage("bot", "Note: a search is currently running from another page. Wait for it to finish before starting a new one.");
  }).catch(function () { /* ignore */ });

  // Restore previous session on page load
  restoreSession();
})();