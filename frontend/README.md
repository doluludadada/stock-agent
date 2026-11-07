# Stock Agent web

The web UI for Stock Agent: a market overview with a selectable research target, the strategy library and formula
designer, analysis runs, valuation, the watchlist, the mock account and the administrator's settings form. It reads
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
```

`just frontend-check` runs these from the repository root, and CI runs the same steps in
`.github/workflows/frontend.yml`. `bun tools/capture-screens.ts <out-dir> --url <app>`
signs in through the API and saves every page at 375, 768, 1024 and 1440 px in both themes, with an audit of each in
`audit.json`; besides signing in, it only reads.

## Browser flows (E2E)

`bun run e2e` runs the Playwright suite in `e2e/` against a real backend. Nothing in it mocks the API. Run it on your
machine before you merge a change to a page:

1. Start a backend with a disposable database and its own copy of `config/`. The local `verify-stock-agent` skill
   does this from the repository root: `prepare <run-id>`, then `serve <run-id> 8810`, both through
   `.claude/skills/verify-stock-agent/bin/verify-stock-agent`. On its first start the backend prints
   `No administrator yet. Set one up in the web app with the setup code <code>`.
2. Install the browser once: `bunx playwright install chromium`.
3. Run the suite:

   ```bash
   E2E_API_URL=http://127.0.0.1:8810 E2E_SETUP_CODE=<code> \
     E2E_SETTINGS_DIR=~/.cache/stock-agent-verify/runs/<run-id>/app/config bun run e2e
   ```

   Playwright starts the dev server on port 5199, or on `E2E_PORT`, and reuses one that is already there. Without
   `E2E_SETTINGS_DIR` it skips the test that edits a settings file on disk.

The suite is not in CI. Its specs read real market data from the backend (daily bars, the TAIEX, the TWSE and TPEX
OpenAPI archive) and start an analysis run that calls the AI provider. A CI runner would depend on those
third-party sites, and their answers change every session. Without a backend and its setup code, every test fails.

## Stack

React 19, TypeScript (strict), Vite 8, Tailwind CSS v4 (`@tailwindcss/vite`), shadcn/ui on Radix, React Router,
TanStack Query, Recharts, Motion, Lucide, i18next. Lint uses oxlint; tests use Vitest, Testing Library and Playwright.

## Where things are

- Architecture, data owners and the design system: [docs/frontend-guide.md](docs/frontend-guide.md)
- Production serving: [docs/deployment.md](docs/deployment.md)
- Screenshots before and after the 2026-11-04 redesign: [docs/screenshots/redesign/](docs/screenshots/redesign/)
- Third-party licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
