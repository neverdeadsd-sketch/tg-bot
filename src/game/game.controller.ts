import { Body, Controller, Get, Post } from '@nestjs/common';
import { IsInt, IsString, IsUUID, Length, Max, Min } from 'class-validator';
import { GameService, SpinResult } from './game.service';

export class SpinDto {
  @IsUUID()
  playerId: string;

  @IsString()
  @Length(3, 3)
  currency: string;

  /** Stake in minor units. Capped so a demo cannot ask for an absurd payout. */
  @IsInt()
  @Min(1)
  @Max(1_000_000)
  bet: number;
}

@Controller('game')
export class GameController {
  constructor(private readonly game: GameService) {}

  @Get('paytable')
  paytable(): Record<string, unknown> {
    return this.game.describe();
  }

  @Post('spin')
  spin(@Body() dto: SpinDto): Promise<SpinResult> {
    return this.game.spin(dto);
  }
}
