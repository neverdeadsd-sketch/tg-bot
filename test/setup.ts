import { runMigrations } from '../scripts/migrate';
import { testPool, truncateAll } from './helpers';

beforeAll(async () => {
  // Idempotent: schema_migrations makes re-running a no-op, so every test file
  // can safely ensure the schema exists.
  await runMigrations(process.env.TEST_DATABASE_URL as string);
});

beforeEach(async () => {
  await truncateAll();
});

afterAll(async () => {
  await testPool.end();
});
