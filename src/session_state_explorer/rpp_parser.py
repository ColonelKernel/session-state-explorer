"""A pragmatic, tolerant parser for REAPER ``.rpp`` project files.

REAPER projects are plain-text and block-structured. Blocks open with a ``<TAG``
line and close with a lone ``>`` line; scalar settings are single lines such as
``NAME "Lead Vox"`` or ``TEMPO 120 4 4``. This parser walks the file line by line
with an explicit context stack, so unknown blocks (plug-in state chunks, render
configs, envelopes) are skipped safely rather than derailing the parse.

Design goals, in priority order:

1. **Never raise on real-world input.** Anything we cannot interpret confidently
   becomes a warning on :class:`ProjectState`, not an exception.
2. **Preserve traceability.** Raw source lines are kept on the parsed objects.
3. **Extract the human-meaningful surface**: tracks, items, sources, FX chains and
   sends. Plug-in-private parameter state is explicitly *not* reconstructed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .models import (
    FxState,
    MediaItemState,
    ProjectState,
    RouteState,
    TrackState,
)
from .utils import (
    classify_fx_family,
    classify_track_role,
    decode_color,
    linear_to_db,
    safe_float,
    safe_int,
)

_QUOTE_CHARS = "\"'`"
# Block openers whose first token denotes an FX processor.
_FX_TAGS = {"VST", "JS", "AU", "AUFX", "CLAP", "LV2", "DX"}


# ---------------------------------------------------------------------------
# Low-level tokenisation (REAPER quoting aware)
# ---------------------------------------------------------------------------

def _parse_first_token(text: str) -> Tuple[Optional[str], str]:
    """Return ``(token, remainder)`` honouring REAPER's quoting.

    REAPER quotes a value when it contains spaces, choosing the first of ``"`` ``'``
    or backtick that does not occur inside the value. We mirror that on read: if the
    field starts with a quote char, read to the matching close quote; otherwise read
    a whitespace-delimited bare token.
    """

    text = text.strip()
    if not text:
        return None, ""
    quote = text[0]
    if quote in _QUOTE_CHARS:
        end = text.find(quote, 1)
        if end == -1:
            # Unterminated quote: take the rest of the line, defensively.
            return text[1:], ""
        return text[1:end], text[end + 1 :].strip()
    parts = text.split(None, 1)
    token = parts[0]
    remainder = parts[1] if len(parts) > 1 else ""
    return token, remainder


def _tokenize(text: str) -> List[str]:
    """Split a line into REAPER-quoting-aware tokens."""

    tokens: List[str] = []
    rest = text
    while True:
        token, rest = _parse_first_token(rest)
        if token is None:
            break
        tokens.append(token)
    return tokens


def _first_value(rest: str) -> Optional[str]:
    """First quoted-or-bare value from the remainder of a property line."""

    token, _ = _parse_first_token(rest)
    return token


# ---------------------------------------------------------------------------
# Parse-time context frames
# ---------------------------------------------------------------------------

@dataclass
class _Frame:
    kind: str  # project | track | item | source | fxchain | fx | unknown
    track: Optional[TrackState] = None
    item: Optional[MediaItemState] = None
    fx: Optional[FxState] = None
    # FX-chain bookkeeping: a BYPASS line precedes the FX block it applies to.
    pending_enabled: Optional[bool] = None
    last_fx: Optional[FxState] = None


@dataclass
class _State:
    project: ProjectState
    stack: List[_Frame] = field(default_factory=list)
    track_count: int = 0
    # Deferred AUXRECV resolution: (dest_track_index, src_track_index, raw_line).
    pending_routes: List[Tuple[int, int, str]] = field(default_factory=list)

    def top(self) -> Optional[_Frame]:
        return self.stack[-1] if self.stack else None

    def nearest(self, kind: str) -> Optional[_Frame]:
        for frame in reversed(self.stack):
            if frame.kind == kind:
                return frame
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_rpp(text: str, source_file: Optional[str] = None) -> ProjectState:
    """Parse REAPER project ``text`` into a :class:`ProjectState`.

    ``source_file`` is recorded for provenance and used elsewhere to resolve audio
    paths relative to the project. This function never raises on malformed input.
    """

    project = ProjectState(source_file=source_file)
    if source_file:
        # A readable default project name; the .rpp has no explicit project title.
        from os.path import basename, splitext

        project.project_name = splitext(basename(source_file))[0]

    state = _State(project=project)

    try:
        for raw_line in text.splitlines():
            _consume_line(state, raw_line)
    except Exception as exc:  # pragma: no cover - defensive backstop
        project.warnings.append(f"Parser stopped early on an unexpected error: {exc!r}")

    _resolve_routes(state)
    _finalize(state)
    return project


# ---------------------------------------------------------------------------
# Line dispatch
# ---------------------------------------------------------------------------

def _consume_line(state: _State, raw_line: str) -> None:
    stripped = raw_line.strip()
    if not stripped:
        return

    # Record raw lines for the nearest track/item to support traceability.
    _record_raw(state, raw_line)

    if stripped == ">":
        if state.stack:
            state.stack.pop()
        return

    if stripped.startswith("<"):
        _open_block(state, stripped, raw_line)
        return

    _scalar_line(state, stripped, raw_line)


def _record_raw(state: _State, raw_line: str) -> None:
    top = state.top()
    if top is None:
        return
    if top.kind == "item" and top.item is not None:
        top.item.raw_lines.append(raw_line.rstrip())
    elif top.kind in {"track", "fxchain"}:
        track_frame = state.nearest("track")
        if track_frame and track_frame.track is not None:
            track_frame.track.raw_lines.append(raw_line.rstrip())


def _open_block(state: _State, stripped: str, raw_line: str) -> None:
    tag = stripped[1:].split(None, 1)[0].upper() if len(stripped) > 1 else ""
    top = state.top()

    if tag == "REAPER_PROJECT":
        state.stack.append(_Frame(kind="project"))
        return

    if tag == "TRACK":
        track = TrackState(id=f"track-{state.track_count}", index=state.track_count)
        state.project.tracks.append(track)
        state.track_count += 1
        state.stack.append(_Frame(kind="track", track=track))
        return

    if tag == "ITEM" and top is not None and state.nearest("track"):
        track = state.nearest("track").track
        assert track is not None
        item = MediaItemState(
            id=f"item-{track.index}-{len(track.media_items)}",
            track_id=track.id,
        )
        track.media_items.append(item)
        state.stack.append(_Frame(kind="item", item=item))
        return

    if tag == "SOURCE":
        item_frame = state.nearest("item")
        if item_frame and item_frame.item is not None:
            # Source type is the tag argument, e.g. "<SOURCE WAVE".
            source_type = stripped[1:].split(None, 2)
            if len(source_type) >= 2 and item_frame.item.source_type is None:
                item_frame.item.source_type = source_type[1].upper()
        state.stack.append(_Frame(kind="source", item=item_frame.item if item_frame else None))
        return

    if tag in {"FXCHAIN", "FXCHAIN_REC"}:
        state.stack.append(_Frame(kind="fxchain"))
        return

    if tag in _FX_TAGS and state.nearest("fxchain") is not None:
        _open_fx(state, tag, stripped, raw_line)
        return

    # Anything else (RENDER_CFG, envelopes, plug-in chunks, master FX, ...) is a
    # block we don't model. Push an opaque frame so nesting stays balanced.
    state.stack.append(_Frame(kind="unknown"))


def _open_fx(state: _State, tag: str, stripped: str, raw_line: str) -> None:
    track_frame = state.nearest("track")
    fxchain = state.nearest("fxchain")
    if track_frame is None or track_frame.track is None:
        state.stack.append(_Frame(kind="unknown"))
        return
    track = track_frame.track

    name = _extract_fx_name(stripped, tag)
    if not name:
        name = f"Unknown {tag} processor"
        state.project.warnings.append(
            f"FX name could not be read on track '{track.name or track.id}'; "
            "the processor may use an unusual chunk format."
        )

    enabled = True
    if fxchain is not None and fxchain.pending_enabled is not None:
        enabled = fxchain.pending_enabled
        fxchain.pending_enabled = None

    fx = FxState(
        id=f"fx-{track.index}-{len(track.fx)}",
        track_id=track.id,
        index=len(track.fx),
        name=name,
        fx_type=tag,
        family=classify_fx_family(name),
        enabled=enabled,
        raw_line=raw_line.rstrip(),
    )
    track.fx.append(fx)
    if fxchain is not None:
        fxchain.last_fx = fx
    state.stack.append(_Frame(kind="fx", fx=fx))


def _extract_fx_name(stripped: str, tag: str) -> Optional[str]:
    """Best-effort processor name from an FX opener line."""

    body = stripped[1:]  # drop leading '<'
    # Remove the tag token itself.
    _, remainder = _parse_first_token(body)
    for token in _tokenize(remainder):
        if token and token.strip():
            return token.strip()
    return None


def _scalar_line(state: _State, stripped: str, raw_line: str) -> None:
    key = stripped.split(None, 1)[0].upper()
    rest = stripped[len(key):].strip()
    top = state.top()
    top_kind = top.kind if top else None

    # ----- project-level settings -----
    if key == "TEMPO":
        state.project.tempo = safe_float(rest.split()[0]) if rest else None
        return
    if key == "SAMPLERATE":
        state.project.sample_rate = safe_int(rest.split()[0]) if rest else None
        return

    # ----- names: dispatch by current context -----
    if key == "NAME":
        value = _first_value(rest)
        if top_kind == "item":
            if top.item is not None:
                top.item.name = value
        else:
            track_frame = state.nearest("track")
            if track_frame and track_frame.track is not None and top_kind != "fx":
                if track_frame.track.name is None:
                    track_frame.track.name = value
                    track_frame.track.role = classify_track_role(value)
        return

    # ----- track-level settings -----
    if top_kind == "track" or (top_kind == "fxchain" and key in {"BYPASS", "PRESETNAME", "WAK"}):
        if _track_scalar(state, key, rest):
            return

    # ----- item / source settings -----
    if key == "POSITION" and state.nearest("item"):
        frame = state.nearest("item")
        if frame and frame.item is not None:
            frame.item.position = safe_float(rest.split()[0]) if rest else None
        return
    if key == "LENGTH" and state.nearest("item"):
        frame = state.nearest("item")
        if frame and frame.item is not None:
            frame.item.length = safe_float(rest.split()[0]) if rest else None
        return
    if key == "FILE" and state.nearest("item"):
        frame = state.nearest("item")
        if frame and frame.item is not None and frame.item.source_file is None:
            frame.item.source_file = _first_value(rest)
        return

    # ----- routing -----
    if key == "AUXRECV":
        _handle_auxrecv(state, rest, raw_line)
        return


def _track_scalar(state: _State, key: str, rest: str) -> bool:
    track_frame = state.nearest("track")
    track = track_frame.track if track_frame else None
    if track is None:
        return False

    if key == "VOLPAN":
        tokens = rest.split()
        if tokens:
            vol = safe_float(tokens[0])
            track.volume = vol
            track.volume_db = linear_to_db(vol)
        if len(tokens) > 1:
            track.pan = safe_float(tokens[1])
        return True

    if key == "MUTESOLO":
        tokens = rest.split()
        if tokens:
            track.mute = safe_int(tokens[0]) not in (0, None)
        if len(tokens) > 1:
            track.solo = safe_int(tokens[1]) not in (0, None)
        return True

    if key == "PEAKCOL":
        tokens = rest.split()
        if tokens:
            track.color = decode_color(safe_int(tokens[0]))
        return True

    if key == "BYPASS":
        fxchain = state.nearest("fxchain")
        if fxchain is not None:
            tokens = rest.split()
            bypassed = bool(tokens) and safe_int(tokens[0]) not in (0, None)
            fxchain.pending_enabled = not bypassed
        return True

    if key == "PRESETNAME":
        fxchain = state.nearest("fxchain")
        if fxchain is not None and fxchain.last_fx is not None:
            fxchain.last_fx.preset = _first_value(rest)
        return True

    if key == "WAK":
        return True  # plug-in "wet/automation" flags; nothing to model.

    return False


def _handle_auxrecv(state: _State, rest: str, raw_line: str) -> None:
    track_frame = state.nearest("track")
    if track_frame is None or track_frame.track is None:
        state.project.warnings.append(
            "Encountered an AUXRECV line outside of a track context; send ignored."
        )
        return
    dest_index = track_frame.track.index
    tokens = rest.split()
    src_index = safe_int(tokens[0]) if tokens else None
    if src_index is None:
        state.project.warnings.append(
            "Could not resolve target track for AUXRECV line."
        )
        return
    state.pending_routes.append((dest_index, src_index, raw_line.rstrip()))


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def _resolve_routes(state: _State) -> None:
    tracks = state.project.tracks
    for route_idx, (dest_index, src_index, raw) in enumerate(state.pending_routes):
        route_id = f"route-{route_idx}"
        if 0 <= src_index < len(tracks) and 0 <= dest_index < len(tracks):
            source = tracks[src_index]
            target = tracks[dest_index]
            state.project.routes.append(
                RouteState(
                    id=route_id,
                    source_track_id=source.id,
                    target_track_id=target.id,
                    target_name=target.name,
                    route_type="send",
                    raw_line=raw,
                )
            )
        else:
            # The receiving track (where the AUXRECV lives) is always a real,
            # parsed track; only the referenced source index is out of range. We
            # anchor the unresolved relationship on the known track so the graph
            # stays consistent, and flag the missing end as a warning.
            anchor = (
                tracks[dest_index].id
                if 0 <= dest_index < len(tracks)
                else (tracks[0].id if tracks else "project")
            )
            state.project.routes.append(
                RouteState(
                    id=route_id,
                    source_track_id=anchor,
                    target_track_id=None,
                    target_name=f"track index {src_index} (out of range)",
                    route_type="unresolved",
                    raw_line=raw,
                )
            )
            state.project.warnings.append(
                "Could not resolve target track for AUXRECV line."
            )


def _finalize(state: _State) -> None:
    project = state.project
    # Roles for tracks that never got an explicit NAME still classify as Unknown.
    for track in project.tracks:
        if track.role is None:
            track.role = classify_track_role(track.name)
    if not project.tracks:
        project.warnings.append(
            "No tracks were parsed. The file may not be a REAPER project, or it uses "
            "an unsupported layout."
        )
