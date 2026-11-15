import { fitsSegmented } from './segmented'

describe('a row of buttons or a list', () => {
  it('keeps as buttons what a phone’s row shows whole, and lists the rest', () => {
    expect(fitsSegmented(['Off', '09:05', '09:30', '10:00', '13:00']), 'the schedule’s times as shipped').toBe(true)
    expect(fitsSegmented(['Off', '09:05', '09:30', '10:00', '11:00', '13:00'])).toBe(false)
    expect(fitsSegmented(['Off', 'Administrators', 'Everyone'])).toBe(true)
    expect(fitsSegmented(['OpenAI', 'Grok', 'Gemini', 'Groq', 'Claude'])).toBe(false)
  })
})
