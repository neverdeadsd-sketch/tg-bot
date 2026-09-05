import { randomInt } from 'node:crypto';
import {
  evaluate,
  SYMBOLS,
  Symbol,
  theoreticalRtp,
  TOTAL_WEIGHT,
} from '../src/game/paytable';

const bySymbol = (key: string): Symbol => SYMBOLS.find((s) => s.key === key)!;

function pick(): Symbol {
  const roll = randomInt(TOTAL_WEIGHT);
  let cumulative = 0;
  for (const symbol of SYMBOLS) {
    cumulative += symbol.weight;
    if (roll < cumulative) return symbol;
  }
  return SYMBOLS[SYMBOLS.length - 1];
}

describe('slot paytable', () => {
  describe('evaluate', () => {
    it('pays three of a kind', () => {
      const seven = bySymbol('SEVEN');
      expect(evaluate([seven, seven, seven])).toEqual({
        multiplier: 190,
        winningSymbol: 'SEVEN',
        kind: 'THREE_OF_A_KIND',
      });
    });

    it('pays a pair only for the high symbols', () => {
      const star = bySymbol('STAR');
      const lemon = bySymbol('LEMON');
      expect(evaluate([star, star, lemon]).kind).toBe('PAIR');
      expect(evaluate([star, star, lemon]).multiplier).toBe(1);
    });

    it('does not pay a pair of low symbols', () => {
      const cherry = bySymbol('CHERRY');
      const bell = bySymbol('BELL');
      expect(evaluate([cherry, cherry, bell])).toEqual({
        multiplier: 0,
        winningSymbol: null,
        kind: 'NO_WIN',
      });
    });

    it('does not pay three different symbols', () => {
      expect(evaluate([bySymbol('CHERRY'), bySymbol('LEMON'), bySymbol('BELL')]).kind)
        .toBe('NO_WIN');
    });
  });

  describe('return to player', () => {
    it('matches the value derived from the paytable', () => {
      // Enumerated exactly over all 5³ outcomes, so this is a fact about the
      // table above rather than a measurement. If a weight or a payout changes,
      // this number moves and the assertion says so.
      expect(theoreticalRtp()).toBeCloseTo(0.9484, 4);
    });

    it('stays inside a band a real operator could ship', () => {
      // The guard that matters commercially: a slot paying out more than it
      // takes is not a rounding error, and one paying far too little fails
      // licensing. An edit that breaks either bound should fail here.
      const rtp = theoreticalRtp();
      expect(rtp).toBeGreaterThan(0.85);
      expect(rtp).toBeLessThan(0.98);
    });

    it('is reproduced by the RNG over many spins', () => {
      const spins = 200_000;
      let staked = 0;
      let paid = 0;
      for (let i = 0; i < spins; i++) {
        staked += 100;
        paid += 100 * evaluate([pick(), pick(), pick()]).multiplier;
      }
      // A wide band on purpose: this asserts the generator draws from the
      // declared weights, not that a sample equals its expectation.
      expect(paid / staked).toBeCloseTo(theoreticalRtp(), 1);
    });
  });

  describe('reel strip', () => {
    it('declares weights that sum to a round total', () => {
      expect(TOTAL_WEIGHT).toBe(100);
    });

    it('gives every symbol a distinct key and glyph', () => {
      expect(new Set(SYMBOLS.map((s) => s.key)).size).toBe(SYMBOLS.length);
      expect(new Set(SYMBOLS.map((s) => s.glyph)).size).toBe(SYMBOLS.length);
    });
  });
});
