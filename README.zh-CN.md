# FM2note

[English](README.md) | [中文](README.zh-CN.md)

> 自动转写播客并保存为 Obsidian 笔记。

FM2note 监听播客 RSS 更新，使用云端 ASR 转写，生成 AI 摘要，直接写入 Obsidian vault。

## 功能

- **本地 Web UI** — `fm2note web`（浏览器）或 `fm2note app`（桌面窗口），含转录 / 历史 / 订阅 / 设置 四个页面
- **RSS 监听** — 支持任意 RSS/Atom feed，自动检测新剧集
- **多 ASR 引擎** — FunASR、Paraformer、通义听悟、百炼、OpenAI Whisper
- **AI 摘要** — 章节速览 + 关键词（Poe / OpenAI / DeepSeek / Groq 等）
- **直写 Obsidian** — Markdown + YAML frontmatter
- **模板可定制** — 自定义笔记模板路径和章节标签
- **字幕检测** — 有字幕时跳过 ASR（节省成本）
- **阿里云余额徽章** — 可选，顶部显示余额并在过低时弹窗提醒
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

1. 编辑 `.env` — 只填 API Key 这类敏感信息（非敏感配置走 `config/config.yaml` 或 Web UI 设置页）：

```bash
export DASHSCOPE_API_KEY=sk-xxx          # FunASR/通义听悟必需

# AI 摘要（选一个，都不填则跳过摘要）
export POE_API_KEY=pk-xxx                # Poe 订阅
export OPENAI_API_KEY=sk-xxx             # OpenAI / DeepSeek / Groq
```

2. 在 `config/config.yaml`（或 Web UI 设置页）设置 Obsidian vault 路径：

```yaml
vault_path: "/Users/你/Documents/MyVault"
podcast_dir: "10_Podcasts"
```

2. 添加播客订阅。推荐打开 Web UI 的 **订阅** 页面，直接粘贴小宇宙播客页、剧集页或分享文本；FM2note 会用默认 RSSHub 自动生成订阅地址。

也可以手动编辑 `config/subscriptions.yaml`：

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
fm2note run-once     # 手动执行一次
fm2note serve        # 持续轮询（每 3 小时）
fm2note transcribe <URL>   # 单集转录（不需要 RSS 订阅）
```

> `.env` 会从工作目录自动加载，无需手动 `source`。

## Web UI（v1.4+）

不想再碰终端的用户走这个：

```bash
fm2note web          # 浏览器打开 http://127.0.0.1:7878
fm2note app          # 桌面窗口（需要 pip install 'fm2note[app]'）
fm2note install-shortcut   # 桌面生成双击启动图标
```

### 签名 macOS 桌面 App

如果要做成 Mac App Store 之外直接分发的 `.app`，先安装桌面和打包依赖：

```bash
python3.11 -m pip install -e ".[app,macos]"
make macos-app
```

产物是 `dist/FM2note.app`。如果要生成本机测试用的拖拽安装镜像：

```bash
make macos-dmg
```

正式分发推荐用 DMG。DMG 里有 `FM2note.app` 和 `Applications` 快捷方式，中间带
箭头提示拖拽安装，打开后会显示标准的拖拽安装窗口。如果 Keychain 里已经有
`Developer ID Application` 证书，脚本会使用 hardened runtime 签名；如果没有证书，
会退回 ad-hoc 签名，用于本机测试。

要公证 Developer ID 签名产物，先存一次 notary 凭据：

```bash
xcrun notarytool store-credentials fm2note-notary
APPLE_NOTARY_PROFILE=fm2note-notary make macos-notarize
```

这会产出 `dist/FM2note-macos.dmg`，同时保留备用 `dist/FM2note-macos.zip`。
正常发给别人时，优先发 DMG。这个公众版不会预填你的个人 RSSHub 或订阅，用户首次
启动后自己在界面里填写。

如果要生成预置版，只能把你愿意暴露的一次性配置放到本机忽略目录。profile 里的所有值
都会对 Apple 公证服务和任何拿到 DMG/App 包的人可见，包括 Obsidian 路径、RSSHub 地址、
API key、token 和注释：

```text
packaging/profiles/girlfriend/
  config/config.yaml
  config/subscriptions.yaml
  .env                  # 不要放密钥；这里的每个值都会在 App 包里可见
```

然后运行：

```bash
FM2NOTE_ALLOW_VISIBLE_PROFILE=1 APPLE_NOTARY_PROFILE=fm2note-notary make macos-notarize-girlfriend
```

这会产出 `dist/FM2note-girlfriend-macos.dmg`。内置 profile 只会在首次启动时复制到
`~/Library/Application Support/FM2note`，之后不会覆盖用户自己的修改。

打包后的桌面 App 默认把配置和数据放在
`~/Library/Application Support/FM2note`。如果要复用已有配置目录，启动前设置
`FM2NOTE_HOME`。

桌面 App 和后台服务是两件事：打开 App 会启动当前窗口所需的本地 GUI 服务；launchd
后台服务只负责关掉窗口后继续定时检查订阅。设置页里会把它标成“后台自动检查”，避免和
当前正在运行的 App 窗口混淆。

界面四个页面：

- **转录** — 贴播客 URL → 5 阶段实时进度（解析 / 字幕 / ASR / 摘要 / 写入）→ 一键 `obsidian://` 跳转
- **历史** — `state.db` 的最近剧集 + 失败摘要的重试
- **订阅** — 粘贴小宇宙链接自动识别并生成 RSSHub 地址，也可手动编辑/测试 RSS；ruamel.yaml 保留 YAML 注释
- **设置** — 编辑 API key、切换引擎、改 vault 路径；含健康自检 + launchd 服务状态

顶部导航有阿里云余额徽章（可选，配置 `ALIYUN_ACCESS_KEY_ID` / `_SECRET` 即可，参见 `.env.example`）。Web 服务只监听 `127.0.0.1`；需要局域网访问请用反向代理。

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

FM2note 支持多种 AI 摘要提供商，默认**自动检测**可用的 API Key。在 `config/config.yaml`（或 Web UI 设置页）设置：

| 提供商 | YAML 配置 | API Key（`.env`） | 默认模型 |
|---|---|---|---|
| Poe | `summary_provider: poe` | `POE_API_KEY` | GPT-5.5 |
| OpenAI | `summary_provider: openai` | `OPENAI_API_KEY` | gpt-4o-mini |
| DeepSeek/Groq/Ollama | `summary_provider: openai` + `summary_base_url: <url>` | `OPENAI_API_KEY` | 自定义 |
| 不使用 | `summary_provider: none` | — | — |
| 自动（默认） | `summary_provider: auto` | 任一可用 | 自动 |

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

## 配置

### config/config.yaml（非敏感配置）

所有非敏感配置都在这里，也可通过 Web UI 设置页编辑。

| 字段 | 默认 | 说明 |
|---|---|---|
| `vault_path` | — | Obsidian Vault 路径（必填） |
| `podcast_dir` | `Podcasts` | Vault 内笔记子目录 |
| `poll_interval_hours` | `3` | `serve` 模式轮询间隔 |
| `asr_engine` | `funasr` | `funasr` / `paraformer` / `tingwu` / `bailian` / `whisper_api` |
| `max_retries` | `3` | 失败剧集最大重试次数 |
| `summary_provider` | `auto` | `auto` / `poe` / `openai` / `none` |
| `summary_model` | — | 覆写模型（默认走 provider 默认） |
| `summary_cooldown` | `60` | 摘要 API 调用间隔（秒） |
| `summary_base_url` | — | OpenAI-compatible 端点（DeepSeek/Groq/Ollama） |
| `log_level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `template_path` | — | 自定义 Jinja2 模板路径（可选） |

### .env（敏感凭据）

v1.4.12 起，`.env` **只放** API Key / 凭据。任何非敏感字段放这里会触发启动 warning——它会静默覆盖 Web UI 的修改。

| 变量 | 是否必需 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | DashScope 引擎必需 | 阿里云 DashScope API Key |
| `POE_API_KEY` | 否 | Poe API Key（用于摘要） |
| `OPENAI_API_KEY` | 否 | OpenAI API Key（摘要 / Whisper） |
| `TINGWU_APP_ID` | 仅 `tingwu` 引擎需要 | 通义听悟 App ID |
| `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` | 否 | RAM 子账号 AK/SK，用于余额徽章 |

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
