"""Tests for the REAPER .rpp parser."""

from __future__ import annotations

from session_state_explorer.rpp_parser import parse_rpp

FAKE_RPP = """<REAPER_PROJECT 0.1 "7.0/test" 1700000000
  TEMPO 124 4 4
  SAMPLERATE 48000 0 0
  <TRACK {GUID-0}
    NAME "Lead Vox"
    PEAKCOL 16576
    VOLPAN 1 -0.2 -1 -1 1
    MUTESOLO 0 0 0
    <ITEM
      POSITION 0
      LENGTH 4.5
      NAME "vox_take1"
      <SOURCE WAVE
        FILE "audio/vox.wav"
      >
    >
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST3: Pro-Q 3 (FabFilter)" ProQ3.vst3 0 "" 1
        ZmFrZWNodW5r
      >
      PRESETNAME "Vocal Bright"
      WAK 0 0
    >
  >
  <TRACK {GUID-1}
    NAME "Reverb Bus"
    VOLPAN 1 0 -1 -1 1
    MUTESOLO 0 0 0
    AUXRECV 0 0 1 0 0 0 0
  >
>
"""


def test_tracks_are_parsed():
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    assert len(project.tracks) == 2
    assert project.tracks[0].name == "Lead Vox"
    assert project.tracks[1].name == "Reverb Bus"
    assert project.tempo == 124.0
    assert project.sample_rate == 48000


def test_track_attributes_are_parsed():
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    vox = project.tracks[0]
    assert vox.role == "Vocal"
    assert vox.pan == -0.2
    assert vox.volume_db == 0.0  # unity gain
    assert vox.color is not None and vox.color.startswith("#")
    assert vox.mute is False


def test_media_item_is_parsed():
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    items = project.media_items
    assert len(items) == 1
    item = items[0]
    assert item.name == "vox_take1"
    assert item.position == 0.0
    assert item.length == 4.5
    assert item.source_file == "audio/vox.wav"
    assert item.source_type == "WAVE"


def test_fx_is_parsed_with_family_and_preset():
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    fx = project.tracks[0].fx
    assert len(fx) == 1
    assert "Pro-Q" in fx[0].name
    assert fx[0].family == "EQ"
    assert fx[0].fx_type == "VST"
    assert fx[0].enabled is True
    assert fx[0].preset == "Vocal Bright"
    assert fx[0].raw_line  # traceability preserved


def test_bypassed_fx_marked_disabled():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Gtr"
    <FXCHAIN
      BYPASS 1 0 0
      <VST "VST: ReaDelay (Cockos)" readelay.dll 0 "" 0
      >
    >
  >
>
"""
    project = parse_rpp(rpp)
    fx = project.tracks[0].fx
    assert len(fx) == 1
    assert fx[0].enabled is False
    assert fx[0].family == "Ambience"


def test_send_is_parsed():
    project = parse_rpp(FAKE_RPP, source_file="test.rpp")
    assert len(project.routes) == 1
    route = project.routes[0]
    # AUXRECV 0 on track index 1 => track 0 sends into track 1.
    assert route.source_track_id == "track-0"
    assert route.target_track_id == "track-1"
    assert route.route_type == "send"


def test_unresolved_send_records_warning():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Bus"
    AUXRECV 99 0 1 0 0 0 0
  >
>
"""
    project = parse_rpp(rpp)
    assert len(project.routes) == 1
    assert project.routes[0].route_type == "unresolved"
    assert any("AUXRECV" in w for w in project.warnings)


def test_parser_is_robust_to_garbage():
    # Malformed / truncated input must not raise.
    project = parse_rpp("<REAPER_PROJECT\n  <TRACK\n    NAME \"x\n  garbage line ]]\n")
    assert isinstance(project.warnings, list)
    # It should still have found the one track.
    assert len(project.tracks) == 1


def test_empty_input_warns_no_tracks():
    project = parse_rpp("")
    assert project.tracks == []
    assert any("No tracks" in w for w in project.warnings)
