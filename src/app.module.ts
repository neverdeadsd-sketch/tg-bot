import { Module } from '@nestjs/common';
import { DatabaseModule } from './database/database.module';
import { WalletModule } from './wallet/wallet.module';
import { HealthModule } from './health/health.module';
import { GameModule } from './game/game.module';

@Module({
  imports: [DatabaseModule, WalletModule, HealthModule, GameModule],
})
export class AppModule {}
