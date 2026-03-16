# FM2note

[English](README.md) | [中文](README.zh-CN.md)

> Automatically transcribe podcasts and save them as Obsidian notes.

FM2note monitors podcast RSS feeds, transcribes episodes using cloud ASR, generates AI summaries, and writes structured Markdown notes directly into your Obsidian vault.

## Features

- **RSS monitoring** — auto-detect new episodes from any RSS/Atom feed
- **Multiple ASR engines** — FunASR, Paraformer, TingWu, OpenAI Whisper
- **AI summaries** — chapter breakdown + keywords via Poe or OpenAI
- **Direct Obsidian vault write** — Markdown with YAML frontmatter
- **Subtitle detection** — skip ASR when subtitles are available (saves cost)
- **Auto-retry** — failed episodes retried on next cycle
- **Self-hosted** — your data stays on your machine

## Architecture

```
Server (optional)              Local Mac
┌──────────────────┐      ┌────────────────────────────┐
│  RSSHub + Redis  │      │  fm2note (Python process)   │
│  (Docker, 24/7)  │◄────│  launchd/systemd auto-start │
│  :1200           │      │          │                  │
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

This creates `config/config.yaml`, `config/subscriptions.yaml`, and `.env`.

### Configure

1. Edit `.env` — add your API keys:

```bash
export DASHSCOPE_API_KEY=sk-xxx          # Required for FunASR/TingWu
export OBSIDIAN_VAULT_PATH="/path/to/vault"
export POE_API_KEY=pk-xxx                # Optional: AI summaries
```

2. Edit `config/subscriptions.yaml` — add your podcasts:

```yaml
podcasts:
  - name: "My Favorite Podcast"
    rss_url: "https://example.com/feed.xml"
    tags: ["tech"]
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
| FunASR (default) | ~0.79 CNY | Chinese-optimized | Chinese podcasts |
| Paraformer | ~0.29 CNY | Budget option | Cost-sensitive |
| TingWu | ~3.00 CNY | ASR + AI summary built-in | All-in-one |
| Whisper API | ~$0.36 | Multilingual | English/other languages |

Set `asr_engine` in `config/config.yaml`.

## AI Summary

FM2note can generate AI summaries with chapter breakdowns and keywords:

- **Poe** (default): Set `POE_API_KEY` in `.env`. Uses GPT-5.4 via Poe subscription.
- **None**: Without a summary API key, FM2note outputs transcription only.

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

Standard RSS feeds (Apple Podcasts, Spotify via RSS, etc.) don't need RSSHub.

### How to Find Xiaoyuzhou Podcast ID

Open the podcast page in your browser:
`https://www.xiaoyuzhoufm.com/podcast/PODCAST_ID`

Copy the `PODCAST_ID` part.

## Configuration

### config/config.yaml

| Field | Default | Description |
|---|---|---|
| `vault_path` | `/vault` | Obsidian vault path (override with `OBSIDIAN_VAULT_PATH` env var) |
| `podcast_dir` | `Podcasts` | Subdirectory in vault for notes |
| `poll_interval_hours` | `3` | Polling interval for `serve` mode |
| `asr_engine` | `funasr` | ASR engine: `funasr` / `paraformer` / `tingwu` / `whisper_api` |
| `max_retries` | `3` | Max retry attempts for failed episodes |
| `summary_cooldown` | `60` | Seconds between Poe API calls |

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DASHSCOPE_API_KEY` | Yes (for DashScope engines) | Alibaba DashScope API key |
| `OBSIDIAN_VAULT_PATH` | Yes | Absolute path to Obsidian vault |
| `POE_API_KEY` | No | Poe API key for AI summaries |
| `TINGWU_APP_ID` | No (only for `tingwu` engine) | TingWu App ID |
| `OPENAI_API_KEY` | No (only for `whisper_api`) | OpenAI API key |

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
| FunASR + Poe summary | ~16 CNY (~$2) |
| Paraformer + Poe summary | ~6 CNY (~$1) |
| TingWu (all-in-one) | ~55 CNY (~$8) |

## Development

```bash
pip install -e ".[dev]"
make lint        # ruff check
make test        # pytest (170+ tests)
make test-cov    # Coverage report
make format      # Auto-format
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

[MIT](LICENSE)
