# FM2note

小宇宙播客自动转写笔记管线。监听播客更新，通义听悟 ASR 转写 + AI 摘要，直接写入 Obsidian vault。

## 架构

```
RSSHub (自建)          通义听悟 (DashScope)       Obsidian Vault
    │                        │                        │
    ▼                        ▼                        ▼
RSS 轮询 ──→ 新剧集检测 ──→ ASR 转写 ──→ Markdown 生成 ──→ .md 写入
                │                           │
                ▼                           ▼
           SQLite 状态管理            AI 摘要 + 章节速览
```

**三个容器**：fm2note（Python 主服务）+ RSSHub + Redis（缓存）

## 快速部署

### 1. 克隆仓库

```bash
ssh your-server
cd /opt
git clone https://github.com/YOUR_USER/FM2note.git
cd FM2note
```

### 2. 配置环境变量

```bash
cp .env.example .env
vim .env
```

必填项：

| 变量 | 说明 | 获取方式 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 通义听悟 API Key | [DashScope 控制台](https://dashscope.console.aliyun.com/) |
| `TINGWU_APP_ID` | 听悟应用 ID | [通义听悟控制台](https://tingwu.console.aliyun.com/) → 创建项目 |
| `OBSIDIAN_VAULT_PATH` | Obsidian vault 绝对路径 | 服务器上 vault 目录 |

### 3. 配置订阅

编辑 `config/subscriptions.yaml`，添加播客：

```yaml
podcasts:
  - name: "播客名称"
    rss_url: "http://rsshub:1200/xiaoyuzhou/podcast/PODCAST_ID"
    tags: ["tag1", "tag2"]
```

播客 ID 从小宇宙链接获取：`xiaoyuzhoufm.com/podcast/PODCAST_ID`

### 4. 启动

```bash
docker compose up -d --build
```

验证：

```bash
# 检查容器状态
docker compose ps

# 查看 fm2note 日志
docker compose logs -f fm2note

# 验证 RSSHub
docker compose exec fm2note curl -s http://rsshub:1200/xiaoyuzhou/podcast/YOUR_ID | head -20
```

### 5. 手动触发一次（可选）

```bash
docker compose exec fm2note python main.py run-once
```

## 运行模式

| 命令 | 说明 |
|---|---|
| `python main.py serve` | 定时调度模式（默认，每 3 小时检查一次） |
| `python main.py run-once` | 手动执行一次检查和处理 |
| `python main.py transcribe <audio_url>` | 单独转写一个音频 URL（调试用） |

## 配置说明

### config/config.yaml

| 字段 | 默认值 | 说明 |
|---|---|---|
| `vault_path` | `/vault` | Obsidian vault 路径（Docker 内） |
| `podcast_dir` | `Podcasts` | vault 内子目录 |
| `poll_interval_hours` | `3` | RSS 轮询间隔（小时） |
| `asr_engine` | `tingwu` | ASR 引擎（tingwu / bailian / whisper_api） |
| `max_retries` | `3` | 失败重试次数 |
| `log_level` | `INFO` | 日志级别 |

### Docker 挂载卷

| 容器路径 | 宿主机路径 | 用途 |
|---|---|---|
| `/vault` | `$OBSIDIAN_VAULT_PATH` | Obsidian vault（笔记输出） |
| `/app/data` | `./data` | SQLite 状态数据库 + 临时文件 |
| `/app/logs` | `./logs` | 日志文件 |
| `/app/config` | `./config` | 配置文件（可热编辑订阅） |

## 技术栈

| 层 | 技术 |
|---|---|
| 语言 | Python 3.11 |
| RSS 解析 | feedparser |
| HTTP | httpx (async) |
| ASR | 通义听悟 (dashscope SDK) |
| 模板 | Jinja2 |
| 状态 | SQLite (aiosqlite) |
| 调度 | APScheduler |
| 日志 | loguru |
| 容器 | Docker + docker-compose |

## 开发

```bash
# 安装依赖
pip install -r requirements.txt -r requirements-dev.txt

# 代码检查
make lint

# 运行测试
make test

# 格式化
make format
```

## 成本

通义听悟：转写 0.6 元/小时 + AI 功能 0.064 元/小时。20 集/月（每集 1 小时）约 14.56 元。新用户 90 天免费。

## 版本

当前版本：v0.5.1

详见 [CLAUDE.md](CLAUDE.md) 的 Version History。
