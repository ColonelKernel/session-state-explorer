# 90-second demo script

A tight walkthrough for a screen recording. Aim for ~90 seconds; the beats below map to
roughly 15 seconds each. Speak in a calm, research-prototype register — no hype.

---

**0:00 — Problem (≈15s)**

> "DAW sessions contain rich production knowledge — how a mix is organised, what is
> processed where, how things are routed. But most AI music systems only ever see rendered
> audio or isolated parameters. The session structure itself is thrown away."

**0:15 — Prototype (≈15s)**

> "Session State Explorer parses a REAPER project into an interpretable graph of its DAW
> state. I'll load the bundled example project."

*(Click **Load bundled example project**. Show the parsed summary: tracks, items, FX,
routes, tempo, and the count of uncertain elements.)*

**0:30 — Walkthrough (≈15s)**

> "Tracks, clips, FX, routes, and audio files become nodes and edges. Colour and shape mark
> the node type. I can filter the view, or focus on a single track."

*(Hover a few nodes to show tooltips; toggle a filter; point out the unresolved-route node
that marks something the parser could only partially observe.)*

**0:45 — Analysis (≈15s)**

> "With a base audio directory set, the prototype extracts simple acoustic descriptors —
> loudness, spectral shape, dynamics — connecting session structure to acoustic outcome."

*(Tick **Extract audio descriptors**; show the descriptors table.)*

**1:00 — Recommendation (≈15s)**

> "From the graph, it suggests actions — here, a shared ambience bus and an under-processed
> vocal — each with an explanation, a suggested action, and an explicit caveat: these are
> heuristics, not objective mixing rules."

*(Open one or two recommendation cards; read the caveat line aloud.)*

**1:15 — Research value (≈15s)**

> "This is a first step toward DAW-state representations that support creativity rather than
> replacing producers — interpretable, honest about uncertainty, and human-centered. The
> whole session can be exported as JSON for further research."

*(Click an export button to show the JSON download, then stop.)*

---

## Recording tips

- Generate data first: `python data/examples/make_example_data.py`.
- Set the base audio directory to `data/examples` so descriptors and the level-imbalance
  recommendation appear.
- Keep the browser zoom moderate so the graph and a couple of tables are legible.
- Record at 1080p; trim to ~90 seconds.
