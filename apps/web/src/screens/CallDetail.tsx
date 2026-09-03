/**
 * One call: what was said, and what the agent did between the words.
 *
 * The tool calls are attached to the turn they followed rather than listed
 * beside it. "The agent said X, and to say it, it called these" is the
 * question an office manager is actually asking when a caller complains.
 */

import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api, clockTime, type ToolCall, type Turn } from "../api";
import { Nothing, Pill, Screen } from "../components";

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

function ToolRow({ call }: { call: ToolCall }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-l-2 border-slate-200 py-1 pl-3 text-xs">
      <Pill tone={call.ok ? "green" : "red"}>{call.ok ? "ok" : "failed"}</Pill>
      <span className="font-mono font-medium text-slate-800">{call.tool}</span>
      <span className="text-slate-400">{call.agent}</span>
      <span className="tabular-nums text-slate-500">
        {call.duration_ms.toFixed(1)} ms
      </span>
      <span className="text-slate-500">{call.result_rows} rows</span>
      {call.timings &&
        Object.entries(call.timings).map(([k, v]) => (
          <span key={k} className="tabular-nums text-slate-400">
            {k} {Number(v).toFixed(1)} ms
          </span>
        ))}
      <code className="w-full text-slate-500">{JSON.stringify(call.args)}</code>
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

  return (
    <Screen
      title={data.call.caller ?? callId}
      subtitle={`${data.turns.length} turns · ${data.tool_calls.length} tool calls`}
    >
      {data.turns.length === 0 && data.tool_calls.length === 0 ? (
        <Nothing
          what="transcript or tool calls for this call"
          why="ops.transcript_turns and ops.tool_calls are both empty for this call id. Calls taken before the agent recorded transcripts have no words to show."
        />
      ) : (
        <div className="space-y-4">
          {rows.map(({ turn, tools }) => (
            <div key={turn.seq}>
              <div className="flex items-baseline gap-2">
                <span className="w-14 shrink-0 text-xs tabular-nums text-slate-400">
                  {clockTime(turn.created_at)}
                </span>
                <span
                  className={`w-20 shrink-0 text-xs font-medium ${
                    turn.role === "user" ? "text-slate-900" : "text-blue-700"
                  }`}
                >
                  {turn.role === "user" ? "Caller" : (turn.agent ?? "Agent")}
                </span>
                <p className="text-sm text-slate-800">{turn.text}</p>
              </div>
              {tools.length > 0 && (
                <div className="mt-1 ml-36 space-y-1">
                  {tools.map((t) => (
                    <ToolRow key={t.id} call={t} />
                  ))}
                </div>
              )}
            </div>
          ))}
          {orphans.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs text-slate-500">
                Tool calls with no transcript recorded:
              </p>
              {orphans.map((t) => (
                <ToolRow key={t.id} call={t} />
              ))}
            </div>
          )}
        </div>
      )}
    </Screen>
  );
}
