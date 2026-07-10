# FM2note — AGENTS.md

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
| CI/CD | GitHub Actions 已禁用（节省额度）；lint/test/打包走本地命令 |

## 关键文件路径

| 文件 | 用途 |
|---|---|
| `main.py` | CLI 入口（run-once / serve / transcribe / retry-summaries / init / install-service / start-service / app） |
| `src/config.py` | 配置加载与验证（AppConfig / Subscription） |
| `src/models.py` | 数据模型（Episode, TranscriptResult, ProcessedEpisode, SummaryResult） |
| `src/version.py` | 版本号常量 |
| `src/app_paths.py` | 运行目录统一解析（source / pip / packaged app） |
| `src/macos_launcher.py` | Finder/打包 App 启动入口，准备 runtime home 并拉起 GUI/后台 |
| `src/macos_service.py` | macOS launchd 状态、plist 路径和后台禁用标记 |
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
| `src/shared_cache.py` | 共享云端缓存客户端（上传/列表/批量 fetch） |
| `src/web/routes/cloud.py` | 云端浏览与选择性下载 API |
| `server/cache_sidecar.py` | 共享缓存 sidecar 服务端 |
| `scripts/build_macos_app.py` | macOS App / DMG / notarize 构建脚本 |
| `config/config.example.yaml` | 全局配置示例 |
| `config/subscriptions.example.yaml` | 播客订阅列表示例 |
| `src/templates/podcast_note.md.j2` | 笔记 Jinja2 模板（随 pip install 打包） |
| `templates/podcast_note.md.j2` | 本地开发用模板副本（CWD 优先级高于包内模板） |

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
make macos-app   # python3.11 scripts/build_macos_app.py
make macos-dmg   # 生成本机测试 DMG
make macos-dmg-girlfriend      # 生成预置 profile 的女友版 DMG
make macos-notarize-girlfriend # 生成并公证女友版 DMG
make clean       # 清理构建产物
make install-service   # python main.py install-service
make start-service     # python main.py start-service（如手动调用）
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
- GitHub Actions/CI 不得重新启用；发布前使用本地 `make lint` / `make test` / macOS 打包命令验证

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
- **v1.2.7** — 安全加固：路径遍历防护、XML 注入修复、API Key 不再写入 plist
- **v1.3.0** — 正式公开版：.env 自动加载、API Key 彻底从 plist 移除、pip-audit 通过、216 个测试
- **v1.3.1** — 开源前清理：开发文档迁入 devdocs/ + git 历史敏感数据清理 + 模板路径修复
- **v1.3.2** — pip install 端到端修复：模板打包进 wheel + 空订阅友好报错，216 个测试
- **v1.3.3** — Poe 默认模型升级 GPT-5.4 → GPT-5.5
- **v1.4.0** — Web UI MVP：FastAPI + SSE 转录主页 + `fm2note web` 命令 + 设置页只读视图 + 历史/订阅占位，新增 30 个测试
- **v1.4.1** — Web UI 功能完整：历史/订阅/设置可写 + 阿里云余额徽章（方案 A: BSS OpenAPI + RAM 子账号）+ 桌面快捷方式 + 两阶段提交 + SSRF 加固，171 个测试，Codex Code Review 通过
- **v1.4.2** — 体验打磨：健康自检页 + 后台服务状态检测（launchctl） + 友好错误文案映射 + 全局异常中间件 + 测试隔离 conftest 修复，310 个测试
- **v1.4.3** — 收官：`fm2note app` PyWebView 桌面壳 + `install-shortcut --mode app|web` + jinja2 安全 floor + 全部文档更新 + 女友指南改写为 GUI 优先，315 个测试，Codex 二次 Code Review 通过
- **v1.4.4** — UX 收尾：单图标主题切换（默认跟随系统，点击翻转）+ 暗色模式 CSS 覆盖层 + 余额弹窗一次性提示（sessionStorage）+ QR 图缺失优雅降级 + Tailwind CDN 顺序修正 + localStorage 禁用回退；关闭 CI 自动触发
- **v1.4.5** — 彩蛋：header 嵌入像素风边牧（32×24 SVG · 3 条独立动画轨道：呼吸 / 摇尾 / 眨眼） · 点击触发 "汪!" 气泡 + 身体抖动 · CSS 变量适配暗色（黑色变 stone-600 避免与背景同色）
- **v1.4.6** — Header 视觉调优：左侧组从 items-baseline 改 items-center，FM2note / 版本号 / 边牧三者垂直居中对齐；"汪!" 气泡从上方挪到狗下方（避免遮挡顶部窗口拖动条）
- **v1.4.7** — 边牧重画：从 header 挪到 "开始转录" 按钮下方居中，viewBox 改 32×32 显示 128×128（4 倍大小），姿态从侧站改坐姿（更像狗、不像马），头大 + 胸毛蓬松 + 立耳明显 + 黑白配色 + 立尾蜷曲；bark 气泡同步放大字号
- **v1.5.0** — EpisodeProcessor 重构 + daemon progress 全局广播
- **v1.5.1** — GUI 自启开关、静默 init、个人路径硬编码清理
- **v1.5.2** — AppPaths + StateManager 单例 + 多项并发/CWD audit fix
- **v1.5.3** — GUI 日志面板、立即检查、daemon 健康 chip
- **v1.5.4** — 共享缓存上线 + daemon auto-protect + 女友实测 bug 修复
- **v1.6.0** — GUI 云端浏览页 + 选择性下载
- **v1.6.1** — 云端下载按 frontmatter source 去重
- **v1.6.2** — 云端下载路径遍历防护 + launchd 日志路径修复
- **v1.6.3** — 云端缓存 guid/path 安全审计修复
- **v1.6.4** — 窄窗口 header 与订阅预览修复
- **v1.7.0** — macOS 桌面 App 打包 / 签名 / 公证流程
- **v1.7.1** — macOS 公证 profile 路径修复
- **v1.7.2** — macOS DMG 分发包
- **v1.8.0** — macOS 双版本分发 + 桌面/后台状态解耦
- **v1.8.1** — DMG 拖拽箭头 + profile 可见性强确认
- **v1.8.2** — 后台自动检查按钮修复
- **v1.8.3** — App 启动自动拉起后台 daemon
- **v1.8.4** — 云端批量下载加速 + 打包 App 后台启动修复：有界并发 fetch + 1000 条 metadata lookup + packaged CLI 运行目录修复
- **v1.8.5** — Poe 默认摘要模型改为 gemini-3.1-flash-lite；设置页仅在 Poe provider 下显示 Poe 模型选项；转录页边牧增加轻量状态反馈
- **v1.8.6** — 摘要 prompt 统一为 provider 共享；笔记最前面新增“播客内容分析”快速阅读区，并兼容历史页补摘要
- **v1.8.7** — “播客内容分析”升级为信息保真的“精简版博客”；Poe 默认模型切换为 gpt-5.4-mini

## Current Version

v1.8.7 — 精简版博客
