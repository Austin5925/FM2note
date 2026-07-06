# FM2note

[English](README.md) | [中文](README.zh-CN.md)

> Automatically transcribe podcasts and save them as Obsidian notes.

FM2note monitors podcast RSS feeds, transcribes episodes using cloud ASR, generates AI summaries, and writes structured Markdown notes directly into your Obsidian vault.

## Features

- **Local Web UI** — `fm2note web` (browser) or `fm2note app` (native window) with transcribe / history / subscriptions / settings pages
- **RSS monitoring** — auto-detect new episodes from any RSS/Atom feed
- **Multiple ASR engines** — FunASR, Paraformer, TingWu, Bailian, OpenAI Whisper
- **AI summaries** — chapter breakdown + keywords via Poe, OpenAI, or any OpenAI-compatible API
- **Direct Obsidian vault write** — Markdown with YAML frontmatter
- **Customizable templates** — configurable note template path and section labels
- **Subtitle detection** — skip ASR when subtitles are available (saves cost)
- **Aliyun balance widget** — optional top-nav badge with low-balance alert
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

1. Edit `.env` — add your API keys (credentials only; non-secret config lives
   in `config/config.yaml` and is editable from the Web UI):

```bash
export DASHSCOPE_API_KEY=sk-xxx          # Required for FunASR/TingWu

# AI summary (pick one, or leave both empty to skip summaries)
export POE_API_KEY=pk-xxx                # Poe subscription
export OPENAI_API_KEY=sk-xxx             # OpenAI / DeepSeek / Groq
```

2. Set the Obsidian vault path in `config/config.yaml` (or the Web UI's 设置 page):

```yaml
vault_path: "/Users/you/Documents/MyVault"
podcast_dir: "10_Podcasts"
```

2. Add podcast subscriptions. The easiest path is the Web UI **Subscriptions** page:
paste a Xiaoyuzhou podcast page, episode page, or share text, and FM2note will generate
the RSSHub subscription URL automatically.

You can also edit `config/subscriptions.yaml` manually:

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
fm2note run-once     # Process once
fm2note serve        # Continuous daemon (polls every 3 hours)
fm2note transcribe <URL>   # Single episode (no RSS feed needed)
```

> `.env` is auto-loaded from the working directory — no need to `source` manually.

## Web UI (v1.4+)

For everyone who doesn't want to touch the terminal after first install:

```bash
fm2note web          # Browser tab at http://127.0.0.1:7878
fm2note app          # Native desktop window (requires fm2note[app] extra)
fm2note install-shortcut   # Drop a double-clickable launcher on the Desktop
```

### Signed macOS Desktop App

For a real `.app` bundle distributed outside the Mac App Store, install the
desktop and packaging extras:

```bash
python3.11 -m pip install -e ".[app,macos]"
make macos-app
```

This builds `dist/FM2note.app`. If you want a drag-install disk image for local
testing, run:

```bash
make macos-dmg
```

The distributable artifact is the DMG. It contains `FM2note.app` plus an
`Applications` shortcut and opens as a normal drag-to-install Finder window. If
a `Developer ID Application` certificate is available in Keychain, the build
script signs with hardened runtime. Without a Developer ID certificate it falls
back to ad-hoc signing for local testing.

To notarize a Developer ID signed build, first store credentials once:

```bash
xcrun notarytool store-credentials fm2note-notary
APPLE_NOTARY_PROFILE=fm2note-notary make macos-notarize
```

This produces `dist/FM2note-macos.dmg` and a backup `dist/FM2note-macos.zip`.
For normal distribution, share the DMG. This public build does not prefill your
personal RSSHub or subscriptions; users fill their own settings on first launch.

To build a private prefilled variant, put only non-secret first-run files under
an ignored local profile directory:

```text
packaging/profiles/girlfriend/
  config/config.yaml
  config/subscriptions.yaml
  .env                  # optional; avoid shipping real API keys
```

Then run:

```bash
APPLE_NOTARY_PROFILE=fm2note-notary make macos-notarize-girlfriend
```

This produces `dist/FM2note-girlfriend-macos.dmg`. Bundled profile files are
copied once into the user's `~/Library/Application Support/FM2note` on first
launch and never overwrite later edits.

The packaged app stores its runtime config under
`~/Library/Application Support/FM2note` by default. Set `FM2NOTE_HOME` before
launching if you want it to reuse another config directory.

The desktop app and the background service are separate. Opening the app starts
the local GUI server for the current window. The launchd background service is
only for scheduled feed polling when the window is closed; Settings calls it
"background auto-check" to keep that distinction visible.

The UI ships four pages:

- **转录** — paste a podcast URL → 5-stage progress (resolve / subtitle / ASR / summary / write) → one-click `obsidian://` deep link
- **历史** — recent episodes from `state.db` + pending-summary retries
- **订阅** — paste Xiaoyuzhou links to auto-generate RSSHub feeds, or manually edit/test RSS feeds (ruamel.yaml preserves your YAML comments)
- **设置** — write API keys, switch engines, edit vault path; with health self-check and launchd service status

The Aliyun account balance shows in the top nav (configure via the optional `ALIYUN_ACCESS_KEY_ID` / `_SECRET` env vars — see `.env.example`). Bind is always `127.0.0.1`; use a reverse proxy for LAN access.

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

FM2note generates AI summaries with chapter breakdowns and keywords. Set the provider in `config/config.yaml` (or the Web UI's 设置 page):

| Provider | YAML | API Key (`.env`) | Model Default |
|---|---|---|---|
| Poe | `summary_provider: poe` | `POE_API_KEY` | GPT-5.5 |
| OpenAI | `summary_provider: openai` | `OPENAI_API_KEY` | gpt-4o-mini |
| DeepSeek/Groq/Ollama | `summary_provider: openai` + `summary_base_url: <url>` | `OPENAI_API_KEY` | varies |
| None | `summary_provider: none` | — | — |
| Auto (default) | `summary_provider: auto` | any available | auto |

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

### config/config.yaml (non-secret config)

All non-sensitive configuration lives here and is editable from the Web UI's 设置 page.

| Field | Default | Description |
|---|---|---|
| `vault_path` | — | Obsidian vault path (required) |
| `podcast_dir` | `Podcasts` | Subdirectory in vault for notes |
| `poll_interval_hours` | `3` | Polling interval for `serve` mode |
| `asr_engine` | `funasr` | ASR engine: `funasr` / `paraformer` / `tingwu` / `bailian` / `whisper_api` |
| `max_retries` | `3` | Max retry attempts for failed episodes |
| `summary_provider` | `auto` | `auto` / `poe` / `openai` / `none` |
| `summary_model` | — | Override model (default: provider-specific) |
| `summary_cooldown` | `60` | Seconds between summary API calls |
| `summary_base_url` | — | OpenAI-compatible endpoint (DeepSeek, Groq, Ollama) |
| `log_level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `template_path` | — | Custom Jinja2 template path (optional) |

### .env (sensitive credentials only)

As of v1.4.12, `.env` holds **only** API keys / credentials. Putting any non-secret field here will trigger a stale-env warning on startup — it would silently shadow Web UI edits.

| Variable | Required | Description |
|---|---|---|
| `DASHSCOPE_API_KEY` | Yes (for DashScope engines) | Alibaba DashScope API key |
| `POE_API_KEY` | No | Poe API key for AI summaries |
| `OPENAI_API_KEY` | No | OpenAI API key (summaries and/or Whisper) |
| `TINGWU_APP_ID` | No (only for `tingwu`) | TingWu App ID |
| `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` | No | RAM sub-account AK/SK for balance badge |

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
