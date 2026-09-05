import { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { Pool } from 'pg';
import { AppModule } from '../src/app.module';
import { WalletService } from '../src/wallet/wallet.service';

export const testPool = new Pool({
  connectionString: process.env.TEST_DATABASE_URL,
  max: 30,
});

export async function truncateAll(): Promise<void> {
  await testPool.query(
    `TRUNCATE ledger_entries, ledger_transactions, account_balances, accounts, bonuses
     RESTART IDENTITY CASCADE`,
  );
}

export async function createTestApp(): Promise<{ app: INestApplication; wallet: WalletService }> {
  const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
  const app = moduleRef.createNestApplication();
  await app.init();
  return { app, wallet: app.get(WalletService) };
}

/**
 * The invariant that makes the whole design trustworthy: the cached balance of
 * every account equals the sum of its ledger entries. If these ever diverge,
 * the cache is lying and every number the product shows is suspect.
 */
export async function expectBalancesMatchLedger(): Promise<void> {
  const { rows } = await testPool.query<{ account_id: string; balance: string; ledger_sum: string }>(
    `SELECT b.account_id,
            b.balance::text                  AS balance,
            COALESCE(SUM(e.amount), 0)::text AS ledger_sum
     FROM account_balances b
     LEFT JOIN ledger_entries e ON e.account_id = b.account_id
     GROUP BY b.account_id, b.balance`,
  );

  for (const row of rows) {
    expect({ account: row.account_id, balance: row.balance })
      .toEqual({ account: row.account_id, balance: row.ledger_sum });
  }
}

/**
 * Double-entry's global invariant: across every account in the system, the
 * ledger sums to zero. Money is only ever moved, never created or destroyed —
 * if this fails, a code path is minting money.
 */
export async function expectLedgerSumsToZero(): Promise<void> {
  const { rows } = await testPool.query<{ total: string }>(
    `SELECT COALESCE(SUM(amount), 0)::text AS total FROM ledger_entries`,
  );
  expect(rows[0].total).toBe('0');
}

export async function balanceOf(playerId: string, currency = 'EUR'): Promise<{ real: bigint; bonus: bigint }> {
  const { rows } = await testPool.query<{ type: string; balance: string }>(
    `SELECT a.type, b.balance
     FROM accounts a JOIN account_balances b ON b.account_id = a.id
     WHERE a.player_id = $1 AND a.currency = $2`,
    [playerId, currency],
  );

  let real = 0n;
  let bonus = 0n;
  for (const row of rows) {
    if (row.type === 'PLAYER_REAL') real = BigInt(row.balance);
    if (row.type === 'PLAYER_BONUS') bonus = BigInt(row.balance);
  }
  return { real, bonus };
}
