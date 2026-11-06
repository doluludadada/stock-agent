import type { Follow } from './api'
import { followMarks } from './model'

type Item = Follow['follows'][number]

const item = (followedDecisionId: string, filled: number): Item =>
  ({
    decision: { decision_id: `follow-of-${followedDecisionId}-${filled}`, followed_decision_id: followedDecisionId },
    order: { filled_quantity: filled },
  }) as unknown as Item

describe('each decision’s follow mark', () => {
  it('is followed once a follow order of it filled, and stays unmarked after a follow that filled nothing', () => {
    const marks = followMarks({ refusal: 'nothing_to_follow', open_decision_ids: [], follows: [item('buy', 1000), item('sell', 0)] })

    expect(marks.get('buy')).toBe('followed')
    expect(marks.has('sell')).toBe(false)
  })

  it('is open again after a reset of the account, even though a follow of it filled before', () => {
    const marks = followMarks({ refusal: null, open_decision_ids: ['buy'], follows: [item('buy', 1000)] })

    expect(marks.get('buy')).toBe('open')
  })
})
