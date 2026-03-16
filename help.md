# FM2note 使用指南

## 架构概览

```
服务器（可选）                 本地 Mac
┌──────────────────┐      ┌────────────────────────────┐
│  RSSHub + Redis  │      │  fm2note (Python 原生进程)   │
│  (Docker, 7x24)  │◄────│  launchd/systemd 自启        │
│                  │      │          │                  │
└──────────────────┘      │          ▼                  │
                          │  ASR 转写 + AI 摘要          │
                          │  (FunASR/Poe/OpenAI 等)     │
                          │          │                  │
                          │          ▼                  │
                          │  Obsidian vault (本地)       │
                          └────────────────────────────┘
```

标准 RSS feed 无需 RSSHub，可直接使用。RSSHub 仅在使用小宇宙播客时需要。

---

## 1. 如何新增想追的播客

### 标准 RSS 播客（无需 RSSHub）

直接在 `config/subscriptions.yaml` 中添加 RSS feed URL：

```yaml
podcasts:
  - name: "我的播客"
    rss_url: "https://example.com/podcast/feed.xml"
    tags: ["tech"]
```

### 小宇宙播客（需 RSSHub）

#### 第一步：获取播客 ID

打开小宇宙 App 或网页，进入播客主页，URL 格式为：
`https://www.xiaoyuzhoufm.com/podcast/PODCAST_ID`

#### 第二步：编辑订阅配置

```yaml
podcasts:
  - name: "播客名称"
    rss_url: "https://your-rsshub-domain.com/rsshub/xiaoyuzhou/podcast/PODCAST_ID"
    tags: ["标签1", "标签2"]
```

> **注意**：将 `your-rsshub-domain.com` 替换为你的 RSSHub 服务器地址。
> 如果使用 Nginx 反代，路径格式为 `/rsshub/xiaoyuzhou/podcast/...`。

#### 第三步：验证 RSS 可用

```bash
curl "https://your-rsshub-domain.com/rsshub/xiaoyuzhou/podcast/PODCAST_ID" | head -20
```

#### 第四步：手动触发一次

```bash
source .env && fm2note run-once
```

如果 launchd/systemd 服务已在运行，也可以等待下一次自动轮询（默认每 3 小时）。

---

## 2. 如何追播客列表里的历史内容

### 工作原理

fm2note 用 SQLite 数据库（`data/state.db`）跟踪每集的处理状态。首次订阅一个播客时，RSS feed 里的所有剧集都是"未处理"状态，会被全部拉取。

### 操作步骤

```bash
source .env && fm2note run-once
```

处理是逐集串行的（避免 API 限流），历史剧集较多时需要耐心等待。

### RSS feed 剧集数量限制

RSSHub 的小宇宙路由受上游 API 限制，通常只返回**最近 15-20 集**。

**如何处理 feed 中缺失的早期剧集：**

用 `transcribe` 命令逐集处理：

```bash
source .env && fm2note transcribe \
  "https://www.xiaoyuzhoufm.com/episode/EPISODE_ID" \
  --podcast "播客名称"
```

`transcribe` 命令会自动从小宇宙页面解析音频 URL、标题和发布日期。

### 注意事项

- **断点续传**：已完成的剧集不会重复处理，失败的会自动重试（最多 3 次）
- **费用提醒**：批量处理消耗 ASR 额度（FunASR 约 0.79 元/小时，Paraformer 约 0.29 元/小时）

### 查看处理状态

```bash
sqlite3 data/state.db "SELECT title, status, error_msg FROM processed_episodes ORDER BY created_at DESC;"
```

| 状态 | 说明 |
|---|---|
| `pending` | 已发现，等待处理 |
| `transcribing` | 正在转写 |
| `writing` | 正在写入笔记 |
| `done` | 处理完成 |
| `failed` | 处理失败（会自动重试） |

---

## 3. 如何单独转录一集

### 方式一：`transcribe` 命令（推荐）

```bash
source .env && fm2note transcribe "https://example.com/episode.mp3"
```

可选参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--title` | 从 URL 提取 | 笔记标题 |
| `--podcast` | `单独转录` | 播客名称（决定存放目录） |

示例：

```bash
source .env && fm2note transcribe \
  "https://www.xiaoyuzhoufm.com/episode/EPISODE_ID" \
  --podcast "财经播客"
```

### 方式二：临时添加订阅（批量处理）

1. 在 `config/subscriptions.yaml` 中添加该播客
2. 运行 `fm2note run-once`
3. 处理完成后，不想持续追踪则从配置中移除

---

## 4. AI 摘要配置

FM2note 自动检测可用的摘要 API Key：

```bash
# .env 中配置其一即可
export POE_API_KEY=pk-xxx       # Poe 订阅
export OPENAI_API_KEY=sk-xxx    # OpenAI / DeepSeek / Groq

# 或显式指定提供商
export SUMMARY_PROVIDER=openai
export SUMMARY_MODEL=gpt-4o-mini

# DeepSeek / Groq 等 OpenAI-compatible API
export SUMMARY_BASE_URL=https://api.deepseek.com/v1
```

不配置任何摘要 Key 时，仅输出转写文本，不报错。

### 重试失败的摘要

如果摘要生成失败，转写结果会被缓存。稍后可以重试：

```bash
source .env && fm2note retry-summaries
```

---

## 5. 服务管理

### 安装/卸载自启服务

```bash
fm2note install-service    # macOS launchd 或 Linux systemd
fm2note uninstall-service  # 卸载
```

### macOS launchd

```bash
launchctl list | grep fm2note            # 查看状态
tail -f logs/fm2note-stderr.log          # 查看日志
```

### Linux systemd

```bash
systemctl --user status fm2note          # 查看状态
journalctl --user -u fm2note -f          # 查看日志
```
