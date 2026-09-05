import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { Client } from 'pg';
import { config as loadDotenv } from 'dotenv';

// Resolved at runtime because this file runs both from source (ts-node, so
// __dirname is scripts/) and from the compiled output (dist/scripts/).
const MIGRATIONS_DIR =
  [
    join(__dirname, '..', 'migrations'),
    join(__dirname, '..', '..', 'migrations'),
    join(process.cwd(), 'migrations'),
  ].find(existsSync) ?? join(process.cwd(), 'migrations');

/**
 * Minimal forward-only migration runner.
 *
 * Each .sql file runs once, inside its own transaction, in filename order, and
 * is recorded in schema_migrations. A real project would reach for a library
 * once it needs rollbacks or branching history — this is deliberately small
 * enough to read in one sitting.
 */
export async function runMigrations(connectionString: string): Promise<string[]> {
  const client = new Client({ connectionString });
  await client.connect();
  const applied: string[] = [];

  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        name       text PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT now()
      )
    `);

    const { rows } = await client.query<{ name: string }>('SELECT name FROM schema_migrations');
    const done = new Set(rows.map((row) => row.name));

    const files = readdirSync(MIGRATIONS_DIR).filter((f) => f.endsWith('.sql')).sort();

    for (const file of files) {
      if (done.has(file)) continue;

      const sql = readFileSync(join(MIGRATIONS_DIR, file), 'utf8');
      await client.query('BEGIN');
      try {
        await client.query(sql);
        await client.query('INSERT INTO schema_migrations (name) VALUES ($1)', [file]);
        await client.query('COMMIT');
        applied.push(file);
      } catch (error) {
        await client.query('ROLLBACK');
        throw new Error(`Migration ${file} failed: ${(error as Error).message}`);
      }
    }
  } finally {
    await client.end();
  }

  return applied;
}

if (require.main === module) {
  // The app reads .env through src/config.ts; the migration runner is a
  // separate entry point and has to load it too, or `npm run migrate` silently
  // targets nothing on a machine where the variable is not exported by hand.
  loadDotenv();

  const url = process.env.DATABASE_URL;
  if (!url) {
    console.error(
      'DATABASE_URL is not set. Copy .env.example to .env and fill it in, ' +
        'or export DATABASE_URL in your shell.',
    );
    process.exit(1);
  }

  runMigrations(url)
    .then((applied) => {
      console.log(applied.length ? `Applied: ${applied.join(', ')}` : 'Already up to date');
      process.exit(0);
    })
    .catch((error) => {
      console.error(error.message);
      process.exit(1);
    });
}
