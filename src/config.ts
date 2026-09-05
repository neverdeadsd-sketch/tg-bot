import { config as loadDotenv } from 'dotenv';

loadDotenv();

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable ${name}. Copy .env.example to .env.`);
  }
  return value;
}

export const config = {
  port: Number(process.env.PORT ?? 3000),
  nodeEnv: process.env.NODE_ENV ?? 'development',

  // Tests run against a separate database because they truncate tables.
  databaseUrl:
    process.env.NODE_ENV === 'test'
      ? required('TEST_DATABASE_URL')
      : required('DATABASE_URL'),

  providerWebhookSecret: process.env.PROVIDER_WEBHOOK_SECRET ?? 'dev-secret-change-me',
};
