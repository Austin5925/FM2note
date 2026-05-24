# Changelog

All notable changes to FM2note will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.6] - 2026-05-24

### Fixed
- Header 左侧组（FM2note / 版本号 / 边牧）从 `items-baseline` 改为 `items-center`，
  与右侧的余额徽章 / 主题切换 / 导航 tab 视觉上水平对齐
- 边牧 "汪!" 气泡从上方改到狗的下方（避免遮挡桌面应用顶部的窗口拖动条）

## [1.4.5] - 2026-05-24

### Added
- Easter egg: 像素风边牧（32×24 inline SVG）嵌入 header 版本号旁
- 3 条独立 CSS 动画轨道：身体呼吸（1.4s）+ 尾巴摇摆（0.5s）+ 眨眼（4s）
- 点击边牧 → "汪!" 气泡 + 身体抖动微互动
- CSS 变量 `--collie-dark` / `--collie-light` 适配暗色模式（黑色提升为 stone-600 避免与暗色背景同色）

## [1.4.4] - 2026-05-24

### Added
- 单图标主题切换按钮（sun/moon SVG）— 默认跟随系统，点击翻转浅/深色
- 完整暗色模式 CSS 覆盖层（基于 stone 调色板的 cascade 写法）
- 阿里云余额过低弹窗一次性提示（sessionStorage 作用域为浏览器标签页/窗口）

### Fixed
- 余额弹窗的二维码图缺失时优雅降级（onload/onerror + data-loaded，JS 不再无条件 unhide）
- Tailwind Play CDN 配置写法符合官方文档（config 写在 script 之后）
- localStorage 被禁用时（隐私窗口）回退仍能跟随系统主题

### Removed
- 弃用临时的 3 按钮主题切换组（系统/浅/深）

### Chores
- GitHub Actions CI 关闭 push/PR 自动触发（保留 workflow_dispatch 手动入口）
- Makefile `lint` target 加上 `ruff format --check`

## [1.4.3] - 2026-05-24

### Added
- `fm2note app` — desktop window via PyWebView (optional extra: `pip install 'fm2note[app]'`)
- `fm2note install-shortcut --mode app|web` — desktop shortcut now prefers PyWebView with browser fallback
- 女友指南改写为 GUI 优先版本（CLI 流程折叠为进阶用法）

### Documentation
- README / README.zh-CN: 新增 "Web UI" 章节
- girlfriend-guide.md: 全面改写为 Web UI 流程
- CHANGELOG: 整合 v1.4.x 历史

## [1.4.2] - 2026-05-23

### Added
- `GET /api/health-check` — 配置 + key + vault + 余额 一站式自检
- `GET /api/service/status` — 检测 launchd 后台服务安装与运行状态
- 设置页顶部健康自检 + 服务状态面板
- 全局异常中间件（Exception → 500 JSON，不泄漏栈信息）
- 转录失败的 SSE 错误消息走 `friendly_transcribe_error` 友好映射（429/402/401/timeout/小宇宙解析失败 等）

### Fixed
- conftest 加 `_isolate_env` / `_reset_balance_cache` autouse fixture，根治 settings PUT 写 `os.environ` 跨测试污染

## [1.4.1] - 2026-05-23

### Added
- 历史页：state.db + pending_summaries 合并展示 + 单条 / 一键重试摘要
- 订阅页：增删改 RSS（ruamel.yaml 保留注释）+ feedparser 连接测试
- 设置页可写：API key 密码框 + vault 校验 + 引擎切换
- 阿里云余额徽章：BSS OpenAPI QueryAccountBalance + 5 分钟缓存 + 三色告警 + 充值提醒弹窗
- `fm2note install-shortcut` — 一键生成 macOS 桌面快捷方式
- 可选依赖：`fm2note[aliyun]` (BSS SDK)

### Security
- settings/history/transcribe 路由不再接受路径查询参数（防止任意路径写入）
- `_is_xiaoyuzhou_episode_url` 用 urlparse + 精确 host 匹配（修复 SSRF substring 欺骗）
- subscriptions/test 接口拒绝非 http(s) scheme
- 阿里云 SDK 异常仅返回类型名（不透传可能含凭据的原始消息）
- env+yaml 写入两阶段提交（双 stage → 双 replace + finally 清理）
- 异步锁串行化 settings/subscriptions 的读改写操作
- history retry-summary id 严格 hex 校验 + relative_to 路径锚定
- `fm2note web` 强制 127.0.0.1，移除 --host 选项

### Reviewed
- Codex Code Review 通过（C2/H3 fixed: --host removal + two-phase commit）

## [1.4.0] - 2026-05-23

### Added
- Web UI MVP — FastAPI + Jinja2 + Tailwind CDN + SSE 进度推送
- `fm2note web --port 7878` CLI 命令，自动开浏览器
- 转录主页：贴 URL → 5 阶段实时进度（resolve/subtitle_check/asr/summary/write）→ obsidian:// 跳转
- 设置页只读视图（API key 掩码尾 4 位）
- 历史 / 订阅页占位
- `src/transcribe_flow.py` 抽取共享管线，CLI 与 Web 共用

### Changed
- Poe 默认模型 GPT-5.4 → GPT-5.5（v1.3.3 实际变更）

## [1.3.1] - 2026-03-18

### Changed
- Developer docs (help/plan/research/test/dashscope-api) moved to `devdocs/` (gitignored)
- CODE_OF_CONDUCT: enforcement contact now links to GitHub Issues
- CHANGELOG: all version dates corrected to actual release dates
- Template path resolution: pip-installed users auto-find package-bundled templates

### Security
- Git history rewritten to remove server IP and personal paths
- `benchmark_asr.py` added to .gitignore

## [1.3.0] - 2026-03-18

### Changed
- API keys are no longer embedded in launchd plist files — `.env` is auto-loaded at CLI startup
- `source .env` is no longer required before running commands
- All documentation updated to reflect .env auto-loading

### Added
- `_load_dotenv()` auto-loads `.env` from working directory (only sets unset vars)
- Tests for .env auto-loading and plist key exclusion
- 216 tests passing
- pip-audit verification passed (no CVEs in direct dependencies)

### Security
- Plist file no longer contains API keys (was world-readable at ~/Library/LaunchAgents/)
- Path traversal guard on `podcast_name` in ObsidianWriter
- XML escape for launchd plist environment values
- Transcript text truncation (80K chars) before AI API calls
- API response objects no longer logged in error messages (could leak auth headers)

## [1.2.6] - 2026-03-16

### Changed
- All documentation updated to match current codebase
- CLAUDE.md: complete rewrite with all file paths, ASR engines, summarizer modules
- README.md / README.zh-CN.md: added Bailian engine, summary provider table, template customization
- CONTRIBUTING.md: updated to reference Summarizer Protocol and factory pattern
- config.example.yaml: added summary_provider, bailian engine, template_path
- .env.example: restructured with SUMMARY_PROVIDER, SUMMARY_BASE_URL
- help.md: removed hardcoded IPs, updated architecture and commands

### Fixed
- Default ASR engine fallback in load_config() was `tingwu`, now correctly `funasr`

## [1.2.5] - 2026-03-16

### Added
- Summarizer Protocol abstraction (`src/summarizer/base.py`)
- OpenAI-compatible summarizer (GPT-4o, DeepSeek, Groq, Ollama)
- Summarizer factory with auto-detection (`auto`/`poe`/`openai`/`none`)
- `summary_provider`, `summary_base_url` config fields
- 213 tests passing

## [1.2.4] - 2026-03-16

### Added
- Generic RSS/Atom feed support (standard feeds work without RSSHub)
- Customizable note templates (configurable path and section labels)
- Enhanced `fm2note init` with RSSHub URL prompt and macOS vault auto-detection
- Entries without audio enclosure automatically skipped
- GUID fallback chain (id → link → title-based)
- 192 tests passing

## [1.2.2] - 2026-03-15

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
