"""Keyless availability probing through the public t.me pages.

This is a fallback for when api_id/api_hash cannot be obtained. It only ever
answers the question "is this handle occupied", never claims anything —
creating a channel is impossible without the real API.

The catch is that Telegram does not document the markup of these pages and can
change it at any time, so the classifier is not hard-coded. It is *learned* at
runtime: the checker fetches a few handles whose state is known for certain
(occupied ones like @durov, plus long random strings that cannot exist), works
out which HTML signals actually separate the two groups, and refuses to
classify anything at all if no signal separates them. A wrong answer is worse
than no answer, so "unknown" is a first-class result.

Standard library only, on purpose: this has to run on a machine where Telethon
could not be installed.
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

# Handles that are certainly occupied. Used only as calibration controls.
CONTROL_TAKEN = ("durov", "telegram")
# How many impossible-to-exist handles to use as the free-side controls.
CONTROL_FREE_COUNT = 3

# Signals looked for in the page. Which of them actually discriminate is
# decided by calibration, not by this list — extra entries cost nothing.
MARKERS = (
    "tgme_page_title",
    "tgme_page_extra",
    "tgme_page_photo",
    "tgme_page_description",
    "tgme_page_action",
    "tgme_page_context",
    "tgme_head",
    'property="og:title"',
    'property="og:description"',
    'property="og:image"',
    "tgme_action_button",
    "tgme_page_additional",
)


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
    """Raised when the t.me pages cannot be told apart — do not guess."""


def random_handle(length: int = 20, rng: random.Random | None = None) -> str:
    """A handle long and random enough that it cannot plausibly be taken."""
    rng = rng or random.Random()
    body = "".join(rng.choice(string.ascii_lowercase) for _ in range(length - 1))
    return rng.choice(string.ascii_lowercase) + body


def extract_features(html: str) -> frozenset[str]:
    """Reduce a page to the boolean signals calibration can reason about."""
    low = html.lower()
    found = {f"has:{m}" for m in MARKERS if m.lower() in low}
    # Size is a coarse but often decisive signal.
    found.add("size:large" if len(html) > 6000 else "size:small")
    return frozenset(found)


def extract_title(html: str) -> str:
    match = re.search(
        r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', html, re.I
    )
    return match.group(1).strip() if match else ""


@dataclass
class Discriminator:
    """The signals that were found to actually separate taken from free."""

    taken_only: frozenset[str] = frozenset()
    free_only: frozenset[str] = frozenset()
    samples: int = 0

    def usable(self) -> bool:
        return bool(self.taken_only or self.free_only)

    def classify(self, features: frozenset[str]) -> WebAvailability:
        if self.taken_only and self.taken_only & features:
            return WebAvailability.TAKEN
        if self.free_only and self.free_only & features:
            return WebAvailability.FREE
        # Only one side was learned: absence of its markers implies the other.
        if self.taken_only and not self.free_only:
            return WebAvailability.FREE
        if self.free_only and not self.taken_only:
            return WebAvailability.TAKEN
        return WebAvailability.UNKNOWN

    def describe(self) -> str:
        parts = []
        if self.taken_only:
            parts.append("occupied pages carry " + ", ".join(sorted(self.taken_only)))
        if self.free_only:
            parts.append("free pages carry " + ", ".join(sorted(self.free_only)))
        return "; ".join(parts) or "nothing separates the two groups"


class WebChecker:
    def __init__(self, delay: float = 1.5, timeout: float = 15.0,
                 opener=None, rng: random.Random | None = None):
        self.delay = delay
        self.timeout = timeout
        self.rng = rng or random.Random()
        self._opener = opener or urllib.request.build_opener()
        self._last_request = 0.0
        self.discriminator = Discriminator()

    # -- transport ----------------------------------------------------------
    def fetch(self, username: str) -> str:
        """GET the public page for a handle. Raises urllib errors."""
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
        """Learn the discriminator from handles whose state is already known."""
        taken_features, free_features = [], []

        for handle in CONTROL_TAKEN:
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

        common_taken = frozenset.intersection(*taken_features)
        common_free = frozenset.intersection(*free_features)
        any_taken = frozenset.union(*taken_features)
        any_free = frozenset.union(*free_features)

        self.discriminator = Discriminator(
            taken_only=common_taken - any_free,
            free_only=common_free - any_taken,
            samples=len(taken_features) + len(free_features),
        )
        if not self.discriminator.usable():
            raise CalibrationError(
                "The occupied and free t.me pages look identical to this "
                "checker, so it cannot tell them apart. Telegram most likely "
                "changed the page markup. Refusing to guess — use the API "
                "(scan without --web) instead."
            )
        return self.discriminator

    # -- checking -----------------------------------------------------------
    def check(self, username: str) -> WebResult:
        if not self.discriminator.usable():
            raise CalibrationError("calibrate() must succeed before checking")
        try:
            html = self.fetch(username)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return WebResult(username, WebAvailability.FREE, "404 from t.me")
            return WebResult(username, WebAvailability.ERROR, f"HTTP {exc.code}")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return WebResult(username, WebAvailability.ERROR, str(exc))

        availability = self.discriminator.classify(extract_features(html))
        return WebResult(
            username, availability,
            detail="via t.me page", title=extract_title(html),
        )
