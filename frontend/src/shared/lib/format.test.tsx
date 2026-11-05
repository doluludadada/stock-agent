import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import { changeLocale, initI18n } from '@/i18n'
import { useFormat } from './format'

describe('a stock volume in lots', () => {
  it('reads shares as 張 with no space in zh-TW and as lots in English', async () => {
    const i18n = initI18n('zh-TW')
    await act(() => changeLocale('zh-TW'))
    const wrapper = ({ children }: { children: ReactNode }) => <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
    const { result } = renderHook(() => useFormat(), { wrapper })

    expect(result.current.lots(37_000_000)).toBe('3.7萬張')
    expect(result.current.lots(8_234_400)).toBe('8,234張')
    expect(result.current.lots(600)).toBe('1張')

    await act(() => changeLocale('en'))
    expect(result.current.lots(37_000_000)).toBe('37K lots')
    expect(result.current.lots(8_234_400)).toBe('8,234 lots')
  })

  it('says the session of a price that is not the latest', async () => {
    const i18n = initI18n('zh-TW')
    await act(() => changeLocale('zh-TW'))
    const wrapper = ({ children }: { children: ReactNode }) => <I18nextProvider i18n={i18n}>{children}</I18nextProvider>
    const { result } = renderHook(() => useFormat(), { wrapper })
    expect(result.current.closeOn('2026-11-02')).toBe('11/2 收盤')
  })
})
