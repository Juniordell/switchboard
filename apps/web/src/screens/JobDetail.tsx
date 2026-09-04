/**
 * One job: the row, its notes, and what the warranty rule concluded.
 *
 * The warranty section shows the level and the basis, never a bare yes or
 * no. `docs/AGENTS.md` requires that wherever the verdict appears, not only
 * where it is spoken — a screen that shows "covered: yes" without the
 * basis is the same mistake as an agent saying it. So it is two cards: the
 * verdict, and beside it the evidence the verdict was read off.
 */

import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api, dollars, stamp, type Warranty } from "../api";
import {
  BackLink,
  Card,
  Dot,
  invoiceStatusTone,
  Label,
  Meter,
  Nothing,
  Screen,
  Section,
  Stat,
  Status,
  Table,
  workStatusTone,
  type Tone,
} from "../components";

const COVERAGE_TONES: Record<string, Tone> = {
  yes: "ok",
  no: "write",
  was_covered: "warn",
  unknown: "neutral",
};

/**
 * Confidence arrives as one of four words, so the meter reads them rather
 * than a score. `high_historical` is as certain as `high` about a fact in
 * the past tense, which is a caveat for the prose, not for the bars.
 */
const CONFIDENCE_BARS: Record<string, 0 | 1 | 2 | 3> = {
  high: 3,
  high_historical: 3,
  medium: 2,
  unknown: 1,
};

function WarrantyCard({ warranty }: { warranty: Warranty }) {
  const tone = COVERAGE_TONES[warranty.covered] ?? "neutral";
  const uncertain = warranty.level >= 4;
  if (uncertain) {
    // Levels 4-6 have no single row behind them and are spoken as
    // uncertain. Two cards and an empty meter gave "we do not know" the
    // most prominent block on the page; one line says it honestly.
    return (
      <Card className="flex flex-wrap items-center gap-x-3 gap-y-1 border-l-2 border-l-warn px-5 py-3.5">
        <Dot tone={tone} />
        <span className="font-semibold">{warranty.covered.replace("_", " ")}</span>
        <span className="font-mono text-[13px] text-ink-mid">level {warranty.level}</span>
        <span className="text-ink-mid">{warranty.basis}</span>
        <span className="basis-full text-[13px] text-warn">
          Spoken as uncertain and offered for a human to check. Not settled.
        </span>
      </Card>
    );
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-2.5">
          <Dot tone={tone} />
          <span className="text-[15px] font-semibold">
            {warranty.covered.replace("_", " ")}
          </span>
          <span className="font-mono text-[13px] text-ink-mid">
            level {warranty.level}
          </span>
        </div>
        <p className="mt-3 text-ink-mid">{warranty.basis}</p>
        <div className="mt-4">
          <Meter
            filled={CONFIDENCE_BARS[warranty.confidence] ?? 1}
            tone={tone}
          >
            {warranty.confidence.replace("_", " ")} confidence
          </Meter>
        </div>
      </Card>
      <div className="rounded-lg border border-line bg-sunken p-5">
        <Label>Basis for this answer</Label>
        {warranty.evidence ? (
          <p className="mt-3 font-mono text-[13px]">
            {warranty.evidence.kind} {warranty.evidence.id}
          </p>
        ) : (
          <p className="mt-3 text-[13px] text-ink-lo">
            No single row carries the verdict; it follows from the precedence
            rule rather than from one record.
          </p>
        )}
        {uncertain && (
          <p className="mt-3 text-[13px] text-warn">
            Levels 4 to 6 are spoken as uncertain and offered for a human to
            check. Do not quote this as settled.
          </p>
        )}
      </div>
    </div>
  );
}

export function JobDetail() {
  const { jobId = "" } = useParams();
  const { data, isPending, error } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId),
  });

  if (isPending) return <Screen title="Job">Loading…</Screen>;
  if (error) return <Screen title="Job">{String(error)}</Screen>;

  const job = data.job as Record<string, string | number | null>;
  const address = String(job.display_address ?? "").trim();
  const number = data.job.job_number ?? "no number yet";
  const balance = job.outstanding_balance;
  const outstanding = typeof balance === "number" ? balance : null;

  return (
    <Screen
      back={<BackLink to="/jobs" label="Jobs" />}
      title={address || `Job ${number}`}
      meta={`Job ${number} · ${data.job.customer ?? job.customer_id ?? "no customer"}`}
      note={job.description ? String(job.description) : null}
      stats={
        <>
          {outstanding !== null && (
            <Stat value={dollars(outstanding)} label="Outstanding" />
          )}
          <Stat value={data.invoices.length} label="Invoices" />
          <Stat value={data.notes.length} label="Notes" />
        </>
      }
    >
      <div className="flex max-w-[1080px] flex-col gap-8">
        <Section label="Warranty coverage">
          {data.warranty ? (
            <WarrantyCard warranty={data.warranty} />
          ) : (
            <Nothing
              what="warranty verdict"
              why="This job's address does not resolve to a canonical address, so the precedence rule has nothing to evaluate against."
            />
          )}
        </Section>

        <Section label="The job">
          <Table head={[{ label: "Field", className: "w-[220px]" }, "Value"]}>
            <tr>
              <td className="px-5 py-2 text-ink-mid">Status</td>
              <td className="px-5 py-2">
                <Status
                  status={String(job.work_status ?? "—")}
                  tone={workStatusTone(String(job.work_status ?? ""))}
                />
              </td>
            </tr>
            {[
              ["Customer", data.job.customer ?? job.customer_id],
              ["Address", address || null],
              [
                "Scheduled",
                job.scheduled_start ? stamp(String(job.scheduled_start)) : null,
              ],
              [
                "Completed",
                job.completed_at ? stamp(String(job.completed_at)) : null,
              ],
            ].map(([label, value]) => (
              <tr key={String(label)}>
                <td className="px-5 py-2 whitespace-nowrap text-ink-mid">
                  {label}
                </td>
                <td className="px-5 py-2 text-[13px]">
                  {value === null || value === undefined ? "—" : String(value)}
                </td>
              </tr>
            ))}
          </Table>
        </Section>

        <Section label="Invoices" aside={`${data.invoices.length}`}>
          {data.invoices.length === 0 ? (
            <Nothing
              what="invoices"
              why="456 of the dataset's jobs have none. A visit without an invoice is a normal row, not a missing one."
            />
          ) : (
            <Table
              fixed
              head={[
                { label: "Invoice", className: "w-[160px]" },
                { label: "Due", className: "w-[140px] text-right" },
                "Status",
              ]}
            >
              {data.invoices.map((invoice) => (
                <tr key={invoice.invoice_number} className="hover:bg-hover">
                  <td className="px-5 py-2.5 font-mono text-[13px] tabular-nums">
                    {invoice.invoice_number}
                  </td>
                  <td className="px-5 py-2.5 text-right font-mono text-[13px] font-medium tabular-nums">
                    {dollars(invoice.due_amount)}
                  </td>
                  <td className="px-5 py-2.5">
                    <Status
                      status={invoice.status}
                      tone={invoiceStatusTone(invoice.status)}
                    />
                  </td>
                </tr>
              ))}
            </Table>
          )}
          <p className="mt-2 text-[13px] text-ink-lo">
            Invoice numbers are a different sequence from job numbers. Never
            read one as the other.
          </p>
        </Section>

        <Section label="Tech notes" aside={`${data.notes.length}`}>
          {data.notes.length === 0 ? (
            <Nothing
              what="notes"
              why="No row in source.notes references this job."
            />
          ) : (
            <div className="flex flex-col gap-3">
              {data.notes.map((note) => (
                <Card key={note.id} className="p-4">
                  <p className="whitespace-pre-wrap text-ink-mid">
                    {note.content}
                  </p>
                </Card>
              ))}
            </div>
          )}
          <p className="mt-2 text-[13px] text-ink-lo">
            Notes carry no timestamp. Any date belongs to the visit, not the
            note.
          </p>
        </Section>

        {data.agent_notes && data.agent_notes.length > 0 && (
          <Section
            label="Added by the agent"
            aside={`${data.agent_notes.length}`}
          >
            <div className="flex flex-col gap-3">
              {data.agent_notes.map((note) => (
                <Card key={note.id} className="border-l-2 border-l-write p-4">
                  <p className="whitespace-pre-wrap text-ink-mid">
                    {note.content}
                  </p>
                  <p className="mt-2 font-mono text-xs text-ink-lo">
                    {note.call_id}
                  </p>
                </Card>
              ))}
            </div>
          </Section>
        )}
      </div>
    </Screen>
  );
}
