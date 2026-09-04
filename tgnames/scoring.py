"""Offline valuation of a Telegram username.

The score is a weighted blend of five independent signals, each normalised to
0..100 before mixing:

    length      how short the handle is          (dominant factor on the market)
    charset     letters only vs digits/underscores
    lexical     is it a real word, or two words glued together
    pattern     repetitions, runs, palindromes, repdigits
    phonetic    can a human pronounce and dictate it

Modifiers are then applied multiplicatively (reserved trademarks, risky
substrings, bot-like suffixes) and the result is clamped to 0..100.

Nothing here touches the network — this module is pure and fully testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from . import wordlists

# ---------------------------------------------------------------------------
# Telegram's own constraints on public usernames.
# ---------------------------------------------------------------------------
MIN_LENGTH = 5
MAX_LENGTH = 32
USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{3,30}[a-z0-9]$")

VOWELS = frozenset("aeiou")
KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890")

# Blend weights — must sum to 1.0.
WEIGHTS = {
    "length": 0.36,
    "charset": 0.14,
    "lexical": 0.22,
    "pattern": 0.18,
    "phonetic": 0.10,
}

TIERS = (
    (88.0, "S"),   # museum pieces: 5 letters, dictionary word, repdigits
    (74.0, "A"),   # strong, resellable
    (60.0, "B"),   # good, worth holding
    (45.0, "C"),   # decent
    (30.0, "D"),   # marginal
    (0.0, "F"),    # not worth a channel slot
)

# Very rough resale bands. These are heuristics for sorting a queue, not a
# market quote — real prices depend on demand for the exact word.
VALUE_BANDS = (
    (88.0, "$$$$", "1000+"),
    (74.0, "$$$", "250-1000"),
    (60.0, "$$", "50-250"),
    (45.0, "$", "10-50"),
    (0.0, "-", "<10"),
)


@dataclass
class Valuation:
    """Result of analysing a single username."""

    username: str
    valid: bool
    score: float = 0.0
    tier: str = "F"
    value_band: str = "-"
    value_hint: str = "<10"
    components: dict[str, float] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        if not self.valid:
            return f"@{self.username}  INVALID  ({self.error})"
        tags = (" [" + ",".join(self.tags) + "]") if self.tags else ""
        return f"@{self.username}  {self.score:5.1f}  tier {self.tier}  {self.value_band}{tags}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def normalize(username: str) -> str:
    """Strip decoration a user may paste in: @name, t.me/name, full URLs."""
    u = username.strip().lower()
    for prefix in ("https://", "http://", "tg://resolve?domain=", "t.me/", "telegram.me/", "@"):
        if u.startswith(prefix):
            u = u[len(prefix):]
    u = u.split("?", 1)[0].split("/", 1)[0]
    return u.strip()


def validate(username: str) -> str | None:
    """Return an error string, or None when the handle is registrable."""
    if not username:
        return "empty"
    if len(username) < MIN_LENGTH:
        return f"too short (min {MIN_LENGTH})"
    if len(username) > MAX_LENGTH:
        return f"too long (max {MAX_LENGTH})"
    if not USERNAME_RE.match(username):
        return "must be a-z0-9_, start with a letter, end with a letter or digit"
    if "__" in username:
        return "double underscore"
    return None


# ---------------------------------------------------------------------------
# Individual signals
# ---------------------------------------------------------------------------
def length_score(n: int) -> float:
    """Shortness is the single strongest price driver on the market."""
    table = {5: 100.0, 6: 88.0, 7: 74.0, 8: 61.0, 9: 50.0,
             10: 41.0, 11: 33.0, 12: 27.0, 13: 22.0, 14: 18.0}
    if n <= 5:
        return 100.0
    if n in table:
        return table[n]
    return max(3.0, 18.0 - (n - 14) * 1.4)


def charset_score(u: str) -> tuple[float, list[str]]:
    """Pure letters are premium; digits cost, underscores cost a lot."""
    reasons: list[str] = []
    digits = sum(c.isdigit() for c in u)
    unders = u.count("_")
    score = 100.0
    if digits:
        score -= 22.0 + 7.0 * min(digits - 1, 4)
        reasons.append(f"contains {digits} digit(s)")
    if unders:
        score -= 42.0 + 12.0 * (unders - 1)
        reasons.append(f"contains {unders} underscore(s)")
    if not digits and not unders:
        reasons.append("letters only")
    return max(0.0, score), reasons


def split_words(u: str, max_parts: int = 3, min_part: int = 3) -> list[str] | None:
    """Greedy-longest-first split of a handle into known vocabulary words."""
    body = u.strip("_")
    if not body:
        return None

    def rec(rest: str, depth: int) -> list[str] | None:
        if not rest:
            return []
        if depth == 0:
            return None
        for size in range(len(rest), min_part - 1, -1):
            head = rest[:size]
            if wordlists.is_word(head):
                tail = rec(rest[size:], depth - 1)
                if tail is not None:
                    return [head] + tail
        return None

    return rec(body, max_parts)


def lexical_score(u: str) -> tuple[float, list[str], list[str]]:
    """Does the handle mean something? Exact words beat compounds beat noise."""
    tags: list[str] = []
    reasons: list[str] = []
    body = u.strip("_")

    cats = wordlists.categories_of(body)
    if cats:
        tags.extend(cats)
        reasons.append(f"exact dictionary word ({'/'.join(cats)})")
        return wordlists.best_category_weight(body), tags, reasons

    parts = split_words(body)
    if parts and len(parts) >= 2:
        weights = [wordlists.best_category_weight(p) for p in parts]
        base = sum(weights) / len(weights)
        # Two clean words read much better than three glued fragments.
        penalty = {2: 0.82, 3: 0.62}.get(len(parts), 0.5)
        for p in parts:
            tags.extend(wordlists.categories_of(p))
        reasons.append("compound of " + "+".join(parts))
        return base * penalty, sorted(set(tags)), reasons

    # A recognisable word plus junk (numbers, an affix) still carries meaning.
    stripped = u.strip("_0123456789")
    if stripped and stripped != body and wordlists.is_word(stripped):
        tags.extend(wordlists.categories_of(stripped))
        reasons.append(f"word '{stripped}' with decoration")
        return wordlists.best_category_weight(stripped) * 0.55, sorted(set(tags)), reasons

    # Longest embedded word, as a weak signal.
    best = ""
    for size in range(len(body), 3, -1):
        for start in range(0, len(body) - size + 1):
            chunk = body[start:start + size]
            if wordlists.is_word(chunk):
                best = chunk
                break
        if best:
            break
    if best and len(best) >= 4:
        reasons.append(f"contains '{best}'")
        return min(38.0, 8.0 * len(best)), tags, reasons
    return 0.0, tags, reasons


def _is_monotone_run(s: str) -> bool:
    """abcde / edcba / 12345 / 54321"""
    if len(s) < 4:
        return False
    deltas = {ord(b) - ord(a) for a, b in zip(s, s[1:])}
    return deltas in ({1}, {-1})


def _keyboard_run(s: str) -> bool:
    if len(s) < 4:
        return False
    for row in KEYBOARD_ROWS:
        if s in row or s in row[::-1]:
            return True
    return False


def _min_period(s: str) -> int:
    """Shortest repeating unit length; equals len(s) when non-repeating."""
    n = len(s)
    for p in range(1, n // 2 + 1):
        if n % p == 0 and s[:p] * (n // p) == s:
            return p
    return n


def pattern_score(u: str) -> tuple[float, list[str], list[str]]:
    """Structural beauty: repeats, runs, symmetry, repdigits."""
    tags: list[str] = []
    reasons: list[str] = []
    body = u.strip("_")
    best = 0.0

    if len(set(body)) == 1:
        tags.append("repeat")
        reasons.append("single repeated character")
        return 100.0, tags, reasons

    period = _min_period(body)
    if period < len(body):
        tags.append("repeat")
        reasons.append(f"repeats the block '{body[:period]}'")
        best = max(best, 96.0 - 4.0 * period)

    if _is_monotone_run(body):
        tags.append("run")
        reasons.append("alphabetic/numeric run")
        best = max(best, 92.0)

    if _keyboard_run(body):
        tags.append("keyboard")
        reasons.append("keyboard row run")
        best = max(best, 88.0)

    if len(body) >= 5 and body == body[::-1]:
        tags.append("palindrome")
        reasons.append("palindrome")
        best = max(best, 84.0)

    # Repdigit / repeated-letter tail, e.g. crypto777 or gold999.
    tail = re.search(r"(\d)\1{2,}$", body)
    if tail:
        tags.append("repdigit")
        reasons.append(f"repdigit tail '{tail.group(0)}'")
        best = max(best, 68.0)

    # A year tail is common but adds little value.
    year = re.search(r"(19[5-9]\d|20[0-4]\d)$", body)
    if year and not tail:
        tags.append("year")
        reasons.append(f"year tail '{year.group(0)}'")
        best = max(best, 24.0)

    # Doubled letters read well in brands (buzzz, coool).
    if not best and re.search(r"(.)\1\1", body):
        reasons.append("triple letter")
        best = max(best, 46.0)

    if not best:
        # Baseline: reward low character noise for handles with no structure.
        unique_ratio = len(set(body)) / max(1, len(body))
        best = 20.0 * (1.0 - abs(unique_ratio - 0.75))
    return min(100.0, best), tags, reasons


def phonetic_score(u: str) -> tuple[float, list[str]]:
    """How easily the handle survives being read aloud over the phone."""
    reasons: list[str] = []
    letters = [c for c in u if c.isalpha()]
    if not letters:
        return 0.0, ["no letters"]
    body = "".join(letters)

    vowels = sum(c in VOWELS for c in body)
    ratio = vowels / len(body)
    # Ideal vowel share for a pronounceable word is roughly 30-50%.
    ratio_score = max(0.0, 100.0 - abs(ratio - 0.40) * 260.0)

    longest_cons = max((len(m) for m in re.findall(r"[^aeiou]+", body)), default=0)
    longest_vow = max((len(m) for m in re.findall(r"[aeiou]+", body)), default=0)
    cluster_penalty = max(0, longest_cons - 2) * 16.0 + max(0, longest_vow - 2) * 12.0
    if longest_cons >= 4:
        reasons.append(f"{longest_cons} consonants in a row")

    # Alternating consonant/vowel is the most dictatable shape.
    alternations = sum(1 for a, b in zip(body, body[1:]) if (a in VOWELS) != (b in VOWELS))
    alt_score = 100.0 * alternations / max(1, len(body) - 1)

    score = max(0.0, 0.55 * ratio_score + 0.45 * alt_score - cluster_penalty)
    if score >= 70:
        reasons.append("easy to pronounce")
    return min(100.0, score), reasons


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def _tier_for(score: float) -> str:
    for threshold, tier in TIERS:
        if score >= threshold:
            return tier
    return "F"


def _band_for(score: float) -> tuple[str, str]:
    for threshold, band, hint in VALUE_BANDS:
        if score >= threshold:
            return band, hint
    return "-", "<10"


def analyze(username: str) -> Valuation:
    """Score a single username. Never raises."""
    u = normalize(username)
    err = validate(u)
    if err:
        return Valuation(username=u or username.strip(), valid=False, error=err)

    tags: list[str] = []
    reasons: list[str] = []

    s_len = length_score(len(u))
    s_charset, r_charset = charset_score(u)
    s_lex, t_lex, r_lex = lexical_score(u)
    s_pat, t_pat, r_pat = pattern_score(u)
    s_phon, r_phon = phonetic_score(u)

    reasons += [f"length {len(u)}"] + r_charset + r_lex + r_pat + r_phon
    tags += t_lex + t_pat

    lex_raw = s_lex

    # A structurally perfect handle does not need to be a word — let a strong
    # pattern stand in for the lexical and phonetic signals it cannot have.
    if s_pat >= 85.0:
        s_lex = max(s_lex, s_pat * 0.90)
        s_phon = max(s_phon, s_pat * 0.80)

    components = {
        "length": s_len,
        "charset": s_charset,
        "lexical": s_lex,
        "pattern": s_pat,
        "phonetic": s_phon,
    }
    score = sum(components[k] * w for k, w in WEIGHTS.items())

    # ---- multiplicative modifiers -----------------------------------------
    body = u.strip("_")
    if s_lex < 15.0 and s_pat < 45.0 and s_phon < 45.0:
        score *= 0.78
        tags.append("noise")
        reasons.append("no meaning, no structure, hard to pronounce")

    if body in wordlists.reserved():
        score *= 0.25
        tags.append("reserved")
        reasons.append("reserved/trademark word — registration will likely be revoked")
    elif any(part in wordlists.reserved() for part in split_words(body) or []):
        score *= 0.6
        tags.append("reserved-part")
        reasons.append("contains a reserved/trademark word")

    hit = next((w for w in wordlists.blocked_substrings() if w in body), None)
    if hit:
        score *= 0.2
        tags.append("risky")
        reasons.append(f"contains blocked substring '{hit}'")

    if body.endswith("bot"):
        score *= 0.7
        tags.append("bot-like")
        reasons.append("'bot' suffix is read as a bot account")

    if u[0].isalpha() and u[1:].isdigit():
        score *= 1.05
        tags.append("letter-number")

    # Telegram holds back short and meaningful handles and sells them through
    # the Fragment auction rather than handing them out. They have no owner, so
    # every page-based check reports them as free while the client rejects them
    # with "This link is invalid". The five-character space in particular is
    # exhausted: a scan of twenty such handles found none that could be taken.
    # This is a prior about a class of handles, not a fact about any specific
    # one, so it is a tag the user can weigh — never a verdict.
    if len(u) == MIN_LENGTH or (len(u) <= 6 and u.isalpha() and lex_raw >= 80):
        tags.append("likely-reserved")
        reasons.append(
            "short dictionary word — Telegram usually reserves these for the "
            "Fragment auction, so 'free' page checks are misleading"
        )

    # A short pure-letter word deserves an extra nudge: that is the shape that
    # actually sells on the secondary market.
    if len(u) <= 6 and u.isalpha() and lex_raw >= 80:
        score = min(100.0, score * 1.08)
        tags.append("prime")

    score = max(0.0, min(100.0, score))
    band, hint = _band_for(score)
    return Valuation(
        username=u,
        valid=True,
        score=round(score, 2),
        tier=_tier_for(score),
        value_band=band,
        value_hint=hint,
        components={k: round(v, 2) for k, v in components.items()},
        tags=sorted(set(tags)),
        reasons=reasons,
    )


def analyze_many(usernames) -> list[Valuation]:
    return sorted(
        (analyze(u) for u in usernames),
        key=lambda v: (v.valid, v.score),
        reverse=True,
    )
