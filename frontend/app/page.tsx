"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { createSearch, getSearchResults, getSearchStatus, parseAgentRequest } from "@/lib/api";

type CaseResult = { summary: Record<string, string>; case_information: string; sections: Record<string, string> };
type SearchJob = { status: string; completed_jobs?: number; total_jobs?: number; error?: string };
type Bench = "principal" | "dharwad" | "kalaburagi";

function parseAliases(value: string) { return value.split(/[\n,]/).map((alias) => alias.trim()).filter(Boolean); }
function partyNames(value: string) { const parts = value.split(/\s+V\/S\s+/i); return { petitioner: parts[0] ?? "", respondent: parts.slice(1).join(" V/S ") }; }
function apiDate(value: string) { const [year, month, day] = value.split("-"); return `${day}-${month}-${year}`; }

export default function Home() {
  const [respondentAliases, setRespondentAliases] = useState("");
  const [petitionerAliases, setPetitionerAliases] = useState("");
  const [judge, setJudge] = useState("");
  const [authorJudge, setAuthorJudge] = useState("");
  const [coram, setCoram] = useState("");
  const [caseType, setCaseType] = useState("");
  const [caseNumber, setCaseNumber] = useState("");
  const [caseYear, setCaseYear] = useState("");
  const [petitionerName, setPetitionerName] = useState("");
  const [respondentName, setRespondentName] = useState("");
  const [petitionerAdvocate, setPetitionerAdvocate] = useState("");
  const [respondentAdvocate, setRespondentAdvocate] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [bench, setBench] = useState<Bench>("principal");
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<SearchJob | null>(null);
  const [cases, setCases] = useState<CaseResult[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [agentMessage, setAgentMessage] = useState("");
  const [agentBusy, setAgentBusy] = useState(false);

  useEffect(() => {
    if (!jobId || !job || ["completed", "failed", "cancelled"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      const nextJob = await getSearchStatus(jobId) as SearchJob;
      setJob(nextJob);
      if (["completed", "cancelled"].includes(nextJob.status)) {
        const results = await getSearchResults(jobId) as { cases: CaseResult[] };
        setCases(results.cases);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [jobId, job]);

  const rows = useMemo(() => cases.map((caseItem) => {
    const summary = caseItem.summary ?? {};
    return { caseItem, type: summary["Case Type"] ?? "", number: summary["Case No"] ?? "", year: summary["Case Year"] ?? "", ...partyNames(summary["Petitioner V/S Respondent Name"] ?? "") };
  }), [cases]);
  const filteredRows = rows.filter((row) => Object.values(row).join(" ").toLowerCase().includes(query.toLowerCase()));

  async function runSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!startDate || !endDate) { setError("From and to dates are required."); return; }
    try {
      const result = await createSearch({
        respondent_aliases: parseAliases(respondentAliases),
        petitioner_aliases: parseAliases(petitionerAliases),
        start_date: apiDate(startDate), end_date: apiDate(endDate), bench,
        judge, author_judge: authorJudge, coram, case_type: caseType,
        case_number: caseNumber, case_year: caseYear,
        petitioner_name: petitionerName, respondent_name: respondentName,
        petitioner_advocate: petitionerAdvocate, respondent_advocate: respondentAdvocate,
      });
      setCases([]); setJobId(result.job_id); setJob({ status: result.status });
    } catch (searchError) { setError(searchError instanceof Error ? searchError.message : "Could not start search."); }
  }

  async function applyAgentFields() {
    if (!agentMessage.trim()) return;
    setAgentBusy(true);
    setError("");
    try {
      const fields = await parseAgentRequest(agentMessage);
      if (fields.start_date) {
        const [day, month, year] = fields.start_date.split("-");
        setStartDate(`${year}-${month}-${day}`);
      }
      if (fields.end_date) {
        const [day, month, year] = fields.end_date.split("-");
        setEndDate(`${year}-${month}-${day}`);
      }
      if (fields.respondent_aliases) setRespondentAliases(fields.respondent_aliases.join(", "));
      if (fields.petitioner_aliases) setPetitionerAliases(fields.petitioner_aliases.join(", "));
      if (fields.judge !== undefined) setJudge(fields.judge ?? "");
      if (fields.author_judge !== undefined) setAuthorJudge(fields.author_judge ?? "");
      if (fields.coram !== undefined) setCoram(fields.coram ?? "");
      if (fields.case_type !== undefined) setCaseType(fields.case_type ?? "");
      if (fields.case_number !== undefined) setCaseNumber(fields.case_number ?? "");
      if (fields.case_year !== undefined) setCaseYear(fields.case_year ?? "");
      if (fields.petitioner_name !== undefined) setPetitionerName(fields.petitioner_name ?? "");
      if (fields.respondent_name !== undefined) setRespondentName(fields.respondent_name ?? "");
      if (fields.petitioner_advocate !== undefined) setPetitionerAdvocate(fields.petitioner_advocate ?? "");
      if (fields.respondent_advocate !== undefined) setRespondentAdvocate(fields.respondent_advocate ?? "");
      if (fields.bench) setBench(fields.bench as Bench);
    } catch (agentError) {
      setError(agentError instanceof Error ? agentError.message : "Could not parse the request.");
    } finally {
      setAgentBusy(false);
    }
  }

  const running = job && !["completed", "failed", "cancelled"].includes(job.status);
  return (
    <main className="min-h-screen bg-slate-50 px-6 py-12 text-slate-900">
      <div className="mx-auto max-w-6xl space-y-8">
        <header><p className="text-sm font-semibold uppercase tracking-[0.2em] text-teal-700">Iudicium</p><h1 className="mt-2 text-5xl font-semibold tracking-tight">Case search</h1><p className="mt-3 max-w-2xl text-slate-600">Search respondent and petitioner names independently, then review one deduplicated result set.</p></header>
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-6 rounded-xl bg-slate-100 p-4"><label className="block text-sm font-semibold">Describe your search <span className="font-normal text-slate-500">optional</span><textarea rows={3} value={agentMessage} onChange={(event) => setAgentMessage(event.target.value)} placeholder="Find respondent BBMP cases decided between 01-01-2025 and 31-01-2025" className="mt-2 block w-full rounded-lg border border-slate-300 bg-white p-3 font-normal" /></label><button type="button" disabled={agentBusy || !agentMessage.trim()} onClick={applyAgentFields} className="mt-3 rounded-lg border border-teal-700 px-4 py-2 font-semibold text-teal-800 disabled:cursor-not-allowed disabled:opacity-50">{agentBusy ? "Parsing..." : "Fill fields from request"}</button></div>
          <form className="space-y-5" onSubmit={runSearch}>
            <div className="grid gap-5 md:grid-cols-2"><label className="space-y-2 text-sm font-semibold">From date<input required type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal" /></label><label className="space-y-2 text-sm font-semibold">To date<input required type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal" /></label></div>
            <div className="grid gap-5 md:grid-cols-2"><label className="space-y-2 text-sm font-semibold">Respondent aliases <span className="font-normal text-slate-500">optional, comma or line separated<textarea rows={3} value={respondentAliases} onChange={(event) => setRespondentAliases(event.target.value)} placeholder="BBMP, B.B.M.P" className="mt-2 block w-full rounded-lg border border-slate-300 p-3 font-normal" /></span></label><label className="space-y-2 text-sm font-semibold">Petitioner aliases <span className="font-normal text-slate-500">optional, comma or line separated<textarea rows={3} value={petitionerAliases} onChange={(event) => setPetitionerAliases(event.target.value)} placeholder="Petitioner name, alternate spelling" className="mt-2 block w-full rounded-lg border border-slate-300 p-3 font-normal" /></span></label></div>
            <div className="grid gap-5 md:grid-cols-3"><label className="space-y-2 text-sm font-semibold">Judge<select value={judge} onChange={(event) => setJudge(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal"><option value="">Select judge</option></select></label><label className="space-y-2 text-sm font-semibold">Author Judge<select value={authorJudge} onChange={(event) => setAuthorJudge(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal"><option value="">Select author judge</option></select></label><label className="space-y-2 text-sm font-semibold">Coram<select value={coram} onChange={(event) => setCoram(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal"><option value="">Select coram</option></select></label></div>
            <div className="grid gap-5 md:grid-cols-3"><label className="space-y-2 text-sm font-semibold">Case Type<select value={caseType} onChange={(event) => setCaseType(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal"><option value="">Select case type</option></select></label><label className="space-y-2 text-sm font-semibold">Case Number<input value={caseNumber} onChange={(event) => setCaseNumber(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal" /></label><label className="space-y-2 text-sm font-semibold">Case Year<input value={caseYear} onChange={(event) => setCaseYear(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal" /></label></div>
            <div className="grid gap-5 md:grid-cols-2"><label className="space-y-2 text-sm font-semibold">Petitioner Name<input value={petitionerName} onChange={(event) => setPetitionerName(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal" /></label><label className="space-y-2 text-sm font-semibold">Respondent Name<input value={respondentName} onChange={(event) => setRespondentName(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal" /></label><label className="space-y-2 text-sm font-semibold">Petitioner Advocate<input value={petitionerAdvocate} onChange={(event) => setPetitionerAdvocate(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal" /></label><label className="space-y-2 text-sm font-semibold">Respondent Advocate<input value={respondentAdvocate} onChange={(event) => setRespondentAdvocate(event.target.value)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal" /></label></div>
            <div className="flex flex-wrap items-end gap-4"><label className="w-full space-y-2 text-sm font-semibold sm:w-64">Bench<select value={bench} onChange={(event) => setBench(event.target.value as Bench)} className="block w-full rounded-lg border border-slate-300 p-3 font-normal"><option value="principal">Principal Bench</option><option value="dharwad">Dharwad Bench</option><option value="kalaburagi">Kalaburagi Bench</option></select></label><button disabled={!!running} type="submit" className="rounded-lg bg-teal-700 px-5 py-3 font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50">{running ? "Searching..." : "Run search"}</button>{job && <span className="pb-3 text-sm text-slate-600">{job.status} · {job.completed_jobs ?? 0}/{job.total_jobs ?? 0} windows</span>}</div>
            {error && <p className="text-sm text-red-700">{error}</p>}{job?.error && <p className="text-sm text-red-700">{job.error}</p>}
          </form>
        </section>
        {cases.length > 0 && <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"><div className="mb-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm font-semibold uppercase tracking-[0.2em] text-teal-700">Results</p><h2 className="mt-1 text-2xl font-semibold">{cases.length} unique cases</h2></div><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter cases" className="w-full rounded-lg border border-slate-300 p-3 sm:w-72" /></div><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500"><tr><th className="p-3">Case type</th><th className="p-3">Case no.</th><th className="p-3">Year</th><th className="p-3">Petitioner</th><th className="p-3">Respondent</th></tr></thead><tbody>{filteredRows.map((row, index) => <tr key={`${row.type}-${row.number}-${row.year}-${index}`} className="border-b border-slate-100 align-top hover:bg-teal-50"><td className="p-3">{row.type}</td><td className="p-3">{row.number}</td><td className="p-3">{row.year}</td><td className="p-3">{row.petitioner}</td><td className="p-3">{row.respondent}</td></tr>)}</tbody></table></div>{filteredRows.length === 0 && <p className="pt-5 text-sm text-slate-500">No cases match the filter.</p>}</section>}
      </div>
    </main>
  );
}
