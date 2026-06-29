"""A tiny session "fingerprint" for structural comparison between projects.

This is a stretch feature: it reduces a parsed session (plus optional audio
descriptors) to a small vector of interpretable counts, and offers a similarity
measure between two such fingerprints. The intent is to demonstrate how the graph
representation could support retrieval ("find sessions structured like this one")
in future work — not to provide a validated similarity metric.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from .models import AudioDescriptorSet, ProjectState
from .utils import AMBIENCE_FAMILIES, DYNAMICS_FAMILIES, EQ_FAMILIES

# Keys used to build the numeric comparison vector. Descriptor summaries are kept
# separate (they are optional and on a different scale).
_VECTOR_KEYS = [
    "n_tracks",
    "n_vocal_tracks",
    "n_drum_tracks",
    "n_bass_tracks",
    "n_fx",
    "n_ambience_fx",
    "n_dynamics_fx",
    "n_eq_fx",
    "n_routes",
    "avg_fx_per_track",
]


def compute_session_fingerprint(
    project: ProjectState,
    descriptors: Optional[List[AudioDescriptorSet]] = None,
) -> Dict:
    """Reduce a session to a small dict of interpretable structural counts."""

    descriptors = descriptors or []
    tracks = project.tracks
    all_fx = project.fx

    def role_count(role: str) -> int:
        return sum(1 for t in tracks if (t.role or "") == role)

    def family_count(families: set) -> int:
        return sum(1 for f in all_fx if (f.family or "") in families)

    n_tracks = len(tracks)
    n_fx = len(all_fx)

    fingerprint: Dict = {
        "n_tracks": n_tracks,
        "n_vocal_tracks": role_count("Vocal"),
        "n_drum_tracks": role_count("Drums"),
        "n_bass_tracks": role_count("Bass"),
        "n_guitar_tracks": role_count("Guitar"),
        "n_keys_tracks": role_count("Keys"),
        "n_bus_tracks": role_count("Bus"),
        "n_fx": n_fx,
        "n_ambience_fx": family_count(AMBIENCE_FAMILIES),
        "n_dynamics_fx": family_count(DYNAMICS_FAMILIES),
        "n_eq_fx": family_count(EQ_FAMILIES),
        "n_routes": len(project.routes),
        "avg_fx_per_track": round(n_fx / n_tracks, 3) if n_tracks else 0.0,
    }

    available = [d for d in descriptors if d.available]
    if available:
        fingerprint["descriptor_summary"] = {
            "n_audio_files": len(available),
            "mean_rms": _mean([d.rms_mean for d in available]),
            "mean_spectral_centroid": _mean(
                [d.spectral_centroid_mean for d in available]
            ),
            "mean_peak_amplitude": _mean([d.peak_amplitude for d in available]),
        }

    return fingerprint


def compare_fingerprints(fp1: Dict, fp2: Dict) -> float:
    """Cosine similarity over the structural vector, in ``[0.0, 1.0]``.

    Identical structural fingerprints return ``1.0``. Missing keys are treated as
    zero. The descriptor summary is intentionally excluded so the measure reflects
    *session structure* rather than absolute audio levels.
    """

    vec1 = [_as_float(fp1.get(key, 0.0)) for key in _VECTOR_KEYS]
    vec2 = [_as_float(fp2.get(key, 0.0)) for key in _VECTOR_KEYS]

    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    similarity = dot / (norm1 * norm2)
    # Guard against tiny floating-point overshoot above 1.0.
    return round(max(0.0, min(1.0, similarity)), 4)


def _mean(values: List[Optional[float]]) -> Optional[float]:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 6)


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
