# How to deploy the site

The browser loads the built web app and calls same-origin `/v1` paths. One reverse proxy serves both: the static files
of `frontend/dist`, and `/v1` forwarded to the backend. No CORS is needed, and none should be added.

This guide has two procedures. Use Docker Compose on a server. Use the manual procedure only when Docker is not an
option.

## Deploy with Docker Compose

`compose.yml` runs three containers on one network, named `stock-agent-database`, `stock-agent-backend` and
`stock-agent-frontend` after their services:

- `database` is PostgreSQL 18 with pgvector, built from `database/Dockerfile`. It publishes no port.
- `backend` is the Web API, as a user without root rights, with one worker. It publishes no port. The image also holds
  the project's commands, and `pg_dump` and `pg_restore` for the database commands. It runs with a terminal, so its
  log keeps its colours, and the log leaves out the answered status requests of the health check.
- `frontend` is Caddy with the production bundle of the web app, the site's reverse proxy. It forwards only `/v1/*` to the backend, so the API docs
  (`/docs`, `/redoc`, `/openapi.json`) are not reachable. It is the only container that publishes a port.

Everything the site saves lives in one folder on the host, the state folder: the settings in `config/`, the accounts
key in `secrets/`, `backups/`, `.settings-admin/`, and the PostgreSQL data in `postgres/`. The site
reads its settings from the `config/` of the state folder, not from the checkout. So the settings editor and your own
edits never change a file that Git tracks, and `git pull` never meets a local change.

You need Docker Engine with the Compose plugin, Git, and Tailscale. Your user must be in the `docker` group.

### Start the site for the first time

1. Clone the repository on the server, and go to its root.

   ```bash
   git clone <repository-url> stock-agent
   cd stock-agent
   ```

2. Create the state folder, readable only by your user, and copy the shipped settings into it.

   ```bash
   sudo install -d -m 700 -o "$(id -u)" -g "$(id -g)" /srv/stock-agent-state
   cp -R config /srv/stock-agent-state/config
   ```

3. Create `.env`, and keep it private.

   ```bash
   cp .env.example .env
   chmod 600 .env
   ```

4. Set these values in `.env`:

   - The key of the active AI model, for example `ANTHROPIC_API_KEY`. Without it, the backend stops at startup.
   - `STATE_DIR="/srv/stock-agent-state"`.
   - `DB_USER="stock_agent"` and `DB_NAME="stock_agent"`.
   - `DB_PASSWORD`, a new password. The command `openssl rand -hex 24` prints one. The first start creates the
     database with this password, so do not change it afterwards.
   - `SITE_NAME`, the name of the server in the tailnet, for example `my-server.my-tailnet.ts.net`. The command
     `tailscale status --self --json | grep DNSName` prints it.
   - `PROXY_BIND`, the Tailscale address of the server. The command `tailscale ip -4` prints it.
   - `APP_UID` and `APP_GID`, only if `id -u` or `id -g` does not print `1000`.

   Leave `DB_HOST` and `DB_PORT` unset: `compose.yml` sets both. Leave the production Shioaji credentials out for
   now: [Connect the real SinoPac account](#connect-the-real-sinopac-account) adds them.

5. Change two settings in `/srv/stock-agent-state/config/appsetting.yaml`. Change the existing line, and add the
   `api` section at the end of the file.

   ```yaml
   environment: test

   api:
     allowed_hosts: [127.0.0.1, localhost, my-server.my-tailnet.ts.net]
   ```

   `environment: test` turns off the API docs in the backend. `api.allowed_hosts` must hold the value of `SITE_NAME`,
   or every `/v1` request answers 400. Keep `127.0.0.1`: the health check of the container uses it.

6. Build and start the site.

   ```bash
   docker compose up -d --build
   ```

   The first build takes several minutes. The first start creates the `vector` extension and every table of the
   empty database at the schema version of the code, so no migration is needed. When the command returns, `docker compose ps` shows `database` and
   `backend` as `healthy`. If `backend` is `unhealthy`, `docker compose logs backend` names the setting to change.

7. Read the one-time setup code. The backend prints it while no user exists, and makes a new one at each start.

   ```bash
   docker compose logs backend | grep "setup code"
   ```

8. Open `http://<SITE_NAME>:8080` in a browser on a device in the tailnet. The page offers the first-time setup.
   Enter a username, your email address, a password, and the setup code. You are now the administrator.

Registration is closed (`accounts.registration_open: false`). To let another person register, turn the setting on in
the settings editor, and turn it off again afterwards.

The site now answers over plain http, on the Tailscale address only. Tailscale encrypts the traffic between the
devices of the tailnet, but the browser treats the site as not secure, and the session cookie is not marked `Secure`.
After a restart of the server, Docker can start before Tailscale has its address. The proxy then fails to start: run
`docker compose up -d` again. The HTTPS mode below does not have this problem.

### Add the home network

A person on the server's home network who has no Tailscale reaches the site at the server's address there, over plain
http. Nothing encrypts what that browser sends, the password of the sign-in included, so do this only on a network
whose every device you trust.

1. Set both lines in `.env`, with the server's address on the home network. The command `ip -4 addr` prints it.

   ```bash
   COMPOSE_FILE="compose.yml:compose.lan.yml"
   LAN_NAME="192.168.1.10"
   ```

2. Add the same address to `api.allowed_hosts` in `config/appsetting.yaml` of `STATE_DIR`.

3. Start the site again with `docker compose up -d`, and open `http://<LAN_NAME>:8080` on a device of that network.

The address must stay the same, so reserve it for the server in the router. Sign-in with Google does not work at
this address, because `accounts.public_origin` names one address only.

### Change to HTTPS

1. Turn on HTTPS certificates for the tailnet, on the DNS page of the Tailscale admin console.

2. Set `PROXY_BIND="127.0.0.1"` in `.env`, and restart the `frontend` service on the loopback address.

   ```bash
   docker compose up -d
   ```

3. Publish the proxy in the tailnet over HTTPS.

   ```bash
   sudo tailscale serve --bg 8080
   ```

   The command prints the address of the site, `https://<SITE_NAME>`. Tailscale stores this configuration, so it
   survives a restart of the server.

4. Check that the proxy passes the scheme to the backend. Sign in at `https://<SITE_NAME>`, then open the cookies of
   the site in the developer tools of the browser. The cookie `stock_agent_session` must be marked `Secure`. If it is
   not, the proxy does not read the headers of `tailscale serve`: compare the gateway address in
   `frontend/Caddyfile` with the output of `docker network inspect stock-agent_site`.

### Add sign-in with Google

Google accepts a redirect URI only over https, at a host name under a public suffix. The `ts.net` name of the server
behind `tailscale serve` meets both rules, so change to HTTPS first.

1. Create the OAuth client in the Google Cloud Console. [Set up sign-in with
   Google](../../docs/web-integration.md#set-up-sign-in-with-google) has the steps. The authorized redirect URI is
   `https://<SITE_NAME>/v1/auth/google/callback`.

2. Add the client to `.env`.

   ```bash
   GOOGLE_CLIENT_ID="<client ID>"
   GOOGLE_CLIENT_SECRET="<client secret>"
   ```

3. In `/srv/stock-agent-state/config/appsetting.yaml`, set these two settings under `accounts`. `api.allowed_hosts`
   already names `<SITE_NAME>`.

   ```yaml
   accounts:
     public_origin: "https://<SITE_NAME>"
     google_administrator_emails: ["<your Gmail address>"]
   ```

   If the file comes from an earlier version, also copy `google_issuer`, `google_authorization_endpoint` and
   `google_token_endpoint` of `accounts` from `config/appsetting.yaml` of the repository. Google's addresses have no
   default, so without them the backend starts, offers no sign-in with Google, and names the three in one log line.
   The other `google_` settings run on their defaults.

4. Start the backend on the new environment.

   ```bash
   docker compose up -d
   ```

5. Open `https://<SITE_NAME>/sign-in` and click **Sign in with Google**. On a site with no user, the first-time setup
   page shows the same link, and the sign-in creates the administrator.

Your Google account has no password in the app. The CLI needs one. To set a password, run the `reset-password`
command of the table in the next section:

```bash
docker compose exec backend python -m d_presentation.cli.reset_password <username or email>
```

### Connect the real SinoPac account

The site logs in to one SinoPac server at a time, the one `shioaji.server` names: `simulation`, SinoPac's
paper-trading server with no real money, or `production`, the real account with real money. The server can hold both
key sets, and an administrator switches between them on the SinoPac account page without a restart. Environment
`test` and `prod` may switch; `dev` logs in to the simulation server only and refuses to start with a production key
set.

1. Put the CA certificate in the state folder, readable only by the user that owns it.

   ```bash
   install -m 600 Sinopac.pfx "$STATE_DIR/secrets/Sinopac.pfx"
   ```

2. Add the production credentials to `.env`, next to the `*_TEST` pair, which stays. The backend's working folder is
   the state folder, `/state` in the container, so the certificate's path starts there.

   ```dotenv
   SHIOAJI_API_KEY="..."
   SHIOAJI_SECRET_KEY="..."
   SHIOAJI_CA_PATH="/state/secrets/Sinopac.pfx"
   SHIOAJI_CA_PASSWORD="..."
   SHIOAJI_PERSON_ID="..."
   ```

3. Restart the backend once, so it reads the new `.env`. It still logs in to the server `shioaji.server` names.

   ```bash
   docker compose up -d --force-recreate backend
   ```

4. Open the SinoPac account page as an administrator. The panel at the top names the server and lists the production
   variables the server still lacks, by name. While one is missing, the switch to production stays off.

5. Choose **Switch to production**. The dialog says what changes, asks for your password (or a fresh Google sign-in
   for an administrator without one), and asks you to type 「正式環境」. The save writes `features.sinopac_ordering` off
   first, then the server, and the site logs in to production at once: the realtime quotes come from the production
   login too, and the login on the simulation server stays open until the backend stops, for a switch back. The switch
   is refused while a production variable is missing and while `accounts.registration_open` is on, and ordering then
   stays off on the simulation server. A run that started on the simulation login never orders after the switch, even
   once ordering is on again.

6. Read the backend's log. `Logged in to Shioaji production for realtime quotes` and `SinoPac production connected`
   say the login and the account check passed, the certificate included. `SinoPac production orders unavailable`
   names what failed instead, without the server's words.

   ```bash
   docker compose logs backend | grep -i -E "shioaji|sinopac"
   ```

A switch enables no order by itself. To let the site order on the real account, an administrator turns ordering on
in the same panel, which asks for the password again. Each order then still needs an administrator who chooses
SinoPac for that run, and stays within `trading.max_order_value` and `trading.max_daily_buy_value`. A ranking follow,
by hand or by schedule, never orders on production. To go back, choose **Switch to simulation**: ordering turns off
again. A run that started before a switch keeps the login of the server it started on, and its orders are refused
while the settings name the other server. If the server is switched back while that run still goes on, its orders
pass again once ordering is turned on, so wait for the run to end before you switch back.

Keep `environment` as it is. `prod` changes more than the server: it reads the accounts key from `ACCOUNTS_KEY` only,
so a switch of the environment on a site whose key lives in `secrets/accounts.key` locks every account.

### Run a command of the project

The server has no `just` and no `uv`. Each command of the `justfile` runs inside the `backend` container instead.
Use `docker compose exec` while the backend runs. Use `docker compose run --rm` when the backend is stopped or does
not start.

| `justfile` recipe | On the server |
| --- | --- |
| `just db-status` | `docker compose run --rm backend python -m d_presentation.cli.database status` |
| `just db-backup` | `docker compose exec backend python -m d_presentation.cli.database backup` |
| `just db-migrate` | `docker compose run --rm backend python -m d_presentation.cli.database migrate` |
| `just db-restore backups/<file> --yes` | `docker compose run --rm backend python -m d_presentation.cli.database restore backups/<file> --yes` |
| `just reset-password <login>` | `docker compose exec backend python -m d_presentation.cli.reset_password <login>` |
| `just backfill-history 2017-01-01` | `docker compose exec backend python -m d_presentation.cli.backfill_history 2017-01-01` |
| `just ranking` | `docker compose exec backend python -m d_presentation.cli.ranking latest` |
| `just ranking-backtest <first> <last>` | `docker compose exec backend python -m d_presentation.cli.ranking backtest <first> <last>` |
| `just archive-closes` | `docker compose exec backend python -m d_presentation.cli.archive_closes` |
| `just backfill-articles` | `docker compose exec backend python -m d_presentation.cli.article_store` |
| `just backfill-company-background --top 20` | `docker compose exec backend python -m d_presentation.cli.company_background --top 20` |

The working folder of each command is the state folder, so `backups/<file>` names a file in its `backups/`.
[Database migrations](../../docs/database-migrations.md) describes the four database commands.

### Back up the site

A backup is three things: a dump of the database, the state folder without the live PostgreSQL data, and `.env`.
Without `secrets/accounts.key` from the state folder, no one can sign in again, and a new key does not help.

1. Dump the database. The command writes `backups/<DB_NAME>.<time>.v<N>.dump` in the state folder.

   ```bash
   docker compose exec backend python -m d_presentation.cli.database backup
   ```

2. Archive the state folder and `.env` into a folder of their own outside the checkout, and move the archives off
   the server. The archives hold the accounts key, the broker's certificate and every dump, so the folder is root's
   alone (mode 700) and each archive is readable by root only (mode 600). The archive leaves out `postgres/`, because
   a copy of the files of a running database is not a backup. The dump from step 1 is.

   ```bash
   sudo install -d -m 700 /srv/stock-agent-backups
   sudo sh -c 'umask 077 && tar -C /srv --exclude=stock-agent-state/postgres -czf "/srv/stock-agent-backups/stock-agent-state-$(date +%F).tar.gz" stock-agent-state'
   sudo install -m 600 .env "/srv/stock-agent-backups/stock-agent-env-$(date +%F)"
   ```

To restore on a new server, extract the archive to `/srv`, and put `.env` back. Then restore the dump into the empty
database, and start the site. The first command also starts PostgreSQL, which creates the empty database, and the
restore gives the database the `vector` extension before its tables.

```bash
docker compose run --rm backend python -m d_presentation.cli.database restore backups/<file> --yes
docker compose up -d --build
```

### Update the site

1. Get the new version, then rebuild and restart.

   ```bash
   git pull
   docker compose up -d --build
   ```

   The state folder outlives the containers, so the data stays and every user stays signed in.

2. Compare the shipped settings with yours. A new version can add a setting, a prompt, or a built-in strategy, and
   nothing copies it into the state folder.

   ```bash
   diff -ru config /srv/stock-agent-state/config
   ```

   A setting your file does not set, such as the `features` section of a file copied before it existed, runs on
   its default without a word in the log, and a save in the settings page writes it into your file. An address
   has no default, so a log line at the start says what the site goes without until your file sets
   it: no sign-in with Google without Google's three addresses. Copy those from `config/appsetting.yaml`. A line
   of its own names the prompts your `instructions.yaml` does not set: what each feeds is off until the file sets it,
   so a stock page offers no AI brief without `stock_brief_prompt`. Copy them from `config/instructions.yaml`; the
   site reads the file again within a few seconds, with no restart. Another line names any setting
   your file still sets that the app no longer reads: the app ignores it, and you can delete it. If `backend` does not become healthy and `docker compose logs backend` names a setting with
   `Field required`, that setting has no default: copy it from `config/appsetting.yaml` into your file, and run
   `docker compose up -d` again.

   The company background (the main business from MOPS, the annual reports, the company card and the site's own
   writing) is off on a file that lacks its settings, and the start names each missing one:
   `sources.mops.company_basics_url` and its two neighbours, the `sources.annual_reports` section,
   `stock_page.system_writing.daily_ai_calls`, the new field names of `sources.exchange.company_profiles`, and the
   prompt `company_card_prompt`. Copy them from the shipped files, with `sources.mops.request_interval_seconds: 5.0`
   and the shipped `stock_brief_prompt`. [README.md](../../README.md#company-background-and-the-sites-own-writing)
   describes each.

   The world news and the day's world brief are off on a file that lacks their settings, and the start names each:
   `sources.world.news_feeds` and `sources.world.indicator_feeds` in `appsetting.yaml`, and the prompt
   `world_brief_prompt` with `world_brief_query` in `instructions.yaml`. Copy the `sources.world` section and the two
   prompts from the shipped files. The brief also needs the site's own writing
   (`stock_page.system_writing.daily_ai_calls` above 0), since it spends one of its AI calls a day.
   [README.md](../../README.md#world-news-and-the-days-world-brief) describes each.

3. If `docker compose logs backend` names an older database schema, upgrade the database. The command dumps the
   database first.

   ```bash
   docker compose stop backend
   docker compose run --rm backend python -m d_presentation.cli.database migrate
   docker compose up -d
   ```

### Update to the vectors in PostgreSQL (schema version 14)

From schema version 14 the database holds what Chroma held: the article index's vectors (`article_vectors`) and the
LINE chat's conversations (`chat_conversations`). The vectors use the `vector` extension of pgvector, so the database
runs on an image of its own, `database/Dockerfile`: `postgres:18.7` with PGDG's `postgresql-18-pgvector` at a pinned
version. The data folder `postgres/` stays as it is, because the new image runs the same PostgreSQL 18.7. Nothing is
copied from `chroma_data/`: the article index computes its vectors again from the kept articles, Chroma held no
conversation on the deployed site, and the AI reads its past decisions from the trading journal, which holds them all.

The Dockerfile pins PGDG's exact pgvector build. When PGDG publishes a newer one, it moves the pinned one to
apt-archive.postgresql.org, so a fresh build then fails until the pin in `database/Dockerfile` is raised.

1. Get the new version and build the three images. The site keeps running.

   ```bash
   git pull
   docker compose build
   ```

2. Back up the database while the old backend still runs.

   ```bash
   docker compose exec backend python -m d_presentation.cli.database backup
   ```

3. Stop the backend, and start the database on its new image.

   ```bash
   docker compose stop backend
   docker compose up -d database
   ```

4. Check that the server offers the extension. Use the `DB_USER` and `DB_NAME` of `.env` in place of `stock_agent`.
   The answer is `vector|0.8.7|`: the version the server offers, and none installed yet.

   ```bash
   docker compose exec database psql -U stock_agent -d stock_agent -Atc "SELECT name, default_version, installed_version FROM pg_available_extensions WHERE name = 'vector'"
   ```

   No row means the database still runs the official image: run `docker compose up -d --build database` and check
   again.

5. Upgrade the database. The command dumps it first, then creates the extension in one transaction, and prints
   `13 -> 14 add_the_vector_extension`. Only a superuser may create the extension. The image's `DB_USER` is one.

   ```bash
   docker compose run --rm backend python -m d_presentation.cli.database migrate
   ```

6. Start the site. Its first start creates the two tables, empty.

   ```bash
   docker compose up -d
   ```

7. Check the extension, compute the vectors again, and count them.

   ```bash
   docker compose exec database psql -U stock_agent -d stock_agent -c '\dx vector'
   docker compose exec backend python -m d_presentation.cli.article_store
   docker compose exec database psql -U stock_agent -d stock_agent -Atc 'SELECT count(*) FROM article_vectors'
   ```

   `\dx` lists `vector` at `0.8.7`. The second command embeds every stock's kept articles on the server's CPU, prints
   how many, and asks no AI. The count is then those articles and the world news items, which the timer's world
   refresh embeds at the start. Without the command, the Web API's timer and each stock's AI brief compute the vectors
   of the stocks they reach.

8. The start names `db.chroma_persist_path` as a setting the app no longer reads. Delete that line from
   `config/appsetting.yaml` in the state folder.

To go back to the version before, keep the database on its pgvector image: restore the backup of step 2 with
`docker compose run --rm backend python -m d_presentation.cli.database restore backups/<file> --yes`, then check out
the old version and rebuild only the backend with `docker compose up -d --no-deps --build backend`.

When the site works, you can delete `chroma_data/` from the state folder. Nothing reads it any more, and the backup of
step 2 does not need it.

### Read the company background

MOPS and the exchange's document site are sources of a personal site only. A public site reads neither, and these
commands read nothing there.

1. Keep each company's profile from the open data. The Web API also does this by itself at its start.

   ```bash
   docker compose exec backend python -m d_presentation.cli.archive_closes
   ```

2. Read the main business and the annual report of the monthly ranking's best scores.

   ```bash
   docker compose exec backend python -m d_presentation.cli.company_background --top 20
   ```

   It takes about 20 seconds a company and asks no AI. Exit code 2 means a site did not answer and something is
   still due: run it again later. It shares the pace of its requests with the running Web API.

3. Look at a stock page. A signed-in viewer's first brief of a stock writes the company's card, and the site writes
   the cards and briefs of the ranking's top stocks by itself while `stock_page.system_writing.daily_ai_calls` is
   above 0.

The backend container needs no change for this: the PDF library is in the image, the worker process is the image's
own Python, and its temporary file is in the container's `/tmp`, which the backend's user may write.

### Settings of the deployment

Compose reads these variables from `.env`. `.env.example` describes each one.

| Variable | Default | Meaning |
| --- | --- | --- |
| `STATE_DIR` | none, required | The host folder that keeps everything the site saves. |
| `DB_USER`, `DB_PASSWORD`, `DB_NAME` | none, required | The PostgreSQL user, its password, and the database. The first start creates them. |
| `APP_UID`, `APP_GID` | `1000` | The user and the group that own `STATE_DIR`. The backend runs as them. |
| `PROXY_BIND` | `127.0.0.1` | The host address the proxy listens on: the Tailscale address for plain http, or the loopback address behind `tailscale serve`. Never `0.0.0.0`. For the home network, add `compose.lan.yml`. |
| `PROXY_PORT` | `8080` | The host port the proxy listens on. |
| `SITE_NAME` | `localhost` | The host name the proxy answers. |
| `LAN_NAME` | `127.0.0.1` | A second address the proxy answers, which `compose.lan.yml` publishes on the home network. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | none | The OAuth client for sign-in with Google. Set both, with `accounts.public_origin`, or neither. |

The Compose network has a fixed subnet, `172.31.88.0/29`. The backend trusts forwarded headers only from the proxy,
`172.31.88.2`, and from the gateway, `172.31.88.1`. The proxy trusts them only from the gateway, which is the address
that a request from `tailscale serve` arrives from. A browser that reaches the proxy directly cannot set them. If the
subnet is taken on your server, change it in `compose.yml` and in `frontend/Caddyfile` together.

PostgreSQL runs with `shared_buffers=256MB`, `work_mem=8MB`, and at most 50 connections, set in `compose.yml`. The
values leave the memory of a server with 7 GB to the backend, which holds years of daily history while it replays a
backtest.

### What only the operator can do

Two things need the server or an account that no test of the project reaches.

- **Keep the proxy's port off the local network.** Docker publishes a port with its own firewall rules, which run
  before `ufw`'s, so `ufw deny` does not close it. With `PROXY_BIND="127.0.0.1"` behind `tailscale serve`, the port is
  on the loopback address and nothing is to do. With `PROXY_BIND` set to the Tailscale address, a device of the
  local network that routes to that address reaches the port. Refuse it in the chain Docker leaves to the operator,
  and keep the rule across restarts with `iptables-persistent` or a unit of your own:

  ```bash
  sudo iptables -I DOCKER-USER ! -i tailscale0 -p tcp -m conntrack --ctorigdstport 8080 --ctdir ORIGINAL -j DROP
  ```

  Check from another device of the local network that `curl http://<the server's LAN address>:8080/` gets no answer.

- **Confirm a settings save with the real Google once.** An administrator without a password confirms a save by a
  fresh sign-in to Google, asked with `max_age=0` and checked by the `auth_time` Google returns. The tests run it
  against a stand-in for Google. If the real one ignores `max_age=0` or sends no `auth_time`, every such confirmation
  is refused and nothing is saved. So keep a password on the owner's account until it worked once: as a second
  administrator who signs in with Google only, change one harmless setting and confirm the save through Google. If it
  is refused, the owner's password still opens the editor, and `just reset-password <login>` on the server sets a
  password for an account that has none.

### About HTTPS in a tailnet

`tailscale serve` terminates TLS because it needs the fewest parts. The Tailscale daemon gets the certificate for the
`ts.net` name and renews it. The proxy stays on the loopback address, so no port depends on the Tailscale address at
boot.

The alternative is to write certificate files with `tailscale cert` and mount them into Caddy. The certificate lasts
90 days, so that setup needs a renewal timer and a proxy reload, and a port published on the Tailscale address.

The proxy sends `Strict-Transport-Security` only on requests that arrived over HTTPS, and the backend marks the session
cookie `Secure` only then. Both read the scheme from `X-Forwarded-Proto`, which `tailscale serve` sets.

## Deploy without Docker

1. Build the web app: `cd frontend && bun install --frozen-lockfile && bun run build`. The build has no source maps and
   holds no secret. Every `VITE_*` value would be public, and none is used.
2. Run the backend on the same machine with `just run-bn` (127.0.0.1:8800, one worker). Add the public host name to
   `api.allowed_hosts` in `config/appsetting.yaml`, for example
   `allowed_hosts: [127.0.0.1, localhost, stocks.example.org]`. Set `environment: test`, so that the backend serves
   no API docs.
3. Serve over TLS. Send the headers of the app, which are also in `vite.config.ts` (`appSecurityHeaders`). Fall back
   to `index.html` for client routes such as `/runs/<id>` and `/admin/settings`. Forward only `/v1`. Limit request
   bodies and request rates for `/v1`.

Caddy:

```caddy
stocks.example.org {
    encode gzip
    request_body {
        max_size 2MB
    }
    handle /v1/* {
        rate_limit {remote.ip} 30r/m    # with the caddy-ratelimit plugin; or limit in a firewall
        reverse_proxy 127.0.0.1:8800
    }
    handle {
        root * /srv/stock-agent/frontend/dist
        try_files {path} /index.html
        file_server
        header {
            Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            Referrer-Policy no-referrer
            X-Content-Type-Options nosniff
            X-Frame-Options DENY
            Permissions-Policy "camera=(), microphone=(), geolocation=()"
            Strict-Transport-Security "max-age=31536000"
        }
    }
}
```

nginx:

```nginx
server {
    listen 443 ssl;
    server_name stocks.example.org;
    client_max_body_size 2m;
    root /srv/stock-agent/frontend/dist;

    location /v1/ {
        proxy_pass http://127.0.0.1:8800;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri /index.html;
        add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'" always;
        add_header Referrer-Policy no-referrer always;
        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options DENY always;
        add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
        add_header Strict-Transport-Security "max-age=31536000" always;
    }
}
```

The proxy must not add an `Authorization` header or a cookie. Each user signs in on the page, and the API sets its
HttpOnly, SameSite=Strict session cookie on `/v1`. Forward the `Set-Cookie` and `Cookie` headers unchanged, and serve
the app and `/v1` from the same host name. Run one backend worker: background runs, their one-at-a-time lock, and the
settings revision the server started with live in that process.

## The visitor's address and scheme behind the proxy

The backend counts sign-in failures and registrations per client address, and marks the session cookie `Secure` when
the request came over https. Behind a proxy, every request reaches the backend from the proxy, over plain http. So:

1. The proxy sets the visitor's address and scheme, and overwrites whatever the visitor sent. The nginx block above
   does it with `proxy_set_header X-Forwarded-For $remote_addr;` and `proxy_set_header X-Forwarded-Proto $scheme;`.
   The `reverse_proxy` of Caddy sets both headers itself.
2. uvicorn reads those headers only from the addresses in `FORWARDED_ALLOW_IPS` (by default 127.0.0.1), with
   `--proxy-headers` (on by default). A proxy on the same machine needs nothing more.
3. In Docker the proxy reaches the backend from the bridge network, not from 127.0.0.1. `compose.yml` gives that
   network fixed addresses and sets `FORWARDED_ALLOW_IPS` to the proxy and the gateway. Never trust `*` while the port of the backend is reachable
   without the proxy: anyone could then claim any address.

Without these, every visitor shares the address of the proxy: 20 failed sign-ins by anyone lock the Web sign-in of
every user for 15 minutes. The cookie would also lack `Secure` under TLS.

`Secure` is decided by the scheme of the request, not set always, because the owner also uses the app over plain http
on the local network, from a phone, where a `Secure` cookie would never be sent back and sign-in would fail.
