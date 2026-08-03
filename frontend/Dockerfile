# Build context is the repository root.
# Copies host node_modules (from `npm install` / `npm ci` on the builder machine)
# so image builds do not depend on registry reachability inside Docker.
FROM node:22-alpine AS builder
WORKDIR /app
ARG REFRAQ_API_UPSTREAM=http://api:8000
ENV REFRAQ_API_UPSTREAM=$REFRAQ_API_UPSTREAM
COPY frontend/package.json frontend/package-lock.json* ./
COPY frontend/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
