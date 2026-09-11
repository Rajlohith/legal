const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------
// Session storage keys for result persistence
// ------------------------------------------------------------------

const RESULTS_KEY = "detailedSearchResults";

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

  renderSectionsChecklist(data.sections || []);
}

// ------------------------------------------------------------------
// Sections to Include -- which sections get scraped/shown/exported.
// Populated dynamically from the same list config.py's SECTION_ORDER
// defines, so a new section added server-side just shows up here too.
// ------------------------------------------------------------------

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
  // All checked (the default) -> send null so the backend applies no
  // filter at all, rather than a redundant "everything" list.
  return checked.length === boxes.length ? null : checked;
}

const sectionsSelectAllBtn = $("sectionsSelectAll");
if (sectionsSelectAllBtn) {
  sectionsSelectAllBtn.addEventListener("click", () => {
    $("sectionsList").querySelectorAll('input[type="checkbox"]').forEach((b) => { b.checked = true; });
  });
}
const sectionsSelectNoneBtn = $("sectionsSelectNone");
if (sectionsSelectNoneBtn) {
  sectionsSelectNoneBtn.addEventListener("click", () => {
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
  } else if (msg.type === "case_progress") {
    const { done, total, label } = msg.payload;
    $("progressWrap").hidden = false;
    const pct = total ? Math.round((done / total) * 100) : 0;
    $("progressFill").style.width = pct + "%";
    $("progressLabel").textContent =
      `Extracting case ${done} of ${total}` + (label ? ` for '${label}'` : "") + "…";
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
    const res = await fetch("/api/logs/search");
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
  try { await fetch("/api/logs/search", { method: "DELETE" }); } catch (_) {}
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
    included_sections: getIncludedSections(),
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
// Results rendering + filters/sort
// ------------------------------------------------------------------

let allCases = [];
const filterState = {
  search: "",
  caseTypes: new Set(),
  caseYears: new Set(),
  hasJudgment: false,
  hasOrders: false,
  petitioner: "",
  respondent: "",
};
let sortMode = "year_desc";

function onSearchDone(payload) {
  setRunning(false);
  $("progressFill").style.width = "100%";
  $("progressLabel").textContent = payload.cancelled
    ? `Stopped — ${payload.case_count} case(s) saved, ${payload.duplicates_skipped} duplicate(s) skipped.`
    : `Done — ${payload.case_count} case(s) saved, ${payload.duplicates_skipped} duplicate(s) skipped.`;

  appendLog(`Output saved to outputs/${payload.output_filename}`);

  const downloadHref = `/outputs/${encodeURIComponent(payload.output_filename)}`;
  $("downloadLink").href = downloadHref;
  const isZip = payload.output_filename.toLowerCase().endsWith(".zip");
  $("downloadLink").innerHTML = isZip
    ? '<i data-lucide="folder-archive"></i> Excel + Judgment PDFs (.zip)'
    : '<i data-lucide="file-spreadsheet"></i> Excel';
  if (window.lucide) lucide.createIcons();
  const summaryText = `${payload.case_count} unique case(s) found, ${payload.duplicates_skipped} duplicate(s) skipped.`;
  $("resultsSummary").textContent = summaryText;

  allCases = (payload.cases || []).map((c) => ({
    ...c,
    _sectionCount: sectionCount(c),
  }));

  resetFilterState();
  buildFilterOptions(allCases);
  renderFilteredResults();

  $("resultsCard").hidden = false;
  $("resultsCard").scrollIntoView({ behavior: "smooth", block: "start" });

  // Persist to sessionStorage for the duration of the browser session
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

function resetFilterState() {
  filterState.search = "";
  filterState.caseTypes.clear();
  filterState.caseYears.clear();
  filterState.hasJudgment = false;
  filterState.hasOrders = false;
  filterState.petitioner = "";
  filterState.respondent = "";
  $("filterSearch").value = "";
  $("filterHasJudgment").checked = false;
  $("filterHasOrders").checked = false;
  $("filterPetitioner").value = "";
  $("filterRespondent").value = "";
  $("sortSelect").value = "year_desc";
}

function sectionCount(c) {
  let count = c.case_information ? 1 : 0;
  count += Object.keys(c.sections || {}).length;
  return count;
}

// -- Build filter checkboxes from the actual result set --

function buildFilterOptions(cases) {
  const typeCounts = new Map();
  const yearCounts = new Map();

  cases.forEach((c) => {
    const type = c.case_type || "Unknown";
    const year = c.case_year || "Unknown";
    typeCounts.set(type, (typeCounts.get(type) || 0) + 1);
    yearCounts.set(year, (yearCounts.get(year) || 0) + 1);
  });

  renderCheckboxGroup(
    $("filterCaseType"),
    [...typeCounts.entries()].sort((a, b) => b[1] - a[1]),
    filterState.caseTypes,
    onFilterChange
  );
  renderCheckboxGroup(
    $("filterCaseYear"),
    [...yearCounts.entries()].sort((a, b) => String(b[0]).localeCompare(String(a[0]))),
    filterState.caseYears,
    onFilterChange
  );
}

function renderCheckboxGroup(container, entries, stateSet, onChange) {
  container.innerHTML = "";
  entries.forEach(([value, count]) => {
    const label = document.createElement("label");
    label.className = "checkbox-row";
    label.innerHTML = `
      <input type="checkbox" ${stateSet.has(value) ? "checked" : ""}>
      <span>${escapeHtml(value)}</span>
      <span class="count">${count}</span>
    `;
    label.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) stateSet.add(value);
      else stateSet.delete(value);
      onChange();
    });
    container.appendChild(label);
  });
  if (!entries.length) {
    container.innerHTML = '<p class="hint" style="margin:0;">None</p>';
  }
}

// -- Wire up controls --

$("filterSearch").addEventListener("input", (e) => {
  filterState.search = e.target.value.trim().toLowerCase();
  renderFilteredResults();
});
$("filterHasJudgment").addEventListener("change", (e) => {
  filterState.hasJudgment = e.target.checked;
  renderFilteredResults();
});
$("filterHasOrders").addEventListener("change", (e) => {
  filterState.hasOrders = e.target.checked;
  renderFilteredResults();
});
$("filterPetitioner").addEventListener("input", (e) => {
  filterState.petitioner = e.target.value.trim().toLowerCase();
  renderFilteredResults();
});
$("filterRespondent").addEventListener("input", (e) => {
  filterState.respondent = e.target.value.trim().toLowerCase();
  renderFilteredResults();
});
$("sortSelect").addEventListener("change", (e) => {
  sortMode = e.target.value;
  renderFilteredResults();
});
$("clearFiltersBtn").addEventListener("click", () => {
  resetFilterState();
  buildFilterOptions(allCases);
  renderFilteredResults();
});

// -- Clear results button --
$("clearResultsBtn").addEventListener("click", () => {
  allCases = [];
  $("resultsCard").hidden = true;
  try { sessionStorage.removeItem(RESULTS_KEY); } catch(e) {}
});

function onFilterChange() {
  renderFilteredResults();
}

// -- Apply filters + sort, then render --

function renderFilteredResults() {
  let cases = allCases.filter((c) => {
    if (filterState.caseTypes.size && !filterState.caseTypes.has(c.case_type || "Unknown")) {
      return false;
    }
    if (filterState.caseYears.size && !filterState.caseYears.has(c.case_year || "Unknown")) {
      return false;
    }
    if (filterState.hasJudgment && !(c.sections || {})["Judgment Information"]) {
      return false;
    }
    if (filterState.hasOrders && !(c.sections || {})["Daily Orders Information"]) {
      return false;
    }
    // Petitioner / respondent text filters
    if (filterState.petitioner && !(c.petitioner || "").toLowerCase().includes(filterState.petitioner)) return false;
    if (filterState.respondent && !(c.respondent || "").toLowerCase().includes(filterState.respondent)) return false;
    // General search
    if (filterState.search) {
      const haystack = [
        c.case_type, c.case_no, c.case_year, c.petitioner, c.respondent,
      ].join(" ").toLowerCase();
      if (!haystack.includes(filterState.search)) return false;
    }
    return true;
  });

  cases = sortCases(cases, sortMode);

  renderActiveChips();
  $("filteredCount").textContent = `Showing ${cases.length} of ${allCases.length} case(s)`;
  renderResults(cases);
  lucide.createIcons();
}

function sortCases(cases, mode) {
  const copy = [...cases];
  const byYear = (c) => parseInt(c.case_year, 10) || 0;
  const byCaseNo = (c) => parseInt(c.case_no, 10) || 0;

  switch (mode) {
    case "year_asc":
      return copy.sort((a, b) => byYear(a) - byYear(b));
    case "case_no_asc":
      return copy.sort((a, b) => byCaseNo(a) - byCaseNo(b));
    case "case_no_desc":
      return copy.sort((a, b) => byCaseNo(b) - byCaseNo(a));
    case "petitioner_az":
      return copy.sort((a, b) => (a.petitioner || "").localeCompare(b.petitioner || ""));
    case "most_data":
      return copy.sort((a, b) => b._sectionCount - a._sectionCount);
    case "year_desc":
    default:
      return copy.sort((a, b) => byYear(b) - byYear(a));
  }
}

function renderActiveChips() {
  const container = $("activeChips");
  container.innerHTML = "";
  const chips = [];

  filterState.caseTypes.forEach((v) => chips.push({ label: `Type: ${v}`, clear: () => filterState.caseTypes.delete(v) }));
  filterState.caseYears.forEach((v) => chips.push({ label: `Year: ${v}`, clear: () => filterState.caseYears.delete(v) }));
  if (filterState.hasJudgment) chips.push({ label: "Has Judgment", clear: () => { filterState.hasJudgment = false; $("filterHasJudgment").checked = false; } });
  if (filterState.hasOrders) chips.push({ label: "Has Daily Orders", clear: () => { filterState.hasOrders = false; $("filterHasOrders").checked = false; } });
  if (filterState.petitioner) chips.push({ label: `Petitioner: "${filterState.petitioner}"`, clear: () => { filterState.petitioner = ""; $("filterPetitioner").value = ""; } });
  if (filterState.respondent) chips.push({ label: `Respondent: "${filterState.respondent}"`, clear: () => { filterState.respondent = ""; $("filterRespondent").value = ""; } });
  if (filterState.search) chips.push({ label: `"${filterState.search}"`, clear: () => { filterState.search = ""; $("filterSearch").value = ""; } });

  chips.forEach((chip) => {
    const el = document.createElement("span");
    el.className = "chip";
    el.innerHTML = `${escapeHtml(chip.label)} <button type="button"><i data-lucide="x"></i></button>`;
    el.querySelector("button").addEventListener("click", () => {
      chip.clear();
      buildFilterOptions(allCases);
      renderFilteredResults();
    });
    container.appendChild(el);
  });
}

function collectSections(c) {
  // One ordered list of [name, flatText, structured] combining Case
  // Information with every other section -- flatText is kept only as
  // a fallback for cached/older results that predate structured data.
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
  // The site's own column order first, then any extra keys a row
  // carries that weren't in the header (e.g. a folded-in "Notes" line).
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
        <span class="case-card__badge">${c._sectionCount} section${c._sectionCount !== 1 ? "s" : ""} with data</span>
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
    container.innerHTML = '<p class="hint">No cases match the current filters.</p>';
  }
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
  doc.text("iudicium. — Case Search Results", margin, y);
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

    // Case heading
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

      // Section heading
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

    // Separator between cases
    doc.setDrawColor(214, 210, 194);
    doc.setLineDash([2, 2]);
    addPageIfNeeded(6);
    doc.line(margin, y, pageW - margin, y);
    doc.setLineDash([]);
    y += 6;
  });

  doc.save("cases.pdf");
}

function downloadMarkdown() {
  if (!allCases.length) return;
  const mdEscape = (v) => String(v ?? "").replace(/\|/g, "\\|").replace(/\r?\n/g, "<br>");

  const lines = [
    "# iudicium. — Case Search Results",
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
  triggerDownload(lines.join("\n"), "cases.md", "text/markdown;charset=utf-8;");
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

// ------------------------------------------------------------------
// Restore persisted results on page load
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
  set("petName", f.petitioner_name);
  set("respName", f.respondent_name);
  set("petAdv", f.petitioner_adv);
  set("respAdv", f.respondent_adv);
  set("coram", f.coram);
  if (f.from_date) set("fromDate", ddmmyyyyToInput(f.from_date));
  if (f.to_date) set("toDate", ddmmyyyyToInput(f.to_date));
  if (Array.isArray(f.aliases) && f.aliases.length) set("aliases", f.aliases.join("\n"));
  set("aliasField", f.alias_field);
  if (f.report_type) {
    const radio = document.querySelector(`input[name="reportType"][value="${f.report_type}"]`);
    if (radio) radio.checked = true;
  }
  if (f.db_bench && $("dbBench")) $("dbBench").dispatchEvent(new Event("change"));
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

    resetFilterState();
    buildFilterOptions(allCases);
    renderFilteredResults();
    $("resultsCard").hidden = false;
  } catch (e) {
    console.warn("Could not restore persisted results:", e);
  }
}

// ------------------------------------------------------------------
// Job status check — restore running UI instantly on page (re)load
// ------------------------------------------------------------------

async function checkJobStatus() {
  try {
    const res = await fetch("/api/search/status");
    if (!res.ok) return;
    const data = await res.json();
    if (data.is_running) {
      $("progressWrap").hidden = false;
      $("progressLabel").textContent = "Fetching cases…";
      $("progressFill").style.width = "";
      setRunning(true);
    }
  } catch (e) {
    // Endpoint unavailable — fail silently.
  }
}

// ------------------------------------------------------------------
// Init
// ------------------------------------------------------------------

lucide.createIcons();
loadFormOptions().then(applyAssistantPrefill);
checkJobStatus();
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
