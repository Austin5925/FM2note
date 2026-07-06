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
make macos-dmg   # python3.11 scripts/build_macos_app.py --dmg
make macos-notarize # python3.11 scripts/build_macos_app.py --notarize --dmg
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
- **v1.4.8** — 修复"看笔记"按钮在 PyWebView 下不工作：obsidian:// 自定义协议必须走 `<a target="_blank">` 才能被 OS 接管（programmatic `window.location.href` 在嵌入 WebKit 里被吞）。 同步：抽取 `src/web/services/obsidian_url.py` 共享给 transcribe + history，history 端点返回 `obsidian_url` 字段，前端用真链接
- **v1.4.9** — 订阅页用户友好化：默认预填 `https://macroclaw.app/rsshub`，支持粘贴小宇宙播客页 / 剧集页 / 分享文本自动生成 RSSHub 订阅地址，保留名称和 RSS URL 手动兜底
- **v1.4.10** — 测试环境加固：项目 pytest 配置禁用无关的全局 `pytest_ethereum` 插件，解决本机 `web3` / `eth_typing` 不兼容导致 `make test` 启动即失败
- **v1.4.11** — 设置页 vault_path 容错 + macOS 权限提示：粘贴带 `'…'` / `"…"` 的路径自动去引号（后端 + 前端双保险）；`PermissionError` / `FileNotFoundError` 走友好提示（指引"完全磁盘访问"权限）；健康自检改为实际 touch 写测试以识别 macOS TCC 沙箱拦截。新增 7 个测试
- **v1.4.12** — 环境变量一刀切清理（修复"设置改了不生效"同款隐患）：
  - **根因**：`OBSIDIAN_VAULT_PATH` 等 env 变量优先级 > yaml，`fm2note init` 又把 vault_path 写到 `.env`，导致 Web UI 改完 yaml 被 env 反向覆盖
  - 所有**非敏感**配置（vault_path、podcast_dir、asr_engine、summary_provider、summary_model、summary_cooldown、summary_base_url、log_level）改为 **yaml-only**；启动时若发现旧 env 变量给 warning 提示用户清理
  - 所有**敏感凭据**（DashScope/Poe/OpenAI key、Aliyun AK/SK、TingWu AppId）保持 **env-only**
  - 设置页 input 通过 `vault_path_default` 字段显示个人默认路径（女朋友 vault）作为 placeholder + "使用默认" 一键填充按钮
  - `fm2note init` 不再写 `OBSIDIAN_VAULT_PATH` 到 `.env`；`.env.example` 删除所有非敏感变量
  - `src/config.py` 新增 `DEFAULT_VAULT_PATH` 常量（单一来源，前后端共享）
  - 329 个测试（+2 个 env override 回归测试）
- **v1.4.13** — v1.4.12 审计 hotfix（双线第一轮）：
  - `fm2note init` 模板 `.env` 删除残留的 `export LOG_LEVEL=INFO`（不然新用户首次启动就撞 stale-env warning）
  - `scripts/com.fm2note.serve.plist.template` 删除 `OBSIDIAN_VAULT_PATH` / `LOG_LEVEL` env 项
  - README.md / README.zh-CN.md 同步 v1.4.12 的 env / yaml 边界
  - `_clean_path_input` / 前端 `cleanPath` 支持多层引号（如 `"'/path'"` 双粘贴场景），上限 4 层防 DoS
  - 健康自检 touch 探针包 `try/finally`，`.fm2note_writetest` 在任何异常路径都会清理
  - 空 vault_path 漏洞修复 + stale-env warning 模块级去重 + 缺失 YAML 持久化测试
  - 334 个测试
- **v1.4.14** — v1.4.13 审计 hotfix（双线第二轮）：
  - **Critical 测试本身有伪 PASS**：`test_stale_env_warning_fires_only_once` 之前只断言 flag is True（任何 load_config 都会让 flag 翻 True，与 stale env 无关）。改为用 loguru sink 真正统计 warning 调用次数，并补反例测试（无 legacy env 时必须不 warn）
  - `conftest.py` 加 `_reset_legacy_env_warning` autouse fixture，避免模块级 dedup flag 跨测试泄漏
  - `devdocs/help.md` 同步：摘要配置从 `export SUMMARY_*` env 改为 `config.yaml` yaml 写法
  - `README.zh-CN.md` 补完整的「配置」节（yaml-only 字段表 + env-only 字段表），与英文版对齐
  - `test_two_phase_commit_*` 加 yaml-was-committed assertion，把注释承诺的"yaml did commit"显式化
  - **Codex MEDIUM**：`_clean_path_input` 后 `Path(".")` / 相对路径仍能过校验 → silently 写到 CWD。新增 `is_absolute()` 守卫
  - 测试新增覆盖空字符串 / 相对路径 / warning once / no-warning negative case

- **v1.4.15** — 订阅系统改造：消除"首次启动烧光额度"陷阱 + Web UI 加订阅热加载
  - **根因**：fresh install 时 `state.db` 为空，feed 中所有历史剧集（典型 20-50 集）都被当成"新"全量转录，女朋友拉同一份 yaml 会瞬间烧掉一大笔 DashScope/Poe 额度
  - 新增 `POST /api/subscriptions/preview`：返回 feed 中 episode count / unprocessed count / 总时长 / 估算成本（按 asr_engine 单价）
  - `POST /api/subscriptions` 现在 **必填** `backfill_strategy`：`all` / `new_only` / `recent_n` / `since_date`，配套需要的 `recent_n` / `since_date` 字段
  - state.db 新状态 `backfill_skipped`，被 `is_processed()` 视为已处理，避免下次 poll 重转
  - `StateManager.mark_backfill_skipped()` 用 `INSERT OR IGNORE`，并发安全且不覆盖已 `done` 的行
  - GUI 订阅页 add 流程：保存 → preview → 弹策略选择对话框（4 个 radio + N/日期输入）→ 真正 add
  - `RSSChecker` 加 `subs_provider` 钩子，**每次 poll 重读 yaml**，Web UI 改订阅无须重启 daemon
  - 新增 `src/web/services/feed_preview.py`（feedparser → EpisodePreview + 成本估算 + backfill 策略过滤）
  - **双线审计 hotfix（Code Review 主审 + Codex 终审）**：
    - **C1（CRIT）**：`feedparser.parse` 阻塞 event loop → 包 `asyncio.to_thread`（`/preview` + `_apply_backfill_strategy`）
    - **C2（CRIT XSS）**：`subscriptions.js` 把 `preview.asr_engine` 直接 innerHTML 注入 → 用 `escapeHtml()` 包
    - **I1 + BUG 11**：`_apply_backfill_strategy` 移入 yaml_lock 内 + 加重复 URL guard（409 拒绝）+ feedparser 失败时 raise HTTPException（502），不再静默退化成"全部转录"
    - **BUG 10（SSRF）**：`_validate_payload` 校验 rss_url scheme，只接受 http/https
    - **I3 + BUG 2**：`mark_backfill_skipped` 改用 `INSERT OR IGNORE` + rowcount 计数，一招解决并发 SELECT-then-INSERT race + 事务问题；加显式 rollback
    - **I4**：`recent_n` 必须 ≥1（之前 -5 silently 退化成 0 = 全跳）
  - 369 测试（+33 新增：4 种 strategy 端到端 / scheme 校验 / 重复 URL 409 / feedparser 失败 502 / 热加载 / 多边界）

- **v1.4.16** — 转录结果共享上传缓存（多用户去重）
  - **使用场景**：用户和女朋友各自跑 fm2note 订阅同一批播客。任何一方先转完某集，另一方直接拿现成 .md，零 API 消耗
  - **服务端**：新增 `server/cache_sidecar.py` — FastAPI + SQLite + Bearer auth。可通过 `server/docker-compose.cache.yaml` 部署到现有 RSSHub 服务器旁边
  - **客户端**：新增 `src/shared_cache.py`：`SharedCacheClient.from_env()` 读 `SHARED_CACHE_URL` + `SHARED_CACHE_TOKEN`，未配置时返回 None（单用户零开销）
  - **上传 hook**：`pipeline.py` 写完笔记后 fire-and-forget `client.upload(guid, content)`，失败仅 log
  - **下载-skip hook**：`pipeline.process_episode` 入口先 `client.fetch(guid)`，命中就直接 `writer.write_note(episode, cached)` + mark done，**跳过 ASR / Summary / Markdown 渲染**
  - **协议**：`POST /cache/{guid}` upsert（last-write-wins，两人并发 upload 安全）+ `GET /cache/{guid}` 404 on miss
  - **安全**：Bearer token 常时比较；guid 长度限制；upload 5MB 上限；启动时缺 token 拒绝跑
  - **双线审计 hotfix（Code Review 主审 2/3 + Codex 1/3）**：
    - **CRIT #1（CR）**：server 单 aiosqlite 连接并发不安全 → 加 `asyncio.Lock` 包 execute/commit pairs
    - **CRIT #2（CR）**：`_ct_equal` 早返泄露 token 长度 → 改用 `hmac.compare_digest`
    - **IMPORTANT #3（CR + Codex 双方都标）**：cache-hit 路径不检查 `note_exists` → 本地已存在时 `write_note` 抛 `FileExistsError` 被算成 failed → 加 idempotent guard
    - **Codex #6（CR 未提，新发现）**：缺 body-size pre-parse cap，攻击可发 multi-GB body 耗尽 server 内存 → 加 Content-Length middleware 在 FastAPI buffer 前 reject
    - **Codex #4 + #5**：`_UPLOADER_FP` import-time + 5s × N 串行已知 trade-off，加 docstring 标记，留 v1.5.x 优化
  - 405 测试（+36 新增：shared_cache 客户端 13 / cache_sidecar 服务端 13 / pipeline cache-hit-skip + miss-upload + idempotent 6 / URL 编码 / 边界）

- **v1.5.0** — EpisodeProcessor 重构（消除 90% pipeline 代码重复）+ daemon progress 全局广播
  - **根因**：`transcribe_flow.py`（单 URL）和 `pipeline.py`（订阅 daemon）实现了**几乎完全相同**的"下载 → ASR → 摘要 → 渲染 → 写入"五阶段，每次 bug fix 都得改两份；shared cache 只接进了 pipeline，单 URL 路径不享受
  - 新增 `src/episode_processor.py` `EpisodeProcessor` 类：核心 episode 处理的单一来源
  - `Pipeline.process_episode` 现在是 `await self._processor.process(...)` 的薄包装
  - `transcribe_flow.transcribe_single_url` 现在解析 URL 后构 Episode 也走 processor
  - `ProcessingOptions` 控制差异化行为：单 URL flow 不 cache fetch（不要 stale）也不 MCP dedup，daemon flow 全开
  - **Pipeline daemon 进度全局广播**：新增 `subscribe_daemon_progress()` 给 Web 层注册回调，每集 stage 转换实时推到所有订阅者（GUI 历史页 v1.5.3 接入）
  - **审计 fix**: A2 (Code Review) `mark_status("done")` 缺失的 `podcast_name`/`title` 现在由 processor 统一传；Codex debt `Pipeline._downloader` 死代码删除
  - 420 测试（+15 新增：EpisodeProcessor cache-hit / options / progress callback / mark_status 字段 + Pipeline broadcast 订阅/取消/异常隔离）

- **v1.5.1** — GUI 自启开关 + 删 init 交互 + 修个人路径硬编码
  - **A4 fix（Code Review）**：`DEFAULT_VAULT_PATH` 从硬编码个人路径改为通用 `~/Documents/Obsidian`，避免 pip 包泄露作者用户名 + 误导新用户
  - **D1 fix**：`CHANGELOG.md` 从 v1.4.11 起补完整（pyproject 链接此文件，之前是 stub，PyPI changelog 看不到）
  - **Codex fix**：`fm2note init` 的 fallback `.env` 模板现在写完整内容（Poe/OpenAI/Aliyun/Shared cache 全 placeholder），pip-installed 环境拿不到 .env.example 也能生成完整模板
  - **GUI 自启**：设置页"开机自启"开关，调 `POST /api/service/install` / `/uninstall`，子进程跑 `fm2note install-service` 反向化。GUI 用户无须开终端
  - **删 init 交互**：默认 silent skeleton 模式（auto-detect vault + 全 default 值），保留 `--interactive` 标志走旧 prompt 流。next-steps 提示打开 GUI 而非 CLI
  - **Codex audit fix**：`/api/service/status` 的 `launchctl list` subprocess 包 `asyncio.to_thread`，不再阻塞 event loop
  - 425 测试（+5 新增：silent init 默认 / interactive flag / GUI install-toggle / non-darwin reject / 完整 env 模板）

- **v1.5.2** — AppPaths + StateManager 单例 + 多项 audit fix（消除多组 CWD/并发陷阱）
  - **新增 `src/app_paths.py`** AppPaths 单例：所有文件路径（config/subscriptions/.env/db/pending_dir/tmp/logs）从单一来源解析，FM2NOTE_HOME env 可覆盖。替代散落各处的 `Path("data/...")` 类相对路径
  - **A5 fix（Code Review）**：`src/summarizer/pending.py` `PENDING_DIR` 不再 CWD-relative，改走 AppPaths。修复 `fm2note app` Finder 双击启动时 pending summaries 写到 `/data/...` 的灾难
  - **新增 `src/web/services/state_singleton.py`**：FastAPI 生命周期内的 StateManager 单例，所有路由共享。替代 history/preview/add_sub 各自 open+close aiosqlite connection（3 处全修）
  - **A3 fix**：新增 `StateManager.get_recent_history(limit, include_backfill_skipped=False)`，SQL `ORDER BY ... LIMIT` + WHERE filter，history.py 改用。原来的 Python 端全表 sort+slice 退役
  - **A1+B1+C1 fix**：`POST /api/subscriptions/test` 的 `feedparser.parse` 包 `asyncio.to_thread`（v1.4.15 漏修的最后一处）
  - **Codex fix**：`StateManager.mark_status` 用 `BEGIN IMMEDIATE` 显式事务包 SELECT+UPDATE/INSERT，并发 connection 时不再丢 retry_count 增量也不会 IntegrityError
  - conftest.py 新增 `_reset_app_paths` + `_reset_state_singleton` autouse fixtures，把每个测试的 sandbox 锚到自己的 `tmp_path`
  - 431 测试（+5 新增：get_recent_history limit/排序/filter backfill_skipped/include flag + mark_status 事务重试计数）

- **v1.5.3** — GUI 收尾：日志面板 + 立即检查 + daemon 健康 chip + 端到端验证
  - **GUI 日志面板**：新增 `src/web/services/log_buffer.py` loguru sink → 环形 buffer（10k 上限）+ `GET /api/logs?after_seq=N` 增量拉取。设置页加 panel，3 秒轮询 auto-refresh。彻底消除 PyWebView 桌面壳"看不见日志"的工程债
  - **立即检查按钮**：新增 `POST /api/service/poll-now`，detached spawn `fm2note run-once`，fire-and-forget。设置页"立即检查一次"按钮，用户改了订阅不用等 3 小时
  - **daemon 健康 chip**：header 加 `daemon-chip` 元素，60s 轮询 `/api/service/status` 显示"● 运行中 · 上次 5 分钟前"。`/api/service/status` 扩展返回 `last_run_at` / `next_run_estimate_at` / `poll_interval_hours`
  - **端到端 smoke test**：本地 uvicorn 启动验证 5 个关键端点（healthz / settings / logs / status / poll-now）全过
  - 440 测试（+8 新增：log_buffer 幂等/after_seq/上限 + /api/logs 端点 + poll-now spawn + 平台拒绝 + status activity 字段）

- **v1.5.4** — 共享缓存上线 + daemon auto-protect + 女友实测 bug 修复
  - **共享转录缓存正式部署到生产**：v1.4.16 client 端 + 今天首次部署 server 端到 macroclaw.app/fm2note-cache（nginx 反代 + Docker 容器 + Bearer auth + 端到端 e2e 验证全过）。两人订阅同一批播客时，谁先转完另一方零成本拿现成 .md
  - **daemon auto-protect**：新增 `StateManager.has_any_recorded_in` + `RSSChecker._auto_protect_sub`，统一手动编辑 yaml 和 GUI POST `/api/subscriptions` 的语义保护——任何 state.db 完全没记录的 sub 首次 poll 自动 mark `backfill_skipped` (= new_only)。解决"yaml 加新订阅 → 下次 poll 烧光额度" trap（v1.4.15 只保护了 GUI 路径）
  - **cache_sidecar audit fix**：`post_cache` 加 `db_lock`（v1.4.16 Code Review fix #1 漏了 POST 路径，并发 upload 可能 interleave aiosqlite execute/commit 丢写）
  - **女朋友实测 3 个 bug 修复**：
    - sub-modal 遮挡 backfill modal（macOS PyWebView z-index quirk）→ 打开 backfill modal 前先 hide sub-modal
    - 估算 UI 不明确 → 显示"funasr 计价 · 不含 AI 摘要"+ feed 限制说明"通常只返回最近 ~15-20 集" + missing_duration_count 警告
    - `preview_sub` silent fallback 看不到 stack → `logger.warning` → `logger.exception`
  - **RSSChecker 重构**：每个 sub 单次 fetch，feed 复用给 auto-protect + extract_new_episodes（避免引入 auto-protect 导致 double-fetch）
  - 服务器 + 客户端双线文档：`server/README.md` + `macroclaw:/root/fm2note-cache/README.md`
  - 449 测试（+9 新增：has_any_recorded_in 4 + auto-protect 3 + cache lock + preview missing_duration）

- **v1.6.0** — GUI 云端浏览页 + 选择性下载
  - 新增【云端】tab：浏览共享缓存里所有已转录剧集，按节目（podcast_name）分组显示文件夹卡片 → 点开看 episode 列表 → 复选框 + 全选 + "覆盖已存在" 开关 + 单次最多 100 集批量下载
  - 后端：`src/web/routes/cloud.py` (`GET /api/cloud/list`、`POST /api/cloud/download`) + `src/web/templates/cloud.html` + `src/web/static/cloud.js`
  - client: `SharedCacheClient.list_items(prefix, limit)` + `upload(.., podcast_name=, title=)` 新参数；EpisodeProcessor pipeline upload 时传 metadata
  - server v1.6.0: `notes` 表 idempotent migration 加 `podcast_name` + `title` 列；新增 `GET /cache/list` endpoint（按 updated_at DESC、prefix LIKE 过滤、limit hard cap 1000）；upsert 接受 metadata 字段并 COALESCE 兼容 pre-v1.6 client 上传的 NULL
  - 部署：server 重 build 推 macroclaw；23 集 v1.5.4 老数据用 v1.6 client backfill 了 podcast_name + title（last-write-wins）
  - 458 测试（+9 新增：未配置 cache 行为 / 空 guids / >100 限额 / 按节目分组写入 / 不覆盖默认 / 文件名 sanitize / cache miss 报告）

- **v1.7.0** — macOS 桌面 App 打包 / 签名 / 公证流程
  - 新增 `src/macos_launcher.py`：Finder 启动 `.app` 时把运行目录固定到 `~/Library/Application Support/FM2note`，首次启动自动生成 `config/` + `.env` 骨架；`FM2NOTE_HOME` 可覆盖
  - 新增 `scripts/build_macos_app.py`：PyInstaller 生成 `dist/FM2note.app`，自动使用 Keychain 中的 `Developer ID Application` 证书签名；无证书时 ad-hoc 签名用于本机测试；支持 `--notarize`
  - `pyproject.toml` 增加 `macos` optional extra；`Makefile` 增加 `macos-app` / `macos-notarize`
  - README / README.zh-CN 增加桌面包构建、Developer ID 签名、公证说明

- **v1.7.1** — macOS 公证 profile 路径修复
  - 修复 `make macos-notarize` 使用 `APPLE_NOTARY_PROFILE` / `--notary-profile` 时，日志脱敏代码引用未定义 `password` 导致 `NameError`，公证提交前崩溃

- **v1.7.2** — macOS DMG 分发包
  - 新增 `make macos-dmg`，生成带 `/Applications` 快捷方式的拖拽安装 DMG
  - `make macos-notarize` 改为同时产出已公证并 stapled 的 `dist/FM2note-macos.dmg`
  - 修复 zip 产物在 app stapler 之前生成的问题：现在 app staple 后会重新生成 `dist/FM2note-macos.zip`

- **v1.8.0** — macOS 双版本分发 + 桌面/后台状态解耦
  - DMG 构建改用 `dmgbuild` 直接写 Finder icon-view 布局；打开后呈现 `FM2note.app` → `Applications` 的标准拖拽安装窗口，避免依赖 Finder AppleScript 自动化
  - 新增发行 profile：`--profile-dir` 把 `config/config.yaml`、`config/subscriptions.yaml`、`.env` 复制进 `.app/Contents/Resources/FM2noteProfile`，桌面 App 首次启动时只复制一次且不覆盖用户修改
  - 新增 `--release-suffix` 与 `make macos-dmg-girlfriend` / `make macos-notarize-girlfriend`，私有预置版默认读取被 git 忽略的 `packaging/profiles/girlfriend`
  - 公众版新装不再默认使用 `macroclaw.app` RSSHub；订阅页只从环境变量、已有订阅注释或订阅 URL 推断 RSSHub
  - `/api/service/status` 返回 `desktop_app`，顶部 chip 和设置页文案改为区分“桌面 App 正在运行”和“后台自动检查 daemon 是否开启”

- **v1.8.1** — DMG 拖拽箭头
  - DMG 背景增加 `FM2note.app` 指向 `Applications` 的安装箭头，减少用户不知道要拖拽的情况
  - `--profile-dir` 打包现在必须显式传 `--allow-visible-profile` / `FM2NOTE_ALLOW_VISIBLE_PROFILE=1`，因为 profile 里的 Obsidian 路径、RSSHub 地址、API key、token 和注释都会在 DMG/App 包里可见

- **v1.8.2** — 后台自动检查按钮修复
  - 打包后的 macOS 桌面 App 中，`立即检查一次` / `开机自启` / `关闭自启` 现在通过冻结可执行文件的 CLI 模式执行，不再打开第二个桌面窗口
  - launchd plist 在 frozen `.app` 下写入 `FM2note serve`，不再写 `FM2note main.py serve`，后台 daemon 能真正进入 `serve` 模式
  - 补系统性测试：launcher 参数路由、launchd `ProgramArguments`、service 命令选择、poll-now spawn、设置页按钮默认行为

## Current Version

v1.8.2 — 后台自动检查按钮修复
