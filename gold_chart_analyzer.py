"""
Gold Chart Analyzer PRO — V5.0
XAUUSD SNRZ Visual Analyzer
24/7 Telegram Bot

Flow
----
1. User sends H1/H4 chart.
2. User sends M1/M5 chart.
3. Gemini analyzes both images using strict SNRZ rules.
4. Deterministic Python engine validates the AI result.
5. Bot sends BUY / SELL only when every mandatory filter passes.
6. Otherwise it sends WAIT with the exact missing condition.

Required environment variables
-------------------------------
TELEGRAM_BOT_TOKEN
GEMINI_API_KEY

Optional environment variables
------------------------------
GEMINI_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODEL=gemini-3.7-flash
ADMIN_ID=5874840448
POLL_TIMEOUT=30
GEMINI_RETRIES=3
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from google import genai
from google.genai import types


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Gemini 3.8 Flash is the current production Flash default.
# Keep this configurable so the bot can be changed without editing code.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
GEMINI_FALLBACK_MODEL = os.getenv(
    "GEMINI_FALLBACK_MODEL",
    "gemini-3.7-flash",
).strip()

ADMIN_ID = os.getenv("ADMIN_ID", "5874840448").strip()

MIN_STRONG_SCORE = 80.0
MIN_STRONG_CONFIDENCE = 80.0
MIN_RR = 2.0

POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT", "30"))
GEMINI_RETRIES = max(1, int(os.getenv("GEMINI_RETRIES", "3")))

TELEGRAM_TIMEOUT = 45
TELEGRAM_DOWNLOAD_TIMEOUT = 60
TELEGRAM_MESSAGE_LIMIT = 4000

ALLOWED_USERS_FILE = Path("allowed_users.json")
IMAGE_DIR = Path("chart_images")
MAX_IMAGE_AGE_SECONDS = 24 * 60 * 60


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("GoldChartAnalyzer")


# ============================================================
# GEMINI
# ============================================================

gemini: Optional[genai.Client] = None

if GEMINI_API_KEY:
    try:
        gemini = genai.Client(api_key=GEMINI_API_KEY)
        logger.info(
            "Gemini client initialized. primary=%s fallback=%s",
            GEMINI_MODEL,
            GEMINI_FALLBACK_MODEL,
        )
    except Exception:
        logger.exception("Gemini client initialization failed.")
else:
    logger.warning("GEMINI_API_KEY is missing.")


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_API = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    if TELEGRAM_BOT_TOKEN
    else ""
)


# ============================================================
# SAFE HELPERS
# ============================================================

def safe_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None

    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
            if value.lower() in {
                "",
                "n/a",
                "na",
                "none",
                "null",
                "unknown",
                "-",
            }:
                return None

        return float(value)
    except (TypeError, ValueError):
        return None


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "yes",
            "y",
            "1",
            "confirmed",
            "valid",
            "complete",
        }

    return False


def clean_text(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default

    text = str(value).strip()
    return text if text else default


def format_price(value: Any) -> str:
    number = safe_float(value)
    return "N/A" if number is None else f"{number:.2f}"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ============================================================
# TELEGRAM API
# ============================================================

def telegram_request(
    method: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = TELEGRAM_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    if not TELEGRAM_API:
        logger.error("TELEGRAM_BOT_TOKEN is missing.")
        return None

    try:
        response = requests.post(
            f"{TELEGRAM_API}/{method}",
            json=payload or {},
            timeout=timeout,
        )

        if response.status_code != 200:
            logger.error(
                "Telegram HTTP %s on %s: %s",
                response.status_code,
                method,
                response.text[:500],
            )
            return None

        data = response.json()

        if not data.get("ok"):
            logger.error(
                "Telegram method %s failed: %s",
                method,
                data,
            )

        return data

    except requests.RequestException as exc:
        logger.error("Telegram request error on %s: %s", method, exc)
        return None
    except ValueError as exc:
        logger.error("Telegram JSON error on %s: %s", method, exc)
        return None


def send_message(
    chat_id: Any,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
) -> None:
    if not text:
        return

    for start in range(0, len(text), TELEGRAM_MESSAGE_LIMIT):
        chunk = text[start:start + TELEGRAM_MESSAGE_LIMIT]

        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": chunk,
        }

        if reply_markup:
            payload["reply_markup"] = reply_markup

        telegram_request("sendMessage", payload)


def answer_callback(callback_id: str, text: str = "") -> None:
    telegram_request(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text,
        },
    )


# ============================================================
# ACCESS CONTROL
# ============================================================

USER_SESSIONS: Dict[str, Dict[str, Any]] = {}
PENDING_USERS: Dict[str, Dict[str, Any]] = {}


def load_allowed_users() -> Dict[str, Any]:
    if not ALLOWED_USERS_FILE.exists():
        return {}

    try:
        with ALLOWED_USERS_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("Could not load allowed_users.json.")
        return {}


def save_allowed_users(users: Dict[str, Any]) -> None:
    try:
        tmp = ALLOWED_USERS_FILE.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as file:
            json.dump(users, file, ensure_ascii=False, indent=2)
        tmp.replace(ALLOWED_USERS_FILE)
    except Exception:
        logger.exception("Could not save allowed_users.json.")


ALLOWED_USERS = load_allowed_users()

if ADMIN_ID not in ALLOWED_USERS:
    ALLOWED_USERS[ADMIN_ID] = {
        "name": "ADMIN",
        "approved": True,
    }
    save_allowed_users(ALLOWED_USERS)


def is_allowed(user_id: Any) -> bool:
    uid = str(user_id)
    return uid == ADMIN_ID or uid in ALLOWED_USERS


def request_access(
    user_id: Any,
    username: str = "",
    first_name: str = "",
) -> None:
    uid = str(user_id)

    if is_allowed(uid):
        return

    PENDING_USERS[uid] = {
        "username": username or "",
        "first_name": first_name or "",
        "requested_at": int(time.time()),
    }


# ============================================================
# ADMIN
# ============================================================

def admin_help() -> str:
    return (
        "👑 ADMIN PANEL\n\n"
        "/adduser ID\n"
        "/removeuser ID\n"
        "/users\n"
        "/pending\n"
        "/broadcast TEXT\n"
        "/admin"
    )


def handle_admin_command(
    chat_id: Any,
    user_id: Any,
    text: str,
) -> bool:
    if str(user_id) != ADMIN_ID:
        return False

    parts = text.strip().split(maxsplit=1)
    if not parts:
        return True

    command = parts[0].lower()

    if command == "/admin":
        send_message(chat_id, admin_help())
        return True

    if command == "/adduser":
        if len(parts) < 2:
            send_message(chat_id, "❌ User ID بنووسە.")
            return True

        target = parts[1].strip()

        if not target.isdigit():
            send_message(chat_id, "❌ User ID دروست نییە.")
            return True

        ALLOWED_USERS[target] = {
            "name": target,
            "approved": True,
        }
        save_allowed_users(ALLOWED_USERS)
        PENDING_USERS.pop(target, None)

        send_message(chat_id, f"✅ User {target} زیادکرا.")
        return True

    if command == "/removeuser":
        if len(parts) < 2:
            send_message(chat_id, "❌ User ID بنووسە.")
            return True

        target = parts[1].strip()

        if target == ADMIN_ID:
            send_message(chat_id, "❌ ناتوانیت Admin بسڕیتەوە.")
            return True

        ALLOWED_USERS.pop(target, None)
        save_allowed_users(ALLOWED_USERS)

        send_message(chat_id, f"🗑 User {target} لابرا.")
        return True

    if command == "/users":
        if not ALLOWED_USERS:
            send_message(chat_id, "هیچ User ـێک نییە.")
            return True

        lines = ["👥 ALLOWED USERS", ""]
        for uid, info in ALLOWED_USERS.items():
            name = clean_text(info.get("name"), "")
            lines.append(f"• {uid} — {name}")

        send_message(chat_id, "\n".join(lines))
        return True

    if command == "/pending":
        if not PENDING_USERS:
            send_message(chat_id, "📭 هیچ داواکارییەکی چاوەڕوان نییە.")
            return True

        lines = ["📥 PENDING USERS", ""]
        for uid, info in PENDING_USERS.items():
            first_name = clean_text(info.get("first_name"), "")
            username = clean_text(info.get("username"), "")
            username = f"@{username}" if username else ""
            lines.append(f"• {uid} — {first_name} {username}".strip())

        send_message(chat_id, "\n".join(lines))
        return True

    if command == "/broadcast":
        if len(parts) < 2:
            send_message(chat_id, "❌ دەقەکە بنووسە.")
            return True

        text_to_send = parts[1]
        sent = 0

        for uid in list(ALLOWED_USERS.keys()):
            result = telegram_request(
                "sendMessage",
                {
                    "chat_id": uid,
                    "text": text_to_send,
                },
            )
            if result and result.get("ok"):
                sent += 1

        send_message(
            chat_id,
            f"📢 Broadcast نێردرا بۆ {sent} User.",
        )
        return True

    return False


# ============================================================
# PROMPTS
# ============================================================

SYSTEM_PROMPT = r"""
You are a professional visual XAUUSD SNRZ chart analyst.

Your job is NOT to guess a trade.
Your job is to extract what is visibly present on the charts and then
apply the exact SNRZ rules below.

GENERAL VISUAL RULES
--------------------
1. Inspect the actual candle image carefully before answering.
2. Read candles from left to right.
3. The RIGHT side is the most recent part of the chart.
4. Do not call the whole chart trend bearish just because older candles
   made a bearish move.
5. Give more weight to the latest visible swing structure.
6. A strong recent bullish impulse followed by higher highs/higher lows
   must be recognized as bullish/recovery structure when visible.
7. A strong recent bearish impulse followed by lower lows/lower highs
   must be recognized as bearish structure when visible.
8. Do not invent candles, prices, breakouts, or levels.
9. If a price level is not readable, use null.
10. Current price alone does NOT prove a historical breakout.
11. A wick/touch/rejection alone is NOT a breakout.
12. Candle BODY acceptance beyond the same historical level is required.
13. Do not confuse a normal support/resistance with VS/VR.

VS DEFINITION
------------
Original Support
-> UP move
-> NEW Resistance formed AFTER that Support
-> UP move again
-> SAME NEW Resistance broken
-> candle/body acceptance above that Resistance
-> Original Support becomes VS

VR DEFINITION
------------
Original Resistance
-> DOWN move
-> NEW Support formed AFTER that Resistance
-> DOWN move again
-> SAME NEW Support broken
-> candle/body acceptance below that Support
-> Original Resistance becomes VR

IMPORTANT VS/VR
---------------
- The NEW level must form AFTER the original level.
- The SAME NEW level must be broken later.
- Do not substitute a different resistance/support.
- If the historical sequence is not visibly confirmed, set the structure
  invalid rather than inventing confirmation.

ZONE
----
After a valid VS/VR:
1. Identify the formation candle.
2. Look at the immediately previous candle.
3. Compare BODY SIZE only.
4. Select the SHORTER body.
5. Entire selected candle HIGH -> LOW is the zone.
6. Do NOT use an engulfing-zone rule.

ENTRY FLOW
----------
VALID VS/VR
-> ZONE
-> PRICE PULLBACK / RETEST
-> M1/M5 CONFIRMATION
-> STRONG FILTERS
-> ENTRY

Confirmation BEFORE pullback is invalid.

BUY confirmations:
- RBS
- SRR
- I.VR
- complete PO2

SELL confirmations:
- SBR
- RSS
- I.VS
- complete PO2

STRONG SIGNAL
-------------
BUY or SELL is allowed only when ALL are true:
- score >= 80
- confidence >= 80
- RR >= 1:2
- valid VS/VR
- valid zone
- actual zone retest
- confirmation AFTER pullback
- HTF/LTF agreement
- entry exists
- SL exists
- TP1 exists
- no strong rejection
- confirmation side agrees with trade side

If one mandatory item is missing, signal MUST be WAIT.

OUTPUT
------
Return JSON only.
No markdown.
No explanation outside JSON.
"""


USER_ANALYSIS_PROMPT = r"""
Analyze the two supplied XAUUSD chart images.

IMAGE 1 = HTF H1/H4
Use it for:
- latest market trend
- support/resistance
- VS/VR
- zone
- structure

IMAGE 2 = LTF M1/M5
Use it for:
- zone retest
- pullback
- RBS
- SRR
- SBR
- RSS
- I.VS
- I.VR
- PO2
- confirmation

CRITICAL:
The most recent candles are on the RIGHT side of each chart.
Do not describe the entire chart using only an old move.
Determine trend from the latest visible swing structure.

For VS/VR, only confirm the structure when the historical sequence is
visibly supported by the candles. If a precise numerical break price cannot
be read, break_price may be null while break_confirmed may still be true
if the historical breakout is visually obvious.

Return ONLY this JSON shape:

{
  "symbol": "XAUUSD",

  "market": {
    "trend": "",
    "structure": "",
    "current_price": null
  },

  "structures": {
    "vs": {
      "candidate": false,
      "original_level": null,
      "validation_level": null,
      "break_price": null,
      "formation_candle": "",
      "break_candle": "",
      "evidence": {
        "original_level_visible": false,
        "first_move_confirmed": false,
        "new_level_formed_after_original": false,
        "second_move_confirmed": false,
        "same_level_broken": false,
        "break_confirmed": false
      },
      "notes": ""
    },

    "vr": {
      "candidate": false,
      "original_level": null,
      "validation_level": null,
      "break_price": null,
      "formation_candle": "",
      "break_candle": "",
      "evidence": {
        "original_level_visible": false,
        "first_move_confirmed": false,
        "new_level_formed_after_original": false,
        "second_move_confirmed": false,
        "same_level_broken": false,
        "break_confirmed": false
      },
      "notes": ""
    }
  },

  "zones": {
    "vs_zone": {
      "valid": false,
      "high": null,
      "low": null,
      "selected_candle": "",
      "body_size": null,
      "previous_candle_body_size": null
    },

    "vr_zone": {
      "valid": false,
      "high": null,
      "low": null,
      "selected_candle": "",
      "body_size": null,
      "previous_candle_body_size": null
    }
  },

  "pullback": {
    "occurred": false,
    "side": "",
    "zone_retested": false,
    "retest_price": null
  },

  "confirmation": {
    "found": false,
    "name": "",
    "side": "",
    "after_pullback": false,
    "complete": false,
    "notes": ""
  },

  "trade": {
    "signal": "WAIT",
    "score": 0,
    "confidence": 0,
    "entry": null,
    "sl": null,
    "tp1": null,
    "tp2": null,
    "rr": null,
    "rejection": false
  },

  "htf_ltf_agreement": false,
  "reason": "",
  "wait_for": ""
}
"""


# ============================================================
# JSON
# ============================================================

def clean_json_text(text: str) -> str:
    if not text:
        return ""

    cleaned = text.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start >= 0 and end > start:
        return cleaned[start:end + 1]

    return cleaned


def parse_json_response(text: str) -> Dict[str, Any]:
    cleaned = clean_json_text(text)

    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        logger.error(
            "Gemini returned invalid JSON: %s",
            cleaned[:2000],
        )
        return {}


# ============================================================
# STRUCTURES
# ============================================================

def normalize_structure(structure: Any) -> Dict[str, Any]:
    if not isinstance(structure, dict):
        structure = {}

    evidence = structure.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}

    return {
        "candidate": safe_bool(structure.get("candidate")),
        "original_level": safe_float(structure.get("original_level")),
        "validation_level": safe_float(structure.get("validation_level")),
        "break_price": safe_float(structure.get("break_price")),
        "formation_candle": clean_text(
            structure.get("formation_candle"),
            "",
        ),
        "break_candle": clean_text(
            structure.get("break_candle"),
            "",
        ),
        "evidence": {
            key: safe_bool(evidence.get(key))
            for key in (
                "original_level_visible",
                "first_move_confirmed",
                "new_level_formed_after_original",
                "second_move_confirmed",
                "same_level_broken",
                "break_confirmed",
            )
        },
        "notes": clean_text(structure.get("notes"), ""),
    }


def structure_evidence_score(structure: Dict[str, Any]) -> int:
    evidence = structure.get("evidence", {})
    keys = (
        "original_level_visible",
        "first_move_confirmed",
        "new_level_formed_after_original",
        "second_move_confirmed",
        "same_level_broken",
        "break_confirmed",
    )
    return sum(
        1 for key in keys if safe_bool(evidence.get(key))
    )


def verify_vs(structure: Any) -> Tuple[bool, str]:
    s = normalize_structure(structure)

    original = s["original_level"]
    validation = s["validation_level"]
    break_price = s["break_price"]
    ev = s["evidence"]

    if original is None:
        return False, "VS: original Support missing."
    if validation is None:
        return False, "VS: NEW Resistance missing."
    if validation <= original:
        return False, "VS: NEW Resistance must be above Support."

    required = {
        "original_level_visible": "Support visibility",
        "first_move_confirmed": "first UP move",
        "new_level_formed_after_original": "NEW Resistance after Support",
        "second_move_confirmed": "second UP move",
        "same_level_broken": "SAME NEW Resistance break",
        "break_confirmed": "breakout candle/body",
    }

    for key, label in required.items():
        if not ev.get(key):
            return False, f"VS: {label} not confirmed."

    if break_price is not None and break_price <= validation:
        return False, "VS: break price is not above NEW Resistance."

    return True, "VS validated."


def verify_vr(structure: Any) -> Tuple[bool, str]:
    s = normalize_structure(structure)

    original = s["original_level"]
    validation = s["validation_level"]
    break_price = s["break_price"]
    ev = s["evidence"]

    if original is None:
        return False, "VR: original Resistance missing."
    if validation is None:
        return False, "VR: NEW Support missing."
    if validation >= original:
        return False, "VR: NEW Support must be below Resistance."

    required = {
        "original_level_visible": "Resistance visibility",
        "first_move_confirmed": "first DOWN move",
        "new_level_formed_after_original": "NEW Support after Resistance",
        "second_move_confirmed": "second DOWN move",
        "same_level_broken": "SAME NEW Support break",
        "break_confirmed": "breakout candle/body",
    }

    for key, label in required.items():
        if not ev.get(key):
            return False, f"VR: {label} not confirmed."

    if break_price is not None and break_price >= validation:
        return False, "VR: break price is not below NEW Support."

    return True, "VR validated."


def get_valid_structures(data: Dict[str, Any]) -> Dict[str, Any]:
    structures = data.get("structures", {})
    if not isinstance(structures, dict):
        structures = {}

    vs = normalize_structure(structures.get("vs", {}))
    vr = normalize_structure(structures.get("vr", {}))

    vs_valid, vs_reason = verify_vs(vs)
    vr_valid, vr_reason = verify_vr(vr)

    return {
        "vs": vs,
        "vr": vr,
        "vs_valid": vs_valid,
        "vr_valid": vr_valid,
        "vs_reason": vs_reason,
        "vr_reason": vr_reason,
    }


# ============================================================
# ZONE
# ============================================================

def zone_is_valid(
    data: Dict[str, Any],
    side: str,
) -> Tuple[bool, Optional[float], Optional[float]]:
    zones = data.get("zones", {})
    if not isinstance(zones, dict):
        return False, None, None

    zone_key = "vs_zone" if side == "BUY" else "vr_zone"
    zone = zones.get(zone_key, {})

    if not isinstance(zone, dict):
        return False, None, None

    valid = safe_bool(zone.get("valid"))
    high = safe_float(zone.get("high"))
    low = safe_float(zone.get("low"))
    body = safe_float(zone.get("body_size"))
    previous_body = safe_float(zone.get("previous_candle_body_size"))

    if not valid:
        return False, high, low

    if high is None or low is None or high <= low:
        return False, high, low

    if body is None or previous_body is None:
        return False, high, low

    if body >= previous_body:
        return False, high, low

    return True, high, low


# ============================================================
# PULLBACK / CONFIRMATION
# ============================================================

def pullback_is_valid(data: Dict[str, Any]) -> bool:
    pullback = data.get("pullback", {})
    if not isinstance(pullback, dict):
        return False

    return (
        safe_bool(pullback.get("occurred"))
        and safe_bool(pullback.get("zone_retested"))
        and safe_float(pullback.get("retest_price")) is not None
    )


BUY_CONFIRMATIONS = {"RBS", "SRR", "I.VR", "PO2"}
SELL_CONFIRMATIONS = {"SBR", "RSS", "I.VS", "PO2"}


def normalize_confirmation_name(name: Any) -> str:
    if not name:
        return ""

    value = str(name).strip().upper()
    value = value.replace(" ", "")
    value = value.replace("-", "")
    return value


def confirmation_is_valid(
    data: Dict[str, Any],
) -> Tuple[bool, str, str]:
    confirmation = data.get("confirmation", {})
    if not isinstance(confirmation, dict):
        return False, "", ""

    found = safe_bool(confirmation.get("found"))
    complete = safe_bool(confirmation.get("complete"))
    after_pullback = safe_bool(confirmation.get("after_pullback"))

    side = clean_text(
        confirmation.get("side"),
        "",
    ).upper()

    name = normalize_confirmation_name(
        confirmation.get("name")
    )

    if not found or not complete or not after_pullback:
        return False, name, side

    if side == "BUY":
        return name in BUY_CONFIRMATIONS, name, side

    if side == "SELL":
        return name in SELL_CONFIRMATIONS, name, side

    return False, name, side


# ============================================================
# TRADE MATH
# ============================================================

def calculate_rr(
    entry: Any,
    sl: Any,
    tp1: Any,
) -> Optional[float]:
    e = safe_float(entry)
    s = safe_float(sl)
    t = safe_float(tp1)

    if e is None or s is None or t is None:
        return None

    risk = abs(e - s)
    reward = abs(t - e)

    if risk <= 0:
        return None

    return reward / risk


def price_direction_is_valid(
    signal: str,
    entry: Optional[float],
    sl: Optional[float],
    tp1: Optional[float],
) -> bool:
    if entry is None or sl is None or tp1 is None:
        return False

    if signal == "BUY":
        return sl < entry < tp1

    if signal == "SELL":
        return tp1 < entry < sl

    return False


# ============================================================
# DETERMINISTIC STRONG SIGNAL ENGINE
# ============================================================

def strong_signal_engine(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        data = {}

    structures = get_valid_structures(data)
    vs_valid = structures["vs_valid"]
    vr_valid = structures["vr_valid"]

    trade = data.get("trade", {})
    if not isinstance(trade, dict):
        trade = {}

    raw_signal = clean_text(
        trade.get("signal"),
        "WAIT",
    ).upper()

    if raw_signal not in {"BUY", "SELL", "WAIT"}:
        raw_signal = "WAIT"

    score = safe_float(trade.get("score")) or 0.0
    confidence = safe_float(trade.get("confidence")) or 0.0

    entry = safe_float(trade.get("entry"))
    sl = safe_float(trade.get("sl"))
    tp1 = safe_float(trade.get("tp1"))
    tp2 = safe_float(trade.get("tp2"))

    rejection = safe_bool(trade.get("rejection"))

    if raw_signal == "BUY":
        structure_valid = vs_valid
        structure_name = "VS"
    elif raw_signal == "SELL":
        structure_valid = vr_valid
        structure_name = "VR"
    else:
        structure_valid = vs_valid or vr_valid
        structure_name = "VS" if vs_valid else ("VR" if vr_valid else "")

    zone_valid = False
    zone_high = None
    zone_low = None

    if raw_signal in {"BUY", "SELL"}:
        zone_valid, zone_high, zone_low = zone_is_valid(data, raw_signal)
    else:
        if vs_valid:
            zone_valid, zone_high, zone_low = zone_is_valid(data, "BUY")
        if not zone_valid and vr_valid:
            zone_valid, zone_high, zone_low = zone_is_valid(data, "SELL")

    pullback_valid = pullback_is_valid(data)

    (
        confirmation_valid,
        confirmation_name,
        confirmation_side,
    ) = confirmation_is_valid(data)

    agreement = safe_bool(data.get("htf_ltf_agreement"))
    rr = calculate_rr(entry, sl, tp1)

    side_consistent = True
    if raw_signal == "BUY":
        side_consistent = confirmation_side == "BUY"
    elif raw_signal == "SELL":
        side_consistent = confirmation_side == "SELL"

    direction_valid = (
        price_direction_is_valid(
            raw_signal,
            entry,
            sl,
            tp1,
        )
        if raw_signal in {"BUY", "SELL"}
        else False
    )

    checks = {
        "structure": structure_valid,
        "zone": zone_valid,
        "pullback": pullback_valid,
        "confirmation": confirmation_valid,
        "agreement": agreement,
        "score": score >= MIN_STRONG_SCORE,
        "confidence": confidence >= MIN_STRONG_CONFIDENCE,
        "rr": rr is not None and rr >= MIN_RR,
        "entry": entry is not None,
        "sl": sl is not None,
        "tp1": tp1 is not None,
        "direction": direction_valid,
        "no_rejection": not rejection,
        "side_consistent": side_consistent,
    }

    all_valid = all(checks.values())

    final_signal = (
        raw_signal
        if all_valid and raw_signal in {"BUY", "SELL"}
        else "WAIT"
    )

    missing = []

    if not structure_valid:
        missing.append(f"VALID {structure_name or 'VS/VR'}")
    if not zone_valid:
        missing.append("Zone")
    if not pullback_valid:
        missing.append("Pullback/Retest")
    if not confirmation_valid:
        missing.append("M1/M5 Confirmation")
    if not agreement:
        missing.append("HTF/LTF agreement")
    if score < MIN_STRONG_SCORE:
        missing.append("Score ≥ 80")
    if confidence < MIN_STRONG_CONFIDENCE:
        missing.append("Confidence ≥ 80%")
    if rr is None or rr < MIN_RR:
        missing.append("RR ≥ 1:2")
    if entry is None:
        missing.append("Entry")
    if sl is None:
        missing.append("SL")
    if tp1 is None:
        missing.append("TP1")
    if not direction_valid and raw_signal in {"BUY", "SELL"}:
        missing.append("Entry/SL/TP direction")
    if rejection:
        missing.append("No rejection")
    if not side_consistent:
        missing.append("Confirmation side")

    if final_signal == "WAIT":
        if not (vs_valid or vr_valid):
            wait_for = (
                "Complete valid VS/VR structure "
                "with visible historical break"
            )
        elif not zone_valid:
            wait_for = f"{structure_name} Zone"
        elif not pullback_valid:
            wait_for = f"Price Pullback/Retest to {structure_name} Zone"
        elif not confirmation_valid:
            wait_for = "M1/M5 Confirmation after Pullback"
        elif not agreement:
            wait_for = "HTF/LTF agreement"
        elif not direction_valid:
            wait_for = "Logical Entry / SL / TP"
        else:
            wait_for = "Complete Strong Signal filters"
    else:
        wait_for = ""

    decision_reason, solution = build_decision_explanation(
        final_signal=final_signal,
        raw_signal=raw_signal,
        checks=checks,
        missing=missing,
        structure_name=structure_name,
        confirmation_name=confirmation_name,
        score=score,
        confidence=confidence,
        rr=rr,
        rejection=rejection,
        ai_reason=data.get("reason", ""),
    )

    result = dict(data)

    result["engine"] = {
        "vs_valid": vs_valid,
        "vr_valid": vr_valid,
        "vs_reason": structures["vs_reason"],
        "vr_reason": structures["vr_reason"],
        "structure_evidence": {
            "vs": structure_evidence_score(structures["vs"]),
            "vr": structure_evidence_score(structures["vr"]),
        },
        "checks": checks,
        "missing": missing,
        "side_consistent": side_consistent,
        "direction_valid": direction_valid,
        "decision_reason": decision_reason,
        "solution": solution,
    }

    result["decision_reason"] = decision_reason
    result["solution"] = solution

    result["trade"] = {
        "signal": final_signal,
        "score": round(clamp(score, 0, 100), 1),
        "confidence": round(clamp(confidence, 0, 100), 1),
        "entry": entry if final_signal != "WAIT" else None,
        "sl": sl if final_signal != "WAIT" else None,
        "tp1": tp1 if final_signal != "WAIT" else None,
        "tp2": tp2 if final_signal != "WAIT" else None,
        "rr": (
            round(rr, 2)
            if rr is not None and final_signal != "WAIT"
            else None
        ),
        "rejection": rejection,
    }

    result["wait_for"] = wait_for
    return result


# ============================================================
# SIGNAL REASON / ACTION PLAN
# ============================================================

def build_decision_explanation(
    final_signal: str,
    raw_signal: str,
    checks: Dict[str, bool],
    missing: list,
    structure_name: str,
    confirmation_name: str,
    score: float,
    confidence: float,
    rr: Optional[float],
    rejection: bool,
    ai_reason: Any = "",
) -> Tuple[str, str]:
    """Create a deterministic Kurdish explanation and next action."""

    if final_signal in {"BUY", "SELL"}:
        side = "BUY" if final_signal == "BUY" else "SELL"
        reasons = [
            f"{structure_name} ـی دروست پشتڕاستکراوە",
            "Zone ـەکە دروستە و Retest کراوە",
            f"Confirmation ـی {confirmation_name or 'دروست'} دوای Pullback هاتووە",
            "HTF و LTF هاوتان",
            f"Score {score:.0f}/100 و Confidence {confidence:.0f}% ـە",
            f"RR {rr:.2f} ـە" if rr is not None else "RR ـی پێویست هەیە",
        ]
        reason = f"هۆکاری {side}: " + "؛ ".join(reasons) + "."
        solution = (
            "ئەمە Strong Signal ـە. پێش Entry دووبارە دڵنیابە لە Spread/Execution، "
            "پاشان Entry بە SL و TP ـی دیاریکراو بەڕێوەببە."
        )
        return reason, solution

    # Prefer the first blocking condition because it gives the user a clear next step.
    blocker = ""
    if not checks.get("structure", False):
        blocker = "VS/VR ـی تەواو نییە"
        solution = "H1/H4 ـەکە دوبارە بنێرە تا historical break ـی ڕوون بۆ VS/VR دیاری بکرێت."
    elif not checks.get("zone", False):
        blocker = f"{structure_name or 'VS/VR'} Zone ـی دروست نییە"
        solution = "چاوەڕێی Zone ـی دروست بکە؛ Formation candle و previous candle بە body size بەراورد بکرێن."
    elif not checks.get("pullback", False):
        blocker = "Price هێشتا Pullback/Retest ـی Zone ـی نەکردووە"
        solution = f"چاوەڕێی Pullback/Retest بۆ {structure_name or 'Zone'} بکە؛ Confirmation پێش Pullback مەقبول نییە."
    elif not checks.get("confirmation", False):
        blocker = "Confirmation ـی M1/M5 دوای Pullback نییە"
        solution = "M1/M5 بنێرە و چاوەڕێی RBS/SRR/I.VR یان SBR/RSS/I.VS/PO2 ـی تەواو بکە."
    elif not checks.get("agreement", False):
        blocker = "HTF/LTF هاوتا نین"
        solution = "چاوەڕێی هاوتایی H1/H4 و M1/M5 بکە؛ بێ agreement سیگناڵ مەدە."
    elif not checks.get("score", False):
        blocker = f"Score تەنها {score:.0f}/100 ـە"
        solution = "Setup ـێکی بەهێزتر چاوەڕێ بکە تا Score بگاتە 80+."
    elif not checks.get("confidence", False):
        blocker = f"Confidence تەنها {confidence:.0f}% ـە"
        solution = "چاوەڕێی confirmation ـی ڕوونتر و agreement ـی بەهێزتر بکە تا Confidence بگاتە 80%+."
    elif not checks.get("rr", False):
        blocker = f"RR کەمترە لە 1:2{f' ({rr:.2f})' if rr is not None else ''}"
        solution = "Entry/SL/TP ـێکی باشتر چاوەڕێ بکە تا RR بگاتە کەمەک 1:2."
    elif not checks.get("direction", False):
        blocker = "Entry/SL/TP لە ئاراستەی دروست نییە"
        solution = "BUY: SL < Entry < TP1، SELL: TP1 < Entry < SL؛ نرخەکان پێداچوونەوەیان بۆ بکە."
    elif not checks.get("entry", False) or not checks.get("sl", False) or not checks.get("tp1", False):
        blocker = "Entry/SL/TP تەواو نییە"
        solution = "چاوەڕێی setup ـێکی تەواو بکە کە Entry و SL و TP1 ـی ڕوونی هەبێت."
    elif rejection:
        blocker = "Strong rejection هەیە"
        solution = "چاوەڕێ بکە rejection لاواز ببێت و confirmation ـی پاک دروست بێت."
    elif not checks.get("side_consistent", False):
        blocker = "Confirmation و signal side یەک نین"
        solution = "تەنها کاتێک signal بدە کە Confirmation ـەکە هەمان ئاراستەی BUY/SELL ـەکە بێت."
    else:
        blocker = "هەموو مەرجەکان هێشتا کۆنترۆڵ نەکراون"
        solution = "چاوەڕێی تەواوبوونی هەموو Strong Signal filters بکە."

    reason = f"هۆکاری WAIT: {blocker}."
    if ai_reason and clean_text(ai_reason, "") not in {"", "N/A"}:
        reason += f" AI: {clean_text(ai_reason, '')}"
    return reason, solution


# ============================================================
# GEMINI RETRY / IMAGE ANALYSIS
# ============================================================

def is_retryable_ai_error(exc: Exception) -> bool:
    text = str(exc).upper()
    return any(
        marker in text
        for marker in (
            "503",
            "UNAVAILABLE",
            "429",
            "RESOURCE_EXHAUSTED",
            "500",
            "INTERNAL",
            "DEADLINE",
            "TIMEOUT",
        )
    )


def read_image_part(path: str) -> types.Part:
    file_path = Path(path)

    with file_path.open("rb") as file:
        data = file.read()

    mime_type, _ = mimetypes.guess_type(file_path.name)

    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"

    return types.Part.from_bytes(
        data=data,
        mime_type=mime_type,
    )


def call_gemini_model(
    model_name: str,
    zone_path: str,
    confirmation_path: str,
) -> str:
    if gemini is None:
        raise RuntimeError("Gemini client is not initialized.")

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=USER_ANALYSIS_PROMPT),
                read_image_part(zone_path),
                read_image_part(confirmation_path),
            ],
        )
    ]

    response = gemini.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )

    text = getattr(response, "text", "") or ""

    if not text.strip():
        raise RuntimeError("Gemini returned an empty response.")

    return text


def analyze_two_charts(
    zone_path: str,
    confirmation_path: str,
) -> Dict[str, Any]:
    if gemini is None:
        return {
            "error": "Gemini client is not initialized."
        }

    if not Path(zone_path).exists():
        return {"error": "HTF image file is missing."}

    if not Path(confirmation_path).exists():
        return {"error": "LTF image file is missing."}

    models = []
    for model in (GEMINI_MODEL, GEMINI_FALLBACK_MODEL):
        if model and model not in models:
            models.append(model)

    last_error = "Unknown Gemini error."

    for model_name in models:
        for attempt in range(1, GEMINI_RETRIES + 1):
            try:
                logger.info(
                    "Gemini analysis: model=%s attempt=%s/%s",
                    model_name,
                    attempt,
                    GEMINI_RETRIES,
                )

                raw_text = call_gemini_model(
                    model_name,
                    zone_path,
                    confirmation_path,
                )

                data = parse_json_response(raw_text)

                if not data:
                    raise RuntimeError(
                        "Gemini returned invalid JSON."
                    )

                result = strong_signal_engine(data)

                logger.info(
                    "Analysis completed: model=%s signal=%s score=%s confidence=%s",
                    model_name,
                    result.get("trade", {}).get("signal"),
                    result.get("trade", {}).get("score"),
                    result.get("trade", {}).get("confidence"),
                )

                return result

            except Exception as exc:
                last_error = str(exc)

                logger.error(
                    "Gemini error model=%s attempt=%s: %s",
                    model_name,
                    attempt,
                    exc,
                )

                if not is_retryable_ai_error(exc):
                    break

                if attempt < GEMINI_RETRIES:
                    delay = min(20, 2 ** (attempt - 1))
                    time.sleep(delay)

        logger.warning(
            "Switching Gemini model after failures: %s",
            model_name,
        )

    return {
        "error": (
            "Gemini is temporarily unavailable after retries. "
            f"Last error: {last_error}"
        )
    }


# ============================================================
# FORMATTERS
# ============================================================

def format_structure(data: Dict[str, Any]) -> str:
    structures = data.get("structures", {})
    if not isinstance(structures, dict):
        structures = {}

    vs = normalize_structure(structures.get("vs", {}))
    vr = normalize_structure(structures.get("vr", {}))

    engine = data.get("engine", {})
    if not isinstance(engine, dict):
        engine = {}

    vs_valid = safe_bool(engine.get("vs_valid"))
    vr_valid = safe_bool(engine.get("vr_valid"))

    lines = [
        "🧱 STRUCTURE",
        "━━━━━━━━━━━━━━",
    ]

    if vs_valid:
        lines.extend([
            "🟢 VS: VALID",
            f"Support: {format_price(vs['original_level'])}",
            f"NEW Resistance: {format_price(vs['validation_level'])}",
            f"Break: {format_price(vs['break_price'])}",
        ])
    else:
        lines.append("⚪ VS: NOT VALID")

    if vr_valid:
        lines.extend([
            "🔴 VR: VALID",
            f"Resistance: {format_price(vr['original_level'])}",
            f"NEW Support: {format_price(vr['validation_level'])}",
            f"Break: {format_price(vr['break_price'])}",
        ])
    else:
        lines.append("⚪ VR: NOT VALID")

    return "\n".join(lines)


def format_signal(data: Dict[str, Any]) -> str:
    trade = data.get("trade", {})
    if not isinstance(trade, dict):
        trade = {}

    signal = clean_text(trade.get("signal"), "WAIT").upper()
    score = safe_float(trade.get("score")) or 0.0
    confidence = safe_float(trade.get("confidence")) or 0.0

    entry = safe_float(trade.get("entry"))
    sl = safe_float(trade.get("sl"))
    tp1 = safe_float(trade.get("tp1"))
    tp2 = safe_float(trade.get("tp2"))
    rr = safe_float(trade.get("rr"))

    market = data.get("market", {})
    if not isinstance(market, dict):
        market = {}

    trend = clean_text(market.get("trend"), "N/A")
    structure = clean_text(market.get("structure"), "N/A")

    zones = data.get("zones", {})
    if not isinstance(zones, dict):
        zones = {}

    engine = data.get("engine", {})
    if not isinstance(engine, dict):
        engine = {}

    vs_valid = safe_bool(engine.get("vs_valid"))
    vr_valid = safe_bool(engine.get("vr_valid"))

    zone_name = "N/A"
    zone_high = None
    zone_low = None

    if signal == "BUY" or (signal == "WAIT" and vs_valid):
        zone_name = "VS"
        zone = zones.get("vs_zone", {})
        if isinstance(zone, dict):
            zone_high = safe_float(zone.get("high"))
            zone_low = safe_float(zone.get("low"))

    elif signal == "SELL" or (signal == "WAIT" and vr_valid):
        zone_name = "VR"
        zone = zones.get("vr_zone", {})
        if isinstance(zone, dict):
            zone_high = safe_float(zone.get("high"))
            zone_low = safe_float(zone.get("low"))

    confirmation = data.get("confirmation", {})
    if not isinstance(confirmation, dict):
        confirmation = {}

    confirmation_name = clean_text(
        confirmation.get("name"),
        "N/A",
    )

    pullback = data.get("pullback", {})
    if not isinstance(pullback, dict):
        pullback = {}

    pullback_occurred = safe_bool(pullback.get("occurred"))

    if signal == "WAIT":
        lines = [
            "🟡 WAIT",
            "━━━━━━━━━━━━━━",
            "",
            "🥇 XAUUSD",
            "",
            "📊 Score:",
            f"{score:.0f}/100",
            "",
            "💪 Confidence:",
            f"{confidence:.0f}%",
            "",
            "📈 Trend:",
            trend,
            "",
            "🧠 Setup:",
            structure,
            "",
            "🟦 Zone:",
            zone_name,
            "",
            "📍 Zone Price:",
        ]

        if zone_high is not None and zone_low is not None:
            lines.append(
                f"{format_price(zone_low)} - {format_price(zone_high)}"
            )
        else:
            lines.append("N/A")

        lines.extend([
            "",
            format_structure(data),
            "",
            "🔎 Confirmation:",
            confirmation_name,
            "",
            "🔁 Pullback:",
            "YES" if pullback_occurred else "NO",
            "",
            "⏳ WAIT FOR:",
            clean_text(data.get("wait_for"), "Valid setup"),
            "",
            "❓ WHY WAIT:",
            clean_text(
                data.get("decision_reason") or engine.get("decision_reason"),
                "No complete setup yet.",
            ),
            "",
            "🛠 WHAT TO DO:",
            clean_text(
                data.get("solution") or engine.get("solution"),
                "Wait for the missing confirmation.",
            ),
        ])

        return "\n".join(lines)

    emoji = "🟢" if signal == "BUY" else "🔴"

    return "\n".join([
        f"{emoji} {signal}",
        "━━━━━━━━━━━━━━",
        "",
        "🥇 XAUUSD",
        "",
        "📊 Score:",
        f"{score:.0f}/100",
        "",
        "💪 Confidence:",
        f"{confidence:.0f}%",
        "",
        "📈 Trend:",
        trend,
        "",
        "🧠 Setup:",
        structure,
        "",
        f"🟦 Zone ({zone_name}):",
        f"{format_price(zone_low)} - {format_price(zone_high)}",
        "",
        "🎯 Entry:",
        format_price(entry),
        "",
        "🛑 SL:",
        format_price(sl),
        "",
        "💰 TP1:",
        format_price(tp1),
        "",
        "💰 TP2:",
        format_price(tp2),
        "",
        "⚖️ RR:",
        f"1:{rr:.2f}" if rr is not None else "N/A",
        "",
        "🔎 Confirmation:",
        confirmation_name,
        "",
        "🔁 Pullback:",
        "YES",
        "",
        "❓ WHY SIGNAL:",
        clean_text(
            data.get("decision_reason") or engine.get("decision_reason"),
            "All mandatory filters passed.",
        ),
        "",
        "🛠 WHAT TO DO:",
        clean_text(
            data.get("solution") or engine.get("solution"),
            "Follow the Entry / SL / TP plan.",
        ),
        "",
        "🔥 STRONG SIGNAL",
    ])


# ============================================================
# FILE / IMAGE HANDLING
# ============================================================

def cleanup_old_images() -> None:
    try:
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()

        for file_path in IMAGE_DIR.iterdir():
            if not file_path.is_file():
                continue

            try:
                if now - file_path.stat().st_mtime > MAX_IMAGE_AGE_SECONDS:
                    file_path.unlink(missing_ok=True)
            except OSError:
                pass

    except OSError:
        logger.exception("Image cleanup failed.")


def download_telegram_photo(
    file_id: str,
    destination: Path,
) -> bool:
    try:
        file_response = telegram_request(
            "getFile",
            {"file_id": file_id},
        )

        if not file_response:
            return False

        file_path = (
            file_response
            .get("result", {})
            .get("file_path")
        )

        if not file_path:
            return False

        url = (
            "https://api.telegram.org/file/"
            f"bot{TELEGRAM_BOT_TOKEN}/"
            f"{file_path}"
        )

        response = requests.get(
            url,
            timeout=TELEGRAM_DOWNLOAD_TIMEOUT,
        )

        if response.status_code != 200:
            logger.error(
                "Photo download failed: HTTP %s",
                response.status_code,
            )
            return False

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination.write_bytes(response.content)

        return True

    except Exception:
        logger.exception("Photo download error.")
        return False


# ============================================================
# SESSION
# ============================================================

def get_session(user_id: Any) -> Dict[str, Any]:
    uid = str(user_id)

    if uid not in USER_SESSIONS:
        USER_SESSIONS[uid] = {
            "zone_image": None,
            "confirmation_image": None,
            "created_at": time.time(),
        }

    return USER_SESSIONS[uid]


def reset_session(user_id: Any) -> None:
    USER_SESSIONS[str(user_id)] = {
        "zone_image": None,
        "confirmation_image": None,
        "created_at": time.time(),
    }


# ============================================================
# PHOTO HANDLER
# ============================================================

def handle_photo(message: Dict[str, Any]) -> None:
    chat = message.get("chat", {})
    user = message.get("from", {})

    chat_id = chat.get("id")
    user_id = user.get("id")

    if chat_id is None or user_id is None:
        return

    if not is_allowed(user_id):
        request_access(
            user_id,
            user.get("username", ""),
            user.get("first_name", ""),
        )

        send_message(
            chat_id,
            "🔒 ئەم بۆتە تایبەتە.\n"
            "داواکاری دەستگەیشتنت بۆ Admin نێردرا.",
        )
        return

    photos = message.get("photo", [])
    if not photos:
        return

    largest = photos[-1]
    file_id = largest.get("file_id")

    if not file_id:
        return

    session = get_session(user_id)

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    filename = IMAGE_DIR / (
        f"{user_id}_{int(time.time() * 1000)}.jpg"
    )

    if not download_telegram_photo(file_id, filename):
        send_message(
            chat_id,
            "❌ وێنەکە نەتوانرا دابەزێنرێت.",
        )
        return

    if session["zone_image"] is None:
        session["zone_image"] = str(filename)

        send_message(
            chat_id,
            "🟢 وێنەی H1/H4 وەرگیرا.\n\n"
            "ئێستا وێنەی M1/M5 بنێرە بۆ Confirmation.",
        )
        return

    session["confirmation_image"] = str(filename)

    send_message(
        chat_id,
        "⏳ هەردوو وێنەکە وەرگیراون.\n"
        "AI + V5 Engine شیکاری دەکەن...",
    )

    result = analyze_two_charts(
        session["zone_image"],
        session["confirmation_image"],
    )

    if result.get("error"):
        send_message(
            chat_id,
            "❌ هەڵە لە شیکاری:\n"
            + str(result["error"]),
        )
        reset_session(user_id)
        return

    send_message(
        chat_id,
        format_signal(result),
    )

    reset_session(user_id)


# ============================================================
# TEXT HANDLER
# ============================================================

def handle_text(message: Dict[str, Any]) -> None:
    chat = message.get("chat", {})
    user = message.get("from", {})

    chat_id = chat.get("id")
    user_id = user.get("id")

    text = clean_text(message.get("text"), "")

    if not text:
        return

    if text.startswith("/"):
        if handle_admin_command(chat_id, user_id, text):
            return

    if not is_allowed(user_id):
        request_access(
            user_id,
            user.get("username", ""),
            user.get("first_name", ""),
        )

        send_message(
            chat_id,
            "🔒 دەستگەیشتن بۆ ئەم بۆتە نییە.\n"
            "داواکارییەکەت بۆ Admin نێردرا.",
        )
        return

    command = text.lower().strip()

    if command in {"/start", "start"}:
        reset_session(user_id)

        send_message(
            chat_id,
            "🥇 Gold Chart Analyzer PRO V5\n\n"
            "1️⃣ H1/H4 chart بنێرە بۆ VS/VR + Zone.\n"
            "2️⃣ پاشان M1/M5 chart بنێرە بۆ Pullback + Confirmation.\n\n"
            "BUY: RBS / SRR / I.VR / PO2\n"
            "SELL: SBR / RSS / I.VS / PO2\n\n"
            "⚠️ BUY/SELL تەنها کاتێک دەردەچێت "
            "کە هەموو مەرجەکانی Strong Signal پڕ بن.",
        )
        return

    if command in {"/reset", "reset"}:
        reset_session(user_id)
        send_message(chat_id, "♻️ Session نوێ کرایەوە.")
        return

    send_message(
        chat_id,
        "📸 تکایە سەرەتا H1/H4 chart بنێرە.",
    )


# ============================================================
# UPDATE HANDLER
# ============================================================

def handle_update(update: Dict[str, Any]) -> None:
    if not isinstance(update, dict):
        return

    message = update.get("message")

    if isinstance(message, dict):
        if message.get("photo"):
            handle_photo(message)
            return

        if message.get("text"):
            handle_text(message)
            return

    callback = update.get("callback_query")

    if isinstance(callback, dict):
        callback_id = callback.get("id")
        if callback_id:
            answer_callback(callback_id)


# ============================================================
# POLLING
# ============================================================

def delete_webhook() -> bool:
    result = telegram_request(
        "deleteWebhook",
        {
            "drop_pending_updates": False,
        },
    )
    return bool(result and result.get("ok"))


def get_updates(
    offset: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    payload: Dict[str, Any] = {
        "timeout": POLL_TIMEOUT,
        "allowed_updates": [
            "message",
            "callback_query",
        ],
    }

    if offset is not None:
        payload["offset"] = offset

    return telegram_request(
        "getUpdates",
        payload,
        timeout=POLL_TIMEOUT + 15,
    )


def run_bot() -> None:
    logger.info("Starting Gold Chart Analyzer PRO V5.0...")

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing.")
        return

    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is missing.")
        return

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_old_images()

    delete_webhook()

    offset: Optional[int] = None
    last_cleanup = time.time()

    while True:
        try:
            response = get_updates(offset)

            if not response:
                time.sleep(3)
                continue

            if not response.get("ok"):
                logger.error(
                    "Telegram getUpdates failed: %s",
                    response,
                )
                time.sleep(5)
                continue

            updates = response.get("result", [])

            for update in updates:
                update_id = update.get("update_id")

                if update_id is not None:
                    offset = update_id + 1

                try:
                    handle_update(update)
                except Exception:
                    logger.exception("Update handling error.")

            if time.time() - last_cleanup > 3600:
                cleanup_old_images()
                last_cleanup = time.time()

        except KeyboardInterrupt:
            logger.info("Bot stopped manually.")
            break

        except Exception as exc:
            error_text = str(exc)

            # Telegram returns 409 when another polling instance owns
            # the same bot token. Never crash-loop immediately.
            if "409" in error_text or "CONFLICT" in error_text.upper():
                logger.error(
                    "Telegram 409 Conflict: another bot instance "
                    "is running. Waiting 30 seconds."
                )
                time.sleep(30)
                continue

            logger.exception("Polling loop error.")
            time.sleep(10)


# ============================================================
# ENTRY POINT
# ============================================================

def main() -> None:
    run_bot()


if __name__ == "__main__":
    main()
