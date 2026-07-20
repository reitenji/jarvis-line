import io
import struct
import wave

from jarvis_line import completion_chime


def test_wav_bytes_is_short_mono_pcm():
    payload = completion_chime.wav_bytes()

    with wave.open(io.BytesIO(payload), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == completion_chime.SAMPLE_RATE
        assert 0.2 <= audio.getnframes() / audio.getframerate() < 0.5
        frames = audio.readframes(audio.getnframes())

    samples = [sample[0] for sample in struct.iter_unpack("<h", frames)]
    assert max(abs(sample) for sample in samples) <= int(32767 * 0.18)
    assert any(samples)


def test_wav_bytes_is_cached_and_deterministic():
    first = completion_chime.wav_bytes()
    second = completion_chime.wav_bytes()

    assert first is second
    assert first == second
