"""Optional Essentia adapter (graceful no-op when Essentia is absent).

Essentia provides richer high-level descriptors (loudness, danceability, and various
trained classifiers). It can be non-trivial to install on some platforms, so this
prototype never depends on it. When Essentia is importable, ``maybe_extract_highlevel``
returns a small dict of extra descriptors; otherwise it returns ``{}`` and the rest of
the pipeline is unaffected.
"""

from __future__ import annotations

from typing import Dict

try:  # pragma: no cover - Essentia is an optional, platform-dependent accelerator
    import essentia  # noqa: F401
    import essentia.standard as es  # noqa: F401

    ESSENTIA_AVAILABLE = True
except Exception:  # pragma: no cover
    ESSENTIA_AVAILABLE = False


def maybe_extract_highlevel(path: str) -> Dict[str, float]:
    """Return extra high-level descriptors if Essentia is available, else ``{}``.

    This is intentionally conservative: it only computes a couple of cheap,
    well-defined descriptors so it cannot become a heavy or fragile dependency.
    """

    if not ESSENTIA_AVAILABLE:
        return {}

    try:  # pragma: no cover - exercised only where Essentia is installed
        import essentia.standard as es

        loader = es.MonoLoader(filename=path)
        audio = loader()
        extra: Dict[str, float] = {}

        loudness = es.Loudness()
        extra["essentia_loudness"] = float(loudness(audio))

        try:
            danceability = es.Danceability()
            value = danceability(audio)
            # Danceability returns (value, dfa) in recent Essentia versions.
            extra["essentia_danceability"] = float(
                value[0] if isinstance(value, (tuple, list)) else value
            )
        except Exception:
            pass

        return extra
    except Exception:  # pragma: no cover - defensive
        return {}
