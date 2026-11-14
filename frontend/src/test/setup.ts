import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

// findBy and waitFor wait this long before failing, so a test does not fail only because the machine is busy.
configure({ asyncUtilTimeout: 5_000 })

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  window.sessionStorage.clear()
})
