# syntax=docker/dockerfile:1
# The reverse proxy: Caddy with the web app's production bundle. compose.yml builds and runs it.

FROM oven/bun:1.4.2 AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile
COPY . .
RUN bun run build

FROM caddy:2.11.9-alpine
# The image's caddy carries the file capability to bind a port below 1024. This site listens on 8080, and a program
# with a file capability does not start once compose.yml drops every capability, so the copy without it replaces it.
RUN cp /usr/bin/caddy /usr/bin/caddy-plain && mv /usr/bin/caddy-plain /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
# Caddy keeps its own files under these two, which any user can write: the proxy runs as no one in particular.
ENV XDG_CONFIG_HOME=/tmp/caddy-config \
    XDG_DATA_HOME=/tmp/caddy-data
USER 1000:1000
