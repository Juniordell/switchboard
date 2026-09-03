/** The call log: every call, and how much the agent did on it. */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, stamp } from "../api";
import { Nothing, Screen, Table } from "../components";

export function Calls() {
  const { data, isPending, error } = useQuery({
    queryKey: ["calls"],
    queryFn: api.calls,
  });

  if (isPending) return <Screen title="Calls">Loading…</Screen>;
  if (error) return <Screen title="Calls">{String(error)}</Screen>;

  return (
    <Screen title="Calls" subtitle={`${data.count} recorded`}>
      {data.count === 0 ? (
        <Nothing
          what="calls"
          why="ops.calls is empty. The agent writes a row when a call starts, so one inbound call to the number on the dispatch rule fills this."
        />
      ) : (
        <Table head={["Started", "Caller", "Last agent", "Tools", "Ended"]}>
          {data.items.map((call) => (
            <tr key={call.call_id} className="hover:bg-slate-50">
              <td className="px-3 py-2 whitespace-nowrap">
                <Link
                  className="text-blue-700 hover:underline"
                  to={`/calls/${encodeURIComponent(call.call_id)}`}
                >
                  {stamp(call.started_at)}
                </Link>
              </td>
              <td className="px-3 py-2 whitespace-nowrap tabular-nums">
                {call.caller ?? "—"}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                {call.last_agent ?? "—"}
              </td>
              <td className="px-3 py-2 tabular-nums">{call.tool_calls}</td>
              <td className="px-3 py-2 whitespace-nowrap text-slate-500">
                {call.ended_at ? stamp(call.ended_at) : "in progress"}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Screen>
  );
}
