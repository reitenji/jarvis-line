from scripts import verify_clean_install


def test_clean_environment_blocks_host_python_and_pip_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/host/python")
    monkeypatch.setenv("PYTHONHOME", "/host/home")
    monkeypatch.setenv("PIP_INDEX_URL", "https://user:secret@example.invalid/simple")
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://example.invalid/extra")
    monkeypatch.setenv("PIP_CONFIG_FILE", "/host/pip.conf")
    monkeypatch.setenv("GH_TOKEN", "github-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("TMPDIR", "/host/tmp")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = verify_clean_install.clean_environment(tmp_path)

    assert env["PATH"] == "/usr/bin"
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert "PIP_INDEX_URL" not in env
    assert "PIP_EXTRA_INDEX_URL" not in env
    assert "GH_TOKEN" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert env["PIP_CONFIG_FILE"] == verify_clean_install.os.devnull
    assert env["PIP_NO_INDEX"] == "1"
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["TMPDIR"] == str(tmp_path / "tmp")
    assert env["TMP"] == str(tmp_path / "tmp")
    assert env["TEMP"] == str(tmp_path / "tmp")
    assert env["APPDATA"].startswith(str(tmp_path))
    assert env["LOCALAPPDATA"].startswith(str(tmp_path))
