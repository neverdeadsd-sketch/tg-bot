import { config as loadDotenv } from 'dotenv';

loadDotenv();

// Must be set before src/config.ts is imported: it picks TEST_DATABASE_URL
// only when NODE_ENV is 'test'.
process.env.NODE_ENV = 'test';
process.env.TEST_DATABASE_URL ??= 'postgres://wallet:wallet@localhost:5432/wallet_test';
