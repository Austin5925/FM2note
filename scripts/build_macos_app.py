#!/usr/bin/env python3
"""Build, sign, and optionally notarize the FM2note macOS desktop app."""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "FM2note"
DEFAULT_BUNDLE_ID = "com.fm2note.desktop"
PROFILE_RESOURCE_DIR = "FM2noteProfile"
PROFILE_FILE_RELS = (
    Path("config/config.yaml"),
    Path("config/subscriptions.yaml"),
    Path(".env"),
)
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
DMG_WINDOW_SIZE = (560, 360)
DMG_APP_ICON_POS = (170, 180)
DMG_APPLICATIONS_ICON_POS = (390, 180)
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


def ensure_dmgbuild() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "dmgbuild", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            "dmgbuild is not installed. Run:\n  python3.11 -m pip install -e '.[app,macos]'"
        )


def env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUTHY_ENV_VALUES


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
    install_bundle_profile(
        app_path,
        args.profile_dir,
        allow_visible_profile=args.allow_visible_profile,
    )
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


def install_bundle_profile(
    app_path: Path,
    profile_dir_value: str,
    *,
    allow_visible_profile: bool = False,
) -> Path | None:
    """Copy an optional first-run profile into the app bundle resources."""
    target = app_path / "Contents" / "Resources" / PROFILE_RESOURCE_DIR
    shutil.rmtree(target, ignore_errors=True)
    if not profile_dir_value:
        return None

    profile_dir = Path(profile_dir_value).expanduser().resolve()
    if not profile_dir.is_dir():
        raise SystemExit(f"Profile directory does not exist: {profile_dir}")
    if not allow_visible_profile:
        raise SystemExit(
            "Refusing to bundle a first-run profile without explicit consent.\n"
            "Everything under --profile-dir is visible to Apple notarization and to anyone "
            "who receives the DMG/App bundle, including Obsidian paths, RSSHub URLs, API "
            "keys, tokens, and comments.\n"
            "If the profile contains only values you are willing to expose, rerun with "
            "--allow-visible-profile or FM2NOTE_ALLOW_VISIBLE_PROFILE=1."
        )

    copied: list[str] = []
    for rel in PROFILE_FILE_RELS:
        src = profile_dir / rel
        if not src.is_file():
            continue
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel.as_posix())

    if not copied:
        raise SystemExit(
            f"Profile directory has no supported files: {profile_dir}\n"
            "Expected any of: config/config.yaml, config/subscriptions.yaml, .env"
        )

    (target / "PROFILE.txt").write_text(
        "FM2note bundled first-run profile.\n"
        "These files are copied once into ~/Library/Application Support/FM2note "
        "only when the user has not created them yet.\n"
        f"Included: {', '.join(copied)}\n",
        encoding="utf-8",
    )
    return target


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


def sanitize_release_suffix(value: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip(".-_")
    return suffix.lower()


def release_stem(app_path: Path, release_suffix: str = "") -> str:
    suffix = sanitize_release_suffix(release_suffix)
    return f"{app_path.stem}-{suffix}-macos" if suffix else f"{app_path.stem}-macos"


def make_release_zip(app_path: Path, release_suffix: str = "") -> Path:
    archive = app_path.parent / f"{release_stem(app_path, release_suffix)}.zip"
    if archive.exists():
        archive.unlink()
    run(["ditto", "-c", "-k", "--keepParent", str(app_path), str(archive)])
    return archive


def _write_png(path: Path, width: int, height: int, pixels: list[bytearray]) -> None:
    """Write a small RGB PNG without adding another packaging dependency."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw_rows = b"".join(b"\x00" + bytes(row) for row in pixels)
    png = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(raw_rows, level=9)),
            chunk(b"IEND", b""),
        ]
    )
    path.write_bytes(png)


def _fill_rect(
    pixels: list[bytearray],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    height = len(pixels)
    width = len(pixels[0]) // 3 if pixels else 0
    for y in range(max(0, y0), min(height, y1)):
        row = pixels[y]
        for x in range(max(0, x0), min(width, x1)):
            row[x * 3 : x * 3 + 3] = bytes(color)


def _fill_right_triangle(
    pixels: list[bytearray],
    tip_x: int,
    mid_y: int,
    base_x: int,
    half_height: int,
    color: tuple[int, int, int],
) -> None:
    for y in range(mid_y - half_height, mid_y + half_height + 1):
        t = abs(y - mid_y) / max(half_height, 1)
        x_right = round(tip_x - (tip_x - base_x) * t)
        _fill_rect(pixels, base_x, y, x_right + 1, y + 1, color)


def write_dmg_background(path: Path) -> Path:
    """Create the DMG background with a visible install arrow."""
    width, height = DMG_WINDOW_SIZE
    background = (248, 250, 252)
    pixels = [bytearray(background * width) for _ in range(height)]

    # Soft shadow first, then the foreground arrow from FM2note.app to Applications.
    shadow = (203, 213, 225)
    arrow = (71, 85, 105)
    _fill_rect(pixels, 236, 176, 307, 191, shadow)
    _fill_right_triangle(pixels, 334, 183, 305, 28, shadow)
    _fill_rect(pixels, 236, 171, 307, 186, arrow)
    _fill_right_triangle(pixels, 334, 178, 305, 28, arrow)

    # A small center cutout makes the arrow read as a deliberate icon, not a divider.
    highlight = (226, 232, 240)
    _fill_rect(pixels, 252, 176, 292, 181, highlight)

    _write_png(path, width, height, pixels)
    return path


def make_dmg(app_path: Path, identity: str | None, release_suffix: str = "") -> Path:
    """Create a compressed drag-install DMG from the finalized app bundle."""
    ensure_dmgbuild()
    dmg_stem = release_stem(app_path, release_suffix)
    dmg_path = app_path.parent / f"{dmg_stem}.dmg"
    dmg_root = ROOT / "build" / "dmg"
    dmg_root.mkdir(parents=True, exist_ok=True)
    settings_path = dmg_root / f"{dmg_stem}.settings.py"
    background_path = write_dmg_background(dmg_root / f"{dmg_stem}-background.png")
    if dmg_path.exists():
        dmg_path.unlink()

    settings_path.write_text(
        "\n".join(
            [
                "format = 'UDZO'",
                "filesystem = 'HFS+'",
                "compression_level = 9",
                "default_view = 'icon-view'",
                "show_toolbar = False",
                "show_status_bar = False",
                "show_sidebar = False",
                f"background = {str(background_path)!r}",
                f"window_rect = ((200, 120), {DMG_WINDOW_SIZE!r})",
                "icon_size = 96",
                f"files = [({str(app_path)!r}, {app_path.name!r})]",
                "symlinks = {'Applications': '/Applications'}",
                f"icon_locations = {{{app_path.name!r}: {DMG_APP_ICON_POS!r}, "
                f"'Applications': {DMG_APPLICATIONS_ICON_POS!r}}}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    run(
        [
            sys.executable,
            "-m",
            "dmgbuild",
            "-s",
            str(settings_path),
            app_path.stem,
            str(dmg_path),
        ]
    )
    if identity:
        run(["codesign", "--force", "--timestamp", "--sign", identity, str(dmg_path)])
    return dmg_path


def submit_for_notarization(artifact: Path, args: argparse.Namespace) -> None:
    cmd = ["xcrun", "notarytool", "submit", str(artifact), "--wait"]
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


def staple_and_verify_app(app_path: Path) -> None:
    run(["xcrun", "stapler", "staple", str(app_path)])
    run(["xcrun", "stapler", "validate", str(app_path)])
    run(["spctl", "-a", "-vv", str(app_path)])


def staple_and_verify_dmg(dmg_path: Path) -> None:
    run(["xcrun", "stapler", "staple", str(dmg_path)])
    run(["xcrun", "stapler", "validate", str(dmg_path)])
    run(
        [
            "spctl",
            "-a",
            "-vv",
            "-t",
            "open",
            "--context",
            "context:primary-signature",
            str(dmg_path),
        ]
    )


def notarize(
    app_path: Path,
    args: argparse.Namespace,
    identity: str | None,
) -> tuple[Path, Path | None]:
    """Notarize and staple the app, then build finalized release archives."""
    archive = make_release_zip(app_path, args.release_suffix)
    submit_for_notarization(archive, args)
    staple_and_verify_app(app_path)
    archive = make_release_zip(app_path, args.release_suffix)

    dmg_path = None
    if args.dmg:
        dmg_path = make_dmg(app_path, identity, args.release_suffix)
        submit_for_notarization(dmg_path, args)
        staple_and_verify_dmg(dmg_path)
    return archive, dmg_path


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
    parser.add_argument("--dmg", action="store_true", help="Build a compressed drag-install DMG")
    parser.add_argument(
        "--profile-dir",
        default=os.environ.get("FM2NOTE_PROFILE_DIR", ""),
        help="Optional first-run profile directory copied into the app bundle",
    )
    parser.add_argument(
        "--allow-visible-profile",
        action="store_true",
        default=env_truthy("FM2NOTE_ALLOW_VISIBLE_PROFILE"),
        help=(
            "Confirm that all files copied from --profile-dir are intentionally visible "
            "inside the DMG/App bundle"
        ),
    )
    parser.add_argument(
        "--release-suffix",
        default=os.environ.get("FM2NOTE_RELEASE_SUFFIX", ""),
        help="Optional artifact suffix, e.g. girlfriend -> FM2note-girlfriend-macos.dmg",
    )
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
    archive_path = None
    dmg_path = None

    if args.notarize:
        if signing_mode != "developer-id":
            raise SystemExit("Notarization requires a Developer ID Application signature.")
        archive_path, dmg_path = notarize(app_path, args, identity)
    elif args.dmg:
        dmg_path = make_dmg(
            app_path,
            identity if signing_mode == "developer-id" else None,
            args.release_suffix,
        )

    print()
    print(f"Built: {app_path}")
    if archive_path:
        print(f"ZIP: {archive_path}")
    if dmg_path:
        print(f"DMG: {dmg_path}")
    print(f"Signing: {signing_mode}")
    if signing_mode != "developer-id":
        print("Developer ID identity not found; install your certificate before notarizing.")


if __name__ == "__main__":
    main()
