"""
Gold Chart Analyzer PRO — V4.1
XAUUSD SNRZ Visual Analyzer
24/7 Telegram Bot

Flow:
1. H1/H4 -> HTF structure + VS/VR + Zone
2. M1/M5 -> Pullback + confirmation
3. Deterministic engine validates the AI result
4. Strong BUY/SELL only when every mandatory filter passes
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

import requests
from google import genai
from google.genai import types


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Keep the model configurable through GitHub Actions secrets/env.
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash",
).strip()

ADMIN_ID = 5874840448

MIN_STRONG_SCORE = 80.0
MIN_STRONG_CONFIDENCE = 80.0
MIN_RR = 2.0
# Gemini reliability
GEMINI_MAX_RETRIES = 4
GEMINI_RETRY_BASE_DELAY = 3
```


ALLOWED_USERS_FILE = "allowed_users.json"
IMAGE_DIR = "chart_images"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("GoldChartAnalyzer")


# ============================================================
# GEMINI CLIENT
# ============================================================

gemini = None

if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY is missing.")
else:
    try:
        gemini = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini client initialized.")
    except Exception as exc:
        logger.exception(
            "Gemini client initialization failed: %s",
            exc,
        )


# ============================================================
# TELEGRAM CONFIG
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


def clean_text(
    value: Any,
    default: str = "N/A",
) -> str:
    if value is None:
        return default

    text = str(value).strip()

    return text if text else default


def format_price(value: Any) -> str:
    number = safe_float(value)

    if number is None:
        return "N/A"

    return f"{number:.2f}"


# ============================================================
# TELEGRAM API
# ============================================================

def telegram_request(
    method: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 40,
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
                "Telegram API %s: %s",
                response.status_code,
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
        logger.error(
            "Telegram request error: %s",
            exc,
        )
        return None

    except ValueError as exc:
        logger.error(
            "Telegram JSON decode error: %s",
            exc,
        )
        return None


def send_message(
    chat_id: Any,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
) -> None:
    if not text:
        return

    chunks = [
        text[i:i + TELEGRAM_MESSAGE_LIMIT]
        for i in range(
            0,
            len(text),
            TELEGRAM_MESSAGE_LIMIT,
        )
    ]

    for chunk in chunks:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": chunk,
        }

        if reply_markup:
            payload["reply_markup"] = reply_markup

        telegram_request(
            "sendMessage",
            payload,
        )


def answer_callback(
    callback_id: str,
    text: str = "",
) -> None:
    telegram_request(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text,
        },
    )


# ============================================================
# ACCESS SYSTEM
# ============================================================

USER_SESSIONS: Dict[str, Dict[str, Any]] = {}
PENDING_USERS: Dict[str, Dict[str, Any]] = {}


def load_allowed_users() -> Dict[str, Any]:
    if not os.path.exists(ALLOWED_USERS_FILE):
        return {}

    try:
        with open(
            ALLOWED_USERS_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception as exc:
        logger.error(
            "Could not load allowed users: %s",
            exc,
        )
        return {}


def save_allowed_users(
    users: Dict[str, Any],
) -> None:
    try:
        with open(
            ALLOWED_USERS_FILE,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                users,
                file,
                ensure_ascii=False,
                indent=2,
            )

    except Exception as exc:
        logger.error(
            "Could not save allowed users: %s",
            exc,
        )


ALLOWED_USERS = load_allowed_users()

if str(ADMIN_ID) not in ALLOWED_USERS:
    ALLOWED_USERS[str(ADMIN_ID)] = {
        "name": "ADMIN",
        "approved": True,
    }
    save_allowed_users(ALLOWED_USERS)


def is_allowed(user_id: Any) -> bool:
    return (
        str(user_id) == str(ADMIN_ID)
        or str(user_id) in ALLOWED_USERS
    )


def request_access(
    user_id: Any,
    username: str = "",
    first_name: str = "",
) -> bool:
    uid = str(user_id)

    if is_allowed(user_id):
        return True

    PENDING_USERS[uid] = {
        "username": username or "",
        "first_name": first_name or "",
        "requested_at": int(time.time()),
    }

    return False


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
    if str(user_id) != str(ADMIN_ID):
        return False

    parts = text.strip().split(
        maxsplit=1,
    )

    if not parts:
        return True

    command = parts[0].lower()

    if command == "/admin":
        send_message(
            chat_id,
            admin_help(),
        )
        return True

    if command == "/adduser":
        if len(parts) < 2:
            send_message(
                chat_id,
                "❌ User ID بنووسە.",
            )
            return True

        target = parts[1].strip()

        if not target:
            send_message(
                chat_id,
                "❌ User ID دروست نییە.",
            )
            return True

        ALLOWED_USERS[target] = {
            "name": target,
            "approved": True,
        }

        save_allowed_users(ALLOWED_USERS)

        PENDING_USERS.pop(
            target,
            None,
        )

        send_message(
            chat_id,
            f"✅ User {target} زیادکرا.",
        )

        return True

    if command == "/removeuser":
        if len(parts) < 2:
            send_message(
                chat_id,
                "❌ User ID بنووسە.",
            )
            return True

        target = parts[1].strip()

        if target == str(ADMIN_ID):
            send_message(
                chat_id,
                "❌ ناتوانیت Admin بسڕیتەوە.",
            )
            return True

        ALLOWED_USERS.pop(
            target,
            None,
        )

        save_allowed_users(ALLOWED_USERS)

        send_message(
            chat_id,
            f"🗑 User {target} لابرا.",
        )

        return True

    if command == "/users":
        if not ALLOWED_USERS:
            send_message(
                chat_id,
                "هیچ User ـێک نییە.",
            )
            return True

        lines = ["👥 ALLOWED USERS", ""]

        for uid, info in ALLOWED_USERS.items():
            name = clean_text(
                info.get("name"),
                "",
            )
            lines.append(
                f"• {uid} — {name}"
            )

        send_message(
            chat_id,
            "\n".join(lines),
        )

        return True

    if command == "/pending":
        if not PENDING_USERS:
            send_message(
                chat_id,
                "📭 هیچ داواکارییەکی چاوەڕوان نییە.",
            )
            return True

        lines = [
            "📥 PENDING USERS",
            "",
        ]

        for uid, info in PENDING_USERS.items():
            first_name = clean_text(
                info.get("first_name"),
                "",
            )
            username = clean_text(
                info.get("username"),
                "",
            )

            if username:
                username = f"@{username}"

            lines.append(
                f"• {uid} — {first_name} {username}"
            )

        send_message(
            chat_id,
            "\n".join(lines),
        )

        return True

    if command == "/broadcast":
        if len(parts) < 2:
            send_message(
                chat_id,
                "❌ دەقەکە بنووسە.",
            )
            return True

        broadcast_text = parts[1]
        sent = 0

        for uid in list(ALLOWED_USERS.keys()):
            result = telegram_request(
                "sendMessage",
                {
                    "chat_id": uid,
                    "text": broadcast_text,
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
# AI PROMPTS
# ============================================================

SYSTEM_PROMPT = r"""
You are the visual market analyst for an XAUUSD SNRZ Telegram bot.

LANGUAGE
--------
- Explanations must be Sorani Kurdish.
- Technical SNRZ names remain English.

VISUAL DISCIPLINE
-----------------
- Inspect ONLY visible candles.
- Read candles from left to right.
- Never invent candles.
- Never assume a historical breakout.
- Current price is NOT proof of a historical breakout.
- A wick/touch/rejection is NOT automatically a breakout.
- If evidence is unclear, report it as unclear.
- Numerical levels must come from visible chart evidence.

==================================================
VS
==================================================

Original Support
-> UP move
-> NEW Resistance formed AFTER Support
-> UP move again
-> SAME NEW Resistance broken
-> candle/body acceptance above that Resistance
-> Original Support becomes VS

Important:
- Resistance formed before Original Support is irrelevant.
- Normal Support is not automatically VS.
- The SAME NEW Resistance must be broken.
- Current price alone cannot prove the historical break.

==================================================
VR
==================================================

Original Resistance
-> DOWN move
-> NEW Support formed AFTER Resistance
-> DOWN move again
-> SAME NEW Support broken
-> candle/body acceptance below that Support
-> Original Resistance becomes VR

Important:
- Support formed before Original Resistance is irrelevant.
- Normal Resistance is not automatically VR.
- The SAME NEW Support must be broken.
- Current price alone cannot prove the historical break.

==================================================
ZONE
==================================================

After a valid VS/VR:

1. Identify the formation candle.
2. Look at the immediately previous candle.
3. Compare BODY SIZE only.
4. Select the SHORTER body.
5. Entire selected candle HIGH -> LOW = Zone.

NO engulfing zone rule.

==================================================
ENTRY
==================================================

VALID VS/VR
-> ZONE
-> PRICE PULLBACK / RETEST
-> M1/M5 CONFIRMATION
-> STRONG SIGNAL FILTERS
-> ENTRY

Confirmation before pullback is INVALID.

BUY:
- RBS
- SRR
- I.VR
- complete PO2

SELL:
- SBR
- RSS
- I.VS
- complete PO2

==================================================
STRONG SIGNAL
==================================================

Strong BUY/SELL requires ALL:

- Score >= 80
- Confidence >= 80%
- RR >= 1:2
- Valid VS/VR
- Valid Zone
- Actual Zone retest
- Confirmation after pullback
- HTF/LTF agreement
- Logical Entry
- Logical SL
- Logical TP1
- No strong rejection
- No contradiction

If ANY mandatory condition is missing:
WAIT.

Return JSON only.
"""


USER_ANALYSIS_PROMPT = r"""
Analyze both supplied XAUUSD chart images.

IMAGE 1:
HTF chart, normally H1/H4.

Use it for:
- Support
- Resistance
- VS
- VR
- Zone
- HTF trend

IMAGE 2:
LTF chart, normally M1/M5.

Use it for:
- Pullback/retest
- RBS
- SRR
- SBR
- RSS
- I.VS
- I.VR
- PO2
- confirmation

Do NOT invent anything.

For VS/VR, report the visible numerical levels involved in the sequence.

IMPORTANT:
If an exact historical break PRICE cannot be read confidently,
set break_price to null but set break_confirmed=true ONLY if
the historical breakout is visibly confirmed by candles.

Return ONLY JSON using this structure:

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
# JSON PARSING
# ============================================================

def clean_json_text(text: str) -> str:
    if not text:
        return ""

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(
            r"^```(?:json)?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned,
        )

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

    except json.JSONDecodeError as exc:
        logger.error(
            "JSON parse error: %s | response=%s",
            exc,
            cleaned[:1500],
        )
        return {}


# ============================================================
# STRUCTURE NORMALIZATION
# ============================================================

def normalize_structure(
    structure: Any,
) -> Dict[str, Any]:
    if not isinstance(structure, dict):
        structure = {}

    evidence = structure.get(
        "evidence",
        {},
    )

    if not isinstance(evidence, dict):
        evidence = {}

    return {
        "candidate": safe_bool(
            structure.get("candidate")
        ),

        "original_level": safe_float(
            structure.get("original_level")
        ),

        "validation_level": safe_float(
            structure.get("validation_level")
        ),

        "break_price": safe_float(
            structure.get("break_price")
        ),

        "formation_candle": clean_text(
            structure.get("formation_candle"),
            "",
        ),

        "break_candle": clean_text(
            structure.get("break_candle"),
            "",
        ),

        "evidence": {
            key: safe_bool(
                evidence.get(key)
            )
            for key in (
                "original_level_visible",
                "first_move_confirmed",
                "new_level_formed_after_original",
                "second_move_confirmed",
                "same_level_broken",
                "break_confirmed",
            )
        },

        "notes": clean_text(
            structure.get("notes"),
            "",
        ),
    }


def structure_evidence_score(
    structure: Dict[str, Any],
) -> int:
    evidence = structure.get(
        "evidence",
        {},
    )

    keys = (
        "original_level_visible",
        "first_move_confirmed",
        "new_level_formed_after_original",
        "second_move_confirmed",
        "same_level_broken",
        "break_confirmed",
    )

    return sum(
        1
        for key in keys
        if safe_bool(evidence.get(key))
    )


# ============================================================
# V4.1 VS VALIDATOR
# ============================================================

def verify_vs_v41(
    structure: Any,
) -> Tuple[bool, str]:
    """
    Validate VS.

    Required:
    - Original Support
    - NEW Resistance above Support
    - historical breakout confirmation

    Exact break_price is preferred but NOT mandatory if
    the visual model explicitly confirms the historical break.
    """

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
        return False, (
            "VS: NEW Resistance must be above Support."
        )

    if not safe_bool(
        ev.get("original_level_visible")
    ):
        return False, "VS: Support visibility not confirmed."

    if not safe_bool(
        ev.get("new_level_formed_after_original")
    ):
        return False, (
            "VS: NEW Resistance after Support not confirmed."
        )

    if not safe_bool(
        ev.get("first_move_confirmed")
    ):
        return False, "VS: first UP move not confirmed."

    if not safe_bool(
        ev.get("second_move_confirmed")
    ):
        return False, "VS: second UP move not confirmed."

    # Historical break must be explicitly confirmed.
    if not safe_bool(
        ev.get("same_level_broken")
    ):
        return False, (
            "VS: SAME NEW Resistance break not confirmed."
        )

    if not safe_bool(
        ev.get("break_confirmed")
    ):
        return False, (
            "VS: breakout candle/body confirmation missing."
        )

    # If break price exists, enforce chronology.
    if break_price is not None:
        if break_price <= validation:
            return False, (
                "VS: break price is not above NEW Resistance."
            )

    return True, "VS validated."


# ============================================================
# V4.1 VR VALIDATOR
# ============================================================

def verify_vr_v41(
    structure: Any,
) -> Tuple[bool, str]:
    """
    Validate VR.

    Required:
    - Original Resistance
    - NEW Support below Resistance
    - historical breakout confirmation

    Exact break_price is preferred but NOT mandatory if
    the visual model explicitly confirms the historical break.
    """

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
        return False, (
            "VR: NEW Support must be below Resistance."
        )

    if not safe_bool(
        ev.get("original_level_visible")
    ):
        return False, "VR: Resistance visibility not confirmed."

    if not safe_bool(
        ev.get("new_level_formed_after_original")
    ):
        return False, (
            "VR: NEW Support after Resistance not confirmed."
        )

    if not safe_bool(
        ev.get("first_move_confirmed")
    ):
        return False, "VR: first DOWN move not confirmed."

    if not safe_bool(
        ev.get("second_move_confirmed")
    ):
        return False, "VR: second DOWN move not confirmed."

    if not safe_bool(
        ev.get("same_level_broken")
    ):
        return False, (
            "VR: SAME NEW Support break not confirmed."
        )

    if not safe_bool(
        ev.get("break_confirmed")
    ):
        return False, (
            "VR: breakout candle/body confirmation missing."
        )

    if break_price is not None:
        if break_price >= validation:
            return False, (
                "VR: break price is not below NEW Support."
            )

    return True, "VR validated."


def get_valid_structures(
    data: Dict[str, Any],
) -> Dict[str, Any]:
    structures = data.get(
        "structures",
        {},
    )

    if not isinstance(structures, dict):
        structures = {}

    vs = normalize_structure(
        structures.get("vs", {})
    )

    vr = normalize_structure(
        structures.get("vr", {})
    )

    vs_valid, vs_reason = verify_vs_v41(vs)
    vr_valid, vr_reason = verify_vr_v41(vr)

    return {
        "vs": vs,
        "vr": vr,
        "vs_valid": vs_valid,
        "vr_valid": vr_valid,
        "vs_reason": vs_reason,
        "vr_reason": vr_reason,
    }


# ============================================================
# ZONE VALIDATION
# ============================================================

def zone_is_valid(
    data: Dict[str, Any],
    side: str,
) -> Tuple[bool, Optional[float], Optional[float]]:
    zones = data.get(
        "zones",
        {},
    )

    if not isinstance(zones, dict):
        return False, None, None

    zone_key = (
        "vs_zone"
        if side == "BUY"
        else "vr_zone"
    )

    zone = zones.get(
        zone_key,
        {},
    )

    if not isinstance(zone, dict):
        return False, None, None

    valid = safe_bool(
        zone.get("valid")
    )

    high = safe_float(
        zone.get("high")
    )

    low = safe_float(
        zone.get("low")
    )

    body = safe_float(
        zone.get("body_size")
    )

    previous_body = safe_float(
        zone.get(
            "previous_candle_body_size"
        )
    )

    if not valid:
        return False, high, low

    if high is None or low is None:
        return False, high, low

    if high <= low:
        return False, high, low

    if body is None or previous_body is None:
        return False, high, low

    # The selected candle must be the shorter-body candle.
    if body >= previous_body:
        return False, high, low

    return True, high, low


# ============================================================
# PULLBACK
# ============================================================

def pullback_is_valid(
    data: Dict[str, Any],
) -> bool:
    pullback = data.get(
        "pullback",
        {},
    )

    if not isinstance(pullback, dict):
        return False

    occurred = safe_bool(
        pullback.get("occurred")
    )

    retested = safe_bool(
        pullback.get("zone_retested")
    )

    retest_price = safe_float(
        pullback.get("retest_price")
    )

    return (
        occurred
        and retested
        and retest_price is not None
    )


# ============================================================
# CONFIRMATION
# ============================================================

BUY_CONFIRMATIONS = {
    "RBS",
    "SRR",
    "I.VR",
    "PO2",
}

SELL_CONFIRMATIONS = {
    "SBR",
    "RSS",
    "I.VS",
    "PO2",
}


def normalize_confirmation_name(
    name: Any,
) -> str:
    if not name:
        return ""

    value = str(name).strip().upper()

    value = value.replace(" ", "")
    value = value.replace("-", "")

    return value


def confirmation_is_valid(
    data: Dict[str, Any],
) -> Tuple[bool, str, str]:
    confirmation = data.get(
        "confirmation",
        {},
    )

    if not isinstance(confirmation, dict):
        return False, "", ""

    found = safe_bool(
        confirmation.get("found")
    )

    complete = safe_bool(
        confirmation.get("complete")
    )

    after_pullback = safe_bool(
        confirmation.get("after_pullback")
    )

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
        valid = name in BUY_CONFIRMATIONS

    elif side == "SELL":
        valid = name in SELL_CONFIRMATIONS

    else:
        valid = False

    return valid, name, side


# ============================================================
# RR
# ============================================================

def calculate_rr(
    entry: Any,
    sl: Any,
    tp1: Any,
) -> Optional[float]:
    entry_value = safe_float(entry)
    sl_value = safe_float(sl)
    tp_value = safe_float(tp1)

    if (
        entry_value is None
        or sl_value is None
        or tp_value is None
    ):
        return None

    risk = abs(
        entry_value - sl_value
    )

    if risk <= 0:
        return None

    reward = abs(
        tp_value - entry_value
    )

    return reward / risk


# ============================================================
# STRONG SIGNAL ENGINE
# ============================================================

def strong_signal_engine(
    data: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(data, dict):
        data = {}

    structures = get_valid_structures(data)

    vs_valid = structures["vs_valid"]
    vr_valid = structures["vr_valid"]

    trade = data.get(
        "trade",
        {},
    )

    if not isinstance(trade, dict):
        trade = {}

    raw_signal = clean_text(
        trade.get("signal"),
        "WAIT",
    ).upper()

    if raw_signal not in {
        "BUY",
        "SELL",
        "WAIT",
    }:
        raw_signal = "WAIT"

    score = safe_float(
        trade.get("score")
    ) or 0.0

    confidence = safe_float(
        trade.get("confidence")
    ) or 0.0

    entry = safe_float(
        trade.get("entry")
    )

    sl = safe_float(
        trade.get("sl")
    )

    tp1 = safe_float(
        trade.get("tp1")
    )

    tp2 = safe_float(
        trade.get("tp2")
    )

    rejection = safe_bool(
        trade.get("rejection")
    )

    # --------------------------------------------------------
    # Structure
    # --------------------------------------------------------

    if raw_signal == "BUY":
        structure_valid = vs_valid
        structure_name = "VS"

    elif raw_signal == "SELL":
        structure_valid = vr_valid
        structure_name = "VR"

    else:
        structure_valid = (
            vs_valid or vr_valid
        )

        if vs_valid:
            structure_name = "VS"
        elif vr_valid:
            structure_name = "VR"
        else:
            structure_name = ""

    # --------------------------------------------------------
    # Zone
    # --------------------------------------------------------

    zone_valid = False
    zone_high = None
    zone_low = None

    if raw_signal in {
        "BUY",
        "SELL",
    }:
        zone_valid, zone_high, zone_low = (
            zone_is_valid(
                data,
                raw_signal,
            )
        )

    else:
        if vs_valid:
            zone_valid, zone_high, zone_low = (
                zone_is_valid(
                    data,
                    "BUY",
                )
            )

        if not zone_valid and vr_valid:
            zone_valid, zone_high, zone_low = (
                zone_is_valid(
                    data,
                    "SELL",
                )
            )

    # --------------------------------------------------------
    # Pullback
    # --------------------------------------------------------

    pullback_valid = pullback_is_valid(data)

    # --------------------------------------------------------
    # Confirmation
    # --------------------------------------------------------

    (
        confirmation_valid,
        confirmation_name,
        confirmation_side,
    ) = confirmation_is_valid(data)

    # --------------------------------------------------------
    # HTF / LTF agreement
    # --------------------------------------------------------

    agreement = safe_bool(
        data.get(
            "htf_ltf_agreement"
        )
    )

    # --------------------------------------------------------
    # RR
    # --------------------------------------------------------

    rr = calculate_rr(
        entry,
        sl,
        tp1,
    )

    # --------------------------------------------------------
    # Side consistency
    # --------------------------------------------------------

    side_consistent = True

    if raw_signal == "BUY":
        side_consistent = (
            confirmation_side == "BUY"
        )

    elif raw_signal == "SELL":
        side_consistent = (
            confirmation_side == "SELL"
        )

    # --------------------------------------------------------
    # Mandatory checks
    # --------------------------------------------------------

    checks = {
        "structure": structure_valid,
        "zone": zone_valid,
        "pullback": pullback_valid,
        "confirmation": confirmation_valid,
        "agreement": agreement,
        "score": (
            score >= MIN_STRONG_SCORE
        ),
        "confidence": (
            confidence >= MIN_STRONG_CONFIDENCE
        ),
        "rr": (
            rr is not None
            and rr >= MIN_RR
        ),
        "entry": entry is not None,
        "sl": sl is not None,
        "tp1": tp1 is not None,
        "no_rejection": not rejection,
        "side_consistent": side_consistent,
    }

    all_valid = all(
        checks.values()
    )

    # --------------------------------------------------------
    # Final signal
    # --------------------------------------------------------

    if (
        all_valid
        and raw_signal in {
            "BUY",
            "SELL",
        }
    ):
        final_signal = raw_signal
    else:
        final_signal = "WAIT"

    # --------------------------------------------------------
    # WAIT reason
    # --------------------------------------------------------

    missing = []

    if not structure_valid:
        missing.append(
            f"VALID {structure_name or 'VS/VR'}"
        )

    if not zone_valid:
        missing.append("Zone")

    if not pullback_valid:
        missing.append("Pullback/Retest")

    if not confirmation_valid:
        missing.append(
            "M1/M5 Confirmation"
        )

    if not agreement:
        missing.append(
            "HTF/LTF agreement"
        )

    if score < MIN_STRONG_SCORE:
        missing.append(
            "Score ≥ 80"
        )

    if confidence < MIN_STRONG_CONFIDENCE:
        missing.append(
            "Confidence ≥ 80%"
        )

    if rr is None or rr < MIN_RR:
        missing.append(
            "RR ≥ 1:2"
        )

    if entry is None:
        missing.append("Entry")

    if sl is None:
        missing.append("SL")

    if tp1 is None:
        missing.append("TP1")

    if rejection:
        missing.append(
            "No rejection"
        )

    if not side_consistent:
        missing.append(
            "Confirmation side"
        )

    if final_signal == "WAIT":
        if vs_valid or vr_valid:
            if zone_valid:
                if not pullback_valid:
                    wait_for = (
                        f"Price Pullback/Retest "
                        f"to {structure_name} Zone"
                    )
                elif not confirmation_valid:
                    wait_for = (
                        "M1/M5 Confirmation "
                        "after Pullback"
                    )
                else:
                    wait_for = (
                        "Complete Strong Signal filters"
                    )
            else:
                wait_for = (
                    f"{structure_name} Zone"
                )
        else:
            wait_for = (
                "Complete valid VS/VR structure "
                "with visible historical break"
            )

    else:
        wait_for = ""

    result = dict(data)

    result["engine"] = {
        "vs_valid": vs_valid,
        "vr_valid": vr_valid,

        "vs_reason": structures[
            "vs_reason"
        ],

        "vr_reason": structures[
            "vr_reason"
        ],

        "structure_evidence": {
            "vs": structure_evidence_score(
                structures["vs"]
            ),
            "vr": structure_evidence_score(
                structures["vr"]
            ),
        },

        "checks": checks,

        "missing": missing,

        "side_consistent": side_consistent,
    }

    result["trade"] = {
        "signal": final_signal,
        "score": round(
            score,
            1,
        ),
        "confidence": round(
            confidence,
            1,
        ),
        "entry": (
            entry
            if final_signal != "WAIT"
            else None
        ),
        "sl": (
            sl
            if final_signal != "WAIT"
            else None
        ),
        "tp1": (
            tp1
            if final_signal != "WAIT"
            else None
        ),
        "tp2": (
            tp2
            if final_signal != "WAIT"
            else None
        ),
        "rr": (
            round(
                rr,
                2,
            )
            if (
                rr is not None
                and final_signal != "WAIT"
            )
            else None
        ),
        "rejection": rejection,
    }

    result["wait_for"] = wait_for

    return result


# ============================================================
# GEMINI IMAGE ANALYSIS
# ============================================================

```python
def analyze_two_charts(
    zone_path: str,
    confirmation_path: str,
) -> Dict[str, Any]:
    if gemini is None:
        return {
            "error": "Gemini client is not initialized."
        }

    # --------------------------------------------------------
    # READ IMAGES
    # --------------------------------------------------------

    try:
        with open(zone_path, "rb") as file:
            zone_bytes = file.read()

        with open(confirmation_path, "rb") as file:
            confirmation_bytes = file.read()

    except OSError as exc:
        logger.error(
            "Could not read chart images: %s",
            exc,
        )

        return {
            "error": "Could not read chart images."
        }

    # --------------------------------------------------------
    # GEMINI CONTENT
    # --------------------------------------------------------

    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=USER_ANALYSIS_PROMPT,
                ),
                types.Part.from_bytes(
                    data=zone_bytes,
                    mime_type="image/jpeg",
                ),
                types.Part.from_bytes(
                    data=confirmation_bytes,
                    mime_type="image/jpeg",
                ),
            ],
        ),
    ]

    # --------------------------------------------------------
    # RETRY LOOP
    # --------------------------------------------------------

    last_error = ""

    for attempt in range(
        1,
        GEMINI_MAX_RETRIES + 1,
    ):
        try:
            logger.info(
                "Gemini analysis attempt %s/%s using model=%s",
                attempt,
                GEMINI_MAX_RETRIES,
                GEMINI_MODEL,
            )

            response = gemini.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.1,
                ),
            )

            text = getattr(
                response,
                "text",
                "",
            )

            if not text:
                last_error = (
                    "Gemini returned an empty response."
                )

                logger.warning(
                    "%s",
                    last_error,
                )

            else:
                data = parse_json_response(text)

                if data:
                    logger.info(
                        "Gemini analysis successful on attempt %s.",
                        attempt,
                    )

                    return strong_signal_engine(data)

                last_error = (
                    "Gemini returned invalid JSON."
                )

                logger.warning(
                    "%s",
                    last_error,
                )

        except Exception as exc:
            last_error = str(exc)

            error_text = str(exc).lower()

            # ------------------------------------------------
            # TEMPORARY GEMINI ERRORS
            # ------------------------------------------------

            is_temporary = any(
                keyword in error_text
                for keyword in (
                    "503",
                    "unavailable",
                    "high demand",
                    "overloaded",
                    "temporarily",
                    "deadline exceeded",
                    "429",
                    "resource exhausted",
                    "rate limit",
                )
            )

            if not is_temporary:
                logger.exception(
                    "Gemini permanent analysis error."
                )

                return {
                    "error": str(exc)
                }

            logger.warning(
                "Gemini temporary error on attempt %s/%s: %s",
                attempt,
                GEMINI_MAX_RETRIES,
                exc,
            )

        # ----------------------------------------------------
        # WAIT BEFORE RETRY
        # ----------------------------------------------------

        if attempt < GEMINI_MAX_RETRIES:
            delay = (
                GEMINI_RETRY_BASE_DELAY
                * (2 ** (attempt - 1))
            )

            logger.info(
                "Waiting %s seconds before Gemini retry...",
                delay,
            )

            time.sleep(delay)

    # --------------------------------------------------------
    # ALL RETRIES FAILED
    # --------------------------------------------------------

    logger.error(
        "Gemini failed after %s attempts. Last error: %s",
        GEMINI_MAX_RETRIES,
        last_error,
    )

    return {
        "error": (
            "Gemini کاتییەکەی بارەکەی زۆرە (503). "
            "دووبارە هەوڵ بدە."
        )
    }
```

# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(
    data: Dict[str, Any],
) -> str:
    trade = data.get(
        "trade",
        {},
    )

    if not isinstance(trade, dict):
        trade = {}

    signal = clean_text(
        trade.get("signal"),
        "WAIT",
    ).upper()

    score = safe_float(
        trade.get("score")
    ) or 0.0

    confidence = safe_float(
        trade.get("confidence")
    ) or 0.0

    entry = safe_float(
        trade.get("entry")
    )

    sl = safe_float(
        trade.get("sl")
    )

    tp1 = safe_float(
        trade.get("tp1")
    )

    tp2 = safe_float(
        trade.get("tp2")
    )

    rr = safe_float(
        trade.get("rr")
    )

    market = data.get(
        "market",
        {},
    )

    if not isinstance(market, dict):
        market = {}

    trend = clean_text(
        market.get("trend"),
        "N/A",
    )

    structure = clean_text(
        market.get("structure"),
        "N/A",
    )

    zones = data.get(
        "zones",
        {},
    )

    if not isinstance(zones, dict):
        zones = {}

    engine = data.get(
        "engine",
        {},
    )

    if not isinstance(engine, dict):
        engine = {}

    vs_valid = safe_bool(
        engine.get("vs_valid")
    )

    vr_valid = safe_bool(
        engine.get("vr_valid")
    )

    # --------------------------------------------------------
    # Active zone
    # --------------------------------------------------------

    zone_name = "N/A"
    zone_high = None
    zone_low = None

    if signal == "BUY" or (
        signal == "WAIT"
        and vs_valid
    ):
        zone_name = "VS"

        zone = zones.get(
            "vs_zone",
            {},
        )

        if isinstance(zone, dict):
            zone_high = safe_float(
                zone.get("high")
            )
            zone_low = safe_float(
                zone.get("low")
            )

    elif signal == "SELL" or (
        signal == "WAIT"
        and vr_valid
    ):
        zone_name = "VR"

        zone = zones.get(
            "vr_zone",
            {},
        )

        if isinstance(zone, dict):
            zone_high = safe_float(
                zone.get("high")
            )
            zone_low = safe_float(
                zone.get("low")
            )

    confirmation = data.get(
        "confirmation",
        {},
    )

    if not isinstance(confirmation, dict):
        confirmation = {}

    confirmation_name = clean_text(
        confirmation.get("name"),
        "N/A",
    )

    pullback = data.get(
        "pullback",
        {},
    )

    if not isinstance(pullback, dict):
        pullback = {}

    pullback_occurred = safe_bool(
        pullback.get("occurred")
    )

    # ========================================================
    # WAIT
    # ========================================================

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

        if (
            zone_high is not None
            and zone_low is not None
        ):
            lines.append(
                f"{format_price(zone_low)} - "
                f"{format_price(zone_high)}"
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
            (
                "YES"
                if pullback_occurred
                else "NO"
            ),
            "",
            "⏳ WAIT FOR:",
            clean_text(
                data.get("wait_for"),
                "Valid setup",
            ),
        ])

        return "\n".join(lines)

    # ========================================================
    # BUY / SELL
    # ========================================================

    emoji = (
        "🟢"
        if signal == "BUY"
        else "🔴"
    )

    lines = [
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
        (
            f"{format_price(zone_low)} - "
            f"{format_price(zone_high)}"
        ),
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
        (
            f"1:{rr:.2f}"
            if rr is not None
            else "N/A"
        ),
        "",
        "🔎 Confirmation:",
        confirmation_name,
        "",
        "🔁 Pullback:",
        "YES",
        "",
        "🔥 STRONG SIGNAL",
    ]

    return "\n".join(lines)


# ============================================================
# TELEGRAM PHOTO DOWNLOAD
# ============================================================

def download_telegram_photo(
    file_id: str,
    destination: str,
) -> bool:
    try:
        file_response = telegram_request(
            "getFile",
            {
                "file_id": file_id,
            },
        )

        if not file_response:
            return False

        result = file_response.get(
            "result",
            {},
        )

        file_path = result.get(
            "file_path"
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
            timeout=60,
        )

        if response.status_code != 200:
            logger.error(
                "Photo download failed: %s",
                response.status_code,
            )
            return False

        os.makedirs(
            os.path.dirname(destination) or ".",
            exist_ok=True,
        )

        with open(
            destination,
            "wb",
        ) as file:
            file.write(response.content)

        return True

    except Exception as exc:
        logger.error(
            "Photo download error: %s",
            exc,
        )
        return False


# ============================================================
# SESSION
# ============================================================

def get_session(
    user_id: Any,
) -> Dict[str, Any]:
    uid = str(user_id)

    if uid not in USER_SESSIONS:
        USER_SESSIONS[uid] = {
            "zone_image": None,
            "confirmation_image": None,
            "created_at": time.time(),
        }

    return USER_SESSIONS[uid]


def reset_session(
    user_id: Any,
) -> None:
    USER_SESSIONS[str(user_id)] = {
        "zone_image": None,
        "confirmation_image": None,
        "created_at": time.time(),
    }


# ============================================================
# PHOTO HANDLER
# ============================================================

def handle_photo(
    message: Dict[str, Any],
) -> None:
    chat = message.get(
        "chat",
        {},
    )

    user = message.get(
        "from",
        {},
    )

    chat_id = chat.get("id")
    user_id = user.get("id")

    if chat_id is None or user_id is None:
        return

    if not is_allowed(user_id):
        request_access(
            user_id,
            user.get("username"),
            user.get("first_name"),
        )

        send_message(
            chat_id,
            "🔒 ئەم بۆتە تایبەتە.\n"
            "داواکاری دەستگەیشتنت بۆ Admin نێردرا.",
        )

        return

    photos = message.get(
        "photo",
        [],
    )

    if not photos:
        return

    largest = photos[-1]

    file_id = largest.get(
        "file_id"
    )

    if not file_id:
        return

    session = get_session(user_id)

    os.makedirs(
        IMAGE_DIR,
        exist_ok=True,
    )

    filename = os.path.join(
        IMAGE_DIR,
        f"{user_id}_{int(time.time() * 1000)}.jpg",
    )

    if not download_telegram_photo(
        file_id,
        filename,
    ):
        send_message(
            chat_id,
            "❌ وێنەکە نەتوانرا دابەزێنرێت.",
        )
        return

    if session["zone_image"] is None:
        session["zone_image"] = filename

        send_message(
            chat_id,
            "🟢 وێنەی HTF وەرگیرا.\n\n"
            "ئێستا وێنەی M1/M5 بنێرە بۆ Confirmation.",
        )

        return

    session["confirmation_image"] = filename

    send_message(
        chat_id,
        "⏳ هەردوو وێنەکە وەرگیراون.\n"
        "AI + V4.1 Engine شیکاری دەکەن...",
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

def handle_text(
    message: Dict[str, Any],
) -> None:
    chat = message.get(
        "chat",
        {},
    )

    user = message.get(
        "from",
        {},
    )

    chat_id = chat.get("id")
    user_id = user.get("id")

    text = clean_text(
        message.get("text"),
        "",
    )

    if not text:
        return

    if text.startswith("/"):
        if handle_admin_command(
            chat_id,
            user_id,
            text,
        ):
            return

    if not is_allowed(user_id):
        request_access(
            user_id,
            user.get("username"),
            user.get("first_name"),
        )

        send_message(
            chat_id,
            "🔒 دەستگەیشتن بۆ ئەم بۆتە نییە.\n"
            "داواکارییەکەت بۆ Admin نێردرا.",
        )

        return

    command = text.lower().strip()

    if command in {
        "/start",
        "start",
    }:
        reset_session(user_id)

        send_message(
            chat_id,
            "🥇 Gold Chart Analyzer PRO\n\n"
            "1️⃣ H1/H4 chart بنێرە بۆ VS/VR + Zone.\n"
            "2️⃣ پاشان M1/M5 chart بنێرە بۆ Pullback + Confirmation.\n\n"
            "BUY: RBS / SRR / I.VR / PO2\n"
            "SELL: SBR / RSS / I.VS / PO2\n\n"
            "⚠️ Strong signal تەنها کاتێک دەردەچێت "
            "کە هەموو مەرجەکان پڕ بن.",
        )

        return

    if command in {
        "/reset",
        "reset",
    }:
        reset_session(user_id)

        send_message(
            chat_id,
            "♻️ Session نوێ کرایەوە.",
        )

        return

    send_message(
        chat_id,
        "📸 تکایە سەرەتا H1/H4 chart بنێرە.",
    )


# ============================================================
# UPDATE HANDLER
# ============================================================

def handle_update(
    update: Dict[str, Any],
) -> None:
    if not isinstance(update, dict):
        return

    message = update.get(
        "message"
    )

    if isinstance(message, dict):
        if message.get("photo"):
            handle_photo(message)
            return

        if message.get("text"):
            handle_text(message)
            return

    callback = update.get(
        "callback_query"
    )

    if isinstance(callback, dict):
        callback_id = callback.get("id")

        if callback_id:
            answer_callback(
                callback_id
            )


# ============================================================
# POLLING
# ============================================================

def delete_webhook() -> None:
    telegram_request(
        "deleteWebhook",
        {
            "drop_pending_updates": False,
        },
    )


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
    logger.info(
        "Starting Gold Chart Analyzer PRO V4.1..."
    )

    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN is missing. Bot cannot start."
        )
        return

    if not GEMINI_API_KEY:
        logger.error(
            "GEMINI_API_KEY is missing. Bot cannot analyze charts."
        )
        return

    delete_webhook()

    offset = None

    while True:
        try:
            response = get_updates(
                offset
            )

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

            updates = response.get(
                "result",
                [],
            )

            for update in updates:
                try:
                    update_id = update.get(
                        "update_id"
                    )

                    if update_id is not None:
                        offset = update_id + 1

                    handle_update(update)

                except Exception:
                    logger.exception(
                        "Update handling error"
                    )

        except KeyboardInterrupt:
            logger.info(
                "Bot stopped manually."
            )
            break

        except Exception:
            logger.exception(
                "Polling loop error"
            )

            time.sleep(10)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    run_bot()
