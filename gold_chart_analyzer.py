# ============================================================
# gold_chart_analyzer.py
# ============================================================
# GOLD CHART ANALYZER PRO V7
#
# SNRZ STRUCTURE ENGINE
# ------------------------------------------------------------
#
# H1/H4
#   ↓
# VALID VS / VR
#   ↓
# VALID ZONE
#   ↓
# PRICE RETEST / PULLBACK
#   ↓
# M1/M5 CONFIRMATION
#   ↓
# HTF/LTF AGREEMENT
#   ↓
# RR / ENTRY / SL / TP
#   ↓
# DETERMINISTIC ENGINE
#   ↓
# BUY / SELL / WAIT
#
# Gemini = Visual Analyst
# Python  = Final Truth / Validator
# ============================================================

import os
import json
import time
import logging
import requests
import re
import secrets
import signal
from typing import Any, Dict, Optional, List, Tuple

from google import genai
from google.genai import types


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

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.8-flash"
).strip()

GEMINI_FALLBACK_MODEL = os.getenv(
    "GEMINI_FALLBACK_MODEL",
    "gemini-3.7-flash"
).strip()

ADMIN_USER_ID = int(
    os.getenv(
        "ADMIN_USER_ID",
        "5874840448"
    )
)

ACCESS_FILE = os.getenv(
    "ACCESS_FILE",
    "allowed_users.json"
)

# ============================================================
# SIGNAL REQUIREMENTS
# ============================================================

MIN_STRONG_SCORE = 80
MIN_STRONG_CONFIDENCE = 80
MIN_RR = 2.0

TELEGRAM_POLL_TIMEOUT = 30
TELEGRAM_RETRY_DELAY = 5

GEMINI_RETRIES = 3
GEMINI_RETRY_DELAY = 3

MAX_TELEGRAM_MESSAGE_LENGTH = 4000

SESSION_TTL_SECONDS = 60 * 30


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(
    "GoldChartAnalyzerV7"
)


# ============================================================
# CONFIG VALIDATION
# ============================================================

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is missing."
    )

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is missing."
    )


# ============================================================
# GEMINI CLIENT
# ============================================================

gemini = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# TELEGRAM EXCEPTION
# ============================================================

class TelegramAPIError(Exception):

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None
    ):
        super().__init__(message)
        self.status_code = status_code


# ============================================================
# TELEGRAM BOT
# ============================================================

class TelegramBot:

    def __init__(
        self,
        token: str
    ):

        self.token = token

        self.base_url = (
            f"https://api.telegram.org/bot{token}"
        )

    # --------------------------------------------------------
    # Generic API
    # --------------------------------------------------------

    def call(
        self,
        method: str,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 60
    ):

        url = (
            f"{self.base_url}/{method}"
        )

        try:

            response = requests.post(
                url,
                json=data or {},
                timeout=timeout
            )

        except requests.RequestException as exc:

            raise TelegramAPIError(
                f"Telegram request failed: {exc}"
            ) from exc

        status_code = response.status_code

        try:

            result = response.json()

        except ValueError as exc:

            raise TelegramAPIError(
                f"Telegram returned invalid JSON "
                f"(HTTP {status_code})."
            ) from exc

        if status_code != 200:

            description = result.get(
                "description",
                f"HTTP {status_code}"
            )

            raise TelegramAPIError(
                f"{status_code}: {description}",
                status_code=status_code
            )

        if not result.get("ok"):

            description = result.get(
                "description",
                "Telegram API error"
            )

            raise TelegramAPIError(
                description,
                status_code=status_code
            )

        return result.get("result")

    # --------------------------------------------------------
    # getMe
    # --------------------------------------------------------

    def get_me(self):

        return self.call(
            "getMe"
        )

    # --------------------------------------------------------
    # deleteWebhook
    # --------------------------------------------------------

    def delete_webhook(
        self,
        drop_pending_updates: bool = False
    ):

        return self.call(
            "deleteWebhook",
            {
                "drop_pending_updates":
                    drop_pending_updates
            }
        )

    # --------------------------------------------------------
    # getUpdates
    # --------------------------------------------------------

    def get_updates(
        self,
        offset: Optional[int] = None,
        timeout: int = TELEGRAM_POLL_TIMEOUT
    ):

        payload = {
            "timeout": timeout,
            "allowed_updates": [
                "message",
                "callback_query"
            ]
        }

        if offset is not None:

            payload["offset"] = offset

        return self.call(
            "getUpdates",
            payload,
            timeout=timeout + 15
        )

    # --------------------------------------------------------
    # sendMessage
    # --------------------------------------------------------

    def send_message(
        self,
        chat_id: int,
        text: str
    ):

        if not isinstance(
            text,
            str
        ):

            text = str(text)

        if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:

            return self.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": text
                }
            )

        results = []

        for start in range(
            0,
            len(text),
            MAX_TELEGRAM_MESSAGE_LENGTH
        ):

            chunk = text[
                start:
                start + MAX_TELEGRAM_MESSAGE_LENGTH
            ]

            results.append(
                self.call(
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text": chunk
                    }
                )
            )

        return results

    # --------------------------------------------------------
    # answerCallbackQuery
    # --------------------------------------------------------

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None
    ):

        payload = {
            "callback_query_id":
                callback_query_id
        }

        if text:

            payload["text"] = text

        return self.call(
            "answerCallbackQuery",
            payload
        )

    # --------------------------------------------------------
    # getFile
    # --------------------------------------------------------

    def get_file(
        self,
        file_id: str
    ):

        return self.call(
            "getFile",
            {
                "file_id": file_id
            }
        )

    # --------------------------------------------------------
    # downloadFile
    # --------------------------------------------------------

    def download_file(
        self,
        file_path: str
    ):

        url = (
            f"https://api.telegram.org/file/bot"
            f"{self.token}/{file_path}"
        )

        try:

            response = requests.get(
                url,
                timeout=60
            )

            response.raise_for_status()

        except requests.RequestException as exc:

            raise TelegramAPIError(
                f"File download failed: {exc}"
            ) from exc

        return response.content


telegram = TelegramBot(
    TELEGRAM_BOT_TOKEN
)


# ============================================================
# ACCESS DATABASE
# ============================================================

def load_allowed_users() -> set:

    users = {
        ADMIN_USER_ID
    }

    if not os.path.exists(
        ACCESS_FILE
    ):

        return users

    try:

        with open(
            ACCESS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(
            data,
            list
        ):

            for user_id in data:

                try:

                    users.add(
                        int(user_id)
                    )

                except (
                    ValueError,
                    TypeError
                ):

                    continue

    except Exception:

        logger.exception(
            "Could not load allowed users."
        )

    users.add(
        ADMIN_USER_ID
    )

    return users


ALLOWED_USER_IDS = load_allowed_users()


def save_allowed_users():

    try:

        with open(
            ACCESS_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                sorted(
                    ALLOWED_USER_IDS
                ),
                file,
                indent=2,
                ensure_ascii=False
            )

    except Exception:

        logger.exception(
            "Could not save allowed users."
        )


# ============================================================
# ACCESS REQUESTS
# ============================================================

PENDING_ACCESS_REQUESTS: Dict[
    int,
    Dict[str, Any]
] = {}

ACCESS_CODES: Dict[
    str,
    int
] = {}


# ============================================================
# SESSIONS
# ============================================================

USER_SESSIONS: Dict[
    int,
    Dict[str, Any]
] = {}


def reset_session(
    chat_id: int
):

    USER_SESSIONS.pop(
        chat_id,
        None
    )


def get_session(
    chat_id: int
) -> Dict[str, Any]:

    now = time.time()

    session = USER_SESSIONS.get(
        chat_id
    )

    if session:

        created_at = session.get(
            "created_at",
            now
        )

        if (
            now - created_at
            > SESSION_TTL_SECONDS
        ):

            USER_SESSIONS.pop(
                chat_id,
                None
            )

            session = None

    if session is None:

        session = {
            "zone_image": None,
            "confirmation_image": None,
            "created_at": now
        }

        USER_SESSIONS[
            chat_id
        ] = session

    return session


def cleanup_sessions():

    now = time.time()

    for chat_id, session in list(
        USER_SESSIONS.items()
    ):

        created_at = session.get(
            "created_at",
            now
        )

        if (
            now - created_at
            > SESSION_TTL_SECONDS
        ):

            USER_SESSIONS.pop(
                chat_id,
                None
            )


# ============================================================
# ACCESS HELPERS
# ============================================================

def is_admin(
    user_id: Optional[int]
) -> bool:

    return (
        user_id == ADMIN_USER_ID
    )


def is_allowed(
    user_id: Optional[int]
) -> bool:

    return (
        user_id in ALLOWED_USER_IDS
    )


def deny_access(
    chat_id: int
):

    telegram.send_message(
        chat_id,
        """
⛔ دەستگەیشتن ڕەتکرایەوە.

تۆ هێشتا ڕێگەپێدراوی
Gold Chart Analyzer PRO نیت.

بۆ داواکاریی دەستڕاگەیشتن:
🔑 /start
""".strip()
    )


# ============================================================
# ACCESS CODE
# ============================================================

def generate_access_code() -> str:

    while True:

        code = (
            "GC-"
            + secrets.token_hex(
                3
            ).upper()
            + "-"
            + secrets.token_hex(
                2
            ).upper()
        )

        if code not in ACCESS_CODES:

            return code


# ============================================================
# ACCESS REQUEST
# ============================================================

def send_access_request(
    message: Dict[str, Any],
    chat_id: int,
    user_id: int
):

    if is_allowed(
        user_id
    ):

        return False

    user = message.get(
        "from",
        {}
    )

    first_name = user.get(
        "first_name",
        "Unknown"
    )

    last_name = user.get(
        "last_name",
        ""
    )

    username = user.get(
        "username",
        ""
    )

    if user_id in PENDING_ACCESS_REQUESTS:

        request = PENDING_ACCESS_REQUESTS[
            user_id
        ]

        telegram.send_message(
            chat_id,
            f"""
⏳ داواکارییەکەت پێشتر نێردراوە.

🔑 Access Code:
{request.get("code", "N/A")}

🆔 Telegram ID:
{user_id}

تکایە چاوەڕێی Admin بکە.
""".strip()
        )

        return True

    code = generate_access_code()

    PENDING_ACCESS_REQUESTS[
        user_id
    ] = {
        "user_id": user_id,
        "chat_id": chat_id,
        "code": code,
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
        "created_at": time.time()
    }

    ACCESS_CODES[
        code
    ] = user_id

    telegram.send_message(
        chat_id,
        f"""
⏳ داواکاریی دەستڕاگەیشتنت نێردرا بۆ Admin.

━━━━━━━━━━━━━━━━━━

🔑 Access Code:
{code}

🆔 Telegram ID:
{user_id}

━━━━━━━━━━━━━━━━━━

👑 Admin پێویستە ڕێگەپێدانت پێبدات.

تکایە چاوەڕێ بکە...
""".strip()
    )

    full_name = (
        f"{first_name} {last_name}"
    ).strip()

    username_text = (
        f"@{username}"
        if username
        else "N/A"
    )

    admin_text = f"""
🆕 NEW ACCESS REQUEST
━━━━━━━━━━━━━━━━━━

👤 Name:
{full_name}

🔗 Username:
{username_text}

🆔 User ID:
{user_id}

🔑 Access Code:
{code}

━━━━━━━━━━━━━━━━━━
"""

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ APPROVE",
                    "callback_data":
                        f"approve:{code}"
                },
                {
                    "text": "❌ REJECT",
                    "callback_data":
                        f"reject:{code}"
                }
            ]
        ]
    }

    try:

        telegram.call(
            "sendMessage",
            {
                "chat_id":
                    ADMIN_USER_ID,
                "text":
                    admin_text,
                "reply_markup":
                    keyboard
            }
        )

    except Exception:

        logger.exception(
            "Could not notify admin."
        )

    return True


# ============================================================
# ACCESS CALLBACK
# ============================================================

def handle_access_callback(
    callback_query: Dict[str, Any]
):

    callback_id = callback_query.get(
        "id"
    )

    from_user = callback_query.get(
        "from",
        {}
    )

    admin_id = from_user.get(
        "id"
    )

    data = callback_query.get(
        "data",
        ""
    )

    if admin_id != ADMIN_USER_ID:

        telegram.answer_callback_query(
            callback_id,
            "⛔ تەنها Admin دەتوانێت."
        )

        return

    if ":" not in data:

        telegram.answer_callback_query(
            callback_id,
            "❌ Request ـەکە نادروستە."
        )

        return

    action, code = data.split(
        ":",
        1
    )

    user_id = ACCESS_CODES.get(
        code
    )

    if not user_id:

        telegram.answer_callback_query(
            callback_id,
            "⚠️ Code نییە یان بەکارهاتووە."
        )

        return

    request = PENDING_ACCESS_REQUESTS.get(
        user_id
    )

    if not request:

        telegram.answer_callback_query(
            callback_id,
            "⚠️ Request پێشتر مامەڵەی لەگەڵ کراوە."
        )

        return

    if action == "approve":

        ALLOWED_USER_IDS.add(
            user_id
        )

        save_allowed_users()

        PENDING_ACCESS_REQUESTS.pop(
            user_id,
            None
        )

        ACCESS_CODES.pop(
            code,
            None
        )

        telegram.answer_callback_query(
            callback_id,
            "✅ User approved."
        )

        try:

            telegram.send_message(
                user_id,
                """
✅ ڕێگەپێدراویت!

━━━━━━━━━━━━━━━━━━

🥇 Gold Chart Analyzer PRO V7

🧠 SNRZ Structure Engine چالاکە.

📸 هەنگاوی یەکەم:
H1 یان H4 ـی XAUUSD بنێرە.
""".strip()
            )

        except Exception:

            logger.exception(
                "Could not notify approved user."
            )

        return

    if action == "reject":

        PENDING_ACCESS_REQUESTS.pop(
            user_id,
            None
        )

        ACCESS_CODES.pop(
            code,
            None
        )

        telegram.answer_callback_query(
            callback_id,
            "❌ User rejected."
        )

        try:

            telegram.send_message(
                user_id,
                """
❌ داواکارییەکەت ڕەتکرایەوە.
""".strip()
            )

        except Exception:

            logger.exception(
                "Could not notify rejected user."
            )

        return


# ============================================================
# ADMIN COMMANDS
# ============================================================

def handle_admin_command(
    message: Dict[str, Any],
    chat_id: int,
    text: str
) -> bool:

    user_id = (
        message.get(
            "from",
            {}
        ).get(
            "id"
        )
    )

    if not is_admin(
        user_id
    ):

        return False

    command = text.split(
        maxsplit=1
    )[0].lower()

    # --------------------------------------------------------
    # ADD USER
    # --------------------------------------------------------

    if command == "/adduser":

        parts = text.split()

        if len(parts) != 2:

            telegram.send_message(
                chat_id,
                "❌ بەکارهێنان:\n/adduser USER_ID"
            )

            return True

        try:

            new_user_id = int(
                parts[1]
            )

        except ValueError:

            telegram.send_message(
                chat_id,
                "❌ User ID دەبێت ژمارە بێت."
            )

            return True

        ALLOWED_USER_IDS.add(
            new_user_id
        )

        save_allowed_users()

        request = PENDING_ACCESS_REQUESTS.pop(
            new_user_id,
            None
        )

        if request:

            code = request.get(
                "code"
            )

            if code:

                ACCESS_CODES.pop(
                    code,
                    None
                )

        telegram.send_message(
            chat_id,
            f"""
✅ بەکارهێنەر زیادکرا.

🆔 {new_user_id}

👥 Total:
{len(ALLOWED_USER_IDS)}
""".strip()
        )

        return True

    # --------------------------------------------------------
    # REMOVE USER
    # --------------------------------------------------------

    if command == "/removeuser":

        parts = text.split()

        if len(parts) != 2:

            telegram.send_message(
                chat_id,
                "❌ بەکارهێنان:\n/removeuser USER_ID"
            )

            return True

        try:

            remove_user_id = int(
                parts[1]
            )

        except ValueError:

            telegram.send_message(
                chat_id,
                "❌ User ID دەبێت ژمارە بێت."
            )

            return True

        if remove_user_id == ADMIN_USER_ID:

            telegram.send_message(
                chat_id,
                "⛔ ناتوانیت Admin بسڕیتەوە."
            )

            return True

        if remove_user_id in ALLOWED_USER_IDS:

            ALLOWED_USER_IDS.remove(
                remove_user_id
            )

            save_allowed_users()

            telegram.send_message(
                chat_id,
                f"✅ User {remove_user_id} سڕایەوە."
            )

        else:

            telegram.send_message(
                chat_id,
                "ℹ️ User ID لە لیستدا نییە."
            )

        return True

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    if command == "/users":

        lines = []

        for uid in sorted(
            ALLOWED_USER_IDS
        ):

            if uid == ADMIN_USER_ID:

                lines.append(
                    f"👑 {uid} — ADMIN"
                )

            else:

                lines.append(
                    f"👤 {uid}"
                )

        telegram.send_message(
            chat_id,
            "👥 ALLOWED USERS\n"
            "━━━━━━━━━━━━━━\n"
            + "\n".join(lines)
            + f"\n\nTotal: {len(ALLOWED_USER_IDS)}"
        )

        return True

    # --------------------------------------------------------
    # PENDING
    # --------------------------------------------------------

    if command == "/pending":

        if not PENDING_ACCESS_REQUESTS:

            telegram.send_message(
                chat_id,
                "📭 هیچ request ـێکی چاوەڕوان نییە."
            )

            return True

        lines = []

        for uid, request in (
            PENDING_ACCESS_REQUESTS.items()
        ):

            username = request.get(
                "username",
                ""
            )

            username_text = (
                f"@{username}"
                if username
                else "N/A"
            )

            lines.append(
                f"""
👤 {request.get("first_name", "Unknown")}
🔗 {username_text}
🆔 {uid}
🔑 {request.get("code", "N/A")}
"""
            )

        telegram.send_message(
            chat_id,
            "⏳ PENDING REQUESTS\n"
            "━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(lines)
        )

        return True

    # --------------------------------------------------------
    # BROADCAST
    # --------------------------------------------------------

    if command == "/broadcast":

        broadcast_text = text[
            len("/broadcast"):
        ].strip()

        if not broadcast_text:

            telegram.send_message(
                chat_id,
                "❌ پەیامەکە بنووسە."
            )

            return True

        success = 0
        failed = 0

        for uid in list(
            ALLOWED_USER_IDS
        ):

            try:

                telegram.send_message(
                    uid,
                    broadcast_text
                )

                success += 1

            except Exception:

                failed += 1

        telegram.send_message(
            chat_id,
            f"""
📢 Broadcast تەواوبوو.

✅ {success}
❌ {failed}
""".strip()
        )

        return True

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if command == "/admin":

        telegram.send_message(
            chat_id,
            """
👑 ADMIN PANEL
━━━━━━━━━━━━━━━━━━

/adduser USER_ID

/removeuser USER_ID

/users

/pending

/broadcast MESSAGE
""".strip()
        )

        return True

    return False


# ============================================================
# GEMINI SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = r"""
You are an ELITE XAUUSD SNRZ VISUAL STRUCTURE ANALYST.

IMPORTANT:
You must NOT guess a trade.

Your job is to inspect the charts and return
STRUCTURED EVIDENCE.

Python performs final validation.

============================================================
CHARTS
============================================================

IMAGE 1:
HTF = H1 or H4.

IMAGE 2:
LTF = M1 or M5.

============================================================
VS RULE
============================================================

VS is VALID ONLY when ALL five steps are visible:

1. SUPPORT
2. UP
3. NEW RESISTANCE CREATED AFTER THAT SUPPORT
4. UP AGAIN
5. BREAK OF THAT SAME NEW RESISTANCE

IMPORTANT:

A resistance that existed BEFORE the support
does NOT count.

The new resistance MUST be created AFTER support.

If any step is missing:
VS = INVALID.

============================================================
VR RULE
============================================================

VR is VALID ONLY when ALL five steps are visible:

1. RESISTANCE
2. DOWN
3. NEW SUPPORT CREATED AFTER THAT RESISTANCE
4. DOWN AGAIN
5. BREAK OF THAT SAME NEW SUPPORT

IMPORTANT:

A support that existed BEFORE the resistance
does NOT count.

The new support MUST be created AFTER resistance.

If any step is missing:
VR = INVALID.

============================================================
ZONE RULE
============================================================

After a VALID VS or VR:

Take:

1. Formation candle
2. Immediately previous candle

Compare their CANDLE BODY sizes.

The SHORTER BODY wins.

The selected candle's FULL HIGH-TO-LOW
is the Zone.

Never use only body as Zone.

Never use wick comparison.

Never invent Zone.

============================================================
SEQUENCE
============================================================

VALID VS / VR
↓
ZONE
↓
PRICE RETURNS / RETESTS ZONE
↓
CONFIRMATION
↓
ENTRY

Confirmation BEFORE retest = INVALID.

============================================================
BUY
============================================================

Allowed confirmation:

RBS
SRR
I.VR
PO2

============================================================
SELL
============================================================

Allowed confirmation:

SBR
RSS
I.VS
PO2

============================================================
HTF / LTF
============================================================

BUY requires:

HTF = BULLISH
LTF = BULLISH

SELL requires:

HTF = BEARISH
LTF = BEARISH

RANGE, UNKNOWN, N/A or CONFLICT
do NOT count as agreement.

============================================================
PRICE AT ZONE
============================================================

You must determine:

price_at_zone = true

ONLY if the LTF price visibly reaches/retests
the HTF Zone.

Otherwise:

price_at_zone = false.

============================================================
PULLBACK
============================================================

pullback_valid = true

ONLY if a real return/retest toward the Zone
is visible.

============================================================
CONFIRMATION AFTER RETEST
============================================================

confirmation_after_retest = true

ONLY if confirmation happens AFTER
the Zone retest.

============================================================
TRADE LEVELS
============================================================

For BUY:

SL < Entry < TP1

For SELL:

TP1 < Entry < SL

RR must be at least 1:2.

============================================================
REJECTION
============================================================

If strong rejection or fake breakout is visible:

rejection_present = true.

Then final result must be WAIT.

============================================================
IMPORTANT
============================================================

Do NOT invent prices.

Do NOT invent VS.

Do NOT invent VR.

Do NOT call normal support VS.

Do NOT call normal resistance VR.

Do NOT accept confirmation before retest.

Do NOT turn an incomplete setup into BUY/SELL.

If evidence is missing:
WAIT.

============================================================
OUTPUT
============================================================

Return JSON ONLY.

Use exactly these fields:

{
  "signal": "BUY|SELL|WAIT",
  "symbol": "XAUUSD",

  "structure_direction": "VS|VR|NONE",

  "structure_valid": true,
  "structure_step_1": "...",
  "structure_step_2": "...",
  "structure_step_3": "...",
  "structure_step_4": "...",
  "structure_step_5": "...",

  "vs_detected": "...",
  "vr_detected": "...",

  "zone_valid": true,
  "zone_low": "...",
  "zone_high": "...",
  "zone": "...",
  "zone_price": "...",
  "zone_candle": "...",
  "previous_candle": "...",
  "selected_candle": "...",
  "selected_body": "...",

  "price_at_zone": false,
  "pullback_valid": false,
  "pullback_evidence": "...",

  "confirmation": "...",
  "confirmation_valid": false,
  "confirmation_after_retest": false,
  "confirmation_evidence": "...",

  "htf_direction": "BULLISH|BEARISH|RANGE|UNKNOWN",
  "ltf_direction": "BULLISH|BEARISH|RANGE|UNKNOWN",
  "htf_ltf_agreement": false,

  "entry_valid": false,
  "sl_valid": false,
  "tp_valid": false,

  "entry": "N/A",
  "sl": "N/A",
  "tp1": "N/A",
  "tp2": "N/A",
  "tp3": "N/A",
  "rr": "N/A",

  "setup": "...",
  "trend": "...",
  "reasoning": "...",
  "checks": "...",

  "rejection_present": false,
  "rejection_reason": "",

  "wait_for": "",

  "score": 0,
  "confidence": 0
}

All explanations must be Sorani Kurdish.

SNRZ names remain English.
"""


# ============================================================
# GEMINI JSON SCHEMA
# ============================================================

GEMINI_SCHEMA = {
    "type": "object",
    "properties": {

        "signal": {
            "type": "string"
        },

        "symbol": {
            "type": "string"
        },

        "structure_direction": {
            "type": "string"
        },

        "structure_valid": {
            "type": "boolean"
        },

        "structure_step_1": {
            "type": "string"
        },

        "structure_step_2": {
            "type": "string"
        },

        "structure_step_3": {
            "type": "string"
        },

        "structure_step_4": {
            "type": "string"
        },

        "structure_step_5": {
            "type": "string"
        },

        "vs_detected": {
            "type": "string"
        },

        "vr_detected": {
            "type": "string"
        },

        "zone_valid": {
            "type": "boolean"
        },

        "zone_low": {
            "type": "string"
        },

        "zone_high": {
            "type": "string"
        },

        "zone": {
            "type": "string"
        },

        "zone_price": {
            "type": "string"
        },

        "zone_candle": {
            "type": "string"
        },

        "previous_candle": {
            "type": "string"
        },

        "selected_candle": {
            "type": "string"
        },

        "selected_body": {
            "type": "string"
        },

        "price_at_zone": {
            "type": "boolean"
        },

        "pullback_valid": {
            "type": "boolean"
        },

        "pullback_evidence": {
            "type": "string"
        },

        "confirmation": {
            "type": "string"
        },

        "confirmation_valid": {
            "type": "boolean"
        },

        "confirmation_after_retest": {
            "type": "boolean"
        },

        "confirmation_evidence": {
            "type": "string"
        },

        "htf_direction": {
            "type": "string"
        },

        "ltf_direction": {
            "type": "string"
        },

        "htf_ltf_agreement": {
            "type": "boolean"
        },

        "entry_valid": {
            "type": "boolean"
        },

        "sl_valid": {
            "type": "boolean"
        },

        "tp_valid": {
            "type": "boolean"
        },

        "entry": {
            "type": "string"
        },

        "sl": {
            "type": "string"
        },

        "tp1": {
            "type": "string"
        },

        "tp2": {
            "type": "string"
        },

        "tp3": {
            "type": "string"
        },

        "rr": {
            "type": "string"
        },

        "setup": {
            "type": "string"
        },

        "trend": {
            "type": "string"
        },

        "reasoning": {
            "type": "string"
        },

        "checks": {
            "type": "string"
        },

        "rejection_present": {
            "type": "boolean"
        },

        "rejection_reason": {
            "type": "string"
        },

        "wait_for": {
            "type": "string"
        },

        "score": {
            "type": "number"
        },

        "confidence": {
            "type": "number"
        }
    },

    "required": [
        "signal",
        "symbol",
        "structure_direction",
        "structure_valid",
        "structure_step_1",
        "structure_step_2",
        "structure_step_3",
        "structure_step_4",
        "structure_step_5",
        "vs_detected",
        "vr_detected",
        "zone_valid",
        "zone_low",
        "zone_high",
        "zone",
        "zone_price",
        "zone_candle",
        "previous_candle",
        "selected_candle",
        "selected_body",
        "price_at_zone",
        "pullback_valid",
        "pullback_evidence",
        "confirmation",
        "confirmation_valid",
        "confirmation_after_retest",
        "confirmation_evidence",
        "htf_direction",
        "ltf_direction",
        "htf_ltf_agreement",
        "entry_valid",
        "sl_valid",
        "tp_valid",
        "entry",
        "sl",
        "tp1",
        "tp2",
        "tp3",
        "rr",
        "setup",
        "trend",
        "reasoning",
        "checks",
        "rejection_present",
        "rejection_reason",
        "wait_for",
        "score",
        "confidence"
    ]
}


# ============================================================
# HELPERS
# ============================================================

def clean_text(
    value: Any,
    default: str = "N/A"
) -> str:

    if value is None:

        return default

    text = str(
        value
    ).strip()

    if not text:

        return default

    return text


def safe_float(
    value: Any
) -> Optional[float]:

    try:

        if value is None:

            return None

        if isinstance(
            value,
            bool
        ):

            return None

        if isinstance(
            value,
            (int, float)
        ):

            return float(value)

        text = str(
            value
        ).replace(
            ",",
            ""
        )

        match = re.search(
            r"-?\d+(?:\.\d+)?",
            text
        )

        if not match:

            return None

        return float(
            match.group()
        )

    except Exception:

        return None


def normalize_side(
    value: Any
) -> str:

    text = clean_text(
        value,
        "WAIT"
    ).upper()

    if text == "BUY":
        return "BUY"

    if text == "SELL":
        return "SELL"

    return "WAIT"


def normalize_structure(
    value: Any
) -> str:

    text = clean_text(
        value,
        "NONE"
    ).upper()

    if text == "VS":
        return "VS"

    if text == "VR":
        return "VR"

    return "NONE"


def parse_bool(
    value: Any
) -> bool:

    if isinstance(
        value,
        bool
    ):

        return value

    text = clean_text(
        value,
        ""
    ).lower()

    return text in {
        "true",
        "yes",
        "valid",
        "confirmed",
        "complete"
    }


# ============================================================
# NORMALIZE GEMINI RESULT
# ============================================================

DEFAULT_FIELDS = [
    "signal",
    "symbol",
    "structure_direction",
    "structure_valid",
    "structure_step_1",
    "structure_step_2",
    "structure_step_3",
    "structure_step_4",
    "structure_step_5",
    "vs_detected",
    "vr_detected",
    "zone_valid",
    "zone_low",
    "zone_high",
    "zone",
    "zone_price",
    "zone_candle",
    "previous_candle",
    "selected_candle",
    "selected_body",
    "price_at_zone",
    "pullback_valid",
    "pullback_evidence",
    "confirmation",
    "confirmation_valid",
    "confirmation_after_retest",
    "confirmation_evidence",
    "htf_direction",
    "ltf_direction",
    "htf_ltf_agreement",
    "entry_valid",
    "sl_valid",
    "tp_valid",
    "entry",
    "sl",
    "tp1",
    "tp2",
    "tp3",
    "rr",
    "setup",
    "trend",
    "reasoning",
    "checks",
    "rejection_present",
    "rejection_reason",
    "wait_for",
    "score",
    "confidence"
]


def normalize_result(
    data: Dict[str, Any]
) -> Dict[str, Any]:

    if not isinstance(
        data,
        dict
    ):

        data = {}

    result = {}

    for key in DEFAULT_FIELDS:

        result[key] = data.get(
            key
        )

    result["signal"] = normalize_side(
        result.get(
            "signal"
        )
    )

    result["symbol"] = "XAUUSD"

    result["structure_direction"] = (
        normalize_structure(
            result.get(
                "structure_direction"
            )
        )
    )

    result["structure_valid"] = parse_bool(
        result.get(
            "structure_valid"
        )
    )

    result["zone_valid"] = parse_bool(
        result.get(
            "zone_valid"
        )
    )

    result["price_at_zone"] = parse_bool(
        result.get(
            "price_at_zone"
        )
    )

    result["pullback_valid"] = parse_bool(
        result.get(
            "pullback_valid"
        )
    )

    result["confirmation_valid"] = parse_bool(
        result.get(
            "confirmation_valid"
        )
    )

    result["confirmation_after_retest"] = (
        parse_bool(
            result.get(
                "confirmation_after_retest"
            )
        )
    )

    result["htf_ltf_agreement"] = parse_bool(
        result.get(
            "htf_ltf_agreement"
        )
    )

    result["entry_valid"] = parse_bool(
        result.get(
            "entry_valid"
        )
    )

    result["sl_valid"] = parse_bool(
        result.get(
            "sl_valid"
        )
    )

    result["tp_valid"] = parse_bool(
        result.get(
            "tp_valid"
        )
    )

    result["rejection_present"] = parse_bool(
        result.get(
            "rejection_present"
        )
    )

    return result


# ============================================================
# JSON CLEANER
# ============================================================

def clean_json(
    text: str
) -> str:

    if not text:

        raise RuntimeError(
            "Gemini returned empty response."
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

        raise RuntimeError(
            "Gemini did not return JSON."
        )

    return text[
        start:end + 1
    ]


# ============================================================
# ZONE RANGE
# ============================================================

def parse_zone_range(
    low_value: Any,
    high_value: Any
) -> Optional[Tuple[float, float]]:

    low = safe_float(
        low_value
    )

    high = safe_float(
        high_value
    )

    if low is None or high is None:

        return None

    if high <= low:

        return None

    return (
        low,
        high
    )


def zone_from_data(
    data: Dict[str, Any]
) -> Optional[Tuple[float, float]]:

    zone = parse_zone_range(
        data.get("zone_low"),
        data.get("zone_high")
    )

    if zone:

        return zone

    text = clean_text(
        data.get("zone_price"),
        ""
    )

    numbers = re.findall(
        r"-?\d+(?:\.\d+)?",
        text.replace(
            ",",
            ""
        )
    )

    if len(numbers) < 2:

        return None

    try:

        a = float(
            numbers[0]
        )

        b = float(
            numbers[1]
        )

        if a == b:

            return None

        return (
            min(a, b),
            max(a, b)
        )

    except Exception:

        return None


# ============================================================
# STRICT STRUCTURE VALIDATION
# ============================================================

def structure_steps_valid(
    data: Dict[str, Any],
    direction: str
) -> bool:

    if not data.get(
        "structure_valid"
    ):

        return False

    if normalize_structure(
        data.get(
            "structure_direction"
        )
    ) != direction:

        return False

    steps = [
        clean_text(
            data.get(
                f"structure_step_{i}"
            ),
            ""
        ).upper()
        for i in range(
            1,
            6
        )
    ]

    if any(
        not step
        for step in steps
    ):

        return False

    if direction == "VS":

        required = [
            (
                "SUPPORT",
                "S"
            ),
            (
                "UP",
                "U"
            ),
            (
                "RESISTANCE",
                "R"
            ),
            (
                "UP",
                "U"
            ),
            (
                "BREAK",
                "B"
            )
        ]

        # Exact semantic checks.
        if "SUPPORT" not in steps[0]:

            return False

        if (
            "UP" not in steps[1]
            and "BULL" not in steps[1]
        ):

            return False

        if "RESISTANCE" not in steps[2]:

            return False

        if (
            "UP" not in steps[3]
            and "BULL" not in steps[3]
        ):

            return False

        if "BREAK" not in steps[4]:

            return False

        if "RESISTANCE" not in steps[4]:

            return False

        return True

    if direction == "VR":

        if "RESISTANCE" not in steps[0]:

            return False

        if (
            "DOWN" not in steps[1]
            and "BEAR" not in steps[1]
        ):

            return False

        if "SUPPORT" not in steps[2]:

            return False

        if (
            "DOWN" not in steps[3]
            and "BEAR" not in steps[3]
        ):

            return False

        if "BREAK" not in steps[4]:

            return False

        if "SUPPORT" not in steps[4]:

            return False

        return True

    return False


def validate_structure(
    data: Dict[str, Any],
    signal: str
) -> bool:

    signal = normalize_side(
        signal
    )

    if signal == "BUY":

        return structure_steps_valid(
            data,
            "VS"
        )

    if signal == "SELL":

        return structure_steps_valid(
            data,
            "VR"
        )

    return False


# ============================================================
# STRICT ZONE VALIDATION
# ============================================================

def validate_zone(
    data: Dict[str, Any],
    signal: str
) -> bool:

    if not data.get(
        "zone_valid"
    ):

        return False

    structure = normalize_structure(
        data.get(
            "structure_direction"
        )
    )

    expected = (
        "VS"
        if signal == "BUY"
        else "VR"
    )

    if structure != expected:

        return False

    zone = zone_from_data(
        data
    )

    if zone is None:

        return False

    selected = clean_text(
        data.get(
            "selected_candle"
        ),
        ""
    ).upper()

    previous = clean_text(
        data.get(
            "previous_candle"
        ),
        ""
    ).upper()

    body = clean_text(
        data.get(
            "selected_body"
        ),
        ""
    ).upper()

    if not selected:

        return False

    if not previous:

        return False

    # The AI must explicitly state shorter body.
    shorter_words = (
        "SHORTER",
        "SMALLER",
        "کورت",
        "بچووک"
    )

    if not any(
        word in body
        for word in shorter_words
    ):

        return False

    return True


# ============================================================
# PRICE AT ZONE
# ============================================================

def validate_price_at_zone(
    data: Dict[str, Any]
) -> bool:

    return (
        data.get(
            "price_at_zone"
        )
        is True
    )


# ============================================================
# PULLBACK
# ============================================================

def validate_pullback(
    data: Dict[str, Any]
) -> bool:

    if data.get(
        "pullback_valid"
    ) is not True:

        return False

    evidence = clean_text(
        data.get(
            "pullback_evidence"
        ),
        ""
    )

    if not evidence:

        return False

    return True


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


def confirmation_name(
    value: Any
) -> str:

    text = clean_text(
        value,
        ""
    ).upper()

    for name in (
        "I.VR",
        "I.VS",
        "RBS",
        "SBR",
        "SRR",
        "RSS",
        "PO2"
    ):

        if name in text:

            return name

    return ""


def validate_confirmation(
    data: Dict[str, Any],
    signal: str
) -> bool:

    name = confirmation_name(
        data.get(
            "confirmation"
        )
    )

    if not name:

        return False

    if signal == "BUY":

        if name not in BUY_CONFIRMATIONS:

            return False

    elif signal == "SELL":

        if name not in SELL_CONFIRMATIONS:

            return False

    else:

        return False

    if data.get(
        "confirmation_valid"
    ) is not True:

        return False

    if data.get(
        "confirmation_after_retest"
    ) is not True:

        return False

    evidence = clean_text(
        data.get(
            "confirmation_evidence"
        ),
        ""
    )

    if not evidence:

        return False

    return True


# ============================================================
# HTF / LTF AGREEMENT
# ============================================================

def validate_htf_ltf(
    data: Dict[str, Any],
    signal: str
) -> bool:

    htf = clean_text(
        data.get(
            "htf_direction"
        ),
        "UNKNOWN"
    ).upper()

    ltf = clean_text(
        data.get(
            "ltf_direction"
        ),
        "UNKNOWN"
    ).upper()

    if signal == "BUY":

        if htf != "BULLISH":

            return False

        if ltf != "BULLISH":

            return False

    elif signal == "SELL":

        if htf != "BEARISH":

            return False

        if ltf != "BEARISH":

            return False

    else:

        return False

    return (
        data.get(
            "htf_ltf_agreement"
        )
        is True
    )


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_rr(
    data: Dict[str, Any],
    signal: str
) -> Optional[float]:

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

    if None in (
        entry,
        sl,
        tp1
    ):

        return None

    if signal == "BUY":

        risk = entry - sl
        reward = tp1 - entry

    elif signal == "SELL":

        risk = sl - entry
        reward = entry - tp1

    else:

        return None

    if risk <= 0:

        return None

    if reward <= 0:

        return None

    return reward / risk


def validate_trade_levels(
    data: Dict[str, Any],
    signal: str
) -> bool:

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

    if None in (
        entry,
        sl,
        tp1
    ):

        return False

    if data.get(
        "entry_valid"
    ) is not True:

        return False

    if data.get(
        "sl_valid"
    ) is not True:

        return False

    if data.get(
        "tp_valid"
    ) is not True:

        return False

    if signal == "BUY":

        return (
            sl < entry < tp1
        )

    if signal == "SELL":

        return (
            tp1 < entry < sl
        )

    return False


# ============================================================
# REJECTION
# ============================================================

def validate_rejection(
    data: Dict[str, Any]
) -> bool:

    return (
        data.get(
            "rejection_present"
        )
        is not True
    )


# ============================================================
# DETERMINISTIC CHECKS
# ============================================================

def validation_checks(
    data: Dict[str, Any],
    signal: str
) -> Dict[str, bool]:

    structure = validate_structure(
        data,
        signal
    )

    zone = validate_zone(
        data,
        signal
    )

    price_zone = validate_price_at_zone(
        data
    )

    pullback = validate_pullback(
        data
    )

    confirmation = validate_confirmation(
        data,
        signal
    )

    htf_ltf = validate_htf_ltf(
        data,
        signal
    )

    levels = validate_trade_levels(
        data,
        signal
    )

    rr = calculate_rr(
        data,
        signal
    )

    rr_valid = (
        rr is not None
        and rr >= MIN_RR
    )

    no_rejection = validate_rejection(
        data
    )

    return {
        "structure": structure,
        "zone": zone,
        "price_at_zone": price_zone,
        "pullback": pullback,
        "confirmation": confirmation,
        "htf_ltf": htf_ltf,
        "levels": levels,
        "rr": rr_valid,
        "no_rejection": no_rejection
    }


# ============================================================
# SCORE
# ============================================================

def deterministic_score(
    checks: Dict[str, bool]
) -> int:

    weights = {
        "structure": 20,
        "zone": 15,
        "price_at_zone": 10,
        "pullback": 10,
        "confirmation": 15,
        "htf_ltf": 10,
        "levels": 5,
        "rr": 10,
        "no_rejection": 5
    }

    score = 0

    for key, weight in weights.items():

        if checks.get(
            key,
            False
        ):

            score += weight

    return min(
        score,
        100
    )


def deterministic_confidence(
    checks: Dict[str, bool],
    score: int,
    rr: Optional[float]
) -> int:

    confidence = score

    if rr is not None:

        if rr >= 3.0:

            confidence += 5

        elif rr >= 2.5:

            confidence += 3

        elif rr >= 2.0:

            confidence += 1

    if not checks.get(
        "no_rejection",
        False
    ):

        confidence -= 20

    return max(
        0,
        min(
            100,
            confidence
        )
    )


# ============================================================
# REASON GENERATOR
# ============================================================

def missing_reasons(
    data: Dict[str, Any],
    signal: str,
    checks: Dict[str, bool]
) -> List[str]:

    reasons = []

    if not checks["structure"]:

        if signal == "BUY":

            reasons.append(
                "VS ـی تەواو بە 5 step پشتڕاست نەکراوەتەوە."
            )

        else:

            reasons.append(
                "VR ـی تەواو بە 5 step پشتڕاست نەکراوەتەوە."
            )

    if not checks["zone"]:

        reasons.append(
            "Zone بە یاسای shorter body پشتڕاست نەکراوەتەوە."
        )

    if not checks["price_at_zone"]:

        reasons.append(
            "نرخ هێشتا بە ڕوونی لە Zone ـەکە نییە."
        )

    if not checks["pullback"]:

        reasons.append(
            "Pullback / Retest هێشتا تەواو نییە."
        )

    if not checks["confirmation"]:

        if signal == "BUY":

            reasons.append(
                "Confirmation ـی BUY "
                "(RBS / SRR / I.VR / PO2) نییە."
            )

        else:

            reasons.append(
                "Confirmation ـی SELL "
                "(SBR / RSS / I.VS / PO2) نییە."
            )

    if not checks["htf_ltf"]:

        reasons.append(
            "HTF و LTF بە یەک ئاراستەی ڕوون نین."
        )

    if not checks["levels"]:

        reasons.append(
            "Entry / SL / TP لە شوێنی لۆجیکی نین."
        )

    if not checks["rr"]:

        reasons.append(
            "RR کەمترە لە 1:2 یان ناتوانرێت حساب بکرێت."
        )

    if not checks["no_rejection"]:

        reasons.append(
            "Strong rejection / fake breakout هەیە."
        )

    return reasons


# ============================================================
# WAIT NEXT ACTION
# ============================================================

def next_action(
    data: Dict[str, Any],
    signal: str,
    checks: Dict[str, bool]
) -> str:

    zone = zone_from_data(
        data
    )

    zone_text = "N/A"

    if zone:

        zone_text = (
            f"{zone[0]:.2f} - {zone[1]:.2f}"
        )

    if not checks["structure"]:

        if signal == "BUY":

            return (
                "چاوەڕێی VS ـی تەواو بکە: "
                "Support → Up → NEW Resistance → "
                "Up → Break هەمان NEW Resistance."
            )

        if signal == "SELL":

            return (
                "چاوەڕێی VR ـی تەواو بکە: "
                "Resistance → Down → NEW Support → "
                "Down → Break هەمان NEW Support."
            )

        return (
            "چاوەڕێی structure ـێکی ڕوونی VS یان VR بکە."
        )

    if not checks["zone"]:

        return (
            "Zone بە یاسای shorter body دروست بکە؛ "
            "formation candle و previous candle دەبێت ڕوون بن."
        )

    if not checks["price_at_zone"]:

        return (
            f"چاوەڕێ بکە نرخ بگەڕێتەوە بۆ Zone: "
            f"{zone_text}"
        )

    if not checks["pullback"]:

        return (
            f"نرخ لە Zone ـە، بەڵام Pullback / Retest "
            f"هێشتا پشتڕاست نەکراوەتەوە.\n"
            f"📍 Zone: {zone_text}"
        )

    if not checks["confirmation"]:

        if signal == "BUY":

            return (
                "Retest تەواوە؛ چاوەڕێی "
                "RBS / SRR / I.VR / PO2 ـی تەواو بکە."
            )

        if signal == "SELL":

            return (
                "Retest تەواوە؛ چاوەڕێی "
                "SBR / RSS / I.VS / PO2 ـی تەواو بکە."
            )

    if not checks["htf_ltf"]:

        return (
            "چاوەڕێ بکە HTF و LTF لە یەک ئاراستەدا "
            "کۆببنەوە."
        )

    if not checks["levels"]:

        return (
            "چاوەڕێی Entry / SL / TP ـی لۆجیکی بکە."
        )

    if not checks["rr"]:

        return (
            "چاوەڕێی setup ـێک بکە کە RR ـی "
            "لانیکەم 1:2 هەبێت."
        )

    if not checks["no_rejection"]:

        return (
            "چاوەڕێ بکە rejection / fake breakout "
            "نەبێت."
        )

    return (
        "هەموو مەرجەکان هێشتا کۆنەبوونەتەوە."
    )


# ============================================================
# BUILD PATH VALIDATION
# ============================================================

def build_path_validation(
    data: Dict[str, Any],
    signal: str
) -> Dict[str, Any]:

    checks = validation_checks(
        data,
        signal
    )

    score = deterministic_score(
        checks
    )

    rr = calculate_rr(
        data,
        signal
    )

    confidence = deterministic_confidence(
        checks,
        score,
        rr
    )

    reasons = missing_reasons(
        data,
        signal,
        checks
    )

    mandatory = all(
        checks.values()
    )

    valid = (
        mandatory
        and score >= MIN_STRONG_SCORE
        and confidence >= MIN_STRONG_CONFIDENCE
    )

    return {
        "signal": signal,
        "checks": checks,
        "score": score,
        "confidence": confidence,
        "rr": rr,
        "reasons": reasons,
        "valid": valid
    }


# ============================================================
# DETERMINE SUPPORTED DIRECTION
# ============================================================

def determine_direction(
    data: Dict[str, Any]
) -> str:

    structure = normalize_structure(
        data.get(
            "structure_direction"
        )
    )

    if structure == "VS":

        return "BUY"

    if structure == "VR":

        return "SELL"

    return "WAIT"


# ============================================================
# FINAL ENGINE
# ============================================================

def run_final_engine(
    raw_data: Dict[str, Any]
) -> Dict[str, Any]:

    data = normalize_result(
        raw_data
    )

    structure_direction = normalize_structure(
        data.get(
            "structure_direction"
        )
    )

    # --------------------------------------------------------
    # NO STRUCTURE
    # --------------------------------------------------------

    if structure_direction == "NONE":

        data["signal"] = "WAIT"

        data["entry"] = "N/A"
        data["sl"] = "N/A"
        data["tp1"] = "N/A"
        data["tp2"] = "N/A"
        data["tp3"] = "N/A"
        data["rr"] = "N/A"

        data["score"] = 0
        data["confidence"] = 0

        data["rejection_reason"] = (
            "VS یان VR ـی تەواو نەدۆزرایەوە."
        )

        data["wait_for"] = (
            "چاوەڕێی VS یان VR ـی تەواو بکە."
        )

        return data

    # --------------------------------------------------------
    # STRUCTURE → SIDE
    # --------------------------------------------------------

    signal = determine_direction(
        data
    )

    validation = build_path_validation(
        data,
        signal
    )

    # --------------------------------------------------------
    # VALID STRONG SIGNAL
    # --------------------------------------------------------

    if validation["valid"]:

        data["signal"] = signal

        data["score"] = validation[
            "score"
        ]

        data["confidence"] = validation[
            "confidence"
        ]

        rr = validation["rr"]

        data["rr"] = (
            f"1:{rr:.2f}"
            if rr is not None
            else "N/A"
        )

        data["rejection_reason"] = (
            "هیچ rejection ـێکی بەهێز نییە."
        )

        data["wait_for"] = "N/A"

        return data

    # --------------------------------------------------------
    # WAIT
    # --------------------------------------------------------

    data["signal"] = "WAIT"

    data["score"] = validation[
        "score"
    ]

    data["confidence"] = validation[
        "confidence"
    ]

    data["entry"] = "N/A"
    data["sl"] = "N/A"
    data["tp1"] = "N/A"
    data["tp2"] = "N/A"
    data["tp3"] = "N/A"
    data["rr"] = "N/A"

    reasons = validation[
        "reasons"
    ]

    if reasons:

        data["rejection_reason"] = (
            "\n".join(
                f"❌ {reason}"
                for reason in reasons
            )
        )

    else:

        data["rejection_reason"] = (
            "هەموو مەرجەکانی Strong Signal "
            "کۆنەبوونەتەوە."
        )

    checks = validation[
        "checks"
    ]

    data["wait_for"] = next_action(
        data,
        signal,
        checks
    )

    return data


# ============================================================
# GEMINI IMAGE PART
# ============================================================

def make_image_part(
    image_bytes: bytes,
    mime_type: str = "image/jpeg"
):

    return types.Part.from_bytes(
        data=image_bytes,
        mime_type=mime_type
    )


# ============================================================
# GEMINI CALL
# ============================================================

def call_gemini_model(
    model_name: str,
    zone_image: bytes,
    confirmation_image: bytes
) -> str:

    prompt = """
Analyze these TWO XAUUSD screenshots.

IMAGE 1 = HTF H1/H4.
IMAGE 2 = LTF M1/M5.

Follow the SYSTEM PROMPT exactly.

DO NOT GUESS.

You must identify:

VS or VR
→ Zone
→ Price at Zone
→ Pullback/Retest
→ Confirmation after Retest
→ HTF/LTF agreement
→ Entry/SL/TP
→ RR

If any evidence is unclear:
set the related boolean to false.

If structure is incomplete:
structure_valid = false.

If Zone is unclear:
zone_valid = false.

If price has not returned to Zone:
price_at_zone = false.

If confirmation happened before retest:
confirmation_after_retest = false.

If HTF/LTF are not explicitly aligned:
htf_ltf_agreement = false.

Return JSON ONLY.
"""

    image1 = make_image_part(
        zone_image
    )

    image2 = make_image_part(
        confirmation_image
    )

    # --------------------------------------------------------
    # Primary config
    # --------------------------------------------------------

    config = types.GenerateContentConfig(
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=GEMINI_SCHEMA
    )

    try:

        response = gemini.models.generate_content(
            model=model_name,
            contents=[
                SYSTEM_PROMPT,
                prompt,
                image1,
                image2
            ],
            config=config
        )

    except TypeError:

        # SDK compatibility fallback.
        response = gemini.models.generate_content(
            model=model_name,
            contents=[
                SYSTEM_PROMPT,
                prompt,
                image1,
                image2
            ],
            config={
                "temperature": 0.1,
                "response_mime_type":
                    "application/json",
                "response_schema":
                    GEMINI_SCHEMA
            }
        )

    text = getattr(
        response,
        "text",
        None
    )

    if not text:

        raise RuntimeError(
            "Gemini returned empty response."
        )

    return text


# ============================================================
# GEMINI RETRY
# ============================================================

def retryable_gemini_error(
    exc: Exception
) -> bool:

    text = str(
        exc
    ).lower()

    words = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "timeout",
        "temporarily",
        "unavailable",
        "resource exhausted",
        "rate limit"
    )

    return any(
        word in text
        for word in words
    )


def analyze_two_charts(
    zone_image: bytes,
    confirmation_image: bytes
) -> Dict[str, Any]:

    models = []

    if GEMINI_MODEL:

        models.append(
            GEMINI_MODEL
        )

    if (
        GEMINI_FALLBACK_MODEL
        and GEMINI_FALLBACK_MODEL
        not in models
    ):

        models.append(
            GEMINI_FALLBACK_MODEL
        )

    last_error = None

    for model_name in models:

        for attempt in range(
            1,
            GEMINI_RETRIES + 1
        ):

            try:

                logger.info(
                    f"Gemini model={model_name} "
                    f"attempt={attempt}/{GEMINI_RETRIES}"
                )

                raw = call_gemini_model(
                    model_name,
                    zone_image,
                    confirmation_image
                )

                parsed_json = clean_json(
                    raw
                )

                parsed = json.loads(
                    parsed_json
                )

                normalized = normalize_result(
                    parsed
                )

                final_result = run_final_engine(
                    normalized
                )

                return final_result

            except Exception as exc:

                last_error = exc

                logger.exception(
                    "Gemini analysis failed."
                )

                if (
                    attempt < GEMINI_RETRIES
                    and retryable_gemini_error(
                        exc
                    )
                ):

                    time.sleep(
                        GEMINI_RETRY_DELAY
                        * attempt
                    )

                    continue

                break

    raise RuntimeError(
        f"Gemini analysis failed: {last_error}"
    )


# ============================================================
# TELEGRAM PHOTO
# ============================================================

def download_telegram_photo(
    message: Dict[str, Any]
) -> Optional[bytes]:

    photos = message.get(
        "photo"
    )

    if not photos:

        return None

    largest = photos[-1]

    file_id = largest.get(
        "file_id"
    )

    if not file_id:

        return None

    file_info = telegram.get_file(
        file_id
    )

    file_path = file_info.get(
        "file_path"
    )

    if not file_path:

        raise RuntimeError(
            "Telegram file_path missing."
        )

    return telegram.download_file(
        file_path
    )


# ============================================================
# FORMAT CHECKS
# ============================================================

def format_checks(
    data: Dict[str, Any]
) -> str:

    signal = normalize_side(
        data.get(
            "signal"
        )
    )

    if signal not in (
        "BUY",
        "SELL"
    ):

        direction = determine_direction(
            data
        )

        if direction in (
            "BUY",
            "SELL"
        ):

            signal = direction

    if signal not in (
        "BUY",
        "SELL"
    ):

        return (
            "❌ Strong validation path نییە."
        )

    checks = validation_checks(
        data,
        signal
    )

    names = [
        (
            "SNRZ Structure",
            checks["structure"]
        ),
        (
            "Zone",
            checks["zone"]
        ),
        (
            "Price at Zone",
            checks["price_at_zone"]
        ),
        (
            "Pullback / Retest",
            checks["pullback"]
        ),
        (
            "Confirmation",
            checks["confirmation"]
        ),
        (
            "HTF / LTF",
            checks["htf_ltf"]
        ),
        (
            "Entry / SL / TP",
            checks["levels"]
        ),
        (
            "RR >= 1:2",
            checks["rr"]
        ),
        (
            "No Rejection",
            checks["no_rejection"]
        )
    ]

    return "\n".join(
        f"{'✅' if value else '❌'} {name}"
        for name, value in names
    )


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(
    data: Dict[str, Any]
) -> str:

    signal = normalize_side(
        data.get(
            "signal"
        )
    )

    if signal == "BUY":

        title = "🟢 STRONG BUY SIGNAL"

    elif signal == "SELL":

        title = "🔴 STRONG SELL SIGNAL"

    else:

        title = "🟡 WAIT"

    score = safe_float(
        data.get(
            "score"
        )
    )

    confidence = safe_float(
        data.get(
            "confidence"
        )
    )

    score_text = (
        f"{score:.0f}/100"
        if score is not None
        else "0/100"
    )

    confidence_text = (
        f"{confidence:.0f}%"
        if confidence is not None
        else "0%"
    )

    zone = zone_from_data(
        data
    )

    if zone:

        zone_price = (
            f"{zone[0]:.2f} - {zone[1]:.2f}"
        )

    else:

        zone_price = clean_text(
            data.get(
                "zone_price"
            ),
            "N/A"
        )

    text = f"""
{title}
━━━━━━━━━━━━━━━━━━

🥇 XAUUSD

📊 Score:
{score_text}

💪 Confidence:
{confidence_text}

📈 Trend:
{clean_text(data.get("trend"), "N/A")}

🧠 Setup:
{clean_text(data.get("setup"), "N/A")}

━━━━━━━━━━━━━━━━━━

🧩 Structure:
{clean_text(data.get("structure_direction"), "NONE")}

🟦 Zone:
{clean_text(data.get("zone"), "N/A")}

📍 Zone Price:
{zone_price}

━━━━━━━━━━━━━━━━━━

🟢 VS:
{clean_text(data.get("vs_detected"), "N/A")}

🔴 VR:
{clean_text(data.get("vr_detected"), "N/A")}

🔎 Confirmation:
{clean_text(data.get("confirmation"), "N/A")}

📊 HTF:
{clean_text(data.get("htf_direction"), "UNKNOWN")}

📊 LTF:
{clean_text(data.get("ltf_direction"), "UNKNOWN")}
""".strip()

    # --------------------------------------------------------
    # Strong Signal
    # --------------------------------------------------------

    if signal in (
        "BUY",
        "SELL"
    ):

        text += f"""

━━━━━━━━━━━━━━━━━━

🎯 Entry:
{clean_text(data.get("entry"), "N/A")}

🛑 SL:
{clean_text(data.get("sl"), "N/A")}

🥇 TP1:
{clean_text(data.get("tp1"), "N/A")}

🥈 TP2:
{clean_text(data.get("tp2"), "N/A")}

🥉 TP3:
{clean_text(data.get("tp3"), "N/A")}

📊 R:R:
{clean_text(data.get("rr"), "N/A")}
"""

    # --------------------------------------------------------
    # Analysis
    # --------------------------------------------------------

    text += f"""

━━━━━━━━━━━━━━━━━━

🔎 هۆکاری شیکردنەوە:

{clean_text(data.get("reasoning"), "N/A")}

━━━━━━━━━━━━━━━━━━

✅ Final Checks:

{format_checks(data)}
"""

    # --------------------------------------------------------
    # WAIT
    # --------------------------------------------------------

    if signal == "WAIT":

        rejection = clean_text(
            data.get(
                "rejection_reason"
            ),
            "هەموو مەرجەکانی Strong Signal تەواو نەبوون."
        )

        wait_for = clean_text(
            data.get(
                "wait_for"
            ),
            "چاوەڕێی setup ـێکی تەواو بکە."
        )

        text += f"""

━━━━━━━━━━━━━━━━━━

🚫 هۆکاری WAIT:

{rejection}

━━━━━━━━━━━━━━━━━━

👀 چاوەڕێی چی بکەین؟

{wait_for}

━━━━━━━━━━━━━━━━━━

⚠️ هیچ Entry ـێک تا تەواوبوونی
هەموو مەرجە سەرەکییەکان نابێت.
"""

    else:

        text += """

━━━━━━━━━━━━━━━━━━

🔥 STRONG SNRZ SETUP

هەموو مەرجە سەرەکییەکانی
SNRZ validation تێپەڕێنراون.

⚠️ ئەمە شیکردنەوەی تەکنیکییە؛
دڵنیایی بە قازانج نادات.
"""

    return text.strip()


# ============================================================
# START / HELP
# ============================================================

START_MESSAGE = """
🥇 Gold Chart Analyzer PRO V7

🧠 SNRZ Structure Engine

━━━━━━━━━━━━━━━━━━

سیستەم:

VS / VR
↓
Zone
↓
Pullback / Retest
↓
M1/M5 Confirmation
↓
HTF/LTF Agreement
↓
RR Validation
↓
BUY / SELL / WAIT

━━━━━━━━━━━━━━━━━━

📸 هەنگاوی 1:
H1 یان H4 ـی XAUUSD بنێرە.

📸 هەنگاوی 2:
M1 یان M5 بنێرە.

ئەگەر مەرجەکان تەواو نەبن:

🟡 WAIT

بۆتەکە دەڵێت:

❌ بۆچی WAIT ـە
📍 Zone Price
👀 چاوەڕێی چی بکەیت

━━━━━━━━━━━━━━━━━━

/reset
/help
""".strip()


HELP_MESSAGE = """
📚 Gold Chart Analyzer PRO V7

━━━━━━━━━━━━━━━━━━
🧠 SNRZ
━━━━━━━━━━━━━━━━━━

🟢 VS:

Support
→ Up
→ NEW Resistance
→ Up
→ Break same NEW Resistance

🔴 VR:

Resistance
→ Down
→ NEW Support
→ Down
→ Break same NEW Support

━━━━━━━━━━━━━━━━━━
🟦 ZONE
━━━━━━━━━━━━━━━━━━

Formation candle
+
Immediately previous candle

→ Compare BODY
→ Shorter BODY wins
→ Full HIGH-to-LOW = Zone

━━━━━━━━━━━━━━━━━━
🔄 SEQUENCE
━━━━━━━━━━━━━━━━━━

VS/VR
→ Zone
→ Retest
→ Confirmation
→ Entry

Confirmation BEFORE Retest:
❌ INVALID

━━━━━━━━━━━━━━━━━━
🟢 BUY
━━━━━━━━━━━━━━━━━━

RBS
SRR
I.VR
PO2

━━━━━━━━━━━━━━━━━━
🔴 SELL
━━━━━━━━━━━━━━━━━━

SBR
RSS
I.VS
PO2

━━━━━━━━━━━━━━━━━━
🔥 STRONG
━━━━━━━━━━━━━━━━━━

Score >= 80
Confidence >= 80%
RR >= 1:2

Valid:
VS/VR
Zone
Price at Zone
Pullback
Confirmation
HTF/LTF
Entry/SL/TP
No rejection

Otherwise:

🟡 WAIT

━━━━━━━━━━━━━━━━━━

/reset
""".strip()


# ============================================================
# MESSAGE HANDLER
# ============================================================

def handle_message(
    message: Dict[str, Any]
):

    chat_id = (
        message.get(
            "chat",
            {}
        ).get(
            "id"
        )
    )

    if not chat_id:

        return

    user_id = (
        message.get(
            "from",
            {}
        ).get(
            "id"
        )
    )

    text = clean_text(
        message.get(
            "text"
        ),
        ""
    ).strip()

    # --------------------------------------------------------
    # Admin
    # --------------------------------------------------------

    if is_admin(
        user_id
    ):

        if handle_admin_command(
            message,
            chat_id,
            text
        ):

            return

    # --------------------------------------------------------
    # Access
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    if text == "/start":

        reset_session(
            chat_id
        )

        get_session(
            chat_id
        )

        telegram.send_message(
            chat_id,
            START_MESSAGE
        )

        return

    # --------------------------------------------------------
    # HELP
    # --------------------------------------------------------

    if text == "/help":

        telegram.send_message(
            chat_id,
            HELP_MESSAGE
        )

        return

    # --------------------------------------------------------
    # RESET
    # --------------------------------------------------------

    if text == "/reset":

        reset_session(
            chat_id
        )

        telegram.send_message(
            chat_id,
            """
♻️ Session reset کرا.

📸 ئێستا H1 یان H4 ـی XAUUSD بنێرە.
""".strip()
        )

        return

    # --------------------------------------------------------
    # PHOTO
    # --------------------------------------------------------

    photo = download_telegram_photo(
        message
    )

    if photo is not None:

        session = get_session(
            chat_id
        )

        # ----------------------------------------------------
        # FIRST PHOTO
        # ----------------------------------------------------

        if session.get(
            "zone_image"
        ) is None:

            session[
                "zone_image"
            ] = photo

            telegram.send_message(
                chat_id,
                """
✅ H1/H4 وەرگیرا.

🧠 ئێستا HTF ـەکە شیکردنەوە دەکرێت:

VS / VR
↓
Zone

━━━━━━━━━━━━━━━━━━

📸 ئێستا M1 یان M5 بنێرە
بۆ Pullback / Retest + Confirmation.
""".strip()
            )

            return

        # ----------------------------------------------------
        # SECOND PHOTO
        # ----------------------------------------------------

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

🧠 V7 Engine:

VS/VR
→ Zone
→ Retest
→ Confirmation
→ HTF/LTF
→ RR
→ Final Validation

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

                response_text = format_signal(
                    result
                )

                telegram.send_message(
                    chat_id,
                    response_text
                )

            except Exception as exc:

                logger.exception(
                    "Analysis failed."
                )

                telegram.send_message(
                    chat_id,
                    f"""
❌ شیکردنەوەکە نەکرا.

هۆکار:
{exc}

تکایە:

/reset

پاشان chart ـەکان دووبارە بنێرە.
""".strip()
                )

            finally:

                reset_session(
                    chat_id
                )

            return

    # --------------------------------------------------------
    # OTHER TEXT
    # --------------------------------------------------------

    telegram.send_message(
        chat_id,
        """
تکایە chart بنێرە:

1️⃣ H1 یان H4
2️⃣ M1 یان M5

یان:

/help
/reset
""".strip()
    )


# ============================================================
# UPDATE HANDLER
# ============================================================

def handle_update(
    update: Dict[str, Any]
):

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
                "Callback handling error."
            )

        return

    message = update.get(
        "message"
    )

    if not message:

        return

    try:

        handle_message(
            message
        )

    except TelegramAPIError:

        logger.exception(
            "Telegram API error."
        )

    except Exception:

        logger.exception(
            "Message handling error."
        )


# ============================================================
# TELEGRAM INITIALIZATION
# ============================================================

def initialize_telegram():

    logger.info(
        "Connecting to Telegram..."
    )

    me = telegram.get_me()

    logger.info(
        f"Telegram connected: "
        f"@{me.get('username', 'unknown')}"
    )

    telegram.delete_webhook(
        drop_pending_updates=False
    )

    logger.info(
        "Webhook removed. Long polling ready."
    )


# ============================================================
# SIGNAL HANDLERS
# ============================================================

RUNNING = True


def stop_bot(
    signum,
    frame
):

    global RUNNING

    logger.info(
        f"Shutdown signal received: {signum}"
    )

    RUNNING = False


signal.signal(
    signal.SIGINT,
    stop_bot
)

signal.signal(
    signal.SIGTERM,
    stop_bot
)


# ============================================================
# MAIN RUN
# ============================================================

def run():

    logger.info(
        "=================================================="
    )

    logger.info(
        "Gold Chart Analyzer PRO V7 starting..."
    )

    logger.info(
        f"Gemini model: {GEMINI_MODEL}"
    )

    logger.info(
        f"Gemini fallback: {GEMINI_FALLBACK_MODEL}"
    )

    logger.info(
        f"Admin ID: {ADMIN_USER_ID}"
    )

    logger.info(
        f"Allowed users: {len(ALLOWED_USER_IDS)}"
    )

    logger.info(
        f"Minimum score: {MIN_STRONG_SCORE}"
    )

    logger.info(
        f"Minimum confidence: {MIN_STRONG_CONFIDENCE}%"
    )

    logger.info(
        f"Minimum RR: 1:{MIN_RR}"
    )

    logger.info(
        "=================================================="
    )

    # --------------------------------------------------------
    # Initialize Telegram
    # --------------------------------------------------------

    while RUNNING:

        try:

            initialize_telegram()

            break

        except TelegramAPIError as exc:

            logger.error(
                f"Telegram initialization failed: {exc}"
            )

            time.sleep(
                TELEGRAM_RETRY_DELAY
            )

        except Exception:

            logger.exception(
                "Initialization error."
            )

            time.sleep(
                TELEGRAM_RETRY_DELAY
            )

    # --------------------------------------------------------
    # Long polling
    # --------------------------------------------------------

    offset = None

    while RUNNING:

        try:

            cleanup_sessions()

            updates = telegram.get_updates(
                offset=offset,
                timeout=TELEGRAM_POLL_TIMEOUT
            )

            if not updates:

                continue

            for update in updates:

                if not RUNNING:

                    break

                update_id = update.get(
                    "update_id"
                )

                if update_id is not None:

                    offset = (
                        update_id + 1
                    )

                handle_update(
                    update
                )

        except TelegramAPIError as exc:

            text = str(
                exc
            ).lower()

            # ------------------------------------------------
            # 409 Conflict
            # ------------------------------------------------

            if (
                exc.status_code == 409
                or "409" in text
                or "conflict" in text
            ):

                logger.error(
                    "=================================================="
                )

                logger.error(
                    "TELEGRAM 409 CONFLICT"
                )

                logger.error(
                    "Another process is polling this bot token."
                )

                logger.error(
                    "Only ONE running instance is allowed."
                )

                logger.error(
                    "Waiting 10 seconds..."
                )

                logger.error(
                    "=================================================="
                )

                time.sleep(
                    10
                )

            else:

                logger.exception(
                    "Telegram polling error."
                )

                time.sleep(
                    TELEGRAM_RETRY_DELAY
                )

        except KeyboardInterrupt:

            break

        except Exception:

            logger.exception(
                "Unexpected polling error."
            )

            time.sleep(
                TELEGRAM_RETRY_DELAY
            )

    logger.info(
        "Gold Chart Analyzer PRO V7 stopped."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    run()
