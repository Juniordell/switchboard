/**
 * Today, by tech.
 *
 * Grouped in the screen rather than the query so unassigned work still
 * appears: 95 of the dataset's jobs have no tech, and a GROUP BY would have
 * hidden exactly the rows an office manager needs to act on. Those rows are
 * lifted out above the roster for the same reason — the first question of
 * the morning is which jobs nobody is driving to.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, clockTime, dayLabel, localDay, type Job } from "../api";
import {
  Nothing,
  Pill,
  Screen,
  Section,
  Stat,
  Status,
  Table,
  workStatusTone,
} from "../components";

const UNASSIGNED = "Unassigned";

/**
 * A cancelled job is not work. It stays on the board - the office manager
 * may want to know a slot opened up - but not under a tech's name as if
 * someone were driving there, and not in the count of jobs to do. Seen on
 * a real day: a "user canceled" visit listed as a tech's 3 p.m.
 */
const CANCELLED = new Set(["user canceled", "pro canceled"]);

/** Column widths, shared by both tables so the two line up down the page. */
const TIME = "w-[132px]";
const SERVICE = "w-[220px]";
const STATUS = "w-[176px]";
const JOB = "w-[110px] text-right";

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

function Time({ job }: { job: Job }) {
  return (
    <span className="font-mono text-[13px] font-medium tabular-nums">
      {clockTime(job.scheduled_start)}
      {job.arrival_window ? (
        <span className="text-ink-lo"> +{job.arrival_window}m</span>
      ) : null}
    </span>
  );
}

/**
 * The job number, or the pill that stands in for it.
 *
 * A job the agent booked has no number yet, so there is nothing to print;
 * the link stays on either way, because the detail screen is the same
 * click for both and the row is useless without it.
 */
function JobNumber({ job }: { job: Job }) {
  if (job.agent_booked) {
    return (
      <Link to={`/jobs/${job.job_id}`}>
        <Pill tone="write">agent</Pill>
      </Link>
    );
  }
  return (
    <Link
      className="font-mono text-[13px] text-brand hover:text-brand-hover hover:underline"
      to={`/jobs/${job.job_id}`}
    >
      {job.job_number ?? job.job_id.slice(0, 8)}
    </Link>
  );
}

/** The five cells every row shares, after whatever comes before them. */
function JobCells({ job }: { job: Job }) {
  return (
    <>
      <td className={`px-5 py-2.5 whitespace-nowrap ${TIME}`}>
        <Time job={job} />
      </td>
      <td
        className={`truncate px-5 py-2.5 ${SERVICE}`}
        title={job.description || undefined}
      >
        {job.description || "—"}
      </td>
      <td className="truncate px-5 py-2.5" title={job.display_address || undefined}>
        <div className="truncate">{job.display_address || "—"}</div>
        {job.customer && (
          <div className="truncate text-[13px] text-ink-mid">{job.customer}</div>
        )}
      </td>
      <td className={`px-5 py-2.5 ${STATUS}`}>
        <Status
          status={job.work_status}
          tone={workStatusTone(job.work_status)}
        />
      </td>
      <td className={`px-5 py-2.5 ${JOB}`}>
        <JobNumber job={job} />
      </td>
    </>
  );
}

export function Today() {
  const today = localDay();
  const { data, isPending, error } = useQuery({
    queryKey: ["today", today],
    queryFn: () => api.today(today),
  });

  if (isPending) return <Screen title="Today">Loading…</Screen>;
  if (error) return <Screen title="Today">{String(error)}</Screen>;

  const cancelled = data.items.filter((job) => CANCELLED.has(job.work_status));
  const work = data.items.filter((job) => !CANCELLED.has(job.work_status));
  const groups = byTech(work);
  const unassigned = groups.find(([tech]) => tech === UNASSIGNED)?.[1] ?? [];
  const roster = groups.filter(([tech]) => tech !== UNASSIGNED);
  // Counted off the job list, not off the groups: a job with two techs on
  // it appears in two groups and would otherwise be counted twice.
  const assigned = work.filter((job) => job.techs?.length).length;
  const booked = work.filter((job) => job.agent_booked).length;

  return (
    <Screen
      title="Today"
      meta={dayLabel(today)}
      stats={
        <>
          <Stat value={work.length} label="Jobs" />
          <Stat value={roster.length} label="Techs" />
          <Stat value={unassigned.length} label="Unassigned" />
          <Stat value={booked} label="Booked by agent" />
          {cancelled.length > 0 && (
            <Stat value={cancelled.length} label="Cancelled" />
          )}
        </>
      }
    >
      {data.items.length === 0 ? (
        <Nothing
          what="work scheduled today"
          why={`Nothing in source.jobs or the ops overlay starts on ${today}. Stale scheduled jobs — a start date already past — are excluded by docs/SCOPE.md's rule and are not counted here.`}
        />
      ) : (
        <div className="flex flex-col gap-8">
          {unassigned.length > 0 && (
            <Section
              label="Needs a tech"
              aside={`${unassigned.length} of ${work.length} jobs`}
            >
              <Table
                fixed
                head={[
                  { label: "Time", className: TIME },
                  { label: "Service", className: SERVICE },
                  "Address",
                  { label: "Status", className: STATUS },
                  { label: "Job", className: JOB },
                ]}
              >
                {unassigned.map((job) => (
                  <tr key={job.job_id} className="hover:bg-hover">
                    <JobCells job={job} />
                  </tr>
                ))}
              </Table>
            </Section>
          )}

          {roster.length > 0 && (
            <Section
              label="Field techs"
              aside={`${roster.length} on the board · ${assigned} assigned`}
            >
              {/*
                One table for the whole roster, with each tech's name in a
                cell spanning that tech's rows. The columns then line up
                down the page, which a stack of one table per tech never
                manages.
              */}
              <Table
                fixed
                head={[
                  { label: "Tech", className: "w-[204px]" },
                  { label: "Time", className: TIME },
                  { label: "Service", className: SERVICE },
                  "Address",
                  { label: "Status", className: STATUS },
                  { label: "Job", className: JOB },
                ]}
              >
                {roster.map(([tech, jobs]) =>
                  jobs.map((job, index) => (
                    <tr
                      key={`${tech}-${job.job_id}`}
                      className="hover:bg-hover"
                    >
                      {index === 0 && (
                        <td
                          rowSpan={jobs.length}
                          className="border-r border-line px-5 py-2.5 align-top"
                        >
                          <div className="font-medium">{tech}</div>
                          <div className="mt-0.5 font-mono text-xs text-ink-lo">
                            {jobs.length} {jobs.length === 1 ? "job" : "jobs"}
                          </div>
                        </td>
                      )}
                      <JobCells job={job} />
                    </tr>
                  )),
                )}
              </Table>
            </Section>
          )}

          {cancelled.length > 0 && (
            <Section label="Cancelled today" aside={`${cancelled.length}`}>
              <Table
                fixed
                head={[
                  { label: "Time", className: TIME },
                  { label: "Service", className: SERVICE },
                  "Address",
                  { label: "Status", className: STATUS },
                  { label: "Job", className: JOB },
                ]}
              >
                {cancelled.map((job) => (
                  <tr key={job.job_id} className="hover:bg-hover">
                    <JobCells job={job} />
                  </tr>
                ))}
              </Table>
            </Section>
          )}
        </div>
      )}
      <p className="mt-4 text-[13px] text-ink-lo">
        A job the agent booked has no job number — the field service system
        assigns those.
      </p>
    </Screen>
  );
}
