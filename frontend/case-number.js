const $ = (id) => document.getElementById(id);

const RESULTS_KEY = "quickSearchResults";

// ------------------------------------------------------------------
// Form options
// ------------------------------------------------------------------

async function loadFormOptions() {
  const res = await fetch("/api/form-options");
  const data = await res.json();

  fillSelect($("dbBench"), data.db_bench, "-- Select --");
  fillSelect($("caseType"), data.case_types, "-- Select --");
  fillSelect(
    $("caseYear"),
    data.case_years.map((y) => ({ value: String(y), label: String(y) })),
    "Select Year"
  );
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
// WebSocket
// ------------------------------------------------------------------

let ws;
let allCases = [];

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
    $("progressLabel").textContent = "Searching…";
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

$("caseNumberForm").addEventListener("submit", async (e) => {
  e.preventDefault();

  const criteria = {
    db_bench: $("dbBench").value,
    case_type: $("caseType").value,
    case_no: $("caseNo").value,
    case_year: $("caseYear").value,
    output_filename: $("outputFilename").value || null,
  };

  if (!criteria.db_bench || !criteria.case_type || !criteria.case_no || !criteria.case_year) {
    alert("Please fill in Bench, Case Type, Case Number, and Case Year.");
    return;
  }

  $("logBox").innerHTML = "";
  $("resultsCard").hidden = true;
  $("progressWrap").hidden = false;
  $("progressFill").style.width = "0%";
  $("progressLabel").textContent = "Starting…";
  setRunning(true);

  const res = await fetch("/api/case-number-search", {
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
    ? "Stopped."
    : payload.case_count
      ? "Done — case found."
      : "Done — no matching case found.";

  appendLog(`Output saved to outputs/${payload.output_filename}`);

  const downloadHref = `/outputs/${encodeURIComponent(payload.output_filename)}`;
  $("downloadLink").href = downloadHref;
  const summaryText = payload.case_count
    ? `${payload.case_count} case(s) found.`
    : "No case matched that Case Type / Number / Year.";
  $("resultsSummary").textContent = summaryText;

  allCases = payload.cases || [];
  renderResults(allCases);
  $("resultsCard").hidden = false;
  $("resultsCard").scrollIntoView({ behavior: "smooth", block: "start" });

  // Persist to sessionStorage
  try {
    sessionStorage.setItem(RESULTS_KEY, JSON.stringify({
      cases: allCases,
      summary: summaryText,
      downloadHref: downloadHref,
      filename: payload.output_filename,
    }));
  } catch (e) {
    console.warn("Could not save results to sessionStorage:", e);
  }
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
      <div class="case-card__chevron"><i data-lucide="chevron-right"></i></div>
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

  lucide.createIcons();
  if (!cases.length) {
    container.innerHTML = '<p class="hint">No case matched that Case Type / Number / Year.</p>';
  }
  lucide.createIcons();
}

function sectionItem(title, text) {
  const item = document.createElement("div");
  item.className = "section-item";

  const header = document.createElement("div");
  header.className = "section-item__header";
  header.innerHTML = `<span>${escapeHtml(title)}</span><span class="section-item__chevron"><i data-lucide="chevron-right"></i></span>`;
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
// Download: CSV and Markdown (client-side)
// ------------------------------------------------------------------

function downloadCsv() {
  if (!allCases.length) return;
  const headers = ["Case Type", "Case No", "Case Year", "Petitioner", "Respondent"];
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const rows = allCases.map((c) => [
    c.case_type, c.case_no, c.case_year, c.petitioner, c.respondent
  ].map(esc).join(","));
  const csv = [headers.join(","), ...rows].join("\r\n");
  triggerDownload(csv, "case.csv", "text/csv;charset=utf-8;");
}

function downloadMarkdown() {
  if (!allCases.length) return;
  const lines = ["# Case Search Results", "", `**${allCases.length} case(s) found**`, "", "---", ""];
  allCases.forEach((c, i) => {
    lines.push(`## ${i + 1}. ${c.case_type || ""} ${c.case_no || ""}/${c.case_year || ""}`);
    lines.push(`**${c.petitioner || "—"}** v/s **${c.respondent || "—"}**`);
    lines.push("");
    if (c.case_information) {
      lines.push("### Case Information");
      lines.push(c.case_information.trim());
      lines.push("");
    }
    Object.entries(c.sections || {}).forEach(([name, text]) => {
      lines.push(`### ${name}`);
      lines.push(text.trim());
      lines.push("");
    });
    lines.push("---", "");
  });
  triggerDownload(lines.join("\n"), "case.md", "text/markdown;charset=utf-8;");
}

function triggerDownload(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

$("downloadCsvBtn").addEventListener("click", downloadCsv);
$("downloadMdBtn").addEventListener("click", downloadMarkdown);

// -- Clear results button --
$("clearResultsBtn").addEventListener("click", () => {
  allCases = [];
  $("resultsCard").hidden = true;
  try { sessionStorage.removeItem(RESULTS_KEY); } catch(e) {}
});

// ------------------------------------------------------------------
// Restore persisted results
// ------------------------------------------------------------------

function restorePersistedResults() {
  try {
    const stored = sessionStorage.getItem(RESULTS_KEY);
    if (!stored) return;
    const data = JSON.parse(stored);
    if (!data || !data.cases || !data.cases.length) return;

    allCases = data.cases;
    $("downloadLink").href = data.downloadHref || "#";
    $("resultsSummary").textContent = (data.summary || "") + " (restored from this session)";
    renderResults(allCases);
    $("resultsCard").hidden = false;
  } catch (e) {
    console.warn("Could not restore persisted results:", e);
  }
}

// ------------------------------------------------------------------
// Init
// ------------------------------------------------------------------

lucide.createIcons();
loadFormOptions();
connectWs();
restorePersistedResults();

// Log card folding
const logCardHeader = document.getElementById('logCardHeader');
const logCard = document.getElementById('logCard');
if (logCardHeader && logCard) {
  logCardHeader.addEventListener('click', (e) => {
    if (e.target.closest('#clearLogBtn')) return;
    logCard.classList.toggle('open');
  });
}
