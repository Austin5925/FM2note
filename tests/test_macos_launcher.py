from pathlib import Path

from src import macos_launcher


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
