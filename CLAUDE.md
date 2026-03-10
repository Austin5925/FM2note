# FM2note — CLAUDE.md

## 项目概述

FM2note — 小宇宙播客 → Obsidian 笔记自动化管线。Python 后端，Docker 容器化部署。
通过 RSSHub 监听播客更新，通义听悟 API 做语音转写 + AI 摘要，直接写 .md 文件到 Obsidian vault。

## 技术栈

| 层 | 技术 |
|---|---|
| 语言 | Python 3.11+ |
| RSS 解析 | feedparser |
| HTTP 客户端 | httpx（async） |
| ASR 转写 | 通义听悟 API（aliyun-python-sdk-core） |
| 模板渲染 | Jinja2 |
| 状态管理 | SQLite（aiosqlite） |
| 调度 | APScheduler |
| 日志 | loguru |
| 测试 | pytest + pytest-asyncio + pytest-cov |
| 代码规范 | ruff（lint + format） |
| 容器化 | Docker + docker-compose |

## 关键文件路径

| 文件 | 用途 |
|---|---|
| `main.py` | CLI 入口（run-once / serve / transcribe） |
| `src/config.py` | 配置加载与验证 |
| `src/models.py` | 数据模型（Episode, TranscriptResult, ProcessedEpisode） |
| `src/version.py` | 版本号常量 |
| `src/monitor/rss_checker.py` | RSS 轮询、新剧集检测 |
| `src/monitor/state.py` | SQLite 状态管理 |
| `src/downloader/audio.py` | 音频下载（断点续传） |
| `src/transcriber/base.py` | 转写器 Protocol 抽象 |
| `src/transcriber/tingwu.py` | 通义听悟 API 实现 |
| `src/transcriber/factory.py` | 转写器工厂 |
| `src/writer/markdown.py` | Jinja2 模板渲染 |
| `src/writer/obsidian.py` | Obsidian vault 文件写入 |
| `src/pipeline.py` | 主管线编排 |
| `src/scheduler.py` | APScheduler 定时任务 |
| `config/config.yaml` | 全局配置 |
| `config/subscriptions.yaml` | 播客订阅列表 |
| `templates/podcast_note.md.j2` | 笔记 Jinja2 模板 |

## 开发命令

```bash
make lint        # ruff check src/ tests/
make format      # ruff format src/ tests/
make test        # pytest tests/ -v --tb=short -x
make test-cov    # pytest tests/ --cov=src --cov-report=term-missing
make test-integ  # pytest tests/ -v -m integration
make run         # python main.py run-once
make serve       # python main.py serve
make deploy      # ssh server + docker compose rebuild
```

## 代码规范

- **Python 风格**：ruff 强制执行，行宽 100，使用 type hints
- **架构模式**：Protocol 抽象（转写器可替换）+ 工厂模式
- **命名规范**：
  - 模块名 snake_case
  - 类名 PascalCase
  - Protocol 后缀表示抽象（如 `Transcriber`）
- **错误处理**：自定义异常类（`TranscriptionError`, `DownloadError`），不吞掉错误
- **异步**：所有 I/O 操作使用 async/await
- **日志**：loguru 结构化日志，所有外部调用带 context（episode_guid）
- **配置**：敏感信息走环境变量（.env），不得硬编码 API key
- **测试**：每个模块配对测试文件，mock 外部依赖，不实际调 API

## 版本控制与部署规则

每次代码变更完成后必须执行：

1. `make lint` — 代码规范检查通过
2. `make test` — 全部测试通过
3. `git add <相关文件>` — 只添加相关文件
4. `git commit -m "vX.Y.Z: 描述"` — commit 到 master
5. `git push origin master` — 推送到远程
6. `make deploy` — Docker 重建部署到服务器

**硬性规则**：
- 测试不通过不得 commit
- `.env` 文件永远不得 commit（已在 .gitignore 中排除）
- 不使用 feature 分支（直接 commit 到 master）
- 每个版本在本文件的 Version History 中记录变更摘要

## 版本规范

语义化版本 `vX.Y.Z`：
- X：架构性变更
- Y：新功能
- Z：Bug 修复、小优化

版本号维护在 `src/version.py`。

## 每个 Phase 的测试与验收条件

### Phase 0 — 脚手架
- 验收：`make lint` 无报错，`make test` 通过，`docker build .` 成功
- 测试：config 加载验证

### Phase 0.5 — ASR 评测
- 测试：mock HTTP 响应测试每个引擎的请求构建、轮询、解析、错误处理
- 验收：`make test` 通过 + benchmark 报告生成

### Phase 1 — MVP
- 测试：RSS 解析、状态管理 CRUD、下载、模板渲染、文件写入、管线流程
- 验收：`make test` 通过 + 手动 run-once 成功处理 1 集

### Phase 2 — 自动化
- 测试：调度器生命周期、重试逻辑、信号处理
- 验收：Docker 部署成功 + 连续运行 24 小时无异常

### Phase 3 — AI 增强
- 测试：字幕检测、HTML 清洗、MCP mock
- 验收：AI 摘要在笔记中正确显示

### Phase 4 — 生产加固
- 测试：端到端集成测试、配置热更新、通知系统
- 验收：7 天稳定性验证

## 外部 API 参考

| 服务 | 端点 | 鉴权 |
|---|---|---|
| 通义听悟 | `tingwu.cn-beijing.aliyuncs.com` | AccessKey ID + Secret |
| RSSHub（自建） | `http://localhost:1200` | 无 |
| Obsidian MCP | 本地 MCP Server | 本地连接 |

## Version History

- **v0.1.0** — Phase 0 脚手架：项目结构初始化、config/models 模块、Makefile、Dockerfile、pyproject.toml、20 个测试用例通过
- **v0.2.0** — Phase 0.5 ASR 评测：Transcriber Protocol 抽象、通义听悟/百炼/Whisper 三引擎实现、工厂模式、benchmark 脚本、37 个测试用例通过
- **v0.3.0** — Phase 1 MVP 核心管线：RSS 检测、SQLite 状态管理、音频下载、Markdown 生成、Obsidian 写入、Pipeline 编排、CLI 接入、72 个测试用例通过
- **v0.4.0** — Phase 2 自动化与可靠性：APScheduler 定时调度、SIGTERM 优雅关闭、serve 命令接入、Docker 部署就绪、77 个测试用例通过
- **v0.5.0** — Phase 3 AI 增强：字幕检测（跳过 ASR）、Show Notes HTML 清洗、关键词渲染、Obsidian MCP 搜索去重、Pipeline 字幕/ASR 双路径、105 个测试用例通过

## Current Version

v0.5.0 — Phase 3 AI 增强完成
