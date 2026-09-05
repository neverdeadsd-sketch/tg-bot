import { HttpException, Injectable, Logger } from '@nestjs/common';
import { createHmac, randomInt, randomUUID } from 'node:crypto';
import { config } from '../config';
import {
  evaluate,
  SYMBOLS,
  Symbol,
  TOTAL_WEIGHT,
  THREE_OF_A_KIND,
  PAIR,
  theoreticalRtp,
} from './paytable';

export interface SpinRequest {
  playerId: string;
  currency: string;
  /** Stake in minor units. */
  bet: number;
}

export interface SpinResult {
  roundId: string;
  reels: { key: string; glyph: string }[];
  kind: string;
  winningSymbol: string | null;
  multiplier: number;
  payout: number;
  balance: Record<string, unknown>;
}

/**
 * A stand-in for a third-party game provider.
 *
 * In a real platform the games are not written by the operator — they are
 * licensed from Pragmatic, Evolution, Playson and friends, and run on the
 * provider's own servers. What the operator writes is the wallet, and the two
 * meet over a "seamless wallet" integration: on every spin the provider calls
 * the operator to debit the stake, and calls again to credit a win.
 *
 * So this service deliberately talks to the wallet the same way a real provider
 * would — over signed HTTP to /provider/*, not by reaching into the service
 * layer next door. That keeps the integration honest: the HMAC guard, the
 * idempotency keys and the error contract are all exercised for real. The cost
 * is a loopback request per call, which is the right trade for a demo whose
 * point is showing the protocol.
 */
@Injectable()
export class GameService {
  private readonly logger = new Logger(GameService.name);

  /** The wallet is this same process; a real provider would hold a public URL. */
  private readonly walletBaseUrl = `http://127.0.0.1:${config.port}`;

  async spin(request: SpinRequest): Promise<SpinResult> {
    const { playerId, currency, bet } = request;
    const roundId = randomUUID();

    // 1. Debit the stake. If the player cannot cover it, the wallet refuses and
    //    the reels never turn — the money decision comes before the game logic.
    const debit = await this.callWallet('/provider/bet', {
      playerId,
      currency,
      amount: bet,
      idempotencyKey: `${roundId}:bet`,
      reference: roundId,
    });
    if (debit.status >= 400) {
      throw new HttpException(debit.body, debit.status);
    }

    // 2. Spin. randomInt is the CSPRNG, not Math.random: a game whose outcomes
    //    can be predicted from previous ones is not a game, and Math.random is
    //    seeded predictably and never intended for anything of value.
    const reels = [this.pickSymbol(), this.pickSymbol(), this.pickSymbol()];
    const outcome = evaluate(reels);
    const payout = Math.round(bet * outcome.multiplier);

    // 3. Credit the win, if there is one.
    let balance = debit.body.balance as Record<string, unknown>;
    if (payout > 0) {
      const credit = await this.callWallet('/provider/win', {
        playerId,
        currency,
        amount: payout,
        idempotencyKey: `${roundId}:win`,
        reference: roundId,
      });
      if (credit.status >= 400) {
        // The stake is already gone. A real provider retries this call until it
        // succeeds — the idempotency key makes that safe — and reconciles what
        // is still unpaid at the end of the day.
        this.logger.error(`Win credit failed for round ${roundId}: ${JSON.stringify(credit.body)}`);
        throw new HttpException(credit.body, credit.status);
      }
      balance = credit.body.balance as Record<string, unknown>;
    }

    return {
      roundId,
      reels: reels.map((s) => ({ key: s.key, glyph: s.glyph })),
      kind: outcome.kind,
      winningSymbol: outcome.winningSymbol,
      multiplier: outcome.multiplier,
      payout,
      balance,
    };
  }

  /** The paytable as the client renders it, with the RTP derived from it. */
  describe(): Record<string, unknown> {
    return {
      symbols: SYMBOLS.map((s) => ({
        key: s.key,
        glyph: s.glyph,
        probability: Number((s.weight / TOTAL_WEIGHT).toFixed(4)),
        threeOfAKind: THREE_OF_A_KIND[s.key] ?? 0,
        pair: PAIR[s.key] ?? 0,
      })),
      rtp: Number((theoreticalRtp() * 100).toFixed(2)),
      houseEdge: Number(((1 - theoreticalRtp()) * 100).toFixed(2)),
    };
  }

  private pickSymbol(): Symbol {
    const roll = randomInt(TOTAL_WEIGHT);
    let cumulative = 0;
    for (const symbol of SYMBOLS) {
      cumulative += symbol.weight;
      if (roll < cumulative) return symbol;
    }
    return SYMBOLS[SYMBOLS.length - 1];
  }

  /**
   * Signs the exact bytes it sends. Re-serialising the body anywhere between
   * signing and sending would change the signature — the guard on the other
   * side verifies against the raw request body.
   */
  private async callWallet(
    path: string,
    body: Record<string, unknown>,
  ): Promise<{ status: number; body: Record<string, any> }> {
    const payload = JSON.stringify(body);
    const signature = createHmac('sha256', config.providerWebhookSecret)
      .update(payload)
      .digest('hex');

    const response = await fetch(`${this.walletBaseUrl}${path}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-provider-signature': signature },
      body: payload,
    });

    return { status: response.status, body: (await response.json()) as Record<string, any> };
  }
}
