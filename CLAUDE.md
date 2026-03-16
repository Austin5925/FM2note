# FM2note — CLAUDE.md

## 项目概述

FM2note — 播客 → Obsidian 笔记自动化管线。
混合部署：服务器运行 RSSHub + Redis（RSS 代理），本地 Mac 运行 fm2note 主进程。
支持任意 RSS/Atom feed，云端 ASR 转写 + AI 摘要，直接写 .md 文件到本地 Obsidian vault。

## 技术栈

| 层 | 技术 |
|---|---|
| 语言 | Python 3.11+ |
| RSS 解析 | feedparser（兼容 RSS 2.0 / Atom） |
| HTTP 客户端 | httpx（async） |
| ASR 转写 | FunASR / Paraformer / 通义听悟 / 百炼 / Whisper API（dashscope + openai SDK） |
| AI 摘要 | Poe API / OpenAI-compatible API（自动检测，Protocol 抽象） |
| 模板渲染 | Jinja2（可自定义模板路径和标签） |
| 状态管理 | SQLite（aiosqlite） |
| 调度 | APScheduler |
| 日志 | loguru |
| 测试 | pytest + pytest-asyncio + pytest-cov |
| 代码规范 | ruff（lint + format） |
| 容器化 | Docker + docker-compose（仅 RSSHub 服务端） |
| 包管理 | pyproject.toml (PEP 621) + setuptools |
| CI/CD | GitHub Actions（lint + test + PyPI publish） |

## 关键文件路径

| 文件 | 用途 |
|---|---|
| `main.py` | CLI 入口（run-once / serve / transcribe / retry-summaries / init / install-service） |
| `src/config.py` | 配置加载与验证（AppConfig / Subscription） |
| `src/models.py` | 数据模型（Episode, TranscriptResult, ProcessedEpisode, SummaryResult） |
| `src/version.py` | 版本号常量 |
| `src/monitor/rss_checker.py` | RSS 轮询、新剧集检测（兼容标准 RSS/Atom） |
| `src/monitor/state.py` | SQLite 状态管理 |
| `src/monitor/subtitle.py` | 字幕检测与解析 |
| `src/downloader/audio.py` | 音频下载（断点续传） |
| `src/transcriber/base.py` | Transcriber Protocol 抽象 |
| `src/transcriber/tingwu.py` | 通义听悟 API 实现 |
| `src/transcriber/funasr.py` | FunASR + Paraformer 实现 |
| `src/transcriber/bailian.py` | 百炼 ASR 实现 |
| `src/transcriber/whisper_api.py` | OpenAI Whisper API 实现 |
| `src/transcriber/factory.py` | 转写器工厂 |
| `src/summarizer/base.py` | Summarizer Protocol 抽象 |
| `src/summarizer/poe_client.py` | Poe API 摘要实现 |
| `src/summarizer/openai_client.py` | OpenAI-compatible API 摘要实现 |
| `src/summarizer/factory.py` | 摘要器工厂（auto/poe/openai/none） |
| `src/summarizer/pending.py` | 失败摘要缓存与重试 |
| `src/writer/markdown.py` | Jinja2 模板渲染（支持自定义模板和标签） |
| `src/writer/obsidian.py` | Obsidian vault 文件写入 |
| `src/writer/html_cleaner.py` | HTML → Markdown 清洗 |
| `src/pipeline.py` | 主管线编排 |
| `src/scheduler.py` | APScheduler 定时任务 |
| `config/config.example.yaml` | 全局配置示例 |
| `config/subscriptions.example.yaml` | 播客订阅列表示例 |
| `templates/podcast_note.md.j2` | 笔记 Jinja2 模板（标签变量化） |

## 开发命令

```bash
make lint        # ruff check src/ tests/
make format      # ruff format src/ tests/
make test        # pytest tests/ -v --tb=short -x
make test-cov    # pytest tests/ --cov=src --cov-report=term-missing
make test-integ  # pytest tests/ -v -m integration
make run         # python main.py run-once
make serve       # python main.py serve
make build       # python -m build (生成 sdist + wheel)
make clean       # 清理构建产物
make install-service   # python main.py install-service
make uninstall-service # python main.py uninstall-service
make bump-patch  # 版本号 patch +1
make bump-minor  # 版本号 minor +1
```

## 代码规范

- **Python 风格**：ruff 强制执行，行宽 100，使用 type hints
- **架构模式**：Protocol 抽象（Transcriber / Summarizer 可替换）+ 工厂模式
- **命名规范**：模块名 snake_case，类名 PascalCase
- **错误处理**：自定义异常类（`TranscriptionError`, `DownloadError`, `ConfigError`）
- **异步**：所有 I/O 操作使用 async/await
- **日志**：loguru 结构化日志
- **配置**：敏感信息走环境变量（.env），不得硬编码 API key
- **测试**：每个模块配对测试文件，mock 外部依赖，不实际调 API

## 版本控制与部署规则

每次代码变更完成后必须执行：

1. `make lint` — 代码规范检查通过
2. `make test` — 全部测试通过
3. `git add <相关文件>` — 只添加相关文件
4. `git commit -m "vX.Y.Z: 描述"` — commit 到 master
5. `git push origin master` — 推送到远程

**硬性规则**：
- 测试不通过不得 commit
- `.env` 文件永远不得 commit（已在 .gitignore 中排除）
- `config/config.yaml` 和 `config/subscriptions.yaml` 不提交（用户自建）
- 不使用 feature 分支（直接 commit 到 master）
- 每个版本在本文件的 Version History 中记录变更摘要

## 版本规范

语义化版本 `vX.Y.Z`：
- X：架构性变更
- Y：新功能
- Z：Bug 修复、小优化

版本号维护在 `src/version.py`。

## 外部 API 参考

| 服务 | 端点 | 鉴权 |
|---|---|---|
| FunASR / Paraformer | DashScope SDK | DASHSCOPE_API_KEY |
| 通义听悟 | DashScope SDK | DASHSCOPE_API_KEY + TINGWU_APP_ID |
| 百炼 ASR | DashScope SDK | DASHSCOPE_API_KEY |
| OpenAI Whisper | OpenAI API | OPENAI_API_KEY |
| Poe 摘要 | `api.poe.com/v1` | POE_API_KEY |
| OpenAI 摘要 | `api.openai.com/v1`（或自定义 base_url） | OPENAI_API_KEY |
| RSSHub（自建） | 服务器 Docker，通过 Nginx 反代 | 无 |

## Version History

- **v0.1.0** — Phase 0 脚手架：项目结构初始化、config/models 模块，20 个测试
- **v0.2.0** — ASR 评测：Transcriber Protocol、通义听悟/百炼/Whisper 三引擎，37 个测试
- **v0.3.0** — MVP 核心管线：RSS 检测、SQLite 状态管理、音频下载、Markdown 生成、Pipeline，72 个测试
- **v0.4.0** — 自动化：APScheduler 定时调度、SIGTERM 优雅关闭、Docker 部署就绪，77 个测试
- **v0.5.0** — AI 增强：字幕检测、Show Notes HTML 清洗、Obsidian MCP 去重，105 个测试
- **v0.5.1** — 通义听悟 DashScope SDK 迁移 + 实测修复，107 个测试
- **v0.5.2** — 上线前加固：文档对齐、docker-compose 安全加固
- **v1.0.0** — 生产就绪：5 集实测全部通过，107 个测试
- **v1.1.0** — FunASR/Paraformer 引擎 + Poe AI 摘要
- **v1.2.0** — Poe API 限速 + 摘要失败缓存重试
- **v1.2.1** — podcast_dir 改为 10_Podcasts + launchd 服务修复
- **v1.2.2** — 开源化基础：pip install + init + CI + 文档英文化 + 示例配置分离，170 个测试
- **v1.2.4** — 通用 RSS/Atom 兼容 + 模板定制化 + init 增强，192 个测试
- **v1.2.5** — Summarizer Protocol + OpenAI-compatible 摘要器 + 摘要器工厂，213 个测试
- **v1.2.6** — 文档全面更新：所有文档对齐最新代码
- **v1.2.7** — 安全加固：plist 模板清除硬编码路径、config/subscriptions.yaml 从 git 取消跟踪、load_config fallback 修复

## Current Version

v1.2.7 — 安全加固 + 开源前审计
