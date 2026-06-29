"""Tests for the session fingerprint and comparison (stretch feature)."""

from __future__ import annotations

from session_state_explorer.fingerprint import (
    compare_fingerprints,
    compute_session_fingerprint,
)
from session_state_explorer.rpp_parser import parse_rpp

RPP_A = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Lead Vox"
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaEQ (Cockos)" e.dll 0 "" 0
      >
    >
  >
  <TRACK
    NAME "Kick"
  >
>
"""

RPP_B = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Guitar"
  >
>
"""


def test_fingerprint_has_expected_keys():
    project = parse_rpp(RPP_A)
    fp = compute_session_fingerprint(project, [])
    for key in (
        "n_tracks",
        "n_vocal_tracks",
        "n_drum_tracks",
        "n_fx",
        "n_eq_fx",
        "n_routes",
        "avg_fx_per_track",
    ):
        assert key in fp
    assert fp["n_tracks"] == 2
    assert fp["n_vocal_tracks"] == 1
    assert fp["n_eq_fx"] == 1


def test_identical_sessions_have_similarity_one():
    project = parse_rpp(RPP_A)
    fp1 = compute_session_fingerprint(project, [])
    fp2 = compute_session_fingerprint(parse_rpp(RPP_A), [])
    assert compare_fingerprints(fp1, fp2) == 1.0


def test_different_sessions_have_lower_similarity():
    fp_a = compute_session_fingerprint(parse_rpp(RPP_A), [])
    fp_b = compute_session_fingerprint(parse_rpp(RPP_B), [])
    similarity = compare_fingerprints(fp_a, fp_b)
    assert 0.0 <= similarity < 1.0


def test_empty_fingerprint_comparison_is_safe():
    assert compare_fingerprints({}, {}) == 0.0
