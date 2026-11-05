# Deploying the web UI

The browser loads the built app and calls same-origin `/v1` paths. In production one reverse proxy serves both: the
static files of `frontend/dist`, and `/v1` forwarded to the backend on the loopback address. No CORS is needed, and
none should be added.

1. Build: `cd frontend && bun install --frozen-lockfile && bun run build`. The build has no source maps and holds no
   secret; every `VITE_*` value would be public, and none is used.
2. Run the backend on the same machine with `just run-bn` (127.0.0.1:8800, one worker). Add the public host name to
   `api.allowed_hosts` in `config/appsetting.yaml`, for example `allowed_hosts: [127.0.0.1, localhost, stocks.example.org]`.
3. Serve over TLS. Send the app's headers (they are also in `vite.config.ts`, `appSecurityHeaders`, which
   `vite preview` sends), fall back to `index.html` for client routes such as `/runs/<id>` and `/admin/settings`, and
   limit request bodies and request rates for `/v1`.

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
        add_header Strict-Transport-Security "max-age=31536000" always;
    }
}
```

The proxy must not add an `Authorization` header or a cookie: each user signs in on the page, and the API sets its
HttpOnly, SameSite=Strict session cookie on `/v1`. Forward the `Set-Cookie` and `Cookie` headers unchanged, and serve
the app and `/v1` from the same host name. Run one backend worker: background runs, their one-at-a-time lock and the
settings revision the server started with live in that process.

## The visitor's address and scheme behind the proxy

The backend counts sign-in failures and registrations per client address, and marks the session cookie `Secure` when
the request came over https. Behind a proxy, every request reaches the backend from the proxy, over plain http. So:

1. The proxy sets the visitor's address and scheme, overwriting whatever the visitor sent. The nginx block above does
   it with `proxy_set_header X-Forwarded-For $remote_addr;` and `proxy_set_header X-Forwarded-Proto $scheme;`. Caddy's
   `reverse_proxy` sets both headers itself.
2. uvicorn reads those headers only from the addresses in `FORWARDED_ALLOW_IPS` (by default 127.0.0.1), with
   `--proxy-headers` (on by default). A proxy on the same machine needs nothing more.
3. In Docker the proxy reaches the backend from the bridge network, not from 127.0.0.1. Start the backend with that
   network's proxy address trusted, for example
   `FORWARDED_ALLOW_IPS=172.18.0.2 uvicorn main:app --host 0.0.0.0 --port 8800 --proxy-headers`. Never trust `*`
   while the backend's port is reachable without the proxy: anyone could then claim any address.

Without these, every visitor shares the proxy's address: 20 failed sign-ins by anyone lock every user's Web sign-in
for 15 minutes, and registration allows 3 per hour for the whole site. The cookie would also lack `Secure` under TLS.

`Secure` is decided by the request's scheme, not set always, because the owner also uses the app over plain http on the
local network, from a phone, where a `Secure` cookie would never be sent back and sign-in would fail.
