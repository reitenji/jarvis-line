import hashlib
import io

import pytest

from jarvis_line import kokoro_assets


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def asset_spec(payload: bytes) -> kokoro_assets.AssetSpec:
    return kokoro_assets.AssetSpec(
        name="asset.bin",
        url="https://example.invalid/asset.bin",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_official_manifest_pins_release_assets():
    assert kokoro_assets.OFFICIAL_RELEASE_URL.endswith("/model-files-v1.0")
    assert kokoro_assets.MODEL_LICENSE == "Apache-2.0"
    assert kokoro_assets.OFFICIAL_ASSETS["model"].size == 325_532_387
    assert kokoro_assets.OFFICIAL_ASSETS["model"].sha256 == (
        "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"
    )
    assert kokoro_assets.OFFICIAL_ASSETS["voices"].size == 28_214_398
    assert kokoro_assets.OFFICIAL_ASSETS["voices"].sha256 == (
        "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"
    )


def test_verify_asset_detects_hash_mismatch(tmp_path):
    payload = b"verified model"
    path = tmp_path / "asset.bin"
    path.write_bytes(payload)

    assert kokoro_assets.verify_asset(path, asset_spec(payload)) == (True, "verified")

    path.write_bytes(b"modified model")
    ok, reason = kokoro_assets.verify_asset(path, asset_spec(payload))
    assert ok is False
    assert "size mismatch" in reason or "sha256 mismatch" in reason


def test_download_verified_asset_replaces_only_after_verification(tmp_path):
    payload = b"downloaded model"
    destination = tmp_path / "asset.bin"

    result = kokoro_assets.download_verified_asset(
        asset_spec(payload),
        destination,
        opener=lambda _request, timeout: FakeResponse(payload),
    )

    assert result == "downloaded"
    assert destination.read_bytes() == payload
    assert list(tmp_path.glob("*.part-*")) == []


def test_download_verified_asset_preserves_existing_file_on_failure(tmp_path):
    payload = b"expected model"
    destination = tmp_path / "asset.bin"
    destination.write_bytes(b"existing custom model")

    with pytest.raises(ValueError, match="does not match"):
        kokoro_assets.download_verified_asset(
            asset_spec(payload),
            destination,
            opener=lambda _request, timeout: FakeResponse(b"tampered model"),
            force=True,
        )

    assert destination.read_bytes() == b"existing custom model"
    assert list(tmp_path.glob("*.part-*")) == []
