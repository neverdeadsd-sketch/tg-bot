import 'reflect-metadata';
import { Logger, ValidationPipe } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { config } from './config';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, {
    // Needed to verify provider webhook signatures over the exact bytes we
    // received — see ProviderSignatureGuard.
    rawBody: true,
  });

  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,          // strip unknown fields instead of trusting them
      forbidNonWhitelisted: true,
      transform: true,
    }),
  );

  // Bind to all interfaces explicitly: inside a container, listening on
  // localhost makes the service unreachable from the platform's router, and
  // the deploy fails a health check that the app itself thinks is fine.
  await app.listen(config.port, '0.0.0.0');
  new Logger('Bootstrap').log(`Wallet listening on port ${config.port}`);
}

void bootstrap();
