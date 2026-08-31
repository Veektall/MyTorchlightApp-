# HANDOFF: AGENT-01

Status: DONE
Assignment: Tutorial Prompt Vision — make Up/Down/Left/Right sensing fast/reliable from rendered pixels without synchronous OCR dominating bootstrap.

## Deliverables
- `subway_ai/scripts/stage15_prompt_template_detector.py`
  - commit `ddbca92c396731f558bbc4e3f6190f369f010ad1`
- `subway_ai/scripts/benchmark_stage15_prompt_detector.py`
  - commit `4b288d89bfe997b28b8db2175430ae65532c4b3f`
- `.swarm/runs/SWARM-2026-STAGE15-01/outputs/AGENT-01-prompt-benchmark.json`
  - commit `ad46ebca84dba0cd1ade06a980dfc9e8f57cfc6b`
- Worker branch: `swarm/SWARM-2026-STAGE15-01/AGENT-01`

## Key result
The prompt-sensing bottleneck can be removed from the Tesseract hot path. The proposed detector uses rendered pixels only:
1. normalize the canvas to 640x360;
2. isolate white glyph interiors adjacent to the tutorial font's black outline;
3. translation-invariant template-match a shared `Press Arrow Key` prefix to prove prompt presence;
4. independently template-match the suffix word to classify `up/down/left/right`;
5. return no direction unless presence, suffix score, and suffix-margin thresholds all pass.

This search is broad in Y, so it tolerates the prompt moving vertically during tutorial animations. It is bootstrap-only and never becomes learned-policy input.

## Verification
Source artifacts:
- v24 run `33340495280`, artifact `9740534194`
- v25 run `33379193006`, artifact `9753676757`

Ground truth was manually curated by visual inspection of saved video frames, including prompt-present and prompt-absent timestamps. The replay harness normalizes only the recording layout; the production detector receives the canvas screenshot directly.

Measured replay result:
- aggregate visible-prompt accuracy: **15/15**
- prompt-absent false positives: **0/17**
- v24 independent transfer: **5/5 positives correct, 0/9 false positives**
- v25: **10/10 positives correct, 0/8 false positives**
- all four directions are represented (`up`, `down`, `left`, `right`)

Latency on the same canvas crops after warm-up:
- template detector: median **7.861 ms**, p95 **9.977 ms**, max **13.727 ms** over 160 calls
- old broad v17 Tesseract path: median **187.439 ms**, p95 **277.485 ms**, max **316.692 ms** over 8 warmed calls
- median speedup: **23.84x**

The old OCR path also exhibited multi-second outliers during exploratory replay; those are eliminated because the proposed detector performs no OCR.

Exact per-frame scores/timestamps are in `AGENT-01-prompt-benchmark.json` and reproducible with:

```bash
cd subway_ai/scripts
python benchmark_stage15_prompt_detector.py \
  --v24 /path/to/v24/stage15_session.webm \
  --v25 /path/to/v25/stage15_session.webm \
  --out prompt-benchmark.json
```

## False-positive guard
A direction is returned only when all three conditions pass:
- common prompt-prefix match >= `0.55`;
- direction-suffix match >= `0.62`;
- best-vs-second suffix margin >= `0.08`.

On curated prompt-absent frames, the largest presence score was well below the positive range and no frame fired. Background direction-like words alone are insufficient because the common rendered prompt-prefix must also match.

## Integration instructions
Recommended minimal integration into the next evaluator:
1. import `detect_prompt_direction` or `score_prompt_direction` from `stage15_prompt_template_detector.py`;
2. use it as the primary rendered-pixel prompt reader in the existing asynchronous/capture-generation wrapper;
3. **preserve Agent-02/state-machine causal semantics and the proven trusted actuator unchanged**;
4. do not modify score/death/tutorial-handoff/benchmark acceptance gates;
5. optionally keep Tesseract only as a slow fallback for ambiguous/no-detection frames, never as the hot-path actuator trigger and never allowed to override causal capture-generation rules.

The detector is stateless. It should report perception only; prompt latching/retry/action semantics belong to AGENT-02/Orchestrator.

## Constraints preserved
- rendered pixels only;
- no DOM/game internals/accessibility state;
- bootstrap-only, never learned-policy input;
- no synthetic keyboard events;
- no weakening of tutorial handoff or benchmark gates.

## Known limitations / risks
- Templates assume the current official game's white/black outlined tutorial font. A future visual redesign could require new templates/thresholds.
- The detector intentionally covers only Up/Down/Left/Right. It does not classify Space/hoverboard because Agent-01's assignment and observed Stage-15 tutorial sequence require the four arrow directions.
- The offline replay corpus is v24+v25, not a new official-game live run. The Orchestrator should perform the authoritative end-to-end integration run after combining worker results.
- On ambiguous frames the detector returns `None`; it is designed to fail closed rather than guess.

Decisions introduced: NONE.
Dependencies affected: AGENT-02 and ORCHESTRATOR can consume this perception module; it does not supersede their state/control logic.

Next recommended action: ORCHESTRATOR should integrate this detector as the primary prompt sensor into the evidence-backed AGENT-02 control semantics, then run one authoritative Stage-15 workflow.
