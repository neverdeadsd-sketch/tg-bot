import { Injectable } from '@nestjs/common';
import { PoolClient } from 'pg';
import { createHash } from 'node:crypto';
import { DatabaseService } from '../database/database.service';
import { LedgerRepository } from './ledger.repository';
import { BonusRepository, findActiveBonus } from './bonus.repository';
import {
  BalanceView,
  LedgerEntryDraft,
  OperationResult,
  TransactionKind,
  TransactionView,
} from './domain/types';
import {
  ActiveBonusExistsException,
  InsufficientFundsException,
  WageringNotMetException,
} from './domain/errors';

const UNIQUE_VIOLATION = '23505';

export interface MoneyOperation {
  playerId: string;
  currency: string;
  /** Amount in minor units (cents). Always positive. */
  amount: bigint;
  idempotencyKey: string;
  reference?: string;
}

export interface BonusGrantOperation extends MoneyOperation {
  wageringMultiplier: number;
}

/**
 * Fingerprints the business payload of a request.
 *
 * Replaying the same idempotency key with the same payload must return the
 * stored result; replaying it with a different payload is a caller bug we want
 * to surface. Keys are sorted so field order in the request body cannot change
 * the hash. (Payloads here are flat; nested objects would need a deep
 * canonicaliser.)
 */
function hashRequest(payload: Record<string, string | number>): string {
  const canonical = JSON.stringify(payload, Object.keys(payload).sort());
  return createHash('sha256').update(canonical).digest('hex');
}

@Injectable()
export class WalletService {
  constructor(
    private readonly db: DatabaseService,
    private readonly ledger: LedgerRepository,
    private readonly bonuses: BonusRepository,
  ) {}

  /**
   * Money enters the system: the deposit account is debited, the player's real
   * balance credited. The deposit account is allowed to go negative — it
   * represents the outside world, and its balance is the running total of
   * everything ever paid in.
   */
  async deposit(op: MoneyOperation): Promise<OperationResult> {
    return this.executeIdempotent('DEPOSIT', op, hashRequest({
      playerId: op.playerId,
      currency: op.currency,
      amount: op.amount.toString(),
    }), async (client, transactionId) => {
      const realAccount = await this.ledger.getOrCreateAccount(client, op.playerId, 'PLAYER_REAL', op.currency);
      const depositAccount = await this.ledger.getOrCreateAccount(client, null, 'SYSTEM_DEPOSIT', op.currency);

      await this.ledger.lockBalances(client, [realAccount, depositAccount]);
      await this.ledger.applyEntries(client, transactionId, [
        { accountId: depositAccount, amount: -op.amount },
        { accountId: realAccount, amount: op.amount },
      ], op.currency);

      return this.buildBalanceView(client, op.playerId, op.currency);
    });
  }

  /**
   * Money leaves the system. Two gates: an unmet wagering requirement blocks the
   * withdrawal entirely, and only the real (non-bonus) balance is withdrawable.
   */
  async withdraw(op: MoneyOperation): Promise<OperationResult> {
    return this.executeIdempotent('WITHDRAWAL', op, hashRequest({
      playerId: op.playerId,
      currency: op.currency,
      amount: op.amount.toString(),
    }), async (client, transactionId) => {
      const realAccount = await this.ledger.getOrCreateAccount(client, op.playerId, 'PLAYER_REAL', op.currency);
      const payoutAccount = await this.ledger.getOrCreateAccount(client, null, 'SYSTEM_PAYOUT', op.currency);

      const locked = await this.ledger.lockBalances(client, [realAccount, payoutAccount]);
      const realBalance = locked.get(realAccount) ?? 0n;

      const activeBonus = await this.bonuses.findActiveForUpdate(client, op.playerId, op.currency);
      if (activeBonus) {
        const remaining = activeBonus.wageringRequired - activeBonus.wageringProgress;
        if (remaining > 0n) {
          throw new WageringNotMetException(remaining);
        }
      }

      if (realBalance < op.amount) {
        throw new InsufficientFundsException(realBalance, op.amount);
      }

      await this.ledger.applyEntries(client, transactionId, [
        { accountId: realAccount, amount: -op.amount },
        { accountId: payoutAccount, amount: op.amount },
      ], op.currency);

      return this.buildBalanceView(client, op.playerId, op.currency);
    });
  }

  /**
   * Places a bet.
   *
   * Real money is spent first; the bonus balance covers only what real money
   * cannot, which is why a single bet can span two accounts. This is the
   * "sticky bonus" model: the bonus sits locked until the player has wagered
   * enough of their own money, and only then becomes withdrawable.
   *
   * The full stake counts toward the wagering requirement. When the requirement
   * is met, the surviving bonus balance is released to real money as a separate
   * BONUS_CONVERT transaction, so the audit trail shows the release explicitly
   * instead of burying it inside whichever bet happened to trigger it.
   */
  async bet(op: MoneyOperation): Promise<OperationResult> {
    return this.executeIdempotent('BET', op, hashRequest({
      playerId: op.playerId,
      currency: op.currency,
      amount: op.amount.toString(),
      reference: op.reference ?? '',
    }), async (client, transactionId) => {
      const bonusAccount = await this.ledger.getOrCreateAccount(client, op.playerId, 'PLAYER_BONUS', op.currency);
      const realAccount = await this.ledger.getOrCreateAccount(client, op.playerId, 'PLAYER_REAL', op.currency);
      const houseAccount = await this.ledger.getOrCreateAccount(client, null, 'SYSTEM_HOUSE', op.currency);

      const locked = await this.ledger.lockBalances(client, [bonusAccount, realAccount, houseAccount]);
      const bonusBalance = locked.get(bonusAccount) ?? 0n;
      const realBalance = locked.get(realAccount) ?? 0n;

      const fromReal = realBalance < op.amount ? realBalance : op.amount;
      const fromBonus = op.amount - fromReal;

      if (fromBonus > bonusBalance) {
        throw new InsufficientFundsException(realBalance + bonusBalance, op.amount);
      }

      const entries: LedgerEntryDraft[] = [{ accountId: houseAccount, amount: op.amount }];
      if (fromReal > 0n) entries.push({ accountId: realAccount, amount: -fromReal });
      if (fromBonus > 0n) entries.push({ accountId: bonusAccount, amount: -fromBonus });

      await this.ledger.applyEntries(client, transactionId, entries, op.currency);

      await this.progressWagering(client, op, {
        bonusAccount,
        realAccount,
        bonusBalanceAfterBet: bonusBalance - fromBonus,
      });

      return this.buildBalanceView(client, op.playerId, op.currency);
    });
  }

  /**
   * Credits a win. Wins are paid to the real balance; a stricter model would
   * pay wins from bonus-funded rounds back into the bonus balance — see the
   * "Deliberate simplifications" section of the README.
   */
  async win(op: MoneyOperation): Promise<OperationResult> {
    return this.executeIdempotent('WIN', op, hashRequest({
      playerId: op.playerId,
      currency: op.currency,
      amount: op.amount.toString(),
      reference: op.reference ?? '',
    }), async (client, transactionId) => {
      const realAccount = await this.ledger.getOrCreateAccount(client, op.playerId, 'PLAYER_REAL', op.currency);
      const houseAccount = await this.ledger.getOrCreateAccount(client, null, 'SYSTEM_HOUSE', op.currency);

      await this.ledger.lockBalances(client, [realAccount, houseAccount]);
      await this.ledger.applyEntries(client, transactionId, [
        { accountId: houseAccount, amount: -op.amount },
        { accountId: realAccount, amount: op.amount },
      ], op.currency);

      return this.buildBalanceView(client, op.playerId, op.currency);
    });
  }

  /** Grants a bonus with a wagering requirement of amount * multiplier. */
  async grantBonus(op: BonusGrantOperation): Promise<OperationResult> {
    return this.executeIdempotent('BONUS_GRANT', op, hashRequest({
      playerId: op.playerId,
      currency: op.currency,
      amount: op.amount.toString(),
      wageringMultiplier: op.wageringMultiplier,
    }), async (client, transactionId) => {
      const bonusAccount = await this.ledger.getOrCreateAccount(client, op.playerId, 'PLAYER_BONUS', op.currency);
      const houseAccount = await this.ledger.getOrCreateAccount(client, null, 'SYSTEM_HOUSE', op.currency);

      await this.ledger.lockBalances(client, [bonusAccount, houseAccount]);

      try {
        await this.bonuses.create(client, op.playerId, op.currency, op.amount, op.wageringMultiplier);
      } catch (error) {
        // bonuses_one_active_per_player_uq. Checking first would leave a race
        // window between the check and the insert, so we let the database
        // decide and translate its error into a domain one.
        if ((error as { code?: string }).code === UNIQUE_VIOLATION) {
          throw new ActiveBonusExistsException(op.playerId);
        }
        throw error;
      }

      await this.ledger.applyEntries(client, transactionId, [
        { accountId: houseAccount, amount: -op.amount },
        { accountId: bonusAccount, amount: op.amount },
      ], op.currency);

      return this.buildBalanceView(client, op.playerId, op.currency);
    });
  }

  async getBalance(playerId: string, currency: string): Promise<BalanceView> {
    return this.db.withTransaction((client) => this.buildBalanceView(client, playerId, currency));
  }

  async getTransactions(playerId: string, limit?: number): Promise<TransactionView[]> {
    return this.db.withTransaction((client) =>
      this.ledger.listTransactions(client, playerId, limit),
    );
  }

  // ---------------------------------------------------------------------------
  // internals
  // ---------------------------------------------------------------------------

  /**
   * The shape every money operation shares: claim the key, do the work exactly
   * once, snapshot the response. A duplicate request never reaches `work`.
   */
  private async executeIdempotent(
    kind: TransactionKind,
    op: MoneyOperation,
    requestHash: string,
    work: (client: PoolClient, transactionId: string) => Promise<BalanceView>,
  ): Promise<OperationResult> {
    return this.db.withTransaction(async (client) => {
      const claim = await this.ledger.claimIdempotencyKey(client, {
        idempotencyKey: op.idempotencyKey,
        requestHash,
        kind,
        playerId: op.playerId,
        reference: op.reference ?? null,
        metadata: { amount: op.amount.toString(), currency: op.currency },
      });

      if (claim.replayedResult) {
        return { ...(claim.replayedResult as unknown as OperationResult), replayed: true };
      }

      const balance = await work(client, claim.transactionId);
      const result: OperationResult = {
        transactionId: claim.transactionId,
        kind,
        replayed: false,
        balance,
      };

      await this.ledger.storeResult(client, claim.transactionId, result as unknown as Record<string, unknown>);
      return result;
    });
  }

  /**
   * Advances the wagering requirement by the stake and, once it is met, closes
   * the bonus and releases any remaining bonus balance to real money.
   */
  private async progressWagering(
    client: PoolClient,
    op: MoneyOperation,
    accounts: { bonusAccount: string; realAccount: string; bonusBalanceAfterBet: bigint },
  ): Promise<void> {
    const activeBonus = await this.bonuses.findActiveForUpdate(client, op.playerId, op.currency);
    if (!activeBonus) return;

    const progress = await this.bonuses.addProgress(client, activeBonus.id, op.amount);
    if (progress < activeBonus.wageringRequired) return;

    await this.bonuses.markCompleted(client, activeBonus.id);

    if (accounts.bonusBalanceAfterBet <= 0n) return;

    // A distinct ledger transaction, so the release is visible in the audit
    // trail rather than hidden inside the bet that happened to trigger it.
    // Its key is derived from the bet's, which keeps it unique and replay-safe.
    const convert = await this.ledger.claimIdempotencyKey(client, {
      idempotencyKey: `${op.idempotencyKey}:bonus-convert`,
      requestHash: hashRequest({ bonusId: activeBonus.id }),
      kind: 'BONUS_CONVERT',
      playerId: op.playerId,
      reference: activeBonus.id,
      metadata: { released: accounts.bonusBalanceAfterBet.toString() },
    });

    // Both accounts are already locked by the enclosing bet transaction.
    await this.ledger.applyEntries(client, convert.transactionId, [
      { accountId: accounts.bonusAccount, amount: -accounts.bonusBalanceAfterBet },
      { accountId: accounts.realAccount, amount: accounts.bonusBalanceAfterBet },
    ], op.currency);
  }

  private async buildBalanceView(
    client: PoolClient,
    playerId: string,
    currency: string,
  ): Promise<BalanceView> {
    const { real, bonus } = await this.ledger.getBalances(client, playerId, currency);
    const activeBonus = await findActiveBonus(client, playerId, currency);

    const remaining = activeBonus
      ? activeBonus.wageringRequired - activeBonus.wageringProgress
      : 0n;

    return {
      playerId,
      currency,
      real: real.toString(),
      bonus: bonus.toString(),
      total: (real + bonus).toString(),
      wagering: activeBonus
        ? {
            required: activeBonus.wageringRequired.toString(),
            progress: activeBonus.wageringProgress.toString(),
            remaining: (remaining > 0n ? remaining : 0n).toString(),
          }
        : null,
    };
  }
}
