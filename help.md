# FM2note 使用指南

## 架构概览

```
macroclaw.app (<REDACTED_IP>)         本地 Mac
┌─────────────────────┐      ┌──────────────────────────────┐
│  RSSHub + Redis     │      │  fm2note (Python 原生进程)    │
│  (Docker, 7x24)     │◄────│  launchd 自启，每 3h 轮询     │
│  :1200              │      │          │                    │
└─────────────────────┘      │          ▼                    │
                             │  FunASR 转写 + Poe AI 摘要    │
                             │          │                    │
                             │          ▼                    │
                             │  Obsidian vault (iCloud)      │
                             └──────────────────────────────┘
```

---

## 1. 如何新增想追的播客

### 第一步：获取播客 ID

打开小宇宙 App 或网页，进入播客主页，URL 格式为：

```
https://www.xiaoyuzhoufm.com/podcast/PODCAST_ID
```

例如 `https://www.xiaoyuzhoufm.com/podcast/6978a31df828d4e9f2787d3d`，其中 `6978a31df828d4e9f2787d3d` 就是播客 ID。

### 第二步：编辑订阅配置

编辑 `config/subscriptions.yaml`，添加新条目：

```yaml
podcasts:
  - name: "非共识的20分钟"
    rss_url: "http://<REDACTED_IP>:1200/xiaoyuzhou/podcast/6978a31df828d4e9f2787d3d"
    tags: ["finance", "macro"]

  # 新增播客 ↓
  - name: "播客名称"
    rss_url: "http://<REDACTED_IP>:1200/xiaoyuzhou/podcast/你的播客ID"
    tags: ["标签1", "标签2"]
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 播客名称，用于笔记分类和日志 |
| `rss_url` | 是 | RSSHub 代理地址，替换末尾的播客 ID 即可 |
| `tags` | 否 | Obsidian 笔记标签，默认为空 |

### 第三步：验证 RSS 可用

```bash
curl "http://<REDACTED_IP>:1200/xiaoyuzhou/podcast/你的播客ID" | head -20
```

能看到 XML 内容说明 RSSHub 正常抓取。

### 第四步：手动触发一次

```bash
source .env && python3.11 main.py run-once
```

如果 launchd 服务已在运行，也可以等待下一次自动轮询（每 3 小时）。

---

## 2. 如何追播客列表里的历史内容

### 工作原理

fm2note 用 SQLite 数据库（`data/state.db`）跟踪每集的处理状态。每次 `run-once` 时：

1. 拉取 RSS feed 中的所有剧集
2. 逐一比对数据库，筛出 **未处理** 的剧集
3. 对每集执行：ASR 转写 → AI 摘要 → 生成 Markdown → 写入 Obsidian

**首次订阅一个播客时，RSS feed 里的所有剧集都是"未处理"状态，会被全部拉取。**

### 操作步骤

如果你刚添加了一个新播客，直接运行即可获取历史内容：

```bash
source .env && python3.11 main.py run-once
```

fm2note 会自动处理 RSS feed 中所有可用剧集。处理是逐集串行的（避免 API 限流），历史剧集较多时需要耐心等待。

### RSS feed 剧集数量限制

**重要**：RSSHub 的小宇宙路由受上游 API 分页限制，通常只返回**最近 15-20 集**，而非全部历史。这意味着较早的剧集不在 feed 中，`run-once` 无法自动发现。

**如何处理 feed 中缺失的早期剧集：**

1. 打开小宇宙播客主页，找到缺失剧集的链接（格式：`https://www.xiaoyuzhoufm.com/episode/EPISODE_ID`）
2. 用 `transcribe` 命令逐集处理：

```bash
source .env && python3.11 main.py transcribe \
  "https://www.xiaoyuzhoufm.com/episode/EPISODE_ID" \
  --podcast "播客名称"
```

`transcribe` 命令会自动从小宇宙页面解析音频 URL、标题和发布日期，无需手动查找。

**如何确认 feed 返回了多少集：**

```bash
# 在服务器上执行
curl -s "http://localhost:1200/xiaoyuzhou/podcast/播客ID" | grep -o "<item>" | wc -l
```

### 注意事项

- **断点续传**：如果中途失败（网络/API 问题），已完成的剧集不会重复处理。下次 `run-once` 会从断点继续，并自动重试失败任务（最多 3 次）。
- **费用提醒**：批量处理历史内容会消耗 FunASR 额度（约 0.79 元/小时音频），处理前请确认余额。如使用 Paraformer 引擎则约 0.29 元/小时。

### 查看处理状态

状态记录在 SQLite 数据库中，可以直接查询：

```bash
sqlite3 data/state.db "SELECT title, status, error_msg FROM processed_episodes ORDER BY created_at DESC;"
```

状态值含义：

| 状态 | 说明 |
|---|---|
| `pending` | 已发现，等待处理 |
| `transcribing` | 正在转写 |
| `writing` | 正在写入笔记 |
| `done` | 处理完成 |
| `failed` | 处理失败（会自动重试） |

---

## 3. 如何单独转录其他系列的一集

### 方式一：`transcribe` 命令（推荐）

直接提供音频 URL，自动完成转写 + AI 摘要 + 写入 Obsidian：

```bash
source .env && python3.11 main.py transcribe "https://example.com/episode.mp3"
```

可选参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--title` | 从 URL 提取 | 笔记标题 |
| `--podcast` | `单独转录` | 播客名称（决定存放目录） |

示例：

```bash
# 指定标题和分类
source .env && python3.11 main.py transcribe \
  "https://media.xyzcdn.net/.../audio.m4a" \
  --title "美联储加息解读" \
  --podcast "财经播客"
```

笔记写入路径：`Obsidian vault/Podcasts/<podcast名称>/<日期>-<标题>.md`

### 方式二：临时添加订阅（批量处理）

如果你想批量转录某个播客的所有剧集：

1. 在 `config/subscriptions.yaml` 中添加该播客
2. 运行 `python3.11 main.py run-once`
3. 笔记会写入 `Obsidian vault/Podcasts/播客名称/` 目录
4. 处理完成后，如果不想持续追踪，从 `subscriptions.yaml` 中移除即可

### 获取小宇宙单集音频 URL

如果你知道单集链接（如 `https://www.xiaoyuzhoufm.com/episode/EPISODE_ID`），可以通过 RSSHub 获取该播客的 feed，从中找到对应剧集的音频 URL：

```bash
curl "http://<REDACTED_IP>:1200/xiaoyuzhou/podcast/播客ID" -s | grep -o 'url="[^"]*\.m4a' | head -5
```

然后用 `transcribe` 命令转录。
