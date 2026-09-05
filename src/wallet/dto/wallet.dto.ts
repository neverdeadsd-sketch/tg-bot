import { IsInt, IsNotEmpty, IsOptional, IsString, IsUUID, Length, Max, Min } from 'class-validator';

/**
 * Amounts cross the API as integers in MINOR UNITS (cents), never as decimals.
 * "10.00" invites float rounding somewhere down the line; 1000 does not.
 * Number.MAX_SAFE_INTEGER is ~9 * 10^15, comfortably above any real balance,
 * and the value becomes a BigInt the moment it reaches the service.
 */
class AmountBase {
  @IsUUID()
  playerId: string;

  @IsString()
  @Length(3, 3)
  currency: string;

  @IsInt()
  @Min(1)
  @Max(Number.MAX_SAFE_INTEGER)
  amount: number;

  /** Caller-generated key that makes retrying this request safe. */
  @IsString()
  @IsNotEmpty()
  idempotencyKey: string;

  @IsOptional()
  @IsString()
  reference?: string;
}

export class DepositDto extends AmountBase {}
export class WithdrawDto extends AmountBase {}
export class BetDto extends AmountBase {}
export class WinDto extends AmountBase {}

export class GrantBonusDto extends AmountBase {
  /** Wagering requirement = amount * multiplier. */
  @IsInt()
  @Min(1)
  @Max(200)
  wageringMultiplier: number;
}
