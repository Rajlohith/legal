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

function appendLog(text, isErr, ts) {
  const line = document.createElement("div");
  line.className = "log-line" + (isErr ? " err" : "");
  const displayTs = ts || new Date().toLocaleTimeString();
  line.textContent = `[${displayTs}] ${text}`;
  $("logBox").appendChild(line);
  $("logBox").scrollTop = $("logBox").scrollHeight;
}

async function loadPersistedLog() {
  try {
    const res = await fetch("/api/logs/case_number");
    if (!res.ok) return;
    const data = await res.json();
    if (!Array.isArray(data.entries)) return;
    for (const entry of data.entries) {
      appendLog(entry.text, entry.isErr, entry.ts);
    }
  } catch (e) {
    // Server may not support this endpoint yet — fail silently.
  }
}

$("clearLogBtn").addEventListener("click", async () => {
  $("logBox").innerHTML = "";
  try { await fetch("/api/logs/case_number", { method: "DELETE" }); } catch (_) {}
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
  const words = text ? text.trim().split(/\s+/).length : 0;
  const badge = words > 5 ? `<span class="section-data-badge">${words} words</span>` : '';
  header.innerHTML = `<span>${escapeHtml(title)}</span>${badge}<span class="section-item__chevron"><i data-lucide="chevron-right"></i></span>`;
  header.addEventListener("click", () => item.classList.toggle("open"));

  const body = document.createElement("div");
  body.className = "section-item__body";
  body.innerHTML = renderSectionHTML(title, text);

  item.appendChild(header);
  item.appendChild(body);
  return item;
}

// ------------------------------------------------------------------
// Rich section content rendering (shared with case-number page)
// ------------------------------------------------------------------

const CASE_INFO_FIELDS = [
  "Status","Case Number","Classification","Date of Filing","Petitioner",
  "Petitioner Advocate","Respondent","Respondent Advocate","Filing No\\.",
  "Judge","Last Posted For","Date of Decision","Last Action Taken",
  "Next Hearing Date","Case Type","Case Year","Case No",
];

function renderSectionHTML(title, text) {
  if (!text || !text.trim()) {
    return '<p class="hint" style="margin:0;font-size:13px;color:var(--text-muted);">No data recorded.</p>';
  }
  switch (title) {
    case "Case Information": return renderCaseInformation(text);
    case "Party Information": return renderPartyInformation(text);
    case "Prayer Information": return renderPrayerInformation(text);
    default: return renderNarrative(text);
  }
}

function renderNarrative(text) {
  return `<pre class="section-narrative">${escapeHtml(text.trim())}</pre>`;
}

function renderCaseInformation(text) {
  const fieldPattern = new RegExp(
    "(" + CASE_INFO_FIELDS.join("|") + "):\\s*",
    "g"
  );
  const cleaned = text.trim();
  const matches = [...cleaned.matchAll(fieldPattern)];
  if (!matches.length) return renderNarrative(text);

  const pairs = [];
  for (let i = 0; i < matches.length; i++) {
    const key = matches[i][1];
    const start = matches[i].index + matches[i][0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index : cleaned.length;
    const val = cleaned.slice(start, end).trim();
    pairs.push([key, val]);
  }

  let html = '<table class="section-fields">';
  pairs.forEach(([k, v]) => {
    html += `<tr><td class="field-key">${escapeHtml(k)}</td><td class="field-val">${escapeHtml(v)}</td></tr>`;
  });
  html += "</table>";
  return html;
}

function renderPrayerInformation(text) {
  const cleaned = text.trim().replace(/^Prayer Details:\s*/i, "");
  return `<pre class="section-narrative">${escapeHtml(cleaned)}</pre>`;
}

function renderPartyInformation(text) {
  const blocks = [];
  const blockRe = /(Petitioner Details|Respondent Details):/gi;
  const bMatches = [...text.matchAll(blockRe)];

  if (!bMatches.length) return renderNarrative(text);

  bMatches.forEach((m, i) => {
    const blockTitle = m[1];
    const start = m.index + m[0].length;
    const end = i + 1 < bMatches.length ? bMatches[i + 1].index : text.length;
    const blockText = text.slice(start, end).trim();
    blocks.push({ title: blockTitle, text: blockText });
  });

  let html = "";
  blocks.forEach((block) => {
    html += `<div class="party-block-title">${escapeHtml(block.title)}</div>`;
    html += renderPartyBlock(block.text);
  });
  return html;
}

function renderPartyBlock(text) {
  const entryRe = /\b(\d{1,2})\s+(THE |SRI |SMT |MR\.|MS\.|DR\.|M\/S\s)/gi;
  const entries = [...text.matchAll(entryRe)];

  if (entries.length > 1) {
    const rows = [];
    for (let i = 0; i < entries.length; i++) {
      const num = entries[i][1];
      const start = entries[i].index;
      const end = i + 1 < entries.length ? entries[i + 1].index : text.length;
      const content = text.slice(start + entries[i][0].length - entries[i][2].length, end).trim();
      const advMatch = content.match(/Advocate:\s*(.*?)(?=\s+\d+\s+(?:THE|SRI|SMT|MR\.|MS\.|M\/S)|$)/i);
      const advName = advMatch ? advMatch[1].trim() : "";
      const address = advMatch ? content.slice(0, advMatch.index).trim() : content;
      rows.push({ num, address, advocate: advName });
    }

    let html = '<table class="party-table"><thead><tr><th>#</th><th>Party</th><th>Advocate</th></tr></thead><tbody>';
    rows.forEach((r) => {
      html += `<tr><td>${escapeHtml(r.num)}</td><td>${escapeHtml(r.address)}</td><td>${escapeHtml(r.advocate)}</td></tr>`;
    });
    html += "</tbody></table>";
    return html;
  }

  return renderNarrative(text);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

// ------------------------------------------------------------------
// Download: PDF and Markdown (client-side)
// ------------------------------------------------------------------

function downloadPdf() {
  if (!allCases.length) return;
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });
  const pageW = doc.internal.pageSize.getWidth();
  const margin = 14;
  const contentW = pageW - margin * 2;
  let y = margin;

  const addPageIfNeeded = (needed) => {
    if (y + needed > doc.internal.pageSize.getHeight() - margin) {
      doc.addPage();
      y = margin;
    }
  };

  // Title
  doc.setFontSize(18);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(31, 58, 95);
  doc.text("Karnataka Judiciary — Quick Search Results", margin, y);
  y += 8;

  doc.setFontSize(9);
  doc.setFont("helvetica", "normal");
  doc.setTextColor(107, 106, 92);
  doc.text(`Generated: ${new Date().toLocaleString()}   |   ${allCases.length} case(s)`, margin, y);
  y += 8;

  doc.setDrawColor(214, 210, 194);
  doc.line(margin, y, pageW - margin, y);
  y += 6;

  allCases.forEach((c, idx) => {
    addPageIfNeeded(20);

    doc.setFillColor(31, 58, 95);
    doc.rect(margin, y - 4, contentW, 8, "F");
    doc.setFontSize(11);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(255, 255, 255);
    const caseTitle = `${idx + 1}. ${c.case_type || ""} ${c.case_no || ""}/${c.case_year || ""}`;
    doc.text(caseTitle, margin + 2, y);
    y += 5;

    doc.setFontSize(9);
    doc.setFont("helvetica", "normal");
    doc.setTextColor(255, 255, 255);
    doc.text(`${c.petitioner || "—"} v/s ${c.respondent || "—"}`, margin + 2, y);
    y += 7;

    const allSections = [];
    if (c.case_information) allSections.push(["Case Information", c.case_information]);
    Object.entries(c.sections || {}).forEach(([name, text]) => {
      if (text && text.trim()) allSections.push([name, text]);
    });

    allSections.forEach(([secName, secText]) => {
      addPageIfNeeded(12);

      doc.setFontSize(9);
      doc.setFont("helvetica", "bold");
      doc.setTextColor(31, 58, 95);
      doc.text(secName, margin, y);
      doc.setDrawColor(31, 58, 95);
      doc.line(margin, y + 1, pageW - margin, y + 1);
      y += 6;

      const bodyText = secText.trim();
      doc.setFontSize(8.5);
      doc.setFont("helvetica", "normal");
      doc.setTextColor(27, 27, 23);
      const lines = doc.splitTextToSize(bodyText, contentW - 4);
      lines.forEach((line) => {
        addPageIfNeeded(4.5);
        doc.text(line, margin + 2, y);
        y += 4.5;
      });
      y += 3;
    });

    doc.setDrawColor(214, 210, 194);
    doc.setLineDash([2, 2]);
    addPageIfNeeded(6);
    doc.line(margin, y, pageW - margin, y);
    doc.setLineDash([]);
    y += 6;
  });

  doc.save("case.pdf");
}

function downloadMarkdown() {
  if (!allCases.length) return;
  const lines = [
    "# Karnataka Judiciary — Quick Search Results",
    "",
    `**Generated:** ${new Date().toLocaleString()}`,
    "",
    `**Total cases:** ${allCases.length}`,
    "",
    "---",
    "",
  ];
  allCases.forEach((c, i) => {
    lines.push(`## ${i + 1}. ${c.case_type || ""} ${c.case_no || ""}/${c.case_year || ""}`);
    lines.push("");
    lines.push(`| Field | Value |`);
    lines.push(`|-------|-------|`);
    lines.push(`| **Petitioner** | ${c.petitioner || "—"} |`);
    lines.push(`| **Respondent** | ${c.respondent || "—"} |`);
    lines.push(`| **Case Type** | ${c.case_type || "—"} |`);
    lines.push(`| **Case No / Year** | ${c.case_no || "—"} / ${c.case_year || "—"} |`);
    lines.push("");
    if (c.case_information) {
      lines.push("### Case Information");
      lines.push("");
      lines.push(c.case_information.trim());
      lines.push("");
    }
    const sections = Object.entries(c.sections || {});
    sections.forEach(([name, text]) => {
      if (!text || !text.trim()) return;
      lines.push(`### ${name}`);
      lines.push("");
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

$("downloadPdfBtn").addEventListener("click", downloadPdf);
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

// Prefill from the AI Assistant's "Edit in form" button.
function applyAssistantPrefill() {
  let f;
  try {
    const raw = sessionStorage.getItem("assistantPrefill");
    if (!raw) return;
    sessionStorage.removeItem("assistantPrefill");
    f = JSON.parse(raw);
  } catch (e) { return; }
  if (!f) return;
  const set = (id, v) => { if (v != null && $(id)) $(id).value = v; };
  set("dbBench", f.db_bench);
  set("caseType", f.case_type);
  set("caseNo", f.case_no);
  set("caseYear", f.case_year);
}

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
loadFormOptions().then(applyAssistantPrefill);
connectWs();
restorePersistedResults();
loadPersistedLog();

// Log card folding
const logCardHeader = document.getElementById('logCardHeader');
const logCard = document.getElementById('logCard');
if (logCardHeader && logCard) {
  logCardHeader.addEventListener('click', (e) => {
    if (e.target.closest('#clearLogBtn')) return;
    logCard.classList.toggle('open');
  });
}
