"""Tests for CLI commands: init, install-service, uninstall-service."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from main import cli


class TestInit:
    def test_init_creates_config_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init"],
            input="/tmp/test-vault\nfunasr\nPodcasts\n3\n",
        )
        assert result.exit_code == 0
        assert (tmp_path / "config" / "config.yaml").exists()
        assert (tmp_path / "config" / "subscriptions.yaml").exists()

        config_content = (tmp_path / "config" / "config.yaml").read_text()
        assert "/tmp/test-vault" in config_content
        assert "funasr" in config_content
        assert "Podcasts" in config_content

    def test_init_creates_env_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init"],
            input="/tmp/vault\nfunasr\nPodcasts\n3\n",
        )
        assert result.exit_code == 0
        assert (tmp_path / ".env").exists()

    def test_init_copies_example_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env_example = tmp_path / ".env.example"
        env_example.write_text("export DASHSCOPE_API_KEY=sk-xxx\n")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init"],
            input="/tmp/vault\nfunasr\nPodcasts\n3\n",
        )
        assert result.exit_code == 0
        env_content = (tmp_path / ".env").read_text()
        assert "DASHSCOPE_API_KEY" in env_content

    def test_init_skip_existing_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("vault_path: /old\n")
        runner = CliRunner()
        # Answer 'n' to overwrite prompt, then provide init inputs
        result = runner.invoke(
            cli,
            ["init"],
            input="n\nn\n/tmp/vault\nfunasr\nPodcasts\n3\n",
        )
        assert result.exit_code == 0
        # Original file should be unchanged
        assert "/old" in (config_dir / "config.yaml").read_text()

    def test_init_shows_next_steps(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init"],
            input="/tmp/vault\nfunasr\nPodcasts\n3\n",
        )
        assert "Next steps" in result.output
        assert "fm2note run-once" in result.output


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
        # Should contain the dynamically provided paths
        assert "/usr/bin/python3" in content
        assert str(tmp_path) in content
        assert "com.fm2note.serve" in content
        assert "RunAtLoad" in content

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
        assert "Interactive setup" in result.output
