/**
 * What a human still has to decide. T7.3's Reviewer fills this.
 *
 * A row per item would waste the payload the Reviewer writes: it already
 * says why it queued the call, which promises it could not find a write
 * behind, and how sure it was. Those are the three things the person
 * clearing this queue is about to go looking for, so they are on the card.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, stamp, type ReviewItem } from "../api";
import {
  Card,
  Label,
  Meter,
  Nothing,
  Pill,
  Screen,
  Stat,
} from "../components";

/**
 * The payload is the Reviewer's own JSON, so it is read defensively: a
 * missing key means that model call said nothing on the subject, which is
 * not an error and must not blank the card.
 */
function strings(payload: Record<string, unknown>, key: string): string[] {
  const value = payload[key];
  return Array.isArray(value) ? value.filter((v) => typeof v === "string") : [];
}

function confidence(payload: Record<string, unknown>): number | null {
  const value = payload.confidence;
  return typeof value === "number" ? value : null;
}

function List({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mt-3.5">
      <Label>{label}</Label>
      <ul className="mt-1.5 flex flex-col gap-1">
        {items.map((item) => (
          <li
            key={item}
            className="border-l-2 border-line-strong pl-3 text-ink-mid"
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Item({ item }: { item: ReviewItem }) {
  const score = confidence(item.payload);
  const promises = strings(item.payload, "open_promises");
  return (
    <Card
      className={`p-5 ${promises.length > 0 ? "border-l-2 border-l-warn" : ""}`}
    >
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="font-semibold">{item.title}</span>
        <Pill tone="warn">{item.kind}</Pill>
        <Pill>{item.status}</Pill>
        <span className="ml-auto font-mono text-xs text-ink-lo">
          {stamp(item.created_at)}
          {item.call_id && (
            <>
              {" · "}
              <Link
                className="text-brand hover:text-brand-hover hover:underline"
                to={`/calls/${encodeURIComponent(item.call_id)}`}
              >
                {item.call_id}
              </Link>
            </>
          )}
        </span>
      </div>

      <List
        label="Why it was queued"
        items={strings(item.payload, "reasons")}
      />
      <List label="Promises with no write behind them" items={promises} />
      <List label="Problems" items={strings(item.payload, "problems")} />
      <List label="Missed" items={strings(item.payload, "missed")} />

      {score !== null && (
        <div className="mt-4">
          <Meter
            filled={score >= 0.8 ? 3 : score >= 0.5 ? 2 : 1}
            tone={score >= 0.8 ? "ok" : "warn"}
          >
            Reviewer confidence {score.toFixed(2)}
          </Meter>
        </div>
      )}
    </Card>
  );
}

export function ReviewQueue() {
  const { data, isPending, error } = useQuery({
    queryKey: ["review_queue"],
    queryFn: api.reviewQueue,
  });

  if (isPending) return <Screen title="Review">Loading…</Screen>;
  if (error) return <Screen title="Review">{String(error)}</Screen>;

  const unbacked = data.items.filter(
    (item) => strings(item.payload, "open_promises").length > 0,
  ).length;

  return (
    <Screen
      title="Review"
      note="Agent proposals waiting on a human."
      stats={
        <>
          <Stat value={data.count} label="Open" />
          <Stat value={unbacked} label="Unbacked promises" />
        </>
      }
    >
      {data.count === 0 ? (
        <Nothing
          what="items to review"
          why="ops.review_queue is empty. The Reviewer agent (T7.3) is what writes to it: anything it scores below threshold becomes a proposal here instead of a write."
        />
      ) : (
        <div className="flex max-w-[900px] flex-col gap-3">
          {data.items.map((item) => (
            <Item key={item.id} item={item} />
          ))}
        </div>
      )}
    </Screen>
  );
}
