/**
 * The shared pieces.
 *
 * `Nothing` is still the important one: when a table has no rows it says
 * which table is empty and what would put something in it. An empty state
 * that explains itself is a diagnosis; one that shows an illustration is a
 * decoration, and this is a tool an office manager uses on the phone.
 *
 * The rest is one design language repeated: a 24px screen title over a
 * mono sub-line, 11px uppercase labels for anything that names a group,
 * mono tabular figures for anything read aloud, and one card shell —
 * 1px line, 8px radius, two-stop shadow — around every block of rows.
 */

import type { ReactNode } from "react";
import { Link } from "react-router-dom";

/** Five meanings, so a colour never has to be picked by hand. */
export type Tone = "neutral" | "ok" | "warn" | "write" | "brand";

export function Screen({
  title,
  meta,
  note,
  stats,
  back,
  children,
}: {
  title: string;
  /** Mono sub-line beside the title: a date, an id, an address. */
  meta?: ReactNode;
  /** Prose sub-line under the title. */
  note?: ReactNode;
  /** Counts pinned to the right of the header. */
  stats?: ReactNode;
  back?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex-none border-b border-line bg-surface px-6 py-[18px]">
        {back}
        <div className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1">
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">{title}</h1>
          {meta && (
            <span className="font-mono text-[13px] text-ink-lo">{meta}</span>
          )}
          {stats && (
            <div className="ml-auto flex flex-wrap items-baseline gap-x-6">
              {stats}
            </div>
          )}
        </div>
        {note && <p className="mt-1 text-ink-mid">{note}</p>}
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-6">{children}</div>
    </div>
  );
}

/** A number and what it counts, for the right-hand side of a header. */
export function Stat({ value, label }: { value: ReactNode; label: string }) {
  return (
    <span className="flex items-baseline gap-2">
      <span className="font-mono text-[13px] font-medium tabular-nums">
        {value}
      </span>
      <Label>{label}</Label>
    </span>
  );
}

/** The 11px uppercase eyebrow that names every group on every screen. */
export function Label({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-semibold tracking-[0.07em] text-ink-mid uppercase">
      {children}
    </span>
  );
}

export function Section({
  label,
  aside,
  children,
}: {
  label: string;
  /** Mono counts beside the label: how many rows, and of what. */
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2.5">
        <Label>{label}</Label>
        {aside && (
          <span className="font-mono text-xs text-ink-lo">{aside}</span>
        )}
      </div>
      {children}
    </section>
  );
}

/** The one card shell. Everything that holds rows or a verdict uses it. */
export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-line bg-surface shadow-card ${className}`}
    >
      {children}
    </div>
  );
}

type Column = { label: string; className?: string };

export function Table({
  head,
  fixed = false,
  children,
}: {
  head: (string | Column)[];
  /**
   * Fixed layout honours the column widths above, which is what lets a
   * long description ellipsise instead of pushing the job number off the
   * right edge. Leave it off for two-column field/value tables.
   */
  fixed?: boolean;
  children: ReactNode;
}) {
  const columns = head.map((h) => (typeof h === "string" ? { label: h } : h));
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface shadow-card">
      <table className={`w-full text-sm ${fixed ? "table-fixed" : ""}`}>
        <thead>
          <tr className="border-b border-line">
            {columns.map((column) => (
              <th
                key={column.label}
                className={`h-9 px-5 text-left text-[11px] font-semibold tracking-[0.07em] whitespace-nowrap text-ink-lo uppercase ${column.className ?? ""}`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

export function Nothing({ what, why }: { what: string; why: string }) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong bg-sunken px-5 py-6 text-sm">
      <p className="font-medium text-ink">No {what} yet.</p>
      <p className="mt-1.5 text-ink-mid">{why}</p>
    </div>
  );
}

const DOTS: Record<Tone, string> = {
  neutral: "bg-line-strong",
  ok: "bg-ok",
  warn: "bg-warn",
  write: "bg-write",
  brand: "bg-brand",
};

/** Status as an 8px dot. Cheaper to scan down a column than a coloured word. */
export function Dot({ tone = "neutral" }: { tone?: Tone }) {
  return (
    <span
      className={`inline-block h-2 w-2 flex-none rounded-full ${DOTS[tone]}`}
    />
  );
}

const PILLS: Record<Tone, string> = {
  neutral: "border-line bg-surface text-ink-lo",
  ok: "border-line bg-surface text-ok",
  warn: "border-line bg-surface text-warn",
  write: "border-write-line bg-write-wash text-write",
  brand: "border-wash-line bg-wash text-brand",
};

export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: Tone;
}) {
  return (
    <span
      className={`inline-flex h-[19px] items-center rounded-[5px] border px-1.5 font-mono text-[10px] font-medium tracking-[0.09em] whitespace-nowrap uppercase ${PILLS[tone]}`}
    >
      {children}
    </span>
  );
}

/**
 * Three bars for a confidence that arrives as a word or a score.
 *
 * Deliberately not a percentage: neither the warranty rule nor the
 * Reviewer measures anything a percentage would be honest about, and a
 * number invites arithmetic that the value cannot support.
 */
export function Meter({
  filled,
  tone,
  children,
}: {
  filled: 0 | 1 | 2 | 3;
  tone: Tone;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="flex gap-1">
        {[1, 2, 3].map((bar) => (
          <span
            key={bar}
            className={`h-1 w-6 rounded-sm ${bar <= filled ? DOTS[tone] : "bg-line"}`}
          />
        ))}
      </span>
      <span className="text-[13px] text-ink-mid">{children}</span>
    </div>
  );
}

/**
 * Status as a colour, for the two closed sets the loader knows.
 *
 * `docs/DECISIONS.md` 30 keeps these sets out of the database as
 * constants, so an unrecognised value must render rather than throw: it
 * falls through to neutral and still shows its own words.
 */
const WORK_STATUS_TONES: Record<string, Tone> = {
  "complete rated": "ok",
  "complete unrated": "ok",
  "in progress": "brand",
  scheduled: "neutral",
  "needs scheduling": "warn",
  "user canceled": "write",
  "pro canceled": "write",
};

const INVOICE_STATUS_TONES: Record<string, Tone> = {
  paid: "ok",
  open: "warn",
  pending_payment: "warn",
  voided: "neutral",
  canceled: "neutral",
};

export function workStatusTone(status: string): Tone {
  return WORK_STATUS_TONES[status] ?? "neutral";
}

export function invoiceStatusTone(status: string): Tone {
  return INVOICE_STATUS_TONES[status] ?? "neutral";
}

/** A status word with its dot, the pairing used in every row. */
export function Status({ status, tone }: { status: string; tone: Tone }) {
  return (
    <span className="flex items-center gap-2 whitespace-nowrap">
      <Dot tone={tone} />
      {status}
    </span>
  );
}

/** The way back off a detail screen, in the header's own type. */
export function BackLink({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      className="mb-2.5 inline-block text-[11px] font-semibold tracking-[0.07em] text-ink-lo uppercase hover:text-ink"
    >
      ← {label}
    </Link>
  );
}
