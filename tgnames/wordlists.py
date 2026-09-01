"""Loading and lookup of the bundled vocabulary files."""

from __future__ import annotations

import functools
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

# Which file feeds which category, and how strongly an exact hit is rewarded.
CATEGORY_FILES = {
    "premium": "words_premium.txt",
    "crypto": "words_crypto.txt",
    "tech": "words_tech.txt",
    "common": "words_common.txt",
    "name": "names.txt",
    "geo": "geo.txt",
}

# Exact-match weight per category, 0..100. Premium vocabulary is what actually
# gets resold, so it outranks a generic dictionary word.
CATEGORY_WEIGHT = {
    "premium": 100.0,
    "crypto": 94.0,
    "name": 90.0,
    "geo": 86.0,
    "tech": 84.0,
    "common": 80.0,
}


def _read_lines(filename: str) -> list[str]:
    path = DATA_DIR / filename
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().lower()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


@functools.lru_cache(maxsize=1)
def categories() -> dict[str, frozenset[str]]:
    """Map category name -> set of words."""
    return {name: frozenset(_read_lines(f)) for name, f in CATEGORY_FILES.items()}


@functools.lru_cache(maxsize=1)
def vocabulary() -> frozenset[str]:
    """Every known word, regardless of category."""
    words: set[str] = set()
    for group in categories().values():
        words |= group
    return frozenset(words)


@functools.lru_cache(maxsize=1)
def reserved() -> frozenset[str]:
    return frozenset(_read_lines("reserved.txt"))


@functools.lru_cache(maxsize=1)
def blocked_substrings() -> tuple[str, ...]:
    return tuple(_read_lines("blocklist_words.txt"))


@functools.lru_cache(maxsize=1)
def affixes() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (prefixes, suffixes) from affixes.txt."""
    prefixes, suffixes = [], []
    for line in _read_lines("affixes.txt"):
        kind, _, value = line.partition(":")
        if kind == "p" and value:
            prefixes.append(value)
        elif kind == "s" and value:
            suffixes.append(value)
    return tuple(prefixes), tuple(suffixes)


@functools.lru_cache(maxsize=4096)
def categories_of(word: str) -> tuple[str, ...]:
    """All categories a word belongs to, best-weighted first."""
    word = word.lower()
    hits = [name for name, group in categories().items() if word in group]
    hits.sort(key=lambda n: CATEGORY_WEIGHT.get(n, 0.0), reverse=True)
    return tuple(hits)


def is_word(token: str) -> bool:
    return token.lower() in vocabulary()


def best_category_weight(word: str) -> float:
    hits = categories_of(word)
    return CATEGORY_WEIGHT[hits[0]] if hits else 0.0
