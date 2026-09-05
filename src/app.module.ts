import { Module } from '@nestjs/common';
import { DatabaseModule } from './database/database.module';
import { WalletModule } from './wallet/wallet.module';

@Module({
  imports: [DatabaseModule, WalletModule],
})
export class AppModule {}
