"""Server-side components for FM2note (deploy alongside RSSHub).

Currently only ships the shared-cache sidecar — a tiny FastAPI service that
holds rendered note Markdown so two users sharing the same subscriptions
don't both pay for the same episode's ASR + summary. See ``cache_sidecar.py``.
"""
