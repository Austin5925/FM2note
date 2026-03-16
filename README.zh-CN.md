# FM2note

[English](README.md) | [中文](README.zh-CN.md)

> 自动转写播客并保存为 Obsidian 笔记。

FM2note 监听播客 RSS 更新，使用云端 ASR 转写，生成 AI 摘要，直接写入 Obsidian vault。

## 功能

- **RSS 监听** — 支持任意 RSS/Atom feed，自动检测新剧集
- **多 ASR 引擎** — FunASR、Paraformer、通义听悟、百炼、OpenAI Whisper
- **AI 摘要** — 章节速览 + 关键词（Poe / OpenAI / DeepSeek / Groq 等）
- **直写 Obsidian** — Markdown + YAML frontmatter
- **模板可定制** — 自定义笔记模板路径和章节标签
- **字幕检测** — 有字幕时跳过 ASR（节省成本）
- **自动重试** — 失败的剧集在下次轮询时重试
- **自托管** — 数据完全在你的设备上

## 架构

```
服务器（可选）                 本地 Mac
┌──────────────────┐      ┌────────────────────────────┐
│  RSSHub + Redis  │      │  fm2note (Python 原生进程)   │
│  (Docker, 7x24)  │◄────│  launchd/systemd 自启        │
│                  │      │          │                  │
└──────────────────┘      │          ▼                  │
                          │  云端 ASR + AI 摘要          │
                          │          │                  │
                          │          ▼                  │
                          │  Obsidian vault (本地)       │
                          └────────────────────────────┘
```

- **服务器**（可选）：运行 RSSHub + Redis（小宇宙 RSS 代理）
- **本地**：fm2note 进程（ASR 转写 + AI 摘要 + 笔记生成 + 写入 vault）

标准 RSS feed 无需 RSSHub，可直接使用。

## 快速开始

### 安装

```bash
pip install fm2note
```

或从源码安装：

```bash
git clone https://github.com/Austin5925/FM2note.git
cd FM2note
pip install -e .
```

### 初始化

```bash
fm2note init
```

交互式生成 `config/config.yaml`、`config/subscriptions.yaml` 和 `.env`。

### 配置

1. 编辑 `.env` — 填入 API Key：

```bash
export DASHSCOPE_API_KEY=sk-xxx          # FunASR/通义听悟必需
export OBSIDIAN_VAULT_PATH="/path/to/vault"

# AI 摘要（选一个，都不填则跳过摘要）
export POE_API_KEY=pk-xxx                # Poe 订阅
export OPENAI_API_KEY=sk-xxx             # OpenAI / DeepSeek / Groq
```

2. 编辑 `config/subscriptions.yaml` — 添加播客：

```yaml
podcasts:
  # 标准 RSS feed（直接使用）
  - name: "我的播客"
    rss_url: "https://example.com/feed.xml"
    tags: ["tech"]

  # 小宇宙播客（通过 RSSHub）
  - name: "非共识的20分钟"
    rss_url: "https://your-rsshub.com/rsshub/xiaoyuzhou/podcast/PODCAST_ID"
    tags: ["finance"]
```

### 运行

```bash
source .env
fm2note run-once     # 手动执行一次
fm2note serve        # 持续轮询（每 3 小时）
```

## ASR 引擎

| 引擎 | 单价/小时 | 特点 | 适用场景 |
|---|---|---|---|
| FunASR（默认） | ~0.79 元 | 中文优化，支持方言 | 中文播客 |
| Paraformer | ~0.29 元 | 低成本，7+ 语言 | 预算有限 |
| 通义听悟 | ~3.00 元 | ASR + AI 摘要一体 | 一站式方案 |
| 百炼 | ~0.79 元 | DashScope SDK，最长 12h/2GB | 长时音频 |
| Whisper API | ~$0.36 | 多语言 | 英文播客 |

在 `config/config.yaml` 中设置 `asr_engine`。所有 DashScope 引擎共用同一个 `DASHSCOPE_API_KEY`。

## AI 摘要

FM2note 支持多种 AI 摘要提供商，默认**自动检测**可用的 API Key：

| 提供商 | 配置 | API Key | 默认模型 |
|---|---|---|---|
| Poe | `SUMMARY_PROVIDER=poe` | `POE_API_KEY` | GPT-5.4 |
| OpenAI | `SUMMARY_PROVIDER=openai` | `OPENAI_API_KEY` | gpt-4o-mini |
| DeepSeek/Groq/Ollama | `SUMMARY_PROVIDER=openai` + `SUMMARY_BASE_URL=...` | `OPENAI_API_KEY` | 自定义 |
| 不使用 | `SUMMARY_PROVIDER=none` | — | — |
| 自动（默认） | `SUMMARY_PROVIDER=auto` | 任一可用 | 自动 |

不配置任何摘要 Key 时，仅输出转写文本，不报错。

## 模板定制

默认笔记模板使用中文标签。可自定义：

```yaml
# config.yaml
template_path: "templates/my_custom_note.md.j2"
```

参见 `src/writer/markdown.py` 中的 `DEFAULT_LABELS` 字典了解可覆盖的标签。

## 部署

### 自启服务

```bash
fm2note install-service    # macOS (launchd) 或 Linux (systemd)
fm2note uninstall-service  # 卸载服务
```

### RSSHub（小宇宙播客必需）

```bash
# 在你的服务器上：
docker compose up -d
```

**Cloudflare 用户**：RSSHub 默认端口 1200 不在 Cloudflare 代理范围内。解决方案：
1. **Nginx 反代**（推荐）：`location /rsshub/ { proxy_pass http://127.0.0.1:1200/; }`
2. **改用 8080 端口**：docker-compose 端口改为 `8080:1200`

### 播客 ID 获取

在浏览器打开播客页面：`https://www.xiaoyuzhoufm.com/podcast/PODCAST_ID`，复制 PODCAST_ID。

## 成本估算（20 集/月，每集约 1 小时）

| 方案 | 月费 |
|---|---|
| FunASR + Poe/OpenAI 摘要 | ~16 元 |
| Paraformer + Poe/OpenAI 摘要 | ~6 元 |
| 通义听悟（一站式） | ~55 元 |

## 开发

```bash
pip install -e ".[dev]"
make lint        # 代码检查
make test        # 运行测试（213+ 个）
make test-cov    # 覆盖率报告
make format      # 自动格式化
make build       # 构建 sdist + wheel
```

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE)
