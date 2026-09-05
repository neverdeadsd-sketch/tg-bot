import { CanActivate, ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';
import { createHmac, timingSafeEqual } from 'node:crypto';
import { Request } from 'express';
import { config } from '../config';

/**
 * Verifies the HMAC-SHA256 signature on an inbound game-provider callback.
 *
 * Two details that are easy to get wrong and are the reason this is a guard
 * rather than three lines in a controller:
 *
 *  1. The signature must be computed over the RAW body. Re-serialising the
 *     parsed JSON changes whitespace and key order, and the signature stops
 *     matching for reasons nobody can debug at 3am.
 *
 *  2. The comparison must be constant-time. A plain `===` leaks, through timing,
 *     how many leading bytes were correct, which is enough to forge a signature
 *     one byte at a time.
 */
@Injectable()
export class ProviderSignatureGuard implements CanActivate {
  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest<Request & { rawBody?: Buffer }>();
    const provided = request.header('x-provider-signature');

    if (!provided) {
      throw new UnauthorizedException({ code: 'MISSING_SIGNATURE', message: 'x-provider-signature header is required' });
    }

    const expected = createHmac('sha256', config.providerWebhookSecret)
      .update(request.rawBody ?? Buffer.alloc(0))
      .digest('hex');

    const providedBuffer = Buffer.from(provided, 'utf8');
    const expectedBuffer = Buffer.from(expected, 'utf8');

    // timingSafeEqual throws on length mismatch, so compare lengths first —
    // the length of a signature is not a secret.
    if (
      providedBuffer.length !== expectedBuffer.length ||
      !timingSafeEqual(providedBuffer, expectedBuffer)
    ) {
      throw new UnauthorizedException({ code: 'INVALID_SIGNATURE', message: 'Signature verification failed' });
    }

    return true;
  }
}
