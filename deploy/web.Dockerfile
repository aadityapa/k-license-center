# Karnex License Center portal (React build) served by Caddy, which also terminates HTTPS
# (automatic Let's Encrypt certificate for $DOMAIN) and forwards /api/* to the API.
# Build context = the repository root.
FROM node:20-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv
