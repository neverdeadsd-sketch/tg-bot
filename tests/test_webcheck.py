"""Tests for the keyless t.me checker, with HTTP faked out.

The point of most of these is the refusal path. Reporting an occupied handle
as free is the one error that costs something, so every shape of occupied page
and every degraded response is checked for exactly that.
"""

import io
import random
import urllib.error

import pytest

from tgnames.webcheck import (
    CalibrationError,
    Discriminator,
    TrustLost,
    WebAvailability,
    WebChecker,
    extract_features,
    extract_title,
    random_handle,
)

# A rich occupied page: person with avatar, bio and subscriber count.
RICH_PAGE = (
    "<!-- padding -->" * 200 +
    '<html><head><meta property="og:title" content="Pavel Durov">'
    '<meta property="og:description" content="bio">'
    '<meta property="og:image" content="x.jpg"></head>'
    '<body><div class="tgme_page">'
    '<div class="tgme_page_title">Pavel Durov</div>'
    '<div class="tgme_page_extra">1 000 000 subscribers</div>'
    '<div class="tgme_page_photo">img</div>'
    '<div class="tgme_page_description">bio</div>'
    '<i class="tgme_icon_user"></i></div></body></html>'
)

# The shape that used to be misreported as free: occupied, but nothing like
# the controls — no avatar, no description, no subscriber count.
SPARSE_PAGE = (
    "<!-- padding -->" * 200 +
    '<html><head><meta property="og:title" content="anon"></head>'
    '<body><div class="tgme_page">'
    '<div class="tgme_page_title">anon</div></div></body></html>'
)

# What a handle that cannot exist renders as.
FREE_PAGE = (
    '<html><head><title>Telegram</title>'
    '<meta property="og:title" content="Telegram">'
    "</head><body>nothing here" + "<!-- padding -->" * 200 + "</body></html>"
)

# A throttled / degraded answer: carries no usable signal at all.
DEGRADED_PAGE = "<html><body>Too Many Requests</body></html>"
# An unfamiliar but full-sized page: neither profile matches it.
STRANGE_PAGE = (
    "<html><head><title>Something else</title></head><body>"
    + "<!-- other -->" * 300
    + "</body></html>"
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeOpener:
    """Serves canned pages and records what was requested."""

    def __init__(self, pages=None, default=FREE_PAGE):
        self.pages = dict(pages or {})
        self.default = default
        self.requested: list[str] = []

    def open(self, request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        handle = url.rsplit("/", 1)[-1]
        self.requested.append(handle)
        page = self.pages.get(handle, self.default)
        if isinstance(page, Exception):
            raise page
        return FakeResponse(page.encode("utf-8"))


CONTROLS = {"durov": RICH_PAGE, "telegram": RICH_PAGE, "botfather": SPARSE_PAGE}


def make_checker(pages=None, default=FREE_PAGE, seed=1, **kwargs):
    merged = dict(CONTROLS)
    merged.update(pages or {})
    opener = FakeOpener(merged, default)
    checker = WebChecker(delay=0.0, opener=opener, rng=random.Random(seed), **kwargs)
    return checker, opener


class TestFeatures:
    def test_occupied_pages_carry_more_signals(self):
        assert extract_features(RICH_PAGE) > extract_features(SPARSE_PAGE)
        assert extract_features(SPARSE_PAGE) - extract_features(FREE_PAGE)

    def test_title_is_extracted(self):
        assert extract_title(RICH_PAGE) == "Pavel Durov"
        assert extract_title(STRANGE_PAGE) == ""

    def test_random_handle_is_a_valid_telegram_username(self):
        from tgnames.scoring import validate
        for _ in range(20):
            assert validate(random_handle()) is None


class TestCalibration:
    def test_learns_a_free_signature_and_occupancy_evidence(self):
        checker, opener = make_checker()
        disc = checker.calibrate()
        assert disc.usable()
        assert disc.free_signature == extract_features(FREE_PAGE)
        assert "has:tgme_page_title" in disc.taken_evidence
        assert disc.samples == 6
        assert opener.requested[:3] == ["durov", "telegram", "botfather"]

    def test_refuses_when_free_pages_disagree(self):
        """Handles that cannot exist must all render the same, or no signature."""
        class Alternating(FakeOpener):
            def open(self, request, timeout=None):
                handle = request.full_url.rsplit("/", 1)[-1]
                if handle in CONTROLS:
                    return super().open(request, timeout)
                self.requested.append(handle)
                page = FREE_PAGE if len(self.requested) % 2 else STRANGE_PAGE
                return FakeResponse(page.encode("utf-8"))

        checker = WebChecker(
            delay=0.0, opener=Alternating(CONTROLS), rng=random.Random(1)
        )
        with pytest.raises(CalibrationError, match="differ from each other"):
            checker.calibrate()

    def test_refuses_when_an_occupied_control_looks_free(self):
        checker, _ = make_checker(pages={"botfather": FREE_PAGE})
        with pytest.raises(CalibrationError, match="botfather"):
            checker.calibrate()

    def test_refuses_when_nothing_proves_occupancy(self):
        checker, _ = make_checker(
            pages={k: FREE_PAGE for k in CONTROLS}, default=FREE_PAGE
        )
        with pytest.raises(CalibrationError):
            checker.calibrate()

    def test_check_before_calibration_is_refused(self):
        checker, _ = make_checker()
        with pytest.raises(CalibrationError, match="calibrate"):
            checker.check("money")

    def test_extra_controls_are_used(self):
        checker, opener = make_checker(
            pages={"mychannel": RICH_PAGE}, extra_controls=("mychannel",)
        )
        checker.calibrate()
        assert "mychannel" in opener.requested


class TestVerdicts:
    def test_rich_occupied_page(self):
        checker, _ = make_checker(pages={"money": RICH_PAGE})
        checker.calibrate()
        result = checker.check("money")
        assert result.availability is WebAvailability.TAKEN
        assert result.title == "Pavel Durov"

    def test_sparse_occupied_page_is_not_reported_free(self):
        """Regression: occupied handles unlike the controls read as free."""
        checker, _ = make_checker(pages={"money": SPARSE_PAGE})
        checker.calibrate()
        assert checker.check("money").availability is WebAvailability.TAKEN

    def test_free_handle(self):
        checker, _ = make_checker()
        checker.calibrate()
        assert checker.check("zqxwvyt").availability is WebAvailability.FREE

    def test_unfamiliar_page_is_unknown_not_free(self):
        """Regression: a page matching neither profile used to read as free."""
        checker, _ = make_checker(pages={"money": STRANGE_PAGE})
        checker.calibrate()
        assert checker.check("money").availability is WebAvailability.UNKNOWN

    def test_truncated_response_is_unknown_not_free(self):
        """Regression: a throttled short page used to match an empty signature."""
        checker, _ = make_checker(pages={"money": DEGRADED_PAGE})
        checker.calibrate()
        assert checker.check("money").availability is WebAvailability.UNKNOWN

    def test_http_404_reads_as_free(self):
        error = urllib.error.HTTPError("u", 404, "nf", {}, None)
        checker, _ = make_checker(pages={"gone": error})
        checker.calibrate()
        assert checker.check("gone").availability is WebAvailability.FREE

    def test_server_error_is_not_an_answer(self):
        error = urllib.error.HTTPError("u", 500, "err", {}, None)
        checker, _ = make_checker(pages={"oops": error})
        checker.calibrate()
        assert checker.check("oops").availability is WebAvailability.UNKNOWN

    def test_transport_failure_is_not_an_answer(self):
        checker, _ = make_checker(pages={"boom": urllib.error.URLError("no route")})
        checker.calibrate()
        assert checker.check("boom").availability is WebAvailability.UNKNOWN


class TestThrottlingDefences:
    def test_429_stops_the_run(self):
        error = urllib.error.HTTPError("u", 429, "slow down", {}, None)
        checker, _ = make_checker(pages={"money": error})
        checker.calibrate()
        with pytest.raises(TrustLost, match="429"):
            checker.check("money")

    def test_a_run_of_unusable_answers_stops_the_run(self):
        checker, _ = make_checker(pages=CONTROLS)
        checker.calibrate()
        checker._opener.default = DEGRADED_PAGE
        with pytest.raises(TrustLost, match="in a row"):
            for _ in range(10):
                checker.check("whatever")

    def test_a_good_answer_resets_the_streak(self):
        checker, _ = make_checker(pages={"bad": STRANGE_PAGE, "good": RICH_PAGE})
        checker.calibrate()
        for _ in range(6):
            assert checker.check("bad").availability is WebAvailability.UNKNOWN
            assert checker.check("good").availability is WebAvailability.TAKEN

    def test_calibration_is_reverified_during_a_long_run(self, monkeypatch):
        import tgnames.webcheck as webcheck
        monkeypatch.setattr(webcheck, "RECHECK_EVERY", 3)
        checker, opener = make_checker(pages={"money": RICH_PAGE})
        checker.calibrate()
        before = len(opener.requested)
        for _ in range(4):
            checker.check("money")
        # One extra fetch beyond the four checks: the re-verification probe.
        assert len(opener.requested) == before + 5

    def test_drift_during_a_run_stops_it(self, monkeypatch):
        import tgnames.webcheck as webcheck
        monkeypatch.setattr(webcheck, "RECHECK_EVERY", 2)
        checker, opener = make_checker(pages={"money": RICH_PAGE})
        checker.calibrate()
        checker.check("money")
        checker.check("money")
        opener.default = DEGRADED_PAGE      # free pages stop looking free
        with pytest.raises(TrustLost, match="throttling"):
            checker.check("money")


class TestDiscriminator:
    def test_occupancy_evidence_wins(self):
        disc = Discriminator(
            free_signature=frozenset(), taken_evidence=frozenset({"has:x"})
        )
        assert disc.classify(frozenset({"has:x"})) is WebAvailability.TAKEN

    def test_free_needs_an_exact_match(self):
        disc = Discriminator(
            free_signature=frozenset({"has:a"}), taken_evidence=frozenset({"has:x"})
        )
        assert disc.classify(frozenset({"has:a"})) is WebAvailability.FREE
        assert disc.classify(frozenset({"has:a", "has:b"})) is WebAvailability.UNKNOWN
        assert disc.classify(frozenset()) is WebAvailability.UNKNOWN

    def test_unusable_discriminator_never_answers(self):
        assert not Discriminator().usable()
        assert Discriminator().classify(frozenset()) is WebAvailability.UNKNOWN


# --- Fragment cross-check ---------------------------------------------------
# Pages modelled on what the client reveals: a handle can be ownerless on t.me
# and still be "taken, but available for purchase".

FRAGMENT_LISTED = (
    '<html><body><div class="tm-section">'
    '<div class="table-cell-status-avail">For sale</div>'
    '<div class="table-cell-value">1000 TON</div>'
    "</div>" + "<!-- pad -->" * 200 + "</body></html>"
)
FRAGMENT_ABSENT = (
    '<html><body><div class="tm-section">'
    '<div class="tm-empty">Nothing found</div>'
    "</div>" + "<!-- pad -->" * 200 + "</body></html>"
)


def make_fragment(pages=None, default=FRAGMENT_ABSENT, seed=1):
    from tgnames.webcheck import FragmentChecker
    opener = FakeOpener(pages or {}, default)
    return FragmentChecker(delay=0.0, opener=opener, rng=random.Random(seed)), opener


class TestFragmentChecker:
    def test_learns_what_a_listing_looks_like(self):
        from tgnames.webcheck import FragmentStatus
        checker, _ = make_fragment({"alalal": FRAGMENT_LISTED})
        disc = checker.calibrate(["alalal"])
        assert disc.usable()
        assert "cls:table-cell-status-avail" in disc.taken_evidence

    def test_detects_a_handle_on_sale(self):
        from tgnames.webcheck import FragmentStatus
        checker, _ = make_fragment({"alalal": FRAGMENT_LISTED,
                                    "pools": FRAGMENT_LISTED})
        checker.calibrate(["alalal"])
        assert checker.check("pools") is FragmentStatus.LISTED

    def test_unlisted_handle(self):
        from tgnames.webcheck import FragmentStatus
        checker, _ = make_fragment({"alalal": FRAGMENT_LISTED})
        checker.calibrate(["alalal"])
        assert checker.check("vaultpay") is FragmentStatus.NOT_LISTED

    def test_refuses_without_a_control(self):
        checker, _ = make_fragment()
        with pytest.raises(CalibrationError, match="at least one handle"):
            checker.calibrate([])

    def test_refuses_when_the_control_looks_unlisted(self):
        checker, _ = make_fragment({"alalal": FRAGMENT_ABSENT})
        with pytest.raises(CalibrationError, match="looks the same"):
            checker.calibrate(["alalal"])

    def test_404_for_the_control_is_explained(self):
        error = urllib.error.HTTPError("u", 404, "nf", {}, None)
        checker, _ = make_fragment({"alalal": error})
        with pytest.raises(CalibrationError, match="not actually listed"):
            checker.calibrate(["alalal"])

    def test_404_is_a_clean_not_listed_signal(self):
        from tgnames.webcheck import FragmentStatus
        error = urllib.error.HTTPError("u", 404, "nf", {}, None)
        checker, _ = make_fragment({"alalal": FRAGMENT_LISTED}, default=error)
        checker.calibrate(["alalal"])
        assert checker.check("whatever") is FragmentStatus.NOT_LISTED

    def test_uncalibrated_checker_answers_unknown(self):
        from tgnames.webcheck import FragmentStatus
        checker, _ = make_fragment()
        assert checker.check("pools") is FragmentStatus.UNKNOWN

    def test_transport_failure_is_unknown(self):
        from tgnames.webcheck import FragmentStatus
        checker, opener = make_fragment({"alalal": FRAGMENT_LISTED})
        checker.calibrate(["alalal"])
        opener.pages["boom"] = urllib.error.URLError("no route")
        assert checker.check("boom") is FragmentStatus.UNKNOWN


class TestClassTokens:
    def test_extracts_class_names(self):
        from tgnames.webcheck import class_tokens
        assert class_tokens('<a class="one two">x</a>') == {"cls:one", "cls:two"}

    def test_is_capped(self):
        from tgnames.webcheck import class_tokens
        html = "".join(f'<i class="c{i}"></i>' for i in range(1000))
        assert len(class_tokens(html, cap=50)) <= 50

    def test_empty_page_has_no_tokens(self):
        from tgnames.webcheck import class_tokens
        assert class_tokens("<html><body>plain</body></html>") == frozenset()
