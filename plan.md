# FM2note 工程实施计划

## 项目概述

将小宇宙 FM 播客自动转化为 Obsidian 笔记的全自动管线。
架构：RSS 监听 → 音频 URL 直传通义听悟 API（转写 + AI 摘要，无需先下载音频） → Obsidian Markdown。
部署：Linux 服务器（已有 React+Go+PostgreSQL 实例），Docker 容器化。

### 关键调研结论

- **通义听悟 API（v2023-09-30）**：接受音频 URL 直传，无需先下载。转写 0.6 元/小时 + AI 功能各 0.064 元/小时，20 集/月约 14.56 元。新用户 90 天免费。最长 6 小时，500MB。结果通过 OSS 签名 URL 返回。
- **阿里云百炼 ASR**：`dashscope` SDK，模型 `qwen3-asr-flash-filetrans`，最长 12 小时/2GB，约 0.79 元/小时，10 小时免费额度。仅转写，无 AI 摘要。
- **RSSHub 小宇宙路由**：`/xiaoyuzhou/podcast/:id`，无需 Puppeteer/auth，内存约 300-400MB。

---

## 版本规范

采用语义化版本 `vX.Y.Z`：

- **X**：架构性变更（如更换 ASR 引擎）
- **Y**：新功能（如新增 AI 摘要）
- **Z**：Bug 修复、小优化

版本号维护在 `src/version.py` 中，每次 phase 完成后 bump minor 版本。

---

## 版本控制与 CI 规则

每次代码变更完成后必须执行：

1. `make lint` — 代码规范检查通过
2. `make test` — 全部测试通过
3. `git add <相关文件>` — 只添加相关文件
4. `git commit -m "vX.Y.Z: 描述"` — commit 到 master
5. `git push origin master` — 推送到远程
6. `make deploy` — Docker 重建部署到服务器

**硬性规则**：

- 测试不通过不得 commit
- `.env` 文件永远不得 commit
- 不使用 feature 分支（直接 commit 到 master，简化流程）
- 每个版本在 CLAUDE.md 的 Version History 中记录变更摘要

---

## 技术栈

| 层            | 技术                                                                            |
| ------------- | ------------------------------------------------------------------------------- |
| 语言          | Python 3.11+                                                                    |
| RSS 解析      | `feedparser`                                                                    |
| HTTP 客户端   | `httpx`（async，支持断点续传）                                                  |
| ASR 转写      | 通义听悟 API v2023-09-30（`aliyun-python-sdk-core`，ROA 签名）                  |
| 备选 ASR      | 阿里云百炼（`dashscope` SDK，`qwen3-asr-flash-filetrans`） / OpenAI Whisper API |
| 模板渲染      | Jinja2                                                                          |
| 状态管理      | SQLite（`aiosqlite`）                                                           |
| 调度          | APScheduler（进程内 cron）                                                      |
| 日志          | `loguru`                                                                        |
| 测试          | `pytest` + `pytest-asyncio` + `pytest-cov`                                      |
| 代码规范      | `ruff`（lint + format）                                                         |
| 容器化        | Docker + docker-compose                                                         |
| Obsidian 集成 | 直接写 .md 文件 + Obsidian MCP 辅助去重                                         |

---

## 目录结构

```
FM2note/
├── config/
│   ├── config.yaml              # 全局配置（vault 路径、API keys 引用、轮询间隔）
│   └── subscriptions.yaml       # 订阅的播客列表及 RSS 地址
├── src/
│   ├── __init__.py
│   ├── version.py               # 版本号常量
│   ├── config.py                # 配置加载与验证
│   ├── models.py                # 数据模型（Episode, Transcript, Note）
│   ├── monitor/
│   │   ├── __init__.py
│   │   ├── rss_checker.py       # RSS 轮询、新剧集检测
│   │   └── state.py             # SQLite 状态管理（已处理剧集）
│   ├── downloader/
│   │   ├── __init__.py
│   │   └── audio.py             # 音频下载（断点续传、临时存储）
│   ├── transcriber/
│   │   ├── __init__.py
│   │   ├── base.py              # 转写器抽象基类（Protocol）
│   │   ├── tingwu.py            # 通义听悟 API 实现
│   │   ├── bailian.py           # 阿里云百炼 ASR 实现
│   │   ├── whisper_api.py       # OpenAI Whisper API 实现
│   │   └── factory.py           # 转写器工厂（按配置选择）
│   ├── writer/
│   │   ├── __init__.py
│   │   ├── markdown.py          # Jinja2 模板渲染
│   │   └── obsidian.py          # Obsidian vault 文件写入与组织
│   ├── pipeline.py              # 主管线编排（单集处理流程）
│   └── scheduler.py             # APScheduler 定时任务
├── templates/
│   └── podcast_note.md.j2       # Jinja2 笔记模板
├── tests/
│   ├── conftest.py              # 共享 fixtures
│   ├── test_config.py
│   ├── test_rss_checker.py
│   ├── test_state.py
│   ├── test_downloader.py
│   ├── test_transcriber.py
│   ├── test_markdown.py
│   ├── test_obsidian.py
│   ├── test_pipeline.py
│   └── benchmark/               # ASR 对比评测脚本
│       └── asr_benchmark.py
├── scripts/
│   └── benchmark_asr.py         # ASR 准确率评测入口
├── data/
│   ├── state.db                 # SQLite 数据库（gitignore）
│   └── tmp/                     # 临时音频文件（gitignore）
├── main.py                      # CLI 入口
├── Makefile                     # 构建/测试/部署命令
├── Dockerfile
├── docker-compose.yaml
├── requirements.txt
├── requirements-dev.txt
├── .env.example                 # 环境变量模板
├── .gitignore
├── CLAUDE.md
└── README.md
```

---

## Makefile 目标

```makefile
lint:        ruff check src/ tests/
format:      ruff format src/ tests/
test:        pytest tests/ -v --tb=short -x
test-cov:    pytest tests/ --cov=src --cov-report=term-missing
test-integ:  pytest tests/ -v -m integration
run:         python main.py run-once
serve:       python main.py serve
deploy:      ssh server "cd /opt/fm2note && git pull && docker compose up -d --build"
bump-patch:  python -c "..." && git add src/version.py
bump-minor:  python -c "..." && git add src/version.py
```

---

## 数据模型设计

### `src/models.py`

```python
@dataclass
class Episode:
    """从 RSS feed 解析出的单集信息"""
    guid: str              # RSS <guid> 或 <link>，唯一标识
    title: str             # 节目标题
    podcast_name: str      # 播客名称
    pub_date: datetime     # 发布日期
    audio_url: str         # 音频下载 URL（enclosure）
    duration: str          # 时长（itunes:duration）
    show_notes: str        # Show Notes（HTML）
    link: str              # 小宇宙节目页面链接

@dataclass
class TranscriptResult:
    """ASR 转写结果"""
    text: str              # 全文转写文本
    paragraphs: list[str]  # 按段落分割的文本列表
    summary: str | None    # AI 生成摘要（通义听悟）
    chapters: list[dict] | None  # 章节速览 [{title, summary}]
    keywords: list[str] | None   # 关键词

@dataclass
class ProcessedEpisode:
    """已处理剧集的状态记录"""
    guid: str
    podcast_name: str
    title: str
    status: str            # pending | downloading | transcribing | writing | done | failed
    error_msg: str | None
    retry_count: int
    created_at: datetime
    updated_at: datetime
```

---

## Phase 0：项目脚手架 → `v0.1.0`

### 目标

- [ ] 初始化 Python 项目结构
- [ ] 配置开发工具链（ruff, pytest, pre-commit）
- [ ] 创建 CLAUDE.md、Makefile、Docker 配置
- [ ] 配置文件加载模块
- [ ] 数据模型定义

### 实现细节

#### `src/version.py`

```python
VERSION = "0.1.0"
```

#### `src/config.py` — 配置加载

**`load_config(path: str) -> AppConfig`**

- 目的：从 `config.yaml` 加载并验证全局配置
- 实现：用 `pyyaml` 解析 YAML，环境变量覆盖敏感字段（API keys 从 `os.environ` 读取，不存 YAML）
- 返回 `AppConfig` dataclass，包含 vault_path、poll_interval、asr_engine 等

**`load_subscriptions(path: str) -> list[Subscription]`**

- 目的：加载播客订阅列表
- 实现：解析 `subscriptions.yaml`，每个条目包含 name、rss_url、tags

#### `config/config.yaml` 格式

```yaml
vault_path: "/path/to/obsidian/vault"
podcast_dir: "Podcasts" # vault 内子目录
poll_interval_hours: 3
asr_engine: "tingwu" # tingwu | bailian | whisper_api
temp_dir: "./data/tmp"
max_retries: 3
log_level: "INFO"
```

#### `config/subscriptions.yaml` 格式

```yaml
podcasts:
  - name: "播客名称A"
    rss_url: "https://your-rsshub/xiaoyuzhou/podcast/PODCAST_ID_A"
    tags: ["tech", "ai"]
  - name: "播客名称B"
    rss_url: "https://your-rsshub/xiaoyuzhou/podcast/PODCAST_ID_B"
    tags: ["business"]
```

### 测试与验收

- 验收：`make lint` 无报错，`make test` 通过，`docker build .` 成功
- 测试：`test_config.py` — 验证 YAML 加载、缺失字段报错、环境变量覆盖

---

## Phase 0.5：ASR 引擎对比评测 → `v0.2.0`

### 目标

- [ ] 实现 3 个云端 ASR 适配器的最小可用版本
- [ ] 从目标播客中取 3-5 段音频样本（各 5-10 分钟）
- [ ] 三条路径（通义听悟、阿里云百炼、OpenAI Whisper）分别转写
- [ ] 生成对比报告供人工评审准确率
- [ ] 调查 Typeless（消费级产品，无开发者 API，不适合自动化管线）

### 实现细节

#### `src/transcriber/base.py` — 转写器抽象

```python
class Transcriber(Protocol):
    """所有 ASR 引擎必须实现此协议"""

    async def transcribe(self, audio_url: str, language: str = "cn") -> TranscriptResult:
        """提交音频并返回转写结果（阻塞直到完成）"""
        ...

    @property
    def name(self) -> str:
        """引擎名称，用于日志和报告"""
        ...
```

#### `src/transcriber/tingwu.py` — 通义听悟实现

**`class TingwuTranscriber(Transcriber)`**

**`__init__(self, access_key_id, access_key_secret, app_key)`**

- 目的：初始化阿里云 SDK 客户端
- 实现：创建 `AcsClient(region_id='cn-beijing', credential=AccessKeyCredential(...))`

**`async def transcribe(self, audio_url, language) -> TranscriptResult`**

- 目的：提交音频 URL 到通义听悟，轮询直到完成，返回结构化结果
- 实现：
  1. 构建请求体：`PUT /openapi/tingwu/v2/tasks?type=offline`（域名 `tingwu.cn-beijing.aliyuncs.com`，版本 `2023-09-30`）
  2. Input 参数：FileUrl（直接传播客音频 URL，无需先下载）、SourceLanguage='cn'、TaskKey（唯一标识）
  3. Transcription 参数：DiarizationEnabled=True（说话人分离）
  4. AI 功能参数：SummarizationEnabled=True（Types: Paragraph, QuestionsAnswering, MindMap）、AutoChaptersEnabled=True（章节速览）
  5. 提交任务，获取 TaskId
  6. 轮询 `GET /openapi/tingwu/v2/tasks/{TaskId}`，间隔 30 秒，最长等待 180 分钟（官方最长处理时间 3 小时）
  7. 状态 COMPLETED → 结果字段包含 OSS 签名 URL（Transcription、Summarization、AutoChapters），需 httpx.get 逐一获取 JSON
  8. 状态 FAILED → 抛出 TranscriptionError
  9. QPS 限制：CreateTask 20/s，GetTaskInfo 100/s

**`_build_task_body(self, audio_url, language) -> dict`**

- 目的：构建 CreateTask 请求体
- 实现：组装 Input（FileUrl, SourceLanguage, TaskKey）+ Parameters（Transcription, Summarization, AutoChapters）

**`_poll_task(self, task_id, timeout, interval) -> dict`**

- 目的：轮询任务状态直到完成或超时
- 实现：循环 GET 请求，检查 Status 字段，超时抛出 TimeoutError

**`async def _fetch_oss_result(self, url: str) -> dict`**

- 目的：从通义听悟返回的 OSS 签名 URL 获取实际结果 JSON
- 实现：`httpx.get(url)` → `response.json()`，带超时和重试

**`_parse_result(self, raw_result) -> TranscriptResult`**

- 目的：将通义听悟原始响应解析为统一的 TranscriptResult
- 实现：
  1. 获取 Result 中的各 OSS URL（Transcription、Summarization、AutoChapters）
  2. 逐一 fetch JSON 内容
  3. 提取 Transcription 中的段落文本和时间戳
  4. 提取 Summarization 中的摘要文本
  5. 提取 AutoChapters 中的章节标题和摘要
  6. 组装为 TranscriptResult

#### `src/transcriber/bailian.py` — 阿里云百炼实现

**`class BailianTranscriber(Transcriber)`**

**`async def transcribe(self, audio_url, language) -> TranscriptResult`**

- 目的：使用 DashScope SDK 调用 qwen3-asr-flash-filetrans（最长 12 小时/2GB）
- 实现：
  1. `Transcription.async_call(model='qwen3-asr-flash-filetrans', file_urls=[audio_url])`
     - 要求 `X-DashScope-Async: enable`（SDK 自动处理）
     - 音频 URL 必须可公开访问
  2. 获取 `task_id`，轮询 `Transcription.fetch(task_id)` 每 2 秒，直到 SUCCEEDED/FAILED
  3. 结果含 `transcription_url`（OSS 签名 URL），fetch 获取 JSON
  4. 解析 JSON：`transcripts[0].text`（全文）、`sentences`（带时间戳的句子列表）
  5. 百炼 ASR 不含摘要/章节功能，summary 和 chapters 字段返回 None
  6. 参数：`channel_id=[0]`、`enable_itn=False`、`enable_words=True`（词级时间戳）

#### `src/transcriber/whisper_api.py` — OpenAI Whisper 实现

**`class WhisperTranscriber(Transcriber)`**

**`async def transcribe(self, audio_url, language) -> TranscriptResult`**

- 目的：使用 OpenAI Whisper API 转写音频
- 实现：
  1. 下载音频到本地临时文件
  2. 若文件 > 25MB，用 `pydub` 分片（每片 24MB）
  3. 逐片调用 `openai.audio.transcriptions.create(model="whisper-1", file=...)`
  4. 拼接所有分片结果
  5. summary 字段返回 None（Whisper 不含摘要）

#### `scripts/benchmark_asr.py` — 评测脚本

**`async def run_benchmark(audio_samples, engines) -> BenchmarkReport`**

- 目的：对相同音频用多个引擎转写，生成对比报告
- 实现：
  1. 遍历 audio_samples（播客音频片段 URL 列表）
  2. 对每个样本，并发调用所有 engines 的 `transcribe()`
  3. 记录：引擎名、耗时、字数、转写文本
  4. 输出 Markdown 报告到 `data/benchmark_report.md`
  5. 人工对比准确率后，在 config.yaml 中确定最终 asr_engine

### Typeless 结论

经调研，Typeless 是消费级 AI 转录工具（自动去除语气词、支持 100+ 语言），但**没有开发者 API**，不适合自动化管线集成。不纳入评测。

### 测试与验收

- 测试：`test_transcriber.py` — 用 mock HTTP 响应测试每个引擎的请求构建、轮询逻辑、结果解析、错误处理
- 验收：`make test` 通过 + 手动运行 `python scripts/benchmark_asr.py` 生成对比报告，人工确认最优引擎

---

## Phase 1：MVP 核心管线 → `v0.3.0`

### 目标

- [ ] RSS 解析与新剧集检测
- [ ] 音频下载（断点续传）
- [ ] ASR 转写（使用 Phase 0.5 确定的最优引擎）
- [ ] Markdown 笔记生成（Jinja2 模板）
- [ ] 写入 Obsidian vault
- [ ] 手动触发运行（`python main.py run-once`）

### 实现细节

#### `src/monitor/rss_checker.py` — RSS 监听

**`class RSSChecker`**

**`__init__(self, subscriptions: list[Subscription], state: StateManager)`**

- 目的：初始化 RSS 检查器
- 实现：保存订阅列表和状态管理器引用

**`async def check_all(self) -> list[Episode]`**

- 目的：检查所有订阅的 RSS feed，返回未处理的新剧集列表
- 实现：
  1. 遍历 subscriptions
  2. 对每个 RSS URL 调用 `_fetch_feed(url)`
  3. 解析每个 item 为 Episode 对象
  4. 通过 `state.is_processed(episode.guid)` 过滤已处理的
  5. 返回新剧集列表，按 pub_date 排序

**`_fetch_feed(self, url: str) -> feedparser.FeedParserDict`**

- 目的：获取并解析 RSS feed
- 实现：`httpx.get(url, timeout=30)` → `feedparser.parse(response.text)`
- 错误处理：网络异常重试 3 次（指数退避 2s/4s/8s）

**`_parse_episode(self, entry, podcast_name) -> Episode`**

- 目的：将 feedparser entry 转换为 Episode 数据模型
- 实现：
  - title: `entry.title`
  - audio_url: `entry.enclosures[0].href`
  - pub_date: `dateutil.parser.parse(entry.published)`
  - show_notes: `entry.summary` 或 `entry.content[0].value`（HTML → 纯文本用 `markdownify`）
  - duration: `entry.get('itunes_duration', '')`
  - guid: `entry.get('id', entry.link)`
  - link: `entry.link`

#### `src/monitor/state.py` — 状态管理

**`class StateManager`**

**`__init__(self, db_path: str)`**

- 目的：初始化 SQLite 连接，建表
- 实现：`aiosqlite.connect(db_path)`，执行 CREATE TABLE IF NOT EXISTS

**SQLite Schema:**

```sql
CREATE TABLE IF NOT EXISTS processed_episodes (
    guid TEXT PRIMARY KEY,
    podcast_name TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error_msg TEXT,
    retry_count INTEGER DEFAULT 0,
    note_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**`async def is_processed(self, guid: str) -> bool`**

- 目的：检查剧集是否已成功处理
- 实现：`SELECT 1 FROM processed_episodes WHERE guid=? AND status='done'`

**`async def mark_status(self, guid: str, status: str, error_msg: str = None)`**

- 目的：更新剧集处理状态
- 实现：INSERT OR UPDATE，同时更新 updated_at

**`async def get_failed(self, max_retries: int = 3) -> list[ProcessedEpisode]`**

- 目的：获取可重试的失败任务
- 实现：`SELECT ... WHERE status='failed' AND retry_count < ?`

#### `src/downloader/audio.py` — 音频下载

**`class AudioDownloader`**

**`__init__(self, temp_dir: str)`**

- 目的：初始化下载器，确保临时目录存在

**`async def download(self, audio_url: str, filename: str) -> Path`**

- 目的：下载音频文件到临时目录，支持断点续传
- 实现：
  1. 检查临时目录中是否有部分下载文件
  2. 有 → 发 Range 请求续传；无 → 全量下载
  3. 使用 `httpx.AsyncClient.stream('GET', url, headers={'Range': ...})`
  4. 流式写入文件，每 1MB flush 一次
  5. 下载完成后验证 Content-Length 一致性
  6. 返回本地文件路径

**`async def cleanup(self, filepath: Path)`**

- 目的：转写完成后删除临时音频文件

#### `src/writer/markdown.py` — Markdown 生成

**`class MarkdownGenerator`**

**`__init__(self, template_dir: str)`**

- 目的：初始化 Jinja2 环境，加载模板

**`def render(self, episode: Episode, transcript: TranscriptResult) -> str`**

- 目的：将剧集元数据和转写结果渲染为 Markdown 笔记
- 实现：加载 `podcast_note.md.j2` 模板，传入所有字段，返回渲染后的字符串

#### `templates/podcast_note.md.j2` — 笔记模板

```jinja2
---
title: "{{ episode.title }}"
podcast: "{{ episode.podcast_name }}"
date: {{ episode.pub_date.strftime('%Y-%m-%d') }}
duration: "{{ episode.duration }}"
source: "{{ episode.link }}"
tags:
  - podcast
  - {{ episode.podcast_name | replace(' ', '-') | lower }}
{% for tag in episode.tags %}
  - {{ tag }}
{% endfor %}
status: unread
created: {{ now.strftime('%Y-%m-%dT%H:%M:%S') }}
asr_engine: "{{ asr_engine }}"
---

# {{ episode.title }}

> **播客**：{{ episode.podcast_name }}
> **日期**：{{ episode.pub_date.strftime('%Y-%m-%d') }}
> **时长**：{{ episode.duration }}
> **链接**：[小宇宙]({{ episode.link }})

{% if transcript.summary %}
## AI 摘要

{{ transcript.summary }}

{% endif %}
{% if transcript.chapters %}
## 章节速览

{% for ch in transcript.chapters %}
### {{ ch.title }}

{{ ch.summary }}

{% endfor %}
{% endif %}
## Show Notes

{{ episode.show_notes }}

## 全文转写

{% for para in transcript.paragraphs %}
{{ para }}

{% endfor %}

---

_由 FM2note v{{ version }} 自动生成_
```

#### `src/writer/obsidian.py` — Obsidian 写入

**`class ObsidianWriter`**

**`__init__(self, vault_path: str, podcast_dir: str)`**

- 目的：初始化 vault 路径配置

**`def write_note(self, episode: Episode, content: str) -> Path`**

- 目的：将 Markdown 内容写入 Obsidian vault 的正确位置
- 实现：
  1. 构建路径：`{vault_path}/{podcast_dir}/{podcast_name}/{date} {title}.md`
  2. 文件名 sanitize：移除 `/\:*?"<>|` 等非法字符，截断至 200 字符
  3. 确保目录存在（`Path.mkdir(parents=True, exist_ok=True)`）
  4. 检查文件是否已存在（避免覆盖）
  5. 写入 UTF-8 编码的 .md 文件
  6. 返回写入的文件路径

**`def note_exists(self, episode: Episode) -> bool`**

- 目的：检查笔记文件是否已存在（双重去重，文件系统层）

#### `src/pipeline.py` — 主管线编排

**`class Pipeline`**

**`__init__(self, config, rss_checker, downloader, transcriber, md_generator, writer, state)`**

- 目的：组装所有模块

**`async def process_episode(self, episode: Episode) -> Path`**

- 目的：处理单集的完整流程
- 实现：
  1. `state.mark_status(guid, 'downloading')`
  2. `audio_path = await downloader.download(episode.audio_url, filename)`
  3. `state.mark_status(guid, 'transcribing')`
  4. `transcript = await transcriber.transcribe(episode.audio_url, 'cn')`
     - 注意：通义听悟直接接受音频 URL，无需先下载（如果音频 URL 可公开访问）
     - 若 URL 有防盗链，则先下载再上传到 OSS 获取临时 URL
  5. `state.mark_status(guid, 'writing')`
  6. `content = md_generator.render(episode, transcript)`
  7. `note_path = writer.write_note(episode, content)`
  8. `state.mark_status(guid, 'done', note_path=note_path)`
  9. `await downloader.cleanup(audio_path)`（如有本地文件）
  10. 返回 note_path
- 错误处理：任何步骤异常 → `state.mark_status(guid, 'failed', error_msg=str(e))`，重新抛出

**`async def run_once(self) -> list[Path]`**

- 目的：执行一次完整的检查-处理循环
- 实现：
  1. `new_episodes = await rss_checker.check_all()`
  2. `failed_episodes = await state.get_failed(max_retries=config.max_retries)`
  3. 合并两个列表
  4. 逐个调用 `process_episode()`（不并发，避免 API 限流）
  5. 记录日志：处理了 N 集，成功 M 集，失败 K 集
  6. 返回所有成功写入的 note_path 列表

#### `main.py` — CLI 入口

```python
import click

@click.group()
def cli():
    pass

@cli.command()
def run_once():
    """手动执行一次检查和处理"""
    asyncio.run(_run_once())

@cli.command()
def serve():
    """启动定时调度服务"""
    asyncio.run(_serve())

@cli.command()
@click.argument('audio_url')
def transcribe(audio_url):
    """单独测试转写一个音频 URL"""
    asyncio.run(_transcribe(audio_url))
```

### 测试与验收

- 测试：
  - `test_rss_checker.py`：mock feedparser 返回，验证 Episode 解析、去重过滤、网络异常重试
  - `test_state.py`：内存 SQLite 测试所有 CRUD 操作、状态流转、失败重试查询
  - `test_downloader.py`：mock httpx 响应，验证流式下载、断点续传、cleanup
  - `test_markdown.py`：验证模板渲染输出包含所有字段、frontmatter 格式正确
  - `test_obsidian.py`：使用 tmp_path fixture 验证文件写入、路径 sanitize、去重检查
  - `test_pipeline.py`：全 mock 集成测试，验证完整流程和状态流转
- 验收：`make test` 通过 + 手动 `python main.py run-once` 成功处理至少 1 集播客并在 Obsidian 中看到笔记

---

## Phase 2：自动化与可靠性 → `v0.4.0`

### 目标

- [ ] APScheduler 定时调度（每 3 小时检查一次）
- [ ] 完善错误重试机制（指数退避）
- [ ] 结构化日志系统（loguru → 文件 + stdout）
- [ ] Docker 容器化部署
- [ ] RSSHub 自建实例部署（Docker，同一服务器）
- [ ] 健康检查端点

### 实现细节

#### `src/scheduler.py` — 定时调度

**`class FM2noteScheduler`**

**`__init__(self, pipeline: Pipeline, config: AppConfig)`**

- 目的：初始化 APScheduler 调度器

**`def start(self)`**

- 目的：启动定时任务
- 实现：
  1. 创建 `AsyncIOScheduler`
  2. 添加 cron job：`scheduler.add_job(pipeline.run_once, 'interval', hours=config.poll_interval_hours)`
  3. 添加立即执行一次的 job（启动时马上跑一轮）
  4. 注册 SIGTERM/SIGINT 信号处理，优雅关闭

**`def stop(self)`**

- 目的：优雅停止调度器，等待当前任务完成

#### 错误重试增强（在 pipeline.py 中）

**`async def _with_retry(self, func, *args, max_retries=3) -> Any`**

- 目的：通用重试包装器
- 实现：指数退避（2^n 秒），可配置最大重试次数，记录每次重试日志

#### 日志配置

**`src/config.py` 中增加日志初始化：**

- loguru 配置：stdout（INFO）+ 文件轮转（`logs/fm2note.log`，10MB 轮转，保留 7 天）
- 结构化字段：timestamp、level、module、episode_guid（context）

#### Docker 部署

**`Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py", "serve"]
```

**`docker-compose.yaml`**

```yaml
services:
  fm2note:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - /path/to/obsidian/vault:/vault # 挂载 Obsidian vault
      - ./data:/app/data # 持久化 SQLite 和临时文件
      - ./logs:/app/logs # 持久化日志
    networks:
      - fm2note-net
    depends_on:
      - rsshub
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "0.5"

  rsshub:
    image: diygod/rsshub:latest # 基础镜像即可，小宇宙路由不需要 Puppeteer
    restart: unless-stopped
    ports:
      - "127.0.0.1:1200:1200" # 仅本地访问，不暴露公网
    environment:
      NODE_ENV: production
      CACHE_TYPE: redis
      REDIS_URL: "redis://redis:6379/"
      CACHE_EXPIRE: 1800 # 30 分钟，适合播客轮询频率
    networks:
      - fm2note-net
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "0.5"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:1200/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:alpine
    restart: unless-stopped
    volumes:
      - redis-data:/data
    networks:
      - fm2note-net
    deploy:
      resources:
        limits:
          memory: 128M

volumes:
  redis-data:

networks:
  fm2note-net:
    driver: bridge
```

#### RSSHub 部署要点

- 默认端口 1200，配置 `127.0.0.1:1200` 仅本地访问，不暴露公网
- 小宇宙路由：`http://rsshub:1200/xiaoyuzhou/podcast/{PODCAST_ID}`（容器间通过 service name 访问）
- **无需 Puppeteer/browserless**：小宇宙路由是标准 HTTP 抓取，不需要浏览器渲染
- 使用 Redis 缓存（跨重启持久化），比 memory 缓存更可靠
- 内存需求：RSSHub ~300MB + Redis ~100MB，总计约 400MB
- 与服务器上已有的 React+Go+PostgreSQL 共存，通过独立 docker network 隔离
- 建议用 Watchtower 或 cron 定期更新 RSSHub 镜像（路由可能因网站变更而失效）

#### 健康检查

在 `main.py serve` 模式中嵌入一个最小 HTTP 端点：

**`GET /health`** → 返回 `{"status": "ok", "version": "0.4.0", "last_check": "...", "episodes_processed": N}`

### 测试与验收

- 测试：
  - `test_scheduler.py`：验证 job 注册、启动/停止生命周期、信号处理
  - `test_pipeline.py` 增加：重试逻辑测试（模拟失败 → 重试 → 成功）
- 验收：
  1. `docker compose up -d` 启动成功
  2. `curl localhost:1200/xiaoyuzhou/podcast/SOME_ID` 返回 RSS XML
  3. FM2note 容器日志显示定时检查正常运行
  4. 模拟 ASR 失败，验证自动重试
  5. 连续运行 24 小时无异常

---

## Phase 3：AI 增强 → `v0.5.0`

### 目标

- [ ] 通义听悟 AI 摘要/章节速览/关键词（已在 Phase 0.5 中预埋参数，此处确保端到端生效）
- [ ] 小宇宙内置字幕检测与直接下载（跳过 ASR，降成本）
- [ ] Obsidian MCP 集成（搜索去重、标签管理）
- [ ] 笔记质量优化（show_notes HTML 清洗、段落智能分割）

### 实现细节

#### 字幕直接下载（可选路径）

在 `src/monitor/rss_checker.py` 中增加：

**`_check_subtitle_available(self, episode: Episode) -> str | None`**

- 目的：检测播客是否有内置字幕（小宇宙 API 或 RSS 扩展字段）
- 实现：检查 RSS `<podcast:transcript>` 标签，或尝试请求已知的字幕 URL 模式
- 有字幕 → 直接下载文本，设置 `episode.has_subtitle = True`

在 `src/pipeline.py` 中：

```python
if episode.has_subtitle:
    transcript = TranscriptResult(text=subtitle_text, paragraphs=..., summary=None, ...)
else:
    transcript = await transcriber.transcribe(...)
```

#### Obsidian MCP 集成

在 `src/writer/obsidian.py` 中增加：

**`async def search_existing(self, title: str) -> bool`**

- 目的：通过 Obsidian MCP 搜索是否已有同名笔记（第三层去重）
- 实现：调用 MCP `search_notes` 工具，匹配标题

**`async def update_tags(self, note_path: str, tags: list[str])`**

- 目的：通过 MCP 管理笔记标签
- 实现：调用 MCP `manage_tags` 工具

#### Show Notes 清洗

**`src/writer/markdown.py` 中增加 `_clean_show_notes(self, html: str) -> str`**

- 目的：将 HTML 格式的 show notes 转为干净的 Markdown
- 实现：使用 `markdownify` 库转换，去除多余空行、修复链接

### 测试与验收

- 测试：
  - 字幕检测逻辑单元测试
  - HTML → Markdown 清洗测试（多种 show notes 格式）
  - MCP 调用 mock 测试
- 验收：
  1. 有字幕的播客自动跳过 ASR
  2. AI 摘要和章节在笔记中正确显示
  3. Obsidian 中 tag 和文件夹结构正确

---

## Phase 4：生产加固 → `v1.0.0`

### 目标

- [ ] 通知系统（处理完成/失败时推送通知）
- [ ] 监控与告警（容器健康检查、磁盘空间监控）
- [ ] 多播客源支持预留（Apple Podcasts、Spotify RSS）
- [ ] 配置热更新（修改 subscriptions.yaml 后无需重启）
- [ ] 性能优化（并发处理多集、音频 URL 直传避免下载）
- [ ] 完善 README 文档

### 实现细节

#### 通知系统

**`src/notifier.py`**

**`class Notifier(Protocol)`**

- `async def notify(self, title: str, body: str, level: str)`

**`class LogNotifier(Notifier)`**

- 最简实现：仅写日志

**`class WebhookNotifier(Notifier)`**（可选）

- 通过 webhook URL 推送（兼容 Bark/ServerChan/Telegram）

#### 配置热更新

**`src/config.py` 中增加 `FileWatcher`**

- 使用 `watchdog` 库监听 `subscriptions.yaml` 变更
- 变更时重新加载订阅列表，无需重启服务

#### 多源预留

`subscriptions.yaml` 中增加 source_type 字段：

```yaml
podcasts:
  - name: "播客名称"
    source_type: "xiaoyuzhou" # xiaoyuzhou | apple | spotify | generic_rss
    rss_url: "..."
```

RSSChecker 根据 source_type 选择不同的解析策略。

### 测试与验收

- 测试：
  - 端到端集成测试：mock RSS → 下载 → mock ASR → 写入 → 验证文件
  - 配置热更新测试
  - 通知系统测试
- 验收：
  1. `make test` + `make test-integ` 全部通过
  2. 系统连续运行 7 天无异常
  3. 手动添加新播客到 subscriptions.yaml，无需重启即生效
  4. README 文档完善，新用户可独立部署

---

## TODO 总览

### Phase 0 — 脚手架 `v0.1.0`

- [ ] Python 项目结构初始化
- [ ] ruff + pytest + Makefile 配置
- [ ] config.yaml / subscriptions.yaml 加载模块
- [ ] 数据模型定义（Episode, TranscriptResult, ProcessedEpisode）
- [ ] CLAUDE.md 创建
- [ ] Dockerfile + docker-compose.yaml 骨架
- [ ] `make lint` + `make test` 通过

### Phase 0.5 — ASR 评测 `v0.2.0`

- [ ] Transcriber Protocol 抽象基类
- [ ] TingwuTranscriber 实现（CreateTask + 轮询 + 结果解析）
- [ ] BailianTranscriber 实现（DashScope SDK）
- [ ] WhisperTranscriber 实现（OpenAI API + 分片）
- [ ] TranscriberFactory 工厂模式
- [ ] benchmark_asr.py 评测脚本
- [ ] 用 3-5 段目标播客音频进行对比评测
- [ ] 人工评审确定最优引擎
- [ ] 单元测试覆盖所有引擎

### Phase 1 — MVP 核心管线 `v0.3.0`

- [ ] RSSChecker 实现（feedparser 解析 + 新剧集检测）
- [ ] StateManager 实现（SQLite CRUD + 状态流转）
- [ ] AudioDownloader 实现（httpx 流式 + 断点续传）
- [ ] MarkdownGenerator 实现（Jinja2 模板渲染）
- [ ] ObsidianWriter 实现（文件写入 + 路径 sanitize）
- [ ] Pipeline 编排（process_episode + run_once）
- [ ] main.py CLI（run-once + transcribe 命令）
- [ ] podcast_note.md.j2 模板
- [ ] 全模块单元测试
- [ ] 手动端到端验证

### Phase 2 — 自动化与可靠性 `v0.4.0`

- [ ] APScheduler 定时调度
- [ ] 指数退避重试机制
- [ ] loguru 结构化日志（文件轮转 + stdout）
- [ ] Docker 容器化 + docker-compose
- [ ] RSSHub 自建实例部署（同服务器 Docker）
- [ ] /health 健康检查端点
- [ ] SIGTERM 优雅关闭
- [ ] 24 小时稳定性验证

### Phase 3 — AI 增强 `v0.5.0`

- [ ] 通义听悟摘要/章节/关键词端到端生效
- [ ] 小宇宙字幕检测与直接下载
- [ ] Obsidian MCP 搜索去重
- [ ] Show Notes HTML → Markdown 清洗
- [ ] 笔记模板优化

### Phase 4 — 生产加固 `v1.0.0`

- [ ] 通知系统（Webhook/Bark）
- [ ] 配置热更新（watchdog）
- [ ] 多播客源预留（source_type）
- [ ] 容器健康监控
- [ ] 并发处理优化
- [ ] README 文档
- [ ] 7 天稳定性验证

---

## 外部 API 参考

| 服务           | 端点                                                                  | 鉴权                           | 关键限制                                          |
| -------------- | --------------------------------------------------------------------- | ------------------------------ | ------------------------------------------------- |
| 通义听悟 v2    | `PUT/GET tingwu.cn-beijing.aliyuncs.com/openapi/tingwu/v2/tasks`      | AccessKey ID + Secret + AppKey | CreateTask QPS=20, GetTask QPS=100, 最长 6h/500MB |
| 阿里云百炼 ASR | `POST dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription` | Bearer `DASHSCOPE_API_KEY`     | 最长 12h/2GB, 需 `X-DashScope-Async: enable`      |
| OpenAI Whisper | `POST api.openai.com/v1/audio/transcriptions`                         | Bearer `OPENAI_API_KEY`        | 单次 25MB，需分片                                 |
| RSSHub（自建） | `http://rsshub:1200/xiaoyuzhou/podcast/:id`                           | 无（容器内网）                 | 无                                                |
| Obsidian MCP   | 本地 MCP Server                                                       | 本地连接                       | 需 Obsidian 运行                                  |

## 成本估算（20 集/月，每集 1 小时）

| 方案                       | 月成本    | 功能                               |
| -------------------------- | --------- | ---------------------------------- |
| 通义听悟（转写+摘要+章节） | ~14.56 元 | 转写 + AI 摘要 + 章节速览 + 关键词 |
| 阿里云百炼 ASR             | ~15.8 元  | 仅转写（无 AI 功能）               |
| OpenAI Whisper             | ~43 元    | 仅转写（需分片处理）               |

**结论**：通义听悟性价比最高，功能最全。90 天免费试用足够完成全部开发和测试。

## 环境变量（.env）

```bash
# 通义听悟（主选）
ALIBABA_CLOUD_ACCESS_KEY_ID=
ALIBABA_CLOUD_ACCESS_KEY_SECRET=
TINGWU_APP_KEY=                    # 在通义听悟控制台创建项目获取

# 阿里云百炼（备选）
DASHSCOPE_API_KEY=                 # 百炼控制台获取

# OpenAI Whisper（备选）
OPENAI_API_KEY=

# Obsidian
OBSIDIAN_VAULT_PATH=/path/to/vault

# 日志
LOG_LEVEL=INFO
```

## 参考文档

- [通义听悟 API 接入文档](https://help.aliyun.com/zh/tingwu/tingwu-api)
- [通义听悟 CreateTask API](https://help.aliyun.com/zh/tingwu/api-tingwu-2023-09-30-createtask)
- [通义听悟离线转写指南](https://help.aliyun.com/zh/tingwu/offline-transcribe-of-audio-and-video-files)
- [通义听悟 SDK 安装](https://help.aliyun.com/zh/tingwu/install-the-sdk)
- [通义听悟计费规则](https://help.aliyun.com/zh/tingwu/pricing-and-billing-rules)
- [百炼 ASR 录音文件识别](https://help.aliyun.com/zh/model-studio/qwen-speech-recognition)
- [Qwen3-ASR-Toolkit](https://github.com/QwenLM/Qwen3-ASR-Toolkit)
- [RSSHub 部署文档](https://docs.rsshub.app/deploy/)
- [RSSHub 小宇宙路由源码](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/xiaoyuzhou/podcast.ts)
