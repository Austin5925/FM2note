# DashScope 通义听悟 API 实测备忘

> 基于 v0.5.1 实测总结，dashscope SDK 1.25.13

## SDK 调用方式

```python
from dashscope.multimodal.tingwu.tingwu import TingWu

# 创建任务
response = TingWu.call(
    model="tingwu-meeting",
    user_defined_input={
        "task": "createTask",
        "type": "offline",
        "appId": "tw_xxx",
        "fileUrl": "https://...",
        "phraseId": "",
    },
    api_key="sk-xxx",
    base_address="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    parameters={},
)
data_id = response.output["dataId"]

# 轮询任务
response = TingWu.call(
    model="tingwu-meeting",
    user_defined_input={"task": "getTask", "dataId": data_id},
    api_key="sk-xxx",
    base_address="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
)
status = response.output["status"]  # 数字！不是字符串
```

## 关键陷阱

### 1. 响应对象不是 dict

`TingWu.call()` 返回 `DashScopeAPIResponse`，不是 dict。

```python
# 错误
output = response.get("output", {})  # 不可靠

# 正确
output = response.output  # 属性访问
```

虽然 `DashScopeAPIResponse` 实现了 `.get()` 方法，但最佳实践是用属性访问。

### 2. 任务状态是数字，不是字符串

```python
# 错误
if status == "COMPLETED":  # 永远不会匹配

# 正确
if status == 0:  # 完成
if status == 1:  # 运行中
if status == 2:  # 失败
```

### 3. OSS 结果的字段名与旧 ROA SDK 完全不同

| 数据 | 旧 ROA SDK 格式 | DashScope 实际格式 |
|---|---|---|
| output 路径键 | `Result.Transcription` | `transcriptionPath`（顶层） |
| output 路径键 | `Result.Summarization` | `summarizationPath`（顶层） |
| output 路径键 | `Result.AutoChapters` | `autoChaptersPath`（顶层） |
| 转写段落 | `Transcription.Paragraphs[].Words[].Text` | `paragraphs[].words[].text` |
| 摘要 | `Summarization.Paragraph` | `paragraphSummary` |
| 章节 | `{"AutoChapters": [{"Title", "Summary"}]}` | 直接 `list`：`[{"headline", "summary"}]` |

### 4. autoChapters OSS 直接返回 list

```python
chap_data = await fetch_oss(url)

# 错误
raw_chapters = chap_data.get("AutoChapters", [])  # AttributeError

# 正确
raw_chapters = chap_data if isinstance(chap_data, list) else []
```

## 认证

- 只需 **一个** DashScope API Key（`sk-xxx`）
- 加上 TingWu AppId（`tw_xxx`，在听悟控制台获取）
- 不需要 AccessKey ID/Secret 对

## OSS 结果完整结构

### transcriptionPath → JSON

```json
{
  "audioInfo": {"duration": 828, "language": "cn", "sampleRate": 16000},
  "paragraphs": [
    {
      "paragraphId": "p1",
      "speakerId": "s0",
      "words": [
        {"text": "嗨", "start": 4380, "end": 4637, "id": 10, "sentenceId": 1}
      ]
    }
  ]
}
```

### summarizationPath → JSON

```json
{
  "paragraphSummary": "本记录讲述了...",
  "mindMapSummary": [{"title": "...", "topic": [...]}],
  "questionsAnsweringSummary": [{"question": "...", "answer": "..."}]
}
```

### autoChaptersPath → JSON（直接 list）

```json
[
  {
    "id": 1,
    "headline": "章节标题",
    "summary": "章节摘要",
    "start": 4380,
    "end": 130620
  }
]
```

## 性能参考

- 13 分钟音频 → ASR 约 1 分钟完成
- 返回：3798 字 / 19 段 / 5 章节 / 完整摘要
- 轮询间隔建议：30 秒
