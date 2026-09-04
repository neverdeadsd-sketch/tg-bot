"""Keyless availability probing through the public t.me pages.

This is a fallback for when api_id/api_hash cannot be obtained. It only ever
answers "is this handle occupied" — claiming needs the real API.

Correctness rule, learned the hard way: **a free verdict requires positive
proof, never the absence of evidence.** Occupied handles render in many
shapes (user with no avatar, bot, group, restricted channel), and a throttled
or degraded response carries no markers at all. Concluding "free" from missing
markers reports occupied handles as free, which is the one error that actually
costs something.

So the logic is inverted relative to the obvious approach:

* every *free* handle renders the same canonical empty page, so that page's
  exact feature set is learned as a signature. Matching it exactly -> FREE.
* anything carrying a signal that a free page provably never carries -> TAKEN.
* anything else -> UNKNOWN. Never a guess.

Calibration proves all of that at runtime against handles whose state is
certain, and is re-verified during a long scan so throttling kicking in
mid-run is caught rather than silently turning every answer into "free".

Standard library only, on purpose: this has to run where Telethon could not
be installed.
"""

from __future__ import annotations

import random
import re
import string
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
BASE_URL = "https://t.me/"

# Handles that are certainly occupied, chosen to span different page shapes
# (person, broadcast channel, bot). More diversity here means the calibration
# is proven against more of the variety it will meet.
CONTROL_TAKEN = ("durov", "telegram", "botfather")
CONTROL_FREE_COUNT = 3

# Signals looked for in a page. Which ones actually discriminate is decided by
# calibration, not by this list, so extra entries are harmless.
MARKERS = (
    "tgme_page_title",
    "tgme_page_extra",
    "tgme_page_photo",
    "tgme_page_description",
    "tgme_page_action",
    "tgme_page_context",
    "tgme_page_additional",
    "tgme_action_button",
    "tgme_header_link",
    "tgme_page",
    'property="og:title"',
    'property="og:description"',
    'property="og:image"',
    "tgme_icon_user",
    "tgme_icon_group",
    "tgme_icon_channel",
)

# A real t.me page is several kilobytes. Anything much smaller is an error or
# throttle page, never a verdict — checked before the signature comparison,
# because an empty page would otherwise match an empty free signature.
MIN_PLAUSIBLE_BYTES = 600

# Consecutive unusable answers that mean the run has stopped being trustworthy
# (almost always throttling) rather than meeting a few odd pages.
MAX_CONSECUTIVE_UNKNOWN = 4
# Re-prove the calibration every this many checks during a long scan.
RECHECK_EVERY = 25


class WebAvailability(str, Enum):
    FREE = "available"
    TAKEN = "taken"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass
class WebResult:
    username: str
    availability: WebAvailability
    detail: str = ""
    title: str = ""


class CalibrationError(RuntimeError):
    """The pages cannot be told apart — refuse to answer rather than guess."""


class TrustLost(RuntimeError):
    """Mid-run the responses stopped matching calibration; stop the scan."""


def random_handle(length: int = 20, rng: random.Random | None = None) -> str:
    """A handle long and random enough that it cannot plausibly be taken."""
    rng = rng or random.Random()
    return "".join(rng.choice(string.ascii_lowercase) for _ in range(length))


def size_bucket(html: str) -> str:
    """Coarse size class. Keeps a truncated page from matching a real one."""
    size = len(html)
    if size < MIN_PLAUSIBLE_BYTES:
        return "size:tiny"
    if size < 8000:
        return "size:small"
    if size < 40000:
        return "size:medium"
    return "size:large"


def extract_features(html: str) -> frozenset[str]:
    """Reduce a page to the boolean signals calibration reasons about."""
    low = html.lower()
    found = {f"has:{m}" for m in MARKERS if m.lower() in low}
    found.add(size_bucket(html))
    return frozenset(found)


def extract_title(html: str) -> str:
    match = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', html, re.I)
    return match.group(1).strip() if match else ""


@dataclass
class Discriminator:
    """What calibration proved about free and occupied pages."""

    # Exact feature set every free page produced. FREE requires matching it.
    free_signature: frozenset[str] | None = None
    # Signals seen on occupied pages and never on a free one.
    taken_evidence: frozenset[str] = frozenset()
    samples: int = 0

    def usable(self) -> bool:
        return self.free_signature is not None and bool(self.taken_evidence)

    def classify(self, features: frozenset[str]) -> WebAvailability:
        if not self.usable():
            return WebAvailability.UNKNOWN
        # Positive proof of occupancy wins: a page carrying a signal that free
        # pages never carry is occupied, whatever else it looks like.
        if features & self.taken_evidence:
            return WebAvailability.TAKEN
        # Free only on an exact match with the proven-canonical empty page.
        if features == self.free_signature:
            return WebAvailability.FREE
        # Neither — an unfamiliar page. Say so instead of picking a side.
        return WebAvailability.UNKNOWN

    def describe(self) -> str:
        if not self.usable():
            return "nothing separates the two groups"
        free = ", ".join(sorted(self.free_signature)) or "no signals at all"
        return (
            f"free pages look exactly like [{free}]; "
            f"{len(self.taken_evidence)} signal(s) prove occupancy"
        )


class WebChecker:
    def __init__(self, delay: float = 2.0, timeout: float = 15.0,
                 opener=None, rng: random.Random | None = None,
                 extra_controls: tuple[str, ...] = ()):
        self.delay = delay
        self.timeout = timeout
        self.rng = rng or random.Random()
        self._opener = opener or urllib.request.build_opener()
        self._last_request = 0.0
        self.discriminator = Discriminator()
        self.controls_taken = tuple(CONTROL_TAKEN) + tuple(extra_controls)
        self._checks_since_recheck = 0
        self._consecutive_unknown = 0

    # -- transport ----------------------------------------------------------
    def fetch(self, username: str) -> str:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        request = urllib.request.Request(
            BASE_URL + username, headers={"User-Agent": USER_AGENT}
        )
        with self._opener.open(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    # -- calibration --------------------------------------------------------
    def calibrate(self, on_sample=None) -> Discriminator:
        """Prove, against handles of known state, that verdicts are possible."""
        taken_features, free_features = [], []

        for handle in self.controls_taken:
            features = extract_features(self.fetch(handle))
            taken_features.append(features)
            if on_sample:
                on_sample(handle, "occupied", features)

        for _ in range(CONTROL_FREE_COUNT):
            handle = random_handle(rng=self.rng)
            features = extract_features(self.fetch(handle))
            free_features.append(features)
            if on_sample:
                on_sample(handle, "free", features)

        # 0. Nothing implausibly short can take part in calibration.
        if "size:tiny" in frozenset().union(*taken_features, *free_features):
            raise CalibrationError(
                "t.me returned implausibly short pages, which means throttling "
                "or a blocked connection rather than real content. Wait, or "
                "raise --delay."
            )

        # 1. Every free page must render identically, or there is no signature.
        signature = free_features[0]
        if any(f != signature for f in free_features):
            raise CalibrationError(
                "Handles that cannot exist returned pages that differ from each "
                "other, so there is no reliable 'free' page to compare against. "
                "This usually means t.me is throttling the requests — wait, or "
                "raise --delay."
            )

        # 2. Occupied pages must be distinguishable from that signature.
        identical = [
            handle for handle, f in zip(self.controls_taken, taken_features)
            if f == signature
        ]
        if identical:
            raise CalibrationError(
                f"Occupied handles ({', '.join('@' + h for h in identical)}) "
                f"render exactly like a free handle, so occupancy cannot be "
                f"detected. Refusing to guess — use the API (scan without --web)."
            )

        evidence = frozenset().union(*taken_features) - signature
        if not evidence:
            raise CalibrationError(
                "No signal appears on occupied pages that is absent from free "
                "ones. Telegram most likely changed the page markup. Refusing "
                "to guess — use the API (scan without --web)."
            )

        self.discriminator = Discriminator(
            free_signature=signature,
            taken_evidence=evidence,
            samples=len(taken_features) + len(free_features),
        )
        self._checks_since_recheck = 0
        self._consecutive_unknown = 0
        return self.discriminator

    def _reverify(self) -> None:
        """Confirm a known-free handle still matches the learned signature."""
        html = self.fetch(random_handle(rng=self.rng))
        if len(html) < MIN_PLAUSIBLE_BYTES or (
            extract_features(html) != self.discriminator.free_signature
        ):
            raise TrustLost(
                "A handle that cannot exist no longer renders like the one "
                "calibration learned — t.me has almost certainly started "
                "throttling. Stopping so that no unreliable verdict is stored. "
                "Wait a while and re-run, or raise --delay."
            )
        self._checks_since_recheck = 0

    # -- checking -----------------------------------------------------------
    def check(self, username: str) -> WebResult:
        if not self.discriminator.usable():
            raise CalibrationError("calibrate() must succeed before checking")

        if self._checks_since_recheck >= RECHECK_EVERY:
            self._reverify()

        try:
            html = self.fetch(username)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                result = WebResult(username, WebAvailability.FREE, "404 from t.me")
                self._consecutive_unknown = 0
                self._checks_since_recheck += 1
                return result
            if exc.code == 429:
                raise TrustLost(
                    "t.me answered 429 (too many requests). Stopping; wait a "
                    "while and re-run, or raise --delay."
                ) from exc
            return self._unusable(username, f"HTTP {exc.code}")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return self._unusable(username, str(exc))

        self._checks_since_recheck += 1
        if len(html) < MIN_PLAUSIBLE_BYTES:
            return self._unusable(
                username, f"implausibly short response ({len(html)} bytes)"
            )
        availability = self.discriminator.classify(extract_features(html))
        if availability is WebAvailability.UNKNOWN:
            return self._unusable(username, "page matches neither profile")

        self._consecutive_unknown = 0
        return WebResult(
            username, availability, detail="via t.me page", title=extract_title(html)
        )

    def _unusable(self, username: str, detail: str) -> WebResult:
        """Record a non-answer, and stop the run if they start piling up."""
        self._consecutive_unknown += 1
        if self._consecutive_unknown >= MAX_CONSECUTIVE_UNKNOWN:
            raise TrustLost(
                f"{self._consecutive_unknown} unusable responses in a row "
                f"({detail}). t.me is almost certainly throttling. Stopping so "
                f"that no unreliable verdict is stored — wait, or raise --delay."
            )
        return WebResult(username, WebAvailability.UNKNOWN, detail)


# ---------------------------------------------------------------------------
# Fragment cross-check
# ---------------------------------------------------------------------------
# t.me cannot distinguish "free" from "listed on the Fragment auction": both
# serve an ownerless page, and the client only reveals the difference as
# "Sorry, this link is taken. But it's available for purchase." Fragment
# publishes a page per username, so it can answer that question keylessly.
#
# The markup there is undocumented too, so the same rule applies: prove the
# classifier against handles of known state, refuse otherwise. The listed-side
# control cannot be guessed, so it has to be supplied by the caller — someone
# who has actually seen a handle offered for sale.

FRAGMENT_URL = "https://fragment.com/username/"


class FragmentStatus(str, Enum):
    LISTED = "purchasable"      # on sale — cannot simply be claimed
    NOT_LISTED = "not_listed"
    UNKNOWN = "unknown"


def class_tokens(html: str, cap: int = 400) -> frozenset[str]:
    """CSS class names used on a page.

    A site-agnostic feature space: rather than guessing which words matter on
    a page whose markup is undocumented, let calibration pick from whatever
    structure the page actually uses.
    """
    tokens: set[str] = set()
    for match in re.finditer(r'class="([^"]{1,300})"', html, re.I):
        for token in match.group(1).split():
            tokens.add(f"cls:{token.lower()}")
            if len(tokens) >= cap:
                return frozenset(tokens)
    return frozenset(tokens)


def page_features(html: str) -> frozenset[str]:
    """Generic features for a page whose markup is not known in advance."""
    return class_tokens(html) | {size_bucket(html)}


class FragmentChecker:
    """Answers 'is this handle being sold on Fragment', or refuses to."""

    def __init__(self, delay: float = 2.0, timeout: float = 15.0,
                 opener=None, rng: random.Random | None = None):
        self.delay = delay
        self.timeout = timeout
        self.rng = rng or random.Random()
        self._opener = opener or urllib.request.build_opener()
        self._last_request = 0.0
        self.discriminator = Discriminator()

    def fetch(self, username: str) -> str:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        request = urllib.request.Request(
            FRAGMENT_URL + username, headers={"User-Agent": USER_AGENT}
        )
        with self._opener.open(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def calibrate(self, listed_controls, on_sample=None) -> Discriminator:
        """Learn what a for-sale page looks like from handles known to be one."""
        if not listed_controls:
            raise CalibrationError(
                "The Fragment check needs at least one handle you have seen "
                "offered for sale, to prove it can recognise one. Pass it with "
                "--fragment-control (the client says 'available for purchase' "
                "on such a handle)."
            )

        listed, absent = [], []
        for handle in listed_controls:
            try:
                features = page_features(self.fetch(handle))
            except urllib.error.HTTPError as exc:
                raise CalibrationError(
                    f"Fragment returned HTTP {exc.code} for the control "
                    f"@{handle}. If that handle is not actually listed, pass "
                    f"one that is."
                ) from exc
            listed.append(features)
            if on_sample:
                on_sample(handle, "for sale", features)

        for _ in range(CONTROL_FREE_COUNT):
            handle = random_handle(rng=self.rng)
            try:
                features = page_features(self.fetch(handle))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    # A 404 for an unlisted handle is itself a clean signal.
                    features = frozenset({"http:404"})
                else:
                    raise CalibrationError(
                        f"Fragment returned HTTP {exc.code} while calibrating."
                    ) from exc
            absent.append(features)
            if on_sample:
                on_sample(handle, "not listed", features)

        signature = absent[0]
        if any(f != signature for f in absent):
            raise CalibrationError(
                "Fragment pages for handles that cannot exist differ from each "
                "other, so there is no reliable 'not listed' page to compare "
                "against. Skipping the Fragment check."
            )
        evidence = frozenset().union(*listed) - signature
        if not evidence:
            raise CalibrationError(
                "A handle known to be for sale looks the same on Fragment as "
                "one that cannot exist. Skipping the Fragment check rather "
                "than guessing."
            )

        self.discriminator = Discriminator(
            free_signature=signature, taken_evidence=evidence,
            samples=len(listed) + len(absent),
        )
        return self.discriminator

    def check(self, username: str) -> FragmentStatus:
        if not self.discriminator.usable():
            return FragmentStatus.UNKNOWN
        try:
            html = self.fetch(username)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                features = frozenset({"http:404"})
            else:
                return FragmentStatus.UNKNOWN
        except (urllib.error.URLError, OSError, TimeoutError):
            return FragmentStatus.UNKNOWN
        else:
            if len(html) < MIN_PLAUSIBLE_BYTES:
                return FragmentStatus.UNKNOWN
            features = page_features(html)

        verdict = self.discriminator.classify(features)
        return {
            WebAvailability.TAKEN: FragmentStatus.LISTED,
            WebAvailability.FREE: FragmentStatus.NOT_LISTED,
        }.get(verdict, FragmentStatus.UNKNOWN)
