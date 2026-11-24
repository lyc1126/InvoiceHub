"""ENG-09 capacity governance tests for generations, ParseCache, and server source cache."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from invoice_hub.storage import generations
from invoice_hub.storage.parse_cache import ParseCache, prune_damaged_caches
from invoice_hub.storage.source_adapters import SourceError
from invoice_hub.storage.source_cache import (
    cache_path,
    cache_usage,
    evict_objects,
    obtain,
    prune_summary_generations,
)


def _publish_dummy_generation(workspace: Path, source: Path, body: str, *, expected: str = "") -> dict:
    with generations.candidate(workspace) as stage:
        for name in generations.SUMMARY + generations.COST[:2]:
            (stage / name).write_text(body, encoding="utf-8")
        return generations.publish(workspace, source, stage, expected=expected)


def test_generations_auto_prune_keeps_bounded_count_and_preserves_protected_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "source"
    workspace.mkdir()
    source.mkdir()
    invoice = source / "inv.pdf"
    invoice.write_bytes(b"%PDF-1.4")
    manual_status = source / "成本开票状态.json"
    manual_status.write_text('{"items":{"k":{"invoiced_quantity":"3"}}}', encoding="utf-8")

    expected = ""
    published_ids = []
    for idx in range(10):
        res = _publish_dummy_generation(workspace, source, f"gen-{idx}-" + ("x" * 128), expected=expected)
        expected = res["generation"]
        published_ids.append(expected)

    usage = generations.generation_usage(workspace)
    assert usage["generation_count"] <= generations.DEFAULT_MAX_GENERATIONS
    assert usage["current_generation"] == published_ids[-1]
    assert generations.resolve(workspace, source, "发票汇总.csv").read_text(encoding="utf-8").startswith("gen-9-")
    # Source invoice, manual JSON, and export receipt must remain intact.
    assert invoice.read_bytes() == b"%PDF-1.4"
    assert json.loads(manual_status.read_text(encoding="utf-8"))["items"]["k"]["invoiced_quantity"] == "3"
    assert (workspace / "projection-export-receipt.json").is_file()


def test_generations_prune_respects_pinned_reader_receipt_and_resumes_interrupted_cleanup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "source"
    workspace.mkdir()
    source.mkdir()

    g1 = _publish_dummy_generation(workspace, source, "a" * 2048)["generation"]
    g2 = _publish_dummy_generation(workspace, source, "b" * 2048, expected=g1)["generation"]
    g3 = _publish_dummy_generation(workspace, source, "c" * 2048, expected=g2)["generation"]

    # Simulate an interrupted prune tombstone and stale vs fresh candidate staging dirs.
    gen_root = workspace / "projection-generations"
    tombstone = gen_root / ".pruning-deadbeef"
    tombstone.mkdir()
    (tombstone / "leftover.csv").write_text("stale", encoding="utf-8")

    stale_cand = gen_root / ".candidate-old"
    stale_cand.mkdir()
    old_ts = time.time() - 7200
    os.utime(stale_cand, (old_ts, old_ts))

    fresh_cand = gen_root / ".candidate-fresh"
    fresh_cand.mkdir()

    # Pin g1 as an active reader and prune aggressively to 1 generation / 1 byte.
    with generations.pin_generation(workspace, g1):
        report = generations.prune_generations(workspace, keep_generations=1, max_bytes=1)
        assert report["removed_staging"] == 2
        assert (gen_root / g1).is_dir()  # pinned reader protected
        assert (gen_root / g3).is_dir()  # current manifest protected
        assert not (gen_root / g2).exists()  # unprotected middle generation reclaimed
        assert not tombstone.exists()
        assert not stale_cand.exists()
        assert fresh_cand.is_dir()  # fresh in-flight candidate untouched

    # After reader unpins g1, pruning reclaims it cleanly.
    report_after = generations.prune_generations(workspace, keep_generations=1, max_bytes=1)
    assert report_after["removed_generations"] == 1
    assert not (gen_root / g1).exists()
    assert (gen_root / g3).is_dir()


def test_generations_prune_skips_when_manifest_is_corrupt(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = tmp_path / "source"
    workspace.mkdir()
    source.mkdir()
    g1 = _publish_dummy_generation(workspace, source, "one")["generation"]
    g2 = _publish_dummy_generation(workspace, source, "two", expected=g1)["generation"]
    (workspace / "projection-manifest.json").write_text("{corrupt", encoding="utf-8")

    report = generations.prune_generations(workspace, keep_generations=1, max_bytes=1)
    assert report.get("skipped") == "corrupt_manifest"
    assert (workspace / "projection-generations" / g1).is_dir()
    assert (workspace / "projection-generations" / g2).is_dir()


def test_parse_cache_upgrades_legacy_schema_and_prunes_orphans_versions_lru_and_damaged(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db_path = workspace / "parse-cache.sqlite3"
    # Seed a legacy 6-column raw table (without last_used) to verify seamless upgrade.
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE raw (key TEXT PRIMARY KEY, signature TEXT, digest TEXT, version TEXT, payload TEXT, verified REAL)")
    con.commit()
    con.close()

    # Create 5 quarantined damaged files; pruning should keep only 2 newest.
    for idx in range(5):
        dmg = workspace / f"parse-cache.damaged-{idx:02d}"
        dmg.write_bytes(b"corrupt")
        ts = time.time() - (50 - idx)
        os.utime(dmg, (ts, ts))

    files = []
    for idx in range(4):
        f = tmp_path / f"inv_{idx}.pdf"
        f.write_bytes(f"pdf-{idx}".encode())
        files.append(f)

    with ParseCache(workspace) as cache:
        for f in files:
            cache.read("invoice", f, "v2", lambda name=f.name: {"file": name})
            cache.read("cost", f, "cost-v2-" + "a" * 64, lambda name=f.name: {"cost": name})
        # Also insert an obsolete version row for an active file.
        cache.read("invoice", files[0], "v1-old", lambda: {"old": True})
        # Force a separate key with an obsolete version on an active file.
        cache._save(json.dumps(["cost", str(files[1].absolute())]), [0, 0, 0, 0, 0], "d", "cost-v1-oldhash", {"old": 1}, time.time() - 500, time.time() - 500)

        # Keep only files[0..2] as active (files[3] was deleted), keep v2 / cost-v2-* versions.
        active = {str(f.absolute()) for f in files[:3]}
        res = cache.prune(active_paths=active, version_prefixes={"invoice": "v2", "cost": "cost-v2-"}, max_rows=100)
        assert res["deleted_orphans"] == 2  # invoice + cost for files[3]
        assert res["deleted_versions"] == 2  # v1-old for files[0] + cost-v1-oldhash for files[1]
        assert res["removed_damaged"] == 3
        assert len(list(workspace.glob("parse-cache.damaged-*"))) == 2
        surviving = {row[0] for row in cache.db.execute("SELECT key FROM raw").fetchall()}
        assert json.dumps(["invoice", str(files[2].absolute())]) in surviving
        assert json.dumps(["cost", str(files[2].absolute())]) in surviving

    # Stress-test LRU row bound: insert 120 entries, bound to max_rows=30.
    with ParseCache(workspace) as cache:
        now = time.time()
        for idx in range(120):
            cache._save(
                json.dumps(["invoice", f"/virtual/{idx}.pdf"]),
                [1, idx, 10, 1, 1],
                f"{idx:064x}",
                "v2",
                {"n": idx},
                now - (200 - idx),
                now - (200 - idx),
            )
        bounded = cache.prune(max_rows=30)
        assert bounded["remaining_rows"] <= 30
        assert bounded["deleted_lru"] > 0
        # Most recently used entries survive; oldest were evicted.
        keys = {row[0] for row in cache.db.execute("SELECT key FROM raw").fetchall()}
        assert json.dumps(["invoice", "/virtual/119.pdf"]) in keys
        assert json.dumps(["invoice", "/virtual/0.pdf"]) not in keys
    assert prune_damaged_caches(workspace, keep=2) == 0


class _FakeAdapter:
    def __init__(self, payloads: dict[str, bytes]):
        self.payloads = payloads
        self.copies = 0

    def copy(self, entry, destination: Path, _report):
        self.copies += 1
        destination.write_bytes(self.payloads[entry["id"]])


def test_source_cache_lru_eviction_pins_active_leases_and_bounds_budget(tmp_path: Path) -> None:
    root = tmp_path / "source-cache"
    root.mkdir()
    # 12 files of 1,000 bytes each with a 4,500-byte budget -> at most 4 files fit at once.
    payloads = {f"e{i:02d}": (bytes([65 + (i % 26)]) * 1000) for i in range(12)}
    adapter = _FakeAdapter(payloads)
    cached_map: dict[str, dict] = {}

    # Seed first file and pin it as if an active preview lease holds it.
    e0 = {"id": "e00", "name": "inv00.pdf", "size": 1000, "version": "v1"}
    _p0, info0, fresh0 = obtain(adapter, root, e0, None, lambda _m: None, budget=4500, cached_map=cached_map)
    assert fresh0
    cached_map["e00"] = info0
    pinned = {info0["object"]}

    # Download 11 more files sequentially under the tight 4,500-byte budget.
    for idx in range(1, 12):
        eid = f"e{idx:02d}"
        entry = {"id": eid, "name": f"inv{idx:02d}.pdf", "size": 1000, "version": "v1"}
        _path, info, fresh = obtain(
            adapter, root, entry, cached_map.get(eid), lambda _m: None,
            budget=4500, cached_map=cached_map, pinned_objects=pinned,
        )
        assert fresh
        cached_map[eid] = info
        usage = cache_usage(root)
        assert usage["objects_bytes"] <= 4500

    # Pinned e00 must survive all 11 subsequent downloads; unpinned early entries were evicted.
    assert "e00" in cached_map
    assert cache_path(root, cached_map["e00"]).is_file()
    assert "e01" not in cached_map
    assert "e11" in cached_map

    # If every byte of the budget is pinned, requesting a new file fails closed with cache_full.
    all_pinned = {info["object"] for info in cached_map.values()}
    with pytest.raises(SourceError) as exc_info:
        obtain(
            adapter, root, {"id": "extra", "name": "extra.pdf", "size": 2000, "version": "v1"},
            None, lambda _m: None, budget=4500, cached_map=cached_map, pinned_objects=all_pinned,
        )
    assert exc_info.value.code == "cache_full"


def test_source_cache_evicts_orphans_crash_leftovers_and_superseded_summary_generations(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    orphan = root / "objects" / ("a" * 64) / "orphan.pdf"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan-bytes")

    stale_part = root / "dead.part"
    stale_part.write_bytes(b"partial")
    old_ts = time.time() - 7200
    os.utime(stale_part, (old_ts, old_ts))

    tombstone = root / ".pruning-old"
    tombstone.mkdir()
    (tombstone / "x").write_text("1", encoding="utf-8")

    result = evict_objects(root, {}, budget=1024 * 1024)
    assert result["evicted_objects"] == 1
    assert not orphan.exists()
    assert not stale_part.exists()
    assert not tombstone.exists()

    # Summary generations cleanup keeps active pointers and removes obsolete ones.
    gen_root = root / "summary-generations"
    keep_gen = "1" * 32
    drop_gen = "2" * 32
    for g in (keep_gen, drop_gen):
        d = gen_root / g
        d.mkdir(parents=True)
        (d / "view.json").write_text("{}", encoding="utf-8")
    pruned = prune_summary_generations(root, {keep_gen})
    assert pruned["removed"] == 1
    assert (gen_root / keep_gen).is_dir()
    assert not (gen_root / drop_gen).exists()
