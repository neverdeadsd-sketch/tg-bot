import { Injectable } from '@nestjs/common';
import { PoolClient } from 'pg';
import { Bonus, BonusStatus } from './domain/types';

interface BonusRow {
  id: string;
  player_id: string;
  currency: string;
  granted_amount: string;
  wagering_multiplier: number;
  wagering_required: string;
  wagering_progress: string;
  status: BonusStatus;
}

function toBonus(row: BonusRow): Bonus {
  return {
    id: row.id,
    playerId: row.player_id,
    currency: row.currency,
    grantedAmount: BigInt(row.granted_amount),
    wageringMultiplier: row.wagering_multiplier,
    wageringRequired: BigInt(row.wagering_required),
    wageringProgress: BigInt(row.wagering_progress),
    status: row.status,
  };
}

@Injectable()
export class BonusRepository {
  /**
   * Loads the player's active bonus and locks it for the rest of the
   * transaction, so two concurrent bets cannot both read the same wagering
   * progress and each write back their own increment (a lost update).
   */
  async findActiveForUpdate(
    client: PoolClient,
    playerId: string,
    currency: string,
  ): Promise<Bonus | null> {
    const { rows } = await client.query<BonusRow>(
      `SELECT * FROM bonuses
       WHERE player_id = $1 AND currency = $2 AND status = 'ACTIVE'
       FOR UPDATE`,
      [playerId, currency],
    );
    return rows.length > 0 ? toBonus(rows[0]) : null;
  }

  async create(
    client: PoolClient,
    playerId: string,
    currency: string,
    grantedAmount: bigint,
    wageringMultiplier: number,
  ): Promise<Bonus> {
    const { rows } = await client.query<BonusRow>(
      `INSERT INTO bonuses (player_id, currency, granted_amount, wagering_multiplier, wagering_required)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING *`,
      [
        playerId,
        currency,
        grantedAmount.toString(),
        wageringMultiplier,
        (grantedAmount * BigInt(wageringMultiplier)).toString(),
      ],
    );
    return toBonus(rows[0]);
  }

  async addProgress(client: PoolClient, bonusId: string, amount: bigint): Promise<bigint> {
    const { rows } = await client.query<{ wagering_progress: string }>(
      `UPDATE bonuses
       SET wagering_progress = wagering_progress + $2
       WHERE id = $1
       RETURNING wagering_progress`,
      [bonusId, amount.toString()],
    );
    return BigInt(rows[0].wagering_progress);
  }

  async markCompleted(client: PoolClient, bonusId: string): Promise<void> {
    await client.query(
      `UPDATE bonuses SET status = 'COMPLETED', completed_at = now() WHERE id = $1`,
      [bonusId],
    );
  }
}

/**
 * Non-locking read used by the balance view. Kept separate from
 * findActiveForUpdate so a plain balance query does not take write locks.
 */
export async function findActiveBonus(
  client: PoolClient,
  playerId: string,
  currency: string,
): Promise<Bonus | null> {
  const { rows } = await client.query<BonusRow>(
    `SELECT * FROM bonuses
     WHERE player_id = $1 AND currency = $2 AND status = 'ACTIVE'`,
    [playerId, currency],
  );
  return rows.length > 0 ? toBonus(rows[0]) : null;
}
