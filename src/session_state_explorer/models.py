"""Typed data models for the parsed DAW-state.

These ``pydantic`` v2 models describe what the prototype can confidently extract
from a REAPER ``.rpp`` file. The design favours *transparency about uncertainty*
over completeness: optional fields default to ``None`` and raw source lines are
preserved (``raw_line`` / ``raw_lines``) so the UI can show traceability between a
parsed value and the underlying project text.

Nothing here attempts to reconstruct plug-in-private state. The models capture the
accessible, human-meaningful surface of a session.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["info", "suggestion", "warning"]


class FxState(BaseModel):
    """A single processor in a track's FX chain, as observed in the ``.rpp``."""

    id: str
    track_id: str
    index: int
    name: str
    fx_type: Optional[str] = None  # e.g. "VST", "VST3", "JS", "AU", "CLAP"
    family: Optional[str] = None  # heuristic family: EQ / Dynamics / Ambience / ...
    enabled: Optional[bool] = None  # False when the processor is bypassed
    preset: Optional[str] = None
    raw_line: Optional[str] = None


class MediaItemState(BaseModel):
    """A media item (clip) placed on a track."""

    id: str
    track_id: str
    name: Optional[str] = None
    position: Optional[float] = None  # seconds
    length: Optional[float] = None  # seconds
    source_file: Optional[str] = None
    source_type: Optional[str] = None  # e.g. "WAVE", "MP3", "FLAC", "MIDI"
    raw_lines: List[str] = Field(default_factory=list)


class RouteState(BaseModel):
    """A send / receive / routing relationship between tracks.

    REAPER stores sends as ``AUXRECV`` lines on the *receiving* track that point at
    the *source* track by index. We normalise this into a directed source -> target
    relationship. When the target cannot be resolved confidently, ``route_type`` is
    set to ``"unresolved"`` and a warning is recorded on the project.
    """

    id: str
    source_track_id: str
    target_track_id: Optional[str] = None
    target_name: Optional[str] = None
    route_type: str = "send"  # "send" | "receive" | "unresolved"
    raw_line: Optional[str] = None


class TrackState(BaseModel):
    """A single track and its observable state."""

    id: str
    index: int
    name: Optional[str] = None
    role: Optional[str] = None  # heuristic role: Vocal / Drums / Bass / ...
    volume: Optional[float] = None  # linear gain as stored by REAPER (1.0 == unity)
    volume_db: Optional[float] = None  # convenience: volume expressed in dB
    pan: Optional[float] = None  # -1.0 (L) .. +1.0 (R)
    mute: Optional[bool] = None
    solo: Optional[bool] = None
    color: Optional[str] = None  # "#rrggbb" when decodable
    media_items: List[MediaItemState] = Field(default_factory=list)
    fx: List[FxState] = Field(default_factory=list)
    raw_lines: List[str] = Field(default_factory=list)


class ProjectState(BaseModel):
    """The top-level parsed project."""

    project_name: Optional[str] = None
    source_file: Optional[str] = None
    tempo: Optional[float] = None
    sample_rate: Optional[int] = None
    tracks: List[TrackState] = Field(default_factory=list)
    routes: List[RouteState] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    # -- convenience accessors -------------------------------------------------
    @property
    def media_items(self) -> List[MediaItemState]:
        items: List[MediaItemState] = []
        for track in self.tracks:
            items.extend(track.media_items)
        return items

    @property
    def fx(self) -> List[FxState]:
        processors: List[FxState] = []
        for track in self.tracks:
            processors.extend(track.fx)
        return processors


class AudioDescriptorSet(BaseModel):
    """Simple acoustic descriptors for one audio file.

    Computed with ``librosa`` by default. When the audio backend is unavailable or
    a file cannot be read, ``available`` is ``False`` and ``unavailable_reason``
    explains why, so the rest of the pipeline can continue uninterrupted.
    """

    node_id: Optional[str] = None  # graph node id of the associated audio_file
    file_path: Optional[str] = None
    available: bool = False
    unavailable_reason: Optional[str] = None

    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    rms_mean: Optional[float] = None
    rms_std: Optional[float] = None
    spectral_centroid_mean: Optional[float] = None
    spectral_bandwidth_mean: Optional[float] = None
    spectral_rolloff_mean: Optional[float] = None
    zero_crossing_rate_mean: Optional[float] = None
    tempo_estimate: Optional[float] = None
    onset_strength_mean: Optional[float] = None
    dynamic_range_db: Optional[float] = None  # approximation (peak vs noise floor)
    peak_amplitude: Optional[float] = None
    integrated_loudness_lufs: Optional[float] = None  # via pyloudnorm if available

    # Optional high-level descriptors contributed by an Essentia adapter, if present.
    extra: dict = Field(default_factory=dict)


class Recommendation(BaseModel):
    """An explainable, graph-derived suggestion.

    Every recommendation carries an explicit ``caveat`` to preserve producer agency:
    these are heuristics meant to support reflection, not objective mixing rules.
    """

    id: str
    title: str
    severity: Severity = "suggestion"
    confidence: float = 0.5
    related_node_ids: List[str] = Field(default_factory=list)
    explanation: str = ""
    suggested_action: str = ""
    caveat: str = "This is a graph-based heuristic, not an objective mixing rule."
