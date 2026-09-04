/** Scheduled work across every day, source and the write overlay as one list. */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, stamp } from "../api";
import {
  Nothing,
  Pill,
  Screen,
  Stat,
  Status,
  Table,
  workStatusTone,
} from "../components";

export function Jobs() {
  const { data, isPending, error } = useQuery({
    queryKey: ["jobs"],
    queryFn: api.jobs,
  });

  if (isPending) return <Screen title="Jobs">Loading…</Screen>;
  if (error) return <Screen title="Jobs">{String(error)}</Screen>;

  const booked = data.items.filter((job) => job.agent_booked).length;
  const moved = data.items.filter((job) => job.rescheduled).length;

  return (
    <Screen
      title="Jobs"
      note="Loaded work and the agent's writes, in one list."
      stats={
        <>
          <Stat value={data.count} label="Most recent" />
          <Stat value={booked} label="Booked by agent" />
          <Stat value={moved} label="Rescheduled" />
        </>
      }
    >
      {data.count === 0 ? (
        <Nothing
          what="scheduled jobs"
          why="No row in source.jobs or ops.booked_jobs carries a scheduled start."
        />
      ) : (
        <Table
          fixed
          head={[
            { label: "Scheduled", className: "w-[172px]" },
            { label: "Job", className: "w-[110px]" },
            { label: "Customer", className: "w-[150px]" },
            "Service",
            { label: "Status", className: "w-[176px]" },
            { label: "Source", className: "w-[104px]" },
          ]}
        >
          {data.items.map((job) => (
            <tr key={job.job_id} className="hover:bg-hover">
              <td className="px-5 py-2.5 font-mono text-[13px] tabular-nums text-ink-mid">
                {stamp(job.scheduled_start)}
              </td>
              <td className="px-5 py-2.5">
                <Link
                  className="font-mono text-[13px] font-medium text-brand hover:text-brand-hover hover:underline"
                  to={`/jobs/${job.job_id}`}
                >
                  {job.job_number ?? job.job_id.slice(0, 8)}
                </Link>
              </td>
              <td className="truncate px-5 py-2.5 font-mono text-xs text-ink-lo">
                {job.customer_id}
              </td>
              <td
                className="truncate px-5 py-2.5"
                title={job.description || undefined}
              >
                {job.description || "—"}
              </td>
              <td className="px-5 py-2.5">
                <Status
                  status={job.work_status}
                  tone={workStatusTone(job.work_status)}
                />
              </td>
              <td className="px-5 py-2.5">
                {job.agent_booked ? (
                  <Pill tone="write">agent</Pill>
                ) : job.rescheduled ? (
                  <Pill tone="warn">moved</Pill>
                ) : (
                  <span className="text-[13px] text-ink-lo">loaded</span>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Screen>
  );
}
