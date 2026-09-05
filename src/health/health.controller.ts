import { Controller, Get, ServiceUnavailableException } from '@nestjs/common';
import { DatabaseService } from '../database/database.service';

/** Tables that must exist for the service to be able to do anything at all. */
const REQUIRED_TABLES = [
  'accounts',
  'account_balances',
  'ledger_transactions',
  'ledger_entries',
  'bonuses',
];

/**
 * Readiness probe for the platform's health check.
 *
 * It deliberately checks more than "is the process alive": it opens a database
 * connection AND verifies the schema is present. A process that is running but
 * pointed at an unmigrated database is not healthy — it will answer every real
 * request with a 500, which is exactly the failure this project already shipped
 * once. Returning 503 here makes a deploy fail loudly instead of going live
 * broken.
 */
@Controller('health')
export class HealthController {
  constructor(private readonly db: DatabaseService) {}

  @Get()
  async check(): Promise<Record<string, unknown>> {
    let tables: string[];
    try {
      const rows = await this.db.query<{ table_name: string }>(
        `SELECT table_name FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name = ANY($1::text[])`,
        [REQUIRED_TABLES],
      );
      tables = rows.map((row) => row.table_name);
    } catch (error) {
      throw new ServiceUnavailableException({
        status: 'error',
        reason: 'DATABASE_UNREACHABLE',
        detail: (error as Error).message,
      });
    }

    const missing = REQUIRED_TABLES.filter((name) => !tables.includes(name));
    if (missing.length > 0) {
      throw new ServiceUnavailableException({
        status: 'error',
        reason: 'SCHEMA_NOT_MIGRATED',
        missingTables: missing,
        detail: 'Run the migrations before serving traffic.',
      });
    }

    const [migration] = await this.db.query<{ name: string }>(
      `SELECT name FROM schema_migrations ORDER BY name DESC LIMIT 1`,
    );

    return {
      status: 'ok',
      database: 'reachable',
      schema: 'migrated',
      latestMigration: migration?.name ?? null,
    };
  }
}
