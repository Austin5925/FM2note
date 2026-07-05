#!/usr/bin/env python3
"""Build, sign, and optionally notarize the FM2note macOS desktop app."""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "FM2note"
DEFAULT_BUNDLE_ID = "com.fm2note.desktop"
EXCLUDED_MODULES = [
    "IPython",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "black",
    "gi",
    "ipykernel",
    "jupyter_client",
    "matplotlib",
    "mypy",
    "notebook",
    "numexpr",
    "pandas",
    "pyarrow",
    "pytest",
    "qtpy",
    "scipy",
    "sphinx",
    "sqlalchemy",
    "tkinter",
    "tornado",
    "webview.platforms.android",
    "webview.platforms.cef",
    "webview.platforms.edgechromium",
    "webview.platforms.gtk",
    "webview.platforms.mshtml",
    "webview.platforms.qt",
    "webview.platforms.win32",
    "webview.platforms.winforms",
    "zmq",
]


def run(
    cmd: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = True,
    display_cmd: list[str] | None = None,
) -> subprocess.CompletedProcess:
    print("+", " ".join(display_cmd or cmd))
    return subprocess.run(cmd, cwd=cwd, check=check)


def parse_developer_id_identity(output: str) -> str | None:
    """Extract the first Developer ID Application identity name from security output."""
    pattern = re.compile(r'"(Developer ID Application:[^"]+)"')
    match = pattern.search(output)
    return match.group(1) if match else None


def find_developer_id_identity() -> str | None:
    result = subprocess.run(
        ["security", "find-identity", "-p", "codesigning", "-v"],
        capture_output=True,
        text=True,
        check=False,
    )
    return parse_developer_id_identity(result.stdout)


def ensure_pyinstaller() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            "PyInstaller is not installed. Run:\n  python3.11 -m pip install -e '.[app,macos]'"
        )


def build_app(args: argparse.Namespace) -> Path:
    ensure_pyinstaller()
    dist_dir = ROOT / "dist"
    work_dir = ROOT / "build" / "pyinstaller"
    spec_dir = ROOT / "build"
    if args.clean:
        shutil.rmtree(dist_dir / args.name, ignore_errors=True)
        shutil.rmtree(dist_dir / f"{args.name}.app", ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name",
        args.name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--osx-bundle-identifier",
        args.bundle_id,
        "--collect-data",
        "src.web",
        "--collect-data",
        "src.templates",
        "--hidden-import",
        "webview.platforms.cocoa",
        "--hidden-import",
        "src.transcriber.funasr",
        "--hidden-import",
        "src.transcriber.tingwu",
        "--hidden-import",
        "src.transcriber.bailian",
        "--hidden-import",
        "src.transcriber.whisper_api",
        "--hidden-import",
        "src.summarizer.poe_client",
        "--hidden-import",
        "src.summarizer.openai_client",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespan.on",
    ]
    for module in EXCLUDED_MODULES:
        cmd.extend(["--exclude-module", module])
    if args.clean:
        cmd.append("--clean")
    if args.icon:
        cmd.extend(["--icon", str(Path(args.icon).expanduser())])
    cmd.append(str(ROOT / "src" / "macos_launcher.py"))

    run(cmd)
    app_path = dist_dir / f"{args.name}.app"
    if not app_path.exists():
        raise SystemExit(f"Build did not produce {app_path}")
    patch_info_plist(app_path)
    return app_path


def app_version() -> str:
    sys.path.insert(0, str(ROOT))
    from src.version import VERSION

    return VERSION


def patch_info_plist(app_path: Path) -> None:
    """Set app metadata that PyInstaller's CLI cannot express directly."""
    plist_path = app_path / "Contents" / "Info.plist"
    with plist_path.open("rb") as f:
        info = plistlib.load(f)
    version = app_version()
    info["CFBundleShortVersionString"] = version
    info["CFBundleVersion"] = version
    with plist_path.open("wb") as f:
        plistlib.dump(info, f)


def sign_app(app_path: Path, identity: str | None, *, no_sign: bool) -> str:
    """Sign the app and return the signing mode."""
    if no_sign:
        return "unsigned"

    if identity:
        run(
            [
                "codesign",
                "--force",
                "--deep",
                "--options",
                "runtime",
                "--timestamp",
                "--sign",
                identity,
                str(app_path),
            ]
        )
        return "developer-id"

    run(["codesign", "--force", "--deep", "--sign", "-", str(app_path)])
    return "ad-hoc"


def verify_signature(app_path: Path) -> None:
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_path)])
    # Gatekeeper rejects ad-hoc or non-notarized builds; keep this diagnostic non-fatal.
    run(["spctl", "-a", "-vv", str(app_path)], check=False)


def make_notary_zip(app_path: Path) -> Path:
    archive = app_path.parent / f"{app_path.stem}-macos.zip"
    if archive.exists():
        archive.unlink()
    run(["ditto", "-c", "-k", "--keepParent", str(app_path), str(archive)])
    return archive


def notarize(app_path: Path, args: argparse.Namespace) -> None:
    archive = make_notary_zip(app_path)
    cmd = ["xcrun", "notarytool", "submit", str(archive), "--wait"]
    display_cmd = cmd.copy()
    if args.notary_profile:
        cmd.extend(["--keychain-profile", args.notary_profile])
        display_cmd.extend(["--keychain-profile", args.notary_profile])
    else:
        apple_id = args.apple_id or os.environ.get("APPLE_ID", "")
        team_id = args.team_id or os.environ.get("APPLE_TEAM_ID", "")
        password = args.password or os.environ.get("APPLE_APP_SPECIFIC_PASSWORD", "")
        if not (apple_id and team_id and password):
            raise SystemExit(
                "Notarization needs --notary-profile or APPLE_ID, APPLE_TEAM_ID, "
                "and APPLE_APP_SPECIFIC_PASSWORD."
            )
        cmd.extend(["--apple-id", apple_id, "--team-id", team_id, "--password", password])
        display_cmd.extend(["--apple-id", apple_id, "--team-id", team_id, "--password", "********"])
    run(cmd, display_cmd=display_cmd)
    run(["xcrun", "stapler", "staple", str(app_path)])
    run(["spctl", "-a", "-vv", str(app_path)])


def resolve_identity(requested: str | None) -> str | None:
    if requested and requested != "auto":
        return requested
    return find_developer_id_identity()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=APP_NAME, help="App bundle name")
    parser.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID, help="macOS bundle id")
    parser.add_argument("--icon", default="", help="Optional .icns path")
    parser.add_argument(
        "--sign-identity", default=os.environ.get("APPLE_CODESIGN_IDENTITY", "auto")
    )
    parser.add_argument("--no-sign", action="store_true", help="Leave the app unsigned")
    parser.add_argument("--notarize", action="store_true", help="Submit signed app to Apple notary")
    parser.add_argument("--notary-profile", default=os.environ.get("APPLE_NOTARY_PROFILE", ""))
    parser.add_argument("--apple-id", default="")
    parser.add_argument("--team-id", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--clean", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    if platform.system() != "Darwin":
        raise SystemExit("macOS app packaging must run on macOS.")

    args = parse_args(argv)
    app_path = build_app(args)
    identity = None if args.no_sign else resolve_identity(args.sign_identity)
    signing_mode = sign_app(app_path, identity, no_sign=args.no_sign)
    verify_signature(app_path)

    if args.notarize:
        if signing_mode != "developer-id":
            raise SystemExit("Notarization requires a Developer ID Application signature.")
        notarize(app_path, args)

    print()
    print(f"Built: {app_path}")
    print(f"Signing: {signing_mode}")
    if signing_mode != "developer-id":
        print("Developer ID identity not found; install your certificate before notarizing.")


if __name__ == "__main__":
    main()
