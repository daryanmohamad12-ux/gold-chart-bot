# ============================================================
# gold_chart_analyzer.py
# SNRZ GOLD CHART ANALYZER PRO - V6
#
# Flow:
# H1/H4
#   -> VS / VR
#   -> Zone
#   -> Pullback / Retest
#   -> M1/M5 Confirmation
#   -> Deterministic Strong Signal Engine
#   -> BUY / SELL / WAIT
#
# Features:
# - Telegram access request system
# - Admin approve / reject
# - Persistent allowed users
# - Gemini 3.8 Flash
# - Strict JSON output
# - Deterministic validation
# - BUY / SELL evaluated independently
# - WAIT next-action engine
# - RR validation
# - 24/7 polling
# - Telegram 409 protection
# - Automatic retry / backoff
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

MIN_STRONG_SCORE = 80
MIN_STRONG_CONFIDENCE = 80
MIN_RR = 2.0

TELEGRAM_POLL_TIMEOUT = 30
TELEGRAM_REQUEST_TIMEOUT = 60

GEMINI_RETRIES = 3
GEMINI_RETRY_DELAY = 2

MAX_TELEGRAM_MESSAGE_LENGTH = 3900

SESSION_TTL_SECONDS = 60 * 60 * 2


# ============================================================
# VALIDATION
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
# GEMINI CLIENT
# ============================================================

gemini = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# GLOBAL STATE
# ============================================================

USER_SESSIONS: Dict[int, Dict[str, Any]] = {}

PENDING_ACCESS_REQUESTS: Dict[
    int,
    Dict[str, Any]
] = {}

ACCESS_CODES: Dict[
    str,
    int
] = {}


# ============================================================
# ACCESS DATABASE
# ============================================================

def load_allowed_users() -> set:
    default_users = {
        ADMIN_USER_ID
    }

    try:
        if not os.path.exists(
            ACCESS_FILE
        ):
            return default_users

        with open(
            ACCESS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )

        users = set()

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

        elif isinstance(
            data,
            dict
        ):

            raw_users = data.get(
                "users",
                []
            )

            for user_id in raw_users:

                try:
                    users.add(
                        int(user_id)
                    )

                except (
                    ValueError,
                    TypeError
                ):
                    continue

        users.add(
            ADMIN_USER_ID
        )

        return users

    except Exception:

        logger.exception(
            "Could not load allowed users."
        )

        return default_users


ALLOWED_USER_IDS = (
    load_allowed_users()
)


def save_allowed_users() -> None:

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
# TELEGRAM API
# ============================================================

class TelegramAPIError(
    Exception
):

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None
    ):

        super().__init__(
            message
        )

        self.status_code = (
            status_code
        )


class TelegramConflictError(
    TelegramAPIError
):
    pass


class TelegramBot:

    def __init__(
        self,
        token: str
    ):

        self.token = token

        self.base_url = (
            f"https://api.telegram.org/bot{token}"
        )

    def call(
        self,
        method: str,
        data: Optional[Dict] = None,
        timeout: int = TELEGRAM_REQUEST_TIMEOUT
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
                f"Telegram network error: {exc}"
            ) from exc

        try:

            result = response.json()

        except ValueError:

            result = {}

        if response.status_code == 409:

            raise TelegramConflictError(
                "Telegram 409 Conflict: "
                "another bot instance is running.",
                status_code=409
            )

        if response.status_code >= 400:

            description = result.get(
                "description",
                response.text
            )

            raise TelegramAPIError(
                f"Telegram HTTP {response.status_code}: "
                f"{description}",
                status_code=response.status_code
            )

        if not result.get(
            "ok",
            False
        ):

            description = result.get(
                "description",
                "Telegram API error"
            )

            raise TelegramAPIError(
                description
            )

        return result.get(
            "result"
        )

    def get_me(self):

        return self.call(
            "getMe"
        )

    def delete_webhook(
        self,
        drop_pending_updates=False
    ):

        return self.call(
            "deleteWebhook",
            {
                "drop_pending_updates":
                    drop_pending_updates
            }
        )

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

    def send_message(
        self,
        chat_id: int,
        text: str
    ):

        if not isinstance(
            text,
            str
        ):

            text = str(
                text
            )

        chunks = split_message(
            text,
            MAX_TELEGRAM_MESSAGE_LENGTH
        )

        results = []

        for chunk in chunks:

            results.append(
                self.call(
                    "sendMessage",
                    {
                        "chat_id":
                            chat_id,

                        "text":
                            chunk
                    }
                )
            )

        return results

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None
    ):

        data = {
            "callback_query_id":
                callback_query_id
        }

        if text:

            data["text"] = text

        return self.call(
            "answerCallbackQuery",
            data
        )

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: Optional[Dict] = None
    ):

        data = {
            "chat_id":
                chat_id,

            "message_id":
                message_id
        }

        if reply_markup is not None:

            data["reply_markup"] = (
                reply_markup
            )

        return self.call(
            "editMessageReplyMarkup",
            data
        )

    def get_file(
        self,
        file_id: str
    ):

        return self.call(
            "getFile",
            {
                "file_id":
                    file_id
            }
        )

    def download_file(
        self,
        file_path: str
    ) -> bytes:

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

            return response.content

        except requests.RequestException as exc:

            raise TelegramAPIError(
                f"Telegram file download failed: {exc}"
            ) from exc


telegram = TelegramBot(
    TELEGRAM_BOT_TOKEN
)


# ============================================================
# HELPERS
# ============================================================

def split_message(
    text: str,
    max_length: int
) -> List[str]:

    if len(text) <= max_length:

        return [text]

    chunks = []

    current = ""

    for line in text.splitlines(
        keepends=True
    ):

        if (
            len(current)
            + len(line)
            <= max_length
        ):

            current += line

        else:

            if current:

                chunks.append(
                    current
                )

            while len(line) > max_length:

                chunks.append(
                    line[:max_length]
                )

                line = line[
                    max_length:
                ]

            current = line

    if current:

        chunks.append(
            current
        )

    return chunks


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

            return float(
                value
            )

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

    return text if text else default


def normalize_signal(
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


def normalize_side(
    value: Any
) -> str:

    text = clean_text(
        value,
        ""
    ).upper()

    if "BUY" in text:

        return "BUY"

    if "SELL" in text:

        return "SELL"

    return ""


def is_missing(
    value: Any
) -> bool:

    text = clean_text(
        value,
        ""
    ).strip().upper()

    return text in {
        "",
        "N/A",
        "NA",
        "NONE",
        "NULL",
        "UNKNOWN",
        "NOT AVAILABLE",
        "NOT CLEAR"
    }


def normalize_bool(
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
        "y",
        "1",
        "valid",
        "confirmed",
        "complete",
        "completed"
    }


# ============================================================
# SESSION MANAGEMENT
# ============================================================

def reset_session(
    chat_id: int
) -> None:

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

    if not session:

        session = {
            "zone_image":
                None,

            "confirmation_image":
                None,

            "created_at":
                now,

            "updated_at":
                now
        }

        USER_SESSIONS[
            chat_id
        ] = session

    else:

        created_at = session.get(
            "created_at",
            now
        )

        if (
            now - created_at
            > SESSION_TTL_SECONDS
        ):

            session = {
                "zone_image":
                    None,

                "confirmation_image":
                    None,

                "created_at":
                    now,

                "updated_at":
                    now
            }

            USER_SESSIONS[
                chat_id
            ] = session

        else:

            session[
                "updated_at"
            ] = now

    return session


def cleanup_sessions() -> None:

    now = time.time()

    expired = []

    for chat_id, session in (
        USER_SESSIONS.items()
    ):

        updated_at = session.get(
            "updated_at",
            session.get(
                "created_at",
                now
            )
        )

        if (
            now - updated_at
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
# ACCESS CONTROL
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
) -> None:

    telegram.send_message(

        chat_id,

        """
⛔ دەستگەیشتن ڕەتکرایەوە.

تۆ هێشتا ڕێگەپێدراوی
Gold Chart Analyzer PRO نیت.

بۆ داواکاریی دەستگەیشتن:
🔑 /start
""".strip()
    )


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
    message: Dict,
    chat_id: int,
    user_id: int
) -> None:

    if is_allowed(
        user_id
    ):

        telegram.send_message(
            chat_id,
            "✅ تۆ پێشتر ڕێگەپێدراویت."
        )

        return

    if user_id in PENDING_ACCESS_REQUESTS:

        request = (
            PENDING_ACCESS_REQUESTS[
                user_id
            ]
        )

        code = request[
            "code"
        ]

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

        return

    user = message.get(
        "from",
        {}
    )

    first_name = clean_text(
        user.get(
            "first_name"
        ),
        "Unknown"
    )

    last_name = clean_text(
        user.get(
            "last_name"
        ),
        ""
    )

    username = clean_text(
        user.get(
            "username"
        ),
        ""
    )

    code = (
        generate_access_code()
    )

    request = {

        "user_id":
            user_id,

        "chat_id":
            chat_id,

        "code":
            code,

        "first_name":
            first_name,

        "last_name":
            last_name,

        "username":
            username,

        "created_at":
            time.time()
    }

    PENDING_ACCESS_REQUESTS[
        user_id
    ] = request

    ACCESS_CODES[
        code
    ] = user_id

    telegram.send_message(

        chat_id,

        f"""
⏳ داواکاریی دەستگەیشتنت نێردرا بۆ Admin.

━━━━━━━━━━━━━━━━━━

🔑 Access Code:
{code}

🆔 Telegram ID:
{user_id}

━━━━━━━━━━━━━━━━━━

👑 چاوەڕێی پەسەندکردنی Admin بکە.
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

بڕیار بدە:
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
            "Could not notify admin."
        )


# ============================================================
# ACCESS CALLBACK
# ============================================================

def handle_access_callback(
    callback_query: Dict
) -> None:

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

    data = clean_text(
        callback_query.get(
            "data"
        ),
        ""
    )

    if not is_admin(
        admin_id
    ):

        telegram.answer_callback_query(

            callback_id,

            "⛔ تەنها Admin دەتوانێت ئەمە بکات."
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

            "⚠️ Access Code نەدۆزرایەوە."
        )

        return

    request = (
        PENDING_ACCESS_REQUESTS.get(
            user_id
        )
    )

    if not request:

        telegram.answer_callback_query(

            callback_id,

            "⚠️ Request ـەکە پێشتر مامەڵەی لەگەڵ کراوە."
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

🥇 Gold Chart Analyzer PRO

🧠 SNRZ Structure Engine چالاکە.

هەنگاوی 1️⃣:
📸 H1 یان H4 ـی XAUUSD بنێرە.

دوای ئەوە:
📸 M1 یان M5 بنێرە.
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
    message: Dict,
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

    if command == "/adduser":

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

        telegram.send_message(

            chat_id,

            f"""
✅ بەکارهێنەر زیادکرا.

🆔 User ID:
{new_user_id}

👥 Total:
{len(ALLOWED_USER_IDS)}
""".strip()
        )

        return True

    if command == "/removeuser":

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

        if (
            remove_user_id
            == ADMIN_USER_ID
        ):

            telegram.send_message(
                chat_id,
                "⛔ ناتوانیت Admin بسڕیتەوە."
            )

            return True

        if (
            remove_user_id
            in ALLOWED_USER_IDS
        ):

            ALLOWED_USER_IDS.remove(
                remove_user_id
            )

            save_allowed_users()

            telegram.send_message(

                chat_id,

                f"""
✅ بەکارهێنەر سڕایەوە.

🆔 User ID:
{remove_user_id}
""".strip()
            )

        else:

            telegram.send_message(
                chat_id,
                "ℹ️ User ID ـەکە لە لیستدا نییە."
            )

        return True

    if command == "/users":

        users = sorted(
            ALLOWED_USER_IDS
        )

        if not users:

            text_out = (
                "👥 هیچ بەکارهێنەرێک نییە."
            )

        else:

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

            text_out = (
                "👥 ALLOWED USERS\n"
                "━━━━━━━━━━━━━━\n"
                + "\n".join(lines)
                + "\n\n"
                + f"Total: {len(users)}"
            )

        telegram.send_message(
            chat_id,
            text_out
        )

        return True

    if command == "/pending":

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

    if command == "/broadcast":

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
                    "Broadcast failed for %s",
                    uid
                )

        telegram.send_message(

            chat_id,

            f"""
📢 Broadcast تەواوبوو.

✅ سەرکەوتوو:
{success}

❌ سەرکەوتوو نەبوو:
{failed}
""".strip()
        )

        return True

    if command == "/admin":

        telegram.send_message(

            chat_id,

            """
👑 ADMIN PANEL
━━━━━━━━━━━━━━━━━━

➕ زیادکردن:

/adduser USER_ID

➖ سڕینەوە:

/removeuser USER_ID

👥 بەکارهێنەران:

/users

⏳ داواکارییەکان:

/pending

📢 Broadcast:

/broadcast MESSAGE
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

Your job is to identify the structure first.

The required sequence is:

VALID VS/VR
→ ZONE
→ PULLBACK / RETEST
→ CONFIRMATION
→ STRONG SIGNAL CHECK
→ BUY / SELL

Otherwise WAIT.

============================================================
IMAGE ROLES
============================================================

IMAGE 1 = H1 or H4.
IMAGE 2 = M1 or M5.

IMAGE 1:
Higher timeframe structure.

IMAGE 2:
Lower timeframe confirmation.

Never reverse these roles.

============================================================
VS
============================================================

A normal Support is NOT automatically VS.

VS requires:

SUPPORT
→ UP
→ NEW RESISTANCE CREATED AFTER SUPPORT
→ UP AGAIN
→ BREAK THAT SAME NEW RESISTANCE

Only then:

SUPPORT = VS.

Any Resistance existing BEFORE the Support is irrelevant.

If the new Resistance after Support has not been broken:

NOT VS.

============================================================
VR
============================================================

A normal Resistance is NOT automatically VR.

VR requires:

RESISTANCE
→ DOWN
→ NEW SUPPORT CREATED AFTER RESISTANCE
→ DOWN AGAIN
→ BREAK THAT SAME NEW SUPPORT

Only then:

RESISTANCE = VR.

Any Support existing BEFORE the Resistance is irrelevant.

If the new Support after Resistance has not been broken:

NOT VR.

============================================================
ZONE
============================================================

After a VALID VS or VR:

1. Identify the candle where the VS/VR is formed.
2. Identify the immediately previous candle.
3. Compare BODY size.
4. Choose the candle with the SHORTER BODY.
5. The ENTIRE selected candle HIGH-to-LOW is the Zone.

Zone is NOT body only.

Do NOT use engulfing calculations.

Do NOT invent another zone method.

============================================================
PULLBACK
============================================================

A valid zone alone is not enough.

Required:

VALID VS/VR
→ ZONE
→ PRICE RETURNS / RETESTS ZONE
→ CONFIRMATION

If price has not reached/retested the Zone:

WAIT.

============================================================
BUY
============================================================

BUY can only use:

RBS
SRR
I.VR
PO2

And only after Pullback/Retest.

============================================================
SELL
============================================================

SELL can only use:

SBR
RSS
I.VS
PO2

And only after Pullback/Retest.

============================================================
STRONG SIGNAL
============================================================

BUY or SELL requires:

1. Valid VS/VR.
2. Valid Zone.
3. Price at/retesting Zone.
4. Confirmation AFTER Pullback.
5. HTF/LTF agreement.
6. Clear Entry.
7. Logical SL.
8. Logical TP.
9. RR >= 1:2.
10. Score >= 80.
11. Confidence >= 80.
12. No strong rejection.

If one mandatory condition is missing:

WAIT.

============================================================
WAIT
============================================================

WAIT is preferred over guessing.

If Zone exists but price has not returned:

Explain that the trader must wait for the Zone.

If price returned but confirmation is missing:

Explain the exact confirmation needed.

If confirmation appeared before retest:

Treat it as INVALID.

If RR is below 1:2:

WAIT.

Never invent prices.

============================================================
OUTPUT
============================================================

Return ONLY valid JSON.

Required keys:

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

============================================================
LANGUAGE
============================================================

All explanatory text must be Sorani Kurdish.

Technical SNRZ names remain English.

============================================================
WAIT
============================================================

When WAIT:

entry = "N/A"
sl = "N/A"
tp1 = "N/A"
tp2 = "N/A"
tp3 = "N/A"
rr = "N/A"

If Zone exists:

zone_price MUST contain its actual range.

wait_for MUST explain the next action.

Never invent prices.
"""


# ============================================================
# JSON SCHEMA
# ============================================================

RESPONSE_SCHEMA = {

    "type": "object",

    "properties": {

        "signal": {
            "type": "string"
        },

        "symbol": {
            "type": "string"
        },

        "setup": {
            "type": "string"
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

        "confidence": {
            "type": "number"
        },

        "score": {
            "type": "number"
        },

        "zone": {
            "type": "string"
        },

        "zone_price": {
            "type": "string"
        },

        "htf_zones": {
            "type": "string"
        },

        "vs_detected": {
            "type": "string"
        },

        "vr_detected": {
            "type": "string"
        },

        "confirmation": {
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

        "rejection_reason": {
            "type": "string"
        },

        "wait_for": {
            "type": "string"
        }
    },

    "required": [
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
}


# ============================================================
# JSON CLEANER
# ============================================================

def clean_json(
    text: str
) -> str:

    if not text:

        raise RuntimeError(
            "Gemini returned an empty response."
        )

    text = text.strip()

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

    start = text.find(
        "{"
    )

    end = text.rfind(
        "}"
    )

    if (
        start == -1
        or end == -1
        or end <= start
    ):

        raise RuntimeError(
            "Gemini did not return JSON."
        )

    return text[
        start:end + 1
    ]


# ============================================================
# NORMALIZE AI RESULT
# ============================================================

def normalize_result(
    raw: Any
) -> Dict[str, Any]:

    if not isinstance(
        raw,
        dict
    ):

        raw = {}

    result = {}

    result["signal"] = normalize_signal(
        raw.get(
            "signal"
        )
    )

    result["symbol"] = "XAUUSD"

    for key in [
        "setup",
        "entry",
        "sl",
        "tp1",
        "tp2",
        "tp3",
        "rr",
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
    ]:

        result[key] = clean_text(
            raw.get(
                key
            )
        )

    result["score"] = (
        safe_float(
            raw.get(
                "score",
                0
            )
        )
        or 0
    )

    result["confidence"] = (
        safe_float(
            raw.get(
                "confidence",
                0
            )
        )
        or 0
    )

    return result


# ============================================================
# STRUCTURE VALIDATION
# ============================================================

def contains_token(
    text: str,
    token: str
) -> bool:

    return (
        token.upper()
        in text.upper()
    )


def has_valid_vs(
    data: Dict[str, Any]
) -> bool:

    text = " ".join(
        [
            data.get(
                "vs_detected",
                ""
            ),

            data.get(
                "htf_zones",
                ""
            ),

            data.get(
                "zone",
                ""
            )
        ]
    ).upper()

    return (
        "VS" in text
        and "NOT VS" not in text
        and "INVALID VS" not in text
    )


def has_valid_vr(
    data: Dict[str, Any]
) -> bool:

    text = " ".join(
        [
            data.get(
                "vr_detected",
                ""
            ),

            data.get(
                "htf_zones",
                ""
            ),

            data.get(
                "zone",
                ""
            )
        ]
    ).upper()

    return (
        "VR" in text
        and "NOT VR" not in text
        and "INVALID VR" not in text
    )


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

    if is_missing(
        zone
    ):

        return False

    if is_missing(
        zone_price
    ):

        return False

    return True


def parse_zone_range(
    zone_price: str
) -> Optional[Tuple[float, float]]:

    if is_missing(
        zone_price
    ):

        return None

    numbers = re.findall(
        r"-?\d+(?:\.\d+)?",
        zone_price.replace(
            ",",
            ""
        )
    )

    if len(numbers) < 2:

        return None

    try:

        first = float(
            numbers[0]
        )

        second = float(
            numbers[1]
        )

        return (
            min(
                first,
                second
            ),
            max(
                first,
                second
            )
        )

    except Exception:

        return None


# ============================================================
# PULLBACK / RETEST DETECTION
# ============================================================

def pullback_is_valid(
    data: Dict[str, Any]
) -> bool:

    text = " ".join(
        [
            data.get(
                "setup",
                ""
            ),

            data.get(
                "reasoning",
                ""
            ),

            data.get(
                "checks",
                ""
            ),

            data.get(
                "confirmation",
                ""
            )
        ]
    ).lower()

    positive_terms = [
        "pullback",
        "retest",
        "retested",
        "returned to zone",
        "reached zone",
        "لامدانەوە",
        "گەڕایەوە",
        "گەیشتووەتە zone"
    ]

    negative_terms = [
        "no retest",
        "not retested",
        "retest missing",
        "without retest",
        "pullback missing",
        "retest نەکراوە",
        "pullback نییە"
    ]

    if any(
        term in text
        for term in negative_terms
    ):

        return False

    return any(
        term in text
        for term in positive_terms
    )


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


def normalize_confirmation(
    value: str
) -> str:

    text = clean_text(
        value,
        ""
    ).upper()

    for name in [
        "I.VR",
        "I.VS",
        "RBS",
        "SBR",
        "SRR",
        "RSS",
        "PO2"
    ]:

        if name in text:

            return name

    return ""


def confirmation_is_valid(
    signal: str,
    confirmation: str
) -> bool:

    normalized = (
        normalize_confirmation(
            confirmation
        )
    )

    if signal == "BUY":

        return (
            normalized
            in BUY_CONFIRMATIONS
        )

    if signal == "SELL":

        return (
            normalized
            in SELL_CONFIRMATIONS
        )

    return False


def confirmation_after_pullback(
    data: Dict[str, Any]
) -> bool:

    text = " ".join(
        [
            data.get(
                "confirmation",
                ""
            ),

            data.get(
                "reasoning",
                ""
            ),

            data.get(
                "checks",
                ""
            )
        ]
    ).lower()

    invalid_terms = [
        "before pullback",
        "before retest",
        "confirmation before",
        "پێش pullback",
        "پێش retest"
    ]

    if any(
        term in text
        for term in invalid_terms
    ):

        return False

    return pullback_is_valid(
        data
    )


# ============================================================
# HTF / LTF AGREEMENT
# ============================================================

def htf_ltf_agree(
    data: Dict[str, Any],
    signal: str
) -> bool:

    text = " ".join(
        [
            data.get(
                "checks",
                ""
            ),

            data.get(
                "reasoning",
                ""
            ),

            data.get(
                "setup",
                ""
            )
        ]
    ).lower()

    conflict_terms = [
        "conflict",
        "disagree",
        "opposite",
        "مخالف",
        "ناکۆک",
        "conflicting"
    ]

    if any(
        term in text
        for term in conflict_terms
    ):

        return False

    agreement_terms = [
        "agree",
        "agreement",
        "aligned",
        "alignment",
        "htf/l tf",
        "htf/ltf",
        "htf + ltf",
        "هاوتا",
        "گونجاو"
    ]

    return any(
        term in text
        for term in agreement_terms
    )


# ============================================================
# DIRECTION VALIDATION
# ============================================================

def direction_valid(
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

    if signal == "BUY":

        return (
            sl < entry
            and tp1 > entry
        )

    if signal == "SELL":

        return (
            sl > entry
            and tp1 < entry
        )

    return False


# ============================================================
# RR
# ============================================================

def calculate_rr(
    data: Dict[str, Any]
) -> Optional[float]:

    signal = normalize_signal(
        data.get(
            "signal"
        )
    )

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


# ============================================================
# SCORE ENGINE
# ============================================================

def calculate_deterministic_score(
    data: Dict[str, Any],
    signal: str
) -> Tuple[int, List[str]]:

    score = 0
    passed = []

    if signal == "BUY":

        structure_ok = (
            has_valid_vs(data)
        )

    else:

        structure_ok = (
            has_valid_vr(data)
        )

    if structure_ok:

        score += 20
        passed.append(
            "Valid VS/VR"
        )

    if zone_exists(
        data
    ):

        score += 15
        passed.append(
            "Valid Zone"
        )

    if pullback_is_valid(
        data
    ):

        score += 15
        passed.append(
            "Pullback/Retest"
        )

    confirmation = (
        data.get(
            "confirmation",
            ""
        )
    )

    if (
        confirmation_is_valid(
            signal,
            confirmation
        )
        and confirmation_after_pullback(
            data
        )
    ):

        score += 15
        passed.append(
            "Valid Confirmation"
        )

    if htf_ltf_agree(
        data,
        signal
    ):

        score += 10
        passed.append(
            "HTF/LTF Agreement"
        )

    rr = calculate_rr(
        data
    )

    if (
        rr is not None
        and rr >= MIN_RR
    ):

        score += 10
        passed.append(
            "RR >= 1:2"
        )

    if direction_valid(
        data,
        signal
    ):

        score += 5
        passed.append(
            "Entry/SL/TP Direction"
        )

    rejection_text = (
        data.get(
            "rejection_reason",
            ""
        )
    ).lower()

    strong_rejection = any(
        word in rejection_text
        for word in [
            "rejection",
            "strong rejection",
            "fake breakout",
            "fake break"
        ]
    )

    if not strong_rejection:

        score += 5
        passed.append(
            "No Strong Rejection"
        )

    ai_score = safe_float(
        data.get(
            "score",
            0
        )
    ) or 0

    if ai_score >= 80:

        score += 5
        passed.append(
            "AI Score >= 80"
        )

    return (
        min(
            score,
            100
        ),
        passed
    )


# ============================================================
# CONFIDENCE ENGINE
# ============================================================

def calculate_deterministic_confidence(
    data: Dict[str, Any],
    score: int,
    signal: str
) -> int:

    base = score

    ai_confidence = safe_float(
        data.get(
            "confidence",
            0
        )
    ) or 0

    blended = (
        (base * 0.75)
        + (min(
            ai_confidence,
            100
        ) * 0.25)
    )

    mandatory = [

        (
            signal == "BUY"
            and has_valid_vs(data)
        )
        or
        (
            signal == "SELL"
            and has_valid_vr(data)
        ),

        zone_exists(data),

        pullback_is_valid(data),

        confirmation_after_pullback(data),

        htf_ltf_agree(
            data,
            signal
        ),

        direction_valid(
            data,
            signal
        ),

        (
            calculate_rr(
                data
            ) or 0
        ) >= MIN_RR
    ]

    mandatory_count = sum(
        1
        for item in mandatory
        if item
    )

    if mandatory_count < len(
        mandatory
    ):

        blended = min(
            blended,
            79
        )

    return max(
        0,
        min(
            int(
                round(
                    blended
                )
            ),
            100
        )
    )


# ============================================================
# BUILD WAIT ACTION
# ============================================================

def build_wait_action(
    data: Dict[str, Any],
    preferred_side: str
) -> str:

    zone_price = clean_text(
        data.get(
            "zone_price"
        ),
        ""
    )

    if not zone_exists(
        data
    ):

        return (
            "سەرەتا VS/VR ـێکی تەواو "
            "و Zone ـێکی ڕوون پێویستە."
        )

    if preferred_side == "BUY":

        structure_ok = (
            has_valid_vs(
                data
            )
        )

        if not structure_ok:

            return (
                "چاوەڕێی VS ـێکی تەواوی "
                "لە H1/H4 بکە."
            )

        if not pullback_is_valid(
            data
        ):

            return (
                f"چاوەڕێ بکە نرخ بگەڕێتەوە "
                f"بۆ Zone ـی {zone_price}."
            )

        if not confirmation_is_valid(
            "BUY",
            data.get(
                "confirmation",
                ""
            )
        ):

            return (
                f"نرخ گەیشتووەتە Zone ـی "
                f"{zone_price}؛ "
                "ئێستا چاوەڕێی RBS یان SRR "
                "یان I.VR یان PO2 بکە."
            )

    if preferred_side == "SELL":

        structure_ok = (
            has_valid_vr(
                data
            )
        )

        if not structure_ok:

            return (
                "چاوەڕێی VR ـێکی تەواوی "
                "لە H1/H4 بکە."
            )

        if not pullback_is_valid(
            data
        ):

            return (
                f"چاوەڕێ بکە نرخ بگاتەوە "
                f"بۆ Zone ـی {zone_price}."
            )

        if not confirmation_is_valid(
            "SELL",
            data.get(
                "confirmation",
                ""
            )
        ):

            return (
                f"نرخ گەیشتووەتە Zone ـی "
                f"{zone_price}؛ "
                "ئێستا چاوەڕێی SBR یان RSS "
                "یان I.VS یان PO2 بکە."
            )

    rr = calculate_rr(
        data
    )

    if (
        rr is not None
        and rr < MIN_RR
    ):

        return (
            "Setup هەیە، بەڵام RR کەمترە "
            "لە 1:2؛ چاوەڕێی Entry/TP ـێکی باشتر بکە."
        )

    return (
        "هەموو بەڵگەکان هێشتا بە تەواوی "
        "پشتڕاست نەبوونەتەوە؛ چاوەڕێ بکە."
    )


# ============================================================
# STRONG SIGNAL ENGINE
# ============================================================

def strong_signal_engine(
    data: Dict[str, Any]
) -> Dict[str, Any]:

    data = normalize_result(
        data
    )

    raw_signal = (
        data["signal"]
    )

    candidates = []

    if raw_signal in (
        "BUY",
        "WAIT"
    ):

        candidates.append(
            "BUY"
        )

    if raw_signal in (
        "SELL",
        "WAIT"
    ):

        candidates.append(
            "SELL"
        )

    evaluated = []

    for side in candidates:

        candidate = dict(
            data
        )

        candidate[
            "signal"
        ] = side

        score, passed = (
            calculate_deterministic_score(
                candidate,
                side
            )
        )

        confidence = (
            calculate_deterministic_confidence(
                candidate,
                score,
                side
            )
        )

        rr = calculate_rr(
            candidate
        )

        reasons = []

        if side == "BUY":

            if not has_valid_vs(
                candidate
            ):

                reasons.append(
                    "VS ـی تەواو نییە."
                )

        else:

            if not has_valid_vr(
                candidate
            ):

                reasons.append(
                    "VR ـی تەواو نییە."
                )

        if not zone_exists(
            candidate
        ):

            reasons.append(
                "Zone ـی ڕوون نییە."
            )

        if not pullback_is_valid(
            candidate
        ):

            reasons.append(
                "Pullback / Retest پشتڕاست نییە."
            )

        if not confirmation_is_valid(
            side,
            candidate.get(
                "confirmation",
                ""
            )
        ):

            reasons.append(
                "Confirmation ـی دروست نییە."
            )

        if not confirmation_after_pullback(
            candidate
        ):

            reasons.append(
                "Confirmation پێش Pullback هاتووە یان "
                "ڕیزبەندییەکە پشتڕاست نییە."
            )

        if not htf_ltf_agree(
            candidate,
            side
        ):

            reasons.append(
                "HTF/LTF agreement پشتڕاست نییە."
            )

        if not direction_valid(
            candidate,
            side
        ):

            reasons.append(
                "Entry/SL/TP direction دروست نییە."
            )

        if (
            rr is None
            or rr < MIN_RR
        ):

            reasons.append(
                "RR کەمترە لە 1:2 یان ناتوانرێت حساب بکرێت."
            )

        accepted = (
            score >= MIN_STRONG_SCORE
            and confidence >= MIN_STRONG_CONFIDENCE
            and not reasons
        )

        evaluated.append(
            {
                "side":
                    side,

                "score":
                    score,

                "confidence":
                    confidence,

                "rr":
                    rr,

                "passed":
                    passed,

                "reasons":
                    reasons,

                "accepted":
                    accepted
            }
        )

    accepted_paths = [
        item
        for item in evaluated
        if item["accepted"]
    ]

    # --------------------------------------------------------
    # BOTH SIDES VALID = CONFLICT
    # --------------------------------------------------------

    if len(
        accepted_paths
    ) > 1:

        data["signal"] = "WAIT"

        data["score"] = 0

        data["confidence"] = 0

        data["entry"] = "N/A"
        data["sl"] = "N/A"
        data["tp1"] = "N/A"
        data["tp2"] = "N/A"
        data["tp3"] = "N/A"
        data["rr"] = "N/A"

        data["rejection_reason"] = (
            "BUY و SELL هەردووکیان بە شێوەیەکی "
            "ناڕوون پشتڕاست بوون؛ conflict ـە."
        )

        data["wait_for"] = (
            "چاوەڕێ بکە direction ـی HTF/LTF "
            "ڕوونتر بێت."
        )

        return data

    # --------------------------------------------------------
    # ONE VALID PATH
    # --------------------------------------------------------

    if len(
        accepted_paths
    ) == 1:

        selected = accepted_paths[0]

        data["signal"] = (
            selected["side"]
        )

        data["score"] = (
            selected["score"]
        )

        data["confidence"] = (
            selected["confidence"]
        )

        if selected["rr"] is not None:

            data["rr"] = (
                f"1:{selected['rr']:.2f}"
            )

        data["rejection_reason"] = (
            "هیچ rejection filter ـێکی "
            "سەرەکی نەشکا."
        )

        data["wait_for"] = "N/A"

        return data

    # --------------------------------------------------------
    # WAIT
    # --------------------------------------------------------

    if evaluated:

        evaluated.sort(
            key=lambda item: (
                item["score"],
                item["confidence"]
            ),
            reverse=True
        )

        best = evaluated[0]

        data["score"] = (
            best["score"]
        )

        data["confidence"] = (
            best["confidence"]
        )

        preferred_side = (
            best["side"]
        )

        reason_parts = (
            best["reasons"]
        )

        if reason_parts:

            data["rejection_reason"] = (
                " ".join(
                    reason_parts
                )
            )

        else:

            data["rejection_reason"] = (
                "مەرجە سەرەکییەکان هێشتا "
                "بە تەواوی تێپەڕ نەبوون."
            )

        data["wait_for"] = (
            build_wait_action(
                data,
                preferred_side
            )
        )

    else:

        data["score"] = 0
        data["confidence"] = 0

        data["rejection_reason"] = (
            "هیچ path ـێکی BUY/SELL "
            "پشتڕاست نەکراوەتەوە."
        )

        data["wait_for"] = (
            "چاوەڕێی structure ـێکی تەواوی "
            "SNRZ بکە."
        )

    data["signal"] = "WAIT"

    data["entry"] = "N/A"
    data["sl"] = "N/A"
    data["tp1"] = "N/A"
    data["tp2"] = "N/A"
    data["tp3"] = "N/A"
    data["rr"] = "N/A"

    zone_price = clean_text(
        data.get(
            "zone_price"
        ),
        ""
    )

    if (
        not is_missing(
            zone_price
        )
        and zone_price
        not in data["wait_for"]
    ):

        data["wait_for"] += (
            f"\n📍 Zone Price: {zone_price}"
        )

    return data


# ============================================================
# GEMINI CALL
# ============================================================

def call_gemini(
    zone_image: bytes,
    confirmation_image: bytes,
    model_name: str
) -> Dict[str, Any]:

    zone_base64 = (
        base64.b64encode(
            zone_image
        ).decode(
            "utf-8"
        )
    )

    confirmation_base64 = (
        base64.b64encode(
            confirmation_image
        ).decode(
            "utf-8"
        )
    )

    user_prompt = """
Analyze these two XAUUSD chart images.

IMAGE 1:
H1/H4 Higher Timeframe.

IMAGE 2:
M1/M5 Lower Timeframe.

Do NOT guess.

First identify complete VS/VR.

Then identify Zone.

Then determine whether price has actually returned/retested the Zone.

Only after Pullback/Retest may you accept confirmation.

BUY:
RBS / SRR / I.VR / PO2

SELL:
SBR / RSS / I.VS / PO2

Confirmation before Pullback is INVALID.

Strong signal requires:

Valid VS/VR
Valid Zone
Price at/retesting Zone
Valid confirmation after Pullback
HTF/LTF agreement
Logical Entry
Logical SL
Logical TP
RR >= 1:2
Score >= 80
Confidence >= 80
No strong rejection

If anything mandatory is missing:
WAIT.

The zone_price must contain the actual price range
when a valid Zone exists.

Never invent a price.

Return ONLY JSON.
"""

    interaction = gemini.interactions.create(

        model=model_name,

        input=[
            {
                "type":
                    "text",

                "text":
                    SYSTEM_PROMPT
                    + "\n\n"
                    + user_prompt
            },

            {
                "type":
                    "image",

                "data":
                    zone_base64,

                "mime_type":
                    "image/jpeg"
            },

            {
                "type":
                    "image",

                "data":
                    confirmation_base64,

                "mime_type":
                    "image/jpeg"
            }
        ],

        generation_config={
            "thinking_level":
                "medium"
        },

        response_format={
            "type":
                "text",

            "mime_type":
                "application/json",

            "schema":
                RESPONSE_SCHEMA
        }
    )

    text = getattr(
        interaction,
        "output_text",
        None
    )

    cleaned = clean_json(
        text
    )

    result = json.loads(
        cleaned
    )

    return normalize_result(
        result
    )


# ============================================================
# RETRY GEMINI
# ============================================================

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
                    "Gemini analysis: model=%s attempt=%s",
                    model_name,
                    attempt
                )

                result = call_gemini(
                    zone_image,
                    confirmation_image,
                    model_name
                )

                return strong_signal_engine(
                    result
                )

            except Exception as exc:

                last_error = exc

                logger.exception(
                    "Gemini attempt failed."
                )

                if attempt < GEMINI_RETRIES:

                    time.sleep(
                        GEMINI_RETRY_DELAY
                        * attempt
                    )

        logger.warning(
            "Switching Gemini model."
        )

    raise RuntimeError(
        f"Gemini analysis failed: {last_error}"
    )


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(
    data: Dict[str, Any]
) -> str:

    signal = normalize_signal(
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

        title = "🟡 WAIT"

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
━━━━━━━━━━━━━━━━━━
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
━━━━━━━━━━━━━━━━━━
🔎 هۆکار:
{data.get("reasoning", "N/A")}

✅ Checks:
{data.get("checks", "N/A")}
"""

    if signal == "WAIT":

        text += f"""
━━━━━━━━━━━━━━━━━━
🚫 هۆکاری WAIT:

{data.get(
    "rejection_reason",
    "setup ـێکی بەهێز نەدۆزرایەوە."
)}

━━━━━━━━━━━━━━━━━━
👀 چاوەڕێی چی بکەین؟

{data.get(
    "wait_for",
    "چاوەڕێی structure ـێکی تەواوی SNRZ بکە."
)}
"""

    else:

        text += """
━━━━━━━━━━━━━━━━━━
🟢 STRONG SNRZ SETUP

هەموو filter ـە سەرەکییەکان
پشتڕاست کراونەتەوە.

⚠️ ئەمە شیکردنەوەی تەکنیکییە؛
هیچ دڵنیاییەک بە قازانج نادات.
"""

    return text.strip()


# ============================================================
# DOWNLOAD TELEGRAM PHOTO
# ============================================================

def download_telegram_photo(
    message: Dict
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
            "Telegram file path missing."
        )

    return telegram.download_file(
        file_path
    )


# ============================================================
# START MESSAGE
# ============================================================

def send_start_message(
    chat_id: int
) -> None:

    telegram.send_message(

        chat_id,

        """
🥇 Gold Chart Analyzer PRO — V6

🧠 SNRZ Structure Engine

سیستەم بە ئەم ڕیزبەندییە کار دەکات:

VS / VR
↓
ZONE
↓
PULLBACK / RETEST
↓
CONFIRMATION
↓
STRONG SIGNAL CHECK
↓
BUY / SELL

ئەگەر هەر مەرجێک تەواو نەبێت:

🟡 WAIT

و بۆتەکە بە ڕوونی دەڵێت:

🚫 هۆکاری WAIT چییە؟
📍 Zone Price چییە؟
👀 چاوەڕێی چی بکەین؟

هەنگاوی 1️⃣:
📸 H1 یان H4 ـی XAUUSD بنێرە.

هەنگاوی 2️⃣:
📸 M1 یان M5 ـی XAUUSD بنێرە.
""".strip()
    )


# ============================================================
# HELP
# ============================================================

def send_help(
    chat_id: int
) -> None:

    telegram.send_message(

        chat_id,

        """
📚 GOLD CHART ANALYZER V6
━━━━━━━━━━━━━━━━━━

HTF:
H1 / H4

LTF:
M1 / M5

VS:
Support
→ Up
→ New Resistance after Support
→ Up
→ Break New Resistance

VR:
Resistance
→ Down
→ New Support after Resistance
→ Down
→ Break New Support

ZONE:
VS/VR candle + previous candle
→ shorter BODY
→ entire HIGH-to-LOW candle

PULLBACK:
Zone
→ Return / Retest
→ Confirmation

BUY:
RBS / SRR / I.VR / PO2

SELL:
SBR / RSS / I.VS / PO2

STRONG SIGNAL:
Score >= 80
Confidence >= 80%
RR >= 1:2
Valid VS/VR
Valid Zone
Pullback
Confirmation
HTF/LTF agreement

ئەگەر یەکێک لەم مەرجانە نەبێت:

🟡 WAIT
""".strip()
    )


# ============================================================
# MESSAGE HANDLER
# ============================================================

def handle_message(
    message: Dict
) -> None:

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
    # ADMIN COMMANDS FIRST
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
    # ACCESS
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

        send_start_message(
            chat_id
        )

        return

    # --------------------------------------------------------
    # HELP
    # --------------------------------------------------------

    if text == "/help":

        send_help(
            chat_id
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
        # FIRST IMAGE
        # ----------------------------------------------------

        if (
            session.get(
                "zone_image"
            )
            is None
        ):

            session[
                "zone_image"
            ] = photo

            session[
                "updated_at"
            ] = time.time()

            telegram.send_message(

                chat_id,

                """
✅ Chart ـی یەکەم وەرگیرا.

📊 ئەمە وەک H1/H4 مامەڵەی لەگەڵ دەکرێت.

🧠 سەرەتا:
VS / VR
→ Zone

پاشان:
📸 M1 یان M5 بنێرە بۆ Confirmation.
""".strip()
            )

            return

        # ----------------------------------------------------
        # SECOND IMAGE
        # ----------------------------------------------------

        if (
            session.get(
                "confirmation_image"
            )
            is None
        ):

            session[
                "confirmation_image"
            ] = photo

            session[
                "updated_at"
            ] = time.time()

            telegram.send_message(

                chat_id,

                """
⏳ هەردوو chart وەرگیرا.

🧠 V6 SNRZ Engine

VS / VR
↓
Zone
↓
Pullback / Retest
↓
Confirmation
↓
Score / Confidence / RR
↓
BUY / SELL / WAIT

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

                response_text = (
                    format_signal(
                        result
                    )
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
❌ شیکردنەوەکە سەرکەوتوو نەبوو.

هۆکار:
{exc}

تکایە:

/reset

پاشان chart ـەکان بە quality ـی باشتر بنێرە.
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
📸 تکایە chart ـی XAUUSD بنێرە.

هەنگاوی 1:
H1 / H4

هەنگاوی 2:
M1 / M5

یان:

/start
""".strip()
    )


# ============================================================
# UPDATE HANDLER
# ============================================================

def handle_update(
    update: Dict
) -> None:

    callback_query = update.get(
        "callback_query"
    )

    if callback_query:

        handle_access_callback(
            callback_query
        )

        return

    message = update.get(
        "message"
    )

    if message:

        handle_message(
            message
        )


# ============================================================
# TELEGRAM CONNECTION
# ============================================================

def initialize_telegram() -> None:

    me = telegram.get_me()

    logger.info(
        "Telegram connected: @%s",
        me.get(
            "username"
        )
    )

    telegram.delete_webhook(
        drop_pending_updates=False
    )

    logger.info(
        "Telegram webhook removed."
    )


# ============================================================
# MAIN POLLING LOOP
# ============================================================

def run() -> None:

    logger.info(
        "=========================================="
    )

    logger.info(
        "Gold Chart Analyzer PRO V6 starting..."
    )

    logger.info(
        "Gemini primary: %s",
        GEMINI_MODEL
    )

    logger.info(
        "Gemini fallback: %s",
        GEMINI_FALLBACK_MODEL
    )

    logger.info(
        "Admin ID: %s",
        ADMIN_USER_ID
    )

    logger.info(
        "Allowed users: %s",
        len(ALLOWED_USER_IDS)
    )

    logger.info(
        "Minimum score: %s",
        MIN_STRONG_SCORE
    )

    logger.info(
        "Minimum confidence: %s%%",
        MIN_STRONG_CONFIDENCE
    )

    logger.info(
        "Minimum RR: 1:%s",
        MIN_RR
    )

    logger.info(
        "=========================================="
    )

    initialize_telegram()

    offset = None

    consecutive_errors = 0

    while True:

        try:

            cleanup_sessions()

            updates = telegram.get_updates(

                offset=offset,

                timeout=TELEGRAM_POLL_TIMEOUT
            )

            consecutive_errors = 0

            for update in updates:

                update_id = update.get(
                    "update_id"
                )

                if (
                    update_id
                    is not None
                ):

                    offset = (
                        update_id + 1
                    )

                try:

                    handle_update(
                        update
                    )

                except TelegramConflictError:

                    raise

                except Exception:

                    logger.exception(
                        "Update handling error."
                    )

        except TelegramConflictError:

            logger.error(
                "=========================================="
            )

            logger.error(
                "TELEGRAM 409 CONFLICT"
            )

            logger.error(
                "Another instance of this bot "
                "is using the same token."
            )

            logger.error(
                "Stop the other process/container."
            )

            logger.error(
                "=========================================="
            )

            time.sleep(
                15
            )

        except TelegramAPIError as exc:

            consecutive_errors += 1

            delay = min(
                60,
                5 * consecutive_errors
            )

            logger.error(
                "Telegram API error: %s",
                exc
            )

            logger.info(
                "Retrying in %s seconds...",
                delay
            )

            time.sleep(
                delay
            )

        except KeyboardInterrupt:

            logger.info(
                "Bot stopped manually."
            )

            break

        except Exception:

            consecutive_errors += 1

            delay = min(
                60,
                5 * consecutive_errors
            )

            logger.exception(
                "Unexpected polling error."
            )

            time.sleep(
                delay
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    run()
