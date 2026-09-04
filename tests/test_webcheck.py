"""Tests for the keyless t.me checker, with HTTP faked out.

The point of these is the refusal path: the checker must never answer when it
cannot prove it can tell an occupied handle from a free one.
"""

import io
import random
import urllib.error

import pytest

from tgnames.webcheck import (
    CalibrationError,
    Discriminator,
    WebAvailability,
    WebChecker,
    extract_features,
    extract_title,
    random_handle,
)

TAKEN_PAGE = (
    '<html><head><meta property="og:title" content="Pavel Durov">'
    '<meta property="og:image" content="x.jpg"></head>'
    '<body><div class="tgme_page_title">Pavel Durov</div>'
    '<div class="tgme_page_extra">1 000 000 subscribers</div>'
    '<div class="tgme_page_photo">img</div>' + "padding" * 2000 + "</body></html>"
)
FREE_PAGE = "<html><head><title>Telegram</title></head><body>nothing here</body></html>"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeOpener:
    """Serves canned pages and records what was requested."""

    def __init__(self, pages: dict[str, str], default: str = FREE_PAGE):
        self.pages = pages
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


def make_checker(pages=None, default=FREE_PAGE, seed=1):
    opener = FakeOpener(pages or {"durov": TAKEN_PAGE, "telegram": TAKEN_PAGE}, default)
    checker = WebChecker(delay=0.0, opener=opener, rng=random.Random(seed))
    return checker, opener


class TestFeatures:
    def test_taken_page_yields_more_signals(self):
        assert len(extract_features(TAKEN_PAGE)) > len(extract_features(FREE_PAGE))

    def test_title_is_extracted(self):
        assert extract_title(TAKEN_PAGE) == "Pavel Durov"
        assert extract_title(FREE_PAGE) == ""

    def test_random_handle_is_a_valid_length(self):
        from tgnames.scoring import validate
        for _ in range(20):
            assert validate(random_handle()) is None


class TestCalibration:
    def test_learns_a_discriminator(self):
        checker, opener = make_checker()
        disc = checker.calibrate()
        assert disc.usable()
        assert "has:tgme_page_title" in disc.taken_only
        assert disc.samples == 5
        assert opener.requested[:2] == ["durov", "telegram"]

    def test_refuses_when_pages_are_identical(self):
        # Every page looks the same -> nothing can be concluded.
        checker, _ = make_checker(pages={"durov": FREE_PAGE, "telegram": FREE_PAGE})
        with pytest.raises(CalibrationError, match="cannot tell them apart"):
            checker.calibrate()

    def test_refuses_when_free_pages_look_occupied(self):
        checker, _ = make_checker(default=TAKEN_PAGE)
        with pytest.raises(CalibrationError):
            checker.calibrate()

    def test_check_before_calibration_is_refused(self):
        checker, _ = make_checker()
        with pytest.raises(CalibrationError, match="calibrate"):
            checker.check("money")

    def test_describe_is_human_readable(self):
        checker, _ = make_checker()
        assert "occupied pages carry" in checker.calibrate().describe()


class TestChecking:
    def test_occupied_handle(self):
        checker, _ = make_checker(pages={
            "durov": TAKEN_PAGE, "telegram": TAKEN_PAGE, "money": TAKEN_PAGE,
        })
        checker.calibrate()
        result = checker.check("money")
        assert result.availability is WebAvailability.TAKEN
        assert result.title == "Pavel Durov"

    def test_free_handle(self):
        checker, _ = make_checker()
        checker.calibrate()
        assert checker.check("zqxwvyt").availability is WebAvailability.FREE

    def test_http_404_reads_as_free(self):
        error = urllib.error.HTTPError("u", 404, "nf", {}, None)
        checker, _ = make_checker(pages={
            "durov": TAKEN_PAGE, "telegram": TAKEN_PAGE, "gone": error,
        })
        checker.calibrate()
        assert checker.check("gone").availability is WebAvailability.FREE

    def test_transport_failure_is_not_an_answer(self):
        checker, _ = make_checker(pages={
            "durov": TAKEN_PAGE, "telegram": TAKEN_PAGE,
            "boom": urllib.error.URLError("no route"),
        })
        checker.calibrate()
        result = checker.check("boom")
        assert result.availability is WebAvailability.ERROR

    def test_server_error_is_not_an_answer(self):
        error = urllib.error.HTTPError("u", 500, "err", {}, None)
        checker, _ = make_checker(pages={
            "durov": TAKEN_PAGE, "telegram": TAKEN_PAGE, "oops": error,
        })
        checker.calibrate()
        assert checker.check("oops").availability is WebAvailability.ERROR


class TestDiscriminator:
    def test_unknown_when_nothing_matches(self):
        disc = Discriminator(taken_only=frozenset({"a"}), free_only=frozenset({"b"}))
        assert disc.classify(frozenset({"a"})) is WebAvailability.TAKEN
        assert disc.classify(frozenset({"b"})) is WebAvailability.FREE
        assert disc.classify(frozenset({"c"})) is WebAvailability.UNKNOWN

    def test_one_sided_discriminator_infers_the_other_side(self):
        disc = Discriminator(taken_only=frozenset({"a"}))
        assert disc.classify(frozenset({"a"})) is WebAvailability.TAKEN
        assert disc.classify(frozenset({"z"})) is WebAvailability.FREE

    def test_empty_discriminator_is_unusable(self):
        assert not Discriminator().usable()
