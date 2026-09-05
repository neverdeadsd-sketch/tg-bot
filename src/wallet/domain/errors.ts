import { ConflictException, HttpException, HttpStatus, UnprocessableEntityException } from '@nestjs/common';

/**
 * Domain errors carry a stable machine-readable `code` alongside the HTTP
 * status. Clients — especially game providers retrying a seamless-wallet call —
 * branch on the code, never on the message text.
 */
export class DomainException extends HttpException {
  constructor(code: string, message: string, status: HttpStatus) {
    super({ code, message }, status);
  }
}

export class InsufficientFundsException extends DomainException {
  constructor(available: bigint, requested: bigint) {
    super(
      'INSUFFICIENT_FUNDS',
      `Insufficient funds: available ${available}, requested ${requested}`,
      HttpStatus.UNPROCESSABLE_ENTITY,
    );
  }
}

export class WageringNotMetException extends DomainException {
  constructor(remaining: bigint) {
    super(
      'WAGERING_NOT_MET',
      `Withdrawal blocked: ${remaining} of wagering requirement remaining`,
      HttpStatus.UNPROCESSABLE_ENTITY,
    );
  }
}

/**
 * Same idempotency key, different payload. This is always a caller bug — either
 * a key collision or a mutated retry — and silently returning the stored result
 * would hide it, so we surface it instead.
 */
export class IdempotencyKeyConflictException extends ConflictException {
  constructor(key: string) {
    super({
      code: 'IDEMPOTENCY_KEY_CONFLICT',
      message: `Idempotency key ${key} was already used with a different payload`,
    });
  }
}

export class ActiveBonusExistsException extends ConflictException {
  constructor(playerId: string) {
    super({
      code: 'ACTIVE_BONUS_EXISTS',
      message: `Player ${playerId} already holds an active bonus`,
    });
  }
}

export class UnbalancedTransactionException extends UnprocessableEntityException {
  constructor(sum: bigint) {
    super({
      code: 'UNBALANCED_TRANSACTION',
      message: `Double-entry violation: ledger entries sum to ${sum}, expected 0`,
    });
  }
}
