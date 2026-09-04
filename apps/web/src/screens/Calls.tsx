/** The call log: every call, and how much the agent did on it. */

import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, elapsed, stamp } from "../api";
import { Dot, Nothing, Pill, Screen, Stat, Table } from "../components";

export function Calls() {
  const navigate = useNavigate();
  const { data, isPending, error } = useQuery({
    queryKey: ["calls"],
    queryFn: api.calls,
  });

  if (isPending) return <Screen title="Calls">Loading…</Screen>;
  if (error) return <Screen title="Calls">{String(error)}</Screen>;

  const live = data.items.filter((call) => !call.ended_at).length;
  const tools = data.items.reduce((n, call) => n + call.tool_calls, 0);

  return (
    <Screen
      title="Calls"
      note="Every call, and what the agent did between the words."
      stats={
        <>
          <Stat value={data.count} label="Recorded" />
          <Stat value={live} label="In progress" tone={live ? "warn" : undefined} />
          <Stat value={tools} label="Tool calls" />
        </>
      }
    >
      {data.count === 0 ? (
        <Nothing
          what="calls"
          why="ops.calls is empty. The agent writes a row when a call starts, so one inbound call to the number on the dispatch rule fills this."
        />
      ) : (
        <div className="max-w-[1100px]">
        <Table
          fixed
          head={[
            { label: "Started", className: "w-[172px]" },
            "Caller",
            { label: "Last agent", className: "w-[140px]" },
            { label: "Tools", className: "w-[84px] text-right" },
            { label: "Ended", className: "w-[172px]" },
            { label: "Len", className: "w-[76px] text-right" },
          ]}
        >
          {data.items.map((call) => (
            <tr
              key={call.call_id}
              className="cursor-pointer hover:bg-hover"
              onClick={() => navigate(`/calls/${encodeURIComponent(call.call_id)}`)}
            >
              <td className="px-5 py-2.5 font-mono text-[13px] tabular-nums text-ink-mid">
                {stamp(call.started_at)}
              </td>
              <td className="px-5 py-2.5 font-mono text-[13px] font-medium text-brand">
                {call.caller ?? "unknown"}
                <span className="ml-2 text-ink-lo">›</span>
              </td>
              <td className="px-5 py-2.5">
                {call.last_agent ? <Pill tone="brand">{call.last_agent}</Pill> : "—"}
              </td>
              <td className="px-5 py-2.5 text-right font-mono text-[13px] tabular-nums">
                {call.tool_calls}
              </td>
              <td className="px-5 py-2.5 text-[13px] whitespace-nowrap text-ink-mid">
                {call.ended_at ? (
                  <span className="font-mono tabular-nums">
                    {stamp(call.ended_at)}
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <Dot tone="brand" />
                    in progress
                  </span>
                )}
              </td>
              <td className="px-5 py-2.5 text-right font-mono text-[13px] tabular-nums text-ink-lo">
                {elapsed(call.started_at, call.ended_at) ?? "—"}
              </td>
            </tr>
          ))}
        </Table>
        </div>
      )}
    </Screen>
  );
}
