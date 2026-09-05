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

  await app.listen(config.port);
  new Logger('Bootstrap').log(`Wallet listening on port ${config.port}`);
}

void bootstrap();
