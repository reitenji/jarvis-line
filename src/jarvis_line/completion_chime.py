from __future__ import annotations

import io
import math
import struct
import wave
from functools import lru_cache


SAMPLE_RATE = 24_000
_DURATION_SECONDS = 0.36
_MASTER_AMPLITUDE = 0.12


def _tone(time_seconds: float, start: float, duration: float, frequency: float) -> float:
    local_time = time_seconds - start
    if local_time < 0 or local_time >= duration:
        return 0.0
    attack = min(1.0, local_time / 0.012)
    release = min(1.0, (duration - local_time) / 0.065)
    decay = math.exp(-2.4 * local_time / duration)
    return math.sin(2.0 * math.pi * frequency * local_time) * attack * release * decay


@lru_cache(maxsize=1)
def wav_bytes() -> bytes:
    frame_count = int(SAMPLE_RATE * _DURATION_SECONDS)
    frames = bytearray()
    for index in range(frame_count):
        time_seconds = index / SAMPLE_RATE
        signal = (
            0.72 * _tone(time_seconds, 0.0, 0.22, 523.25)
            + 0.72 * _tone(time_seconds, 0.095, 0.235, 659.25)
        )
        sample = max(-1.0, min(1.0, signal * _MASTER_AMPLITUDE))
        frames.extend(struct.pack("<h", round(sample * 32767)))

    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(frames)
    return output.getvalue()
