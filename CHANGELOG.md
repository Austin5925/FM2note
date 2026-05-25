# Changelog

All notable changes to FM2note will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.6.3] - 2026-05-25

### Fixed
- **Codex audit S1 (LOW)**: 恶意 cache row 设 `podcast_name='..'` 时 `_safe_filename` 之前只过滤 `/` 等非法字符不过滤纯 dot → 会让 target_dir 解析到 vault 父目录。修复：(a) `_safe_filename` 把 `"."`/`".."`/全 `.` 输入映射成 `"untitled"`；(b) write 前 `is_relative_to(podcast_root)` defense-in-depth 检查，越界返回 `reason=path_escapes_vault` 不写
- **Codex audit S2 (LOW)**: `_normalize_guid` 之前用 `str.replace('://', ':/')` 会折叠 guid 任意位置的 `://`，对极少见的 opaque guid（如 `foo://bar://baz`）会误折叠 → 缓存查找静默 miss。修复：改用 `^scheme://` 前缀正则只折叠第一个 URI scheme 分隔符

### Added
- 3 个新测试：`_normalize_guid` 只折叠 leading scheme / `_safe_filename` 处理纯点输入 / download `podcast_name=".."` 不逃逸 vault
- 466 测试（463 + 3）全过

### Verified
- 端到端 smoke test 在本地（v1.6.2 launchd daemon + 新启动 web server）：healthz / cloud list / cloud download 全 PASS。daemon 自动发现 1 集新剧集并上传到云端（云端 66 → 67）

## [1.6.2] - 2026-05-25

### Fixed
- **`fm2note install-service` 在 macOS 12+ 静默失败**（launchd exit 78 EX_CONFIG，无 stderr 输出）。根因：launchd 的 `xpcproxy` 辅助进程在 Desktop / Documents / Downloads 下被 macOS Sandbox 拒绝 read-data，无法打开 `StandardOutPath` / `StandardErrorPath` → 进程根本起不来。`log show --predicate "eventMessage contains 'fm2note'"` 才能看到 `kernel: (Sandbox) System Policy: xpcproxy(...) deny(1) file-read-data .../logs/fm2note-stdout.log`。这版把 log 路径改到 macOS 信任的 `~/Library/Logs/fm2note/`（与 Apple 自家 daemon 一致），daemon 启动恢复正常。Linux 路径不变（仍是 `<workdir>/logs/`）
- 影响范围：任何项目在 `~/Desktop` / `~/Documents` 下的用户跑 `fm2note install-service` 都会撞这个；女朋友机器装"开机自启"开关也会触发，所以必须修

## [1.6.1] - 2026-05-25

### Fixed
- **GUI【云端】下载 guid-level 去重**：之前 download endpoint 只按 file path 查 vault 是否已有，命名风格不同就 false negative（`Ep 25｜油价` 全角 vs `Ep 25 _ 油价` ASCII 算两份）→ 重复 .md。这版 download 前扫该 podcast 文件夹所有 .md 的 `frontmatter.source`，按 normalized guid 去重；命中返回 `reason=already_exists_by_source`（含已存在文件路径），不发起 fetch、不写第二份
- 新 helper `_scan_existing_guids(podcast_dir)` 用 frontmatter 头 2KB 正则解 source（不引 pyyaml）+ `_normalize_guid` 把 `https://` 折成 `https:/` 与 server 存储格式对齐
- `overwrite=True` 仍能强刷（明示意图绕过 dedup）

### Added
- 5 个新测试：guid-level dedup / overwrite 绕 dedup / 空目录 helper / 无 frontmatter 文件跳过 / normalize idempotent
- 463 测试（458 + 5）全过

## [1.6.0] - 2026-05-25

### Added
- **GUI【云端】新页面** — 浏览共享缓存里所有已转录剧集，按节目分类显示，单/多选下载到本地 vault
- `src/web/templates/cloud.html` + `src/web/static/cloud.js` — folder/file 两级视图、全选/反选、覆盖已存在开关、按节目 + 文件夹结构写入 `<vault>/<podcast_dir>/<podcast_name>/<title>.md`
- `src/web/routes/cloud.py` — `GET /api/cloud/list?prefix=...&limit=...` + `POST /api/cloud/download {guids, overwrite}` (单次 ≤ 100 集)
- `src/shared_cache.py::SharedCacheClient.list_items(prefix, limit)` — client 端 LIST 调用，错误时返回空列表（与 fetch/upload 一致 swallow-all 风格）
- `SharedCacheClient.upload(..., podcast_name=, title=)` — 上传时带 metadata
- `src/episode_processor.py` — pipeline 上传时传 episode.podcast_name + episode.title
- **server v1.6.0** — `notes` 表新增 `podcast_name` + `title` 列（PRAGMA table_info 守卫的 idempotent migration）；`GET /cache/list` 端点；upsert 接受 metadata 字段（pre-v1.6 client 不带也兼容，旧行 podcast_name=NULL）
- 9 个新测试覆盖 cloud routes: 未配置 cache 时 GET 返回 reason=cache_unconfigured / POST 503、空 guids 400、>100 集 400、按节目分组写入、覆盖默认 false、文件名 sanitize、cache miss 报告

### Changed
- 桌面包 `.env` `SHARED_CACHE_URL`/`TOKEN` 默认指向 macroclaw（v1.5.4 已加，v1.6.0 配套 LIST + 下载）
- 458 测试（+9）全过；端到端 client↔server cloud LIST + 上传 metadata + 批量 backfill 23 集到生产 cache 验证

## [1.5.4] - 2026-05-25

### Added
- **共享转录缓存 sidecar 正式部署到生产**（macroclaw.app/fm2note-cache），完成 v1.4.16 client 端 + server 端的全闭环
- `src/monitor/state.py::has_any_recorded_in(guids)` — 批量 SQL `IN ?` 查询，supports daemon auto-protect
- `src/monitor/rss_checker.py::_auto_protect_sub(sub, feed)` — daemon 启动自检：任何 state.db 里完全没记录的 sub → mark 当前 feed 所有集为 `backfill_skipped`，统一手动编辑 yaml 加订阅与 GUI POST `/api/subscriptions` 的语义保护（不再"yaml 加新订阅 → 下次 poll 烧光额度"）
- preview API 返回新字段 `missing_duration_count`（feed 里没 itunes:duration 的集子数），UI 现在显示"⚠️ 含 N 集未提供时长，实际可能更贵"
- `server/README.md` — cache_sidecar 部署清单 + 协议参考 + 集成位置 + 故障排查
- `tests/test_state.py` 加 4 个 `has_any_recorded_in` 用例；`tests/test_rss_checker.py` 加 3 个 `_auto_protect_sub` 用例。共 449 测试

### Fixed
- **`server/cache_sidecar.py::post_cache`** 没用 `db_lock`（v1.4.16 Code Review fix #1 只 patch 了 GET 路径）→ 并发 upload 可能 interleave aiosqlite execute/commit，丢失一方的写。已加 lock
- **GUI 加订阅弹窗 z-index 被 sub-modal 遮在下面**（macOS PyWebView 焦点 quirk）→ 打开 backfill modal 前先 `modal.classList.add('hidden')` 让 sub-modal 消失（`src/web/static/subscriptions.js`）
- **preview 估算 UI 显示不明确**：现在显示"约 ¥X.XX（XX 分钟 · funasr 计价 · 不含 AI 摘要）"，并在 feed 里有 0-duration 集子时加 orange 警告
- `preview_sub` 的 `try/except` 用 `logger.exception` 代替 `logger.warning("...", type(e).__name__)`，下次再有 TypeError 类的 silent fallback 才能从日志看到完整 stack

### Changed
- `RSSChecker.check_all` 重构：每个 sub 单次 fetch，feed 复用给 `_auto_protect_sub` + `_extract_new_episodes`（避免引入 auto-protect 后的 double-fetch）。`_check_feed` 保留为 backward-compat thin wrapper
- 前端 backfill modal 现在显示一行 hint："podcast feed 通常只返回最近 ~15-20 集，更早的历史无法通过订阅抓取（可在【转录】页粘单集链接补转）"
- 桌面包 `.env` 默认填 `SHARED_CACHE_URL` + `SHARED_CACHE_TOKEN`，开箱即用共享缓存

## [1.5.3] - 2026-05-25

### Added
- `src/web/services/log_buffer.py` — loguru sink → 10k 上限环形 buffer，`GET /api/logs?after_seq=N` 增量拉
- 设置页【日志面板】3 秒轮询 auto-refresh，消除 PyWebView 桌面壳"看不见日志"的工程债
- `POST /api/service/poll-now` — detached spawn `fm2note run-once`，fire-and-forget。设置页新增"立即检查一次"按钮
- 顶部 daemon 健康徽章 60s 轮询 `/api/service/status`：● 运行中 · 上次 X 分钟前
- `/api/service/status` 新增 `last_run_at` / `next_run_estimate_at` / `poll_interval_hours` 字段

### Fixed
- 端到端 smoke test 验证 healthz / settings / logs / status / poll-now 五端点全过

## [1.5.2] - 2026-05-25

### Added
- `src/app_paths.py` — AppPaths 单例：所有文件路径（config/subscriptions/.env/db/pending/tmp/logs）从单一来源解析，`FM2NOTE_HOME` env 可覆盖
- `src/web/services/state_singleton.py` — FastAPI 生命周期内的 StateManager 单例
- `StateManager.get_recent_history(limit, include_backfill_skipped=False)` — SQL `ORDER BY` + `LIMIT` + filter，替代 Python 端全表 sort+slice
- 共 431 测试（+5 个 history limit / 排序 / filter / mark_status 事务）

### Fixed
- `src/summarizer/pending.py::PENDING_DIR` 不再 CWD-relative — 修复 `fm2note app` Finder 双击启动时 pending summaries 写到 `/data/...` 的灾难（A5）
- `POST /api/subscriptions/test` 的 `feedparser.parse` 包 `asyncio.to_thread`（v1.4.15 漏修的最后一处 A1/B1/C1）
- `StateManager.mark_status` 用 `BEGIN IMMEDIATE` 包 SELECT+UPDATE/INSERT，并发 connection retry_count 增量不再丢、不再 IntegrityError（Codex 找的并发 race）
- 测试 `conftest.py` 新增 `_reset_app_paths` + `_reset_state_singleton` autouse fixtures

### Changed
- `history.py` / `subscription preview` / `subscription add` 三处不再各自 open+close aiosqlite，全部走 singleton 复用一条连接

## [1.5.1] - 2026-05-25

### Fixed
- `DEFAULT_VAULT_PATH` 从硬编码个人路径改为通用 `~/Documents/Obsidian`，避免 pip 包泄露作者用户名 + 误导新用户写入不存在路径（Code Review A4）
- `pyproject.toml` 配置 `.env.example` 一起打进 wheel，否则 `fm2note init` 在 pip-installed 环境只生成单 key 的最小 `.env`（Codex 全仓审计）
- `CHANGELOG.md` 从 v1.4.11 起补完整（pyproject 链接此文件，之前是 stub，新用户点开 PyPI changelog 看不到）

### Changed
- `fm2note init` 不再交互式 prompt，改为静默生成骨架文件并提示打开 GUI（GUI 时代 init 的所有输出 v1.4.12 起都能在设置页改）
- 设置页新增 "开机自启" 开关，调 `install-service` 后端化，GUI 用户无须开终端

## [1.5.0] - 2026-05-25

### Changed
- 抽 `src/episode_processor.py::EpisodeProcessor` 作为 episode 处理的唯一来源，消除 `transcribe_flow.py` 和 `pipeline.py` 90% 重复
- `Pipeline.process_episode` 现在是 `EpisodeProcessor.process` 的薄包装
- `transcribe_flow.transcribe_single_url` 同样委托给 processor
- `ProcessingOptions` 控制单 URL vs daemon 的差异化行为（cache fetch / MCP dedup 等）

### Added
- `subscribe_daemon_progress()` Pipeline daemon 进度全局广播，GUI 历史页可实时显示 daemon 处理进度（v1.5.3 接入）
- TingWu 等内置摘要引擎现在会发 `summary, skipped, 引擎内置摘要` 事件，GUI 进度条不再卡 asr 阶段

### Fixed
- `mark_status("done")` 缺失的 `podcast_name` / `title` 字段（Code Review A2），retry edge case 时 history 显示空已修
- 删除 `Pipeline._downloader` 死代码（Codex 全仓审计）

## [1.4.16] - 2026-05-25

### Added
- 转录结果共享上传缓存：服务端 sidecar (`server/cache_sidecar.py`, FastAPI + SQLite + Bearer auth) + 客户端 (`src/shared_cache.py`)
- pipeline 写完笔记后 fire-and-forget upload；rss_checker 处理新集前先 fetch，命中跳过 ASR + 摘要
- 部署文件 `server/Dockerfile.cache` + `server/docker-compose.cache.yaml`

### Fixed
- 双线审计：server 单 aiosqlite 连接并发不安全 → 加 lock；`_ct_equal` 时序泄漏 → `hmac.compare_digest`；cache-hit 路径 `FileExistsError` → idempotent guard；body-size pre-parse cap → Content-Length middleware

## [1.4.15] - 2026-05-25

### Added
- `POST /api/subscriptions/preview` 返回 feed 中 episode count / unprocessed count / 估算成本
- `POST /api/subscriptions` 必填 `backfill_strategy`：`all` / `new_only` / `recent_n` / `since_date`
- state.db 新状态 `backfill_skipped`（被 `is_processed` 视为已处理）
- `RSSChecker` 加 `subs_provider` 钩子，每次 poll 重读 yaml，Web UI 改订阅无须重启 daemon
- GUI 订阅页 add 流程：保存 → preview → 弹策略选择对话框 → 真正 add

### Fixed
- 双线审计：feedparser.parse 包 `to_thread`；rss_url 校验 scheme（防 SSRF）；`mark_backfill_skipped` 用 `INSERT OR IGNORE`；空 vault / 相对路径拒绝；多层引号 strip；`StateManager.mark_backfill_skipped` 不覆盖 `done` 行；feedparser 失败时不允许 add（避免静默 reintroduce 烧额度）

## [1.4.14] - 2026-05-25

### Fixed
- `test_stale_env_warning_fires_only_once` 之前只检查 flag 是 True，但 flag 在任何 `load_config` 都翻 True（与有无 stale env 无关），改为用 loguru sink 真正统计 warning 调用次数
- `conftest.py` 加 `_reset_legacy_env_warning` autouse fixture，避免模块级 dedup flag 跨测试泄漏
- `devdocs/help.md` + `README.zh-CN.md` 同步 v1.4.12 的 env/yaml 边界（配置表拆为 yaml-only / env-only 两表）
- `test_two_phase_commit_*` 加 yaml-was-committed assertion
- `_clean_path_input` 后 `Path(".")` / 相对路径仍能过校验 → silently 写到 CWD。新增 `is_absolute()` 守卫

## [1.4.13] - 2026-05-25

### Fixed
- `fm2note init` 模板 `.env` 删除残留的 `export LOG_LEVEL=INFO`
- `scripts/com.fm2note.serve.plist.template` 删除 `OBSIDIAN_VAULT_PATH` / `LOG_LEVEL` env 项
- README.md / README.zh-CN.md 同步 v1.4.12 的 env / yaml 边界
- `_clean_path_input` / 前端 `cleanPath` 支持多层引号 strip
- 健康自检 touch 探针包 `try/finally`
- 空 vault_path 漏洞修复 + stale-env warning 模块级去重 + 补 yaml 持久化测试

## [1.4.12] - 2026-05-25

### Changed
- 环境变量一刀切清理：所有非敏感配置改为 yaml-only（vault_path / podcast_dir / asr_engine / summary_* / log_level）
- 所有敏感凭据保持 env-only（DashScope/Poe/OpenAI key、Aliyun AK/SK、TingWu AppId）
- 设置页新增 `vault_path_default` 字段做 placeholder + "使用默认" 按钮
- `fm2note init` 不再写 `OBSIDIAN_VAULT_PATH` 到 `.env`

### Fixed
- 核心 bug：vault_path env override 导致 Web UI 改 yaml 后被 env 反向覆盖，用户看到 "保存成功后刷新又变回去"

## [1.4.11] - 2026-05-25

### Fixed
- 设置页 vault_path 容错：粘贴带 `'…'` / `"…"` 的路径自动去引号（后端 + 前端双保险）
- `PermissionError` / `FileNotFoundError` 走友好提示（指引 macOS "完全磁盘访问" 权限）
- 健康自检改为实际 touch 写测试，识别 macOS TCC 沙箱拦截

## [1.4.10] - 2026-05-24

### Fixed
- 本机全局 `web3` 安装的 `pytest_ethereum` 插件与 `eth_typing` 版本不兼容，会在 pytest 自动加载阶段拦截 `make test`
- 在项目 pytest 配置中禁用无关的 `pytest_ethereum` 插件，保留 `make test` 原命令不变

## [1.4.9] - 2026-05-24

### Added
- 订阅页新增“粘贴链接自动识别”：支持小宇宙播客页、剧集页、分享文本、已有 RSSHub URL，自动生成订阅名称和最终 RSS 地址
- 新增 `/api/subscriptions/defaults` 和 `/api/subscriptions/resolve`，前端可直接拿默认 RSSHub 地址并解析用户粘贴内容
- 默认 RSSHub 地址面向本地家庭使用预填为 `https://macroclaw.app/rsshub`，仍可在界面中手动覆盖

### Changed
- 订阅弹窗从手动填 RSS URL 改为“先粘贴播客链接”的主流程，保留最终 RSS 地址和名称的可编辑兜底

## [1.4.8] - 2026-05-24

### Fixed
- 历史页"看笔记"按钮在 `fm2note app` (PyWebView) 下点击无反应：
  - 根因：`window.location.href = "obsidian://..."` 在嵌入 WebKit 里不会触发 OS 协议处理器
  - 修法：服务端在 history 响应里直接算好 `obsidian_url`，前端用 `<a target="_blank" rel="noopener">`，由 OS 接管自定义协议
- 转录完成卡片的"在 Obsidian 中打开"也加上 `target="_blank"`（同样的潜在问题，预防性修复）

### Refactored
- 抽取 `src/web/services/obsidian_url.py::build_obsidian_url()`，供 transcribe 和 history 路由共用（之前 transcribe 内部有 `_make_obsidian_url`，history 在前端 JS 重复实现一次，三处逻辑不一致）

## [1.4.7] - 2026-05-24

### Changed
- 边牧从 header 挪到"开始转录"按钮下方居中，从 48×36 放大到 128×128（约 4× 大小）
- viewBox 由 32×24 改 32×32（增加纵向空间放下坐姿姿态）
- 姿态由侧站改为坐姿 — 修复 v1.4.5 "看起来像马" 的反馈：
  · 头部明显增大（占整体 ~30%，原 ~20%）
  · 胸毛白色蓬松（区别于光滑马身）
  · 前腿短而垂直、后腿盘坐（破除马的四足对称感）
  · 立耳上方加 1 像素尖端突出
  · 蜷曲短尾在身后（替代原"水平鞭尾"）
- bark 气泡字号 10→14、padding 加大、动画位移翻倍以匹配更大的狗

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
