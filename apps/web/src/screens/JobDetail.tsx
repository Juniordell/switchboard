/**
 * One job: the row, its notes, and what the warranty rule concluded.
 *
 * The warranty box shows the level and the basis, never a bare yes or no.
 * `docs/AGENTS.md` requires that wherever the verdict appears, not only
 * where it is spoken — a screen that shows "covered: yes" without the
 * basis is the same mistake as an agent saying it.
 */

import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api, dollars, type Warranty } from "../api";
import { Nothing, Pill, Screen, Table } from "../components";

function WarrantyBox({ warranty }: { warranty: Warranty }) {
  const tone =
    warranty.covered === "yes"
      ? "green"
      : warranty.covered === "no"
        ? "red"
        : "amber";
  const uncertain = warranty.level >= 4;
  return (
    <div className="rounded border border-slate-200 p-3">
      <div className="flex items-baseline gap-2">
        <Pill tone={tone}>{warranty.covered}</Pill>
        <span className="text-sm font-medium text-slate-700">
          level {warranty.level}
        </span>
        <span className="text-xs text-slate-500">{warranty.confidence}</span>
      </div>
      <p className="mt-2 text-sm text-slate-700">{warranty.basis}</p>
      {warranty.evidence && (
        <p className="mt-1 text-xs text-slate-500">
          Evidence: {warranty.evidence.kind} {warranty.evidence.id}
        </p>
      )}
      {uncertain && (
        <p className="mt-2 text-xs text-amber-700">
          Levels 4 to 6 are spoken as uncertain and offered for a human to
          check. Do not quote this as settled.
        </p>
      )}
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

  return (
    <Screen
      title={`Job ${data.job.job_number ?? "(no number yet)"}`}
      subtitle={String(job.display_address ?? "")}
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Table head={["Field", "Value"]}>
            {[
              ["Status", job.work_status],
              ["Scheduled", job.scheduled_start],
              ["Completed", job.completed_at],
              ["Customer", job.customer_id],
              ["Canonical address", job.canonical_id],
              [
                "Outstanding",
                typeof job.outstanding_balance === "number"
                  ? dollars(job.outstanding_balance)
                  : null,
              ],
            ].map(([label, value]) => (
              <tr key={String(label)}>
                <td className="px-3 py-1.5 whitespace-nowrap text-slate-500">
                  {label}
                </td>
                <td className="px-3 py-1.5 font-mono text-xs text-slate-800">
                  {value === null || value === undefined ? "—" : String(value)}
                </td>
              </tr>
            ))}
          </Table>

          <div>
            <h2 className="mb-2 text-sm font-semibold text-slate-700">
              Invoices
            </h2>
            {data.invoices.length === 0 ? (
              <Nothing
                what="invoices"
                why="456 of the dataset's jobs have none. A visit without an invoice is a normal row, not a missing one."
              />
            ) : (
              <Table head={["Invoice", "Due", "Status"]}>
                {data.invoices.map((invoice) => (
                  <tr key={invoice.invoice_number}>
                    <td className="px-3 py-1.5 font-mono tabular-nums">
                      {invoice.invoice_number}
                    </td>
                    <td className="px-3 py-1.5 tabular-nums">
                      {dollars(invoice.due_amount)}
                    </td>
                    <td className="px-3 py-1.5 text-slate-600">
                      {invoice.status}
                    </td>
                  </tr>
                ))}
              </Table>
            )}
            <p className="mt-1 text-xs text-slate-400">
              Invoice numbers are a different sequence from job numbers. Never
              read one as the other.
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <h2 className="mb-2 text-sm font-semibold text-slate-700">
              Warranty
            </h2>
            {data.warranty ? (
              <WarrantyBox warranty={data.warranty} />
            ) : (
              <Nothing
                what="warranty verdict"
                why="This job's address does not resolve to a canonical address, so the precedence rule has nothing to evaluate against."
              />
            )}
          </div>

          <div>
            <h2 className="mb-2 text-sm font-semibold text-slate-700">
              Notes{" "}
              <span className="font-normal text-slate-400">
                · {data.notes.length}
              </span>
            </h2>
            {data.notes.length === 0 ? (
              <Nothing
                what="notes"
                why="No row in source.notes references this job."
              />
            ) : (
              <ul className="space-y-2">
                {data.notes.map((note) => (
                  <li
                    key={note.id}
                    className="rounded border border-slate-200 px-3 py-2 text-sm whitespace-pre-wrap text-slate-700"
                  >
                    {note.content}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-1 text-xs text-slate-400">
              Notes carry no timestamp. Any date belongs to the visit, not the
              note.
            </p>
          </div>

          {data.agent_notes && data.agent_notes.length > 0 && (
            <div>
              <h2 className="mb-2 text-sm font-semibold text-slate-700">
                Added by the agent
              </h2>
              <ul className="space-y-2">
                {data.agent_notes.map((note) => (
                  <li
                    key={note.id}
                    className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-slate-700"
                  >
                    {note.content}
                    <span className="mt-1 block text-xs text-slate-500">
                      {note.call_id}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </Screen>
  );
}
