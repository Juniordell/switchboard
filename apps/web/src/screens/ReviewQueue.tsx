/** What a human still has to decide. T7.3's Reviewer fills this. */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, stamp } from "../api";
import { Nothing, Pill, Screen, Table } from "../components";

export function ReviewQueue() {
  const { data, isPending, error } = useQuery({
    queryKey: ["review_queue"],
    queryFn: api.reviewQueue,
  });

  if (isPending) return <Screen title="Review queue">Loading…</Screen>;
  if (error) return <Screen title="Review queue">{String(error)}</Screen>;

  return (
    <Screen title="Review queue" subtitle={`${data.count} open`}>
      {data.count === 0 ? (
        <Nothing
          what="items to review"
          why="ops.review_queue is empty. The Reviewer agent (T7.3) is what writes to it: anything it scores below threshold becomes a proposal here instead of a write."
        />
      ) : (
        <Table head={["Opened", "Kind", "Title", "Call", "Status"]}>
          {data.items.map((item) => (
            <tr key={item.id} className="hover:bg-slate-50">
              <td className="px-3 py-2 whitespace-nowrap">
                {stamp(item.created_at)}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">
                <Pill tone="amber">{item.kind}</Pill>
              </td>
              <td className="px-3 py-2">{item.title}</td>
              <td className="px-3 py-2 whitespace-nowrap">
                {item.call_id ? (
                  <Link
                    className="text-blue-700 hover:underline"
                    to={`/calls/${encodeURIComponent(item.call_id)}`}
                  >
                    {item.call_id}
                  </Link>
                ) : (
                  "—"
                )}
              </td>
              <td className="px-3 py-2">{item.status}</td>
            </tr>
          ))}
        </Table>
      )}
    </Screen>
  );
}
