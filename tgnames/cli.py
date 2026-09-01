"""Command line interface."""

from __future__ import annotations

import argparse
import asyncio
import csv
import itertools
import json
import logging
import sys

from . import generator, storage
from .config import load as load_config
from .scoring import analyze, analyze_many
from .storage import (
    STATUS_AVAILABLE,
    STATUS_CLAIMED,
    STATUS_NEW,
    Storage,
)

log = logging.getLogger("tgnames")

TIER_ORDER = "SABCDF"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)


def _read_inputs(values: list[str], file: str | None) -> list[str]:
    items = list(values)
    if file:
        if file == "-":
            items += [ln.strip() for ln in sys.stdin]
        else:
            items += list(generator.from_file(file))
    return [i for i in items if i]


def _print_table(rows: list[tuple], headers: tuple[str, ...]) -> None:
    if not rows:
        print("(nothing to show)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))


def _open_db(args) -> Storage:
    cfg = load_config(args.config)
    return Storage(args.db or cfg.db)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_analyze(args) -> int:
    """Score usernames offline — no Telegram account needed."""
    names = _read_inputs(args.username, args.file)
    if not names:
        print("nothing to analyze; pass usernames or --file", file=sys.stderr)
        return 2

    results = analyze_many(names)
    if args.json:
        print(json.dumps([v.as_dict() for v in results], indent=2, ensure_ascii=False))
        return 0

    if args.explain:
        for v in results:
            print(f"\n@{v.username}")
            if not v.valid:
                print(f"  INVALID: {v.error}")
                continue
            print(f"  score {v.score:.2f}  tier {v.tier}  band {v.value_band} "
                  f"(rough resale ${v.value_hint})")
            print("  components: " + ", ".join(f"{k}={val:.0f}" for k, val in v.components.items()))
            if v.tags:
                print("  tags: " + ", ".join(v.tags))
            for reason in v.reasons:
                print(f"    - {reason}")
        return 0

    rows = [
        (v.username, f"{v.score:.1f}" if v.valid else "-", v.tier if v.valid else "-",
         v.value_band, ",".join(v.tags) or "-", v.error or "")
        for v in results
        if args.all or v.valid
    ]
    _print_table(rows, ("username", "score", "tier", "band", "tags", "note"))
    return 0


def cmd_generate(args) -> int:
    """Generate candidates, score them, keep the good ones."""
    cfg = load_config(args.config)
    min_score = args.min_score if args.min_score is not None else cfg.selection.min_score
    exclude = set(cfg.selection.exclude_tags) if not args.no_filter else set()

    if args.file:
        raw = generator.from_file(args.file)
        source = f"file:{args.file}"
    elif args.mutate:
        raw = generator.mutations(args.mutate)
        source = "mutate"
    else:
        raw = generator.generate(args.strategy, seed=args.seed)
        source = args.strategy

    kept, seen, scanned = [], set(), 0
    for username in raw:
        scanned += 1
        if username in seen:
            continue
        seen.add(username)
        v = analyze(username)
        if not v.valid or v.score < min_score:
            continue
        if exclude & set(v.tags):
            continue
        kept.append(v)
        if scanned >= args.max_scan:
            break

    # Rank the whole pool before truncating, otherwise --limit would just take
    # whatever the strategy happened to emit first (alphabetical, for words).
    kept.sort(key=lambda v: (-v.score, len(v.username)))
    if args.limit:
        kept = kept[: args.limit]
    with _open_db(args) as db:
        before = sum(db.stats().values())
        db.upsert_many(kept, source=source)
        after = sum(db.stats().values())
        db.log("generate", detail=f"{source}: scanned={scanned} kept={len(kept)} new={after-before}")

    print(f"strategy={source}  scanned={scanned}  kept={len(kept)}  new in db={after - before}")
    for v in kept[:args.show]:
        print(f"  {v.tier} {v.score:6.2f}  @{v.username}  {','.join(v.tags) or '-'}")
    return 0


def cmd_scan(args) -> int:
    """Check queued candidates against Telegram."""
    from .client import StopRun, UsernameHunter
    from .ratelimit import QuotaExceeded

    cfg = load_config(args.config)
    min_score = args.min_score if args.min_score is not None else cfg.selection.min_score

    async def run() -> int:
        with _open_db(args) as db:
            queue = db.queue(
                STATUS_NEW, args.limit, min_score=min_score,
                exclude_tags=tuple(cfg.selection.exclude_tags),
            )
            if not queue:
                print("queue is empty — run `generate` first, or lower --min-score")
                return 0
            print(f"checking {len(queue)} candidates "
                  f"(score >= {min_score}, ~{cfg.limits.checks_per_minute:.0f}/min)")

            def report(cand, result):
                mark = {"available": "FREE", "taken": "taken", "purchasable": "fragment",
                        "invalid": "invalid", "error": "error"}[result.availability.value]
                print(f"  [{mark:>8}] @{cand.username}  ({cand.score:.1f} {cand.tier})")

            hunter = UsernameHunter(cfg, db)
            try:
                async with hunter:
                    tally = await hunter.scan(queue, on_result=report)
            except (StopRun, QuotaExceeded) as exc:
                print(f"\nstopped: {exc}", file=sys.stderr)
                return 1
            print("\nresult: " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
            free = db.queue(STATUS_AVAILABLE, 20, min_score=min_score)
            if free:
                print("\ntop free right now:")
                for c in free:
                    print(f"  {c.tier} {c.score:6.2f}  @{c.username}")
        return 0

    return asyncio.run(run())


def cmd_claim(args) -> int:
    """Claim free usernames by creating a channel for each one."""
    from .client import StopRun, UsernameHunter
    from .ratelimit import QuotaExceeded

    cfg = load_config(args.config)
    min_score = args.min_score if args.min_score is not None else cfg.selection.min_score
    dry_run = not args.execute

    async def run() -> int:
        with _open_db(args) as db:
            if args.username:
                queue = []
                for raw in args.username:
                    v = analyze(raw)
                    if not v.valid:
                        print(f"  skipping @{v.username}: {v.error}")
                        continue
                    queue.append(db.get(v.username) or storage.Candidate(
                        username=v.username, score=v.score, tier=v.tier,
                        value_band=v.value_band, tags=v.tags, source="cli",
                        status=STATUS_AVAILABLE))
            else:
                queue = db.queue(
                    STATUS_AVAILABLE, args.limit, min_score=min_score,
                    exclude_tags=tuple(cfg.selection.exclude_tags),
                )
            if not queue:
                print("nothing available to claim — run `scan` first")
                return 0

            hunter = UsernameHunter(cfg, db)
            left_h, left_d = hunter.claim_quota.remaining()
            print(f"{'DRY RUN' if dry_run else 'LIVE'}: {len(queue)} candidate(s); "
                  f"quota left {left_h}/hour, {left_d}/day")
            for c in queue:
                print(f"  {c.tier} {c.score:6.2f}  @{c.username}")

            if dry_run:
                print("\nNothing was created. Re-run with --execute to actually claim.")
                print("Each claim creates a PUBLIC channel on your account and is "
                      "counted against Telegram's public-link limit.")
                return 0

            if not args.yes:
                print(f"\nThis will create {len(queue)} public channel(s) on your account.")
                if input("Type 'yes' to continue: ").strip().lower() != "yes":
                    print("aborted")
                    return 1

            def report(cand, result):
                state = "OK" if result.ok else "--"
                print(f"  [{state}] @{cand.username}: {result.detail}")

            try:
                async with hunter:
                    tally = await hunter.claim_batch(queue, dry_run=False, on_result=report)
            except (StopRun, QuotaExceeded) as exc:
                print(f"\nstopped: {exc}", file=sys.stderr)
                return 1
            print("\nresult: " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
        return 0

    return asyncio.run(run())


def cmd_hunt(args) -> int:
    """generate -> scan -> claim in one pass."""
    import copy

    rc = cmd_generate(args)
    if rc:
        return rc
    print()
    rc = cmd_scan(args)
    if rc:
        return rc
    print()
    # Claiming is far more expensive than scanning, so it gets its own budget.
    claim_args = copy.copy(args)
    claim_args.limit = args.claim_limit
    return cmd_claim(claim_args)


def cmd_list(args) -> int:
    with _open_db(args) as db:
        items = db.all_by_status(args.status, args.limit)
        rows = [
            (c.username, f"{c.score:.1f}", c.tier, c.value_band, c.status,
             c.source, ",".join(c.tags) or "-", c.note or "")
            for c in items
        ]
        _print_table(rows, ("username", "score", "tier", "band", "status", "source", "tags", "note"))
    return 0


def cmd_stats(args) -> int:
    with _open_db(args) as db:
        stats = db.stats()
        total = sum(stats.values())
        print(f"candidates: {total}")
        for status, count in sorted(stats.items(), key=lambda kv: -kv[1]):
            print(f"  {status:<13} {count}")
        cfg = load_config(args.config)
        from .ratelimit import Quota
        for name, per_h, per_d in (
            ("check", cfg.limits.checks_per_hour, cfg.limits.checks_per_day),
            ("claim", cfg.limits.claims_per_hour, cfg.limits.claims_per_day),
        ):
            left_h, left_d = Quota(db, name, per_h, per_d).remaining()
            print(f"quota {name}: {left_h}/{per_h} left this hour, {left_d}/{per_d} left today")
        events = db.recent_events(args.events)
        if events:
            print("\nrecent events:")
            for e in events:
                print(f"  {e['kind']:<13} {e['username'] or '':<20} {e['detail']}")
    return 0


def cmd_export(args) -> int:
    with _open_db(args) as db:
        items = db.all_by_status(args.status, args.limit)
    if args.format == "json":
        payload = [
            {"username": c.username, "score": c.score, "tier": c.tier, "band": c.value_band,
             "status": c.status, "tags": c.tags, "source": c.source, "note": c.note,
             "channel_id": c.channel_id}
            for c in items
        ]
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.out:
            open(args.out, "w", encoding="utf-8").write(text)
            print(f"wrote {len(items)} rows to {args.out}")
        else:
            print(text)
        return 0

    handle = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    writer = csv.writer(handle)
    writer.writerow(["username", "score", "tier", "band", "status", "tags", "source", "note"])
    for c in items:
        writer.writerow([c.username, f"{c.score:.2f}", c.tier, c.value_band, c.status,
                         "|".join(c.tags), c.source, c.note or ""])
    if args.out:
        handle.close()
        print(f"wrote {len(items)} rows to {args.out}")
    return 0


def cmd_login(args) -> int:
    """Interactive first login — creates the Telethon session file."""
    from .client import UsernameHunter

    cfg = load_config(args.config)

    async def run() -> int:
        with _open_db(args) as db:
            hunter = UsernameHunter(cfg, db)
            async with hunter:
                me = await hunter.client.get_me()
                print(f"signed in as @{me.username or me.id} ({me.first_name})")
                print(f"session stored at {cfg.telegram.session}.session")
        return 0

    return asyncio.run(run())


def cmd_inventory(args) -> int:
    """List public channels this account owns, i.e. the handles already held."""
    from .client import UsernameHunter

    cfg = load_config(args.config)

    async def run() -> int:
        with _open_db(args) as db:
            hunter = UsernameHunter(cfg, db)
            async with hunter:
                owned = await hunter.owned_public_channels()
            rows = [(u, str(cid), title) for cid, u, title in owned]
            _print_table(rows, ("username", "channel_id", "title"))
            print(f"\n{len(owned)} public channel(s) owned. Telegram allows 10 public "
                  f"links on a regular account (more with Premium).")
        return 0

    return asyncio.run(run())


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tgnames",
        description="Analyse valuable Telegram usernames and hold them via channels.",
    )
    p.add_argument("-c", "--config", help="path to config.toml")
    p.add_argument("--db", help="override the SQLite path")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="score usernames offline")
    a.add_argument("username", nargs="*")
    a.add_argument("-f", "--file", help="read usernames from a file ('-' for stdin)")
    a.add_argument("--explain", action="store_true", help="show the score breakdown")
    a.add_argument("--json", action="store_true")
    a.add_argument("--all", action="store_true", help="include invalid handles")
    a.set_defaults(func=cmd_analyze)

    g = sub.add_parser("generate", help="generate and score candidates into the db")
    g.add_argument("-s", "--strategy", default="all",
                   choices=list(generator.STRATEGIES) + ["all"])
    g.add_argument("-f", "--file", help="load candidates from a file instead")
    g.add_argument("--mutate", nargs="+", help="derive variants of these handles")
    g.add_argument("-n", "--limit", type=int, default=500, help="how many to keep")
    g.add_argument("--max-scan", type=int, default=400000, help="candidate cap per run")
    g.add_argument("--min-score", type=float)
    g.add_argument("--no-filter", action="store_true", help="ignore exclude_tags")
    g.add_argument("--show", type=int, default=15, help="how many to print")
    g.add_argument("--seed", type=int)
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("scan", help="check availability against Telegram")
    s.add_argument("-n", "--limit", type=int, default=50)
    s.add_argument("--min-score", type=float)
    s.set_defaults(func=cmd_scan)

    c = sub.add_parser("claim", help="hold free usernames by creating channels")
    c.add_argument("username", nargs="*", help="claim these specific handles")
    c.add_argument("-n", "--limit", type=int, default=3)
    c.add_argument("--min-score", type=float)
    c.add_argument("--execute", action="store_true",
                   help="actually create channels (default is a dry run)")
    c.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    c.set_defaults(func=cmd_claim)

    h = sub.add_parser("hunt", help="generate + scan + claim in one pass")
    h.add_argument("-s", "--strategy", default="all",
                   choices=list(generator.STRATEGIES) + ["all"])
    h.add_argument("-f", "--file")
    h.add_argument("--mutate", nargs="+")
    h.add_argument("-n", "--limit", type=int, default=50)
    h.add_argument("--max-scan", type=int, default=400000)
    h.add_argument("--min-score", type=float)
    h.add_argument("--no-filter", action="store_true")
    h.add_argument("--show", type=int, default=10)
    h.add_argument("--seed", type=int)
    h.add_argument("--claim-limit", type=int, default=3,
                   help="how many handles to actually claim in this pass")
    h.add_argument("--execute", action="store_true")
    h.add_argument("-y", "--yes", action="store_true")
    h.set_defaults(func=cmd_hunt, username=[])

    li = sub.add_parser("list", help="show stored candidates")
    li.add_argument("--status", choices=[
        storage.STATUS_NEW, storage.STATUS_AVAILABLE, storage.STATUS_TAKEN,
        storage.STATUS_PURCHASABLE, storage.STATUS_INVALID, storage.STATUS_CLAIMED,
        storage.STATUS_FAILED, storage.STATUS_SKIPPED])
    li.add_argument("-n", "--limit", type=int, default=50)
    li.set_defaults(func=cmd_list)

    st = sub.add_parser("stats", help="database and quota summary")
    st.add_argument("--events", type=int, default=10)
    st.set_defaults(func=cmd_stats)

    e = sub.add_parser("export", help="dump candidates as csv/json")
    e.add_argument("--status")
    e.add_argument("--format", choices=("csv", "json"), default="csv")
    e.add_argument("-n", "--limit", type=int, default=5000)
    e.add_argument("-o", "--out")
    e.set_defaults(func=cmd_export)

    lg = sub.add_parser("login", help="sign in and create the session file")
    lg.set_defaults(func=cmd_login)

    inv = sub.add_parser("inventory", help="list public channels this account owns")
    inv.set_defaults(func=cmd_inventory)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
