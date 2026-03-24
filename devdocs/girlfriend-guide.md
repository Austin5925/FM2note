# FM2note 使用指南

这个工具可以把你订阅的播客自动转成文字笔记，保存到你的 Obsidian 里。

---

## 第一步：安装

### 1.1 确认 Python 版本

打开 Mac 的"终端"（在启动台搜索"终端"或"Terminal"），输入：

```bash
python3 --version
```

需要 **Python 3.11 或更高**。如果版本低于 3.11，先安装新版：

```bash
brew install python@3.11
```

没有 brew 的话，先装 Homebrew（复制这行到终端回车）：

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 1.2 安装 fm2note

```bash
pip3 install fm2note
```

安装完后验证一下：

```bash
fm2note --version
```

看到版本号（比如 `fm2note, version 1.3.2`）就说明装好了。

---

## 第二步：初始化

在终端里先建一个工作文件夹，以后 fm2note 的所有数据都放在这里：

```bash
mkdir ~/fm2note && cd ~/fm2note
fm2note init
```

会问你几个问题，**直接按下面的表格填**：

| 问题 | 填什么 |
|---|---|
| **Obsidian vault path** | `/Users/你的用户名/Library/Mobile Documents/iCloud~md~obsidian/Documents/你的库名`（见下方说明） |
| **ASR engine** | 直接回车（默认 funasr） |
| **Podcast subdirectory** | 输入 `10_Podcasts`（和 Austin 的保持一致） |
| **Polling interval** | 直接回车（默认 3） |
| **RSSHub base URL** | 输入 `https://macroclaw.app/rsshub` |

### 怎么找 Obsidian vault 路径？

打开 Obsidian → 左下角齿轮 → 关于 → 往下拉，能看到"库路径"，复制即可。

---

## 第三步：配置 API Key

`fm2note init` 会自动生成一个 `.env` 文件，但里面的 key 是假的，需要替换成真的。

用文本编辑器打开：

```bash
open -t ~/fm2note/.env
```

**把里面的全部内容删掉**，替换成下面这段（直接复制粘贴）：

```
# DashScope API Key（语音识别用）
export DASHSCOPE_API_KEY=sk-f04f00928af143a0bc04af604f13818e

# 通义听悟 AppId（备用引擎，目前不用管）
export TINGWU_APP_ID=tw_fgVnGvZ05xAr

# OpenAI（暂时不用）
export OPENAI_API_KEY=

# Poe AI 摘要
export POE_API_KEY=h_PtQD7vC-GcbsrR_FsxZ-WCfZ9lEu2Xz-3beiwg_9w

# Obsidian 笔记库路径（改成你自己的！）
export OBSIDIAN_VAULT_PATH="/Users/你的用户名/Library/Mobile Documents/iCloud~md~obsidian/Documents/你的库名"

# 日志级别
export LOG_LEVEL=INFO
```

**注意：`OBSIDIAN_VAULT_PATH` 那一行必须改成你自己的路径！** 其他的都不用动。

保存文件。

---

## 第四步：配置播客订阅

用文本编辑器打开：

```bash
open -t ~/fm2note/config/subscriptions.yaml
```

**把里面的内容替换成**（直接复制粘贴）：

```yaml
podcasts:
  - name: "非共识的20分钟"
    rss_url: "https://macroclaw.app/rsshub/xiaoyuzhou/podcast/6978a31df828d4e9f2787d3d"
    tags: ["finance", "macro"]
```

这是 Austin 已经配好的播客。以后想加新的，照着格式添加就行。

### 想添加自己的小宇宙播客？

1. 在浏览器打开小宇宙播客页面
2. 看网址：`https://www.xiaoyuzhoufm.com/podcast/6978a31df828d4e9f2787d3d`
3. 最后那串 `6978a31df828d4e9f2787d3d` 就是播客 ID
4. RSS 地址就是：`https://macroclaw.app/rsshub/xiaoyuzhou/podcast/播客ID`

保存文件。

---

## 第五步：确认配置

运行之前确认一下配置文件对不对。用文本编辑器打开：

```bash
open -t ~/fm2note/config/config.yaml
```

确认 `podcast_dir` 是 `"10_Podcasts"`，`asr_engine` 是 `"funasr"`。如果 init 时输错了，直接在这里改。

---

## 第六步：运行！

```bash
cd ~/fm2note
fm2note run-once
```

第一次运行会：
1. 检查你订阅的播客有没有新剧集
2. 下载音频
3. 发给阿里云做语音识别（大约 1-3 分钟/集）
4. 生成 Markdown 笔记
5. 写入你的 Obsidian vault

完成后打开 Obsidian，在 `10_Podcasts` 文件夹里就能看到笔记了。

---

## 日常使用

每次想检查新播客，运行：

```bash
cd ~/fm2note && fm2note run-once
```

已经处理过的剧集不会重复处理。

### 设置自动运行（可选）

如果想让它在后台自动运行（每 3 小时检查一次新播客）：

```bash
cd ~/fm2note
fm2note install-service
```

之后就不用手动运行了，Mac 开机后自动在后台工作。

想停掉自动运行：

```bash
fm2note uninstall-service
```

---

## 费用

语音识别按时长计费，大约：
- **FunASR**（默认）：每小时 ≈ 0.79 元
- 一集 1 小时的播客 ≈ 0.8 元
- 每月 20 集 ≈ 16 元

阿里云新用户通常有免费额度，初期可能不用花钱。

---

## 常见问题

### Q: 运行后没有笔记生成？

检查终端输出的日志，常见原因：
- API Key 填错了 → 重新检查 `.env`
- Obsidian vault 路径不对 → 检查 `config/config.yaml` 里的 `vault_path`
- RSS 地址无效 → 用浏览器打开 RSS URL 看能否显示 XML 内容

### Q: 提示 `command not found: fm2note`？

Python 的安装路径可能不在系统 PATH 中，试以下步骤：

**方法一**：用完整路径运行（先找到它装在哪）：

```bash
python3 -m pip show fm2note
```

看 `Location` 那行，比如 `/Users/xxx/Library/Python/3.11/lib/python/site-packages`，那对应的命令在 `/Users/xxx/Library/Python/3.11/bin/fm2note`。

**方法二**：把 pip 的 bin 目录加到 PATH（一劳永逸）：

```bash
echo 'export PATH="$HOME/Library/Python/3.11/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

然后重新试 `fm2note --version`。

### Q: Obsidian 里看不到文件夹？

确认 `config/config.yaml` 中 `podcast_dir` 的值和你期望的一致。笔记会保存在 `vault/10_Podcasts/播客名/` 下。

### Q: 想换一个播客？

编辑 `~/fm2note/config/subscriptions.yaml`，添加或删除条目，然后重新运行 `fm2note run-once`。

### Q: 提示 `No podcasts configured`？

说明你还没有配置播客订阅。回到第四步，编辑 `~/fm2note/config/subscriptions.yaml`，添加至少一个播客。

### Q: 出了问题怎么办？

把终端里的报错截图发给 Austin。
