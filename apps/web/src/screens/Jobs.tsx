/** Scheduled work across every day, source and the write overlay as one list. */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, stamp } from "../api";
import { Nothing, Pill, Screen, Table } from "../components";

export function Jobs() {
  const { data, isPending, error } = useQuery({
    queryKey: ["jobs"],
    queryFn: api.jobs,
  });

  if (isPending) return <Screen title="Jobs">Loading…</Screen>;
  if (error) return <Screen title="Jobs">{String(error)}</Screen>;

  return (
    <Screen title="Jobs" subtitle={`${data.count} most recently scheduled`}>
      {data.count === 0 ? (
        <Nothing
          what="scheduled jobs"
          why="No row in source.jobs or ops.booked_jobs carries a scheduled start."
        />
      ) : (
        <Table head={["Scheduled", "Job", "Status", "Description", "Source"]}>
          {data.items.map((job) => (
            <tr key={job.job_id} className="hover:bg-slate-50">
              <td className="px-3 py-2 whitespace-nowrap tabular-nums">
                {stamp(job.scheduled_start)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                <Link
                  className="text-blue-700 hover:underline"
                  to={`/jobs/${job.job_id}`}
                >
                  {job.job_number ?? job.job_id.slice(0, 16)}
                </Link>
              </td>
              <td className="px-3 py-2 whitespace-nowrap text-slate-600">
                {job.work_status}
              </td>
              <td className="px-3 py-2 text-slate-500">
                {job.description || "—"}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {job.agent_booked ? (
                  <Pill tone="amber">agent</Pill>
                ) : job.rescheduled ? (
                  <Pill tone="amber">moved</Pill>
                ) : (
                  <span className="text-xs text-slate-400">loaded</span>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Screen>
  );
}
