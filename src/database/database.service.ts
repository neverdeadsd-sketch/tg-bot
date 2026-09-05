import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { Pool, PoolClient, QueryResultRow } from 'pg';
import { config } from '../config';

/**
 * Postgres error codes we retry on. Both mean "the database refused to let two
 * transactions interleave the way they tried to" — retrying is the documented
 * remedy, not a workaround.
 */
const RETRYABLE_ERROR_CODES = new Set([
  '40001', // serialization_failure
  '40P01', // deadlock_detected
]);

export type TransactionFn<T> = (client: PoolClient) => Promise<T>;

@Injectable()
export class DatabaseService implements OnModuleDestroy {
  private readonly logger = new Logger(DatabaseService.name);
  private readonly pool: Pool;

  constructor() {
    this.pool = new Pool({
      connectionString: config.databaseUrl,
      // Keep this comfortably below Postgres max_connections. Every concurrent
      // transaction holds a connection for its whole lifetime, so an
      // undersized pool shows up as latency, an oversized one as errors.
      max: Number(process.env.DATABASE_POOL_SIZE ?? 20),
      idleTimeoutMillis: 30_000,
      connectionTimeoutMillis: 5_000,
    });
  }

  async query<T extends QueryResultRow>(text: string, params: unknown[] = []): Promise<T[]> {
    const result = await this.pool.query<T>(text, params);
    return result.rows;
  }

  /**
   * Runs `fn` inside a single database transaction, retrying on deadlock and
   * serialization failures with a short randomised backoff.
   *
   * Everything money-related goes through here. A partially applied ledger
   * write is worse than a failed one, so there is no code path that writes an
   * entry outside a transaction.
   */
  async withTransaction<T>(fn: TransactionFn<T>, maxAttempts = 3): Promise<T> {
    let lastError: unknown;

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      const client = await this.pool.connect();
      try {
        await client.query('BEGIN');
        const result = await fn(client);
        await client.query('COMMIT');
        return result;
      } catch (error) {
        await client.query('ROLLBACK').catch(() => undefined);
        lastError = error;

        const code = (error as { code?: string }).code;
        if (!code || !RETRYABLE_ERROR_CODES.has(code) || attempt === maxAttempts) {
          throw error;
        }

        // Randomised backoff so retrying transactions do not collide again in
        // lockstep. Tiny delays are enough — these conflicts resolve fast.
        const delayMs = Math.floor(Math.random() * 10 * attempt) + 5;
        this.logger.warn(`Retrying transaction after ${code} (attempt ${attempt}/${maxAttempts})`);
        await new Promise((resolve) => setTimeout(resolve, delayMs));
      } finally {
        client.release();
      }
    }

    throw lastError;
  }

  async onModuleDestroy(): Promise<void> {
    await this.pool.end();
  }
}
