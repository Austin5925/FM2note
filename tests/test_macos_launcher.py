from pathlib import Path
from subprocess import CompletedProcess

from src import macos_launcher
from src.macos_service import BACKGROUND_DISABLED_MARKER


def test_prepare_home_sets_runtime_home(tmp_path, monkeypatch):
    monkeypatch.delenv("FM2NOTE_HOME", raising=False)
    monkeypatch.delenv("FM2NOTE_DESKTOP_APP", raising=False)
    monkeypatch.chdir(Path.cwd())

    home = tmp_path / "FM2note Home"
    resolved = macos_launcher.prepare_home(home)

    assert resolved == home.resolve()
    assert Path.cwd() == home.resolve()
    assert home.exists()
    assert macos_launcher.os.environ["FM2NOTE_HOME"] == str(home.resolve())
    assert macos_launcher.os.environ["FM2NOTE_DESKTOP_APP"] == "1"


def test_prepare_home_command_mode_clears_desktop_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(Path.cwd())
    monkeypatch.setenv("FM2NOTE_DESKTOP_APP", "1")

    home = tmp_path / "FM2note Home"
    resolved = macos_launcher.prepare_home(home, desktop_app=False)

    assert resolved == home.resolve()
    assert "FM2NOTE_DESKTOP_APP" not in macos_launcher.os.environ


def test_app_args_allows_port_override(monkeypatch):
    monkeypatch.setenv("FM2NOTE_PORT", "7979")

    assert macos_launcher.app_args() == ["app", "--port", "7979"]


def test_cli_args_from_argv_strips_finder_and_compat_wrappers():
    assert macos_launcher.cli_args_from_argv(["-psn_0_12345"]) == []
    assert macos_launcher.cli_args_from_argv(["main.py", "serve"]) == ["serve"]
    assert macos_launcher.cli_args_from_argv(["-m", "main", "run-once"]) == ["run-once"]


def test_main_routes_subcommands_without_opening_desktop_window(tmp_path, monkeypatch):
    desktop_modes: list[bool] = []
    homes: list[Path | None] = []
    cli_calls: list[list[str]] = []

    def fake_prepare_home(home=None, *, desktop_app=True):
        homes.append(home)
        desktop_modes.append(desktop_app)
        return tmp_path

    def fake_cli_main(*, args, prog_name, standalone_mode):
        cli_calls.append(args)

    import main

    monkeypatch.delenv("FM2NOTE_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(macos_launcher.sys, "argv", ["FM2note", "run-once"])
    monkeypatch.setattr(macos_launcher, "prepare_home", fake_prepare_home)
    monkeypatch.setattr(macos_launcher, "apply_bundled_profile", lambda home: [])
    monkeypatch.setattr(macos_launcher, "ensure_initialized", lambda home: None)
    monkeypatch.setattr(main.cli, "main", fake_cli_main)

    macos_launcher.main()

    assert homes == [tmp_path]
    assert desktop_modes == [False]
    assert cli_calls == [["run-once"]]


def test_main_routes_subcommands_respect_env_home(tmp_path, monkeypatch):
    homes: list[Path | None] = []
    cli_calls: list[list[str]] = []

    def fake_prepare_home(home=None, *, desktop_app=True):
        homes.append(home)
        return tmp_path

    def fake_cli_main(*, args, prog_name, standalone_mode):
        cli_calls.append(args)

    import main

    monkeypatch.setenv("FM2NOTE_HOME", str(tmp_path / "explicit-home"))
    monkeypatch.setattr(macos_launcher.sys, "argv", ["FM2note", "serve"])
    monkeypatch.setattr(macos_launcher, "prepare_home", fake_prepare_home)
    monkeypatch.setattr(macos_launcher, "apply_bundled_profile", lambda home: [])
    monkeypatch.setattr(macos_launcher, "ensure_initialized", lambda home: None)
    monkeypatch.setattr(main.cli, "main", fake_cli_main)

    macos_launcher.main()

    assert homes == [None]
    assert cli_calls == [["serve"]]


def test_main_starts_background_service_for_desktop_launch(tmp_path, monkeypatch):
    desktop_modes: list[bool] = []
    ensured: list[Path] = []
    cli_calls: list[list[str]] = []

    def fake_prepare_home(home=None, *, desktop_app=True):
        desktop_modes.append(desktop_app)
        return tmp_path

    def fake_cli_main(*, args, prog_name, standalone_mode):
        cli_calls.append(args)

    import main

    monkeypatch.setattr(macos_launcher.sys, "argv", ["FM2note"])
    monkeypatch.setattr(macos_launcher, "prepare_home", fake_prepare_home)
    monkeypatch.setattr(macos_launcher, "apply_bundled_profile", lambda home: [])
    monkeypatch.setattr(macos_launcher, "ensure_initialized", lambda home: None)
    monkeypatch.setattr(
        macos_launcher, "ensure_background_service", lambda home: ensured.append(home)
    )
    monkeypatch.setattr(main.cli, "main", fake_cli_main)

    macos_launcher.main()

    assert desktop_modes == [True]
    assert ensured == [tmp_path]
    assert cli_calls == [["app"]]


def test_ensure_background_service_skips_when_user_disabled(tmp_path, monkeypatch):
    (tmp_path / BACKGROUND_DISABLED_MARKER).write_text("disabled\n")
    monkeypatch.setattr(macos_launcher.platform, "system", lambda: "Darwin")

    result = macos_launcher.ensure_background_service(tmp_path)

    assert result == {"ok": True, "skipped": "disabled-by-user"}


def test_ensure_background_service_skips_when_current_service_running(tmp_path, monkeypatch):
    monkeypatch.setattr(macos_launcher.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        macos_launcher,
        "macos_status",
        lambda: {"running": True, "installed": True},
    )
    monkeypatch.setattr(
        macos_launcher, "background_service_args", lambda: ["/App/FM2note", "serve"]
    )
    monkeypatch.setattr(macos_launcher, "launchd_plist_matches", lambda args, home: True)

    result = macos_launcher.ensure_background_service(tmp_path)

    assert result == {"ok": True, "skipped": "already-running"}


def test_ensure_background_service_installs_when_missing_or_stale(tmp_path, monkeypatch):
    calls: list[tuple[list[str], str]] = []
    monkeypatch.setattr(macos_launcher.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        macos_launcher, "macos_status", lambda: {"running": False, "installed": False}
    )
    monkeypatch.setattr(macos_launcher, "self_cli_command", lambda sub: ["/App/FM2note", sub])

    def fake_run(cmd, *, cwd, capture_output, text, timeout, check):
        calls.append((cmd, cwd))
        return CompletedProcess(cmd, 0, stdout="installed\n", stderr="")

    monkeypatch.setattr(macos_launcher.subprocess, "run", fake_run)

    result = macos_launcher.ensure_background_service(tmp_path)

    assert result["ok"] is True
    assert calls == [(["/App/FM2note", "install-service"], str(tmp_path.resolve()))]


def test_ensure_initialized_runs_init_when_files_missing(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_main(*, args, prog_name, standalone_mode):
        calls.append(args)
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "config.yaml").write_text("vault_path: /tmp/vault\n")
        (tmp_path / "config" / "subscriptions.yaml").write_text("podcasts: []\n")
        (tmp_path / ".env").write_text("export DASHSCOPE_API_KEY=\n")

    import main

    monkeypatch.setattr(main.cli, "main", fake_main)
    macos_launcher.ensure_initialized(tmp_path)

    assert calls == [["init"]]


def test_ensure_initialized_skips_existing_runtime_home(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text("vault_path: /tmp/vault\n")
    (tmp_path / "config" / "subscriptions.yaml").write_text("podcasts: []\n")
    (tmp_path / ".env").write_text("export DASHSCOPE_API_KEY=\n")

    import main

    def fail_main(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("init should not run")

    monkeypatch.setattr(main.cli, "main", fail_main)
    macos_launcher.ensure_initialized(tmp_path)


def test_apply_bundled_profile_copies_missing_files_once(tmp_path):
    profile = tmp_path / "profile"
    (profile / "config").mkdir(parents=True)
    (profile / "config" / "config.yaml").write_text("vault_path: /girlfriend\n")
    (profile / "config" / "subscriptions.yaml").write_text("podcasts: []\n")
    (profile / ".env").write_text("export DASHSCOPE_API_KEY=\n")
    home = tmp_path / "home"
    home.mkdir()

    copied = macos_launcher.apply_bundled_profile(home, profile)

    assert [p.as_posix() for p in copied] == [
        "config/config.yaml",
        "config/subscriptions.yaml",
        ".env",
    ]
    assert (home / "config" / "config.yaml").read_text() == "vault_path: /girlfriend\n"
    assert (home / macos_launcher.PROFILE_MARKER).exists()

    (home / "config" / "config.yaml").write_text("vault_path: /edited\n")
    copied_again = macos_launcher.apply_bundled_profile(home, profile)

    assert copied_again == []
    assert (home / "config" / "config.yaml").read_text() == "vault_path: /edited\n"


def test_apply_bundled_profile_does_not_overwrite_existing_files(tmp_path):
    profile = tmp_path / "profile"
    (profile / "config").mkdir(parents=True)
    (profile / "config" / "config.yaml").write_text("vault_path: /bundled\n")
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    (home / "config" / "config.yaml").write_text("vault_path: /existing\n")

    copied = macos_launcher.apply_bundled_profile(home, profile)

    assert copied == []
    assert (home / "config" / "config.yaml").read_text() == "vault_path: /existing\n"
