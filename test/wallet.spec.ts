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

/** Asserts the promise rejects with a specific domain error code. */
async function expectDomainError(promise: Promise<unknown>, code: string): Promise<void> {
  await expect(promise).rejects.toBeInstanceOf(HttpException);
  await promise.catch((error: HttpException) => {
    expect(error.getResponse()).toMatchObject({ code });
  });
}

describe('WalletService', () => {
  let app: INestApplication;
  let wallet: WalletService;
  let playerId: string;
  const currency = 'EUR';

  beforeAll(async () => {
    ({ app, wallet } = await createTestApp());
  });

  afterAll(async () => {
    await app.close();
  });

  beforeEach(() => {
    playerId = randomUUID();
  });

  const key = () => randomUUID();

  describe('deposit', () => {
    it('credits the real balance and keeps the ledger balanced', async () => {
      const result = await wallet.deposit({ playerId, currency, amount: 10_000n, idempotencyKey: key() });

      expect(result.replayed).toBe(false);
      expect(result.balance).toMatchObject({ real: '10000', bonus: '0', total: '10000' });

      await expectBalancesMatchLedger();
      await expectLedgerSumsToZero();
    });
  });

  describe('idempotency', () => {
    it('replays the stored result instead of crediting twice', async () => {
      const idempotencyKey = key();
      const first = await wallet.deposit({ playerId, currency, amount: 10_000n, idempotencyKey });
      const second = await wallet.deposit({ playerId, currency, amount: 10_000n, idempotencyKey });

      expect(first.replayed).toBe(false);
      expect(second.replayed).toBe(true);
      expect(second.transactionId).toBe(first.transactionId);

      // The money moved exactly once, which is the entire point.
      await expect(balanceOf(playerId)).resolves.toMatchObject({ real: 10_000n });

      const { rows } = await testPool.query('SELECT COUNT(*)::int AS n FROM ledger_transactions');
      expect(rows[0].n).toBe(1);
    });

    it('rejects a reused key carrying a different payload', async () => {
      const idempotencyKey = key();
      await wallet.deposit({ playerId, currency, amount: 10_000n, idempotencyKey });

      await expectDomainError(
        wallet.deposit({ playerId, currency, amount: 99_999n, idempotencyKey }),
        'IDEMPOTENCY_KEY_CONFLICT',
      );

      await expect(balanceOf(playerId)).resolves.toMatchObject({ real: 10_000n });
    });
  });

  describe('withdraw', () => {
    it('moves money out and leaves the ledger balanced', async () => {
      await wallet.deposit({ playerId, currency, amount: 10_000n, idempotencyKey: key() });
      const result = await wallet.withdraw({ playerId, currency, amount: 4_000n, idempotencyKey: key() });

      expect(result.balance.real).toBe('6000');
      await expectBalancesMatchLedger();
      await expectLedgerSumsToZero();
    });

    it('refuses to overdraw', async () => {
      await wallet.deposit({ playerId, currency, amount: 1_000n, idempotencyKey: key() });

      await expectDomainError(
        wallet.withdraw({ playerId, currency, amount: 2_000n, idempotencyKey: key() }),
        'INSUFFICIENT_FUNDS',
      );

      // The failed attempt rolled back cleanly — no partial write.
      await expect(balanceOf(playerId)).resolves.toMatchObject({ real: 1_000n });
      await expectBalancesMatchLedger();
    });
  });

  describe('bets', () => {
    it('spends real money first and falls back to bonus', async () => {
      await wallet.deposit({ playerId, currency, amount: 1_000n, idempotencyKey: key() });
      await wallet.grantBonus({
        playerId, currency, amount: 2_000n, wageringMultiplier: 10, idempotencyKey: key(),
      });

      // Stake 1500: 1000 from real (all of it), 500 from bonus.
      await wallet.bet({ playerId, currency, amount: 1_500n, idempotencyKey: key(), reference: 'round-1' });

      await expect(balanceOf(playerId)).resolves.toEqual({ real: 0n, bonus: 1_500n });
      await expectBalancesMatchLedger();
      await expectLedgerSumsToZero();
    });

    it('refuses a stake larger than real + bonus combined', async () => {
      await wallet.deposit({ playerId, currency, amount: 500n, idempotencyKey: key() });

      await expectDomainError(
        wallet.bet({ playerId, currency, amount: 900n, idempotencyKey: key() }),
        'INSUFFICIENT_FUNDS',
      );

      await expect(balanceOf(playerId)).resolves.toMatchObject({ real: 500n });
    });

    it('credits wins to the real balance', async () => {
      await wallet.deposit({ playerId, currency, amount: 1_000n, idempotencyKey: key() });
      await wallet.bet({ playerId, currency, amount: 1_000n, idempotencyKey: key(), reference: 'round-2' });
      await wallet.win({ playerId, currency, amount: 2_500n, idempotencyKey: key(), reference: 'round-2' });

      await expect(balanceOf(playerId)).resolves.toMatchObject({ real: 2_500n });
      await expectLedgerSumsToZero();
    });
  });

  describe('bonus wagering', () => {
    it('blocks withdrawal until the wagering requirement is met', async () => {
      await wallet.deposit({ playerId, currency, amount: 10_000n, idempotencyKey: key() });
      await wallet.grantBonus({
        playerId, currency, amount: 1_000n, wageringMultiplier: 2, idempotencyKey: key(),
      });

      await wallet.bet({ playerId, currency, amount: 500n, idempotencyKey: key(), reference: 'r1' });

      await expectDomainError(
        wallet.withdraw({ playerId, currency, amount: 100n, idempotencyKey: key() }),
        'WAGERING_NOT_MET',
      );
    });

    it('releases the bonus to real money once wagering completes', async () => {
      await wallet.deposit({ playerId, currency, amount: 10_000n, idempotencyKey: key() });
      await wallet.grantBonus({
        playerId, currency, amount: 1_000n, wageringMultiplier: 2, idempotencyKey: key(),
      });

      // Requirement is 1000 * 2 = 2000. Stake exactly that, funded from real.
      const result = await wallet.bet({
        playerId, currency, amount: 2_000n, idempotencyKey: key(), reference: 'r1',
      });

      // 10000 - 2000 staked = 8000 real, plus the 1000 bonus now released.
      expect(result.balance).toMatchObject({ real: '9000', bonus: '0' });
      expect(result.balance.wagering).toBeNull();

      // The release is its own auditable transaction, not a silent adjustment.
      const { rows } = await testPool.query<{ kind: string }>(
        `SELECT kind FROM ledger_transactions WHERE kind = 'BONUS_CONVERT'`,
      );
      expect(rows).toHaveLength(1);

      // ...and the audit trail must say the release happened AFTER the bet that
      // caused it. Ordering by created_at cannot: now() is the transaction
      // start time, so both rows written by this bet share one timestamp.
      // `seq` is the monotonic insertion order that makes the log readable.
      const { rows: ordered } = await testPool.query<{ kind: string }>(
        `SELECT kind FROM ledger_transactions ORDER BY seq`,
      );
      expect(ordered.map((row) => row.kind)).toEqual([
        'DEPOSIT',
        'BONUS_GRANT',
        'BET',
        'BONUS_CONVERT',
      ]);

      // And withdrawal is now unblocked.
      await wallet.withdraw({ playerId, currency, amount: 9_000n, idempotencyKey: key() });
      await expect(balanceOf(playerId)).resolves.toEqual({ real: 0n, bonus: 0n });

      await expectBalancesMatchLedger();
      await expectLedgerSumsToZero();
    });

    it('allows only one active bonus per player', async () => {
      await wallet.grantBonus({
        playerId, currency, amount: 1_000n, wageringMultiplier: 2, idempotencyKey: key(),
      });

      await expectDomainError(
        wallet.grantBonus({
          playerId, currency, amount: 500n, wageringMultiplier: 2, idempotencyKey: key(),
        }),
        'ACTIVE_BONUS_EXISTS',
      );
    });
  });
});
