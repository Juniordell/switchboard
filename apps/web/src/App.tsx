/**
 * The shell: four screens and a live counter.
 *
 * The counter subscribes to /api/events, the SSE endpoint T6.2 measured at
 * 12 ms p95 from tool call to frame. It exists so the operator can see the
 * agent working without refreshing, and so a stalled agent is visible as an
 * absence rather than as a stale page.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import { CallDetail } from "./screens/CallDetail";
import { Calls } from "./screens/Calls";
import { JobDetail } from "./screens/JobDetail";
import { Jobs } from "./screens/Jobs";
import { ReviewQueue } from "./screens/ReviewQueue";
import { Today } from "./screens/Today";

const TABS = [
  ["/", "Today"],
  ["/calls", "Calls"],
  ["/jobs", "Jobs"],
  ["/review", "Review queue"],
] as const;

function LiveFeed() {
  const [events, setEvents] = useState(0);
  const [last, setLast] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const queryClient = useQueryClient();

  useEffect(() => {
    const source = new EventSource("/api/events");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (message) => {
      const event = JSON.parse(message.data);
      setEvents((n) => n + 1);
      setLast(event.data?.tool ?? event.data?.action ?? event.channel);
      // Something changed on the server; let the open screen refetch.
      queryClient.invalidateQueries();
    };
    return () => source.close();
  }, [queryClient]);

  return (
    <div className="flex items-center gap-2 text-xs">
      <span
        className={`h-2 w-2 rounded-full ${
          connected ? "bg-emerald-500" : "bg-slate-300"
        }`}
      />
      <span className="text-slate-500">
        {connected ? "live" : "disconnected"}
      </span>
      {events > 0 && (
        <span className="tabular-nums text-slate-400">
          {events} events{last ? ` · ${last}` : ""}
        </span>
      )}
    </div>
  );
}

export function App() {
  const { pathname } = useLocation();
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="flex items-center justify-between border-b border-slate-200 px-6 py-3">
        <nav className="flex items-center gap-1">
          <span className="mr-3 font-semibold">Switchboard</span>
          {TABS.map(([to, label]) => {
            const active =
              to === "/" ? pathname === "/" : pathname.startsWith(to);
            return (
              <Link
                key={to}
                to={to}
                className={`rounded px-2.5 py-1 text-sm ${
                  active
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </nav>
        <LiveFeed />
      </header>
      <Routes>
        <Route path="/" element={<Today />} />
        <Route path="/calls" element={<Calls />} />
        <Route path="/calls/:callId" element={<CallDetail />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/jobs/:jobId" element={<JobDetail />} />
        <Route path="/review" element={<ReviewQueue />} />
      </Routes>
    </div>
  );
}
