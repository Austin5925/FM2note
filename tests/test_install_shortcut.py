"""Tests for the install-shortcut command output safety."""

from __future__ import annotations

import platform
import shlex

import pytest
from click.testing import CliRunner

from main import cli


@pytest.mark.skipif(
    platform.system() != "Darwin",
    reason="install-shortcut macOS branch — Linux branch writes fm2note.sh instead",
)
class TestInstallShortcut:
    def test_app_mode_uses_safe_workdir_quoting(self, tmp_path, monkeypatch):
        """If CWD contains shell-special chars, the shortcut must still parse safely."""
        weird_dir = tmp_path / 'pa"th $with"weird"chars'
        weird_dir.mkdir()
        monkeypatch.chdir(weird_dir)

        target = tmp_path / "Desktop"
        target.mkdir()

        runner = CliRunner()
        result = runner.invoke(cli, ["install-shortcut", "--dir", str(target)])
        assert result.exit_code == 0
        shortcut = target / "FM2note.command"
        body = shortcut.read_text(encoding="utf-8")
        # The path appears via shlex.quote → single-quoted, with embedded ' escaped
        assert shlex.quote(str(weird_dir)) in body
        # No raw double-quoted interpolation that would be vulnerable
        assert f'cd "{weird_dir}"' not in body

    def test_app_mode_probes_import_not_help(self, tmp_path, monkeypatch):
        """Probe must actually `import webview`, not just call `--help`."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "Desktop"
        target.mkdir()

        runner = CliRunner()
        result = runner.invoke(cli, ["install-shortcut", "--dir", str(target)])
        assert result.exit_code == 0
        body = (target / "FM2note.command").read_text(encoding="utf-8")
        assert "import webview" in body
        # Old wrong probe should be gone
        assert "fm2note app --help" not in body

    def test_web_mode_skips_pywebview_probe(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "Desktop"
        target.mkdir()

        runner = CliRunner()
        result = runner.invoke(cli, ["install-shortcut", "--dir", str(target), "--mode", "web"])
        assert result.exit_code == 0
        body = (target / "FM2note.command").read_text(encoding="utf-8")
        assert "fm2note web" in body
        assert "import webview" not in body
        assert "fm2note app" not in body

    def test_shortcut_is_executable(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "Desktop"
        target.mkdir()
        runner = CliRunner()
        runner.invoke(cli, ["install-shortcut", "--dir", str(target)])
        shortcut = target / "FM2note.command"
        assert shortcut.exists()
        # owner has execute bit
        assert shortcut.stat().st_mode & 0o100

    def test_app_command_help_lists_in_cli(self):
        """`fm2note app --help` should be a known command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["app", "--help"])
        assert result.exit_code == 0
        assert "Launch the Web UI" in result.output
        assert "--port" in result.output
