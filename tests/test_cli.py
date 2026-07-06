"""Tests for CLI commands: init, install-service, uninstall-service."""

import os
import plistlib
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from main import cli


class TestInit:
    """v1.5.1: default is silent skeleton mode (no prompts). The old
    interactive prompt flow is preserved behind ``--interactive``."""

    def test_init_silent_creates_skeleton(self, tmp_path, monkeypatch):
        """No input needed — should generate defaults with auto-detected vault."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "config" / "config.yaml").exists()
        assert (tmp_path / "config" / "subscriptions.yaml").exists()
        config_content = (tmp_path / "config" / "config.yaml").read_text()
        assert "funasr" in config_content  # default
        assert "Podcasts" in config_content  # default

    def test_init_silent_creates_env_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".env").exists()
        env_content = (tmp_path / ".env").read_text()
        # v1.5.1 full template includes more than just DashScope
        assert "DASHSCOPE_API_KEY" in env_content
        assert "POE_API_KEY" in env_content

    def test_init_silent_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        """Silent mode is non-destructive — must NOT clobber existing config."""
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("vault_path: /pre-existing\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0, result.output
        assert "/pre-existing" in (config_dir / "config.yaml").read_text()

    def test_init_copies_example_env_when_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_example = tmp_path / ".env.example"
        env_example.write_text("export DASHSCOPE_API_KEY=sk-from-example\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0, result.output
        env_content = (tmp_path / ".env").read_text()
        assert "sk-from-example" in env_content

    def test_init_shows_gui_next_steps(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0, result.output
        assert "Next steps" in result.output
        # v1.5.1 next-steps point at the GUI, not the deprecated CLI
        assert "fm2note app" in result.output or "fm2note web" in result.output

    def test_init_interactive_uses_prompts(self, tmp_path, monkeypatch):
        """The old prompt flow still works behind --interactive."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init", "--interactive"],
            input="/tmp/typed-vault\nfunasr\nPodcasts\n3\n\n",
        )
        assert result.exit_code == 0, result.output
        config_content = (tmp_path / "config" / "config.yaml").read_text()
        assert "/tmp/typed-vault" in config_content

    def test_init_silent_multi_vault_does_not_block(self, tmp_path, monkeypatch):
        """v1.5.1 Code Review #4 regression: with multiple Obsidian vaults
        detected, silent init MUST auto-pick the first one instead of
        calling click.prompt — otherwise the silent flow hangs waiting on
        stdin that will never come."""
        monkeypatch.chdir(tmp_path)
        from unittest.mock import patch

        with patch(
            "main._detect_obsidian_vaults",
            return_value=[Path("/vault/a"), Path("/vault/b"), Path("/vault/c")],
        ):
            runner = CliRunner()
            # Pass NO input — if the prompt fires the runner will EOF and
            # exit non-zero. A passing run proves silent mode skipped the prompt.
            result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0, result.output
        # And the first vault was picked
        config_content = (tmp_path / "config" / "config.yaml").read_text()
        assert "/vault/a" in config_content


class TestInstallService:
    def test_install_service_macos(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "logs").mkdir()

        with (
            patch("platform.system", return_value="Darwin"),
            patch("main._install_launchd") as mock_launchd,
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["install-service"])
            assert result.exit_code == 0
            mock_launchd.assert_called_once()

    def test_install_service_linux(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "logs").mkdir()

        with (
            patch("platform.system", return_value="Linux"),
            patch("main._install_systemd") as mock_systemd,
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["install-service"])
            assert result.exit_code == 0
            mock_systemd.assert_called_once()

    def test_install_service_unsupported(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "logs").mkdir()

        with patch("platform.system", return_value="Windows"):
            runner = CliRunner()
            result = runner.invoke(cli, ["install-service"])
            assert result.exit_code != 0

    def test_launchd_plist_generation(self, tmp_path, monkeypatch):
        """Test that the launchd plist is generated with correct dynamic paths."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        (tmp_path / "Library" / "LaunchAgents").mkdir(parents=True)
        (tmp_path / "logs").mkdir()

        import main

        with patch("subprocess.run"):
            main._install_launchd(
                python_path="/usr/bin/python3",
                workdir=str(tmp_path),
                log_dir=str(tmp_path / "logs"),
            )

        plist_path = tmp_path / "Library" / "LaunchAgents" / "com.fm2note.serve.plist"
        assert plist_path.exists()
        content = plist_path.read_text()
        data = plistlib.loads(plist_path.read_bytes())
        # Should contain the dynamically provided paths
        assert "/usr/bin/python3" in content
        assert str(tmp_path) in content
        assert "com.fm2note.serve" in content
        assert "RunAtLoad" in content
        assert data["ProgramArguments"] == ["/usr/bin/python3", "main.py", "serve"]
        # API keys must NOT be embedded in plist
        assert "DASHSCOPE_API_KEY" not in content
        assert "POE_API_KEY" not in content
        assert "OPENAI_API_KEY" not in content

    def test_launchd_plist_for_frozen_app_runs_serve_not_desktop_window(
        self, tmp_path, monkeypatch
    ):
        """Packaged .app launchd entries must call the frozen executable in CLI mode."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        import main

        monkeypatch.setattr(main.sys, "frozen", True, raising=False)
        with patch("subprocess.run"):
            main._install_launchd(
                python_path="/Applications/FM2note.app/Contents/MacOS/FM2note",
                workdir=str(tmp_path),
                log_dir=str(tmp_path / "logs"),
            )

        plist_path = tmp_path / "Library" / "LaunchAgents" / "com.fm2note.serve.plist"
        data = plistlib.loads(plist_path.read_bytes())
        assert data["ProgramArguments"] == [
            "/Applications/FM2note.app/Contents/MacOS/FM2note",
            "serve",
        ]
        assert "main.py" not in plist_path.read_text()

    def test_systemd_unit_generation(self, tmp_path, monkeypatch):
        """Test that systemd unit file is generated with correct dynamic paths."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".config" / "systemd" / "user").mkdir(parents=True)

        import main

        with patch("subprocess.run"):
            main._install_systemd(
                python_path="/usr/bin/python3",
                workdir=str(tmp_path),
            )

        unit_path = tmp_path / ".config" / "systemd" / "user" / "fm2note.service"
        assert unit_path.exists()
        content = unit_path.read_text()
        assert "/usr/bin/python3" in content
        assert str(tmp_path) in content


class TestUninstallService:
    def test_uninstall_macos_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with patch("platform.system", return_value="Darwin"):
            runner = CliRunner()
            result = runner.invoke(cli, ["uninstall-service"])
            assert result.exit_code == 0
            assert "not found" in result.output

    def test_uninstall_linux_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with patch("platform.system", return_value="Linux"):
            runner = CliRunner()
            result = runner.invoke(cli, ["uninstall-service"])
            assert result.exit_code == 0
            assert "not found" in result.output


class TestLoadDotenv:
    def test_load_dotenv_sets_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TEST_FM2NOTE_KEY", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("export TEST_FM2NOTE_KEY=test-value\n")

        from main import _load_dotenv

        _load_dotenv()
        assert os.environ.get("TEST_FM2NOTE_KEY") == "test-value"
        # Cleanup
        monkeypatch.delenv("TEST_FM2NOTE_KEY", raising=False)

    def test_load_dotenv_does_not_override_existing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TEST_FM2NOTE_KEY", "original")
        env_file = tmp_path / ".env"
        env_file.write_text("export TEST_FM2NOTE_KEY=overridden\n")

        from main import _load_dotenv

        _load_dotenv()
        assert os.environ["TEST_FM2NOTE_KEY"] == "original"

    def test_load_dotenv_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from main import _load_dotenv

        _load_dotenv()  # should not raise


class TestParseEnvFile:
    def test_parse_env_file(self, tmp_path):
        from main import _parse_env_file

        env_file = tmp_path / ".env"
        env_file.write_text(
            "# comment\nexport DASHSCOPE_API_KEY=real-key\n"
            'export OBSIDIAN_VAULT_PATH="/Users/test/vault"\n'
            "export POE_API_KEY=\n"
            "export OPENAI_API_KEY=sk-xxx\n"
        )
        result = _parse_env_file(env_file)
        assert result["DASHSCOPE_API_KEY"] == "real-key"
        assert result["OBSIDIAN_VAULT_PATH"] == "/Users/test/vault"
        # Empty and placeholder values should be excluded
        assert "POE_API_KEY" not in result
        assert "OPENAI_API_KEY" not in result


class TestVersionFlag:
    def test_version(self):
        from src.version import VERSION

        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert VERSION in result.output


class TestHelpText:
    def test_main_help_is_english(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Podcast RSS" in result.output

    def test_run_once_help_is_english(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["run-once", "--help"])
        assert result.exit_code == 0
        assert "Check all subscriptions" in result.output

    def test_serve_help_is_english(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "scheduled polling" in result.output.lower()

    def test_transcribe_help_is_english(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["transcribe", "--help"])
        assert result.exit_code == 0
        assert "Transcribe" in result.output

    def test_init_help_is_english(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0
        # v1.5.1 renamed the command summary; check for a stable English phrase
        assert "skeleton config" in result.output or "Generate" in result.output
