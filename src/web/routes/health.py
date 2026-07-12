from __future__ import annotations

import contextlib
import os
from pathlib import Path

from fastapi import APIRouter

from src.config import load_config
from src.web.paths import CONFIG_PATH
from src.web.services.balance import fetch_balance

router = APIRouter(prefix="/api")


def _check(label: str, ok: bool, hint: str = "") -> dict:
    return {"label": label, "ok": ok, "hint": hint}


@router.get("/health-check")
async def health_check() -> dict:
    """Probe critical config + connectivity. Read-only; never modifies state.

    Returns one entry per check with ``{label, ok, hint}``. Frontend can decide
    how to render. Keys are **not** probed by actually calling the upstream
    (that would burn quota); only their presence is verified.
    """
    items: list[dict] = []

    # ---- Config load ----
    try:
        config = load_config(CONFIG_PATH)
        items.append(_check("配置文件可读", True))
    except Exception as e:
        items.append(_check("配置文件可读", False, f"{type(e).__name__}: {e}"))
        return {"items": items, "overall_ok": False}

    # ---- Obsidian vault ----
    vault = Path(config.vault_path).expanduser()
    if not vault.exists():
        items.append(_check("Obsidian Vault 路径", False, f"路径不存在: {vault}"))
    elif not vault.is_dir():
        items.append(_check("Obsidian Vault 路径", False, f"不是目录: {vault}"))
    elif not os.access(vault, os.W_OK):
        items.append(_check("Obsidian Vault 路径", False, f"无写权限: {vault}"))
    else:
        # POSIX W_OK only checks file-mode bits — on macOS the path may sit
        # inside a TCC-protected location (e.g. ~/Library/Mobile Documents/
        # for iCloud Drive) where the OS itself blocks writes unless the
        # parent process has Full Disk Access. The only way to know is to
        # actually try a write. The finally clause guarantees the probe file
        # never leaks into the user's vault even if the unlink itself fails.
        probe = vault / ".fm2note_writetest"
        try:
            probe.write_text("ok", encoding="utf-8")
            items.append(_check("Obsidian Vault 路径", True, str(vault)))
        except PermissionError:
            items.append(
                _check(
                    "Obsidian Vault 路径",
                    False,
                    "macOS 阻止写入：去 系统设置 → 隐私与安全性 → 完全磁盘访问，"
                    "把 Terminal 或 fm2note 加进白名单",
                )
            )
        except OSError as e:
            items.append(_check("Obsidian Vault 路径", False, f"写入失败: {type(e).__name__}"))
        finally:
            with contextlib.suppress(OSError):
                probe.unlink(missing_ok=True)

    # ---- State DB parent writable ----
    db_parent = Path(config.db_path).expanduser().parent
    db_writable = db_parent.exists() and os.access(db_parent, os.W_OK)
    if not db_writable:
        try:
            db_parent.mkdir(parents=True, exist_ok=True)
            db_writable = os.access(db_parent, os.W_OK)
        except OSError:
            db_writable = False
    items.append(
        _check(
            "状态数据库可写",
            db_writable,
            "" if db_writable else f"父目录无写权限: {db_parent}",
        )
    )

    # ---- ASR provider key ----
    if config.asr_engine == "poe":
        items.append(
            _check(
                "Poe 语音 Key",
                bool(config.poe_api_key),
                "已配置" if config.poe_api_key else "Poe 转写引擎需要 POE_API_KEY",
            )
        )
    elif config.asr_engine == "whisper_api":
        items.append(
            _check(
                "OpenAI 语音 Key",
                bool(config.openai_api_key),
                "已配置" if config.openai_api_key else "Whisper 引擎需要 OPENAI_API_KEY",
            )
        )
    else:
        items.append(
            _check(
                "DashScope 语音 Key",
                bool(config.dashscope_api_key),
                "已配置" if config.dashscope_api_key else "未配置（去设置页填 sk- 开头的 key）",
            )
        )

    # ---- Summary provider ----
    if config.summary_provider == "none":
        items.append(_check("AI 摘要", True, "已禁用"))
    elif config.poe_api_key or config.openai_api_key:
        which = "Poe" if config.poe_api_key else "OpenAI"
        items.append(_check("AI 摘要", True, f"{which} key 已配置"))
    else:
        items.append(_check("AI 摘要", False, "无可用 key（可在设置页填 Poe 或 OpenAI）"))

    # ---- TingWu app id (only if engine selected) ----
    if config.asr_engine == "tingwu":
        items.append(
            _check(
                "TingWu App ID",
                bool(config.tingwu_app_id),
                "已配置" if config.tingwu_app_id else "tingwu 引擎需要 TINGWU_APP_ID",
            )
        )

    # ---- Active transcription balance ----
    if config.asr_engine == "poe":
        items.append(
            _check(
                "Poe 转写余额",
                bool(config.poe_api_key),
                "无限（使用套餐积分）" if config.poe_api_key else "配置 POE_API_KEY 后显示",
            )
        )
    else:
        balance_state = await fetch_balance()
        if balance_state.configured:
            if balance_state.snapshot is not None:
                snap = balance_state.snapshot
                tag = {"ok": "✓", "warn": "⚠", "critical": "✕"}.get(snap.alert_level, "?")
                items.append(
                    _check(
                        "阿里云余额",
                        snap.alert_level != "critical",
                        f"{tag} ¥{snap.available_cash_amount:.2f} 现金可用",
                    )
                )
            else:
                items.append(_check("阿里云余额", False, balance_state.error or "未知错误"))

    overall_ok = all(item["ok"] for item in items)
    return {"items": items, "overall_ok": overall_ok}
