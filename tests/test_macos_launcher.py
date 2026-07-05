from pathlib import Path

from src import macos_launcher


def test_prepare_home_sets_runtime_home(tmp_path, monkeypatch):
    monkeypatch.delenv("FM2NOTE_HOME", raising=False)
    monkeypatch.chdir(Path.cwd())

    home = tmp_path / "FM2note Home"
    resolved = macos_launcher.prepare_home(home)

    assert resolved == home.resolve()
    assert Path.cwd() == home.resolve()
    assert home.exists()
    assert macos_launcher.os.environ["FM2NOTE_HOME"] == str(home.resolve())


def test_app_args_allows_port_override(monkeypatch):
    monkeypatch.setenv("FM2NOTE_PORT", "7979")

    assert macos_launcher.app_args() == ["app", "--port", "7979"]


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
