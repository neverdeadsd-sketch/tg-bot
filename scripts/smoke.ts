import { config as loadDotenv } from 'dotenv';

loadDotenv();

import { randomUUID } from 'node:crypto';
import { Client } from 'pg';

/**
 * Smoke test: drives a RUNNING server over HTTP and checks that the whole money
 * path actually works against the real database.
 *
 * This exists because the unit suite cannot catch a class of failure that
 * already bit this project once: the tests run against their own database with
 * their own environment loading, so a migration that never reached the
 * application database left every endpoint returning 500 while the suite stayed
 * green. Tests prove the logic; this proves the deployment.
 *
 *   npm run start:dev      # in one terminal
 *   npm run smoke          # in another
 *
 * Exits non-zero on the first sign of trouble, so it can gate a deploy.
 */

const BASE_URL = process.env.SMOKE_BASE_URL ?? `http://localhost:${process.env.PORT ?? 3000}`;

let failures = 0;

function check(label: string, actual: unknown, expected: unknown): void {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    console.log(`  ✓ ${label}`);
    return;
  }
  console.log(`  ✗ ${label}`);
  console.log(`      expected: ${e}`);
  console.log(`      actual:   ${a}`);
  failures++;
}

interface HttpResult {
  status: number;
  // Responses are either an OperationResult/BalanceView or an error envelope.
  body: Record<string, any>;
}

async function post(path: string, body: unknown): Promise<HttpResult> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { status: response.status, body: (await response.json()) as Record<string, any> };
}

async function get(path: string): Promise<HttpResult> {
  const response = await fetch(`${BASE_URL}${path}`);
  return { status: response.status, body: (await response.json()) as Record<string, any> };
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForServer(timeoutMs = 15_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await fetch(`${BASE_URL}/wallet/${randomUUID()}/balance?currency=EUR`);
      return;
    } catch {
      await sleep(300);
    }
  }
  throw new Error(
    `No server responding at ${BASE_URL}.\n` +
      'Start it first: npm run start:dev (or npm run build && npm start)',
  );
}

async function run(): Promise<void> {
  await waitForServer();

  const playerId = randomUUID();
  const currency = 'EUR';
  const key = (name: string) => `smoke-${playerId}-${name}`;

  console.log(`Smoke test against ${BASE_URL}`);
  console.log(`Player ${playerId}\n`);

  // --- readiness ----------------------------------------------------------
  // First, because everything below is meaningless if the schema is missing,
  // and this says so in one line instead of ten failed assertions.
  console.log('health');
  const health = await get('/health');
  check('status 200', health.status, 200);
  check('database reachable', health.body.database, 'reachable');
  check('schema migrated', health.body.schema, 'migrated');
  if (health.status !== 200) {
    throw new Error(`Service is not ready: ${JSON.stringify(health.body)}`);
  }

  // --- deposit ------------------------------------------------------------
  console.log('deposit');
  const deposit = await post('/wallet/deposit', {
    playerId, currency, amount: 10_000, idempotencyKey: key('dep'),
  });
  check('status 201', deposit.status, 201);
  check('real balance', deposit.body.balance?.real, '10000');
  check('not a replay', deposit.body.replayed, false);

  // --- idempotent replay --------------------------------------------------
  console.log('\nreplay of the same request');
  const replay = await post('/wallet/deposit', {
    playerId, currency, amount: 10_000, idempotencyKey: key('dep'),
  });
  check('same transaction id', replay.body.transactionId, deposit.body.transactionId);
  check('marked as replayed', replay.body.replayed, true);
  check('money moved only once', replay.body.balance?.real, '10000');

  // --- key reuse with a different payload ---------------------------------
  console.log('\nsame key, different payload');
  const conflict = await post('/wallet/deposit', {
    playerId, currency, amount: 99_999, idempotencyKey: key('dep'),
  });
  check('status 409', conflict.status, 409);
  check('error code', conflict.body.code, 'IDEMPOTENCY_KEY_CONFLICT');

  // --- bonus grant --------------------------------------------------------
  console.log('\nbonus grant, wagering x2');
  const bonus = await post('/wallet/bonus', {
    playerId, currency, amount: 1_000, wageringMultiplier: 2, idempotencyKey: key('bon'),
  });
  check('bonus balance', bonus.body.balance?.bonus, '1000');
  check('wagering required', bonus.body.balance?.wagering?.required, '2000');
  check('wagering remaining', bonus.body.balance?.wagering?.remaining, '2000');

  // --- withdrawal blocked by wagering -------------------------------------
  console.log('\nwithdrawal while wagering is unmet');
  const blocked = await post('/wallet/withdraw', {
    playerId, currency, amount: 100, idempotencyKey: key('wd-blocked'),
  });
  check('status 422', blocked.status, 422);
  check('error code', blocked.body.code, 'WAGERING_NOT_MET');

  // --- overdraft ----------------------------------------------------------
  console.log('\nstake larger than the whole balance');
  const overdraft = await post('/wallet/bet', {
    playerId, currency, amount: 999_999, idempotencyKey: key('bet-over'),
  });
  check('status 422', overdraft.status, 422);
  check('error code', overdraft.body.code, 'INSUFFICIENT_FUNDS');

  // --- bet that completes the wagering requirement ------------------------
  console.log('\nbet of 2000, completing the wagering requirement');
  const bet = await post('/wallet/bet', {
    playerId, currency, amount: 2_000, idempotencyKey: key('bet'), reference: 'smoke-round-1',
  });
  check('real after stake and release', bet.body.balance?.real, '9000');
  check('bonus released', bet.body.balance?.bonus, '0');
  check('wagering cleared', bet.body.balance?.wagering, null);

  // --- balance endpoint agrees --------------------------------------------
  console.log('\nbalance endpoint');
  const balance = await get(`/wallet/${playerId}/balance?currency=${currency}`);
  check('status 200', balance.status, 200);
  check('real', balance.body.real, '9000');
  check('total', balance.body.total, '9000');

  // --- withdrawal now allowed ---------------------------------------------
  console.log('\nwithdrawal after wagering is met');
  const withdraw = await post('/wallet/withdraw', {
    playerId, currency, amount: 9_000, idempotencyKey: key('wd'),
  });
  check('status 201', withdraw.status, 201);
  check('balance emptied', withdraw.body.balance?.real, '0');

  // --- provider callback rejects an unsigned request ----------------------
  console.log('\nprovider callback without a signature');
  const unsigned = await post('/provider/bet', {
    playerId, currency, amount: 100, idempotencyKey: key('prov'),
  });
  check('status 401', unsigned.status, 401);
  check('error code', unsigned.body.code, 'MISSING_SIGNATURE');

  // --- transactions endpoint ---------------------------------------------
  console.log('\ntransactions endpoint');
  const history = await get(`/wallet/${playerId}/transactions`);
  check('status 200', history.status, 200);
  const kinds = (history.body as unknown as { kind: string }[]).map((t) => t.kind);
  check('operations in order', kinds, [
    'DEPOSIT', 'BONUS_GRANT', 'BET', 'BONUS_CONVERT', 'WITHDRAWAL',
  ]);
  const unbalanced = (history.body as unknown as { kind: string; entries: { amount: string }[] }[])
    .filter((t) => t.entries.reduce((sum, e) => sum + Number(e.amount), 0) !== 0)
    .map((t) => t.kind);
  check('every transaction sums to zero', unbalanced, []);

  // --- game provider ------------------------------------------------------
  console.log('\ngame provider');
  const paytable = await get('/game/paytable');
  check('paytable served', paytable.status, 200);
  const rtp = paytable.body.rtp as number;
  check('RTP is inside a shippable band', rtp > 85 && rtp < 98, true);

  // Fund a separate player so the spin cannot disturb the assertions above.
  const gambler = randomUUID();
  await post('/wallet/deposit', {
    playerId: gambler, currency, amount: 10_000, idempotencyKey: `${gambler}-fund`,
  });

  const spin = await post('/game/spin', { playerId: gambler, currency, bet: 100 });
  check('spin accepted', spin.status, 201);
  check('three reels', (spin.body.reels as unknown[])?.length, 3);
  const spent = 10_000 - 100 + (spin.body.payout as number);
  check('stake debited and any win credited', spin.body.balance?.real, String(spent));

  const brokePlayer = randomUUID();
  const brokeSpin = await post('/game/spin', { playerId: brokePlayer, currency, bet: 100 });
  check('spin refused without funds', brokeSpin.status, 422);
  check('error code', brokeSpin.body.code, 'INSUFFICIENT_FUNDS');

  // --- demo page ----------------------------------------------------------
  console.log('\ndemo page');
  const page = await fetch(`${BASE_URL}/`);
  check('served at /', page.status, 200);
  check('is html', (page.headers.get('content-type') ?? '').includes('text/html'), true);

  // --- audit trail --------------------------------------------------------
  // Read straight from the database: this is the one thing the HTTP surface
  // does not expose, and the ordering it verifies was a real bug.
  console.log('\naudit trail');
  const client = new Client({ connectionString: process.env.DATABASE_URL });
  await client.connect();
  try {
    const { rows } = await client.query<{ kind: string }>(
      `SELECT kind FROM ledger_transactions WHERE player_id = $1 ORDER BY seq`,
      [playerId],
    );
    check('operations in insertion order', rows.map((row) => row.kind), [
      'DEPOSIT',
      'BONUS_GRANT',
      'BET',
      'BONUS_CONVERT',
      'WITHDRAWAL',
    ]);

    // Failed operations must leave nothing behind: the idempotency row is
    // written before the work, so a rejected request has to roll it back.
    const { rows: distinctTimes } = await client.query<{ n: string }>(
      `SELECT COUNT(DISTINCT created_at)::text AS n
       FROM ledger_transactions WHERE player_id = $1`,
      [playerId],
    );
    check('every operation has its own timestamp', distinctTimes[0].n, '5');
  } finally {
    await client.end();
  }
}

run()
  .then(() => {
    if (failures > 0) {
      console.log(`\nSMOKE FAILED — ${failures} check(s) did not pass`);
      process.exit(1);
    }
    console.log('\nSMOKE PASSED');
    process.exit(0);
  })
  .catch((error) => {
    console.error(`\nSMOKE ERRORED\n${(error as Error).message}`);
    process.exit(1);
  });
