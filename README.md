# FM2note

小宇宙播客自动转写笔记管线。监听播客更新，通义听悟 ASR 转写 + AI 摘要，直接写入 Obsidian vault。

## 架构

```
macroclaw.app (服务器)              本地 Mac
┌─────────────────────┐      ┌──────────────────────────────┐
│  RSSHub + Redis     │      │  fm2note (Python 原生进程)    │
│  (Docker, 7x24)     │◄────│  launchd 自启，每 3h 轮询     │
│  :1200              │      │          │                    │
└─────────────────────┘      │          ▼                    │
                             │  通义听悟 ASR → .md 写入      │
                             │          │                    │
                             │          ▼                    │
                             │  Obsidian vault (iCloud)      │
                             └──────────────────────────────┘
```

- **服务器**：仅运行 RSSHub + Redis（RSS 抓取代理，7x24 在线）
- **本地 Mac**：运行 fm2note 主进程（ASR 转写 + 笔记生成，直接写入本地 vault）

## 部署

### 服务器端（macroclaw.app）

```bash
ssh macroclaw.app
cd /opt
git clone https://github.com/Austin5925/FM2note.git
cd FM2note
docker compose up -d
```

验证 RSSHub：

```bash
curl http://localhost:1200/xiaoyuzhou/podcast/6978a31df828d4e9f2787d3d | head -5
```

服务器防火墙需开放 1200 端口（或通过 Nginx 反代）。

### 本地 Mac

#### 1. 安装依赖

```bash
cd ~/Desktop/gitRepo/FM2note
pip3.11 install -r requirements.txt
```

#### 2. 配置环境变量

```bash
cp .env.example .env
vim .env
```

```bash
DASHSCOPE_API_KEY=sk-xxx
TINGWU_APP_ID=tw_xxx
OBSIDIAN_VAULT_PATH="/path/to/obsidian/vault"
LOG_LEVEL=INFO
```

#### 3. 验证 RSSHub 连通

```bash
curl http://<REDACTED_IP>:1200/xiaoyuzhou/podcast/6978a31df828d4e9f2787d3d | head -5
```

#### 4. 手动测试一次

```bash
source .env && python3.11 main.py run-once
```

#### 5. 安装自启服务

```bash
make install-service
```

fm2note 将在每次登录时自动启动，每 3 小时检查播客更新。

## 运行模式

| 命令 | 说明 |
|---|---|
| `python3.11 main.py serve` | 定时调度模式（默认，每 3h 检查） |
| `python3.11 main.py run-once` | 手动执行一次 |
| `python3.11 main.py transcribe <url>` | 单独转写音频 URL（调试） |

## 服务管理

```bash
# 查看服务状态
launchctl list | grep fm2note

# 停止服务
launchctl unload ~/Library/LaunchAgents/com.fm2note.serve.plist

# 启动服务
launchctl load ~/Library/LaunchAgents/com.fm2note.serve.plist

# 卸载服务
make uninstall-service

# 查看日志
tail -f logs/fm2note-stderr.log

# 更新服务器 RSSHub
make deploy
```

## 配置

### config/config.yaml

| 字段 | 默认值 | 说明 |
|---|---|---|
| `vault_path` | `/vault` | 可被 `OBSIDIAN_VAULT_PATH` 环境变量覆盖 |
| `podcast_dir` | `Podcasts` | vault 内子目录 |
| `poll_interval_hours` | `3` | RSS 轮询间隔（小时） |
| `asr_engine` | `tingwu` | ASR 引擎 |
| `max_retries` | `3` | 失败重试次数 |

### config/subscriptions.yaml

```yaml
podcasts:
  - name: "非共识的20分钟"
    rss_url: "http://<REDACTED_IP>:1200/xiaoyuzhou/podcast/6978a31df828d4e9f2787d3d"
    tags: ["finance", "macro"]
```

播客 ID 从小宇宙链接获取：`xiaoyuzhoufm.com/podcast/PODCAST_ID`

## 资源消耗

### 服务器（macroclaw.app）

| 容器 | 内存 | CPU |
|---|---|---|
| RSSHub | ~200MB | 极低 |
| Redis | ~10MB | 极低 |
| **合计** | **~210MB** | **<0.2 核** |

### 本地 Mac

| 进程 | 内存 | CPU |
|---|---|---|
| fm2note (idle) | ~40MB | 接近 0 |
| fm2note (转写中) | ~80MB | 极低 |

## 开发

```bash
make lint      # 代码检查
make test      # 运行测试（107 passed）
make format    # 格式化
```

## 成本

通义听悟：~15 元/月（20 集 x 1 小时）。新用户 90 天免费。

## 版本

当前版本：v1.0.0

详见 [CLAUDE.md](CLAUDE.md) 的 Version History。
