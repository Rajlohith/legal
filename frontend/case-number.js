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

  renderSectionsChecklist(data.sections || []);
}

function renderSectionsChecklist(sectionNames) {
  const container = $("sectionsList");
  if (!container) return;
  container.innerHTML = "";
  sectionNames.forEach((name) => {
    const label = document.createElement("label");
    label.className = "checkbox-row";
    label.innerHTML = `<input type="checkbox" value="${escapeHtml(name)}" checked><span>${escapeHtml(name)}</span>`;
    container.appendChild(label);
  });
}

function getIncludedSections() {
  const container = $("sectionsList");
  if (!container) return null;
  const boxes = [...container.querySelectorAll('input[type="checkbox"]')];
  if (!boxes.length) return null;
  const checked = boxes.filter((b) => b.checked).map((b) => b.value);
  return checked.length === boxes.length ? null : checked;
}

const sectionsSelectAllBtn2 = $("sectionsSelectAll");
if (sectionsSelectAllBtn2) {
  sectionsSelectAllBtn2.addEventListener("click", () => {
    $("sectionsList").querySelectorAll('input[type="checkbox"]').forEach((b) => { b.checked = true; });
  });
}
const sectionsSelectNoneBtn2 = $("sectionsSelectNone");
if (sectionsSelectNoneBtn2) {
  sectionsSelectNoneBtn2.addEventListener("click", () => {
    $("sectionsList").querySelectorAll('input[type="checkbox"]').forEach((b) => { b.checked = false; });
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
    included_sections: getIncludedSections(),
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
  const isZip = payload.output_filename.toLowerCase().endsWith(".zip");
  $("downloadLink").innerHTML = isZip
    ? '<i data-lucide="folder-archive"></i> Excel + Judgment PDFs (.zip)'
    : '<i data-lucide="file-spreadsheet"></i> Excel';
  if (window.lucide) lucide.createIcons();
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

function collectSections(c) {
  const entries = [];
  if (c.case_info_structured || c.case_information) {
    entries.push(["Case Information", c.case_information || "", c.case_info_structured || null]);
  }
  const names = new Set([
    ...Object.keys(c.sections || {}),
    ...Object.keys(c.sections_structured || {}),
  ]);
  names.forEach((name) => {
    const text = (c.sections || {})[name] || "";
    const structured = (c.sections_structured || {})[name] || null;
    if (text || structured) entries.push([name, text, structured]);
  });
  return entries;
}

function tableColumns(table) {
  const cols = [];
  (table.headers || []).forEach((h) => { if (h && !cols.includes(h)) cols.push(h); });
  (table.rows || []).forEach((row) => {
    Object.keys(row).forEach((k) => { if (!cols.includes(k)) cols.push(k); });
  });
  return cols;
}

function sectionRowCount(structured) {
  if (!structured) return 0;
  if (structured.kind === "tables") {
    return (structured.tables || []).reduce((sum, t) => sum + (t.rows || []).length, 0);
  }
  if (structured.kind === "fields") return (structured.pairs || []).length;
  return 0;
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
        ${c.judgment_pdf ? '<span class="case-card__badge" title="' + escapeHtml(c.judgment_pdf) + '"><i data-lucide="file-text"></i> Judgment PDF in download</span>' : ""}
      </div>
      <div class="case-card__chevron"><i data-lucide="chevron-right"></i></div>
    `;
    header.addEventListener("click", () => card.classList.toggle("open"));

    const body = document.createElement("div");
    body.className = "case-card__body";

    const accordion = document.createElement("div");
    accordion.className = "section-accordion";

    collectSections(c).forEach(([name, text, structured]) => {
      accordion.appendChild(sectionItem(name, text, structured));
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

function sectionItem(title, text, structured) {
  const item = document.createElement("div");
  item.className = "section-item";

  const header = document.createElement("div");
  header.className = "section-item__header";

  let badge = "";
  const rowCount = sectionRowCount(structured);
  if (rowCount) {
    badge = `<span class="section-data-badge">${rowCount} row${rowCount !== 1 ? "s" : ""}</span>`;
  } else {
    const narrativeText = structured && structured.kind === "narrative" ? structured.text : text;
    const words = narrativeText ? narrativeText.trim().split(/\s+/).filter(Boolean).length : 0;
    if (words > 5) badge = `<span class="section-data-badge">${words} words</span>`;
  }

  header.innerHTML = `<span>${escapeHtml(title)}</span>${badge}<span class="section-item__chevron"><i data-lucide="chevron-right"></i></span>`;
  header.addEventListener("click", () => item.classList.toggle("open"));

  const body = document.createElement("div");
  body.className = "section-item__body";
  body.innerHTML = renderSectionHTML(text, structured);

  item.appendChild(header);
  item.appendChild(body);
  return item;
}

// ------------------------------------------------------------------
// Rich section content rendering -- driven entirely by the structure
// the backend read from the page's own HTML (see
// scraper/section_structure.py). No section-name-specific parsing
// here: a "tables" section renders as real tables using whatever
// columns it actually has, a "fields" section as a two-column table,
// and anything else as plain narrative text.
// ------------------------------------------------------------------

function renderSectionHTML(text, structured) {
  if (!structured) {
    if (!text || !text.trim()) {
      return '<p class="hint" style="margin:0;font-size:13px;color:var(--text-muted);">No data recorded.</p>';
    }
    return renderNarrative(text);
  }
  if (structured.kind === "tables") {
    const html = (structured.tables || []).map(renderStructuredTable).join("");
    return html || '<p class="hint" style="margin:0;font-size:13px;color:var(--text-muted);">No data recorded.</p>';
  }
  if (structured.kind === "fields") {
    return renderFieldsTable(structured.pairs || []);
  }
  if (structured.kind === "narrative") {
    return renderNarrative(structured.text || "");
  }
  return '<p class="hint" style="margin:0;font-size:13px;color:var(--text-muted);">No data recorded.</p>';
}

function renderNarrative(text) {
  if (!text || !text.trim()) {
    return '<p class="hint" style="margin:0;font-size:13px;color:var(--text-muted);">No data recorded.</p>';
  }
  return `<pre class="section-narrative">${escapeHtml(text.trim())}</pre>`;
}

function renderFieldsTable(pairs) {
  if (!pairs.length) return '<p class="hint" style="margin:0;font-size:13px;color:var(--text-muted);">No data recorded.</p>';
  let html = '<table class="section-fields">';
  pairs.forEach(([k, v]) => {
    html += `<tr><td class="field-key">${escapeHtml(k)}</td><td class="field-val">${escapeHtml(v).replace(/\n/g, "<br>")}</td></tr>`;
  });
  html += "</table>";
  return html;
}

function renderStructuredTable(table) {
  const cols = tableColumns(table);
  if (!cols.length || !(table.rows || []).length) return "";
  let html = "";
  if (table.title) html += `<div class="party-block-title">${escapeHtml(table.title)}</div>`;
  html += '<table class="party-table"><thead><tr>' + cols.map((h) => `<th>${escapeHtml(h)}</th>`).join("") + "</tr></thead><tbody>";
  (table.rows || []).forEach((row) => {
    html += "<tr>" + cols.map((h) => `<td>${escapeHtml(row[h] || "").replace(/\n/g, "<br>")}</td>`).join("") + "</tr>";
  });
  html += "</tbody></table>";
  return html;
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
  const pageH = doc.internal.pageSize.getHeight();
  const margin = 14;
  const contentW = pageW - margin * 2;
  let y = margin;

  const addPageIfNeeded = (needed) => {
    if (y + needed > pageH - margin) {
      doc.addPage();
      y = margin;
    }
  };

  // Title
  doc.setFontSize(18);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(31, 58, 95);
  doc.text("Iudicium — Quick Search Results", margin, y);
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

    if (c.judgment_pdf) {
      addPageIfNeeded(6);
      doc.setFontSize(8.5);
      doc.setFont("helvetica", "italic");
      doc.setTextColor(140, 109, 47);
      doc.text(`Judgment PDF: pdfs/${c.judgment_pdf}  (included in the Excel .zip download)`, margin, y);
      doc.setFont("helvetica", "normal");
      y += 6;
    }

    collectSections(c).forEach(([secName, secText, structured]) => {
      addPageIfNeeded(12);

      doc.setFontSize(9);
      doc.setFont("helvetica", "bold");
      doc.setTextColor(31, 58, 95);
      doc.text(secName, margin, y);
      doc.setDrawColor(31, 58, 95);
      doc.line(margin, y + 1, pageW - margin, y + 1);
      y += 5;

      if (structured && structured.kind === "tables" && structured.tables.length) {
        structured.tables.forEach((table) => {
          if (table.title) {
            addPageIfNeeded(6);
            doc.setFontSize(8.5);
            doc.setFont("helvetica", "bolditalic");
            doc.setTextColor(140, 109, 47);
            doc.text(table.title, margin, y);
            doc.setFont("helvetica", "normal");
            y += 4;
          }
          const cols = tableColumns(table);
          const body = (table.rows || []).map((row) => cols.map((h) => String(row[h] || "")));
          doc.autoTable({
            startY: y,
            head: [cols],
            body,
            margin: { left: margin, right: margin },
            styles: { fontSize: 7.5, cellPadding: 1.5, textColor: [27, 27, 23], overflow: "linebreak" },
            headStyles: { fillColor: [31, 58, 95], textColor: 255, fontStyle: "bold" },
            alternateRowStyles: { fillColor: [246, 244, 238] },
          });
          y = doc.lastAutoTable.finalY + 4;
        });
      } else if (structured && structured.kind === "fields" && structured.pairs.length) {
        doc.autoTable({
          startY: y,
          body: structured.pairs.map(([k, v]) => [k, v]),
          margin: { left: margin, right: margin },
          styles: { fontSize: 7.5, cellPadding: 1.5, textColor: [27, 27, 23], overflow: "linebreak" },
          columnStyles: { 0: { fontStyle: "bold", cellWidth: 42, textColor: [31, 58, 95] } },
          theme: "grid",
        });
        y = doc.lastAutoTable.finalY + 4;
      } else {
        const bodyText = (structured && structured.text ? structured.text : secText || "").trim();
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
      }
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
  const mdEscape = (v) => String(v ?? "").replace(/\|/g, "\\|").replace(/\r?\n/g, "<br>");

  const lines = [
    "# Iudicium — Quick Search Results",
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
    lines.push(`**${c.petitioner || "—"}** v/s **${c.respondent || "—"}**`);
    lines.push("");
    if (c.judgment_pdf) {
      lines.push(`**Judgment PDF:** [${c.judgment_pdf}](pdfs/${c.judgment_pdf}) *(inside the downloaded .zip)*`);
      lines.push("");
    }

    collectSections(c).forEach(([secName, secText, structured]) => {
      lines.push(`### ${secName}`);
      lines.push("");

      if (structured && structured.kind === "tables" && structured.tables.length) {
        structured.tables.forEach((table) => {
          if (table.title) {
            lines.push(`**${table.title}**`);
            lines.push("");
          }
          const cols = tableColumns(table);
          if (cols.length && (table.rows || []).length) {
            lines.push(`| ${cols.map(mdEscape).join(" | ")} |`);
            lines.push(`|${cols.map(() => "---").join("|")}|`);
            table.rows.forEach((row) => {
              lines.push(`| ${cols.map((h) => mdEscape(row[h])).join(" | ")} |`);
            });
            lines.push("");
          }
        });
      } else if (structured && structured.kind === "fields" && structured.pairs.length) {
        lines.push("| Field | Value |");
        lines.push("|-------|-------|");
        structured.pairs.forEach(([k, v]) => {
          lines.push(`| **${mdEscape(k)}** | ${mdEscape(v)} |`);
        });
        lines.push("");
      } else {
        const text = (structured && structured.text ? structured.text : secText || "").trim();
        if (text) {
          lines.push(text);
          lines.push("");
        }
      }
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
    const isZip = (data.filename || "").toLowerCase().endsWith(".zip");
    $("downloadLink").innerHTML = isZip
      ? '<i data-lucide="folder-archive"></i> Excel + Judgment PDFs (.zip)'
      : '<i data-lucide="file-spreadsheet"></i> Excel';
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
