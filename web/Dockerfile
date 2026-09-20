# node:24-slim, pinned by digest — see docs/implementation-plan.md Appendix E.
# Build-time only: Node never runs in production, Caddy serves the static
# build output from the shared "web-dist" volume (see docker-compose.yml).
FROM node@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
RUN npm run build

CMD ["sh", "-c", "rm -rf /dist/* && cp -r /app/dist/. /dist/"]
