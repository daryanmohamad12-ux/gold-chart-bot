Gold Chart Analyzer PRO — V4
=============================

XAUUSD SNRZ Visual Analyzer
24/7 Telegram Bot

FLOW
----
1. H1/H4 = HTF structure + VS/VR + Zone
2. M1/M5 = LTF confirmation
3. Pullback MUST happen before confirmation
4. Engine independently validates VS/VR evidence
5. Strong BUY/SELL only when ALL filters pass

IMPORTANT
---------
VS:
Support
 -> Up
 -> NEW Resistance after Support
 -> Up again
 -> Break SAME Resistance
 -> Original Support = VS

VR:
Resistance
 -> Down
 -> NEW Support after Resistance
 -> Down again
 -> Break SAME Support
 -> Original Resistance = VR

ZONE
----
After valid VS/VR:
- Find formation candle
- Look at immediately previous candle
- Compare BODY SIZE
- Choose SHORTER body
- Whole selected candle HIGH -> LOW = Zone

NO ENGULFING ZONE RULE.

ENTRY
-----
VALID VS/VR
 -> Zone
 -> Pullback / Retest
 -> M1/M5 confirmation
 -> Strong Signal filters
 -> Entry

Technical terms remain English.
Explanations are Kurdish Sorani.
"""

import os
import json
import time
import logging
import requests
import base64
import re
import secrets

from google import genai


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

ADMIN_ID = 5874840448

MIN_STRONG_SCORE = 80
MIN_STRONG_CONFIDENCE = 80
MIN_RR = 2.0

POLL_TIMEOUT = 30
TELEGRAM_MESSAGE_LIMIT = 4000

ALLOWED_USERS_FILE = "allowed_users.json"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("GoldChartAnalyzer")


# ============================================================
# GEMINI
# ============================================================

if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY is missing.")

try:
    gemini = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    gemini = None
    logger.error("Gemini client initialization failed: %s", e)


# ============================================================
# TELEGRAM
# ============================================================

if not TELEGRAM_BOT_TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN is missing.")

TELEGRAM_API = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    if TELEGRAM_BOT_TOKEN
    else ""
)


def telegram_request(method, payload=None, timeout=40):
    if not TELEGRAM_API:
        return None

    try:
        response = requests.post(
            f"{TELEGRAM_API}/{method}",
            json=payload or {},
            timeout=timeout
        )

        if response.status_code != 200:
            logger.error(
                "Telegram API %s: %s",
                response.status_code,
                response.text[:500]
            )
            return None

        return response.json()

    except Exception as e:
        logger.error("Telegram request error: %s", e)
        return None


def send_message(chat_id, text, reply_markup=None):
    if not text:
        return

    chunks = [
        text[i:i + TELEGRAM_MESSAGE_LIMIT]
        for i in range(0, len(text), TELEGRAM_MESSAGE_LIMIT)
    ]

    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk
        }

        if reply_markup:
            payload["reply_markup"] = reply_markup

        telegram_request("sendMessage", payload)


def answer_callback(callback_id, text=""):
    telegram_request(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text
        }
    )


# ============================================================
# ACCESS SYSTEM
# ============================================================

USER_SESSIONS = {}


def load_allowed_users():
    if not os.path.exists(ALLOWED_USERS_FILE):
        return {}

    try:
        with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception as e:
        logger.error("Could not load allowed users: %s", e)

    return {}


def save_allowed_users(users):
    try:
        with open(
            ALLOWED_USERS_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                users,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:
        logger.error("Could not save allowed users: %s", e)


ALLOWED_USERS = load_allowed_users()

if str(ADMIN_ID) not in ALLOWED_USERS:
    ALLOWED_USERS[str(ADMIN_ID)] = {
        "name": "ADMIN",
        "approved": True
    }
    save_allowed_users(ALLOWED_USERS)


PENDING_USERS = {}


def is_allowed(user_id):
    return (
        str(user_id) == str(ADMIN_ID)
        or str(user_id) in ALLOWED_USERS
    )


def request_access(user_id, username, first_name):
    uid = str(user_id)

    if is_allowed(user_id):
        return True

    PENDING_USERS[uid] = {
        "username": username or "",
        "first_name": first_name or "",
        "requested_at": int(time.time())
    }

    return False


# ============================================================
# ADMIN COMMANDS
# ============================================================

def admin_help():
    return (
        "👑 ADMIN PANEL\n\n"
        "/adduser ID\n"
        "/removeuser ID\n"
        "/users\n"
        "/pending\n"
        "/broadcast TEXT\n"
        "/admin"
    )


def handle_admin_command(chat_id, user_id, text):
    if str(user_id) != str(ADMIN_ID):
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
            send_message(chat_id, "❌ ID بنووسە.")
            return True

        target = parts[1].strip()

        ALLOWED_USERS[target] = {
            "name": target,
            "approved": True
        }

        save_allowed_users(ALLOWED_USERS)

        send_message(
            chat_id,
            f"✅ User `{target}` زیادکرا."
        )
        return True

    if command == "/removeuser":
        if len(parts) < 2:
            send_message(chat_id, "❌ ID بنووسە.")
            return True

        target = parts[1].strip()

        if target in ALLOWED_USERS:
            del ALLOWED_USERS[target]
            save_allowed_users(ALLOWED_USERS)

        send_message(
            chat_id,
            f"🗑 User `{target}` لابرا."
        )
        return True

    if command == "/users":
        if not ALLOWED_USERS:
            send_message(chat_id, "هیچ User ـێک نییە.")
            return True

        lines = ["👥 ALLOWED USERS\n"]

        for uid, info in ALLOWED_USERS.items():
            name = info.get("name", "")
            lines.append(f"• {uid} — {name}")

        send_message(chat_id, "\n".join(lines))
        return True

    if command == "/pending":
        if not PENDING_USERS:
            send_message(chat_id, "📭 هیچ داواکارییەکی چاوەڕوان نییە.")
            return True

        lines = ["📥 PENDING USERS\n"]

        for uid, info in PENDING_USERS.items():
            lines.append(
                f"• {uid} — "
                f"{info.get('first_name', '')} "
                f"@{info.get('username', '')}"
            )

        send_message(chat_id, "\n".join(lines))
        return True

    if command == "/broadcast":
        if len(parts) < 2:
            send_message(chat_id, "❌ دەقەکە بنووسە.")
            return True

        message = parts[1]

        sent = 0

        for uid in ALLOWED_USERS:
            if telegram_request(
                "sendMessage",
                {
                    "chat_id": uid,
                    "text": message
                }
            ):
                sent += 1

        send_message(
            chat_id,
            f"📢 Broadcast نێردرا بۆ {sent} User."
        )

        return True

    return False


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = r"""
You are the visual market analyst for an XAUUSD SNRZ Telegram bot.

LANGUAGE:
- Explanations must be Sorani Kurdish.
- Technical SNRZ names must remain English.

ABSOLUTE VISUAL RULE:
- Inspect only visible candles.
- Read the chart from left to right.
- Never invent missing candles.
- Never assume a breakout that is not visibly confirmed.
- Current price alone is NOT historical proof.
- A wick/touch/rejection is NOT automatically a break.
- If evidence is unclear, mark it unclear rather than guessing.

==================================================
VS RULE
==================================================

A Support becomes VS ONLY when this exact sequence is visible:

1. Original Support exists.
2. Price moves UP from that Support.
3. A NEW Resistance forms AFTER the original Support.
4. Price moves UP again from that area.
5. The SAME NEW Resistance is visibly broken.
6. The break is confirmed by visible candle/body acceptance above it.

Important:
- Resistance formed BEFORE the original Support is irrelevant.
- Normal Support is NOT automatically VS.
- If the new Resistance is not broken, it is NOT VS.
- Do not use current price as proof of a historical break.

==================================================
VR RULE
==================================================

A Resistance becomes VR ONLY when this exact inverse sequence is visible:

1. Original Resistance exists.
2. Price moves DOWN from that Resistance.
3. A NEW Support forms AFTER the original Resistance.
4. Price moves DOWN again from that area.
5. The SAME NEW Support is visibly broken.
6. The break is confirmed by visible candle/body acceptance below it.

Important:
- Support formed BEFORE the original Resistance is irrelevant.
- Normal Resistance is NOT automatically VR.
- If the new Support is not broken, it is NOT VR.
- Do not use current price as proof of a historical break.

==================================================
ZONE RULE
==================================================

After VS/VR formation:

1. Identify the formation candle.
2. Look at the immediately previous candle.
3. Compare BODY SIZE only.
4. Choose the shorter-body candle.
5. The entire HIGH -> LOW of that selected candle is the Zone.

Do NOT use engulfing-based zones.

==================================================
ENTRY ORDER
==================================================

VALID VS/VR
-> ZONE
-> PRICE PULLBACK / RETEST
-> M1/M5 CONFIRMATION
-> STRONG SIGNAL CHECK
-> ENTRY

Confirmation BEFORE pullback is INVALID.

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

==================================================
STRONG SIGNAL
==================================================

Strong BUY/SELL requires:

- Score >= 80
- Confidence >= 80%
- RR >= 1:2
- Valid VS/VR
- Valid Zone
- Price actually retested Zone
- Confirmation occurred AFTER pullback
- HTF/LTF agreement
- Logical Entry
- Logical SL
- Logical TP1
- No strong rejection
- No major contradiction

If ANY mandatory condition is missing:
WAIT.

==================================================
IMPORTANT
==================================================

The final engine will independently validate structure evidence.

Your job:
- Carefully inspect chart
- Report visible price levels
- Report candle/sequence evidence
- Do not force a valid/invalid answer if the chart is unclear
- Provide enough evidence for the deterministic engine.

Return JSON only.
"""


# ============================================================
# USER PROMPT
# ============================================================

USER_ANALYSIS_PROMPT = r"""
Analyze these two XAUUSD charts.

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
- entry confirmation

Do NOT invent anything.

Most importantly, report the numerical price levels involved in the visible VS/VR sequence.

Return exactly this JSON structure:

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
# JSON CLEANER
# ============================================================

def clean_json_text(text):
    if not text:
        return ""

    text = text.strip()

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE
        )

        text = re.sub(
            r"\s*```$",
            "",
            text
        )

    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:
        return text[start:end + 1]

    return text


def parse_json_response(text):
    cleaned = clean_json_text(text)

    try:
        return json.loads(cleaned)

    except Exception as e:
        logger.error(
            "JSON parse error: %s | Response: %s",
            e,
            cleaned[:1000]
        )

        return {}


# ============================================================
# SAFE HELPERS
# ============================================================

def safe_float(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()

            if value.lower() in (
                "",
                "n/a",
                "na",
                "none",
                "null",
                "unknown"
            ):
                return None

        return float(value)

    except Exception:
        return None


def safe_bool(value):
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        return value.strip().lower() in (
            "true",
            "yes",
            "y",
            "1",
            "confirmed",
            "valid"
        )

    return False


def clean_text(value, default="N/A"):
    if value is None:
        return default

    value = str(value).strip()

    if not value:
        return default

    return value


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_structure(s):
    if not isinstance(s, dict):
        s = {}

    evidence = s.get("evidence", {})

    if not isinstance(evidence, dict):
        evidence = {}

    return {
        "candidate": safe_bool(s.get("candidate")),

        "original_level": safe_float(
            s.get("original_level")
        ),

        "validation_level": safe_float(
            s.get("validation_level")
        ),

        "break_price": safe_float(
            s.get("break_price")
        ),

        "formation_candle": clean_text(
            s.get("formation_candle"),
            ""
        ),

        "break_candle": clean_text(
            s.get("break_candle"),
            ""
        ),

        "evidence": {
            "original_level_visible":
                safe_bool(
                    evidence.get(
                        "original_level_visible"
                    )
                ),

            "first_move_confirmed":
                safe_bool(
                    evidence.get(
                        "first_move_confirmed"
                    )
                ),

            "new_level_formed_after_original":
                safe_bool(
                    evidence.get(
                        "new_level_formed_after_original"
                    )
                ),

            "second_move_confirmed":
                safe_bool(
                    evidence.get(
                        "second_move_confirmed"
                    )
                ),

            "same_level_broken":
                safe_bool(
                    evidence.get(
                        "same_level_broken"
                    )
                ),

            "break_confirmed":
                safe_bool(
                    evidence.get(
                        "break_confirmed"
                    )
                )
        },

        "notes": clean_text(
            s.get("notes"),
            ""
        )
    }


# ============================================================
# V4 STRUCTURE VALIDATION
# ============================================================

def structure_evidence_score(structure):
    evidence = structure.get("evidence", {})

    keys = [
        "original_level_visible",
        "first_move_confirmed",
        "new_level_formed_after_original",
        "second_move_confirmed",
        "same_level_broken",
        "break_confirmed"
    ]

    return sum(
        1 for key in keys
        if safe_bool(evidence.get(key))
    )


def verify_vs_v4(structure):
    """
    V4 VS validator.

    Main improvement over V3:
    Do not blindly reject a structure simply because Gemini
    missed one evidence boolean.

    Numeric chronology + explicit break evidence are weighted
    more heavily.

    However, we NEVER invent a missing level.
    """

    s = normalize_structure(structure)

    original = s["original_level"]
    validation = s["validation_level"]
    break_price = s["break_price"]

    ev = s["evidence"]

    # Original support must exist.
    if original is None:
        return False, "VS: original Support missing."

    # New resistance must be above original support.
    if validation is None:
        return False, "VS: NEW Resistance level missing."

    if validation <= original:
        return False, "VS: validation Resistance is not above Support."

    # Break price must be above the NEW Resistance.
    if break_price is None:
        return False, "VS: historical break price missing."

    if break_price <= validation:
        return False, "VS: break price is not above NEW Resistance."

    # Critical evidence.
    critical = (
        safe_bool(ev.get("original_level_visible")),
        safe_bool(ev.get("new_level_formed_after_original")),
        safe_bool(ev.get("same_level_broken")),
        safe_bool(ev.get("break_confirmed"))
    )

    # Explicit candidate is allowed to be false if numeric/evidence
    # proves the sequence. Candidate is not treated as the authority.
    if all(critical):
        return True, "VS validated."

    # V4 fallback:
    # If the key numeric chronology is valid and at least 4/6
    # visible evidence points exist, accept.
    score = structure_evidence_score(s)

    if score >= 4 and (
        safe_bool(ev.get("same_level_broken"))
        or safe_bool(ev.get("break_confirmed"))
    ):
        return True, "VS validated from strong evidence."

    return False, (
        f"VS rejected: evidence insufficient ({score}/6)."
    )


def verify_vr_v4(structure):
    """
    V4 VR validator.
    """

    s = normalize_structure(structure)

    original = s["original_level"]
    validation = s["validation_level"]
    break_price = s["break_price"]

    ev = s["evidence"]

    if original is None:
        return False, "VR: original Resistance missing."

    if validation is None:
        return False, "VR: NEW Support level missing."

    if validation >= original:
        return False, "VR: validation Support is not below Resistance."

    if break_price is None:
        return False, "VR: historical break price missing."

    if break_price >= validation:
        return False, "VR: break price is not below NEW Support."

    critical = (
        safe_bool(ev.get("original_level_visible")),
        safe_bool(ev.get("new_level_formed_after_original")),
        safe_bool(ev.get("same_level_broken")),
        safe_bool(ev.get("break_confirmed"))
    )

    if all(critical):
        return True, "VR validated."

    score = structure_evidence_score(s)

    if score >= 4 and (
        safe_bool(ev.get("same_level_broken"))
        or safe_bool(ev.get("break_confirmed"))
    ):
        return True, "VR validated from strong evidence."

    return False, (
        f"VR rejected: evidence insufficient ({score}/6)."
    )


def get_valid_structures(data):
    structures = data.get("structures", {})

    if not isinstance(structures, dict):
        structures = {}

    vs = normalize_structure(
        structures.get("vs", {})
    )

    vr = normalize_structure(
        structures.get("vr", {})
    )

    vs_valid, vs_reason = verify_vs_v4(vs)
    vr_valid, vr_reason = verify_vr_v4(vr)

    return {
        "vs": vs,
        "vr": vr,
        "vs_valid": vs_valid,
        "vr_valid": vr_valid,
        "vs_reason": vs_reason,
        "vr_reason": vr_reason
    }


# ============================================================
# CONFIRMATION
# ============================================================

BUY_CONFIRMATIONS = {
    "RBS",
    "SRR",
    "I.VR",
    "PO2"
}

SELL_CONFIRMATIONS = {
    "SBR",
    "RSS",
    "I.VS",
    "PO2"
}


def normalize_confirmation_name(name):
    if not name:
        return ""

    value = str(name).strip().upper()

    value = value.replace(" ", "")
    value = value.replace("-", "")

    return value


def confirmation_is_valid(data):
    confirmation = data.get(
        "confirmation",
        {}
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
        ""
    ).upper()

    name = normalize_confirmation_name(
        confirmation.get("name")
    )

    if not found:
        return False, name, side

    if not complete:
        return False, name, side

    if not after_pullback:
        return False, name, side

    if side == "BUY":
        if name not in BUY_CONFIRMATIONS:
            return False, name, side

    elif side == "SELL":
        if name not in SELL_CONFIRMATIONS:
            return False, name, side

    else:
        return False, name, side

    return True, name, side


# ============================================================
# ZONE
# ============================================================

def zone_is_valid(data, side):
    zones = data.get("zones", {})

    if not isinstance(zones, dict):
        return False, None, None

    key = (
        "vs_zone"
        if side == "BUY"
        else "vr_zone"
    )

    zone = zones.get(key, {})

    if not isinstance(zone, dict):
        return False, None, None

    valid = safe_bool(zone.get("valid"))

    high = safe_float(zone.get("high"))
    low = safe_float(zone.get("low"))

    if not valid:
        return False, high, low

    if high is None or low is None:
        return False, high, low

    if high <= low:
        return False, high, low

    # Body-size selection must be documented.
    body = safe_float(
        zone.get("body_size")
    )

    previous_body = safe_float(
        zone.get("previous_candle_body_size")
    )

    if body is None or previous_body is None:
        return False, high, low

    return True, high, low


# ============================================================
# PULLBACK
# ============================================================

def pullback_is_valid(data):
    pullback = data.get(
        "pullback",
        {}
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
# RR
# ============================================================

def calculate_rr(entry, sl, tp1):
    entry = safe_float(entry)
    sl = safe_float(sl)
    tp1 = safe_float(tp1)

    if (
        entry is None
        or sl is None
        or tp1 is None
    ):
        return None

    risk = abs(entry - sl)

    if risk <= 0:
        return None

    reward = abs(tp1 - entry)

    return reward / risk


# ============================================================
# STRONG SIGNAL ENGINE
# ============================================================

def strong_signal_engine(data):
    if not isinstance(data, dict):
        data = {}

    structures = get_valid_structures(data)

    vs = structures["vs"]
    vr = structures["vr"]

    vs_valid = structures["vs_valid"]
    vr_valid = structures["vr_valid"]

    trade = data.get("trade", {})

    if not isinstance(trade, dict):
        trade = {}

    raw_signal = clean_text(
        trade.get("signal"),
        "WAIT"
    ).upper()

    if raw_signal not in {
        "BUY",
        "SELL",
        "WAIT"
    }:
        raw_signal = "WAIT"

    score = safe_float(
        trade.get("score")
    )

    confidence = safe_float(
        trade.get("confidence")
    )

    if score is None:
        score = 0

    if confidence is None:
        confidence = 0

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

    # --------------------------------------------
    # Structure
    # --------------------------------------------

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

        structure_name = (
            "VS"
            if vs_valid
            else "VR"
            if vr_valid
            else ""
        )

    # --------------------------------------------
    # Zone
    # --------------------------------------------

    zone_valid = False
    zone_high = None
    zone_low = None

    if raw_signal in {"BUY", "SELL"}:
        zone_valid, zone_high, zone_low = zone_is_valid(
            data,
            raw_signal
        )
    else:
        if vs_valid:
            zone_valid, zone_high, zone_low = zone_is_valid(
                data,
                "BUY"
            )

        if not zone_valid and vr_valid:
            zone_valid, zone_high, zone_low = zone_is_valid(
                data,
                "SELL"
            )

    # --------------------------------------------
    # Pullback
    # --------------------------------------------

    pullback_valid = pullback_is_valid(data)

    # --------------------------------------------
    # Confirmation
    # --------------------------------------------

    confirmation_valid, confirmation_name, confirmation_side = (
        confirmation_is_valid(data)
    )

    # --------------------------------------------
    # HTF/LTF
    # --------------------------------------------

    agreement = safe_bool(
        data.get("htf_ltf_agreement")
    )

    # --------------------------------------------
    # RR
    # --------------------------------------------

    rr = calculate_rr(
        entry,
        sl,
        tp1
    )

    # --------------------------------------------
    # Mandatory checks
    # --------------------------------------------

    checks = {
        "structure": structure_valid,
        "zone": zone_valid,
        "pullback": pullback_valid,
        "confirmation": confirmation_valid,
        "agreement": agreement,
        "score": score >= MIN_STRONG_SCORE,
        "confidence": confidence >= MIN_STRONG_CONFIDENCE,
        "rr": (
            rr is not None
            and rr >= MIN_RR
        ),
        "entry": entry is not None,
        "sl": sl is not None,
        "tp1": tp1 is not None,
        "no_rejection": not rejection
    }

    all_valid = all(checks.values())

    # --------------------------------------------
    # Side consistency
    # --------------------------------------------

    side_consistent = True

    if raw_signal == "BUY":
        side_consistent = (
            confirmation_side == "BUY"
        )

    elif raw_signal == "SELL":
        side_consistent = (
            confirmation_side == "SELL"
        )

    if not side_consistent:
        all_valid = False

    # --------------------------------------------
    # Final signal
    # --------------------------------------------

    if all_valid and raw_signal in {
        "BUY",
        "SELL"
    }:
        final_signal = raw_signal
    else:
        final_signal = "WAIT"

    # --------------------------------------------
    # WAIT reason
    # --------------------------------------------

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

    if rejection:
        missing.append("No rejection")

    if not side_consistent:
        missing.append("Confirmation side")

    if final_signal == "WAIT":
        if structure_valid and zone_valid:
            if raw_signal == "BUY" or (
                not raw_signal and vs_valid
            ):
                wait_for = "Price Pullback/Retest to VS Zone → M1/M5 Confirmation"

            elif raw_signal == "SELL" or (
                not raw_signal and vr_valid
            ):
                wait_for = "Price Pullback/Retest to VR Zone → M1/M5 Confirmation"

            else:
                wait_for = "Valid Pullback + Confirmation"

        elif vs_valid:
            wait_for = "VS Zone → Pullback → M1/M5 Confirmation"

        elif vr_valid:
            wait_for = "VR Zone → Pullback → M1/M5 Confirmation"

        else:
            wait_for = (
                "Complete valid VS/VR structure "
                "with visible historical break"
            )

    else:
        wait_for = ""

    # --------------------------------------------
    # Preserve valid zone even during WAIT
    # --------------------------------------------

    result = dict(data)

    result["engine"] = {
        "vs_valid": vs_valid,
        "vr_valid": vr_valid,
        "vs_reason": structures["vs_reason"],
        "vr_reason": structures["vr_reason"],
        "structure_evidence": {
            "vs": structure_evidence_score(vs),
            "vr": structure_evidence_score(vr)
        },
        "checks": checks,
        "side_consistent": side_consistent
    }

    result["trade"] = {
        "signal": final_signal,
        "score": round(score, 1),
        "confidence": round(confidence, 1),
        "entry": entry if final_signal != "WAIT" else None,
        "sl": sl if final_signal != "WAIT" else None,
        "tp1": tp1 if final_signal != "WAIT" else None,
        "tp2": tp2 if final_signal != "WAIT" else None,
        "rr": round(rr, 2) if (
            rr is not None
            and final_signal != "WAIT"
        ) else None,
        "rejection": rejection
    }

    result["wait_for"] = wait_for

    # Force Zone fields to N/A only if NO valid structure.
    if not vs_valid and not vr_valid:
        result["zones"] = {
            "vs_zone": {
                "valid": False,
                "high": None,
                "low": None
            },
            "vr_zone": {
                "valid": False,
                "high": None,
                "low": None
            }
        }

    return result


# ============================================================
# GEMINI IMAGE ANALYSIS
# ============================================================

def analyze_two_charts(zone_path, confirmation_path):
    if gemini is None:
        return {
            "error": "Gemini client is not initialized."
        }

    try:
        with open(zone_path, "rb") as f:
            zone_bytes = f.read()

        with open(confirmation_path, "rb") as f:
            confirmation_bytes = f.read()

    except Exception as e:
        logger.error(
            "Could not read chart images: %s",
            e
        )

        return {
            "error": "Could not read chart images."
        }

    try:
        # Gemini SDK input.
        #
        # Using bytes directly through Part is more robust
        # than relying on undocumented input dictionaries.

        from google.genai import types

        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=USER_ANALYSIS_PROMPT
                    ),

                    types.Part.from_bytes(
                        data=zone_bytes,
                        mime_type="image/jpeg"
                    ),

                    types.Part.from_bytes(
                        data=confirmation_bytes,
                        mime_type="image/jpeg"
                    )
                ]
            )
        ]

        response = gemini.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.1
            )
        )

        text = getattr(
            response,
            "text",
            ""
        )

        if not text:
            return {
                "error": "Gemini returned an empty response."
            }

        data = parse_json_response(text)

        if not data:
            return {
                "error": "Gemini returned invalid JSON."
            }

        return strong_signal_engine(data)

    except Exception as e:
        logger.exception(
            "Gemini analysis error"
        )

        return {
            "error": str(e)
        }


# ============================================================
# FORMATTERS
# ============================================================

def format_price(value):
    value = safe_float(value)

    if value is None:
        return "N/A"

    return f"{value:.2f}"


def format_structure(data):
    structures = data.get(
        "structures",
        {}
    )

    vs = normalize_structure(
        structures.get("vs", {})
        if isinstance(structures, dict)
        else {}
    )

    vr = normalize_structure(
        structures.get("vr", {})
        if isinstance(structures, dict)
        else {}
    )

    engine = data.get(
        "engine",
        {}
    )

    vs_valid = safe_bool(
        engine.get("vs_valid")
    )

    vr_valid = safe_bool(
        engine.get("vr_valid")
    )

    lines = []

    lines.append("🧱 STRUCTURE")
    lines.append("━━━━━━━━━━━━━━")

    # VS
    if vs_valid:
        lines.append("🟢 VS: VALID")
        lines.append(
            f"Support: {format_price(vs['original_level'])}"
        )
        lines.append(
            f"NEW Resistance: {format_price(vs['validation_level'])}"
        )
        lines.append(
            f"Break: {format_price(vs['break_price'])}"
        )

    else:
        lines.append("⚪ VS: NOT VALID")

    # VR
    if vr_valid:
        lines.append("🔴 VR: VALID")
        lines.append(
            f"Resistance: {format_price(vr['original_level'])}"
        )
        lines.append(
            f"NEW Support: {format_price(vr['validation_level'])}"
        )
        lines.append(
            f"Break: {format_price(vr['break_price'])}"
        )

    else:
        lines.append("⚪ VR: NOT VALID")

    return "\n".join(lines)


def format_signal(data):
    trade = data.get(
        "trade",
        {}
    )

    if not isinstance(trade, dict):
        trade = {}

    signal = clean_text(
        trade.get("signal"),
        "WAIT"
    ).upper()

    score = safe_float(
        trade.get("score")
    ) or 0

    confidence = safe_float(
        trade.get("confidence")
    ) or 0

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
        {}
    )

    if not isinstance(market, dict):
        market = {}

    trend = clean_text(
        market.get("trend"),
        "N/A"
    )

    structure = clean_text(
        market.get("structure"),
        "N/A"
    )

    zones = data.get(
        "zones",
        {}
    )

    if not isinstance(zones, dict):
        zones = {}

    engine = data.get(
        "engine",
        {}
    )

    if not isinstance(engine, dict):
        engine = {}

    vs_valid = safe_bool(
        engine.get("vs_valid")
    )

    vr_valid = safe_bool(
        engine.get("vr_valid")
    )

    # Determine active zone.
    zone_name = "N/A"
    zone_high = None
    zone_low = None

    if signal == "BUY" or (
        signal == "WAIT" and vs_valid
    ):
        zone_name = "VS"
        zone = zones.get(
            "vs_zone",
            {}
        )

        if isinstance(zone, dict):
            zone_high = safe_float(
                zone.get("high")
            )
            zone_low = safe_float(
                zone.get("low")
            )

    elif signal == "SELL" or (
        signal == "WAIT" and vr_valid
    ):
        zone_name = "VR"
        zone = zones.get(
            "vr_zone",
            {}
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
        {}
    )

    if not isinstance(confirmation, dict):
        confirmation = {}

    confirmation_name = clean_text(
        confirmation.get("name"),
        "N/A"
    )

    pullback = data.get(
        "pullback",
        {}
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
            zone_name
        ]

        if (
            zone_high is not None
            and zone_low is not None
        ):
            lines.extend([
                "",
                "📍 Zone Price:",
                f"{format_price(zone_low)} - "
                f"{format_price(zone_high)}"
            ])
        else:
            lines.extend([
                "",
                "📍 Zone Price:",
                "N/A"
            ])

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
            clean_text(
                data.get(
                    "wait_for",
                    ""
                ),
                "Valid setup"
            )
        ])

        return "\n".join(lines)

    # ========================================================
    # STRONG BUY / SELL
    # ========================================================

    emoji = "🟢" if signal == "BUY" else "🔴"

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
        f"{format_price(zone_low)} - "
        f"{format_price(zone_high)}",
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
        "🔥 STRONG SIGNAL"
    ]

    return "\n".join(lines)


# ============================================================
# TELEGRAM FILE DOWNLOAD
# ============================================================

def download_telegram_photo(file_id, destination):
    try:
        file_response = telegram_request(
            "getFile",
            {
                "file_id": file_id
            }
        )

        if not file_response:
            return False

        result = file_response.get(
            "result",
            {}
        )

        file_path = result.get(
            "file_path"
        )

        if not file_path:
            return False

        url = (
            f"https://api.telegram.org/file/"
            f"bot{TELEGRAM_BOT_TOKEN}/"
            f"{file_path}"
        )

        response = requests.get(
            url,
            timeout=60
        )

        if response.status_code != 200:
            logger.error(
                "Photo download failed: %s",
                response.status_code
            )
            return False

        with open(destination, "wb") as f:
            f.write(response.content)

        return True

    except Exception as e:
        logger.error(
            "Photo download error: %s",
            e
        )

        return False


# ============================================================
# SESSION HELPERS
# ============================================================

def get_session(user_id):
    uid = str(user_id)

    if uid not in USER_SESSIONS:
        USER_SESSIONS[uid] = {
            "zone_image": None,
            "confirmation_image": None,
            "created_at": time.time()
        }

    return USER_SESSIONS[uid]


def reset_session(user_id):
    USER_SESSIONS[str(user_id)] = {
        "zone_image": None,
        "confirmation_image": None,
        "created_at": time.time()
    }


# ============================================================
# PHOTO HANDLER
# ============================================================

def handle_photo(message):
    chat = message.get(
        "chat",
        {}
    )

    user = message.get(
        "from",
        {}
    )

    chat_id = chat.get("id")
    user_id = user.get("id")

    if chat_id is None or user_id is None:
        return

    if not is_allowed(user_id):
        request_access(
            user_id,
            user.get("username"),
            user.get("first_name")
        )

        send_message(
            chat_id,
            "🔒 ئەم بۆتە تایبەتە.\n"
            "داواکاری دەستگەیشتنت بۆ Admin نێردرا."
        )

        return

    photos = message.get(
        "photo",
        []
    )

    if not photos:
        return

    largest = photos[-1]

    file_id = largest.get("file_id")

    if not file_id:
        return

    session = get_session(user_id)

    os.makedirs(
        "chart_images",
        exist_ok=True
    )

    filename = (
        f"chart_images/"
        f"{user_id}_{int(time.time() * 1000)}.jpg"
    )

    if not download_telegram_photo(
        file_id,
        filename
    ):
        send_message(
            chat_id,
            "❌ وێنەکە نەتوانرا دابەزێنرێت."
        )
        return

    if session["zone_image"] is None:
        session["zone_image"] = filename

        send_message(
            chat_id,
            "🟢 وێنەی HTF وەرگیرا.\n\n"
            "ئێستا وێنەی M1/M5 بنێرە بۆ Confirmation."
        )

        return

    session["confirmation_image"] = filename

    send_message(
        chat_id,
        "⏳ هەردوو وێنەکە وەرگیراون.\n"
        "AI + V4 Engine شیکاری دەکەن..."
    )

    result = analyze_two_charts(
        session["zone_image"],
        session["confirmation_image"]
    )

    if result.get("error"):
        send_message(
            chat_id,
            "❌ هەڵە لە شیکاری:\n"
            + str(result["error"])
        )

        reset_session(user_id)
        return

    signal_text = format_signal(result)

    send_message(
        chat_id,
        signal_text
    )

    reset_session(user_id)


# ============================================================
# TEXT HANDLER
# ============================================================

def handle_text(message):
    chat = message.get(
        "chat",
        {}
    )

    user = message.get(
        "from",
        {}
    )

    chat_id = chat.get("id")
    user_id = user.get("id")

    text = clean_text(
        message.get("text"),
        ""
    )

    if not text:
        return

    # Admin commands.
    if text.startswith("/"):
        if handle_admin_command(
            chat_id,
            user_id,
            text
        ):
            return

    # Access.
    if not is_allowed(user_id):
        request_access(
            user_id,
            user.get("username"),
            user.get("first_name")
        )

        send_message(
            chat_id,
            "🔒 دەستگەیشتن بۆ ئەم بۆتە نییە.\n"
            "داواکارییەکەت بۆ Admin نێردرا."
        )

        return

    command = text.lower().strip()

    if command in {
        "/start",
        "start"
    }:
        reset_session(user_id)

        send_message(
            chat_id,
            "🥇 Gold Chart Analyzer PRO\n\n"
            "1️⃣ H1/H4 chart بنێرە بۆ VS/VR + Zone.\n"
            "2️⃣ پاشان M1/M5 chart بنێرە بۆ Confirmation.\n\n"
            "BUY: RBS / SRR / I.VR / PO2\n"
            "SELL: SBR / RSS / I.VS / PO2\n\n"
            "⚠️ Strong signal تەنها کاتێک دەردەچێت "
            "کە هەموو مەرجەکان پڕ بن."
        )

        return

    if command in {
        "/reset",
        "reset"
    }:
        reset_session(user_id)

        send_message(
            chat_id,
            "♻️ Session نوێ کرایەوە."
        )

        return

    send_message(
        chat_id,
        "📸 تکایە سەرەتا H1/H4 chart بنێرە."
    )


# ============================================================
# UPDATE HANDLER
# ============================================================

def handle_update(update):
    if not isinstance(update, dict):
        return

    message = update.get("message")

    if message:
        if message.get("photo"):
            handle_photo(message)
            return

        if message.get("text"):
            handle_text(message)
            return

    callback = update.get(
        "callback_query"
    )

    if callback:
        callback_id = callback.get(
            "id"
        )

        if callback_id:
            answer_callback(
                callback_id
            )


# ============================================================
# POLLING
# ============================================================

def delete_webhook():
    try:
        telegram_request(
            "deleteWebhook",
            {
                "drop_pending_updates": False
            }
        )
    except Exception:
        pass


def get_updates(offset=None):
    payload = {
        "timeout": POLL_TIMEOUT,
        "allowed_updates": [
            "message",
            "callback_query"
        ]
    }

    if offset is not None:
        payload["offset"] = offset

    return telegram_request(
        "getUpdates",
        payload,
        timeout=POLL_TIMEOUT + 15
    )


def run_bot():
    logger.info(
        "Starting Gold Chart Analyzer PRO V4..."
    )

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
                    response
                )

                time.sleep(5)
                continue

            updates = response.get(
                "result",
                []
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
# MAIN
# ============================================================

if __name__ == "__main__":
    run_bot()
````
