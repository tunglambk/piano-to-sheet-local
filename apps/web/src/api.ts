export type Artifact = { kind: string; name: string; size: number; url?: string };
export type Stage = { stage: string; engine: string; status: string; cache_hit: boolean; duration_s: number };
export type Job = {
  id: string;
  name: string;
  status: string;
  preset: string;
  duration_s: number;
  origin_offset_s: number;
  error: string | null;
  created_at: string;
  params: Record<string, unknown>;
  artifacts: Artifact[];
  stages: Stage[];
};

export type Timemap = {
  notes: Record<string, [number, number]>;
  measures: { measure: number; onset_s: number }[];
  n_notes: number;
};

export type SyncPayload = { timemap: Timemap; pages: { name: string; url: string }[] };

const base = "/api/v1";

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(detail.detail ?? response.statusText);
  }
  return (await response.json()) as T;
}

export async function listJobs(query = ""): Promise<Job[]> {
  const response = await fetch(`${base}/jobs?limit=100${query ? `&q=${encodeURIComponent(query)}` : ""}`);
  return (await json<{ jobs: Job[] }>(response)).jobs;
}

export async function getJob(id: string): Promise<Job> {
  return json<Job>(await fetch(`${base}/jobs/${id}`));
}

export async function createJob(file: File, preset: string, name: string): Promise<string> {
  const body = new FormData();
  body.append("file", file);
  body.append("preset", preset);
  body.append("name", name);
  body.append("params", "{}");
  body.append("range", "{}");
  const response = await fetch(`${base}/jobs`, { method: "POST", body });
  return (await json<{ job_id: string }>(response)).job_id;
}

export async function cancelJob(id: string): Promise<void> {
  await fetch(`${base}/jobs/${id}/cancel`, { method: "POST" });
}

export async function deleteJob(id: string): Promise<void> {
  await fetch(`${base}/jobs/${id}`, { method: "DELETE" });
}

export async function syncPayload(id: string): Promise<SyncPayload> {
  return json<SyncPayload>(await fetch(`${base}/jobs/${id}/sync`));
}

export function artifactUrl(id: string, kind: string, name?: string): string {
  const suffix = name ? `?name=${encodeURIComponent(name)}` : "";
  return `${base}/jobs/${id}/artifacts/${kind}${suffix}`;
}

export function eventsUrl(id: string): string {
  return `${base}/jobs/${id}/events`;
}
