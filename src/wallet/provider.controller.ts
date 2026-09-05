import { Body, Controller, Post, UseGuards } from '@nestjs/common';
import { WalletService } from './wallet.service';
import { BetDto, WinDto } from './dto/wallet.dto';
import { ProviderSignatureGuard } from './provider-signature.guard';
import { OperationResult } from './domain/types';

/**
 * Seamless-wallet callbacks from a game provider.
 *
 * Providers retry aggressively on any non-2xx response and on timeouts, so
 * every endpoint here must be idempotent. It is: the provider's round/transaction
 * id is passed straight through as the idempotency key, so a retried debit
 * returns the original result instead of charging the player twice.
 */
@Controller('provider')
@UseGuards(ProviderSignatureGuard)
export class ProviderController {
  constructor(private readonly wallet: WalletService) {}

  @Post('bet')
  bet(@Body() dto: BetDto): Promise<OperationResult> {
    return this.wallet.bet({ ...dto, amount: BigInt(dto.amount) });
  }

  @Post('win')
  win(@Body() dto: WinDto): Promise<OperationResult> {
    return this.wallet.win({ ...dto, amount: BigInt(dto.amount) });
  }
}
