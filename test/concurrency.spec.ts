import { randomUUID } from 'node:crypto';
import { HttpException, INestApplication } from '@nestjs/common';
import { WalletService } from '../src/wallet/wallet.service';
import {
  balanceOf,
  createTestApp,
  expectBalancesMatchLedger,
  expectLedgerSumsToZero,
  testPool,
} from './helpers';

/**
 * These are the tests the whole design exists for.
 *
 * A wallet that works when requests arrive one at a time is easy. Every real
 * incident in this domain — the double spend, the negative balance, the player
 * credited twice for one deposit — happens when two requests touch the same
 * balance at the same instant. So we reproduce that on purpose.
 */
describe('concurrency', () => {
  let app: INestApplication;
  let wallet: WalletService;
  const currency = 'EUR';

  beforeAll(async () => {
    ({ app, wallet } = await createTestApp());
  });

  afterAll(async () => {
    await app.close();
  });

  it('never lets parallel bets overdraw a balance', async () => {
    const playerId = randomUUID();
    const stake = 100n;
    const affordableBets = 50;

    await wallet.deposit({
      playerId,
      currency,
      amount: stake * BigInt(affordableBets),
      idempotencyKey: randomUUID(),
    });

    // 100 bets fired at once against a balance that covers exactly 50.
    // Without row locks this is the classic double-spend: every request reads
    // the same balance, every request believes it can afford the stake.
    const attempts = await Promise.allSettled(
      Array.from({ length: 100 }, () =>
        wallet.bet({ playerId, currency, amount: stake, idempotencyKey: randomUUID(), reference: 'race' }),
      ),
    );

    const settled = attempts.filter((a) => a.status === 'fulfilled');
    const refused = attempts.filter((a) => a.status === 'rejected');

    expect(settled).toHaveLength(affordableBets);
    expect(refused).toHaveLength(100 - affordableBets);

    // Every refusal is the deliberate business rule, not a crash or a deadlock.
    for (const attempt of refused as PromiseRejectedResult[]) {
      expect(attempt.reason).toBeInstanceOf(HttpException);
      expect((attempt.reason as HttpException).getResponse()).toMatchObject({
        code: 'INSUFFICIENT_FUNDS',
      });
    }

    // The balance landed exactly on zero — never below it, not even briefly.
    await expect(balanceOf(playerId)).resolves.toEqual({ real: 0n, bonus: 0n });

    // 50 bets means 50 committed bet transactions, no more and no fewer.
    const { rows } = await testPool.query<{ n: number }>(
      `SELECT COUNT(*)::int AS n FROM ledger_transactions WHERE kind = 'BET'`,
    );
    expect(rows[0].n).toBe(affordableBets);

    await expectBalancesMatchLedger();
    await expectLedgerSumsToZero();
  });

  it('applies a duplicated request exactly once when all copies arrive together', async () => {
    const playerId = randomUUID();
    const idempotencyKey = randomUUID();

    // A provider timing out and retrying, or a client double-submitting: the
    // same request lands 15 times simultaneously. All must succeed — a retry
    // is not an error — but the money must move once.
    const results = await Promise.all(
      Array.from({ length: 15 }, () =>
        wallet.deposit({ playerId, currency, amount: 5_000n, idempotencyKey }),
      ),
    );

    const transactionIds = new Set(results.map((r) => r.transactionId));
    expect(transactionIds.size).toBe(1);
    expect(results.filter((r) => !r.replayed)).toHaveLength(1);

    await expect(balanceOf(playerId)).resolves.toMatchObject({ real: 5_000n });

    const { rows } = await testPool.query<{ n: number }>(
      `SELECT COUNT(*)::int AS n FROM ledger_entries`,
    );
    expect(rows[0].n).toBe(2); // one debit, one credit — a single transaction

    await expectBalancesMatchLedger();
    await expectLedgerSumsToZero();
  });

  it('keeps the ledger consistent under mixed parallel traffic', async () => {
    const players = Array.from({ length: 10 }, () => randomUUID());

    await Promise.all(
      players.map((playerId) =>
        wallet.deposit({ playerId, currency, amount: 10_000n, idempotencyKey: randomUUID() }),
      ),
    );

    // Bets, wins and withdrawals from ten players interleaved arbitrarily.
    // Individual operations may legitimately fail on funds; the invariants may
    // not fail at all.
    const operations = players.flatMap((playerId) => [
      wallet.bet({ playerId, currency, amount: 3_000n, idempotencyKey: randomUUID(), reference: 'm1' }),
      wallet.bet({ playerId, currency, amount: 4_000n, idempotencyKey: randomUUID(), reference: 'm2' }),
      wallet.win({ playerId, currency, amount: 1_500n, idempotencyKey: randomUUID(), reference: 'm1' }),
      wallet.withdraw({ playerId, currency, amount: 2_000n, idempotencyKey: randomUUID() }),
    ]);

    await Promise.allSettled(operations);

    const { rows } = await testPool.query<{ negative: number }>(
      `SELECT COUNT(*)::int AS negative
       FROM account_balances b
       JOIN accounts a ON a.id = b.account_id
       WHERE a.player_id IS NOT NULL AND b.balance < 0`,
    );
    expect(rows[0].negative).toBe(0);

    await expectBalancesMatchLedger();
    await expectLedgerSumsToZero();
  });
});
