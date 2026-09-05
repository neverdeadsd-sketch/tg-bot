import { Body, Controller, Get, Param, ParseUUIDPipe, Post, Query } from '@nestjs/common';
import { WalletService } from './wallet.service';
import { BetDto, DepositDto, GrantBonusDto, WinDto, WithdrawDto } from './dto/wallet.dto';
import { BalanceView, OperationResult } from './domain/types';

@Controller('wallet')
export class WalletController {
  constructor(private readonly wallet: WalletService) {}

  @Post('deposit')
  deposit(@Body() dto: DepositDto): Promise<OperationResult> {
    return this.wallet.deposit({ ...dto, amount: BigInt(dto.amount) });
  }

  @Post('withdraw')
  withdraw(@Body() dto: WithdrawDto): Promise<OperationResult> {
    return this.wallet.withdraw({ ...dto, amount: BigInt(dto.amount) });
  }

  @Post('bet')
  bet(@Body() dto: BetDto): Promise<OperationResult> {
    return this.wallet.bet({ ...dto, amount: BigInt(dto.amount) });
  }

  @Post('win')
  win(@Body() dto: WinDto): Promise<OperationResult> {
    return this.wallet.win({ ...dto, amount: BigInt(dto.amount) });
  }

  @Post('bonus')
  grantBonus(@Body() dto: GrantBonusDto): Promise<OperationResult> {
    return this.wallet.grantBonus({ ...dto, amount: BigInt(dto.amount) });
  }

  @Get(':playerId/balance')
  getBalance(
    @Param('playerId', ParseUUIDPipe) playerId: string,
    @Query('currency') currency = 'EUR',
  ): Promise<BalanceView> {
    return this.wallet.getBalance(playerId, currency);
  }
}
