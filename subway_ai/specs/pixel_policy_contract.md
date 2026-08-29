# Subway Surfers Pixel-Only Policy Contract

## Goal
Build an agent that plays the official Subway Surfers game from the same visual evidence available to a human player.

## Evaluation interface

**Input**
- Only rendered RGB game pixels.
- Canonical live observation: 8 consecutive RGB frames sampled from a 15 fps stream.
- Live policy frame size: 640 x 360 pixels (width x height), matching the official browser game's landscape canvas.
- No DOM, JavaScript objects, internal coordinates, collision flags, obstacle lists, score variables, or game telemetry may enter the evaluated policy.

**Output action space**
- `stay`
- `left`
- `right`
- `jump`
- `roll`

The browser/runtime is an eye-and-hand transport layer only: capture pixels, deliver ordinary trusted inputs.

## Training allowances
- Public/reusable gameplay video may be used for visual/world-model pretraining.
- Weak/pseudo action labels may be inferred from visible motion, but must retain confidence values and must not be treated as exact labels.
- Our controlled Linux runs may supply exact action timestamps because we know which keys we send.
- Browser/game internals may be used for diagnostics during environment development, but not as features for the final evaluated policy.

## Environment-controller boundary
Menu/tutorial/death/restart automation is outside the gameplay policy. It must itself rely on pixels or ordinary UI interaction and must not leak privileged game state into the policy.

## Canonical offline dataset contract
- RGB, 15 fps, H.264 MP4, no audio.
- Automatically locate the temporally active gameplay viewport before normalization; stable browser chrome, borders, and sidebars are excluded when detectable.
- Preserve source gameplay orientation and geometry rather than stretch it:
  - landscape bucket: 640 x 360
  - portrait bucket: 360 x 640
- Training clip: 4.0 seconds / 60 frames.
- Default clip stride: 2.0 seconds.
- Preserve aspect ratio; pad rather than stretch.
- Every clip must carry source ID, source time range, detected crop/crop method, orientation, normalized dimensions, motion/QC metrics, and reuse status.

The pretraining encoder may consume both orientation buckets. The final closed-loop policy is evaluated only on the 640 x 360 live browser observation contract.

## Success criteria for Stages 1-3
1. This interface is frozen and versioned.
2. A source manifest contains reusable footage plus high-score and failure/collision discovery candidates with explicit provenance/reuse status.
3. An automated ingestion pipeline can produce canonical clips plus a machine-readable index and visual QC contact sheet from approved sources.

## Version
`pixel-policy-contract-v1.1` — corrected after validating the real browser viewport; frozen for the first video-pretraining experiment.
