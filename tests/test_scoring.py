import pytest

from tgnames.scoring import analyze, length_score, normalize, split_words, validate


class TestValidation:
    @pytest.mark.parametrize("raw,expected", [
        ("@money", "money"),
        ("t.me/money", "money"),
        ("https://t.me/money", "money"),
        ("telegram.me/money", "money"),
        ("tg://resolve?domain=money", "money"),
        ("  MONEY  ", "money"),
        ("t.me/money?start=1", "money"),
    ])
    def test_normalize(self, raw, expected):
        assert normalize(raw) == expected

    @pytest.mark.parametrize("username", ["money", "abc12", "a_b_c_d", "x" * 32])
    def test_accepts_valid(self, username):
        assert validate(username) is None

    @pytest.mark.parametrize("username,fragment", [
        ("", "empty"),
        ("abcd", "too short"),
        ("a" * 33, "too long"),
        ("1money", "must be"),          # cannot start with a digit
        ("money_", "must be"),          # cannot end with an underscore
        ("mon ey", "must be"),
        ("mon-ey", "must be"),
        ("mon__ey", "double underscore"),
    ])
    def test_rejects_invalid(self, username, fragment):
        err = validate(username)
        assert err is not None and fragment in err


class TestLengthScore:
    def test_monotonically_decreasing(self):
        scores = [length_score(n) for n in range(5, 33)]
        assert scores == sorted(scores, reverse=True)

    def test_five_is_maximal(self):
        assert length_score(5) == 100.0
        assert length_score(4) == 100.0   # clamped; validation rejects it anyway

    def test_long_handles_stay_positive(self):
        assert 0 < length_score(32) < 10


class TestSplitWords:
    def test_splits_compound(self):
        assert split_words("goldbank") == ["gold", "bank"]

    def test_single_word_is_one_part(self):
        assert split_words("money") == ["money"]

    def test_returns_none_for_noise(self):
        assert split_words("xkcdqz") is None


class TestAnalyze:
    def test_invalid_scores_zero(self):
        v = analyze("zz")
        assert not v.valid and v.score == 0.0 and v.error

    def test_dictionary_word_beats_noise(self):
        assert analyze("money").score > analyze("mqnzy").score

    def test_short_beats_long(self):
        assert analyze("token").score > analyze("tokenmarket").score

    def test_letters_beat_underscores(self):
        assert analyze("goldbank").score > analyze("gold_bank").score

    def test_letters_beat_digits(self):
        assert analyze("goldbank").score > analyze("goldbank12").score

    @pytest.mark.parametrize("username", ["aaaaa", "abcde", "ababab"])
    def test_patterns_reach_top_tier(self, username):
        v = analyze(username)
        assert v.tier in ("S", "A"), f"{username} -> {v.tier} ({v.score})"

    def test_reserved_word_is_penalised(self):
        v = analyze("telegram")
        assert "reserved" in v.tags
        assert v.score < analyze("teleport").score

    def test_risky_substring_is_penalised(self):
        assert "risky" in analyze("pornhub").tags

    def test_noise_is_tagged(self):
        assert "noise" in analyze("xkcdqz").tags

    def test_bot_suffix_is_discounted(self):
        assert analyze("goldbot").score < analyze("goldbox").score

    def test_score_is_bounded(self):
        for u in ["aaaaa", "money", "x" * 32, "a_b_c_1", "zzzzzzzzzzzzzzzz"]:
            v = analyze(u)
            assert 0.0 <= v.score <= 100.0

    def test_components_are_reported(self):
        v = analyze("money")
        assert set(v.components) == {"length", "charset", "lexical", "pattern", "phonetic"}
        assert v.reasons

    def test_accepts_decorated_input(self):
        assert analyze("https://t.me/money").username == "money"

    def test_is_deterministic(self):
        assert analyze("goldbank").score == analyze("goldbank").score
