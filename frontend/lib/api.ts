const API_URL = process.env.NEXT_PUBLIC_API_URL;

export type SearchRequest = {
  respondent_aliases: string[];
  petitioner_aliases: string[];
  judge?: string;
  author_judge?: string;
  coram?: string;
  case_type?: string;
  case_number?: string;
  case_year?: string;
  petitioner_name?: string;
  respondent_name?: string;
  petitioner_advocate?: string;
  respondent_advocate?: string;
  start_date: string;
  end_date: string;
  bench?: "principal" | "dharwad" | "kalaburagi";
};

export type AgentFields = Partial<SearchRequest>;

export async function parseAgentRequest(message: string) {
  const res = await fetch(`${API_URL}/api/agent/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<AgentFields>;
}

export async function createSearch(req: SearchRequest) {
  const res = await fetch(`${API_URL}/api/searches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<{ job_id: string; status: string }>;
}

export async function getSearchStatus(jobId: string) {
  const res = await fetch(`${API_URL}/api/searches/${jobId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getSearchResults(jobId: string) {
  const res = await fetch(`${API_URL}/api/searches/${jobId}/results`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}