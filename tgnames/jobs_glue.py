"""The long-running operations, driven from the UI instead of the CLI.

These wrap the same modules the command line uses; the only difference is that
progress is written into a Job the browser polls, and each loop checks whether
the user pressed Stop.
"""

from __future__ import annotations

from . import generator, storage
from .scoring import analyze
from .webcheck import (
    CalibrationError,
    FragmentChecker,
    FragmentStatus,
    TrustLost,
    WebAvailability,
    WebChecker,
)


def _log(job, level: str, text: str) -> None:
    job.lines.append({"level": level, "text": text})


def run_generate(app, body, job, should_stop) -> None:
    strategy = body.get("strategy") or "all"
    limit = int(body.get("limit") or 300)
    min_length = int(body.get("minLength") or 0)
    min_score = body.get("minScore")
    min_score = float(min_score) if min_score not in (None, "") else app.config.selection.min_score
    no_filter = bool(body.get("noFilter"))
    seeds = body.get("seeds") or []

    exclude = set() if no_filter else set(app.config.selection.exclude_tags)
    if seeds:
        raw = generator.mutations(seeds)
        source = "mutate"
    else:
        raw = generator.generate(strategy)
        source = strategy

    job.message = f"generating from {source}"
    kept, seen, scanned = [], set(), 0
    for username in raw:
        if should_stop():
            break
        scanned += 1
        if scanned % 5000 == 0:
            job.done = scanned
            job.message = f"scored {scanned:,} candidates, kept {len(kept)}"
        if username in seen or len(username) < min_length:
            continue
        seen.add(username)
        v = analyze(username)
        if not v.valid or v.score < min_score or (exclude & set(v.tags)):
            continue
        kept.append(v)
        if scanned > 400000:
            break

    kept.sort(key=lambda v: (-v.score, len(v.username)))
    kept = kept[:limit]
    with app.db() as db:
        before = sum(db.stats().values())
        db.upsert_many(kept, source=source)
        added = sum(db.stats().values()) - before
        db.log("generate", detail=f"{source}: kept={len(kept)} new={added}")

    job.total = job.done = scanned
    job.message = f"kept {len(kept)}, {added} new in the database"
    _log(job, "ok", job.message)
    for v in kept[:12]:
        _log(job, "info", f"{v.tier} {v.score:6.2f}  @{v.username}")


def run_rescore(app, _body, job, should_stop) -> None:
    with app.db() as db:
        rows = db.all_by_status(None, 1000000)
        job.total = len(rows)
        changed = 0
        fresh_all = []
        for i, row in enumerate(rows, 1):
            if should_stop():
                break
            fresh = analyze(row.username)
            if not fresh.valid:
                continue
            fresh_all.append(fresh)
            if abs(fresh.score - row.score) > 0.01 or sorted(fresh.tags) != sorted(row.tags):
                changed += 1
                added = sorted(set(fresh.tags) - set(row.tags))
                if changed <= 15:
                    note = f"  +{','.join(added)}" if added else ""
                    _log(job, "info",
                         f"@{row.username}: {row.score:.2f} -> {fresh.score:.2f}{note}")
            job.done = i
        db.upsert_many(fresh_all, source="rescore")
    job.message = f"re-scored {len(fresh_all)}, {changed} changed"
    _log(job, "ok", job.message)


def run_scan(app, body, job, should_stop) -> None:
    limit = int(body.get("limit") or 50)
    delay = float(body.get("delay") or 2.0)
    include_reserved = bool(body.get("includeReserved"))
    controls = [c for c in (body.get("controls") or []) if c]
    fragment_controls = [c for c in (body.get("fragmentControls") or []) if c]
    min_score = body.get("minScore")
    min_score = float(min_score) if min_score not in (None, "") else app.config.selection.min_score

    checker = WebChecker(delay=delay, extra_controls=tuple(controls))
    job.message = "calibrating against handles of known state"
    _log(job, "step", "Calibrating the t.me checker...")

    def sample(handle, expected, features):
        _log(job, "muted", f"  {expected:>10}  @{handle} — {len(features)} signal(s)")

    try:
        disc = checker.calibrate(on_sample=sample)
    except CalibrationError as exc:
        job.state = "failed"
        job.error = str(exc)
        _log(job, "error", str(exc))
        return
    except Exception as exc:
        job.state = "failed"
        job.error = f"could not reach t.me: {exc}"
        _log(job, "error", job.error)
        return
    _log(job, "ok", f"Calibrated on {disc.samples} pages.")

    fragment = None
    if fragment_controls:
        _log(job, "step", "Calibrating the Fragment cross-check...")
        fragment = FragmentChecker(delay=delay)
        try:
            fdisc = fragment.calibrate(fragment_controls, on_sample=sample)
            _log(job, "ok", f"Fragment calibrated: {len(fdisc.taken_evidence)} signal(s) "
                            f"mark a listing.")
        except Exception as exc:
            fragment = None
            _log(job, "warn", f"Fragment check unavailable: {exc}")
    else:
        _log(job, "warn", "No Fragment control given — handles on sale cannot be "
                          "told apart from free ones.")

    excluded = [t for t in app.config.selection.exclude_tags
                if not (include_reserved and t == "likely-reserved")]
    with app.db() as db:
        queue = db.queue(storage.STATUS_NEW, limit, min_score=min_score,
                         exclude_tags=tuple(excluded))
    if not queue:
        job.message = "queue is empty — generate first, or lower the minimum score"
        _log(job, "warn", job.message)
        return

    job.total = len(queue)
    job.message = f"checking {len(queue)} handles"
    tally: dict[str, int] = {}

    for i, cand in enumerate(queue, 1):
        if should_stop():
            _log(job, "warn", "stopped at your request")
            break
        try:
            result = checker.check(cand.username)
        except TrustLost as exc:
            job.state = "failed"
            job.error = str(exc)
            _log(job, "error", str(exc))
            break

        verdict = result.availability
        on_sale = (verdict is WebAvailability.FREE and fragment is not None
                   and fragment.check(cand.username) is FragmentStatus.LISTED)

        key = "purchasable" if on_sale else verdict.value
        tally[key] = tally.get(key, 0) + 1
        status = (storage.STATUS_PURCHASABLE if on_sale else {
            WebAvailability.FREE: storage.STATUS_UNCLAIMED,
            WebAvailability.TAKEN: storage.STATUS_TAKEN,
        }.get(verdict))

        with app.db() as db:
            if status:
                note = {
                    storage.STATUS_PURCHASABLE: "listed for sale on Fragment",
                    storage.STATUS_UNCLAIMED: "no owner visible",
                }.get(status, "owner visible")
                db.set_status(cand.username, status,
                              note=f"{result.detail}: {note}", checked=True)
            else:
                db.log("webcheck", cand.username, f"{verdict.value}: {result.detail}")

        reserved = "likely-reserved" in analyze(cand.username).tags
        _log(job, "row", json_row(cand, key, on_sale, reserved, result))
        job.done = i

    job.message = ", ".join(f"{k}={v}" for k, v in sorted(tally.items())) or "nothing checked"
    _log(job, "ok", f"Done: {job.message}")


def json_row(cand, key, on_sale, reserved, result) -> str:
    """One result line, as a compact string the page splits on '|'."""
    verdict = "purchasable" if on_sale else key
    if verdict == "available" and reserved:
        verdict = "reserved"
    return "|".join([
        cand.username, f"{cand.score:.1f}", cand.tier, verdict,
        (result.title or "")[:60],
    ])
