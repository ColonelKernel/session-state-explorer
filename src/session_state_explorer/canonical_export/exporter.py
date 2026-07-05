"""``export_bundle()`` — one ``.rpp`` file in, one 5-file snapshot bundle out.

The bundle is the adapter's wire product (the analyzer never sees the nested
intermediate):

- ``adapter_descriptor.json`` — the bundle-level identity card.
- ``capabilities.json`` — the honest capability manifest (read pathway only).
- ``native.json`` — the complete native ``ProjectState`` dump (the
  losslessness guarantee; referenced by path+hash from the snapshot, never
  embedded in it).
- ``canonical.snapshot.json`` — the flat v0.2 ``CanonicalDAWSnapshot``.
- ``validation.json`` — the ``validate_snapshot`` report for the snapshot as
  written.

Determinism: ids are reset per export, ``snapshot_id`` derives from the
content hash of ``native.json``, and ``created_at`` derives from the source
file's mtime — exporting the same file twice yields byte-identical bundles.

Sanitization (on by default): home-directory prefixes in path strings are
replaced with ``"~"`` everywhere in the bundle, so a shared fixture never
leaks a user name.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from canonical_snapshot import SourceInfo, flatten_session, validate_snapshot
from canonical_snapshot.ids import reset_id_counters

from .. import __version__ as ADAPTER_VERSION
from ..rpp_parser import parse_rpp
from .manifest import (
    CAPTURE_MODES,
    build_adapter_descriptor,
    build_capability_manifest,
)
from .mapper import to_canonical

BUNDLE_FILES = (
    "adapter_descriptor.json",
    "capabilities.json",
    "native.json",
    "canonical.snapshot.json",
    "validation.json",
)

# Any POSIX home-directory prefix (not just the current user's): a bundle
# sanitized on one machine must not leak collaborators' paths either.
_HOME_PREFIX_RE = re.compile(r"(?:/Users|/home)/[^/\s\"']+")


def _redact_homes(value: str) -> str:
    home = str(Path.home())
    if home not in ("/", "") and value.startswith(home):
        value = "~" + value[len(home):]
    return _HOME_PREFIX_RE.sub("~", value)


def _sanitize(obj: Any) -> Any:
    """Recursively redact home-directory prefixes in every string."""

    if isinstance(obj, str):
        return _redact_homes(obj)
    if isinstance(obj, dict):
        return {key: _sanitize(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(value) for value in obj]
    return obj


def _dump_json(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _daw_version(header_platform: Optional[str]) -> Optional[str]:
    """Version part of the ``<REAPER_PROJECT`` header token (``"7.0/win64"`` -> ``"7.0"``)."""

    if not header_platform:
        return None
    return header_platform.split("/", 1)[0] or header_platform


def export_bundle(
    rpp_path: Path,
    out_dir: Path,
    *,
    audio_base: Optional[Path] = None,
    sanitize: bool = True,
) -> dict[str, Any]:
    """Export one ``.rpp`` project as a canonical 5-file snapshot bundle.

    Returns a small report: bundle file paths, the validation outcome, and
    entity/relationship counts. Raises :class:`FileNotFoundError` when
    ``rpp_path`` does not exist.
    """

    rpp_path = Path(rpp_path)
    if not rpp_path.is_file():
        raise FileNotFoundError(f"No such .rpp file: {rpp_path}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Deterministic ids for every export run.
    reset_id_counters()

    # -- parse: .rpp text -> native ProjectState ---------------------------
    text = rpp_path.read_text(encoding="utf-8", errors="replace")
    project = parse_rpp(text, source_file=str(rpp_path))

    # -- native.json (sanitized first so the recorded hash matches the file) --
    native_dict = project.model_dump()
    if sanitize:
        native_dict = _sanitize(native_dict)
    native_bytes = _dump_json(native_dict)
    native_sha256 = hashlib.sha256(native_bytes).hexdigest()

    # -- nested intermediate -> flat v0.2 snapshot --------------------------
    session = to_canonical(project, source_artifact="rpp_file")
    if audio_base is not None:
        session.metadata["audio_base_dir"] = str(audio_base)

    daw_version = _daw_version(project.header_platform)
    source = SourceInfo(
        daw="reaper",
        daw_version=daw_version,
        adapter="session-state-explorer-reaper",
        adapter_version=ADAPTER_VERSION,
        capture_modes=list(CAPTURE_MODES),
    )
    capabilities = build_capability_manifest(
        daw_version=daw_version, adapter_version=ADAPTER_VERSION
    )
    created_at = datetime.fromtimestamp(
        rpp_path.stat().st_mtime, tz=timezone.utc
    ).isoformat()

    snapshot = flatten_session(
        session,
        source,
        capabilities,
        native_file="native.json",
        native_sha256=native_sha256,
        snapshot_id=f"reaper:rpp:{native_sha256[:16]}",
        created_at=created_at,
        default_stability="COMMUNITY_DOCUMENTED",
    )

    snapshot_dict = snapshot.model_dump()
    if sanitize:
        snapshot_dict = _sanitize(snapshot_dict)

    # -- validate exactly what will be written ------------------------------
    report = validate_snapshot(snapshot_dict)

    # -- write the 5-file bundle --------------------------------------------
    payloads = {
        "adapter_descriptor.json": build_adapter_descriptor().model_dump(),
        "capabilities.json": capabilities.model_dump(),
        "canonical.snapshot.json": snapshot_dict,
        "validation.json": report.model_dump(),
    }
    paths: dict[str, Path] = {}
    for name in BUNDLE_FILES:
        path = out_dir / name
        if name == "native.json":
            path.write_bytes(native_bytes)
        else:
            path.write_bytes(_dump_json(payloads[name]))
        paths[name] = path

    return {
        "bundle_dir": out_dir,
        "files": paths,
        "snapshot_id": snapshot_dict["snapshot_id"],
        "native_sha256": native_sha256,
        "valid": report.valid,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
        "stats": dict(report.stats),
    }
