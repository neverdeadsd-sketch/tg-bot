# ledger-wallet

A double-entry wallet backend for a gambling platform, built around the three
things that actually break real money systems: **duplicate requests**,
**concurrent writes to the same balance**, and **balances that drift away from
their history**.

NestJS · TypeScript · PostgreSQL · raw SQL (no ORM) · Docker

---

## Why this exists

Every iGaming platform has a wallet at its centre. Game providers call it on
every spin, payment providers call it on every deposit, and both of them retry
aggressively on any timeout. The wallet is the one service where a bug does not
produce a wrong pixel — it produces money that should not exist.

This project implements that core, small enough to read in one sitting, with the
hard parts solved rather than hand-waved:

| Problem | Solution here |
|---|---|
| A provider retries a debit after a timeout | Idempotency keys enforced by a unique index |
| Two bets hit the same balance at once | `SELECT … FOR UPDATE` with deterministic lock ordering |
| A balance disagrees with its own history | Append-only ledger as source of truth, balance as a derived cache, invariant asserted in tests |
| A bug overdraws an account | `CHECK (balance >= 0)` — the database refuses, regardless of application logic |
| Rounding errors in money | `BIGINT` minor units, `BigInt` arithmetic, never floats |

---

## Quick start

```bash
cp .env.example .env
docker compose up -d db          # Postgres 16 on :5432
npm install
npm run migrate
npm test                         # 14 tests, including the concurrency suite
npm run start:dev                # http://localhost:3000
npm run smoke                    # in a second terminal: drives the running server
```

Or run everything in containers:

```bash
docker compose up --build
```

---

## Data model

```
                    ledger_entries  (append-only, source of truth)
                          │
                          │  SUM(amount) per account
                          ▼
                    account_balances  (derived cache, O(1) reads)

accounts ─┬─ PLAYER_REAL      withdrawable player money
          ├─ PLAYER_BONUS     locked until wagering is met
          ├─ SYSTEM_DEPOSIT   counterparty for money entering the system
          ├─ SYSTEM_PAYOUT    counterparty for money leaving
          └─ SYSTEM_HOUSE     counterparty for bets, wins, bonus grants
```

Money flow for a bet of 1500 by a player holding 1000 real and 2000 bonus:

```
  PLAYER_REAL   -1000  ┐
  PLAYER_BONUS   -500  ├─  one transaction, entries sum to 0
  SYSTEM_HOUSE  +1500  ┘
```

Player accounts may never go negative. System accounts represent the outside
world and legitimately do — the deposit account's balance is the negated running
total of everything ever paid in.

---

## The three hard parts

### 1. Idempotency is enforced by the database, not the application

A game provider that does not get a `200` will call again. The naive fix —
"check whether we already processed this key, then process it" — has a race
between the check and the write, and under load that race is not theoretical.

Instead the unique index decides:

```sql
INSERT INTO ledger_transactions (idempotency_key, request_hash, ...)
VALUES ($1, $2, ...)
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING id
```

Exactly one caller gets a row back. Concurrent duplicates block on the index
until the winner commits, then read back the stored result and return it
verbatim. The response is snapshotted in `ledger_transactions.result` so a
replay a week later still returns what the caller originally saw.

Reusing a key with a *different* payload returns `409 IDEMPOTENCY_KEY_CONFLICT`
rather than silently handing back someone else's outcome — that case is always
a caller bug, and hiding it makes it permanent.

### 2. Concurrency is handled with row locks, in a fixed order

Balances are read under `SELECT … FOR UPDATE`, which holds the row until the
transaction ends. That is what makes the subsequent "can they afford it?" check
meaningful: nothing can change the balance between the read and the write.

Locks are always taken in sorted account-id order. Two transactions touching the
same two accounts in opposite orders deadlock; sorting removes the cycle
entirely. Deadlock and serialization failures are still retried with jittered
backoff in `DatabaseService.withTransaction`, because being right under load
means assuming they will happen anyway.

### 3. Double entry, with the invariant actually checked

Every transaction writes entries that sum to exactly zero. Balances are a cache
folded from those entries inside the same database transaction, so they can
never be updated without a matching ledger record.

Two invariants are asserted after every test:

- **per account** — cached balance equals `SUM(ledger_entries.amount)`
- **globally** — every entry in the system sums to `0`; money is only ever
  moved, never created

---

## What the concurrency tests prove

`test/concurrency.spec.ts` fires 100 simultaneous bets at a balance that covers
exactly 50, then asserts that 50 succeed, 50 are refused with a clean
`INSUFFICIENT_FUNDS`, and the balance lands on zero without ever going below it.

The test is only worth something if it fails when the protection is removed, so
that was verified: deleting `FOR UPDATE` from `lockBalances` and re-running gives

```
✕ never lets parallel bets overdraw a balance
    Expected constructor: HttpException
    Received constructor: DatabaseError
```

The result is worth reading closely. Still exactly 50 bets committed and the
balance still never went negative — because the `CHECK (balance >= 0)`
constraint caught every overdraft the application check had waved through. The
money stayed correct; what broke was the *semantics*. Fifty players who should
have received a tidy `422 INSUFFICIENT_FUNDS` got a raw database error instead.

That is the argument for defence in depth in one experiment: the lock provides
correct behaviour, the constraint provides a floor under it, and neither one
makes the other redundant.

---

## API

All amounts are integers in **minor units** (cents). `idempotencyKey` is
required on every write.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/wallet/deposit` | Credit real balance |
| `POST` | `/wallet/withdraw` | Debit real balance (blocked by unmet wagering) |
| `POST` | `/wallet/bet` | Debit real first, bonus for the remainder |
| `POST` | `/wallet/win` | Credit real balance |
| `POST` | `/wallet/bonus` | Grant a bonus with `wageringMultiplier` |
| `GET` | `/wallet/:playerId/balance?currency=EUR` | Current balances and wagering progress |
| `POST` | `/provider/bet` · `/provider/win` | Seamless-wallet callbacks, HMAC-signed |

```bash
curl -X POST localhost:3000/wallet/deposit \
  -H 'content-type: application/json' \
  -d '{"playerId":"f735d060-8f9c-4f4f-907b-12c6ca785ec8",
       "currency":"EUR","amount":10000,"idempotencyKey":"dep-1"}'
```

```json
{
  "transactionId": "9a105d94-8008-413c-b31c-39f26ff49c38",
  "kind": "DEPOSIT",
  "replayed": false,
  "balance": { "real": "10000", "bonus": "0", "total": "10000", "wagering": null }
}
```

Repeating that exact call returns the same `transactionId` with
`"replayed": true` and moves no money.

### Provider callbacks

`/provider/*` verifies an `x-provider-signature` HMAC-SHA256 header over the
**raw** request body — re-serialising parsed JSON changes byte order and breaks
signatures for reasons nobody enjoys debugging. The comparison is constant-time,
since a plain `===` leaks how many leading bytes were correct.

---

## Bonus wagering

A bonus is granted with a multiplier; the requirement is `amount × multiplier`.
Bets spend real money first — the "sticky bonus" model — so the bonus stays
locked until the player has wagered enough of their own money.

While a requirement is unmet, withdrawals are refused with `WAGERING_NOT_MET`.
When it is met, the bonus is closed and any surviving bonus balance is released
to real money as its own `BONUS_CONVERT` transaction, so the release is visible
in the audit trail rather than buried inside whichever bet triggered it.

A partial unique index allows only one active bonus per player per currency, so
a concurrent double-grant cannot slip through.

### Reading the audit trail

Order by `ledger_transactions.seq`, never by `created_at`:

```sql
SELECT seq, kind, created_at FROM ledger_transactions ORDER BY seq;
```

`created_at` originally defaulted to `now()`, which in PostgreSQL is the
*transaction* start time — so the BET and the BONUS_CONVERT it triggers, written
in one transaction, shared a timestamp to the microsecond and came back in
arbitrary order. Migration `002` switches the default to `clock_timestamp()` and
adds `seq`, a monotonic insertion counter.

Both changes matter for different reasons. Distinct timestamps make the recorded
times mean what a reader assumes. `seq` is what the log should actually be
ordered by, because wall clocks are not monotonic: NTP steps them, and they can
run backwards. An audit trail must not depend on one to know what happened
first.

---

## Testing

```bash
npm test          # requires Postgres; tests truncate TEST_DATABASE_URL
npm run typecheck
```

14 tests over two suites: behaviour (`test/wallet.spec.ts`) and concurrency
(`test/concurrency.spec.ts`). Tests run against a real PostgreSQL instance
rather than mocks — the behaviour under test *is* database behaviour, and a
mocked `FOR UPDATE` proves nothing.

### Smoke test

```bash
npm run start:dev     # one terminal
npm run smoke         # another
```

`scripts/smoke.ts` drives the **running** server over HTTP and checks the whole
money path end to end — deposit, replay, key conflict, bonus, blocked and
allowed withdrawal, overdraft, provider signature — then reads the audit trail
straight from the database to confirm its ordering. It exits non-zero on the
first failed check, so it can gate a deploy.

It exists because the unit suite structurally cannot catch one class of failure,
and this project hit it: the tests use their own database and their own
environment loading, so when migrations never reached the *application*
database, every endpoint returned 500 while the suite stayed green. Pointed at
an unmigrated database the smoke test fails in exactly the right way:

```
  ✗ status 201
      expected: 201
      actual:   500
SMOKE ERRORED
relation "ledger_transactions" does not exist
```

Tests prove the logic. The smoke test proves the deployment.

---

## Deliberate simplifications

Called out because knowing what is missing matters as much as what is built:

- **Wins always credit the real balance.** A stricter model pays wins from
  bonus-funded rounds back into the bonus balance and tracks the split per
  round.
- **No rollback / cancel operation.** Providers send these when a round is
  voided; it would be a reversing transaction referencing the original, not a
  delete.
- **No outbound webhook delivery.** Inbound signature verification is
  implemented; the outbound side needs an outbox table and a retry worker.
- **No currency conversion.** Every operation is single-currency by design.
- **No authentication** beyond the provider HMAC. A real deployment sits behind
  a gateway that handles operator auth.
- **Balance reads are not paginated into statements.** `ledger_entries` has the
  index for it; the endpoint is not written.

## Possible next steps

- Reversing transactions (`ROLLBACK` kind) for voided rounds
- A reconciliation job comparing cached balances to ledger sums on a schedule
- Outbox + worker for outbound provider notifications
- Partitioning `ledger_entries` by month once it stops fitting in cache
- k6 load profile to find where the lock on `SYSTEM_HOUSE` becomes the bottleneck
  (it will — every bet touches it, and that is the first thing to shard)

---

## The demo page

`GET /` serves a single static page that drives the API from a browser: deposit,
grant a bonus, bet, win, withdraw. It exists because a wallet with no way to
look at it is a hard thing to show anyone.

It is built around the two things worth seeing rather than reading about:

- **The ledger table** renders each transaction's legs and their sum, so the
  double-entry invariant is visible rather than asserted — every row ends in `Σ 0`.
- **Replay last request** sends the same idempotency key again and shows the
  response coming back with `"replayed": true` and the balance unmoved.
  **Replay, changed amount** shows the `409` that a mutated retry earns.

Every call is logged on the page with its method, path, status and JSON body, so
the API is legible without opening a terminal. No build step and no
dependencies — one HTML file in `public/`, served by
`app.useStaticAssets`.

`GET /wallet/:playerId/transactions` backs the ledger table: it returns each
operation with its entries, ordered by `seq`.

## Deploying

The service needs a PostgreSQL URL and nothing else. It binds `0.0.0.0` so it is
reachable from a platform router, reads `PORT` from the environment, and exposes
a readiness probe.

| Setting | Value |
|---|---|
| Build | `npm ci --include=dev && npm run build` |
| Start | `node dist/scripts/migrate.js && node dist/src/main.js` |
| Health check path | `/health` |
| Required env | `DATABASE_URL` |
| Optional env | `PORT`, `PROVIDER_WEBHOOK_SECRET` |

`--include=dev` matters: with `NODE_ENV=production` set, npm omits
devDependencies, and the build needs TypeScript.

Migrations run on start. They are idempotent — `schema_migrations` makes a
repeat a no-op — so a restart or a second instance costs one query.

A managed Postgres URL ending in `?sslmode=require` works as-is; `pg` reads the
mode from the connection string and verifies the server certificate.

### `/health`

The probe checks more than liveness. It opens a database connection **and**
verifies the schema is present, because a process that is running against an
unmigrated database is not healthy — it answers every real request with a 500.

```json
{ "status": "ok", "database": "reachable", "schema": "migrated",
  "latestMigration": "002_audit_ordering.sql" }
```

Unmigrated, it returns `503` and says why, so a bad deploy fails loudly instead
of going live broken:

```json
{ "status": "error", "reason": "SCHEMA_NOT_MIGRATED",
  "missingTables": ["accounts", "account_balances", "..."] }
```

## Scope

A portfolio project, written to demonstrate how the money core of an iGaming
platform is built correctly. It is not a licensed product and implements no
gambling logic — no RNG, no game rounds, no odds. Just the ledger.

MIT licensed.
