"""End-to-end tests for the canonical 5-file bundle exporter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from session_state_explorer.canonical_export.exporter import (
    BUNDLE_FILES,
    export_bundle,
)

EXAMPLE_RPP = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "examples"
    / "example_project.rpp"
)


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("bundle")
    result = export_bundle(EXAMPLE_RPP, out_dir)
    return out_dir, result


def _load(out_dir: Path, name: str):
    return json.loads((out_dir / name).read_text(encoding="utf-8"))


def test_all_five_bundle_files_are_written(bundle):
    out_dir, result = bundle
    assert set(BUNDLE_FILES) == {
        "adapter_descriptor.json",
        "capabilities.json",
        "native.json",
        "canonical.snapshot.json",
        "validation.json",
    }
    for name in BUNDLE_FILES:
        assert (out_dir / name).is_file(), name
    assert result["valid"] is True


def test_validation_report_is_valid(bundle):
    out_dir, _ = bundle
    report = _load(out_dir, "validation.json")
    assert report["valid"] is True
    assert report["errors"] == []
    assert report["stats"]["entities"] > 0


def test_snapshot_has_track_channel_split(bundle):
    out_dir, _ = bundle
    snapshot = _load(out_dir, "canonical.snapshot.json")
    types = {e["entity_type"] for e in snapshot["entities"]}
    assert "PROJECT" in types
    assert "TRACK" in types
    assert "CHANNEL" in types
    rel_types = {r["rel_type"] for r in snapshot["relationships"]}
    assert "TRACK_USES_CHANNEL" in rel_types
    # REAPER fuses lane and signal path: every TRACK emits its CHANNEL half.
    tracks = [e for e in snapshot["entities"] if e["entity_type"] == "TRACK"]
    used = {
        r["source"]
        for r in snapshot["relationships"]
        if r["rel_type"] == "TRACK_USES_CHANNEL"
    }
    assert {t["id"] for t in tracks} == used


def test_native_hash_matches_extensions_ref(bundle):
    out_dir, result = bundle
    snapshot = _load(out_dir, "canonical.snapshot.json")
    ref = snapshot["extensions"]["reaper"]["native_file"]
    assert ref["path"] == "native.json"
    actual = hashlib.sha256((out_dir / "native.json").read_bytes()).hexdigest()
    assert ref["sha256"] == actual == result["native_sha256"]
    # snapshot_id is derived from the same content hash (deterministic).
    assert snapshot["snapshot_id"] == f"reaper:rpp:{actual[:16]}"


def test_no_home_dir_paths_in_canonical_json(bundle):
    out_dir, _ = bundle
    for name in ("canonical.snapshot.json", "native.json"):
        text = (out_dir / name).read_text(encoding="utf-8")
        assert "/Users/" not in text, name
        assert "/home/" not in text, name
        assert str(Path.home()) not in text, name


def test_provenance_resolves_and_source_is_honest(bundle):
    out_dir, _ = bundle
    snapshot = _load(out_dir, "canonical.snapshot.json")
    assert snapshot["schema_version"].startswith("0.2")
    assert snapshot["source"]["daw"] == "reaper"
    assert snapshot["source"]["adapter"] == "session-state-explorer-reaper"
    assert snapshot["source"]["capture_modes"] == ["file_parse"]
    assert snapshot["source"]["daw_version"] == "7.0"  # from the .rpp header
    prov_ids = {p["id"] for p in snapshot["provenance"]}
    for entity in snapshot["entities"]:
        for ref in entity["prov"].values():
            assert ref in prov_ids
    # created_at derives from the file mtime, not now(): deterministic.
    assert snapshot["created_at"]
    evidences = {p["evidence"] for p in snapshot["provenance"]}
    assert "OBSERVED" in evidences
    assert "INFERRED" in evidences  # heuristic track roles


def test_export_is_deterministic(bundle, tmp_path):
    out_dir, _ = bundle
    second = tmp_path / "again"
    export_bundle(EXAMPLE_RPP, second)
    for name in BUNDLE_FILES:
        assert (second / name).read_bytes() == (out_dir / name).read_bytes(), name


def test_capabilities_and_descriptor_are_honest(bundle):
    out_dir, _ = bundle
    caps = _load(out_dir, "capabilities.json")
    assert set(caps["read"]) >= {"structure", "channel", "routing", "processing"}
    # write / live_observation / render are empty: support NONE, stated.
    assert caps["write"] == {}
    assert caps["live_observation"] == {}
    assert caps["render"] == {}
    plugin_state = caps["read"]["processing"]["fields"]["plugin_internal_state"]
    assert plugin_state["support"] == "NONE"
    descriptor = _load(out_dir, "adapter_descriptor.json")
    assert descriptor["adapter_id"] == "reaper-rpp"
    assert descriptor["known_limitations"]
