# Changelog

All notable changes to FM2note will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned (v1.2.4)
- Generic RSS/Atom feed support (not just Xiaoyuzhou via RSSHub)
- Customizable note templates (configurable path and labels)
- Enhanced `fm2note init` with RSSHub URL prompt and vault auto-detection

### Planned (v1.2.5)
- Summarizer Protocol abstraction (pluggable LLM backends)
- OpenAI-compatible summarizer (GPT-4o, DeepSeek, Groq, Ollama)
- Summarizer factory with auto-detection
- PyPI publication

## [1.2.2] - 2025-06-15

### Added
- `fm2note init` interactive setup command
- `fm2note install-service` / `uninstall-service` with dynamic path generation
- systemd support for Linux service installation
- GitHub Actions CI (lint + test on Python 3.11/3.12/3.13)
- PyPI packaging support (`pip install fm2note`)
- MIT LICENSE file
- CHANGELOG.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md
- Example config files (`config.example.yaml`, `subscriptions.example.yaml`)

### Changed
- CLI help text switched from Chinese to English
- Error messages in config.py switched to English with helpful hints
- pyproject.toml rewritten with full PEP 621 metadata and build-system
- Makefile: replaced private `deploy` target with `build`/`clean`
- docker-compose.yaml: RSSHub port bound to 127.0.0.1 (use Nginx reverse proxy)
- launchd plist no longer hardcodes user paths (generated dynamically)

### Removed
- Hardcoded `<USER_HOME>/...` paths in scripts
- Hardcoded private RSSHub server IP in subscriptions
- Private server `deploy` target from Makefile

### Tests
- 170 tests passing (up from 149), 82% coverage

## [1.2.1] - 2025-06-01

### Changed
- `podcast_dir` renamed to `10_Podcasts`
- Fixed launchd service configuration

## [1.2.0] - 2025-05-01

### Added
- Poe API rate limiting (configurable cooldown)
- Summary failure caching with `retry-summaries` command
- Pending summary retry mechanism

## [1.1.0] - 2025-04-01

### Added
- FunASR and Paraformer ASR engines (DashScope SDK)
- Poe API integration for AI summaries (GPT-5.4)
- Cost-optimized two-step pipeline: ASR + LLM summary
- Usage guide documentation

### Changed
- Default ASR engine changed from TingWu to FunASR

## [1.0.0] - 2025-03-01

### Added
- Production-ready release
- 5-episode real-world validation (2682-3798 chars, 0 failures)
- Complete deployment documentation
- Docker three-container orchestration (fm2note + RSSHub + Redis)
- 107 test cases passing

## [0.5.2] - 2025-02-15

### Changed
- Documentation alignment (CLAUDE.md/README/.env.example)
- Config reset to Docker defaults
- docker-compose: added config volume mount, removed RSSHub public port

### Removed
- Development docs from git tracking (research/plan/test/docs)

## [0.5.1] - 2025-02-10

### Changed
- Migrated TingWu to DashScope SDK (`dashscope.multimodal.tingwu.TingWu`)
- Single API Key auth (no AccessKey pair needed)
- Fixed polling status codes (numeric 0/1/2, not strings)
- Fixed OSS response format (camelCase fields)
- 107 test cases passing

## [0.5.0] - 2025-02-01

### Added
- Subtitle detection (skip ASR when subtitles available)
- Show Notes HTML cleaning
- Keyword rendering in templates
- Obsidian MCP search deduplication
- Pipeline dual-path: subtitle or ASR
- 105 test cases passing

## [0.4.0] - 2025-01-15

### Added
- APScheduler for scheduled polling
- SIGTERM graceful shutdown
- `serve` CLI command
- Docker deployment ready
- 77 test cases passing

## [0.3.0] - 2025-01-01

### Added
- RSS feed parsing and new episode detection
- SQLite state management
- Audio download with resume support
- Markdown note generation (Jinja2)
- Obsidian vault file writing
- Pipeline orchestration
- CLI (`run-once`, `transcribe` commands)
- 72 test cases passing

## [0.2.0] - 2024-12-15

### Added
- Transcriber Protocol abstraction
- TingWu, Bailian, Whisper API implementations
- Transcriber factory pattern
- ASR benchmark script
- 37 test cases passing

## [0.1.0] - 2024-12-01

### Added
- Project scaffold
- Config loading and validation
- Data models (Episode, TranscriptResult, ProcessedEpisode)
- Makefile, Dockerfile, pyproject.toml
- 20 test cases passing
