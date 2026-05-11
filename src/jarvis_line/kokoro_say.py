#!/usr/bin/env python3
import asyncio
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


CONFIG_PATH = Path.home() / ".codex" / "hooks" / "jarvis_line_config.json"
LEGACY_CONFIG_PATH = Path.home() / ".codex" / "hooks" / "kokoro_tts_config.json"
_KOKORO_DEPS = None


def kokoro_deps():
    global _KOKORO_DEPS
    if _KOKORO_DEPS is None:
        import numpy as np
        import sounddevice as sd
        import soundfile as sf
        from kokoro_onnx import Kokoro

        _KOKORO_DEPS = {"np": np, "sd": sd, "sf": sf, "Kokoro": Kokoro}
    return _KOKORO_DEPS


def Kokoro(*args, **kwargs):
    return kokoro_deps()["Kokoro"](*args, **kwargs)


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        try:
            return json.loads(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}


def parse_voice_mix(spec: str) -> list[tuple[str, float]]:
    items: list[tuple[str, float]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, weight_text = part.split(":", 1)
            weight = float(weight_text.strip())
        else:
            name = part
            weight = 1.0
        items.append((name.strip(), weight))
    if not items:
        raise ValueError("Voice mix is empty")
    return items


def build_voice_tensor(engine: Any, spec: str):
    np = kokoro_deps()["np"]
    mix = parse_voice_mix(spec)
    tensors = []
    weights = []
    for name, weight in mix:
        tensors.append(engine.get_voice_style(name))
        weights.append(weight)
    weight_array = np.array(weights, dtype=np.float32)
    weight_array = weight_array / weight_array.sum()
    stacked = np.stack(tensors)
    return np.tensordot(weight_array, stacked, axes=1).astype(np.float32)


def spawn_player(sound_path: Path, volume: float) -> None:
    volume = max(0.0, min(volume, 1.0))
    if sys.platform == "darwin":
        subprocess.run(
            ["afplay", "-v", f"{volume:.2f}", str(sound_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    if sys.platform.startswith("win"):
        escaped_path = str(sound_path).replace("'", "''")
        ps = (
            "$p=New-Object System.Media.SoundPlayer "
            f"'{escaped_path}';"
            "$p.PlaySync()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    if sys.platform.startswith("linux"):
        for command in (
            ["paplay", str(sound_path)],
            ["aplay", str(sound_path)],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(sound_path)],
        ):
            if shutil.which(command[0]):
                subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                return
    raise RuntimeError(f"Unsupported platform for playback: {sys.platform}")


def play_stream(engine: Any, text: str, voice, lang: str, speed: float, volume: float) -> dict[str, float | None]:
    deps = kokoro_deps()
    np = deps["np"]
    sd = deps["sd"]
    volume = max(0.0, min(volume, 1.0))
    started = time.perf_counter()

    async def _run() -> dict[str, float | None]:
        stream = None
        last_sample_rate = None
        first_chunk_ms = None
        try:
            async for chunk, sample_rate in engine.create_stream(text, voice=voice, lang=lang, speed=speed):
                if first_chunk_ms is None:
                    first_chunk_ms = (time.perf_counter() - started) * 1000
                if stream is None:
                    stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32")
                    stream.start()
                last_sample_rate = sample_rate
                data = np.ascontiguousarray(np.clip(chunk * volume, -1.0, 1.0).astype(np.float32))
                stream.write(data)

            if stream is not None and last_sample_rate:
                # Add a tiny fade-to-silence tail so the last phoneme does not feel clipped.
                tail_ms = 140
                fade_ms = 35
                tail_samples = max(1, int(last_sample_rate * (tail_ms / 1000.0)))
                fade_samples = max(1, int(last_sample_rate * (fade_ms / 1000.0)))
                tail = np.zeros(tail_samples, dtype=np.float32)
                fade = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
                tail[:fade_samples] = fade * 0.0005
                stream.write(tail)
        finally:
            if stream is not None:
                stream.stop()
                stream.close()
        return {"first_chunk_ms": first_chunk_ms}

    return asyncio.run(_run())


def warm_stream(engine: Any, text: str, voice, lang: str, speed: float) -> dict[str, float | None]:
    started = time.perf_counter()

    async def _run() -> dict[str, float | None]:
        stream = engine.create_stream(text, voice=voice, lang=lang, speed=speed)
        try:
            await anext(stream)
            return {"first_chunk_ms": (time.perf_counter() - started) * 1000}
        finally:
            close = getattr(stream, "aclose", None)
            if close:
                await close()

    return asyncio.run(_run())


def synthesize_to_file(
    engine: Any,
    text: str,
    voice,
    lang: str,
    speed: float,
    output_path: Path,
) -> Path:
    sf = kokoro_deps()["sf"]
    audio, sample_rate = engine.create(text, voice=voice, lang=lang, speed=speed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, audio, sample_rate)
    return output_path


def main() -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--voice", default=cfg.get("voice", "bm_george:70,bm_lewis:30"))
    parser.add_argument("--lang", default=cfg.get("lang", "en-gb"))
    parser.add_argument("--speed", type=float, default=float(cfg.get("speed", 0.95)))
    parser.add_argument("--volume", type=float, default=float(cfg.get("volume", 0.70)))
    parser.add_argument("--output")
    parser.add_argument("--play", action="store_true")
    parser.add_argument("--no-play", action="store_true")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--tempfile", action="store_true")
    parser.add_argument("--keep-file", action="store_true")
    args = parser.parse_args()

    model_path = Path(cfg.get("model_path", ""))
    voices_path = Path(cfg.get("voices_path", ""))
    if not model_path.exists() or not voices_path.exists():
        raise FileNotFoundError("Kokoro model files are missing; update kokoro_tts_config.json")

    engine = Kokoro(str(model_path), str(voices_path))
    voice = build_voice_tensor(engine, args.voice)
    should_play = args.play or (cfg.get("play_by_default", True) and not args.no_play)
    playback_mode = str(cfg.get("playback_mode", "stream")).strip().lower()
    if args.stream:
        playback_mode = "stream"
    if args.tempfile:
        playback_mode = "tempfile"

    temp_dir = Path(cfg.get("temp_dir", str(Path.home() / ".codex" / "tts" / "generated")))
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Explicit output files should always be rendered to disk.
    if args.output:
        out_path = Path(args.output).expanduser()
        synthesize_to_file(engine, args.text, voice, args.lang, args.speed, out_path)
        print(out_path)
        if should_play:
            spawn_player(out_path, args.volume)
        return 0

    if should_play and playback_mode == "stream":
        try:
            play_stream(engine, args.text, voice, args.lang, args.speed, args.volume)
            print("stream://played")
            return 0
        except Exception as exc:
            if str(cfg.get("fallback_playback_mode", "tempfile")).strip().lower() != "tempfile":
                raise
            print(f"stream-fallback://{exc.__class__.__name__}")

    filename = f"kokoro_{int(time.time() * 1000)}.wav"
    out_path = temp_dir / filename
    synthesize_to_file(engine, args.text, voice, args.lang, args.speed, out_path)
    print(out_path)
    if should_play:
        try:
            spawn_player(out_path, args.volume)
        finally:
            if not args.keep_file and cfg.get("delete_after_play", True):
                out_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
