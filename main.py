import asyncio
import os
import platform
import shutil
import sys
from pathlib import Path
from textwrap import dedent

import click
from loguru import logger

from src.version import VERSION

# --- launchd plist template (macOS) ---
LAUNCHD_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.fm2note.serve</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>main.py</string>
        <string>serve</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{workdir}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_env}</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{log_dir}/fm2note-stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{log_dir}/fm2note-stderr.log</string>
</dict>
</plist>
"""

# --- systemd unit template (Linux) ---
SYSTEMD_UNIT_TEMPLATE = """\
[Unit]
Description=FM2note Podcast-to-Notes Pipeline
After=network-online.target

[Service]
Type=simple
ExecStart={python} {workdir}/main.py serve
WorkingDirectory={workdir}
EnvironmentFile={workdir}/.env
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
"""


def _load_dotenv():
    """Auto-load .env file from working directory into os.environ.

    This ensures API keys are available even when launched by launchd/systemd
    (which don't source shell profiles). Only sets vars that are not already set.
    """
    env_path = Path(".env")
    if not env_path.exists():
        return
    for key, value in _parse_env_file(env_path).items():
        if key not in os.environ:
            os.environ[key] = value


@click.group()
@click.version_option(version=VERSION)
def cli():
    """FM2note — Podcast RSS → Obsidian notes automation pipeline"""
    _load_dotenv()


@cli.command()
@click.option("--config", "config_path", default="config/config.yaml", help="Config file path")
@click.option("--subs", "subs_path", default="config/subscriptions.yaml", help="Subscriptions path")
def run_once(config_path: str, subs_path: str):
    """Check all subscriptions and process new episodes once"""
    logger.info("FM2note v{} — run-once mode", VERSION)
    asyncio.run(_run_once(config_path, subs_path))


@cli.command()
@click.option("--config", "config_path", default="config/config.yaml", help="Config file path")
@click.option("--subs", "subs_path", default="config/subscriptions.yaml", help="Subscriptions path")
def serve(config_path: str, subs_path: str):
    """Start scheduled polling daemon"""
    logger.info("FM2note v{} — serve mode", VERSION)
    asyncio.run(_serve(config_path, subs_path))


@cli.command()
@click.argument("audio_url")
@click.option("--title", default=None, help="Note title (auto-detected from URL if omitted)")
@click.option("--podcast", "podcast_name", default="单独转录", help="Podcast name for folder")
@click.option("--config", "config_path", default="config/config.yaml", help="Config file path")
def transcribe(audio_url: str, title: str | None, podcast_name: str, config_path: str):
    """Transcribe a single audio URL and generate an Obsidian note"""
    logger.info("FM2note v{} — transcribe: {}", VERSION, audio_url)
    asyncio.run(_transcribe(audio_url, title, podcast_name, config_path))


@cli.command("retry-summaries")
@click.option("--config", "config_path", default="config/config.yaml", help="Config file path")
def retry_summaries(config_path: str):
    """Retry previously failed AI summaries"""
    logger.info("FM2note v{} — retry-summaries mode", VERSION)
    asyncio.run(_retry_summaries(config_path))


@cli.command()
@click.option("--port", default=7878, show_default=True, type=int, help="Bind port")
@click.option("--no-browser", is_flag=True, help="Do not auto-open the browser")
def web(port: int, no_browser: bool):
    """Launch the local Web UI.

    Always binds to 127.0.0.1 — exposing FM2note to a routable interface would
    create SSRF risk via the subscription/transcribe URL inputs and leak the
    settings UI (which can read/write API keys). Use a reverse proxy if you need
    LAN access.
    """
    import threading
    import webbrowser

    try:
        import uvicorn
    except ImportError:
        click.echo(
            "uvicorn 未安装。请重新安装：pip install --upgrade fm2note",
            err=True,
        )
        sys.exit(1)

    from src.web.app import create_app

    host = "127.0.0.1"
    app = create_app()
    if not no_browser:
        threading.Timer(
            1.5, lambda: webbrowser.open(f"http://{host}:{port}")
        ).start()
    logger.info("FM2note v{} — web UI at http://{}:{}", VERSION, host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command()
@click.option("--port", default=7878, show_default=True, type=int, help="Bind port")
def app(port: int):
    """Launch the Web UI inside a native desktop window (requires fm2note[app]).

    Same backend as ``fm2note web`` but wrapped in a PyWebView window so users
    don't need to switch to a browser tab. Closing the window stops the server.
    Falls back with a helpful message if pywebview isn't installed.
    """
    try:
        import webview
    except ImportError:
        click.echo(
            "pywebview 未安装。运行：\n"
            "  pip install --upgrade 'fm2note[app]'\n"
            "或继续用 fm2note web（浏览器模式）。",
            err=True,
        )
        sys.exit(1)

    try:
        import uvicorn
    except ImportError:
        click.echo("uvicorn 未安装。请重新安装 fm2note。", err=True)
        sys.exit(1)

    import threading
    import time
    import urllib.request

    from src.web.app import create_app

    host = "127.0.0.1"
    fastapi_app = create_app()

    server_config = uvicorn.Config(fastapi_app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(server_config)

    def _run_server():
        server.run()

    t = threading.Thread(target=_run_server, daemon=True)
    t.start()

    # Wait until the server is ready (max ~6s). Abort with a clear error if it
    # never comes up — opening a window onto a dead server is worse than failing fast.
    ready = False
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=0.3):
                ready = True
                break
        except Exception:
            time.sleep(0.2)
    if not ready:
        click.echo(
            f"启动失败：等待 http://{host}:{port}/healthz 超时（6s）。"
            "可能是端口被占用，请用 --port 换一个。",
            err=True,
        )
        sys.exit(1)

    logger.info("FM2note v{} — desktop app at http://{}:{}", VERSION, host, port)
    webview.create_window(
        "FM2note",
        f"http://{host}:{port}",
        width=900,
        height=900,
        min_size=(700, 700),
    )
    webview.start()
    # Window closed → shut down uvicorn. The thread is a daemon, so even if join
    # times out the OS will release the socket on process exit.
    server.should_exit = True
    t.join(timeout=3)
    if t.is_alive():
        logger.warning("uvicorn 关停超时；进程退出时由内核回收端口")


@cli.command("install-shortcut")
@click.option("--dir", "target_dir", default=None, help="Where to put the shortcut (default: Desktop)")
@click.option("--mode", type=click.Choice(["app", "web"]), default="app", help="Use desktop app window (default) or browser tab")
def install_shortcut(target_dir: str | None, mode: str):
    """Drop a double-clickable launcher on the Desktop (macOS) or HOME (Linux).

    Default mode is ``app`` (PyWebView desktop window). The generated launcher
    tries ``fm2note app`` first and falls back to ``fm2note web`` if PyWebView
    isn't installed.
    """
    import shlex

    if platform.system() == "Darwin":
        target = Path(target_dir).expanduser() if target_dir else Path.home() / "Desktop"
        shortcut_path = target / "FM2note.command"
        workdir_q = shlex.quote(str(Path.cwd().resolve()))  # safe even if path has " or $
        if mode == "app":
            body = dedent(f"""\
                #!/bin/bash
                # FM2note launcher (auto-generated)
                cd {workdir_q} 2>/dev/null || cd "$HOME"
                # Prefer desktop window if pywebview is actually importable;
                # `--help` would succeed even when pywebview is missing, so probe by import.
                if command -v python3 >/dev/null 2>&1 && python3 -c 'import webview' >/dev/null 2>&1; then
                  exec fm2note app
                else
                  exec fm2note web
                fi
            """)
        else:
            body = dedent(f"""\
                #!/bin/bash
                cd {workdir_q} 2>/dev/null || cd "$HOME"
                exec fm2note web
            """)
        shortcut_path.write_text(body, encoding="utf-8")
        shortcut_path.chmod(0o755)
        click.echo(f"  Created {shortcut_path}")
        click.echo(
            "  首次双击若被 macOS 拦截，右键 → 打开 → 确认即可（仅需一次）"
        )
    elif platform.system() == "Linux":
        target = Path(target_dir).expanduser() if target_dir else Path.home()
        shortcut_path = target / "fm2note.sh"
        workdir_q = shlex.quote(str(Path.cwd().resolve()))
        shortcut_path.write_text(
            dedent(f"""\
                #!/bin/bash
                cd {workdir_q} 2>/dev/null || cd "$HOME"
                exec fm2note web
            """),
            encoding="utf-8",
        )
        shortcut_path.chmod(0o755)
        click.echo(f"  Created {shortcut_path}")
    else:
        click.echo("install-shortcut: unsupported platform", err=True)
        sys.exit(1)


@cli.command()
def init():
    """Interactive setup — generate config and subscription files"""
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)

    config_path = config_dir / "config.yaml"
    subs_path = config_dir / "subscriptions.yaml"

    if config_path.exists() and not click.confirm(
        f"{config_path} already exists. Overwrite?", default=False
    ):
        click.echo("Skipping config.yaml")
        config_path = None

    if subs_path.exists() and not click.confirm(
        f"{subs_path} already exists. Overwrite?", default=False
    ):
        click.echo("Skipping subscriptions.yaml")
        subs_path = None

    # Gather settings
    default_vault = _detect_obsidian_vault()
    vault_path = click.prompt("Obsidian vault path", default=default_vault or "", type=str)
    asr_engine = click.prompt(
        "ASR engine",
        type=click.Choice(["funasr", "paraformer", "tingwu", "whisper_api"]),
        default="funasr",
    )
    podcast_dir = click.prompt("Podcast subdirectory in vault", default="Podcasts")
    poll_hours = click.prompt("Polling interval (hours)", default=3, type=int)
    rsshub_url = click.prompt(
        "RSSHub base URL (leave empty if not using)",
        default="",
        show_default=False,
    )

    # Generate config.yaml
    if config_path:
        config_content = dedent(f"""\
            # FM2note Configuration (generated by fm2note init)
            vault_path: "{vault_path}"
            podcast_dir: "{podcast_dir}"
            poll_interval_hours: {poll_hours}
            asr_engine: "{asr_engine}"
            temp_dir: "./data/tmp"
            db_path: "./data/state.db"
            max_retries: 3
            summary_cooldown: 60
            log_level: "INFO"
        """)
        config_path.write_text(config_content, encoding="utf-8")
        click.echo(f"  Created {config_path}")

    # Generate subscriptions.yaml
    if subs_path:
        if rsshub_url:
            rsshub_url = rsshub_url.rstrip("/")
            subs_content = dedent(f"""\
                # FM2note Podcast Subscriptions (generated by fm2note init)
                # RSSHub: {rsshub_url}
                #
                # Xiaoyuzhou podcast ID: open podcast page, copy ID from URL
                #   https://www.xiaoyuzhoufm.com/podcast/PODCAST_ID

                podcasts:
                  # - name: "Your Podcast"
                  #   rss_url: "{rsshub_url}/xiaoyuzhou/podcast/YOUR_PODCAST_ID"
                  #   tags: ["example"]
            """)
        else:
            subs_content = dedent("""\
                # FM2note Podcast Subscriptions (generated by fm2note init)
                # Add your podcast RSS feeds below.
                # Standard RSS/Atom feeds work directly.
                # For Xiaoyuzhou podcasts, you need a self-hosted RSSHub.

                podcasts:
                  # - name: "Your Podcast"
                  #   rss_url: "https://example.com/feed.xml"
                  #   tags: ["example"]
            """)
        subs_path.write_text(subs_content, encoding="utf-8")
        click.echo(f"  Created {subs_path}")

    # Generate .env if not exists
    env_path = Path(".env")
    if not env_path.exists():
        env_example = Path(".env.example")
        if env_example.exists():
            shutil.copy(env_example, env_path)
            click.echo("  Created .env (from .env.example)")
        else:
            env_content = dedent(f"""\
                export DASHSCOPE_API_KEY=sk-xxx
                export OBSIDIAN_VAULT_PATH="{vault_path}"
                export LOG_LEVEL=INFO
            """)
            env_path.write_text(env_content, encoding="utf-8")
            click.echo("  Created .env")

    click.echo("\nNext steps:")
    click.echo("  1. Edit .env and add your API keys")
    click.echo("  2. Edit config/subscriptions.yaml and add your podcasts")
    click.echo("  3. Run: fm2note run-once")


@cli.command("install-service")
def install_service():
    """Install as a system service (launchd on macOS, systemd on Linux)"""
    system = platform.system()
    python_path = sys.executable
    workdir = str(Path.cwd())
    log_dir = str(Path.cwd() / "logs")

    # Ensure log directory exists
    Path(log_dir).mkdir(exist_ok=True)

    if system == "Darwin":
        _install_launchd(python_path, workdir, log_dir)
    elif system == "Linux":
        _install_systemd(python_path, workdir)
    else:
        click.echo(f"Unsupported platform: {system}. Manual setup required.", err=True)
        sys.exit(1)


def _install_launchd(python_path: str, workdir: str, log_dir: str):
    """Install macOS launchd service."""
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    plist_content = LAUNCHD_PLIST_TEMPLATE.format(
        python=python_path,
        workdir=workdir,
        log_dir=log_dir,
        path_env=path_env,
    )

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.fm2note.serve.plist"

    # API keys are NOT embedded in the plist — they stay in .env
    # The CLI auto-loads .env at startup via _load_dotenv()
    plist_path.write_text(plist_content, encoding="utf-8")
    click.echo(f"  Wrote {plist_path}")

    import subprocess

    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    click.echo("  Service installed and started. It will auto-start on login.")
    click.echo(f"  Logs: {log_dir}/fm2note-stdout.log")


def _install_systemd(python_path: str, workdir: str):
    """Install Linux systemd user service."""
    unit_content = SYSTEMD_UNIT_TEMPLATE.format(
        python=python_path,
        workdir=workdir,
    )

    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "fm2note.service"

    unit_path.write_text(unit_content, encoding="utf-8")
    click.echo(f"  Wrote {unit_path}")

    import subprocess

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "fm2note"], check=True)
    click.echo("  Service installed and started.")
    click.echo("  Check status: systemctl --user status fm2note")


@cli.command("uninstall-service")
def uninstall_service():
    """Uninstall the system service"""
    system = platform.system()

    if system == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.fm2note.serve.plist"
        if plist_path.exists():
            import subprocess

            subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            plist_path.unlink()
            click.echo("  Service uninstalled.")
        else:
            click.echo("  Service not found (already uninstalled?).")
    elif system == "Linux":
        unit_path = Path.home() / ".config" / "systemd" / "user" / "fm2note.service"
        if unit_path.exists():
            import subprocess

            subprocess.run(["systemctl", "--user", "disable", "--now", "fm2note"], check=False)
            unit_path.unlink()
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
            click.echo("  Service uninstalled.")
        else:
            click.echo("  Service not found (already uninstalled?).")
    else:
        click.echo(f"Unsupported platform: {system}", err=True)


def _parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse a .env file, extracting KEY=VALUE pairs."""
    env_vars = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Remove 'export ' prefix
        if line.startswith("export "):
            line = line[7:]
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if value and not value.startswith("sk-xxx") and value != "":
                env_vars[key] = value
    return env_vars


def _detect_obsidian_vaults() -> list[Path]:
    """Detect all Obsidian vault paths on macOS (iCloud + local)."""
    vaults: list[Path] = []
    if platform.system() != "Darwin":
        return vaults
    # iCloud Obsidian vaults
    icloud_base = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents"
    if icloud_base.is_dir():
        vaults.extend(d for d in sorted(icloud_base.iterdir()) if d.is_dir())
    # Local (non-iCloud) vaults — check Obsidian config
    obsidian_config = Path.home() / "Library/Application Support/obsidian/obsidian.json"
    if obsidian_config.exists():
        try:
            import json

            data = json.loads(obsidian_config.read_text(encoding="utf-8"))
            for _id, info in data.get("vaults", {}).items():
                p = Path(info.get("path", ""))
                if p.is_dir() and p not in vaults:
                    vaults.append(p)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return vaults


def _detect_obsidian_vault() -> str | None:
    """Auto-detect Obsidian vault; if multiple, let user pick."""
    vaults = _detect_obsidian_vaults()
    if not vaults:
        return None
    if len(vaults) == 1:
        return str(vaults[0])
    # Multiple vaults — show picker
    click.echo("\nDetected multiple Obsidian vaults:")
    for i, v in enumerate(vaults, 1):
        click.echo(f"  [{i}] {v.name}  ({v})")
    while True:
        choice = click.prompt("Choose vault number", type=int, default=1)
        if 1 <= choice <= len(vaults):
            return str(vaults[choice - 1])
        click.echo(f"  Please enter a number between 1 and {len(vaults)}")


def _create_md_generator(config):
    """Create MarkdownGenerator, using custom template path if configured."""
    from src.writer.markdown import MarkdownGenerator

    if config.template_path:
        tp = Path(config.template_path)
        return MarkdownGenerator(
            template_dir=str(tp.parent),
            template_name=tp.name,
        )
    return MarkdownGenerator()


def _create_summarizer(config):
    """Create summarizer using the factory (auto-detects provider from config)."""
    from src.summarizer.factory import create_summarizer

    return create_summarizer(config)


async def _run_once(config_path: str, subs_path: str):
    from src.config import load_config, load_subscriptions
    from src.downloader.audio import AudioDownloader
    from src.monitor.rss_checker import RSSChecker
    from src.monitor.state import StateManager
    from src.pipeline import Pipeline
    from src.transcriber.factory import create_transcriber
    from src.writer.obsidian import ObsidianWriter

    config = load_config(config_path)
    subscriptions = load_subscriptions(subs_path)

    state = StateManager(config.db_path)
    await state.init()

    try:
        rss_checker = RSSChecker(subscriptions, state)
        downloader = AudioDownloader(config.temp_dir)
        transcriber = create_transcriber(config)
        md_generator = _create_md_generator(config)
        writer = ObsidianWriter(config.vault_path, config.podcast_dir)
        summarizer = _create_summarizer(config)

        pipeline = Pipeline(
            config=config,
            rss_checker=rss_checker,
            downloader=downloader,
            transcriber=transcriber,
            md_generator=md_generator,
            writer=writer,
            state=state,
            summarizer=summarizer,
        )

        results = await pipeline.run_once()
        logger.info("Done: {} notes processed", len(results))
    finally:
        await state.close()


async def _serve(config_path: str, subs_path: str):
    from src.config import load_config, load_subscriptions
    from src.downloader.audio import AudioDownloader
    from src.monitor.rss_checker import RSSChecker
    from src.monitor.state import StateManager
    from src.pipeline import Pipeline
    from src.scheduler import FM2noteScheduler
    from src.transcriber.factory import create_transcriber
    from src.writer.obsidian import ObsidianWriter

    config = load_config(config_path)
    subscriptions = load_subscriptions(subs_path)

    state = StateManager(config.db_path)
    await state.init()

    try:
        rss_checker = RSSChecker(subscriptions, state)
        downloader = AudioDownloader(config.temp_dir)
        transcriber = create_transcriber(config)
        md_generator = _create_md_generator(config)
        writer = ObsidianWriter(config.vault_path, config.podcast_dir)
        summarizer = _create_summarizer(config)

        pipeline = Pipeline(
            config=config,
            rss_checker=rss_checker,
            downloader=downloader,
            transcriber=transcriber,
            md_generator=md_generator,
            writer=writer,
            state=state,
            summarizer=summarizer,
        )

        scheduler = FM2noteScheduler(pipeline, config)
        await scheduler.run_forever()
    finally:
        await state.close()




async def _transcribe(audio_url: str, title: str | None, podcast_name: str, config_path: str):
    from src.config import load_config
    from src.transcribe_flow import transcribe_single_url

    config = load_config(config_path)

    def _log_cb(stage: str, status: str, message: str) -> None:
        if status == "start":
            logger.info("[{}] {}", stage, message or "...")
        elif status == "done" and stage == "asr":
            logger.info("Transcription done: {}", message)
        elif status == "skipped":
            logger.debug("[{}] skipped: {}", stage, message)
        elif status == "error":
            logger.warning("[{}] error: {}", stage, message)

    outcome = await transcribe_single_url(
        audio_url,
        config,
        title=title,
        podcast_name=podcast_name,
        progress_callback=_log_cb,
    )
    logger.success("Note written: {}", outcome.note_path)


async def _retry_summaries(config_path: str):
    from src.config import load_config
    from src.summarizer.pending import insert_summary_into_note, load_all_pending, remove_pending

    config = load_config(config_path)
    summarizer = _create_summarizer(config)
    if not summarizer:
        logger.error("POE_API_KEY not configured, cannot retry summaries")
        return

    pending = load_all_pending()
    if not pending:
        logger.info("No pending summaries to retry")
        return

    logger.info("Found {} pending summaries", len(pending))
    success_count = 0
    fail_count = 0

    for item in pending:
        try:
            logger.info("Retrying summary: {}", item["title"])
            result = await summarizer.summarize(item["text"], item["title"])
            if insert_summary_into_note(item["note_path"], result):
                remove_pending(item["_filepath"])
                success_count += 1
                logger.success("Summary added: {}", item["title"])
            else:
                fail_count += 1
                logger.warning("Summary insert failed (note file issue): {}", item["title"])
        except Exception as e:
            fail_count += 1
            logger.warning("Summary retry failed: {} - {}: {}", item["title"], type(e).__name__, e)

    logger.info(
        "Retry complete: {} total, {} success, {} failed",
        len(pending),
        success_count,
        fail_count,
    )


if __name__ == "__main__":
    cli()
