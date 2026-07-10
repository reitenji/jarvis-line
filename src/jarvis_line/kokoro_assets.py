from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


OFFICIAL_SOURCE_URL = "https://github.com/thewh1teagle/kokoro-onnx"
OFFICIAL_RELEASE_URL = f"{OFFICIAL_SOURCE_URL}/releases/tag/model-files-v1.0"
MODEL_LICENSE = "Apache-2.0"


@dataclass(frozen=True)
class AssetSpec:
    name: str
    url: str
    size: int
    sha256: str


OFFICIAL_ASSETS = {
    "model": AssetSpec(
        name="kokoro-v1.0.onnx",
        url=(
            f"{OFFICIAL_SOURCE_URL}/releases/download/model-files-v1.0/"
            "kokoro-v1.0.onnx"
        ),
        size=325_532_387,
        sha256="7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    ),
    "voices": AssetSpec(
        name="voices-v1.0.bin",
        url=(
            f"{OFFICIAL_SOURCE_URL}/releases/download/model-files-v1.0/"
            "voices-v1.0.bin"
        ),
        size=28_214_398,
        sha256="bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    ),
}


def verify_asset(path: Path, spec: AssetSpec) -> tuple[bool, str]:
    path = Path(path)
    if not path.is_file():
        return False, "missing"
    actual_size = path.stat().st_size
    if actual_size != spec.size:
        return False, f"size mismatch: expected {spec.size}, got {actual_size}"

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_hash = digest.hexdigest()
    if actual_hash != spec.sha256:
        return False, f"sha256 mismatch: expected {spec.sha256}, got {actual_hash}"
    return True, "verified"


def download_verified_asset(
    spec: AssetSpec,
    destination: Path,
    *,
    opener: Callable = urllib.request.urlopen,
    force: bool = False,
    timeout: int = 120,
) -> str:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        verified, reason = verify_asset(destination, spec)
        if verified:
            return "already verified"
        if not force:
            raise FileExistsError(
                f"{destination} does not match the pinned official asset ({reason}); "
                "rerun with --force to replace it"
            )

    request = urllib.request.Request(
        spec.url,
        headers={"User-Agent": "Jarvis-Line-Kokoro-Installer"},
    )
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f"{destination.name}.part-",
            dir=destination.parent,
            delete=False,
        ) as output:
            temp_path = Path(output.name)
            downloaded = 0
            with opener(request, timeout=timeout) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > spec.size:
                        raise ValueError(
                            f"downloaded {spec.name} exceeds pinned size {spec.size}"
                        )
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

        verified, reason = verify_asset(temp_path, spec)
        if not verified:
            raise ValueError(f"downloaded {spec.name} does not match pinned metadata: {reason}")
        os.replace(temp_path, destination)
        temp_path = None
        return "downloaded"
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
