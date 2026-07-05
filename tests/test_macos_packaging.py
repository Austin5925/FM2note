import importlib.util
import plistlib
from pathlib import Path


def _load_build_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_macos_app.py"
    spec = importlib.util.spec_from_file_location("build_macos_app", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_developer_id_identity():
    module = _load_build_script()
    output = """
      1) ABCDEF1234567890 "Apple Development: Austin Example (TEAMID)"
      2) 1234567890ABCDEF "Developer ID Application: Austin Example (TEAMID)"
         2 valid identities found
    """

    assert (
        module.parse_developer_id_identity(output)
        == "Developer ID Application: Austin Example (TEAMID)"
    )


def test_parse_developer_id_identity_returns_none_without_match():
    module = _load_build_script()

    assert module.parse_developer_id_identity("0 valid identities found") is None


def test_patch_info_plist_sets_bundle_versions(tmp_path, monkeypatch):
    module = _load_build_script()
    app = tmp_path / "FM2note.app"
    contents = app / "Contents"
    contents.mkdir(parents=True)
    plist_path = contents / "Info.plist"
    plist_path.write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.0.0"}))
    monkeypatch.setattr(module, "app_version", lambda: "9.8.7")

    module.patch_info_plist(app)

    info = plistlib.loads(plist_path.read_bytes())
    assert info["CFBundleShortVersionString"] == "9.8.7"
    assert info["CFBundleVersion"] == "9.8.7"


def test_run_logs_display_command_without_changing_real_command(monkeypatch, capsys):
    module = _load_build_script()
    calls = []

    def fake_run(cmd, *, cwd, check):
        calls.append((cmd, cwd, check))

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.run(
        ["xcrun", "notarytool", "submit", "--password", "real-secret"],
        display_cmd=["xcrun", "notarytool", "submit", "--password", "********"],
    )

    assert "+ xcrun notarytool submit --password ********" in capsys.readouterr().out
    assert calls == [
        (
            ["xcrun", "notarytool", "submit", "--password", "real-secret"],
            module.ROOT,
            True,
        )
    ]
