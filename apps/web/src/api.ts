/**
 * The API, typed.
 *
 * Everything goes through `/api`, which vite proxies to the FastAPI app, so
 * the browser sees one origin and there is no base URL to get wrong between
 * dev and preview.
 */

export type Page<T> = { items: T[]; count: number };

export type Job = {
  job_id: string;
  job_number: string | null;
  customer_id: string;
  /** Company, else name, else the id - the API never leaves it empty. */
  customer?: string;
  scheduled_start: string;
  arrival_window?: number;
  work_status: string;
  description: string;
  display_address?: string;
  techs?: string[] | null;
  agent_booked: boolean;
  rescheduled?: boolean;
};

export type Call = {
  call_id: string;
  caller: string | null;
  started_at: string;
  ended_at: string | null;
  last_agent: string | null;
  tool_calls: number;
};

export type ToolCall = {
  id: string;
  call_id?: string;
  agent: string;
  tool: string;
  args: Record<string, unknown>;
  duration_ms: number;
  result_rows: number;
  ok: boolean;
  timings: Record<string, number> | null;
  created_at: string;
};

export type Turn = {
  seq: number;
  role: string;
  text: string;
  agent: string | null;
  created_at: string;
};

export type CallDetail = {
  call: Partial<Call> & { call_id: string };
  turns: Turn[];
  tool_calls: ToolCall[];
};

export type Warranty = {
  covered: string;
  level: number;
  basis: string;
  confidence: string;
  evidence: { kind: string; id: string } | null;
};

export type JobDetail = {
  job: Record<string, unknown> & {
    job_id: string;
    job_number: string | null;
    customer?: string;
  };
  notes: { id: string; content: string }[];
  agent_notes?: { id: string; content: string; call_id: string }[];
  invoices: { invoice_number: string; due_amount: number; status: string }[];
  warranty: Warranty | null;
};

export type ReviewItem = {
  id: string;
  call_id: string | null;
  kind: string;
  status: string;
  title: string;
  payload: Record<string, unknown>;
  created_at: string;
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  today: (on?: string) => get<Page<Job>>(`/today${on ? `?on=${on}` : ""}`),
  calls: () => get<Page<Call>>("/calls"),
  call: (id: string) => get<CallDetail>(`/calls/${encodeURIComponent(id)}`),
  job: (id: string) => get<JobDetail>(`/jobs/${encodeURIComponent(id)}`),
  jobs: () => get<Page<Job>>("/jobs"),
  reviewQueue: () => get<Page<ReviewItem>>("/review_queue"),
};

/** Money is cents everywhere below the presentation layer. */
export function dollars(cents: number): string {
  return (cents / 100).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
  });
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * A `YYYY-MM-DD` day, spelled out.
 *
 * Built from the parts rather than `new Date(day)`: that parses a bare
 * date as UTC midnight, which in Miami renders as the day before.
 */
export function dayLabel(day: string): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date).toLocaleDateString("en-US", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** How long a call ran, as m:ss. Null while it is still running. */
export function elapsed(
  startIso: string,
  endIso: string | null,
): string | null {
  if (!endIso) return null;
  const start = new Date(startIso).getTime();
  const end = new Date(endIso).getTime();
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/**
 * Today as the person at the screen means it, `YYYY-MM-DD`.
 *
 * Not `toISOString().slice(0, 10)`: that is the UTC date, and at nine in
 * the evening in Miami it is already tomorrow in UTC - the board would
 * show the wrong day for the last hours of every shift.
 */
export function localDay(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function stamp(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
