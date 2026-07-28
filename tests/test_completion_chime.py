import io
import struct
import wave

from jarvis_line import completion_chime


def samples(payload):
    with wave.open(io.BytesIO(payload), "rb") as audio:
        frames = audio.readframes(audio.getnframes())
    return [sample[0] for sample in struct.iter_unpack("<h", frames)]


def test_wav_bytes_is_short_mono_pcm():
    payload = completion_chime.wav_bytes()

    with wave.open(io.BytesIO(payload), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == completion_chime.SAMPLE_RATE
        assert 0.2 <= audio.getnframes() / audio.getframerate() < 0.5
        frames = audio.readframes(audio.getnframes())

    decoded = [sample[0] for sample in struct.iter_unpack("<h", frames)]
    assert max(abs(sample) for sample in decoded) <= int(32767 * 0.18)
    assert any(decoded)


def test_wav_bytes_is_cached_and_deterministic():
    first = completion_chime.wav_bytes()
    second = completion_chime.wav_bytes()

    assert first is second
    assert first == second


def test_wav_bytes_scales_peak_amplitude():
    full_samples = samples(completion_chime.wav_bytes(1.0))
    half_samples = samples(completion_chime.wav_bytes(0.5))
    silent_samples = samples(completion_chime.wav_bytes(0.0))

    assert max(abs(sample) for sample in silent_samples) == 0
    ratio = max(abs(sample) for sample in half_samples) / max(
        abs(sample) for sample in full_samples
    )
    assert 0.49 <= ratio <= 0.51


def test_wav_bytes_normalizes_volume_before_caching():
    assert completion_chime.wav_bytes(-1.0) is completion_chime.wav_bytes(0.0)
    assert completion_chime.wav_bytes(2.0) is completion_chime.wav_bytes(1.0)
    assert completion_chime.wav_bytes("invalid") is completion_chime.wav_bytes(1.0)
    assert completion_chime.wav_bytes(float("nan")) is completion_chime.wav_bytes(1.0)
