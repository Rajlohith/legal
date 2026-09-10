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
// Results rendering + filters/sort
// ------------------------------------------------------------------

let allCases = [];
const filterState = {
  search: "",
  caseTypes: new Set(),
  caseYears: new Set(),
  hasJudgment: false,
  hasOrders: false,
  caseNoMin: "",
  caseNoMax: "",
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
  filterState.caseNoMin = "";
  filterState.caseNoMax = "";
  filterState.petitioner = "";
  filterState.respondent = "";
  $("filterSearch").value = "";
  $("filterHasJudgment").checked = false;
  $("filterHasOrders").checked = false;
  $("filterCaseNoMin").value = "";
  $("filterCaseNoMax").value = "";
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
$("filterCaseNoMin").addEventListener("input", (e) => {
  filterState.caseNoMin = e.target.value.trim();
  renderFilteredResults();
});
$("filterCaseNoMax").addEventListener("input", (e) => {
  filterState.caseNoMax = e.target.value.trim();
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
    // Case number range filter
    const caseNoInt = parseInt(c.case_no, 10) || 0;
    if (filterState.caseNoMin && caseNoInt < parseInt(filterState.caseNoMin, 10)) return false;
    if (filterState.caseNoMax && caseNoInt > parseInt(filterState.caseNoMax, 10)) return false;
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
  if (filterState.caseNoMin) chips.push({ label: `Case No ≥ ${filterState.caseNoMin}`, clear: () => { filterState.caseNoMin = ""; $("filterCaseNoMin").value = ""; } });
  if (filterState.caseNoMax) chips.push({ label: `Case No ≤ ${filterState.caseNoMax}`, clear: () => { filterState.caseNoMax = ""; $("filterCaseNoMax").value = ""; } });
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
    container.innerHTML = '<p class="hint">No cases match the current filters.</p>';
  }
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
// Rich section content rendering
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
  // Build a regex from known field names
  const fieldPattern = new RegExp(
    "(" + CASE_INFO_FIELDS.join("|") + "):\\s*",
    "g"
  );
  const cleaned = text.trim();

  // Split into key/value pairs
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
  // "Prayer Details: WP XXXX/YYYY THIS W.P. IS FILED PRAYING TO- ..."
  const cleaned = text.trim().replace(/^Prayer Details:\s*/i, "");
  return `<pre class="section-narrative">${escapeHtml(cleaned)}</pre>`;
}

function renderPartyInformation(text) {
  // Split on "Petitioner Details:" and "Respondent Details:"
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
  // Try to parse entries like: "Sl.No Petitioner Address 1 NAME S/O ... Advocate: ADV_NAME"
  // or "Sl.No Respondent Address 1 THE STATE OF KARNATAKA..."
  // Simpler approach: split on digit followed by space at start of an entry
  // Detect numbered parties: 1 THE STATE OF, 2 THE COMMISSIONER, etc.
  const entryRe = /\b(\d{1,2})\s+(THE |SRI |SMT |MR\.|MS\.|DR\.|M\/S\s)/gi;
  const entries = [...text.matchAll(entryRe)];

  if (entries.length > 1) {
    // Parse as numbered list
    const rows = [];
    for (let i = 0; i < entries.length; i++) {
      const num = entries[i][1];
      const start = entries[i].index;
      const end = i + 1 < entries.length ? entries[i + 1].index : text.length;
      const content = text.slice(start + entries[i][0].length - entries[i][2].length, end).trim();
      // Try to extract advocate
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

  // Fallback: narrative
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

  const writeLine = (text, opts = {}) => {
    const { fontSize = 10, fontStyle = "normal", color = [27, 27, 23], indent = 0 } = opts;
    doc.setFontSize(fontSize);
    doc.setFont("helvetica", fontStyle);
    doc.setTextColor(...color);
    const lines = doc.splitTextToSize(text, contentW - indent);
    lines.forEach((line) => {
      addPageIfNeeded(5);
      doc.text(line, margin + indent, y);
      y += 5;
    });
  };

  // Title
  doc.setFontSize(18);
  doc.setFont("helvetica", "bold");
  doc.setTextColor(31, 58, 95);
  doc.text("Karnataka Judiciary — Case Search Results", margin, y);
  y += 8;

  doc.setFontSize(9);
  doc.setFont("helvetica", "normal");
  doc.setTextColor(107, 106, 92);
  doc.text(`Generated: ${new Date().toLocaleString()}   |   ${allCases.length} case(s)`, margin, y);
  y += 8;

  // Horizontal rule
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

    // Sections
    const allSections = [];
    if (c.case_information) allSections.push(["Case Information", c.case_information]);
    Object.entries(c.sections || {}).forEach(([name, text]) => {
      if (text && text.trim()) allSections.push([name, text]);
    });

    allSections.forEach(([secName, secText]) => {
      addPageIfNeeded(12);

      // Section heading
      doc.setFontSize(9);
      doc.setFont("helvetica", "bold");
      doc.setTextColor(31, 58, 95);
      doc.text(secName, margin, y);
      doc.setDrawColor(31, 58, 95);
      doc.line(margin, y + 1, pageW - margin, y + 1);
      y += 6;

      // Section body
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
  const lines = [
    "# Karnataka Judiciary — Case Search Results",
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

function restorePersistedResults() {
  try {
    const stored = sessionStorage.getItem(RESULTS_KEY);
    if (!stored) return;
    const data = JSON.parse(stored);
    if (!data || !data.cases || !data.cases.length) return;

    allCases = data.cases;
    $("downloadLink").href = data.downloadHref || "#";
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
