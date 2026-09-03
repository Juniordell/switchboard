/**
 * The shared pieces. There are four of them on purpose.
 *
 * `Nothing` is the important one: when a table has no rows it says which
 * table is empty and what would put something in it. An empty state that
 * explains itself is a diagnosis; one that shows an illustration is a
 * decoration, and this is a tool an office manager uses on the phone.
 */

import type { ReactNode } from "react";

export function Screen({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="p-6">
      <div className="mb-4">
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="text-sm text-slate-500">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

export function Table({
  head,
  children,
}: {
  head: string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto rounded border border-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {head.map((h) => (
              <th key={h} className="px-3 py-2 font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}

export function Nothing({ what, why }: { what: string; why: string }) {
  return (
    <div className="rounded border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm">
      <p className="font-medium text-slate-700">No {what} yet.</p>
      <p className="mt-1 text-slate-500">{why}</p>
    </div>
  );
}

export function Pill({
  children,
  tone = "slate",
}: {
  children: ReactNode;
  tone?: "slate" | "green" | "amber" | "red";
}) {
  const tones = {
    slate: "bg-slate-100 text-slate-700",
    green: "bg-emerald-100 text-emerald-800",
    amber: "bg-amber-100 text-amber-800",
    red: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}
