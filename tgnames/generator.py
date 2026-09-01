"""Candidate generation strategies.

Every strategy is a generator of raw strings; the caller scores and filters
them. Strategies are deliberately cheap so the pipeline can produce tens of
thousands of candidates and let `scoring` do the selection.
"""

from __future__ import annotations

import itertools
import random
import string
from collections.abc import Iterable, Iterator

from . import wordlists
from .scoring import MAX_LENGTH, MIN_LENGTH, validate

LETTERS = string.ascii_lowercase
DIGITS = string.digits
CONSONANTS = "bcdfghjklmnprstvwz"
VOWELS = "aeiou"


def _clean(items: Iterable[str]) -> Iterator[str]:
    """Drop anything Telegram would reject, de-duplicated, order preserved."""
    seen: set[str] = set()
    for item in items:
        u = item.strip().lower()
        if u in seen:
            continue
        seen.add(u)
        if validate(u) is None:
            yield u


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
def words(min_len: int = MIN_LENGTH, max_len: int = 12) -> Iterator[str]:
    """Straight dictionary words that are already valid handles."""
    yield from _clean(w for w in sorted(wordlists.vocabulary()) if min_len <= len(w) <= max_len)


def combos(max_len: int = 12) -> Iterator[str]:
    """prefix+word and word+suffix, e.g. thevault / goldhq."""
    prefixes, suffixes = wordlists.affixes()
    vocab = sorted(w for w in wordlists.vocabulary() if 3 <= len(w) <= 8)
    out: list[str] = []
    for word in vocab:
        for p in prefixes:
            if len(p) + len(word) <= max_len:
                out.append(p + word)
        for s in suffixes:
            if len(word) + len(s) <= max_len:
                out.append(word + s)
    yield from _clean(out)


def compounds(max_len: int = 12, limit: int = 40000) -> Iterator[str]:
    """word+word pairs drawn from the premium and crypto vocabulary."""
    cats = wordlists.categories()
    left = sorted(cats["premium"] | cats["crypto"])
    right = sorted(cats["premium"] | cats["tech"] | cats["common"])
    count = 0
    seen: set[str] = set()
    for a, b in itertools.product(left, right):
        if a == b:
            continue
        u = a + b
        if len(u) > max_len or u in seen:
            continue
        seen.add(u)
        if validate(u) is None:
            yield u
            count += 1
            if count >= limit:
                return


def patterns(length: int = 5) -> Iterator[str]:
    """Structurally valuable shapes: aaaaa, ababa, abcde, aabbc ..."""
    out: list[str] = []
    # single repeated letter
    out += [c * length for c in LETTERS]
    # two-letter alternation
    for a, b in itertools.permutations(LETTERS, 2):
        out.append((a + b) * (length // 2 + 1))
    # alphabetic runs both ways
    for start in range(len(LETTERS)):
        fwd = "".join(LETTERS[(start + i) % 26] for i in range(length))
        bwd = "".join(LETTERS[(start - i) % 26] for i in range(length))
        out += [fwd, bwd]
    # letter + repdigit / run, e.g. a7777, x1234
    run_up = "".join(str((i + 1) % 10) for i in range(length - 1))
    run_down = "".join(str((9 - i) % 10) for i in range(length - 1))
    for c in LETTERS:
        for d in DIGITS:
            out.append(c + d * (length - 1))
        out.append(c + run_up)
        out.append(c + run_down)
    yield from _clean(u[:length] for u in out)


def brandables(count: int = 2000, syllables: int = 2, seed: int | None = None) -> Iterator[str]:
    """Pronounceable CVCV brand names: rivo, kalum, zenta ..."""
    rng = random.Random(seed)
    out: list[str] = []
    for _ in range(count * 3):
        u = "".join(rng.choice(CONSONANTS) + rng.choice(VOWELS) for _ in range(syllables))
        if rng.random() < 0.45:
            u += rng.choice(CONSONANTS)
        out.append(u)
    yield from itertools.islice(_clean(out), count)


def numeric(prefix_len: int = 3, count: int = 3000, seed: int | None = None) -> Iterator[str]:
    """Word or letter stem plus an attractive number: gold777, ton100."""
    rng = random.Random(seed)
    numbers = [str(d) * n for d in range(10) for n in (2, 3, 4)]
    numbers += ["100", "007", "123", "1000", "247", "365", "911", "777", "888", "999"]
    stems = sorted(w for w in wordlists.vocabulary() if 3 <= len(w) <= prefix_len + 3)
    out: list[str] = []
    for _ in range(count * 3):
        out.append(rng.choice(stems) + rng.choice(numbers))
    yield from itertools.islice(_clean(out), count)


def mutations(seeds: Iterable[str], max_len: int = MAX_LENGTH) -> Iterator[str]:
    """Near-misses around handles you already like: plurals, affixes, swaps."""
    prefixes, suffixes = wordlists.affixes()
    out: list[str] = []
    for raw in seeds:
        base = raw.strip().lower().lstrip("@")
        if not base:
            continue
        out += [base + "s", base + "z", base + "x", "the" + base, "my" + base, "go" + base]
        out += [base + s for s in suffixes]
        out += [p + base for p in prefixes]
        # single-character substitutions keep the shape but free the handle
        for i in range(len(base)):
            for c in LETTERS:
                if c != base[i]:
                    out.append(base[:i] + c + base[i + 1:])
    yield from _clean(u for u in out if len(u) <= max_len)


def from_file(path: str) -> Iterator[str]:
    """Read candidates from a text file, one per line (# comments allowed)."""
    with open(path, "r", encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh]
    yield from _clean(ln.lstrip("@") for ln in lines if ln and not ln.startswith("#"))


STRATEGIES = {
    "words": lambda **kw: words(),
    "combos": lambda **kw: combos(),
    "compounds": lambda **kw: compounds(),
    "patterns": lambda **kw: itertools.chain.from_iterable(
        patterns(n) for n in range(MIN_LENGTH, 8)
    ),
    "brandables": lambda **kw: itertools.chain(
        brandables(1500, 2, kw.get("seed")), brandables(1500, 3, kw.get("seed"))
    ),
    "numeric": lambda **kw: numeric(seed=kw.get("seed")),
}


def generate(strategy: str, **kwargs) -> Iterator[str]:
    """Yield unique, valid candidates for one strategy (or every strategy)."""
    if strategy == "all":
        stream = itertools.chain.from_iterable(f(**kwargs) for f in STRATEGIES.values())
    elif strategy in STRATEGIES:
        stream = STRATEGIES[strategy](**kwargs)
    else:
        raise KeyError(f"unknown strategy '{strategy}' (have: {', '.join(STRATEGIES)}, all)")
    # Strategies dedupe within themselves; chaining several (or one strategy
    # across several lengths) can still repeat, so filter once more here.
    return _clean(stream)
