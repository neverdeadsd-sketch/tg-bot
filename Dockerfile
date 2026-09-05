FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY tsconfig*.json ./
COPY src ./src
COPY scripts ./scripts
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY package*.json ./
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist
COPY migrations ./migrations
COPY public ./public
EXPOSE 3000

# Migrations run before the server accepts traffic. They are idempotent —
# schema_migrations makes a repeat a no-op — so a restart or a second replica
# costs one query. Without this a container starts happily against an
# unmigrated database and answers every request with a 500.
CMD ["sh", "-c", "node dist/scripts/migrate.js && node dist/src/main.js"]
