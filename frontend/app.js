const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------
// Tabs
// ------------------------------------------------------------------

$("tabManualBtn").addEventListener("click", () => switchTab("manual"));
$("tabAiBtn").addEventListener("click", () => switchTab("ai"));

function switchTab(name) {
  $("tabManualBtn").classList.toggle("active", name === "manual");
  $("tabAiBtn").classList.toggle("active", name === "ai");
  $("panelManual").hidden = name !== "manual";
  $("panelAi").hidden = name !== "ai";
}

// ------------------------------------------------------------------
// Form options (static dropdowns)
// ------------------------------------------------------------------

async function loadFormOptions() {
  const res = await fetch("/api/form-options");
  const data = await res.json();

  fillSelect($("dbBench"), data.db_bench, "-- Select --");
  fillSelect($("coram"), data.coram, "-- Select --");
  fillSelect(
    $("caseType"),
    data.case_types,
    "-- Select --"
  );
  fillSelect(
    $("caseYear"),
    data.case_years.map((y) => ({ value: String(y), label: String(y) })),
    "Select Year"
  );

  const reportRow = $("reportTypeRow");
  reportRow.innerHTML = "";
  data.report_type.forEach((opt, i) => {
    const id = `report_${opt.value}`;
    const wrapper = document.createElement("label");
    wrapper.innerHTML = `<input type="radio" name="reportType" id="${id}" value="${opt.value}" ${opt.value === "none" ? "checked" : ""}> ${opt.label}`;
    reportRow.appendChild(wrapper);
  });
}

function fillSelect(select, options, placeholder) {
  select.innerHTML = "";
  const ph = document.createElement("option");
  ph.value = "";
  ph.textContent = placeholder;
  select.appendChild(ph);
  options.forEach((opt) => {
    const el = document.createElement("option");
    el.value = opt.value;
    el.textContent = opt.label;
    select.appendChild(el);
  });
}

// ------------------------------------------------------------------
// Judge / Author Judge -- populated live once a bench is chosen
// ------------------------------------------------------------------

$("dbBench").addEventListener("change", async () => {
  const bench = $("dbBench").value;
  const judgeSel = $("judge");
  const authSel = $("authJudge");

  if (!bench) {
    judgeSel.innerHTML = '<option value="">-- Select bench first --</option>';
    authSel.innerHTML = '<option value="">-- Select bench first --</option>';
    return;
  }

  judgeSel.innerHTML = '<option value="">Loading…</option>';
  authSel.innerHTML = '<option value="">Loading…</option>';

  try {
    const res = await fetch("/api/judges", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ db_bench: bench }),
    });
    const data = await res.json();
    const options = (data.judges || []).filter((j) => j.value);

    fillSelect(judgeSel, options, "-- Select --");
    fillSelect(authSel, options, "-- Select --");
  } catch (e) {
    judgeSel.innerHTML = '<option value="">Could not load</option>';
    authSel.innerHTML = '<option value="">Could not load</option>';
  }
});

// ------------------------------------------------------------------
// AI fill
// ------------------------------------------------------------------

$("aiFillBtn").addEventListener("click", async () => {
  const text = $("aiText").value.trim();
  $("aiError").hidden = true;
  $("aiNotes").hidden = true;

  if (!text) return;

  $("aiFillBtn").disabled = true;
  $("aiFillBtn").textContent = "Thinking…";

  try {
    const res = await fetch("/api/ai-fill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();

    if (!data.fields || Object.keys(data.fields).length === 0) {
      if (data.notes) {
        $("aiError").hidden = false;
        $("aiError").textContent = data.notes;
      }
      return;
    }

    await applyAiFields(data.fields);

    if (data.notes) {
      $("aiNotes").hidden = false;
      $("aiNotes").textContent = "AI note: " + data.notes;
    }

    switchTab("manual");
  } catch (e) {
    $("aiError").hidden = false;
    $("aiError").textContent = "Could not reach the AI service: " + e;
  } finally {
    $("aiFillBtn").disabled = false;
    $("aiFillBtn").textContent = "✨ Fill form with AI";
  }
});

async function applyAiFields(fields) {
  if (fields.db_bench) {
    $("dbBench").value = fields.db_bench;
    $("dbBench").dispatchEvent(new Event("change"));
    // give the judge dropdowns a moment; not required for AI fields today
    await new Promise((r) => setTimeout(r, 50));
  }
  if (fields.coram) $("coram").value = String(fields.coram);
  if (fields.case_type) $("caseType").value = String(fields.case_type);
  if (fields.case_no) $("caseNo").value = String(fields.case_no).replace(/\D/g, "");
  if (fields.case_year) $("caseYear").value = String(fields.case_year);
  if (fields.petitioner_name) $("petName").value = fields.petitioner_name;
  if (fields.respondent_name) $("respName").value = fields.respondent_name;
  if (fields.petitioner_adv) $("petAdv").value = fields.petitioner_adv;
  if (fields.respondent_adv) $("respAdv").value = fields.respondent_adv;

  if (fields.report_type) {
    const radio = document.querySelector(
      `input[name="reportType"][value="${fields.report_type}"]`
    );
    if (radio) radio.checked = true;
  }

  if (fields.from_date) $("fromDate").value = ddmmyyyyToInput(fields.from_date);
  if (fields.to_date) $("toDate").value = ddmmyyyyToInput(fields.to_date);

  if (Array.isArray(fields.aliases) && fields.aliases.length) {
    $("aliases").value = fields.aliases.join("\n");
  }
  if (fields.alias_field) {
    $("aliasField").value = fields.alias_field;
  }
}

function ddmmyyyyToInput(value) {
  const parts = String(value).split(/[-/]/);
  if (parts.length !== 3) return "";
  const [dd, mm, yyyy] = parts;
  if (!dd || !mm || !yyyy) return "";
  return `${yyyy.padStart(4, "0")}-${mm.padStart(2, "0")}-${dd.padStart(2, "0")}`;
}

function inputToDdmmyyyy(value) {
  if (!value) return null;
  const [yyyy, mm, dd] = value.split("-");
  return `${dd}-${mm}-${yyyy}`;
}

// ------------------------------------------------------------------
// WebSocket: live log / progress / results
// ------------------------------------------------------------------

let ws;

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/logs`);

  ws.onopen = () => setConnected(true);
  ws.onclose = () => {
    setConnected(false);
    setTimeout(connectWs, 2000);
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleWsMessage(msg);
  };
}

function setConnected(connected) {
  $("connDot").classList.toggle("connected", connected);
  $("connLabel").textContent = connected ? "Connected" : "Reconnecting…";
}

function handleWsMessage(msg) {
  if (msg.type === "log") {
    appendLog(msg.payload);
  } else if (msg.type === "progress") {
    const { done, total } = msg.payload;
    $("progressWrap").hidden = false;
    const pct = total ? Math.round((done / total) * 100) : 0;
    $("progressFill").style.width = pct + "%";
    $("progressLabel").textContent = `Processed ${done} of ${total} search job(s)…`;
  } else if (msg.type === "done") {
    onSearchDone(msg.payload);
  } else if (msg.type === "error") {
    appendLog("ERROR: " + msg.payload, true);
    setRunning(false);
  }
}

function appendLog(text, isErr) {
  const line = document.createElement("div");
  line.className = "log-line" + (isErr ? " err" : "");
  const ts = new Date().toLocaleTimeString();
  line.textContent = `[${ts}] ${text}`;
  $("logBox").appendChild(line);
  $("logBox").scrollTop = $("logBox").scrollHeight;
}

$("clearLogBtn").addEventListener("click", () => {
  $("logBox").innerHTML = "";
});

// ------------------------------------------------------------------
// Run / Stop
// ------------------------------------------------------------------

function setRunning(running) {
  $("runBtn").disabled = running;
  $("stopBtn").disabled = !running;
}

$("searchForm").addEventListener("submit", async (e) => {
  e.preventDefault();

  const criteria = {
    db_bench: $("dbBench").value,
    aliases: $("aliases").value
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean),
    alias_field: $("aliasField").value,
    from_date: inputToDdmmyyyy($("fromDate").value),
    to_date: inputToDdmmyyyy($("toDate").value),
    judge: $("judge").value || null,
    author_judge: $("authJudge").value || null,
    coram: $("coram").value || null,
    case_type: $("caseType").value || null,
    case_no: $("caseNo").value || null,
    case_year: $("caseYear").value || null,
    petitioner_name: $("petName").value || null,
    respondent_name: $("respName").value || null,
    petitioner_adv: $("petAdv").value || null,
    respondent_adv: $("respAdv").value || null,
    report_type: (document.querySelector('input[name="reportType"]:checked') || {}).value || null,
    output_filename: $("outputFilename").value || null,
  };

  if (!criteria.db_bench) {
    alert("Please select a bench.");
    return;
  }
  const hasDates = criteria.from_date && criteria.to_date;
  const hasCaseNoSearch = criteria.case_type && criteria.case_no && criteria.case_year;
  if (!hasDates && !hasCaseNoSearch) {
    alert("Enter a Date of Order range, or fill in Case Type + Case Number + Case Year.");
    return;
  }

  $("logBox").innerHTML = "";
  $("resultsCard").hidden = true;
  $("progressWrap").hidden = false;
  $("progressFill").style.width = "0%";
  $("progressLabel").textContent = "Starting…";
  setRunning(true);

  const res = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(criteria),
  });
  const data = await res.json();

  if (!data.started) {
    appendLog(data.message, true);
    setRunning(false);
  }
});

$("stopBtn").addEventListener("click", async () => {
  $("progressLabel").textContent = "Stopping after the current step…";
  $("stopBtn").disabled = true;
  await fetch("/api/search/stop", { method: "POST" });
});

// ------------------------------------------------------------------
// Results rendering
// ------------------------------------------------------------------

function onSearchDone(payload) {
  setRunning(false);
  $("progressFill").style.width = "100%";
  $("progressLabel").textContent = payload.cancelled
    ? `Stopped — ${payload.case_count} case(s) saved, ${payload.duplicates_skipped} duplicate(s) skipped.`
    : `Done — ${payload.case_count} case(s) saved, ${payload.duplicates_skipped} duplicate(s) skipped.`;

  appendLog(`Output saved to outputs/${payload.output_filename}`);

  $("downloadLink").href = `/outputs/${encodeURIComponent(payload.output_filename)}`;
  $("resultsSummary").textContent =
    `${payload.case_count} unique case(s) found, ${payload.duplicates_skipped} duplicate(s) skipped.`;

  renderResults(payload.cases || []);
  $("resultsCard").hidden = false;
  $("resultsCard").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderResults(cases) {
  const container = $("resultsList");
  container.innerHTML = "";

  cases.forEach((c) => {
    const card = document.createElement("div");
    card.className = "case-card";

    const header = document.createElement("div");
    header.className = "case-card__header";
    header.innerHTML = `
      <div>
        <div class="case-card__title">${escapeHtml(c.case_type)} ${escapeHtml(c.case_no)}/${escapeHtml(c.case_year)}</div>
        <div class="case-card__subtitle">${escapeHtml(c.petitioner)} v/s ${escapeHtml(c.respondent)}</div>
      </div>
      <div class="case-card__chevron">▸</div>
    `;
    header.addEventListener("click", () => card.classList.toggle("open"));

    const body = document.createElement("div");
    body.className = "case-card__body";

    const accordion = document.createElement("div");
    accordion.className = "section-accordion";

    if (c.case_information) {
      accordion.appendChild(sectionItem("Case Information", c.case_information));
    }
    Object.entries(c.sections || {}).forEach(([name, text]) => {
      accordion.appendChild(sectionItem(name, text));
    });

    body.appendChild(accordion);
    card.appendChild(header);
    card.appendChild(body);
    container.appendChild(card);
  });

  if (!cases.length) {
    container.innerHTML = '<p class="hint">No cases matched this search.</p>';
  }
}

function sectionItem(title, text) {
  const item = document.createElement("div");
  item.className = "section-item";

  const header = document.createElement("div");
  header.className = "section-item__header";
  header.innerHTML = `<span>${escapeHtml(title)}</span><span>+</span>`;
  header.addEventListener("click", () => item.classList.toggle("open"));

  const body = document.createElement("div");
  body.className = "section-item__body";
  body.textContent = text;

  item.appendChild(header);
  item.appendChild(body);
  return item;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

// ------------------------------------------------------------------
// Init
// ------------------------------------------------------------------

loadFormOptions();
connectWs();
