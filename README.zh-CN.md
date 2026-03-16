# FM2note

[English](README.md) | [中文](README.zh-CN.md)

> 自动转写播客并保存为 Obsidian 笔记。

FM2note 监听播客 RSS 更新，使用云端 ASR 转写，生成 AI 摘要，直接写入 Obsidian vault。

## 功能

- **RSS 监听** — 自动检测任意 RSS/Atom feed 的新剧集
- **多 ASR 引擎** — FunASR、Paraformer、通义听悟、OpenAI Whisper
- **AI 摘要** — 章节速览 + 关键词（Poe / OpenAI）
- **直写 Obsidian** — Markdown + YAML frontmatter
- **字幕检测** — 有字幕时跳过 ASR（节省成本）
- **自动重试** — 失败的剧集在下次轮询时重试
- **自托管** — 数据完全在你的设备上

## 架构

```
服务器（可选）                 本地 Mac
┌──────────────────┐      ┌────────────────────────────┐
│  RSSHub + Redis  │      │  fm2note (Python 原生进程)   │
│  (Docker, 7x24)  │◄────│  launchd 自启，每 3h 轮询    │
│  :1200           │      │          │                  │
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
export POE_API_KEY=pk-xxx                # 可选：AI 摘要
```

2. 编辑 `config/subscriptions.yaml` — 添加播客：

```yaml
podcasts:
  - name: "非共识的20分钟"
    rss_url: "https://your-rsshub.example.com/xiaoyuzhou/podcast/PODCAST_ID"
    tags: ["finance", "macro"]
```

### 运行

```bash
source .env
fm2note run-once     # 手动执行一次
fm2note serve        # 持续轮询（每 3 小时检查）
```

## ASR 引擎

| 引擎 | 单价/小时 | 特点 | 适用场景 |
|---|---|---|---|
| FunASR（默认） | ~0.79 元 | 中文优化 | 中文播客 |
| Paraformer | ~0.29 元 | 低成本 | 预算有限 |
| 通义听悟 | ~3.00 元 | ASR + AI 摘要一体 | 一站式方案 |
| Whisper API | ~$0.36 | 多语言 | 英文播客 |

在 `config/config.yaml` 中设置 `asr_engine`。

## 部署

### 自启服务

```bash
fm2note install-service    # macOS (launchd) 或 Linux (systemd)
fm2note uninstall-service  # 卸载服务
```

### RSSHub（小宇宙播客必需）

小宇宙播客需要自建 RSSHub：

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
| FunASR + Poe 摘要 | ~16 元 |
| Paraformer + Poe 摘要 | ~6 元 |
| 通义听悟（一站式） | ~55 元 |

## 开发

```bash
pip install -e ".[dev]"
make lint        # 代码检查
make test        # 运行测试（170+ 个）
make test-cov    # 覆盖率报告
make format      # 自动格式化
```

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE)
