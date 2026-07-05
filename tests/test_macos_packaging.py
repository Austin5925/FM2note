import importlib.util
import plistlib
from pathlib import Path
from types import SimpleNamespace


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


def test_submit_for_notarization_with_keychain_profile_does_not_need_password(
    tmp_path, monkeypatch
):
    module = _load_build_script()
    archive = tmp_path / "FM2note-macos.zip"
    calls = []

    monkeypatch.setattr(
        module,
        "run",
        lambda cmd, **kwargs: calls.append((cmd, kwargs)),
    )

    module.submit_for_notarization(
        archive,
        SimpleNamespace(
            notary_profile="fm2note-notary",
            apple_id="",
            team_id="",
            password="",
        ),
    )

    assert calls[0] == (
        [
            "xcrun",
            "notarytool",
            "submit",
            str(archive),
            "--wait",
            "--keychain-profile",
            "fm2note-notary",
        ],
        {
            "display_cmd": [
                "xcrun",
                "notarytool",
                "submit",
                str(archive),
                "--wait",
                "--keychain-profile",
                "fm2note-notary",
            ]
        },
    )


def test_notarize_rebuilds_release_zip_after_stapling(tmp_path, monkeypatch):
    module = _load_build_script()
    app = tmp_path / "FM2note.app"
    first_archive = tmp_path / "pre-staple.zip"
    final_archive = tmp_path / "post-staple.zip"
    zip_calls = []

    def fake_make_release_zip(app_path):
        zip_calls.append(app_path)
        return first_archive if len(zip_calls) == 1 else final_archive

    monkeypatch.setattr(module, "make_release_zip", fake_make_release_zip)
    monkeypatch.setattr(module, "submit_for_notarization", lambda artifact, args: None)
    monkeypatch.setattr(module, "staple_and_verify_app", lambda app_path: None)

    archive, dmg = module.notarize(
        app,
        SimpleNamespace(dmg=False),
        "Developer ID Application: Example (TEAMID)",
    )

    assert zip_calls == [app, app]
    assert archive == final_archive
    assert dmg is None


def test_make_dmg_creates_drag_install_layout(tmp_path, monkeypatch):
    module = _load_build_script()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    app = tmp_path / "dist" / "FM2note.app"
    (app / "Contents").mkdir(parents=True)
    calls = []

    monkeypatch.setattr(
        module,
        "run",
        lambda cmd, **kwargs: calls.append((cmd, kwargs)),
    )

    dmg = module.make_dmg(app, "Developer ID Application: Example (TEAMID)")

    staging = tmp_path / "build" / "dmg" / "FM2note"
    assert (staging / "FM2note.app").is_dir()
    assert (staging / "Applications").is_symlink()
    assert (staging / "Applications").readlink() == Path("/Applications")
    assert dmg == tmp_path / "dist" / "FM2note-macos.dmg"
    assert calls[0][0] == [
        "hdiutil",
        "create",
        "-volname",
        "FM2note",
        "-srcfolder",
        str(staging),
        "-ov",
        "-format",
        "UDZO",
        str(dmg),
    ]
    assert calls[1][0] == [
        "codesign",
        "--force",
        "--timestamp",
        "--sign",
        "Developer ID Application: Example (TEAMID)",
        str(dmg),
    ]
