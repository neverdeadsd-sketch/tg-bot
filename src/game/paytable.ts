/**
 * The maths of the slot, in one file.
 *
 * Reel strips, payouts and the resulting RTP live together because they are one
 * decision: change a weight and the return-to-player changes with it. Keeping
 * them apart is how a "small tweak" to a symbol quietly turns a 95% game into a
 * 110% one, and a slot that pays out more than it takes is not a rounding error,
 * it is the whole business.
 */

export interface Symbol {
  key: string;
  glyph: string;
  weight: number;
}

/** One strip, used on all three reels. Weights are relative, not percentages. */
export const SYMBOLS: Symbol[] = [
  { key: 'CHERRY', glyph: '🍒', weight: 30 },
  { key: 'LEMON', glyph: '🍋', weight: 25 },
  { key: 'BELL', glyph: '🔔', weight: 20 },
  { key: 'STAR', glyph: '⭐', weight: 15 },
  { key: 'SEVEN', glyph: '7️⃣', weight: 10 },
];

export const TOTAL_WEIGHT = SYMBOLS.reduce((sum, s) => sum + s.weight, 0);

/** Three of a kind. */
export const THREE_OF_A_KIND: Record<string, number> = {
  CHERRY: 6,
  LEMON: 10,
  BELL: 20,
  STAR: 50,
  SEVEN: 190,
};

/** Exactly two of a kind — only the high symbols pay. */
export const PAIR: Record<string, number> = {
  STAR: 1,
  SEVEN: 2,
};

export interface SpinOutcome {
  multiplier: number;
  /** Which symbol formed the win, for the client to highlight. */
  winningSymbol: string | null;
  kind: 'THREE_OF_A_KIND' | 'PAIR' | 'NO_WIN';
}

export function evaluate(reels: Symbol[]): SpinOutcome {
  const [a, b, c] = reels;

  if (a.key === b.key && b.key === c.key) {
    return {
      multiplier: THREE_OF_A_KIND[a.key] ?? 0,
      winningSymbol: a.key,
      kind: 'THREE_OF_A_KIND',
    };
  }

  const counts = new Map<string, number>();
  for (const s of reels) counts.set(s.key, (counts.get(s.key) ?? 0) + 1);
  const paired = [...counts.entries()].find(([, n]) => n === 2)?.[0];

  if (paired && PAIR[paired]) {
    return { multiplier: PAIR[paired], winningSymbol: paired, kind: 'PAIR' };
  }
  return { multiplier: 0, winningSymbol: null, kind: 'NO_WIN' };
}

/**
 * Exact theoretical RTP, computed by enumerating all 5³ outcomes rather than
 * simulated. A regulator asks for this number and expects it to be derived, and
 * computing it here means it can never drift from the paytable above.
 */
export function theoreticalRtp(): number {
  let expected = 0;
  for (const a of SYMBOLS) {
    for (const b of SYMBOLS) {
      for (const c of SYMBOLS) {
        const probability =
          (a.weight / TOTAL_WEIGHT) * (b.weight / TOTAL_WEIGHT) * (c.weight / TOTAL_WEIGHT);
        expected += probability * evaluate([a, b, c]).multiplier;
      }
    }
  }
  return expected;
}
