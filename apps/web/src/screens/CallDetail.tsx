/**
 * One call: what was said, and what the agent did between the words.
 *
 * The tool calls are attached to the turn they followed rather than listed
 * beside it. "The agent said X, and to say it, it called these" is the
 * question an office manager is actually asking when a caller complains.
 *
 * Turns alternate sides, caller left and agent right, the way a transcript
 * is read. Tool cards always sit on the agent's side whichever turn they
 * follow, because only the agent makes them — a lookup rendered under the
 * caller's bubble would read as the caller's doing.
 */

import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import {
  api,
  clockTime,
  elapsed,
  stamp,
  type ToolCall,
  type Turn,
} from "../api";
import {
  BackLink,
  Label,
  Nothing,
  Pill,
  Screen,
  Section,
  Stat,
} from "../components";

function attach(turns: Turn[], tools: ToolCall[]) {
  // Every tool call belongs to the last turn that had already been spoken
  // when it ran. Nothing before the first turn gets orphaned: it goes to
  // the first turn instead of disappearing.
  return turns.map((turn, index) => {
    const from = new Date(turn.created_at).getTime();
    const next = turns[index + 1];
    const until = next ? new Date(next.created_at).getTime() : Infinity;
    const mine = tools.filter((t) => {
      const at = new Date(t.created_at).getTime();
      return index === 0 ? at < until : at >= from && at < until;
    });
    return { turn, tools: mine };
  });
}

function ToolCard({ call }: { call: ToolCall }) {
  return (
    <article
      className={`rounded-lg border border-line bg-surface p-4 shadow-card ${
        call.ok ? "" : "border-l-2 border-l-write"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="font-mono text-[13px] font-medium">{call.tool}</span>
        <Pill tone={call.ok ? "neutral" : "write"}>
          {call.ok ? "ok" : "failed"}
        </Pill>
        <span className="ml-auto font-mono text-xs tabular-nums text-ink-lo">
          {clockTime(call.created_at)}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 text-[13px] text-ink-mid">
        <span>{call.agent}</span>
        <span className="font-mono tabular-nums">
          {call.duration_ms.toFixed(1)} ms
        </span>
        <span className="font-mono tabular-nums">
          {call.result_rows} {call.result_rows === 1 ? "row" : "rows"}
        </span>
        {call.timings &&
          Object.entries(call.timings).map(([phase, ms]) => (
            <span key={phase} className="font-mono tabular-nums text-ink-lo">
              {phase} {Number(ms).toFixed(1)} ms
            </span>
          ))}
      </div>
      <pre className="mt-3 overflow-x-auto rounded-md bg-sunken px-3 py-2 font-mono text-xs text-ink-mid">
        {JSON.stringify(call.args)}
      </pre>
    </article>
  );
}

function TurnRow({ turn, tools }: { turn: Turn; tools: ToolCall[] }) {
  const caller = turn.role === "user";
  return (
    <div className="flex flex-col gap-3">
      <div
        className={`flex flex-col gap-1.5 ${caller ? "items-start" : "items-end"}`}
      >
        <div className="flex items-center gap-2">
          <Label>{caller ? "Caller" : (turn.agent ?? "Agent")}</Label>
          <span className="font-mono text-xs tabular-nums text-ink-lo">
            {clockTime(turn.created_at)}
          </span>
        </div>
        <p
          className={`max-w-[88%] rounded-[10px] border px-3.5 py-2.5 ${
            caller
              ? "rounded-tl-[3px] border-line bg-sunken"
              : "rounded-tr-[3px] border-wash-line bg-wash"
          }`}
        >
          {turn.text}
        </p>
      </div>
      {tools.length > 0 && (
        <div className="flex flex-col items-end gap-2">
          {tools.map((call) => (
            <div key={call.id} className="w-[88%]">
              <ToolCard call={call} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function CallDetail() {
  const { callId = "" } = useParams();
  const { data, isPending, error } = useQuery({
    queryKey: ["call", callId],
    queryFn: () => api.call(callId),
  });

  if (isPending) return <Screen title="Call">Loading…</Screen>;
  if (error) return <Screen title="Call">{String(error)}</Screen>;

  const rows = attach(data.turns, data.tool_calls);
  const orphans = data.turns.length === 0 ? data.tool_calls : [];
  const failed = data.tool_calls.filter((call) => !call.ok).length;
  const { started_at, ended_at } = data.call;
  const length = started_at ? elapsed(started_at, ended_at ?? null) : null;

  return (
    <Screen
      back={<BackLink to="/calls" label="Calls" />}
      title={data.call.caller ?? callId}
      meta={started_at ? stamp(started_at) : callId}
      note={data.call.last_agent ? `Last agent: ${data.call.last_agent}` : null}
      stats={
        <>
          <Stat value={data.turns.length} label="Turns" />
          <Stat value={data.tool_calls.length} label="Tool calls" />
          <Stat value={failed} label="Failed" />
          {length && <Stat value={length} label="Length" />}
        </>
      }
    >
      {data.turns.length === 0 && data.tool_calls.length === 0 ? (
        <Nothing
          what="transcript or tool calls for this call"
          why="ops.transcript_turns and ops.tool_calls are both empty for this call id. Calls taken before the agent recorded transcripts have no words to show."
        />
      ) : (
        <div className="flex max-w-[900px] flex-col gap-5">
          {rows.map(({ turn, tools }) => (
            <TurnRow key={turn.seq} turn={turn} tools={tools} />
          ))}
          {orphans.length > 0 && (
            <Section
              label="Tool calls with no transcript recorded"
              aside={`${orphans.length}`}
            >
              <div className="flex flex-col gap-2">
                {orphans.map((call) => (
                  <ToolCard key={call.id} call={call} />
                ))}
              </div>
            </Section>
          )}
        </div>
      )}
    </Screen>
  );
}
