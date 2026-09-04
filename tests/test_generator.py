import itertools

import pytest

from tgnames import generator
from tgnames.scoring import validate


ALL_STRATEGIES = list(generator.STRATEGIES)


@pytest.mark.parametrize("strategy", ALL_STRATEGIES)
def test_strategy_yields_only_valid_handles(strategy):
    items = list(itertools.islice(generator.generate(strategy, seed=7), 500))
    assert items, f"{strategy} produced nothing"
    for username in items:
        assert validate(username) is None, f"{strategy} produced invalid {username!r}"


@pytest.mark.parametrize("strategy", ALL_STRATEGIES)
def test_strategy_has_no_duplicates(strategy):
    items = list(itertools.islice(generator.generate(strategy, seed=7), 2000))
    assert len(items) == len(set(items))


def test_all_chains_every_strategy():
    combined = set(itertools.islice(generator.generate("all", seed=7), 200000))
    for strategy in ALL_STRATEGIES:
        sample = set(itertools.islice(generator.generate(strategy, seed=7), 20))
        assert sample & combined, f"{strategy} missing from 'all'"


def test_unknown_strategy_raises():
    with pytest.raises(KeyError):
        generator.generate("nope")


def test_patterns_contain_repeats_and_runs():
    items = set(generator.patterns(5))
    assert "aaaaa" in items
    assert "abcde" in items


def test_brandables_are_reproducible():
    a = list(generator.brandables(50, seed=42))
    b = list(generator.brandables(50, seed=42))
    assert a == b


def test_mutations_derive_from_seed():
    out = set(generator.mutations(["vault"]))
    assert "vaults" in out
    assert "thevault" in out
    assert all(validate(u) is None for u in out)


def test_mutations_ignore_blank_seeds():
    assert list(generator.mutations(["", "  "])) == []


def test_from_file_skips_comments(tmp_path):
    path = tmp_path / "seed.txt"
    path.write_text("# comment\n@money\n\nlunar\nzz\n", encoding="utf-8")
    assert list(generator.from_file(str(path))) == ["money", "lunar"]


def test_from_file_reads_stdin(monkeypatch):
    import io
    import sys
    monkeypatch.setattr(sys, "stdin", io.StringIO("money\n@lunar\n# skip\nzz\n"))
    assert list(generator.from_file("-")) == ["money", "lunar"]
