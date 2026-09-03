/**
 * Today, by tech.
 *
 * Grouped in the screen rather than the query so unassigned work still
 * appears: 95 of the dataset's jobs have no tech, and a GROUP BY would have
 * hidden exactly the rows an office manager needs to act on.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, clockTime, type Job } from "../api";
import { Nothing, Pill, Screen, Table } from "../components";

const UNASSIGNED = "Unassigned";

function byTech(jobs: Job[]): [string, Job[]][] {
  const groups = new Map<string, Job[]>();
  for (const job of jobs) {
    const techs = job.techs?.length ? job.techs : [UNASSIGNED];
    for (const tech of techs) {
      groups.set(tech, [...(groups.get(tech) ?? []), job]);
    }
  }
  // Unassigned last: it is the exception, not the roster.
  return [...groups.entries()].sort(([a], [b]) =>
    a === UNASSIGNED ? 1 : b === UNASSIGNED ? -1 : a.localeCompare(b),
  );
}

export function Today() {
  const today = new Date().toISOString().slice(0, 10);
  const { data, isPending, error } = useQuery({
    queryKey: ["today", today],
    queryFn: () => api.today(today),
  });

  if (isPending) return <Screen title="Today">Loading…</Screen>;
  if (error) return <Screen title="Today">{String(error)}</Screen>;

  const groups = byTech(data.items);

  return (
    <Screen title="Today" subtitle={`${today} · ${data.count} scheduled`}>
      {groups.length === 0 ? (
        <Nothing
          what="work scheduled today"
          why={`Nothing in source.jobs or the ops overlay starts on ${today}. Stale scheduled jobs — a start date already past — are excluded by docs/SCOPE.md's rule and are not counted here.`}
        />
      ) : (
        <div className="space-y-6">
          {groups.map(([tech, jobs]) => (
            <div key={tech}>
              <h2 className="mb-2 text-sm font-semibold text-slate-700">
                {tech}{" "}
                <span className="font-normal text-slate-400">
                  · {jobs.length}
                </span>
              </h2>
              <Table head={["Time", "Job", "Status", "Address", "Description"]}>
                {jobs.map((job) => (
                  <tr key={`${tech}-${job.job_id}`} className="hover:bg-slate-50">
                    <td className="px-3 py-2 whitespace-nowrap tabular-nums">
                      {clockTime(job.scheduled_start)}
                      {job.arrival_window ? (
                        <span className="ml-1 text-slate-400">
                          +{job.arrival_window}m
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <Link
                        className="text-blue-700 hover:underline"
                        to={`/jobs/${job.job_id}`}
                      >
                        {job.job_number ?? "—"}
                      </Link>
                      {job.agent_booked && (
                        <span className="ml-2">
                          <Pill tone="amber">booked by agent</Pill>
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-slate-600">
                      {job.work_status}
                    </td>
                    <td className="px-3 py-2 text-slate-600">
                      {job.display_address || "—"}
                    </td>
                    <td className="px-3 py-2 text-slate-500">
                      {job.description || "—"}
                    </td>
                  </tr>
                ))}
              </Table>
            </div>
          ))}
        </div>
      )}
      <p className="mt-4 text-xs text-slate-400">
        A job the agent booked has no job number — the field service system
        assigns those.
      </p>
    </Screen>
  );
}
