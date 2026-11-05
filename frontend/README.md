# Stock Agent web

The web UI for Stock Agent: a market overview with a selectable research target, the strategy library and formula
designer, analysis runs, valuation, the watchlist, the mock account and the administrator's settings editor. It reads
and writes through the backend Web API on same-origin `/v1` paths. People sign in with their own account; the first
visit to a new site sets up the administrator with the code the backend prints on its console.

## Run

Requires [Bun](https://bun.sh) 1.4 or later. Start the backend first (`just run-bn` from the repository root).

```bash
cd frontend
bun install
bun run dev        # http://127.0.0.1:5173, /v1 is forwarded to http://127.0.0.1:8800
```

Or from the repository root: `just run-fn`. `STOCK_AGENT_API_URL` moves the backend address.

## Check

```bash
bun install --frozen-lockfile
bun run lint
bun run typecheck
bun run test
bun run build
bun run e2e        # Playwright against a running backend; first run: bunx playwright install chromium
```

`just frontend-check` runs the first five from the repository root. `bun tools/capture-screens.ts <out-dir> --url <app>`
signs in through the API and saves every page at 375, 768, 1024 and 1440 px in both themes, with an audit of each in
`audit.json`; besides signing in, it only reads.

## Stack

React 19, TypeScript (strict), Vite 8, Tailwind CSS v4 (`@tailwindcss/vite`), shadcn/ui on Radix, React Router,
TanStack Query, Recharts, Motion, Lucide, i18next. Lint uses oxlint; tests use Vitest, Testing Library and Playwright.

## Where things are

- Architecture, data owners and the design system: [docs/frontend-guide.md](docs/frontend-guide.md)
- Production serving: [docs/deployment.md](docs/deployment.md)
- Screenshots before and after the 2026-11-04 redesign: [docs/screenshots/redesign/](docs/screenshots/redesign/)
- Third-party licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
