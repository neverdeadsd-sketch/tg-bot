import { Module } from '@nestjs/common';
import { WalletController } from './wallet.controller';
import { ProviderController } from './provider.controller';
import { WalletService } from './wallet.service';
import { LedgerRepository } from './ledger.repository';
import { BonusRepository } from './bonus.repository';

@Module({
  controllers: [WalletController, ProviderController],
  providers: [WalletService, LedgerRepository, BonusRepository],
  exports: [WalletService],
})
export class WalletModule {}
