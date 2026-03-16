# FM2note

[English](README.md) | [中文](README.zh-CN.md)

> Automatically transcribe podcasts and save them as Obsidian notes.

FM2note monitors podcast RSS feeds, transcribes episodes using cloud ASR, generates AI summaries, and writes structured Markdown notes directly into your Obsidian vault.

## Features

- **RSS monitoring** — auto-detect new episodes from any RSS/Atom feed
- **Multiple ASR engines** — FunASR, Paraformer, TingWu, Bailian, OpenAI Whisper
- **AI summaries** — chapter breakdown + keywords via Poe, OpenAI, or any OpenAI-compatible API
- **Direct Obsidian vault write** — Markdown with YAML frontmatter
- **Customizable templates** — configurable note template path and section labels
- **Subtitle detection** — skip ASR when subtitles are available (saves cost)
- **Auto-retry** — failed episodes retried on next cycle
- **Self-hosted** — your data stays on your machine

## Architecture

```
Server (optional)              Local Mac
┌──────────────────┐      ┌────────────────────────────┐
│  RSSHub + Redis  │      │  fm2note (Python process)   │
│  (Docker, 24/7)  │◄────│  launchd/systemd auto-start │
│                  │      │          │                  │
└──────────────────┘      │          ▼                  │
                          │  Cloud ASR + AI summary     │
                          │          │                  │
                          │          ▼                  │
                          │  Obsidian vault (local)     │
                          └────────────────────────────┘
```

- **Server** (optional): RSSHub + Redis for Xiaoyuzhou podcast RSS proxy
- **Local**: fm2note process — ASR, AI summary, note generation, vault write

Standard RSS feeds work directly without RSSHub.

## Quick Start

### Install

```bash
pip install fm2note
```

Or from source:

```bash
git clone https://github.com/Austin5925/FM2note.git
cd FM2note
pip install -e .
```

### Setup

```bash
fm2note init
```

This interactively creates `config/config.yaml`, `config/subscriptions.yaml`, and `.env`.

### Configure

1. Edit `.env` — add your API keys:

```bash
export DASHSCOPE_API_KEY=sk-xxx          # Required for FunASR/TingWu
export OBSIDIAN_VAULT_PATH="/path/to/vault"

# AI summary (pick one, or leave both empty to skip summaries)
export POE_API_KEY=pk-xxx                # Poe subscription
export OPENAI_API_KEY=sk-xxx             # OpenAI / DeepSeek / Groq
```

2. Edit `config/subscriptions.yaml` — add your podcasts:

```yaml
podcasts:
  # Standard RSS feed (works directly)
  - name: "My Favorite Podcast"
    rss_url: "https://example.com/feed.xml"
    tags: ["tech"]

  # Xiaoyuzhou podcast (via RSSHub)
  - name: "小宇宙播客"
    rss_url: "https://your-rsshub.com/rsshub/xiaoyuzhou/podcast/PODCAST_ID"
    tags: ["finance"]
```

### Run

```bash
source .env
fm2note run-once     # Process once
fm2note serve        # Continuous daemon (polls every 3 hours)
```

## ASR Engines

| Engine | Cost/hour | Features | Best for |
|---|---|---|---|
| FunASR (default) | ~0.79 CNY | Chinese-optimized, dialect support | Chinese podcasts |
| Paraformer | ~0.29 CNY | Budget option, 7+ languages | Cost-sensitive |
| TingWu | ~3.00 CNY | ASR + built-in AI summary | All-in-one |
| Bailian | ~0.79 CNY | DashScope SDK, up to 12h/2GB | Long episodes |
| Whisper API | ~$0.36 | Multilingual | English/other languages |

Set `asr_engine` in `config/config.yaml`. All DashScope engines share the same `DASHSCOPE_API_KEY`.

## AI Summary

FM2note generates AI summaries with chapter breakdowns and keywords. The summary provider is **auto-detected** based on available API keys:

| Provider | Config | API Key | Model Default |
|---|---|---|---|
| Poe | `SUMMARY_PROVIDER=poe` | `POE_API_KEY` | GPT-5.4 |
| OpenAI | `SUMMARY_PROVIDER=openai` | `OPENAI_API_KEY` | gpt-4o-mini |
| DeepSeek/Groq/Ollama | `SUMMARY_PROVIDER=openai` + `SUMMARY_BASE_URL=...` | `OPENAI_API_KEY` | varies |
| None | `SUMMARY_PROVIDER=none` | — | — |
| Auto (default) | `SUMMARY_PROVIDER=auto` | any available | auto |

Without any summary API key, FM2note outputs transcription only (no error).

## Template Customization

The default note template uses Chinese section labels. You can customize:

1. **Custom template path** — point to your own Jinja2 template:
   ```yaml
   # config.yaml
   template_path: "templates/my_custom_note.md.j2"
   ```

2. **Label overrides** — see `src/writer/markdown.py` for the `DEFAULT_LABELS` dict.

## Deployment

### Auto-start Service

```bash
fm2note install-service    # macOS (launchd) or Linux (systemd)
fm2note uninstall-service  # Remove the service
```

### RSSHub (for Xiaoyuzhou podcasts)

If you subscribe to Xiaoyuzhou (小宇宙) podcasts, you need a self-hosted RSSHub:

```bash
# On your server:
docker compose up -d
```

This starts RSSHub + Redis. Then use RSS URLs like:
`https://your-domain.com/rsshub/xiaoyuzhou/podcast/PODCAST_ID`

**Cloudflare users**: RSSHub listens on port 1200 (not proxied by Cloudflare). Options:
1. **Nginx reverse proxy** (recommended): Add `location /rsshub/ { proxy_pass http://127.0.0.1:1200/; }` to your Nginx config
2. **Use port 8080**: Change docker-compose port to `8080:1200` (Cloudflare supports 8080)

Standard RSS feeds don't need RSSHub.

### How to Find Xiaoyuzhou Podcast ID

Open the podcast page in your browser:
`https://www.xiaoyuzhoufm.com/podcast/PODCAST_ID`

Copy the `PODCAST_ID` part.

## Configuration

### config/config.yaml

| Field | Default | Description |
|---|---|---|
| `vault_path` | — | Obsidian vault path (override with `OBSIDIAN_VAULT_PATH` env var) |
| `podcast_dir` | `Podcasts` | Subdirectory in vault for notes |
| `poll_interval_hours` | `3` | Polling interval for `serve` mode |
| `asr_engine` | `funasr` | ASR engine: `funasr` / `paraformer` / `tingwu` / `bailian` / `whisper_api` |
| `max_retries` | `3` | Max retry attempts for failed episodes |
| `summary_cooldown` | `60` | Seconds between summary API calls |
| `template_path` | — | Custom Jinja2 template path (optional) |

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DASHSCOPE_API_KEY` | Yes (for DashScope engines) | Alibaba DashScope API key |
| `OBSIDIAN_VAULT_PATH` | Yes | Absolute path to Obsidian vault |
| `SUMMARY_PROVIDER` | No | `auto` / `poe` / `openai` / `none` (default: `auto`) |
| `POE_API_KEY` | No | Poe API key for AI summaries |
| `OPENAI_API_KEY` | No | OpenAI API key (summaries and/or Whisper) |
| `SUMMARY_MODEL` | No | Override model (default: provider-specific) |
| `SUMMARY_BASE_URL` | No | OpenAI-compatible endpoint (DeepSeek, Groq, Ollama) |
| `TINGWU_APP_ID` | No (only for `tingwu`) | TingWu App ID |

## Commands

| Command | Description |
|---|---|
| `fm2note run-once` | Check feeds and process new episodes once |
| `fm2note serve` | Start polling daemon |
| `fm2note transcribe <url>` | Transcribe a single audio URL |
| `fm2note retry-summaries` | Retry failed AI summaries |
| `fm2note init` | Interactive setup wizard |
| `fm2note install-service` | Install auto-start service |
| `fm2note uninstall-service` | Remove auto-start service |

## Cost Estimates (20 episodes/month, ~1 hour each)

| Setup | Monthly Cost |
|---|---|
| FunASR + Poe/OpenAI summary | ~16 CNY (~$2) |
| Paraformer + Poe/OpenAI summary | ~6 CNY (~$1) |
| TingWu (all-in-one) | ~55 CNY (~$8) |

## Development

```bash
pip install -e ".[dev]"
make lint        # ruff check
make test        # pytest (213+ tests)
make test-cov    # Coverage report
make format      # Auto-format
make build       # Build sdist + wheel
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

[MIT](LICENSE)
