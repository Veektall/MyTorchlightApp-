# Subway Surfers Pixel-Only Policy Contract

## Goal
Build an agent that plays the official Subway Surfers game from the same visual evidence available to a human player.

## Evaluation interface

**Input**
- Only rendered RGB game pixels.
- Canonical observation: 8 consecutive RGB frames sampled from a 15 fps stream.
- Canonical frame size: 360 x 640 pixels (width x height).
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

## Canonical dataset contract
- Video: RGB, 360x640, 15 fps, H.264 MP4, no audio.
- Training clip: 4.0 seconds / 60 frames.
- Default clip stride: 2.0 seconds.
- Preserve aspect ratio; pad rather than stretch.
- Remove stable black borders when detected.
- Every clip must carry source ID, source time range, crop, motion/QC metrics, and reuse status.

## Success criteria for Stages 1-3
1. This interface is frozen and versioned.
2. A source manifest contains a mix of long competent play, high-score candidates, and failure/collision candidates.
3. An automated ingestion pipeline can produce canonical clips plus a machine-readable index and visual QC contact sheet from approved sources.

## Version
`pixel-policy-contract-v1` — frozen for the first video-pretraining experiment.
