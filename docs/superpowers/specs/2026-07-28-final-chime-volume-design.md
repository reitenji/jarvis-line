# Final Chime Volume

## Goal

Let users adjust the final completion chime independently from spoken output
without adding persistent audio assets, extra processes, or platform-specific
behavior.

## Considered Approaches

### Follow Speech Volume

Reuse `volume` for both speech and the final chime. This keeps configuration
small, but users cannot keep speech clear while making the short cue quieter.

### Relative Multiplier

Add a multiplier applied to speech volume. This preserves the relationship
between both sounds, but a value such as `0.6` is ambiguous because its audible
result also depends on the speech setting.

### Independent Absolute Level

Add a dedicated `final_chime_volume` value from `0.0` to `1.0`. This is the
selected approach because it is direct, predictable, and maps cleanly to a
percentage slider.

## Configuration

- Add `final_chime_volume` to the shared config contract and every backend
  capability.
- Accept numeric values from `0.0` through `1.0`, inclusive.
- Default to `1.0` so existing installations retain the current chime level.
- Reject booleans, non-numeric values, and out-of-range values in the CLI.
- Keep `final_chime_enabled` as the primary on/off control. A zero volume is
  valid but does not replace the explicit switch.

Example:

```console
jarvis-line config set final_chime_volume 0.6
```

## Playback

The completion-chime generator scales PCM samples before writing the temporary
WAV. Playback continues to use the existing cross-platform player at its
neutral level. Scaling the waveform instead of relying on player-specific
volume flags makes the setting effective on macOS, Windows, and Linux.

The generator clamps defensively, normalizes the value for cache keys, and
keeps a bounded in-memory cache of generated variants. The audio worker still
owns playback under the single global audio lock. It creates one temporary WAV,
plays it before final speech, and removes it in `finally`. No queue schema,
event protocol, additional process, or persistent audio file is introduced.

## macOS App

Add a **Final chime volume** slider immediately below the **Final chime**
switch under Speech > Events:

- display the value as `0%` through `100%`;
- use 5% steps;
- disable it when speech is disabled, speak mode is off, or the final chime is
  disabled;
- read and save `final_chime_volume` through `JarvisConfigDraft`;
- reject values outside `0.0...1.0` in draft validation.

The existing speech-volume slider remains independent.

## Error Handling

Malformed external config cannot crash playback. The runtime falls back to the
default chime volume and clamps the final value before generation. Existing
fail-open behavior remains: a chime generation or playback error is logged
without content and final speech continues.

## Verification

- Test config defaults, schema, backend capabilities, CLI validation, and
  effective-config merging.
- Test WAV validity, boundary clamping, silence at zero, and proportional peak
  amplitude.
- Test that the audio worker forwards the configured level without changing
  final-before-speech ordering or temporary-file cleanup.
- Test macOS draft default, load, validation, and save round trips.
- Run the full Python suite, smoke test, quick runtime soak, and macOS Swift
  tests.
