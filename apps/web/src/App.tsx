/**
 * The shell: a fixed rail, four screens and a live feed.
 *
 * The rail is 240px of sunken paper so the working surface beside it reads
 * as the page. The feed at the foot of it subscribes to /api/events, the
 * SSE endpoint T6.2 measured at 12 ms p95 from tool call to frame. It
 * exists so the operator can see the agent working without refreshing, and
 * so a stalled agent is visible as an absence rather than as a stale page.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import { Label } from "./components";
import { CallDetail } from "./screens/CallDetail";
import { Calls } from "./screens/Calls";
import { JobDetail } from "./screens/JobDetail";
import { Jobs } from "./screens/Jobs";
import { ReviewQueue } from "./screens/ReviewQueue";
import { Stale } from "./screens/Stale";
import { Today } from "./screens/Today";

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="block flex-none"
    >
      {children}
    </svg>
  );
}

const ICONS = {
  calendar: (
    <Icon>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </Icon>
  ),
  list: (
    <Icon>
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
    </Icon>
  ),
  file: (
    <Icon>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6M9 13h6M9 17h4" />
    </Icon>
  ),
  clock: (
    <Icon>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Icon>
  ),
  inbox: (
    <Icon>
      <path d="M22 12h-6l-2 3h-4l-2-3H2" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
    </Icon>
  ),
};

const TABS = [
  { to: "/", label: "Today", icon: ICONS.calendar },
  { to: "/calls", label: "Calls", icon: ICONS.list },
  { to: "/jobs", label: "Jobs", icon: ICONS.file },
  { to: "/stale", label: "Stale", icon: ICONS.clock },
  { to: "/review", label: "Review", icon: ICONS.inbox },
] as const;

function isActive(to: string, pathname: string): boolean {
  return to === "/" ? pathname === "/" : pathname.startsWith(to);
}

/** The rail badges: what each queue is holding. Both share their screen's
 * cache key, so neither costs an extra request. */
function useBadges(): Record<string, number | null> {
  const reviews = useQuery({ queryKey: ["review_queue"], queryFn: api.reviewQueue });
  const stale = useQuery({ queryKey: ["stale"], queryFn: api.stale });
  return {
    Review: reviews.data ? reviews.data.count : null,
    Stale: stale.data ? stale.data.count : null,
  };
}

type Feed = { events: number; last: string | null; connected: boolean };

/** Which query keys each NOTIFY channel can have changed. */
const KEYS_FOR: Record<string, string[]> = {
  switchboard_tool_calls: ["calls", "call"],
  switchboard_writes: ["jobs", "job", "today", "stale"],
  switchboard_async_jobs: ["review_queue"],
};
const ALL_KEYS = ["calls", "call", "jobs", "job", "today", "stale", "review_queue"];

/**
 * One EventSource for the whole shell.
 *
 * The rail and the narrow bar both show the feed, and only CSS decides
 * which is visible, so the subscription is opened here and handed down.
 * Two hooks would mean two sockets and two invalidations per event.
 */
function useLiveFeed(): Feed {
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
      // Refetch what the event says changed. An unscoped invalidation
      // refetched every cached screen on every tool call - five tool calls
      // in one conversation meant five refetches of a job detail nobody
      // was looking at.
      for (const key of KEYS_FOR[event.channel] ?? ALL_KEYS) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    };
    return () => source.close();
  }, [queryClient]);

  return { events, last, connected };
}

function LiveDot({ connected }: { connected: boolean }) {
  return (
    <span
      className={`h-[7px] w-[7px] flex-none rounded-full ${
        connected ? "bg-brand" : "bg-line-strong"
      }`}
      style={connected ? { animation: "pulse-dot 2s ease-in-out infinite" } : {}}
    />
  );
}

/**
 * The feed as the rail's footer card.
 *
 * It shows the last tool name rather than a total only: "27 events" says
 * the socket is open, "27 events · warranty_status" says what the agent is
 * doing right now, which is the question being asked of this corner.
 */
function LiveFeed({ events, last, connected }: Feed) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3.5 shadow-card">
      <div className="flex items-center gap-2">
        <LiveDot connected={connected} />
        <Label>{connected ? "Live feed" : "Disconnected"}</Label>
        <span className="ml-auto font-mono text-xs tabular-nums text-ink-mid">
          {events}
        </span>
      </div>
      <p className="mt-1.5 truncate font-mono text-[13px] text-ink">
        {last ?? (connected ? "idle" : "not connected")}
      </p>
    </div>
  );
}

export function App() {
  const { pathname } = useLocation();
  const badges = useBadges();
  const feed = useLiveFeed();

  const badge = (label: string) => badges[label] || null;

  return (
    <div className="flex h-dvh overflow-hidden">
      <nav className="hidden w-60 flex-none flex-col border-r border-line bg-sunken py-5 lg:flex">
        <div className="flex items-center gap-2.5 px-5 pb-5.5">
          <span className="h-4 w-4 rounded-[5px] bg-brand" />
          <span className="text-[15px] font-semibold tracking-[-0.015em]">
            Switchboard
          </span>
        </div>
        <div className="flex flex-col gap-0.5 px-3">
          {TABS.map(({ to, label, icon }) => {
            const active = isActive(to, pathname);
            return (
              <Link
                key={to}
                to={to}
                className={`flex h-9.5 items-center gap-2.5 rounded-lg px-3 text-[11px] font-semibold tracking-[0.07em] uppercase ${
                  active
                    ? "bg-wash text-brand"
                    : "text-ink-mid hover:bg-hover hover:text-ink"
                }`}
              >
                {icon}
                <span className="flex-1">{label}</span>
                {badge(label) && (
                  <span className="font-mono text-[11px] font-medium tracking-normal text-warn">
                    {badge(label)}
                  </span>
                )}
              </Link>
            );
          })}
        </div>
        <div className="flex-1" />
        <div className="px-4">
          <LiveFeed {...feed} />
        </div>
      </nav>

      {/* Under 1024px the rail becomes a bar: same items, same order. */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex flex-none items-center gap-1 overflow-x-auto border-b border-line bg-surface px-4 py-2 lg:hidden">
          <span className="mr-2 font-semibold whitespace-nowrap">
            Switchboard
          </span>
          {TABS.map(({ to, label }) => (
            <Link
              key={to}
              to={to}
              className={`rounded-lg px-2.5 py-1 text-[11px] font-semibold tracking-[0.07em] whitespace-nowrap uppercase ${
                isActive(to, pathname)
                  ? "bg-wash text-brand"
                  : "text-ink-mid hover:bg-hover"
              }`}
            >
              {label}
              {badge(label) && (
                <span className="ml-1.5 font-mono tracking-normal text-warn">
                  {badge(label)}
                </span>
              )}
            </Link>
          ))}
          <span className="ml-auto pl-3">
            <MobileFeed {...feed} />
          </span>
        </header>

        <main className="min-h-0 flex-1 overflow-hidden">
          <Routes>
            <Route path="/" element={<Today />} />
            <Route path="/calls" element={<Calls />} />
            <Route path="/calls/:callId" element={<CallDetail />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:jobId" element={<JobDetail />} />
            <Route path="/stale" element={<Stale />} />
            <Route path="/review" element={<ReviewQueue />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

/** The same feed, one line, for the narrow bar. */
function MobileFeed({ events, connected }: Feed) {
  return (
    <span className="flex items-center gap-2">
      <LiveDot connected={connected} />
      <span className="font-mono text-xs tabular-nums text-ink-mid">
        {connected ? events : "offline"}
      </span>
    </span>
  );
}
