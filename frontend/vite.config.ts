/// <reference types="vitest/config" />
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type ProxyOptions } from 'vite'

/**
 * The browser calls same-origin /v1 paths. The dev and preview servers forward them to the backend on the loopback
 * address and add nothing: no token, no CORS. A production reverse proxy does the same (frontend/docs/deployment.md).
 */
const api: Record<string, ProxyOptions> = {
  '/v1': { target: process.env.STOCK_AGENT_API_URL ?? 'http://127.0.0.1:8800', changeOrigin: false, secure: true },
}

/** The headers the production reverse proxy sends with the app; `vite preview` sends them too, so they are tested. */
export const appSecurityHeaders = {
  'Content-Security-Policy':
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
  'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: { host: '127.0.0.1', proxy: api },
  preview: { host: '127.0.0.1', proxy: api, headers: appSecurityHeaders },
  build: {
    sourcemap: false,
    rolldownOptions: {
      output: {
        // The shell's packages go to `react` and `vendor` first: otherwise `charts` captures React as a dependency of
        // recharts, and every page downloads the charts.
        codeSplitting: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler|react-router)[\\/]/, tags: ['$initial'], priority: 3 },
            { name: 'vendor', test: /node_modules/, tags: ['$initial'], priority: 2 },
            { name: 'charts', test: /node_modules[\\/](recharts|d3-|victory-vendor)/, priority: 1 },
          ],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Page tests render charts and dialogs; on a loaded machine they need more than the 5 s default.
    testTimeout: 20_000,
    include: ['src/**/*.test.{ts,tsx}', 'tools/**/*.test.ts'],
    exclude: ['**/node_modules/**'],
    css: false,
  },
})
