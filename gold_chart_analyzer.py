````python
# ============================================================
# gold_chart_analyzer.py
# ============================================================
# GOLD CHART ANALYZER PRO V6
#
# SNRZ ENGINE
# ------------------------------------------------------------
# Flow:
#
# H1/H4
#   ↓
# VS / VR
#   ↓
# Zone
#   ↓
# Pullback / Retest
#   ↓
# M1/M5 Confirmation
#   ↓
# Deterministic Validation
#   ↓
# BUY / SELL / WAIT
#
# Gemini = Visual Analyst
# Python  = Final Validator
# ============================================================

import os
import json
import time
import logging
import requests
import base64
import re
import secrets
from typing import Any, Dict, Optional, List, Tuple

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

# Can be changed from environment without editing code.
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
).strip()

# Optional fallback model.
GEMINI_FALLBACK_MODEL = os.getenv(
    "GEMINI_FALLBACK_MODEL",
    ""
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
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(
    "GoldChartAnalyzerV6"
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
# TELEGRAM EXCEPTIONS
# ============================================================

class TelegramAPIError(Exception):
    """
    Telegram API error.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None
    ):
        super().__init__(message)
        self.status_code = status_code


# ============================================================
# TELEGRAM API
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
    # Generic API call
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

        return result.get(
            "result"
        )

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
    # editMessageReplyMarkup
    # --------------------------------------------------------

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: Optional[Dict] = None
    ):

        payload = {
            "chat_id": chat_id,
            "message_id": message_id
        }

        if reply_markup is not None:
            payload["reply_markup"] = (
                reply_markup
            )

        return self.call(
            "editMessageReplyMarkup",
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
    # Download Telegram file
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
# USER ACCESS DATABASE
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
                    list(
                        ALLOWED_USER_IDS
                    )
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

PENDING_ACCESS_REQUESTS: Dict[int, Dict[str, Any]] = {}

ACCESS_CODES: Dict[str, int] = {}


# ============================================================
# USER SESSIONS
# ============================================================

USER_SESSIONS: Dict[int, Dict[str, Any]] = {}


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

    expired = []

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

            expired.append(
                chat_id
            )

    for chat_id in expired:

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

    # Existing request
    if user_id in PENDING_ACCESS_REQUESTS:

        request = PENDING_ACCESS_REQUESTS[
            user_id
        ]

        code = request.get(
            "code",
            "N/A"
        )

        telegram.send_message(
            chat_id,
            f"""
⏳ داواکارییەکەت پێشتر نێردراوە.

🔑 Access Code:
{code}

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

    # User
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

    # Admin
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

👇 بڕیار بدە:
"""

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text":
                        "✅ APPROVE",
                    "callback_data":
                        f"approve:{code}"
                },
                {
                    "text":
                        "❌ REJECT",
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
            "Could not notify admin about access request."
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
            "⛔ تەنها Admin دەتوانێت ئەم کارە بکات."
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
            "⚠️ Access Code نییە یان بەکارهاتووە."
        )

        return

    request = PENDING_ACCESS_REQUESTS.get(
        user_id
    )

    if not request:

        telegram.answer_callback_query(
            callback_id,
            "⚠️ Request ـەکە پێشتر مامەڵەی لەگەڵ کراوە."
        )

        return

    # --------------------------------------------------------
    # APPROVE
    # --------------------------------------------------------

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

🥇 Gold Chart Analyzer PRO V6

🧠 SNRZ Structure Engine چالاکە.

هەنگاوی یەکەم:
📸 H1 یان H4 ـی XAUUSD بنێرە.
""".strip()
            )

        except Exception:

            logger.exception(
                "Could not notify approved user."
            )

        return

    # --------------------------------------------------------
    # REJECT
    # --------------------------------------------------------

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

بۆ بەکارهێنانی
Gold Chart Analyzer PRO
پێویستە Admin ڕێگەپێدانت پێبدات.
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

    user = message.get(
        "from",
        {}
    )

    user_id = user.get(
        "id"
    )

    if not is_admin(
        user_id
    ):
        return False

    # --------------------------------------------------------
    # ADD USER
    # --------------------------------------------------------

    if text.startswith(
        "/adduser"
    ):

        parts = text.split()

        if len(parts) != 2:

            telegram.send_message(
                chat_id,
                """
❌ بەکارهێنان:

/adduser USER_ID

نموونە:

/adduser 123456789
""".strip()
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

        # Remove pending request if exists
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

👤 User ID:
{new_user_id}

👥 کۆی بەکارهێنەرەکان:
{len(ALLOWED_USER_IDS)}
""".strip()
        )

        return True

    # --------------------------------------------------------
    # REMOVE USER
    # --------------------------------------------------------

    if text.startswith(
        "/removeuser"
    ):

        parts = text.split()

        if len(parts) != 2:

            telegram.send_message(
                chat_id,
                """
❌ بەکارهێنان:

/removeuser USER_ID
""".strip()
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
                "⛔ ناتوانیت Admin ـی خۆت بسڕیتەوە."
            )

            return True

        if remove_user_id in ALLOWED_USER_IDS:

            ALLOWED_USER_IDS.remove(
                remove_user_id
            )

            save_allowed_users()

            telegram.send_message(
                chat_id,
                f"""
✅ بەکارهێنەر سڕایەوە.

👤 User ID:
{remove_user_id}
""".strip()
            )

        else:

            telegram.send_message(
                chat_id,
                "ℹ️ ئەم User ID ـە لە لیستدا نییە."
            )

        return True

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    if text == "/users":

        users = sorted(
            ALLOWED_USER_IDS
        )

        lines = []

        for uid in users:

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
            + "\n\n"
            + f"Total: {len(users)}"
        )

        return True

    # --------------------------------------------------------
    # PENDING
    # --------------------------------------------------------

    if text == "/pending":

        if not PENDING_ACCESS_REQUESTS:

            telegram.send_message(
                chat_id,
                "📭 هیچ Access Request ـێکی چاوەڕوان نییە."
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

    if text.startswith(
        "/broadcast"
    ):

        broadcast_text = text[
            len("/broadcast"):
        ].strip()

        if not broadcast_text:

            telegram.send_message(
                chat_id,
                """
❌ پەیامەکە بنووسە.

نموونە:

/broadcast سڵاو بە هەموو بەکارهێنەرەکان
""".strip()
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

                logger.exception(
                    f"Broadcast failed for {uid}"
                )

        telegram.send_message(
            chat_id,
            f"""
📢 Broadcast تەواوبوو.

✅ نێردرا:
{success}

❌ سەرکەوتوو نەبوو:
{failed}
""".strip()
        )

        return True

    # --------------------------------------------------------
    # ADMIN HELP
    # --------------------------------------------------------

    if text == "/admin":

        telegram.send_message(
            chat_id,
            """
👑 ADMIN PANEL
━━━━━━━━━━━━━━━━━━

➕ زیادکردنی User:

/adduser USER_ID

➖ سڕینەوەی User:

/removeuser USER_ID

👥 Users:

/users

⏳ Pending:

/pending

📢 Broadcast:

/broadcast MESSAGE

━━━━━━━━━━━━━━━━━━

🔐 Access Request:
Approve / Reject
تەنها Admin دەتوانێت.
""".strip()
        )

        return True

    return False


# ============================================================
# SNRZ SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = r"""
You are an ELITE XAUUSD SNRZ STRUCTURE ANALYST.

Your job is NOT to guess a trade.

Your job is to identify STRUCTURE and provide visual evidence.

Python will perform the final validation.

============================================================
TIMEFRAMES
============================================================

IMAGE 1:
H1 or H4 = HTF

IMAGE 2:
M1 or M5 = LTF

HTF:
Find VS / VR and Zone.

LTF:
Find Pullback / Retest and Confirmation.

============================================================
VS
============================================================

VS is valid ONLY if:

SUPPORT
→ UP
→ NEW RESISTANCE CREATED AFTER SUPPORT
→ UP AGAIN
→ BREAK THAT SAME NEW RESISTANCE

Only then:

SUPPORT = VS.

Any Resistance before the Support is irrelevant.

If the structure is incomplete:
VS = NOT VALID.

============================================================
VR
============================================================

VR is valid ONLY if:

RESISTANCE
→ DOWN
→ NEW SUPPORT CREATED AFTER RESISTANCE
→ DOWN AGAIN
→ BREAK THAT SAME NEW SUPPORT

Only then:

RESISTANCE = VR.

Any Support before the Resistance is irrelevant.

If the structure is incomplete:
VR = NOT VALID.

============================================================
ZONE
============================================================

After valid VS or VR:

1. Identify formation candle.
2. Identify immediately previous candle.
3. Compare BODY size.
4. Choose the SHORTER BODY.
5. Entire selected candle HIGH-to-LOW = Zone.

Never use only candle body.

Never use engulfing as Zone calculation.

============================================================
SEQUENCE
============================================================

VALID VS/VR
→ ZONE
→ PRICE RETURNS / RETESTS ZONE
→ CONFIRMATION
→ ENTRY

Confirmation before Retest is INVALID.

============================================================
BUY
============================================================

BUY confirmations:

RBS
SRR
I.VR
PO2

============================================================
SELL
============================================================

SELL confirmations:

SBR
RSS
I.VS
PO2

============================================================
STRONG SIGNAL
============================================================

Strong signal requires:

1. Valid VS/VR
2. Valid Zone
3. Price at/retesting Zone
4. Confirmation AFTER retest
5. HTF/LTF agreement
6. Logical Entry
7. Logical SL
8. Logical TP
9. RR >= 1:2
10. Score >= 80
11. Confidence >= 80
12. No strong rejection

If anything is missing:
WAIT.

============================================================
WAIT
============================================================

WAIT must explain exactly what is missing.

Examples:

VS exists but price is away:
"چاوەڕێ بکە نرخ بگەڕێتەوە بۆ Zone."

Price reached VS Zone but confirmation missing:
"VS بەردەستە، بەڵام چاوەڕێی RBS یان SRR یان I.VR بکە."

VR Zone reached but confirmation missing:
"VR بەردەستە، بەڵام چاوەڕێی SBR یان RSS یان I.VS بکە."

Retest missing:
"چاوەڕێی retest بکە."

RR insufficient:
"چاوەڕێی entry ـێکی باشتر بکە."

If valid Zone exists:
ALWAYS provide exact zone_price.

============================================================
IMPORTANT
============================================================

Do NOT invent prices.

Do NOT invent VS/VR.

Do NOT assume normal support = VS.

Do NOT assume normal resistance = VR.

Do NOT use one candle as proof.

Do NOT accept confirmation before retest.

============================================================
OUTPUT
============================================================

Return ONLY JSON.

Keys:

{
  "signal": "BUY | SELL | WAIT",
  "symbol": "XAUUSD",

  "setup": "...",

  "entry": "...",
  "sl": "...",
  "tp1": "...",
  "tp2": "...",
  "tp3": "...",
  "rr": "...",

  "confidence": 0,
  "score": 0,

  "zone": "...",
  "zone_price": "...",

  "htf_zones": "...",

  "vs_detected": "...",
  "vr_detected": "...",

  "confirmation": "...",

  "trend": "...",

  "reasoning": "...",

  "checks": "...",

  "rejection_reason": "...",

  "wait_for": "..."
}

All explanatory text must be Sorani Kurdish.

Technical SNRZ names remain English.

If WAIT:

entry = "N/A"
sl = "N/A"
tp1 = "N/A"
tp2 = "N/A"
tp3 = "N/A"
rr = "N/A"

wait_for must explain the next action.

============================================================
FINAL PRINCIPLE
============================================================

Do not search for a signal.

Search for STRUCTURE.

VS/VR
→ Zone
→ Pullback/Retest
→ Confirmation
→ Strong Signal Validation
→ BUY/SELL.

Otherwise WAIT.
"""


# ============================================================
# JSON HELPERS
# ============================================================

REQUIRED_KEYS = [
    "signal",
    "symbol",
    "setup",
    "entry",
    "sl",
    "tp1",
    "tp2",
    "tp3",
    "rr",
    "confidence",
    "score",
    "zone",
    "zone_price",
    "htf_zones",
    "vs_detected",
    "vr_detected",
    "confirmation",
    "trend",
    "reasoning",
    "checks",
    "rejection_reason",
    "wait_for"
]


def clean_json(
    text: str
) -> str:

    if not text:
        raise RuntimeError(
            "Gemini returned an empty response."
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


def normalize_result(
    data: Dict[str, Any]
) -> Dict[str, Any]:

    if not isinstance(
        data,
        dict
    ):
        data = {}

    result = {}

    for key in REQUIRED_KEYS:

        result[key] = data.get(
            key,
            "N/A"
        )

    # Defaults
    result["symbol"] = "XAUUSD"

    if not result["signal"]:
        result["signal"] = "WAIT"

    return result


# ============================================================
# SAFE VALUES
# ============================================================

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


def normalize_side(
    value: Any
) -> str:

    text = clean_text(
        value,
        "WAIT"
    ).upper()

    if "BUY" in text:
        return "BUY"

    if "SELL" in text:
        return "SELL"

    return "WAIT"


def yes(
    value: Any
) -> bool:

    text = clean_text(
        value,
        ""
    ).lower()

    return text in {
        "yes",
        "true",
        "valid",
        "confirmed",
        "complete",
        "complete yes",
        "بەڵێ"
    }


def no(
    value: Any
) -> bool:

    text = clean_text(
        value,
        ""
    ).lower()

    return text in {
        "no",
        "false",
        "invalid",
        "not valid",
        "incomplete",
        "نەخێر"
    }


# ============================================================
# PRICE / RR
# ============================================================

def calculate_rr(
    data: Dict[str, Any]
) -> Optional[float]:

    signal = normalize_side(
        data.get("signal")
    )

    entry = safe_float(
        data.get("entry")
    )

    sl = safe_float(
        data.get("sl")
    )

    tp1 = safe_float(
        data.get("tp1")
    )

    if None in (
        entry,
        sl,
        tp1
    ):
        return None

    if signal == "BUY":

        risk = (
            entry - sl
        )

        reward = (
            tp1 - entry
        )

    elif signal == "SELL":

        risk = (
            sl - entry
        )

        reward = (
            entry - tp1
        )

    else:

        return None

    if risk <= 0:
        return None

    if reward <= 0:
        return None

    return (
        reward / risk
    )


def direction_valid(
    data: Dict[str, Any]
) -> bool:

    signal = normalize_side(
        data.get("signal")
    )

    entry = safe_float(
        data.get("entry")
    )

    sl = safe_float(
        data.get("sl")
    )

    tp1 = safe_float(
        data.get("tp1")
    )

    if None in (
        entry,
        sl,
        tp1
    ):
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
# ZONE PARSER
# ============================================================

def parse_zone_range(
    zone_price: Any
) -> Optional[Tuple[float, float]]:

    text = clean_text(
        zone_price,
        ""
    )

    if text.upper() in {
        "",
        "N/A",
        "NONE",
        "UNKNOWN"
    }:
        return None

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

        low = min(
            a,
            b
        )

        high = max(
            a,
            b
        )

        if high <= low:
            return None

        return (
            low,
            high
        )

    except Exception:

        return None


def price_in_zone(
    price: Optional[float],
    zone_price: Any
) -> bool:

    if price is None:
        return False

    parsed = parse_zone_range(
        zone_price
    )

    if parsed is None:
        return False

    low, high = parsed

    return (
        low <= price <= high
    )


# ============================================================
# CONFIRMATION
# ============================================================

BUY_CONFIRMATIONS = (
    "RBS",
    "SRR",
    "I.VR",
    "PO2"
)

SELL_CONFIRMATIONS = (
    "SBR",
    "RSS",
    "I.VS",
    "PO2"
)


def normalize_confirmation(
    confirmation: Any
) -> str:

    return clean_text(
        confirmation,
        "N/A"
    ).upper()


def confirmation_is_valid(
    signal: str,
    confirmation: Any
) -> bool:

    signal = normalize_side(
        signal
    )

    confirmation = normalize_confirmation(
        confirmation
    )

    if signal == "BUY":

        return any(
            item in confirmation
            for item in BUY_CONFIRMATIONS
        )

    if signal == "SELL":

        return any(
            item in confirmation
            for item in SELL_CONFIRMATIONS
        )

    return False


def confirmation_after_pullback(
    data: Dict[str, Any]
) -> bool:

    confirmation = normalize_confirmation(
        data.get("confirmation")
    )

    if not confirmation_is_valid(
        data.get("signal"),
        confirmation
    ):
        return False

    # Explicit textual evidence.
    combined = (
        clean_text(
            data.get(
                "confirmation"
            ),
            ""
        )
        + " "
        + clean_text(
            data.get(
                "checks"
            ),
            ""
        )
        + " "
        + clean_text(
            data.get(
                "reasoning"
            ),
            ""
        )
    ).lower()

    # Strong negative indicators.
    invalid_words = (
        "before pullback",
        "before retest",
        "پێش pullback",
        "پێش retest",
        "pullback missing",
        "retest missing"
    )

    if any(
        word in combined
        for word in invalid_words
    ):
        return False

    # Positive indicators.
    positive_words = (
        "after pullback",
        "after retest",
        "pullback confirmed",
        "retest confirmed",
        "دوای pullback",
        "دوای retest"
    )

    return any(
        word in combined
        for word in positive_words
    )


# ============================================================
# VS / VR VALIDATION
# ============================================================

def contains_valid_vs(
    data: Dict[str, Any]
) -> bool:

    fields = [
        data.get(
            "vs_detected"
        ),
        data.get(
            "htf_zones"
        ),
        data.get(
            "zone"
        ),
        data.get(
            "reasoning"
        ),
        data.get(
            "checks"
        )
    ]

    text = " ".join(
        clean_text(
            x,
            ""
        )
        for x in fields
    ).upper()

    return (
        "VS" in text
        and not (
            "NOT VS" in text
            or "NO VS" in text
            or "VS INVALID" in text
        )
    )


def contains_valid_vr(
    data: Dict[str, Any]
) -> bool:

    fields = [
        data.get(
            "vr_detected"
        ),
        data.get(
            "htf_zones"
        ),
        data.get(
            "zone"
        ),
        data.get(
            "reasoning"
        ),
        data.get(
            "checks"
        )
    ]

    text = " ".join(
        clean_text(
            x,
            ""
        )
        for x in fields
    ).upper()

    return (
        "VR" in text
        and not (
            "NOT VR" in text
            or "NO VR" in text
            or "VR INVALID" in text
        )
    )


def validate_structure(
    data: Dict[str, Any],
    signal: str
) -> bool:

    signal = normalize_side(
        signal
    )

    if signal == "BUY":

        return contains_valid_vs(
            data
        )

    if signal == "SELL":

        return contains_valid_vr(
            data
        )

    return False


# ============================================================
# ZONE VALIDATION
# ============================================================

def zone_exists(
    data: Dict[str, Any]
) -> bool:

    zone = clean_text(
        data.get(
            "zone"
        ),
        ""
    )

    zone_price = clean_text(
        data.get(
            "zone_price"
        ),
        ""
    )

    invalid = {
        "",
        "N/A",
        "NONE",
        "UNKNOWN",
        "NOT FOUND"
    }

    if zone.upper() in invalid:
        return False

    if zone_price.upper() in invalid:
        return False

    return (
        parse_zone_range(
            zone_price
        ) is not None
    )


# ============================================================
# PULLBACK / RETEST
# ============================================================

def pullback_is_valid(
    data: Dict[str, Any]
) -> bool:

    fields = [
        data.get(
            "reasoning"
        ),
        data.get(
            "checks"
        ),
        data.get(
            "confirmation"
        ),
        data.get(
            "setup"
        )
    ]

    text = " ".join(
        clean_text(
            x,
            ""
        )
        for x in fields
    ).lower()

    positive = (
        "pullback confirmed",
        "pullback complete",
        "retest confirmed",
        "retest complete",
        "price retested",
        "price returned",
        "دوای pullback",
        "دوای retest",
        "pullback تەواو",
        "retest تەواو",
        "گەڕایەوە بۆ zone"
    )

    negative = (
        "pullback missing",
        "retest missing",
        "no pullback",
        "no retest",
        "has not retested",
        "not retested",
        "پولباک نییە",
        "retest نییە",
        "گەڕانەوەی نییە"
    )

    if any(
        phrase in text
        for phrase in negative
    ):
        return False

    return any(
        phrase in text
        for phrase in positive
    )


# ============================================================
# HTF / LTF AGREEMENT
# ============================================================

def htf_ltf_agree(
    data: Dict[str, Any],
    signal: str
) -> bool:

    signal = normalize_side(
        signal
    )

    trend = clean_text(
        data.get(
            "trend"
        ),
        ""
    ).upper()

    confirmation = normalize_confirmation(
        data.get(
            "confirmation"
        )
    )

    reasoning = clean_text(
        data.get(
            "reasoning"
        ),
        ""
    ).upper()

    combined = (
        f"{trend} "
        f"{confirmation} "
        f"{reasoning}"
    )

    if signal == "BUY":

        if "CONFLICT" in combined:
            return False

        if "BEARISH" in trend:
            return False

        return True

    if signal == "SELL":

        if "CONFLICT" in combined:
            return False

        if "BULLISH" in trend:
            return False

        return True

    return False


# ============================================================
# REJECTION DETECTION
# ============================================================

def strong_rejection_present(
    data: Dict[str, Any]
) -> bool:

    text = " ".join(
        clean_text(
            data.get(
                key
            ),
            ""
        )
        for key in (
            "reasoning",
            "checks",
            "rejection_reason"
        )
    ).lower()

    rejection_terms = (
        "strong rejection",
        "fake breakout",
        "fake break",
        "major rejection",
        "strongly rejected",
        "ڕەتکردنەوەی بەهێز",
        "فەیک breakout",
        "fake breakout"
    )

    return any(
        term in text
        for term in rejection_terms
    )


# ============================================================
# DETERMINISTIC SCORE
# ============================================================

def deterministic_score(
    data: Dict[str, Any],
    signal: str
) -> int:

    signal = normalize_side(
        signal
    )

    if signal not in (
        "BUY",
        "SELL"
    ):
        return 0

    score = 0

    # --------------------------------------------------------
    # 20 — Structure
    # --------------------------------------------------------

    if validate_structure(
        data,
        signal
    ):
        score += 20

    # --------------------------------------------------------
    # 15 — Zone
    # --------------------------------------------------------

    if zone_exists(
        data
    ):
        score += 15

    # --------------------------------------------------------
    # 15 — Pullback
    # --------------------------------------------------------

    if pullback_is_valid(
        data
    ):
        score += 15

    # --------------------------------------------------------
    # 15 — Confirmation
    # --------------------------------------------------------

    if confirmation_is_valid(
        signal,
        data.get(
            "confirmation"
        )
    ):
        score += 15

    # --------------------------------------------------------
    # 10 — HTF/LTF
    # --------------------------------------------------------

    if htf_ltf_agree(
        data,
        signal
    ):
        score += 10

    # --------------------------------------------------------
    # 10 — RR
    # --------------------------------------------------------

    rr = calculate_rr(
        data
    )

    if rr is not None and rr >= MIN_RR:
        score += 10

    # --------------------------------------------------------
    # 5 — Direction
    # --------------------------------------------------------

    if direction_valid(
        data
    ):
        score += 5

    # --------------------------------------------------------
    # 5 — No rejection
    # --------------------------------------------------------

    if not strong_rejection_present(
        data
    ):
        score += 5

    # Max = 95.
    #
    # Additional 5 points are awarded when AI's own score
    # also supports the setup.
    # --------------------------------------------------------

    ai_score = safe_float(
        data.get(
            "score"
        )
    )

    if (
        ai_score is not None
        and ai_score >= 80
    ):
        score += 5

    return min(
        score,
        100
    )


# ============================================================
# DETERMINISTIC CONFIDENCE
# ============================================================

def deterministic_confidence(
    data: Dict[str, Any],
    signal: str,
    score: int
) -> int:

    signal = normalize_side(
        signal
    )

    if signal not in (
        "BUY",
        "SELL"
    ):
        return 0

    confidence = score

    # Strong RR increases confidence.
    rr = calculate_rr(
        data
    )

    if rr is not None:

        if rr >= 3:
            confidence += 3

        elif rr >= 2.5:
            confidence += 2

    # Explicit agreement.
    if htf_ltf_agree(
        data,
        signal
    ):
        confidence += 2

    # Strong rejection reduces confidence.
    if strong_rejection_present(
        data
    ):
        confidence -= 15

    return max(
        0,
        min(
            int(confidence),
            100
        )
    )


# ============================================================
# PATH VALIDATION
# ============================================================

def build_validation(
    data: Dict[str, Any],
    signal: str
) -> Dict[str, Any]:

    signal = normalize_side(
        signal
    )

    reasons: List[str] = []

    checks = {
        "structure": False,
        "zone": False,
        "pullback": False,
        "confirmation": False,
        "confirmation_after_pullback": False,
        "htf_ltf": False,
        "direction": False,
        "rr": False,
        "no_rejection": False
    }

    if signal not in (
        "BUY",
        "SELL"
    ):

        reasons.append(
            "Signal ـی BUY/SELL نییە."
        )

        return {
            "valid": False,
            "score": 0,
            "confidence": 0,
            "checks": checks,
            "reasons": reasons
        }

    # Structure
    checks["structure"] = validate_structure(
        data,
        signal
    )

    if not checks["structure"]:

        if signal == "BUY":

            reasons.append(
                "VS ـێکی تەواو و پشتڕاستکراو نییە."
            )

        else:

            reasons.append(
                "VR ـێکی تەواو و پشتڕاستکراو نییە."
            )

    # Zone
    checks["zone"] = zone_exists(
        data
    )

    if not checks["zone"]:

        reasons.append(
            "Zone ـی دروستی HTF نییە."
        )

    # Pullback
    checks["pullback"] = pullback_is_valid(
        data
    )

    if not checks["pullback"]:

        reasons.append(
            "Pullback / Retest هێشتا پشتڕاست نەکراوەتەوە."
        )

    # Confirmation
    checks["confirmation"] = confirmation_is_valid(
        signal,
        data.get(
            "confirmation"
        )
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

    # Confirmation after pullback
    checks[
        "confirmation_after_pullback"
    ] = (
        checks["confirmation"]
        and checks["pullback"]
        and confirmation_after_pullback(
            data
        )
    )

    if (
        checks["confirmation"]
        and not checks[
            "confirmation_after_pullback"
        ]
    ):

        reasons.append(
            "Confirmation پێش Pullback/Retest ـە "
            "یان دوای Retest بە ڕوونی پشتڕاست نەکراوەتەوە."
        )

    # HTF/LTF
    checks["htf_ltf"] = htf_ltf_agree(
        data,
        signal
    )

    if not checks["htf_ltf"]:

        reasons.append(
            "HTF و LTF لەگەڵ یەکتر هاوتا نین."
        )

    # Direction
    checks["direction"] = direction_valid(
        data
    )

    if not checks["direction"]:

        reasons.append(
            "Entry / SL / TP لە ئاراستەی دروستدا نین."
        )

    # RR
    rr = calculate_rr(
        data
    )

    checks["rr"] = (
        rr is not None
        and rr >= MIN_RR
    )

    if rr is None:

        reasons.append(
            "RR بە شێوەیەکی دروست حساب ناکرێت."
        )

    elif rr < MIN_RR:

        reasons.append(
            f"RR = 1:{rr:.2f} ـە؛ "
            "کەمترە لە 1:2."
        )

    # Rejection
    checks["no_rejection"] = not strong_rejection_present(
        data
    )

    if not checks["no_rejection"]:

        reasons.append(
            "Strong rejection / fake breakout هەیە."
        )

    score = deterministic_score(
        data,
        signal
    )

    confidence = deterministic_confidence(
        data,
        signal,
        score
    )

    # Mandatory requirements
    mandatory = all(
        checks.values()
    )

    valid = (
        mandatory
        and score >= MIN_STRONG_SCORE
        and confidence >= MIN_STRONG_CONFIDENCE
    )

    if score < MIN_STRONG_SCORE:

        reasons.append(
            f"Score = {score}/100 ـە؛ "
            f"پێویستی بە {MIN_STRONG_SCORE} هەیە."
        )

    if confidence < MIN_STRONG_CONFIDENCE:

        reasons.append(
            f"Confidence = {confidence}% ـە؛ "
            f"پێویستی بە {MIN_STRONG_CONFIDENCE}% هەیە."
        )

    return {
        "valid": valid,
        "score": score,
        "confidence": confidence,
        "checks": checks,
        "reasons": reasons,
        "rr": rr
    }


# ============================================================
# WAIT PATH
# ============================================================

def choose_wait_signal(
    buy_validation: Dict[str, Any],
    sell_validation: Dict[str, Any],
    data: Dict[str, Any]
) -> str:

    buy_score = buy_validation.get(
        "score",
        0
    )

    sell_score = sell_validation.get(
        "score",
        0
    )

    buy_structure = buy_validation[
        "checks"
    ].get(
        "structure",
        False
    )

    sell_structure = sell_validation[
        "checks"
    ].get(
        "structure",
        False
    )

    if buy_structure and not sell_structure:
        return "BUY"

    if sell_structure and not buy_structure:
        return "SELL"

    if buy_score > sell_score:
        return "BUY"

    if sell_score > buy_score:
        return "SELL"

    return "WAIT"


def build_wait_message(
    data: Dict[str, Any],
    validation: Dict[str, Any],
    path_signal: str
) -> Tuple[str, str]:

    zone_price = clean_text(
        data.get(
            "zone_price"
        ),
        "N/A"
    )

    checks = validation.get(
        "checks",
        {}
    )

    reasons = validation.get(
        "reasons",
        []
    )

    # --------------------------------------------------------
    # Exact next action
    # --------------------------------------------------------

    if (
        checks.get(
            "structure"
        )
        and not checks.get(
            "zone"
        )
    ):

        wait_for = (
            "چاوەڕێی Zone ـی دروست بکە؛ "
            "Zone دەبێت لە VS/VR ـی تەواوەوە "
            "بە یاسای shorter body دروست بکرێت."
        )

    elif (
        checks.get(
            "structure"
        )
        and checks.get(
            "zone"
        )
        and not checks.get(
            "pullback"
        )
    ):

        if zone_price != "N/A":

            wait_for = (
                f"چاوەڕێ بکە نرخ بگەڕێتەوە بۆ "
                f"Zone ـی {zone_price}. "
                "پێش Retest هیچ Confirmation ـێک "
                "بە Signal ـی دروست وەرناگیرێت."
            )

        else:

            wait_for = (
                "چاوەڕێی Pullback / Retest بکە."
            )

    elif (
        checks.get(
            "pullback"
        )
        and not checks.get(
            "confirmation"
        )
    ):

        if path_signal == "BUY":

            wait_for = (
                "Pullback تەواوە؛ "
                "چاوەڕێی RBS یان SRR یان I.VR "
                "یان PO2 ـی تەواو بکە."
            )

        elif path_signal == "SELL":

            wait_for = (
                "Pullback تەواوە؛ "
                "چاوەڕێی SBR یان RSS یان I.VS "
                "یان PO2 ـی تەواو بکە."
            )

        else:

            wait_for = (
                "چاوەڕێی Confirmation ـی ڕوون بکە."
            )

    elif (
        checks.get(
            "confirmation"
        )
        and not checks.get(
            "confirmation_after_pullback"
        )
    ):

        wait_for = (
            "Confirmation هەیە، بەڵام "
            "پێویستە دوای Pullback / Retest "
            "پشتڕاست بکرێتەوە."
        )

    elif not checks.get(
        "htf_ltf"
    ):

        wait_for = (
            "چاوەڕێ بکە HTF و LTF "
            "لە یەک ئاراستەدا کۆببنەوە."
        )

    elif not checks.get(
        "direction"
    ):

        wait_for = (
            "چاوەڕێی Entry / SL / TP ـی "
            "ڕوون و لۆجیکی بکە."
        )

    elif not checks.get(
        "rr"
    ):

        wait_for = (
            "چاوەڕێی setup ـێک بکە کە "
            "RR ـی لانیکەم 1:2 هەبێت."
        )

    elif not checks.get(
        "no_rejection"
    ):

        wait_for = (
            "چاوەڕێ بکە fake breakout / "
            "strong rejection نەبێت."
        )

    else:

        wait_for = (
            "هێشتا هەموو مەرجەکانی Strong Signal "
            "کۆنەبوونەتەوە؛ چاوەڕێ بکە."
        )

    if (
        zone_price != "N/A"
        and zone_price not in wait_for
    ):

        wait_for += (
            f"\n📍 Zone Price: {zone_price}"
        )

    rejection = (
        " ".join(
            reasons
        )
        if reasons
        else
        "هەموو مەرجەکانی Strong Signal تەواو نەبوون."
    )

    if (
        zone_price != "N/A"
        and "Zone Price" not in rejection
    ):

        rejection = (
            f"📍 Zone Price: {zone_price}\n"
            + rejection
        )

    return (
        rejection,
        wait_for
    )


# ============================================================
# FINAL ENGINE
# ============================================================

def run_final_engine(
    raw_data: Dict[str, Any]
) -> Dict[str, Any]:

    data = normalize_result(
        raw_data
    )

    # --------------------------------------------------------
    # Test BUY and SELL separately.
    # --------------------------------------------------------

    buy_data = dict(
        data
    )

    buy_data["signal"] = "BUY"

    sell_data = dict(
        data
    )

    sell_data["signal"] = "SELL"

    buy_validation = build_validation(
        buy_data,
        "BUY"
    )

    sell_validation = build_validation(
        sell_data,
        "SELL"
    )

    buy_valid = buy_validation[
        "valid"
    ]

    sell_valid = sell_validation[
        "valid"
    ]

    # --------------------------------------------------------
    # BOTH VALID = CONFLICT
    # --------------------------------------------------------

    if buy_valid and sell_valid:

        data["signal"] = "WAIT"

        data["entry"] = "N/A"
        data["sl"] = "N/A"
        data["tp1"] = "N/A"
        data["tp2"] = "N/A"
        data["tp3"] = "N/A"
        data["rr"] = "N/A"

        data["score"] = max(
            buy_validation["score"],
            sell_validation["score"]
        )

        data["confidence"] = min(
            buy_validation["confidence"],
            sell_validation["confidence"]
        )

        data["rejection_reason"] = (
            "BUY و SELL هەردووکیان "
            "لە هەمان کاتدا valid ـن؛ "
            "ئەم conflict ـە بەهۆی SNRZ ـەوە نابێت بە signal بڕیار بدرێت."
        )

        data["wait_for"] = (
            "چاوەڕێ بکە یەک ئاراستەی ڕوون "
            "لە HTF/LTF ـدا پشتڕاست بکرێتەوە."
        )

        return data

    # --------------------------------------------------------
    # BUY VALID
    # --------------------------------------------------------

    if buy_valid:

        data["signal"] = "BUY"

        data["score"] = buy_validation[
            "score"
        ]

        data["confidence"] = buy_validation[
            "confidence"
        ]

        rr = buy_validation.get(
            "rr"
        )

        data["rr"] = (
            f"1:{rr:.2f}"
            if rr is not None
            else "N/A"
        )

        data["rejection_reason"] = (
            "هیچ rejection filter ـێکی سەرەکی نەشکا."
        )

        data["wait_for"] = "N/A"

        return data

    # --------------------------------------------------------
    # SELL VALID
    # --------------------------------------------------------

    if sell_valid:

        data["signal"] = "SELL"

        data["score"] = sell_validation[
            "score"
        ]

        data["confidence"] = sell_validation[
            "confidence"
        ]

        rr = sell_validation.get(
            "rr"
        )

        data["rr"] = (
            f"1:{rr:.2f}"
            if rr is not None
            else "N/A"
        )

        data["rejection_reason"] = (
            "هیچ rejection filter ـێکی سەرەکی نەشکا."
        )

        data["wait_for"] = "N/A"

        return data

    # --------------------------------------------------------
    # WAIT
    # --------------------------------------------------------

    path = choose_wait_signal(
        buy_validation,
        sell_validation,
        data
    )

    if path == "BUY":

        validation = buy_validation

    elif path == "SELL":

        validation = sell_validation

    else:

        validation = (
            buy_validation
            if buy_validation["score"]
            >= sell_validation["score"]
            else sell_validation
        )

    rejection_reason, wait_for = build_wait_message(
        data,
        validation,
        path
    )

    # Use the best path score for WAIT.
    best_score = max(
        buy_validation["score"],
        sell_validation["score"]
    )

    best_confidence = max(
        buy_validation["confidence"],
        sell_validation["confidence"]
    )

    data["signal"] = "WAIT"

    data["score"] = best_score

    data["confidence"] = best_confidence

    data["entry"] = "N/A"
    data["sl"] = "N/A"
    data["tp1"] = "N/A"
    data["tp2"] = "N/A"
    data["tp3"] = "N/A"
    data["rr"] = "N/A"

    data["rejection_reason"] = (
        rejection_reason
    )

    data["wait_for"] = (
        wait_for
    )

    return data


# ============================================================
# GEMINI REQUEST
# ============================================================

def image_to_part(
    image_bytes: bytes,
    mime_type: str = "image/jpeg"
):
    """
    Create Gemini image content.
    """

    return {
        "inline_data": {
            "mime_type": mime_type,
            "data": base64.b64encode(
                image_bytes
            ).decode(
                "utf-8"
            )
        }
    }


def call_gemini_model(
    model_name: str,
    zone_image: bytes,
    confirmation_image: bytes
) -> str:

    user_prompt = r"""
Analyze these two XAUUSD chart images.

IMAGE 1 = H1/H4 HTF.
IMAGE 2 = M1/M5 LTF.

Do not guess.

First identify complete VS / VR.

VS:
Support
→ Up
→ NEW Resistance after Support
→ Up again
→ Break that same NEW Resistance
→ VS

VR:
Resistance
→ Down
→ NEW Support after Resistance
→ Down again
→ Break that same NEW Support
→ VR

Then calculate Zone:

VS/VR formation candle
+
immediately previous candle
→ compare BODY sizes
→ shorter BODY
→ entire HIGH-to-LOW of selected candle = Zone.

Then determine:

Zone
→ Pullback / Retest
→ Confirmation
→ Entry

Confirmation BEFORE Pullback is invalid.

BUY:
RBS / SRR / I.VR / complete PO2

SELL:
SBR / RSS / I.VS / complete PO2

If price is not at Zone:
WAIT.

If Pullback is missing:
WAIT.

If Confirmation is missing:
WAIT.

If HTF/LTF conflict:
WAIT.

If RR < 1:2:
WAIT.

If any required evidence is missing:
WAIT.

For WAIT:
Give a clear Sorani Kurdish explanation.

If Zone exists:
ALWAYS give exact zone_price.

Never invent a price.

Return ONLY valid JSON.
"""

    zone_part = image_to_part(
        zone_image
    )

    confirmation_part = image_to_part(
        confirmation_image
    )

    # --------------------------------------------------------
    # Gemini SDK
    # --------------------------------------------------------

    response = gemini.models.generate_content(
        model=model_name,
        contents=[
            SYSTEM_PROMPT,
            user_prompt,
            zone_part,
            confirmation_part
        ],
        config={
            "temperature": 0.1,
            "response_mime_type": "application/json"
        }
    )

    text = getattr(
        response,
        "text",
        None
    )

    if not text:

        raise RuntimeError(
            "Gemini returned an empty response."
        )

    return text


def should_retry_gemini(
    exc: Exception
) -> bool:

    text = str(
        exc
    ).lower()

    retry_words = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "timeout",
        "temporarily",
        "unavailable",
        "rate limit",
        "resource exhausted"
    )

    return any(
        word in text
        for word in retry_words
    )


def analyze_two_charts(
    zone_image: bytes,
    confirmation_image: bytes
) -> Dict[str, Any]:

    models = [
        GEMINI_MODEL
    ]

    if (
        GEMINI_FALLBACK_MODEL
        and GEMINI_FALLBACK_MODEL
        != GEMINI_MODEL
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
                    f"Gemini analysis: "
                    f"model={model_name} "
                    f"attempt={attempt}/{GEMINI_RETRIES}"
                )

                raw_text = call_gemini_model(
                    model_name,
                    zone_image,
                    confirmation_image
                )

                cleaned = clean_json(
                    raw_text
                )

                parsed = json.loads(
                    cleaned
                )

                parsed = normalize_result(
                    parsed
                )

                # ------------------------------------------------
                # Final deterministic engine
                # ------------------------------------------------

                final_result = run_final_engine(
                    parsed
                )

                return final_result

            except Exception as exc:

                last_error = exc

                logger.exception(
                    f"Gemini attempt failed "
                    f"(model={model_name}, "
                    f"attempt={attempt})."
                )

                if (
                    attempt < GEMINI_RETRIES
                    and should_retry_gemini(
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
# TELEGRAM PHOTO DOWNLOAD
# ============================================================

def download_telegram_photo(
    message: Dict[str, Any]
) -> Optional[bytes]:

    photos = message.get(
        "photo"
    )

    if not photos:
        return None

    largest_photo = photos[-1]

    file_id = largest_photo.get(
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
            "Telegram did not return file_path."
        )

    return telegram.download_file(
        file_path
    )


# ============================================================
# FORMAT HELPERS
# ============================================================

def format_number(
    value: Any
) -> str:

    number = safe_float(
        value
    )

    if number is None:
        return clean_text(
            value,
            "N/A"
        )

    return f"{number:.2f}"


def format_checks(
    data: Dict[str, Any]
) -> str:

    checks = [
        (
            "Structure",
            validate_structure(
                data,
                normalize_side(
                    data.get(
                        "signal"
                    )
                )
            )
        ),
        (
            "Zone",
            zone_exists(
                data
            )
        ),
        (
            "Pullback",
            pullback_is_valid(
                data
            )
        ),
        (
            "Confirmation",
            confirmation_is_valid(
                data.get(
                    "signal"
                ),
                data.get(
                    "confirmation"
                )
            )
        ),
        (
            "HTF/LTF",
            htf_ltf_agree(
                data,
                normalize_side(
                    data.get(
                        "signal"
                    )
                )
            )
        ),
        (
            "Direction",
            direction_valid(
                data
            )
        ),
        (
            "RR >= 1:2",
            (
                calculate_rr(
                    data
                ) is not None
                and calculate_rr(
                    data
                ) >= MIN_RR
            )
        ),
        (
            "No Rejection",
            not strong_rejection_present(
                data
            )
        )
    ]

    lines = []

    for name, valid in checks:

        lines.append(
            f"{'✅' if valid else '❌'} {name}"
        )

    return "\n".join(
        lines
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

        title = (
            "🟢 STRONG BUY SIGNAL"
        )

    elif signal == "SELL":

        title = (
            "🔴 STRONG SELL SIGNAL"
        )

    else:

        title = (
            "🟡 WAIT"
        )

        signal = "WAIT"

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

🟦 Zone:
{clean_text(data.get("zone"), "N/A")}

📍 Zone Price:
{zone_price}

🔎 HTF Zones:
{clean_text(data.get("htf_zones"), "N/A")}

🟢 VS:
{clean_text(data.get("vs_detected"), "N/A")}

🔴 VR:
{clean_text(data.get("vr_detected"), "N/A")}

🔎 Confirmation:
{clean_text(data.get("confirmation"), "N/A")}
""".strip()

    # --------------------------------------------------------
    # TRADE DETAILS
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
    # ANALYSIS
    # --------------------------------------------------------

    text += f"""

━━━━━━━━━━━━━━━━━━
🔎 هۆکاری شیکردنەوە:
{clean_text(data.get("reasoning"), "N/A")}

✅ Checks:
{clean_text(data.get("checks"), "N/A")}
"""

    # --------------------------------------------------------
    # WAIT
    # --------------------------------------------------------

    if signal == "WAIT":

        rejection_reason = clean_text(
            data.get(
                "rejection_reason"
            ),
            "setup ـێکی بەهێز نەدۆزرایەوە."
        )

        wait_for = clean_text(
            data.get(
                "wait_for"
            ),
            "چاوەڕێی structure ـێکی تەواو بکە."
        )

        text += f"""

━━━━━━━━━━━━━━━━━━
🚫 هۆکاری WAIT:
{rejection_reason}

━━━━━━━━━━━━━━━━━━
👀 چاوەڕێی چی بکەین؟
{wait_for}
"""

    else:

        text += """

━━━━━━━━━━━━━━━━━━
🟢 STRONG SNRZ setup

هەموو مەرجە سەرەکییەکانی
SNRZ و Strong Signal تێپەڕێنراون.

⚠️ ئەمە شیکردنەوەی تەکنیکییە؛
هیچ دڵنیاییەک بە قازانج نادات.
"""

    return text.strip()


# ============================================================
# START MESSAGE
# ============================================================

START_MESSAGE = """
🥇 Gold Chart Analyzer PRO V6

🧠 SNRZ Structure Engine چالاکە.

سیستەم بە ڕیزبەندی کار دەکات:

VS / VR
↓
Zone
↓
Pullback / Retest
↓
M1/M5 Confirmation
↓
Strong Signal Validation
↓
BUY / SELL

ئەگەر مەرجەکان تەواو نەبن:

🟡 WAIT

و بۆتەکە هۆکاری WAIT و
Zone Price ـەکە بە ڕوونی پیشان دەدات.

━━━━━━━━━━━━━━━━━━

هەنگاوی 1️⃣:
📸 H1 یان H4 ـی XAUUSD بنێرە.

هەنگاوی 2️⃣:
📸 M1 یان M5 ـی XAUUSD بنێرە.

یان:

/reset
"""

HELP_MESSAGE = """
📚 Gold Chart Analyzer PRO V6

━━━━━━━━━━━━━━━━━━
🧠 SNRZ ENGINE
━━━━━━━━━━━━━━━━━━

HTF:
H1 / H4

LTF:
M1 / M5

━━━━━━━━━━━━━━━━━━
🟢 VS
━━━━━━━━━━━━━━━━━━

Support
→ Up
→ NEW Resistance after Support
→ Up
→ Break NEW Resistance
→ VS

━━━━━━━━━━━━━━━━━━
🔴 VR
━━━━━━━━━━━━━━━━━━

Resistance
→ Down
→ NEW Support after Resistance
→ Down
→ Break NEW Support
→ VR

━━━━━━━━━━━━━━━━━━
🟦 ZONE
━━━━━━━━━━━━━━━━━━

VS/VR formation candle
+
previous candle

→ compare BODY
→ shorter BODY wins
→ full HIGH-to-LOW = Zone

━━━━━━━━━━━━━━━━━━
🔄 SEQUENCE
━━━━━━━━━━━━━━━━━━

VS/VR
→ Zone
→ Pullback / Retest
→ Confirmation
→ Strong Signal

Confirmation before Retest
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
🔥 STRONG SIGNAL
━━━━━━━━━━━━━━━━━━

Score >= 80
Confidence >= 80%
RR >= 1:2
Valid VS/VR
Valid Zone
Pullback/Retest
Valid Confirmation
HTF/LTF agreement
Logical Entry/SL/TP
No strong rejection

ئەگەر یەکێک لەمانە نەبێت:

🟡 WAIT

بۆتەکە دەڵێت:
❌ بۆچی WAIT ـە
👀 چاوەڕێی چی بکەیت
📍 Zone Price ـەکە چییە
"""


# ============================================================
# MESSAGE HANDLER
# ============================================================

def handle_message(
    message: Dict[str, Any]
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

    text = clean_text(
        message.get(
            "text"
        ),
        ""
    ).strip()

    # --------------------------------------------------------
    # Admin commands first
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
    # Unauthorized
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
            START_MESSAGE.strip()
        )

        return

    # --------------------------------------------------------
    # HELP
    # --------------------------------------------------------

    if text == "/help":

        telegram.send_message(
            chat_id,
            HELP_MESSAGE.strip()
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
            "♻️ Session reset کرا.\n\n📸 ئێستا H1 یان H4 بنێرە."
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
        # FIRST IMAGE = HTF
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

🧠 ئێستا HTF structure ـەکە دەناسین:

VS / VR
→ Zone

پاشان:

📸 M1 یان M5 بنێرە بۆ
Pullback / Retest + Confirmation.
""".strip()
            )

            return

        # ----------------------------------------------------
        # SECOND IMAGE = LTF
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

🧠 V6 SNRZ Engine:

VS/VR
→ Zone
→ Pullback
→ Confirmation
→ Deterministic Validation

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

تکایە chart ـەکان بە quality ـی باشتر بنێرە.

یان:

/reset
""".strip()
                )

            finally:

                reset_session(
                    chat_id
                )

            return

        return

    # --------------------------------------------------------
    # OTHER TEXT
    # --------------------------------------------------------

    telegram.send_message(
        chat_id,
        """
تکایە:

1️⃣ H1 یان H4 بنێرە
2️⃣ پاشان M1 یان M5 بنێرە

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

    # --------------------------------------------------------
    # Callback
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Message
    # --------------------------------------------------------

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
            "Telegram API error while handling message."
        )

    except Exception:

        logger.exception(
            "Message handling error."
        )


# ============================================================
# TELEGRAM CONNECTION
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

    # Important:
    # We remove webhook so long polling works.
    telegram.delete_webhook(
        drop_pending_updates=False
    )

    logger.info(
        "Telegram webhook removed."
    )


# ============================================================
# MAIN POLLING LOOP
# ============================================================

def run():

    logger.info(
        "=================================================="
    )

    logger.info(
        "Gold Chart Analyzer PRO V6 starting..."
    )

    logger.info(
        f"Gemini model: {GEMINI_MODEL}"
    )

    if GEMINI_FALLBACK_MODEL:

        logger.info(
            f"Gemini fallback: "
            f"{GEMINI_FALLBACK_MODEL}"
        )

    logger.info(
        f"Admin ID: {ADMIN_USER_ID}"
    )

    logger.info(
        f"Allowed users: "
        f"{len(ALLOWED_USER_IDS)}"
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
        f"Minimum RR: "
        f"1:{MIN_RR}"
    )

    logger.info(
        "=================================================="
    )

    # --------------------------------------------------------
    # Telegram initialization
    # --------------------------------------------------------

    while True:

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
                "Unexpected initialization error."
            )

            time.sleep(
                TELEGRAM_RETRY_DELAY
            )

    # --------------------------------------------------------
    # Polling
    # --------------------------------------------------------

    offset = None

    while True:

        try:

            cleanup_sessions()

            updates = telegram.get_updates(
                offset=offset,
                timeout=TELEGRAM_POLL_TIMEOUT
            )

            if not updates:
                continue

            for update in updates:

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

            # ------------------------------------------------
            # 409 Conflict
            # ------------------------------------------------

            if (
                exc.status_code == 409
                or "409" in str(exc)
                or "conflict" in str(exc).lower()
            ):

                logger.error(
                    "=================================================="
                )

                logger.error(
                    "TELEGRAM 409 CONFLICT"
                )

                logger.error(
                    "Another instance of this bot is running."
                )

                logger.error(
                    "Stop every other instance using this token."
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

            logger.info(
                "Bot stopped by user."
            )

            break

        except Exception:

            logger.exception(
                "Unexpected polling error."
            )

            time.sleep(
                TELEGRAM_RETRY_DELAY
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    run()
````
