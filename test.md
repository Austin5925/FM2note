# FM2note v0.5.1 本地测试报告

> 测试日期：2026-03-10
> 测试环境：macOS Darwin 24.6.0, Python 3.11.12
> 目标剧集：[特集｜美伊：三件大多数中文内容没有认真想过的事](https://www.xiaoyuzhoufm.com/episode/69a2b310de29766da9e12ce8)
> 播客：非共识的20分钟（ID: 6978a31df828d4e9f2787d3d）
> 音频时长：13 分钟（828 秒）

---

## 测试 1：单元测试

**目的**：验证全部代码逻辑正确性

```bash
make test
```

**状态**：✅ 通过
**结果**：107 passed, 0.62s

---

## 测试 2：RSSHub 连通性

**目的**：验证本地 RSSHub 能正确解析「非共识的20分钟」RSS feed

```bash
docker run -d --name rsshub -p 1200:1200 diygod/rsshub:latest
curl -s "http://localhost:1200/xiaoyuzhou/podcast/6978a31df828d4e9f2787d3d" | head -50
```

**状态**：⏭️ 跳过（本地 Docker 未运行）
**备注**：将在服务器端测试 4 中一并验证

---

## 测试 3：ASR 单独转写

**目的**：验证 DashScope API Key + 通义听悟 AppId 能正常转写音频

### 3.1 安装依赖
```bash
pip install -r requirements.txt
```
**结果**：dashscope 1.25.13 安装成功

### 3.2 运行转写
```bash
export $(cat .env | xargs) && python3.11 main.py transcribe \
  "https://media.xyzcdn.net/6978a31df828d4e9f2787d3d/lqGLSpMTDUF7KfgeEq1sZJYd-7Tg.m4a"
```

### 3.3 调试过程

初次运行发现两个 bug，已修复：

#### Bug 1：`taskStatus` 字段名不匹配
- **现象**：轮询状态始终为空字符串，任务永不完成
- **原因**：DashScope 返回 `output.status`（数字: 0=完成, 1=运行中）而非 `output.taskStatus`（字符串）
- **修复**：`_poll_task` 改用 `output.get("status")` + 数字状态码比较

#### Bug 2：OSS 结果 JSON 结构不匹配
- **现象**：解析 autoChapters 时 `AttributeError: 'list' object has no attribute 'get'`
- **原因**：DashScope 版 OSS 响应格式与旧 ROA SDK 完全不同

| 字段 | 旧格式（ROA SDK） | 实际格式（DashScope） |
|---|---|---|
| 转写 | `Transcription.Paragraphs[].Words[].Text` | `paragraphs[].words[].text` |
| 摘要 | `Summarization.Paragraph` | `paragraphSummary` |
| 章节 | `{AutoChapters: [{Title, Summary}]}` | `[{headline, summary}]`（直接 list） |
| 结果路径 | `result.Transcription` | `transcriptionPath`（顶层） |

- **修复**：`_parse_result` 完全重写，匹配 DashScope 实际返回格式

### 3.4 验证结果（使用已完成任务 dj4SK9Mcx5Jr）

**状态**：✅ 通过

```
转写字数: 3798
段落数: 19
摘要长度: 1177
章节数: 5
  [1] 美伊军事冲突升级与间接谈判进展：核设施打击、航母集结及阿曼斡旋背景分析
  [2] 特朗普对伊朗采取军事施压与外交谈判并行策略的深层利益逻辑分析
  [3] 特朗普政府对伊朗核设施可能采取的三种军事与制裁策略分析
  [4] 中东军事冲突爆发前后美股与油价走势的历史规律及霍尔木兹海峡封锁风险的特殊性分析
  [5] 地缘政治冲突升级下原油价格走势与市场逆向信号分析
```

摘要前 200 字：
> 本记录讲述了美伊关系最新动态及特朗普政府应对策略的三层逻辑：谈判与军事施压并行的动机、三种潜在军事方案评估、以及历史冲突对市场影响的规律性分析，重点强调霍尔木兹海峡特殊性带来的新变量...

### 3.5 完整 transcribe 命令

**状态**：✅ 通过

```
23:34:36 任务创建: data_id=kbVSFo1YzICy
23:34:37 轮询状态: 1 (运行中)
23:35:07 轮询状态: 1 (运行中)
23:35:38 轮询状态: 0 (完成)     ← 约 1 分钟
23:35:39 转写完成: 3798 字, 19 段
23:35:39 摘要: 本记录讲述了美伊关系最新动态及特朗普政府应对策略...
```

完整转写文本输出正确，包含摘要和 5 个自动章节。

---

## 测试 4：端到端管线

**目的**：完整流程 RSS 检测 → 转写 → Markdown 生成 → 写入 Obsidian vault

**前置条件**：
- 本地 Docker 运行 RSSHub
- config/subscriptions.yaml 配置播客
- config/config.yaml 指向 Obsidian vault

**状态**：⏳ 待测试 3.5 完成后执行

---

## Bug 修复记录

| Bug | 根因 | 修复 | 影响文件 |
|---|---|---|---|
| 轮询状态为空 | `taskStatus` → `status`（数字） | `_poll_task` 用数字状态码 | `tingwu.py` |
| 解析 chapters 报错 | OSS 直接返回 list | `isinstance(chap_data, list)` | `tingwu.py` |
| OSS 字段名错误 | 全 camelCase、顶层 `xxxPath` | `_parse_result` 重写 | `tingwu.py` |
| mock 用 dict 而非属性 | `response.output` 不是 `response["output"]` | 用 `hasattr` + `.output` | `tingwu.py` |

---

## 总结

| # | 测试项 | 状态 | 备注 |
|---|---|---|---|
| 1 | 单元测试 | ✅ 107 passed | 0.62s |
| 2 | RSSHub 连通性 | ⏭️ 跳过 | 本地无 Docker，服务器测试 |
| 3 | ASR 单独转写 | ✅ 解析验证通过 | 发现并修复 4 个 bug |
| 3.5 | transcribe 命令 | ✅ 通过 | 3798字/19段/5章节/摘要 |
| 4 | 端到端管线 | ⏭️ 待服务器 | 需 Docker + RSSHub |
