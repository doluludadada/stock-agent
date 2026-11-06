import type { Follow, Signal } from './api'

/** A decision's place in the follows of its run: open while a follow may take it, followed once a follow order of it filled. */
export type FollowMark = 'open' | 'followed'

/** Each decision's mark; one a follow filled before the account's last reset is open again, so open wins. */
export function followMarks(follow: Follow): ReadonlyMap<string, FollowMark> {
  const marks = new Map<string, FollowMark>()
  for (const { decision, order } of follow.follows) {
    if (decision.followed_decision_id && order.filled_quantity > 0) marks.set(decision.followed_decision_id, 'followed')
  }
  for (const id of follow.open_decision_ids) marks.set(id, 'open')
  return marks
}

/** The run's decisions a follow takes now, in the server's order. */
export function openDecisions(follow: Follow, decisions: readonly Signal[]): Signal[] {
  const byId = new Map(decisions.map((decision) => [decision.decision_id, decision]))
  return follow.open_decision_ids.flatMap((id) => byId.get(id) ?? [])
}
