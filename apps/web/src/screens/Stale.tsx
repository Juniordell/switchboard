/**
 * Work that was scheduled and never happened.
 *
 * `docs/SCOPE.md`: a `scheduled` job whose start has passed is abandoned,
 * not upcoming. It is kept out of the today view, out of availability, and
 * is never spoken as an appointment - and the rule asks for exactly this
 * bucket, "because 38 forgotten jobs is exactly the kind of thing the owner
 * would want surfaced". It is a queue someone has to chase, so it gets a
 * screen rather than a footnote on another one.
 *
 * Oldest first: the row at the top has been waiting longest, which is the
 * order someone working through this would want.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, stamp } from "../api";
import { Nothing, Screen, Stat, Status, Table, workStatusTone } from "../components";

/** Old enough that it is unlikely to be a scheduling slip. */
const VERY_STALE_DAYS = 90;

export function Stale() {
  const { data, isPending, error } = useQuery({
    queryKey: ["stale"],
    queryFn: api.stale,
  });

  if (isPending) return <Screen title="Stale">Loading…</Screen>;
  if (error) return <Screen title="Stale">{String(error)}</Screen>;

  const oldest = data.items.reduce((n, job) => Math.max(n, job.days_stale ?? 0), 0);
  const veryStale = data.items.filter(
    (job) => (job.days_stale ?? 0) >= VERY_STALE_DAYS,
  ).length;

  return (
    <Screen
      title="Stale"
      note="Scheduled, the day came and went, still open. Nobody is driving to these."
      stats={
        <>
          <Stat value={data.count} label="Jobs" tone={data.count ? "warn" : undefined} />
          <Stat value={oldest} label="Days, oldest" />
          <Stat value={veryStale} label={`Over ${VERY_STALE_DAYS} days`} />
        </>
      }
    >
      {data.count === 0 ? (
        <Nothing
          what="stale jobs"
          why="Every scheduled job has a start date in the future. That is the state this screen exists to notice leaving."
        />
      ) : (
        <div className="max-w-[1180px]">
          <Table
            fixed
            head={[
              { label: "Was due", className: "w-[172px]" },
              { label: "Waiting", className: "w-[104px] text-right" },
              { label: "Job", className: "w-[96px]" },
              { label: "Customer", className: "w-[200px]" },
              "Address",
              { label: "Status", className: "w-[150px]" },
            ]}
          >
            {data.items.map((job) => {
              const days = job.days_stale ?? 0;
              return (
                <tr key={job.job_id} className="hover:bg-hover">
                  <td className="px-5 py-2.5 font-mono text-[13px] tabular-nums text-ink-mid">
                    {stamp(job.scheduled_start)}
                  </td>
                  <td
                    className={`px-5 py-2.5 text-right font-mono text-[13px] tabular-nums ${
                      days >= VERY_STALE_DAYS ? "font-medium text-warn" : "text-ink-mid"
                    }`}
                  >
                    {days}d
                  </td>
                  <td className="px-5 py-2.5">
                    <Link
                      className="font-mono text-[13px] font-medium text-brand hover:text-brand-hover hover:underline"
                      to={`/jobs/${job.job_id}`}
                    >
                      {job.job_number ?? job.job_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="truncate px-5 py-2.5" title={job.customer}>
                    {job.customer ?? job.customer_id}
                  </td>
                  <td
                    className="truncate px-5 py-2.5 text-ink-mid"
                    title={job.display_address || undefined}
                  >
                    {job.display_address || "—"}
                  </td>
                  <td className="px-5 py-2.5">
                    <Status
                      status={job.work_status}
                      tone={workStatusTone(job.work_status)}
                    />
                  </td>
                </tr>
              );
            })}
          </Table>
          <p className="mt-3 text-[13px] text-ink-lo">
            A job that someone started and never closed carries{" "}
            <code>in progress</code>, not <code>scheduled</code>, and is a
            different problem — it is not counted here.
          </p>
        </div>
      )}
    </Screen>
  );
}
