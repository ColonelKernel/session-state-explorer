# Example data

This folder provides a small, self-contained example so the app can be demonstrated without
any proprietary material.

## Files

- `example_project.rpp` — a synthetic REAPER project (committed). It deliberately exercises
  the parser and several recommendation rules: an under-processed vocal track, a dense FX
  chain, individual ambience FX without a shared return, a real drum-group bus with sends,
  and one intentionally **unresolved** send (a source index out of range) to demonstrate
  partial observability.
- `make_example_data.py` — regenerates `example_project.rpp` and synthesises short audio
  stems into `audio/`.
- `audio/` — generated WAV stems (git-ignored). They are produced from code (sine tones and
  filtered noise), contain no copyrighted material, and have deliberately different levels
  so the descriptor-based level-imbalance recommendation can fire.

## Generating the audio

```bash
python data/examples/make_example_data.py
```

This needs `numpy` and `soundfile` (both included in `requirements.txt`). The `.rpp` itself
needs no dependencies and is already committed, so the graph demo works even before the
audio is generated.

## Using it in the app

1. Run `streamlit run src/session_state_explorer/app.py`.
2. Click **Load bundled example project**.
3. Set the base audio directory to `data/examples` (auto-filled when you load the example)
   and tick **Extract audio descriptors**.

## Bringing your own project

Any REAPER `.rpp` will work. Upload it in the sidebar and, if you want audio descriptors,
point the base audio directory at the folder containing the referenced media (or upload the
stems directly).
