# ============================================================
# GOLD CHART ANALYZER PRO
# SNRZ EDITION
# ============================================================
#
# FLOW:
# H1/H4
#   ↓
# VS / VR
#   ↓
# ZONE
#   ↓
# WAIT FOR RETEST
#   ↓
# M1/M5
#   ↓
# CONFIRMATION
#   ↓
# STRONG SIGNAL
#   ↓
# BUY / SELL
#
# ENV:
# TELEGRAM_BOT_TOKEN
# GEMINI_API_KEY
#
# ============================================================

import os
import json
import time
import logging
import base64
import re
import secrets
import requests

from google import genai


# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    ""
).strip()

GEMINI_MODEL = "gemini-3.6-flash"

ADMIN_USER_ID = 5874840448

ACCESS_FILE = "allowed_users.json"

MIN_STRONG_SCORE = 80
MIN_STRONG_CONFIDENCE = 80
MIN_RR = 2.0

MAX_IMAGE_SIZE = 10 * 1024 * 1024


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(
    "gold_chart_analyzer"
)


# ============================================================
# VALIDATION
# ============================================================

if not TELEGRAM_BOT_TOKEN:
    logger.warning(
        "TELEGRAM_BOT_TOKEN is missing."
    )

if not GEMINI_API_KEY:
    logger.warning(
        "GEMINI_API_KEY is missing."
    )


# ============================================================
# GEMINI
# ============================================================

gemini = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# TELEGRAM API
# ============================================================

class TelegramAPIError(Exception):
    pass


class Telegram:

    def __init__(self, token):

        self.token = token

        self.base_url = (
            f"https://api.telegram.org/bot{token}"
        )

    def request(
        self,
        method,
        payload=None,
        timeout=60
    ):

        try:

            response = requests.post(
                f"{self.base_url}/{method}",
                json=payload or {},
                timeout=timeout
            )

        except requests.RequestException as exc:

            raise TelegramAPIError(
                f"Telegram connection error: {exc}"
            ) from exc

        if response.status_code != 200:

            raise TelegramAPIError(
                f"Telegram HTTP {response.status_code}: "
                f"{response.text}"
            )

        try:

            data = response.json()

        except Exception as exc:

            raise TelegramAPIError(
                "Telegram returned invalid JSON."
            ) from exc

        if not data.get("ok"):

            raise TelegramAPIError(
                data.get(
                    "description",
                    "Unknown Telegram error."
                )
            )

        return data.get(
            "result"
        )

    def get_me(self):

        return self.request(
            "getMe"
        )

    def delete_webhook(self):

        return self.request(
            "deleteWebhook",
            {
                "drop_pending_updates": False
            }
        )

    def get_updates(
        self,
        offset=None,
        timeout=30
    ):

        payload = {
            "timeout": timeout
        }

        if offset is not None:

            payload["offset"] = offset

        return self.request(
            "getUpdates",
            payload,
            timeout=timeout + 10
        )

    def send_message(
        self,
        chat_id,
        text,
        reply_markup=None
    ):

        payload = {
            "chat_id": chat_id,
            "text": text
        }

        if reply_markup is not None:

            payload["reply_markup"] = reply_markup

        return self.request(
            "sendMessage",
            payload
        )

    def answer_callback_query(
        self,
        callback_query_id,
        text=""
    ):

        return self.request(
            "answerCallbackQuery",
            {
                "callback_query_id":
                    callback_query_id,
                "text": text
            }
        )

    def get_file(
        self,
        file_id
    ):

        return self.request(
            "getFile",
            {
                "file_id": file_id
            }
        )

    def download_file(
        self,
        file_path
    ):

        url = (
            f"https://api.telegram.org/file/"
            f"bot{self.token}/{file_path}"
        )

        response = requests.get(
            url,
            timeout=60
        )

        if response.status_code != 200:

            raise TelegramAPIError(
                f"Telegram file download failed: "
                f"{response.status_code}"
            )

        return response.content


telegram = Telegram(
    TELEGRAM_BOT_TOKEN
)


# ============================================================
# ACCESS SYSTEM
# ============================================================

ALLOWED_USER_IDS = set()
PENDING_ACCESS_REQUESTS = {}


def load_access():

    global ALLOWED_USER_IDS
    global PENDING_ACCESS_REQUESTS

    if not os.path.exists(
        ACCESS_FILE
    ):

        ALLOWED_USER_IDS = {
            ADMIN_USER_ID
        }

        PENDING_ACCESS_REQUESTS = {}

        save_access()

        return

    try:

        with open(
            ACCESS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        ALLOWED_USER_IDS = set(
            data.get(
                "allowed_users",
                []
            )
        )

        PENDING_ACCESS_REQUESTS = data.get(
            "pending",
            {}
        )

        ALLOWED_USER_IDS.add(
            ADMIN_USER_ID
        )

    except Exception:

        logger.exception(
            "Failed loading access file."
        )

        ALLOWED_USER_IDS = {
            ADMIN_USER_ID
        }

        PENDING_ACCESS_REQUESTS = {}


def save_access():

    data = {
        "allowed_users": list(
            ALLOWED_USER_IDS
        ),
        "pending": PENDING_ACCESS_REQUESTS
    }

    try:

        with open(
            ACCESS_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

    except Exception:

        logger.exception(
            "Failed saving access file."
        )


load_access()


# ============================================================
# USER SESSIONS
# ============================================================

USER_SESSIONS = {}


# ============================================================
# ACCESS HELPERS
# ============================================================

def is_admin(
    user_id
):

    return (
        user_id == ADMIN_USER_ID
    )


def is_allowed(
    user_id
):

    return (
        user_id in ALLOWED_USER_IDS
        or is_admin(user_id)
    )


def send_access_request(
    message,
    chat_id,
    user_id
):

    user = message.get(
        "from",
        {}
    )

    first_name = user.get(
        "first_name",
        "Unknown"
    )

    username = user.get(
        "username",
        ""
    )

    request_id = secrets.token_hex(
        4
    )

    PENDING_ACCESS_REQUESTS[
        str(user_id)
    ] = {
        "user_id": user_id,
        "first_name": first_name,
        "username": username,
        "request_id": request_id
    }

    save_access()

    keyboard = {
        "inline_keyboard": [[
            {
                "text": "✅ Approve",
                "callback_data":
                    f"approve:{user_id}"
            },
            {
                "text": "❌ Reject",
                "callback_data":
                    f"reject:{user_id}"
            }
        ]]
    }

    try:

        telegram.send_message(
            ADMIN_USER_ID,

            f"""
🔔 ACCESS REQUEST

👤 Name:
{first_name}

🔹 Username:
@{username if username else "N/A"}

🆔 User ID:
{user_id}

🔐 Request:
{request_id}
""".strip(),

            keyboard
        )

    except Exception:

        logger.exception(
            "Could not notify admin."
        )

    telegram.send_message(
        chat_id,

        """
🔒 ئەم بۆتە تایبەتە.

داواکاری دەستگەیشتنت نێردراوە بۆ Admin.

⏳ تکایە چاوەڕێ بکە تا دەستگەیشتنت پەسەند بکرێت.
""".strip()
    )


def deny_access(
    chat_id
):

    telegram.send_message(
        chat_id,

        """
🔒 دەستگەیشتنت بۆ ئەم بۆتە نییە.

/ start بکە بۆ ناردنی داواکاری دەستگەیشتن.
""".replace(
            "/ start",
            "/start"
        ).strip()
    )


# ============================================================
# ADMIN COMMANDS
# ============================================================

def handle_admin_command(
    message,
    chat_id,
    text
):

    parts = text.split()

    command = parts[0].lower() \
        if parts else ""

    if command == "/admin":

        telegram.send_message(
            chat_id,

            f"""
👑 ADMIN PANEL

👥 Allowed:
{len(ALLOWED_USER_IDS)}

⏳ Pending:
{len(PENDING_ACCESS_REQUESTS)}

Commands:

/adduser USER_ID
/removeuser USER_ID
/users
/pending
/broadcast MESSAGE
""".strip()
        )

        return True

    if command == "/adduser":

        if len(parts) < 2:

            telegram.send_message(
                chat_id,
                "Usage: /adduser USER_ID"
            )

            return True

        try:

            target = int(
                parts[1]
            )

            ALLOWED_USER_IDS.add(
                target
            )

            PENDING_ACCESS_REQUESTS.pop(
                str(target),
                None
            )

            save_access()

            telegram.send_message(
                chat_id,
                f"✅ User {target} added."
            )

        except ValueError:

            telegram.send_message(
                chat_id,
                "❌ User ID دەبێت ژمارە بێت."
            )

        return True

    if command == "/removeuser":

        if len(parts) < 2:

            telegram.send_message(
                chat_id,
                "Usage: /removeuser USER_ID"
            )

            return True

        try:

            target = int(
                parts[1]
            )

            if target == ADMIN_USER_ID:

                telegram.send_message(
                    chat_id,
                    "❌ ناتوانیت Admin بسڕیتەوە."
                )

                return True

            ALLOWED_USER_IDS.discard(
                target
            )

            save_access()

            telegram.send_message(
                chat_id,
                f"🗑 User {target} removed."
            )

        except ValueError:

            telegram.send_message(
                chat_id,
                "❌ User ID ـەکە هەڵەیە."
            )

        return True

    if command == "/users":

        users = sorted(
            ALLOWED_USER_IDS
        )

        if not users:

            output = "هیچ user ـێک نییە."

        else:

            output = "\n".join(
                f"• {uid}"
                for uid in users
            )

        telegram.send_message(
            chat_id,

            f"""
👥 ALLOWED USERS

{output}
""".strip()
        )

        return True

    if command == "/pending":

        if not PENDING_ACCESS_REQUESTS:

            telegram.send_message(
                chat_id,
                "⏳ هیچ request ـێکی pending نییە."
            )

            return True

        lines = []

        for item in PENDING_ACCESS_REQUESTS.values():

            lines.append(
                f"• {item.get('user_id')} "
                f"- {item.get('first_name')}"
            )

        telegram.send_message(
            chat_id,

            "⏳ PENDING REQUESTS\n\n"
            + "\n".join(lines)
        )

        return True

    if command == "/broadcast":

        if len(parts) < 2:

            telegram.send_message(
                chat_id,
                "Usage: /broadcast MESSAGE"
            )

            return True

        broadcast_text = text[
            len("/broadcast"):
        ].strip()

        sent = 0

        for user_id in list(
            ALLOWED_USER_IDS
        ):

            try:

                telegram.send_message(
                    user_id,
                    broadcast_text
                )

                sent += 1

            except Exception:

                logger.exception(
                    f"Broadcast failed for {user_id}"
                )

        telegram.send_message(
            chat_id,
            f"📢 Broadcast sent to {sent} users."
        )

        return True

    return False


# ============================================================
# ACCESS CALLBACK
# ============================================================

def handle_access_callback(
    callback_query
):

    callback_id = callback_query.get(
        "id"
    )

    data = callback_query.get(
        "data",
        ""
    )

    if not is_admin(
        callback_query.get(
            "from",
            {}
        ).get("id")
    ):

        if callback_id:

            telegram.answer_callback_query(
                callback_id,
                "Unauthorized."
            )

        return

    try:

        action, user_id_text = data.split(
            ":",
            1
        )

        user_id = int(
            user_id_text
        )

    except Exception:

        if callback_id:

            telegram.answer_callback_query(
                callback_id,
                "Invalid request."
            )

        return

    if action == "approve":

        ALLOWED_USER_IDS.add(
            user_id
        )

        PENDING_ACCESS_REQUESTS.pop(
            str(user_id),
            None
        )

        save_access()

        try:

            telegram.send_message(
                user_id,

                """
✅ دەستگەیشتنت پەسەند کرا.

ئێستا `/start` بکە بۆ دەستپێکردنی Gold Chart Analyzer PRO.
""".strip()
            )

        except Exception:

            logger.exception(
                "Could not notify approved user."
            )

        if callback_id:

            telegram.answer_callback_query(
                callback_id,
                "User approved."
            )

        telegram.send_message(
            ADMIN_USER_ID,
            f"✅ User {user_id} approved."
        )

    elif action == "reject":

        PENDING_ACCESS_REQUESTS.pop(
            str(user_id),
            None
        )

        save_access()

        try:

            telegram.send_message(
                user_id,

                """
❌ داواکاری دەستگەیشتنت پەسەند نەکرا.
""".strip()
            )

        except Exception:

            logger.exception(
                "Could not notify rejected user."
            )

        if callback_id:

            telegram.answer_callback_query(
                callback_id,
                "User rejected."
            )


# ============================================================
# JSON CLEANER
# ============================================================

def clean_json(
    text
):

    if not text:

        raise ValueError(
            "Empty AI response."
        )

    text = text.strip()

    text = re.sub(
        r"^```json\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"^```\s*",
        "",
        text
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    start = text.find(
        "{"
    )

    end = text.rfind(
        "}"
    )

    if start == -1 or end == -1:

        raise ValueError(
            "No JSON object found."
        )

    return text[
        start:end + 1
    ]


# ============================================================
# SAFE FLOAT
# ============================================================

def safe_float(
    value
):

    if value is None:

        return None

    if isinstance(
        value,
        (int, float)
    ):

        return float(
            value
        )

    text = str(
        value
    )

    matches = re.findall(
        r"-?\d+(?:\.\d+)?",
        text
    )

    if not matches:

        return None

    try:

        return float(
            matches[0]
        )

    except Exception:

        return None


# ============================================================
# RR
# ============================================================

def calculate_rr(
    data
):

    entry = safe_float(
        data.get(
            "entry"
        )
    )

    sl = safe_float(
        data.get(
            "sl"
        )
    )

    tp1 = safe_float(
        data.get(
            "tp1"
        )
    )

    if (
        entry is None
        or sl is None
        or tp1 is None
    ):

        return None

    risk = abs(
        entry - sl
    )

    reward = abs(
        tp1 - entry
    )

    if risk <= 0:

        return None

    return reward / risk


# ============================================================
# CONFIRMATION VALIDATION
# ============================================================

def confirmation_is_valid(
    signal,
    confirmation
):

    text = str(
        confirmation or ""
    ).upper()

    if signal == "BUY":

        valid = (
            "RBS" in text
            or "SRR" in text
            or "I.VR" in text
            or "PO2" in text
        )

    elif signal == "SELL":

        valid = (
            "SBR" in text
            or "RSS" in text
            or "I.VS" in text
            or "PO2" in text
        )

    else:

        valid = False

    return valid


# ============================================================
# VS / VR VALIDATION
# ============================================================

def validate_vs_vr(
    data,
    signal
):

    vs = str(
        data.get(
            "vs_detected",
            ""
        )
    ).upper()

    vr = str(
        data.get(
            "vr_detected",
            ""
        )
    ).upper()

    if signal == "BUY":

        return (
            "VS" in vs
            or "VR" in vr
        )

    if signal == "SELL":

        return (
            "VR" in vr
            or "VS" in vs
        )

    return False


# ============================================================
# STRONG SIGNAL ENGINE
# ============================================================

def strong_signal_engine(
    data
):

    if not isinstance(
        data,
        dict
    ):

        raise ValueError(
            "AI response is not an object."
        )

    signal = str(
        data.get(
            "signal",
            "WAIT"
        )
    ).upper().strip()

    if signal not in (
        "BUY",
        "SELL",
        "WAIT"
    ):

        signal = "WAIT"

    score = safe_float(
        data.get(
            "score",
            0
        )
    ) or 0

    confidence = safe_float(
        data.get(
            "confidence",
            0
        )
    ) or 0

    zone = str(
        data.get(
            "zone",
            ""
        )
    ).strip()

    zone_price = str(
        data.get(
            "zone_price",
            ""
        )
    ).strip()

    confirmation = str(
        data.get(
            "confirmation",
            ""
        )
    ).strip()

    rejection_reasons = []

    # ========================================================
    # SCORE
    # ========================================================

    if score < MIN_STRONG_SCORE:

        rejection_reasons.append(
            f"Score = {score:.0f} ـە؛ "
            f"پێویستە کەمترین "
            f"{MIN_STRONG_SCORE} بێت."
        )

    # ========================================================
    # CONFIDENCE
    # ========================================================

    if confidence < MIN_STRONG_CONFIDENCE:

        rejection_reasons.append(
            f"Confidence = {confidence:.0f}% ـە؛ "
            f"پێویستە کەمترین "
            f"{MIN_STRONG_CONFIDENCE}% بێت."
        )

    # ========================================================
    # VS / VR
    # ========================================================

    if signal in (
        "BUY",
        "SELL"
    ):

        if not validate_vs_vr(
            data,
            signal
        ):

            rejection_reasons.append(
                "هیچ VS/VR ـێکی HTF "
                "بە شێوەیەکی ڕوون "
                "پشتڕاست نەکراوەتەوە."
            )

    # ========================================================
    # CONFIRMATION
    # ========================================================

    if signal in (
        "BUY",
        "SELL"
    ):

        if not confirmation_is_valid(
            signal,
            confirmation
        ):

            rejection_reasons.append(
                "Confirmation ـی دروستی "
                "SNRZ نییە."
            )

    # ========================================================
    # ZONE
    # ========================================================

    if not zone:

        rejection_reasons.append(
            "Zone بەردەست نییە."
        )

    elif zone.upper() in (
        "NONE",
        "N/A",
        "UNKNOWN"
    ):

        rejection_reasons.append(
            "Zone ـێکی ڕوونی HTF نییە."
        )

    # ========================================================
    # ZONE PRICE
    # ========================================================

    if not zone_price:

        if signal in (
            "BUY",
            "SELL"
        ):

            rejection_reasons.append(
                "Zone Price دیاری نەکراوە."
            )

    elif zone_price.upper() in (
        "NONE",
        "N/A",
        "UNKNOWN"
    ):

        if signal in (
            "BUY",
            "SELL"
        ):

            rejection_reasons.append(
                "Zone Price ـی دروست نییە."
            )

    # ========================================================
    # ENTRY / SL / TP
    # ========================================================

    if signal in (
        "BUY",
        "SELL"
    ):

        entry = str(
            data.get(
                "entry",
                "N/A"
            )
        )

        sl = str(
            data.get(
                "sl",
                "N/A"
            )
        )

        tp1 = str(
            data.get(
                "tp1",
                "N/A"
            )
        )

        if entry.upper() == "N/A":

            rejection_reasons.append(
                "Entry دیاری نەکراوە."
            )

        if sl.upper() == "N/A":

            rejection_reasons.append(
                "SL دیاری نەکراوە."
            )

        if tp1.upper() == "N/A":

            rejection_reasons.append(
                "TP1 دیاری نەکراوە."
            )

    # ========================================================
    # RR
    # ========================================================

    calculated_rr = calculate_rr(
        data
    )

    if signal in (
        "BUY",
        "SELL"
    ):

        if calculated_rr is None:

            rejection_reasons.append(
                "RR بە شێوەیەکی دروست "
                "حساب ناکرێت."
            )

        elif calculated_rr < MIN_RR:

            rejection_reasons.append(
                f"RR = 1:{calculated_rr:.2f} ـە؛ "
                "کەمترە لە 1:2."
            )

    # ========================================================
    # FINAL WAIT
    # ========================================================

    if rejection_reasons:

        data["signal"] = "WAIT"

        data["entry"] = "N/A"
        data["sl"] = "N/A"
        data["tp1"] = "N/A"
        data["tp2"] = "N/A"
        data["tp3"] = "N/A"
        data["rr"] = "N/A"

        data["rejection_reason"] = (
            " ".join(
                rejection_reasons
            )
        )

        wait_for = str(
            data.get(
                "wait_for",
                ""
            )
        ).strip()

        # ----------------------------------------------------
        # ZONE PRICE IN WAIT
        # ----------------------------------------------------

        if (
            zone_price
            and zone_price.upper()
            not in (
                "N/A",
                "NONE",
                "UNKNOWN"
            )
        ):

            data["rejection_reason"] = (
                f"📍 Zone Price: "
                f"{zone_price}\n"
                + data["rejection_reason"]
            )

            if wait_for:

                if zone_price not in wait_for:

                    wait_for = (
                        f"{wait_for}\n"
                        f"📍 Zone Price: "
                        f"{zone_price}"
                    )

            else:

                wait_for = (
                    f"چاوەڕێ بکە نرخ "
                    f"بگەڕێتەوە بۆ Zone ـی "
                    f"{zone_price}."
                )

        else:

            if not wait_for:

                wait_for = (
                    "چاوەڕێی structure ـێکی "
                    "تەواوی SNRZ و "
                    "confirmation ـی ڕوون بکە."
                )

        data["wait_for"] = wait_for

        return data

    # ========================================================
    # ACCEPTED STRONG SIGNAL
    # ========================================================

    data["signal"] = signal

    if calculated_rr is not None:

        data["rr"] = (
            f"1:{calculated_rr:.2f}"
        )

    data["rejection_reason"] = (
        "هیچ rejection filter ـێک نەشکا."
    )

    data["wait_for"] = "N/A"

    return data


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = r"""
You are GOLD CHART ANALYZER PRO.

You analyze XAUUSD screenshots using ONLY the SNRZ structure.

============================================================
TIMEFRAME
============================================================

IMAGE 1:
H1 or H4.
This is HTF.

IMAGE 2:
M1 or M5.
This is LTF.

============================================================
VALID VS
============================================================

VS is valid ONLY when:

SUPPORT
→ UP
→ NEW RESISTANCE AFTER SUPPORT
→ UP AGAIN
→ BREAK NEW RESISTANCE

The NEW resistance created AFTER support is the important one.

Do not use an old resistance.

============================================================
VALID VR
============================================================

VR is valid ONLY when:

RESISTANCE
→ DOWN
→ NEW SUPPORT AFTER RESISTANCE
→ DOWN AGAIN
→ BREAK NEW SUPPORT

The NEW support created AFTER resistance is the important one.

Do not use an old support.

============================================================
ZONE
============================================================

Zone is made from:

VS/VR candle
+
immediately previous candle.

Compare BODY sizes.

The shorter BODY wins.

Then the entire candle HIGH-to-LOW
becomes the Zone.

Do NOT use engulfing logic.

============================================================
FLOW
============================================================

VALID VS/VR
→ ZONE
→ PRICE RETURNS / RETESTS ZONE
→ M1/M5 CONFIRMATION
→ STRONG SIGNAL CHECK
→ ENTRY

Confirmation BEFORE Zone retest is INVALID.

============================================================
BUY CONFIRMATIONS
============================================================

RBS
SRR
I.VR
complete PO2

============================================================
SELL CONFIRMATIONS
============================================================

SBR
RSS
I.VS
complete PO2

============================================================
INVERSION
============================================================

I.VR:

VR breaks
→ inversion
→ support.

I.VS:

VS breaks
→ inversion
→ resistance.

============================================================
PO2
============================================================

PO2 is strongest only when COMPLETE.

SELL example:

VS break
→ I.VS
→ new resistance
→ new support breaks
→ return to I.VS
→ SELL.

BUY is the mirror structure.

Never call incomplete structure PO2.

============================================================
STRONG SIGNAL
============================================================

BUY or SELL ONLY if:

Score >= 80
Confidence >= 80
RR >= 1:2
Clear HTF Zone
Price retested Zone
Valid M1/M5 confirmation AFTER retest
HTF/LTF agreement
Logical Entry
Logical SL
Logical TP

If anything is missing:

WAIT.

============================================================
RISK
============================================================

SL should normally be around 50 pips beyond Zone.

BUY:
SL below Zone.

SELL:
SL above Zone.

TP1:
normally 100–200 pips from Entry.

TP2:
5-minute liquidity.

TP3:
previous VS/VR or important liquidity.

Do not invent impossible prices.

============================================================
WAIT
============================================================

If price has NOT reached Zone:

WAIT.

wait_for MUST clearly say:

چاوەڕێ بکە نرخ بگەڕێتەوە بۆ Zone ـی X.

Always include exact Zone Price.

============================================================
OUTPUT
============================================================

Return ONLY valid JSON.

Required keys:

{
 "signal": "BUY/SELL/WAIT",
 "score": 0,
 "confidence": 0,
 "trend": "...",
 "setup": "...",
 "zone": "...",
 "zone_price": "...",
 "htf_zones": "...",
 "vs_detected": "...",
 "vr_detected": "...",
 "confirmation": "...",
 "entry": "...",
 "sl": "...",
 "tp1": "...",
 "tp2": "...",
 "tp3": "...",
 "rr": "...",
 "reasoning": "...",
 "checks": "...",
 "wait_for": "..."
}

Never invent Zone Price.
Never invent Entry, SL or TP when they cannot be read logically.
"""


# ============================================================
# GEMINI IMAGE ANALYSIS
# ============================================================

def analyze_two_charts(
    zone_image,
    confirmation_image
):

    if len(zone_image) > MAX_IMAGE_SIZE:

        raise RuntimeError(
            "H1/H4 image زۆر گەورەیە."
        )

    if len(confirmation_image) > MAX_IMAGE_SIZE:

        raise RuntimeError(
            "M1/M5 image زۆر گەورەیە."
        )

    zone_base64 = base64.b64encode(
        zone_image
    ).decode(
        "utf-8"
    )

    confirmation_base64 = base64.b64encode(
        confirmation_image
    ).decode(
        "utf-8"
    )

    user_prompt = r"""
Analyze both XAUUSD chart images.

IMAGE 1 = H1/H4.
IMAGE 2 = M1/M5.

Follow the complete SNRZ structure.

FIRST scan the entire H1/H4 chart.

Identify valid VS and VR only when complete structure is proven.

VS:

SUPPORT
→ UP
→ NEW RESISTANCE AFTER SUPPORT
→ UP AGAIN
→ BREAK NEW RESISTANCE
→ VS

VR:

RESISTANCE
→ DOWN
→ NEW SUPPORT AFTER RESISTANCE
→ DOWN AGAIN
→ BREAK NEW SUPPORT
→ VR

ZONE:

VS/VR candle + immediately previous candle.

Compare BODY size.

Shorter BODY wins.

Entire candle HIGH-to-LOW is the Zone.

Not engulfing.

PULLBACK:

VALID VS/VR
→ ZONE
→ PRICE RETURNS/RETESTS ZONE
→ M1/M5 CONFIRMATION
→ STRONG SIGNAL CHECK
→ ENTRY

Never accept confirmation before Pullback.

BUY:

RBS / SRR / I.VR / complete PO2

SELL:

SBR / RSS / I.VS / complete PO2

Strong signal:

Score >= 80
Confidence >= 80
RR >= 1:2
Clear Zone
Price retested Zone
Valid confirmation after Pullback
HTF/LTF agreement
Logical Entry
Logical SL
Logical TP.

If anything is missing:

WAIT.

IMPORTANT:

If a valid Zone exists,
ALWAYS provide the actual Zone Price in:

"zone_price"

Example:

"zone_price": "2380.00 - 2382.00"

If WAIT because price has not reached Zone,
"wait_for" MUST include the exact Zone Price.

Example:

"wait_for": "چاوەڕێ بکە نرخ بگەڕێتەوە بۆ Zone ـی 2380.00 - 2382.00."

Do not invent prices.

Return ONLY valid JSON.
"""

    try:

        interaction = gemini.interactions.create(

            model=GEMINI_MODEL,

            system_instruction=SYSTEM_PROMPT,

            input=[

                {
                    "type": "text",
                    "text": user_prompt
                },

                {
                    "type": "image",
                    "data": zone_base64,
                    "mime_type": "image/jpeg"
                },

                {
                    "type": "image",
                    "data": confirmation_base64,
                    "mime_type": "image/jpeg"
                }
            ],

            generation_config={
                "thinking_level": "medium"
            }
        )

        text = interaction.output_text

        cleaned = clean_json(
            text
        )

        result = json.loads(
            cleaned
        )

        return strong_signal_engine(
            result
        )

    except json.JSONDecodeError as exc:

        logger.exception(
            "Invalid JSON returned by Gemini."
        )

        raise RuntimeError(
            "AI وەڵامی JSON ـی دروستی نەدا."
        ) from exc

    except Exception as exc:

        logger.exception(
            "Gemini analysis failed."
        )

        raise RuntimeError(
            f"Gemini API error: {exc}"
        ) from exc


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(
    data
):

    signal = str(
        data.get(
            "signal",
            "WAIT"
        )
    ).upper()

    if signal == "BUY":

        title = (
            "🟢 STRONG BUY SIGNAL"
        )

    elif signal == "SELL":

        title = (
            "🔴 STRONG SELL SIGNAL"
        )

    else:

        title = "🟡 WAIT"

        signal = "WAIT"

    zone_price = str(
        data.get(
            "zone_price",
            "N/A"
        )
    ).strip()

    if not zone_price:

        zone_price = "N/A"

    text = f"""
{title}
━━━━━━━━━━━━━━

🥇 XAUUSD

📊 Score:
{data.get("score", 0)}/100

💪 Confidence:
{data.get("confidence", 0)}%

📈 Trend:
{data.get("trend", "N/A")}

🧠 Setup:
{data.get("setup", "N/A")}

🟦 Zone:
{data.get("zone", "N/A")}

📍 Zone Price:
{zone_price}

🔎 HTF Zones:
{data.get("htf_zones", "N/A")}

🟢 VS:
{data.get("vs_detected", "N/A")}

🔴 VR:
{data.get("vr_detected", "N/A")}

🔎 Confirmation:
{data.get("confirmation", "N/A")}
"""

    if signal != "WAIT":

        text += f"""
━━━━━━━━━━━━━━

🎯 Entry:
{data.get("entry", "N/A")}

🛑 SL:
{data.get("sl", "N/A")}

🥇 TP1:
{data.get("tp1", "N/A")}

🥈 TP2:
{data.get("tp2", "N/A")}

🥉 TP3:
{data.get("tp3", "N/A")}

📊 R:R:
{data.get("rr", "N/A")}
"""

    text += f"""
━━━━━━━━━━━━━━

🔎 هۆکار:
{data.get("reasoning", "N/A")}

✅ Checks:
{data.get("checks", "N/A")}
"""

    if signal == "WAIT":

        text += f"""
━━━━━━━━━━━━━━

🚫 هۆکاری WAIT:
{data.get(
    "rejection_reason",
    "setup ـێکی بەهێز نەدۆزرایەوە."
)}

👀 چاوەڕێی چی بکەین؟
{data.get(
    "wait_for",
    f"چاوەڕێ بکە نرخ بگەڕێتەوە بۆ Zone ـی {zone_price}."
)}
"""

    else:

        text += """
━━━━━━━━━━━━━━

🟢 STRONG SNRZ setup

هەموو rejection filter ـە سەرەکییەکان تێپەڕاند.

⚠️ ئەمە تەنها شیکردنەوەی تەکنیکییە؛
هیچ دڵنیاییەک بە قازانج نادات.
"""

    return text.strip()


# ============================================================
# DOWNLOAD TELEGRAM PHOTO
# ============================================================

def download_telegram_photo(
    message
):

    photos = message.get(
        "photo"
    )

    if not photos:

        return None

    largest_photo = photos[-1]

    file_id = largest_photo[
        "file_id"
    ]

    file_info = telegram.get_file(
        file_id
    )

    file_path = file_info[
        "file_path"
    ]

    photo = telegram.download_file(
        file_path
    )

    if len(photo) > MAX_IMAGE_SIZE:

        raise RuntimeError(
            "❌ وێنەکە لە 10MB گەورەترە."
        )

    return photo


# ============================================================
# WAIT FOR ZONE DETECTOR
# ============================================================

def is_waiting_for_zone(
    result
):

    signal = str(
        result.get(
            "signal",
            "WAIT"
        )
    ).upper()

    if signal != "WAIT":

        return False

    zone_price = str(
        result.get(
            "zone_price",
            ""
        )
    ).strip()

    if not zone_price:

        return False

    if zone_price.upper() in (
        "N/A",
        "NONE",
        "UNKNOWN"
    ):

        return False

    wait_for = str(
        result.get(
            "wait_for",
            ""
        )
    )

    text = wait_for.lower()

    zone_words = (
        "zone",
        "بگەڕێتەوە",
        "بگاتە",
        "گەیشتە",
        "گەڕایەوە"
    )

    return any(
        word in text
        for word in zone_words
    )


# ============================================================
# MESSAGE HANDLER
# ============================================================

def handle_message(
    message
):

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get(
        "id"
    )

    if not chat_id:

        return

    user = message.get(
        "from",
        {}
    )

    user_id = user.get(
        "id"
    )

    text = message.get(
        "text",
        ""
    ).strip()

    # ========================================================
    # ADMIN FIRST
    # ========================================================

    if is_admin(
        user_id
    ):

        if handle_admin_command(
            message,
            chat_id,
            text
        ):

            return

    # ========================================================
    # ACCESS
    # ========================================================

    if not is_allowed(
        user_id
    ):

        if text == "/start":

            send_access_request(
                message,
                chat_id,
                user_id
            )

            return

        deny_access(
            chat_id
        )

        return

    # ========================================================
    # START
    # ========================================================

    if text == "/start":

        USER_SESSIONS[
            chat_id
        ] = {

            "zone_image": None,

            "confirmation_image": None,

            "state":
                "awaiting_htf"
        }

        telegram.send_message(
            chat_id,

            """
🥇 Gold Chart Analyzer PRO

🧠 SNRZ Structure Engine چالاکە.

هەنگاوی 1️⃣:

📸 H1 یان H4 ـی XAUUSD بنێرە.

پاشان:

📍 VS / VR
→ Zone
→ Pullback / Retest

کاتێک نرخ گەیشتە Zone:

📸 chart ـێکی نوێی M1 یان M5 بنێرە.

بۆتەکە هەمان Zone ـی H1/H4
دەپارێزێت.

🟡 ئەگەر مەرجەکان تەواو نەبن:
WAIT
""".strip()
        )

        return

    # ========================================================
    # HELP
    # ========================================================

    if text == "/help":

        telegram.send_message(
            chat_id,

            """
📚 SNRZ STRUCTURE ENGINE

HTF:
H1 / H4

LTF:
M1 / M5

VS:
Support
→ Up
→ New Resistance
→ Up
→ Break New Resistance

VR:
Resistance
→ Down
→ New Support
→ Down
→ Break New Support

ZONE:
VS/VR candle
+
previous candle
→ shorter BODY
→ entire HIGH-LOW

FLOW:

VS/VR
→ Zone
→ Pullback / Retest
→ Confirmation
→ Strong Signal
→ Entry

BUY:
RBS / SRR / I.VR / PO2

SELL:
SBR / RSS / I.VS / PO2

ئەگەر نرخ هێشتا نەگەیشتووەتە Zone:

🟡 WAIT

کاتێک نرخ گەیشتە Zone:

📸 M1/M5 ـی نوێ بنێرە.

H1/H4 دووبارە مەبنێرە.
""".strip()
        )

        return

    # ========================================================
    # RESET
    # ========================================================

    if text == "/reset":

        USER_SESSIONS.pop(
            chat_id,
            None
        )

        telegram.send_message(
            chat_id,

            """
♻️ Session reset کرا.

📸 ئێستا H1 یان H4 بنێرە.
""".strip()
        )

        return

    # ========================================================
    # PHOTO
    # ========================================================

    photo = download_telegram_photo(
        message
    )

    if photo is not None:

        session = USER_SESSIONS.setdefault(
            chat_id,
            {
                "zone_image": None,
                "confirmation_image": None,
                "state": "awaiting_htf"
            }
        )

        state = session.get(
            "state",
            "awaiting_htf"
        )

        # ====================================================
        # RETEST CHART
        # ====================================================

        if state == "waiting_retest_chart":

            if session.get(
                "zone_image"
            ) is None:

                session[
                    "state"
                ] = "awaiting_htf"

                telegram.send_message(
                    chat_id,

                    """
⚠️ Zone ـی پێشوو لە Session ـدا نییە.

تکایە H1 یان H4 ـی نوێ بنێرە.
""".strip()
                )

                return

            session[
                "confirmation_image"
            ] = photo

            telegram.send_message(
                chat_id,

                """
🔄 Fresh M1/M5 Chart وەرگیرا.

📍 Zone ـی H1/H4 ـی پێشوو
هەر پارێزراوە.

🧠 شیکردنەوە:

Zone Retest
→ Confirmation
→ Strong Signal

⏳ تکایە چاوەڕێ بکە...
""".strip()
            )

            try:

                result = analyze_two_charts(
                    session[
                        "zone_image"
                    ],
                    session[
                        "confirmation_image"
                    ]
                )

                telegram.send_message(
                    chat_id,
                    format_signal(
                        result
                    )
                )

                if is_waiting_for_zone(
                    result
                ):

                    session[
                        "state"
                    ] = (
                        "waiting_retest_chart"
                    )

                    session[
                        "confirmation_image"
                    ] = None

                    telegram.send_message(
                        chat_id,

                        f"""
📍 Zone ـەکە هەر پارێزراوە:

{result.get("zone_price", "N/A")}

🟡 WAIT

کاتێک نرخ گەیشتە/گەڕایەوە بۆ ئەم Zone ـە:

📸 chart ـێکی نوێی M1 یان M5 بنێرە.

⚠️ H1/H4 دووبارە مەبنێرە.
""".strip()
                    )

                else:

                    USER_SESSIONS.pop(
                        chat_id,
                        None
                    )

            except Exception as exc:

                logger.exception(
                    "Fresh retest analysis failed."
                )

                session[
                    "confirmation_image"
                ] = None

                telegram.send_message(
                    chat_id,

                    f"""
❌ شیکردنەوەی Fresh Chart نەکرا.

هۆکار:
{exc}

📸 M1/M5 ـی ڕوون دووبارە بنێرە.
""".strip()
                )

            return

        # ====================================================
        # FIRST IMAGE — HTF
        # ====================================================

        if session.get(
            "zone_image"
        ) is None:

            session[
                "zone_image"
            ] = photo

            session[
                "confirmation_image"
            ] = None

            session[
                "state"
            ] = "awaiting_confirmation"

            telegram.send_message(
                chat_id,

                """
✅ H1/H4 وەرگیرا.

🔎 VS / VR ـی HTF دەناسین.

📍 Zone دیاری دەکرێت.

پاشان:

⏳ چاوەڕێی Pullback / Retest دەکەین.

کاتێک نرخ گەیشتە Zone:

📸 M1 یان M5 ـی نوێ بنێرە.
""".strip()
            )

            return

        # ====================================================
        # SECOND IMAGE — LTF
        # ====================================================

        if session.get(
            "confirmation_image"
        ) is None:

            session[
                "confirmation_image"
            ] = photo

            telegram.send_message(
                chat_id,

                """
⏳ هەردوو chart وەرگیرا.

🧠 SNRZ ENGINE

VS / VR
→ Zone
→ Retest
→ Confirmation
→ Score
→ Confidence
→ RR

شیکردنەوە دەکەم...
""".strip()
            )

            try:

                result = analyze_two_charts(
                    session[
                        "zone_image"
                    ],
                    session[
                        "confirmation_image"
                    ]
                )

                telegram.send_message(
                    chat_id,
                    format_signal(
                        result
                    )
                )

                # ============================================
                # KEEP HTF IF WAITING FOR ZONE
                # ============================================

                if is_waiting_for_zone(
                    result
                ):

                    session[
                        "state"
                    ] = (
                        "waiting_retest_chart"
                    )

                    session[
                        "confirmation_image"
                    ] = None

                    zone_price = result.get(
                        "zone_price",
                        "N/A"
                    )

                    telegram.send_message(
                        chat_id,

                        f"""
📍 Zone ـەکە هەر پارێزراوە:

{zone_price}

🟡 WAIT

هێشتا confirmation ـی دروستی
دوای Retest نییە.

کاتێک نرخ گەیشتە/گەڕایەوە بۆ Zone:

📸 chart ـێکی نوێی M1 یان M5 بنێرە.

⚠️ H1/H4 دووبارە مەبنێرە.
بۆتەکە Zone ـی پێشوو هەڵدەگرێت.
""".strip()
                    )

                else:

                    USER_SESSIONS.pop(
                        chat_id,
                        None
                    )

            except Exception as exc:

                logger.exception(
                    "Analysis failed."
                )

                session[
                    "confirmation_image"
                ] = None

                telegram.send_message(
                    chat_id,

                    f"""
❌ شیکردنەوەکە نەکرا.

هۆکار:

{exc}

📸 chart ـێکی ڕوون دووبارە بنێرە.
""".strip()
                )

            return

        return

    # ========================================================
    # OTHER TEXT
    # ========================================================

    telegram.send_message(
        chat_id,

        """
تکایە chart بنێرە.

1️⃣ H1 یان H4
↓
2️⃣ Zone / Retest
↓
3️⃣ M1 یان M5

ئەگەر بۆتەکە WAIT ـی داوە
و Zone ـی دیاری کردووە:

📸 M1/M5 ـی نوێ بنێرە.

یان:

/start
""".strip()
    )


# ============================================================
# MAIN LOOP
# ============================================================

def run():

    logger.info(
        "======================================"
    )

    logger.info(
        "Gold Chart Analyzer PRO started."
    )

    logger.info(
        f"Gemini model: {GEMINI_MODEL}"
    )

    logger.info(
        f"Admin ID: {ADMIN_USER_ID}"
    )

    logger.info(
        f"Allowed users: "
        f"{len(ALLOWED_USER_IDS)}"
    )

    logger.info(
        f"Pending requests: "
        f"{len(PENDING_ACCESS_REQUESTS)}"
    )

    logger.info(
        f"Minimum score: "
        f"{MIN_STRONG_SCORE}"
    )

    logger.info(
        f"Minimum confidence: "
        f"{MIN_STRONG_CONFIDENCE}%"
    )

    logger.info(
        f"Minimum RR: 1:{MIN_RR}"
    )

    logger.info(
        "======================================"
    )

    # ========================================================
    # TELEGRAM CONNECTION
    # ========================================================

    try:

        me = telegram.get_me()

        logger.info(
            f"Telegram connected: "
            f"@{me.get('username')}"
        )

    except Exception:

        logger.exception(
            "Telegram connection failed."
        )

        raise

    # ========================================================
    # REMOVE WEBHOOK
    # ========================================================

    try:

        telegram.delete_webhook()

        logger.info(
            "Telegram webhook removed."
        )

    except Exception:

        logger.exception(
            "Could not delete webhook."
        )

    # ========================================================
    # POLLING
    # ========================================================

    offset = None

    while True:

        try:

            updates = telegram.get_updates(
                offset=offset,
                timeout=30
            )

            for update in updates:

                update_id = update.get(
                    "update_id"
                )

                if update_id is not None:

                    offset = (
                        update_id + 1
                    )

                # ============================================
                # CALLBACK
                # ============================================

                callback_query = update.get(
                    "callback_query"
                )

                if callback_query:

                    try:

                        handle_access_callback(
                            callback_query
                        )

                    except Exception:

                        logger.exception(
                            "Callback error."
                        )

                    continue

                # ============================================
                # MESSAGE
                # ============================================

                message = update.get(
                    "message"
                )

                if not message:

                    continue

                try:

                    handle_message(
                        message
                    )

                except Exception:

                    logger.exception(
                        "Message handling error."
                    )

        except TelegramAPIError as exc:

            error_text = str(
                exc
            )

            if "409" in error_text:

                logger.error(
                    "Telegram 409 Conflict."
                )

                logger.error(
                    "Another bot instance is running."
                )

                logger.error(
                    "Stop every other instance "
                    "using this bot token."
                )

                time.sleep(
                    10
                )

            else:

                logger.error(
                    f"Telegram polling error: "
                    f"{error_text}"
                )

                time.sleep(
                    5
                )

        except KeyboardInterrupt:

            logger.info(
                "Bot stopped manually."
            )

            break

        except Exception:

            logger.exception(
                "Unexpected error."
            )

            time.sleep(
                5
            )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    run()
