# ============================================================
# FORMAT SIGNAL — SORANI KURDISH
# ============================================================

def format_signal(data):

    signal = str(
        data.get(
            "signal",
            "WAIT"
        )
    ).upper()

    if signal == "BUY":
        title = "🟢 سیگناڵی STRONG BUY"

    elif signal == "SELL":
        title = "🔴 سیگناڵی STRONG SELL"

    else:
        title = "🟡 چاوەڕوان بە"
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

📊 خاڵ:
{data.get("score", 0)}/100

💪 دڵنیایی:
{data.get("confidence", 0)}%

📈 ئاراستە:
{data.get("trend", "N/A")}

🧠 پێکهاتە:
{data.get("setup", "N/A")}

🟦 Zone:
{data.get("zone", "N/A")}

📍 نرخی Zone:
{zone_price}

🔎 Zone ـەکانی HTF:
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
🔎 هۆکاری شیکردنەوە:
{data.get("reasoning", "هیچ زانیارییەک بەردەست نییە.")}

✅ پشکنینەکان:
{data.get("checks", "هیچ زانیارییەک بەردەست نییە.")}
"""

    if signal == "WAIT":

        text += f"""
━━━━━━━━━━━━━━
🚫 هۆکاری چاوەڕوانبوون:
{data.get(
    "rejection_reason",
    "پێکهاتەیەکی بەهێزی SNRZ پشتڕاست نەکراوەتەوە."
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
🟢 پێکهاتەی STRONG SNRZ پشتڕاست کراوەتەوە.

⚠️ ئەمە تەنها شیکردنەوەی تەکنیکییە؛
هیچ دڵنیاییەک بە قازانج نادات.
"""

    return text.strip()
12:30 AM
# ============================================================
# gold_chart_analyzer.py
# SNRZ GOLD CHART ANALYZER PRO
# ADMIN + ACCESS REQUEST SYSTEM + ALLOWED USERS
#
# SNRZ VERIFICATION ENGINE V3
# STRUCTURED VS / VR EVIDENCE
# I.VS / I.VR CONFIRMATION SUPPORT
# PULLBACK -> CONFIRMATION ORDER CHECK
# STRONG SIGNAL ENGINE V3
# ============================================================

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

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    ""
).strip()

GEMINI_MODEL = "gemini-3.6-flash"


# ============================================================
# ADMIN
# ============================================================

ADMIN_USER_ID = 5874840448


# ============================================================
# ACCESS DATABASE
# ============================================================

ACCESS_FILE = "allowed_users.json"


def load_allowed_users():

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

        for user_id in data:

            try:
                users.add(
                    int(user_id)
                )

            except (
                ValueError,
                TypeError
            ):
                pass

        users.add(
            ADMIN_USER_ID
        )

        return users

    except Exception:

        logging.exception(
            "Could not load allowed users."
        )

        return default_users


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

        logging.exception(
            "Could not save allowed users."
        )


ALLOWED_USER_IDS = load_allowed_users()


# ============================================================
# ACCESS REQUESTS
# ============================================================

PENDING_ACCESS_REQUESTS = {}
ACCESS_CODES = {}


# ============================================================
# CONFIG CHECK
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
# STRONG SIGNAL SETTINGS
# ============================================================

MIN_STRONG_SCORE = 80
MIN_STRONG_CONFIDENCE = 80
MIN_RR = 2.0


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(
    "GoldChartAnalyzer"
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


class TelegramBot:

    def __init__(
        self,
        token
    ):

        self.token = token

        self.base_url = (
            f"https://api.telegram.org/bot{token}"
        )


    def call(
        self,
        method,
        data=None,
        timeout=60
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

            response.raise_for_status()

            result = response.json()

            if not result.get(
                "ok"
            ):

                raise TelegramAPIError(
                    result.get(
                        "description",
                        "Telegram API error"
                    )
                )

            return result["result"]

        except requests.RequestException as exc:

            raise TelegramAPIError(
                f"Telegram request failed: {exc}"
            ) from exc


    def get_me(self):

        return self.call(
            "getMe"
        )


    def delete_webhook(self):

        return self.call(
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
        chat_id,
        text
    ):

        max_length = 4000

        if not isinstance(
            text,
            str
        ):

            text = str(text)

        if len(text) <= max_length:

            return self.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": text
                }
            )

        results = []

        for i in range(
            0,
            len(text),
            max_length
        ):

            chunk = text[
                i:i + max_length
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


    def answer_callback_query(
        self,
        callback_query_id,
        text=None
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
        chat_id,
        message_id,
        reply_markup=None
    ):

        data = {
            "chat_id": chat_id,
            "message_id": message_id
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
        file_id
    ):

        return self.call(
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
            f"https://api.telegram.org/file/bot"
            f"{self.token}/{file_path}"
        )

        response = requests.get(
            url,
            timeout=60
        )

        response.raise_for_status()

        return response.content


telegram = TelegramBot(
    TELEGRAM_BOT_TOKEN
)


# ============================================================
# USER SESSIONS
# ============================================================

USER_SESSIONS = {}


# ============================================================
# ACCESS CONTROL
# ============================================================

def is_admin(
    user_id
):

    return user_id == ADMIN_USER_ID


def is_allowed(
    user_id
):

    return (
        user_id in ALLOWED_USER_IDS
    )


def deny_access(
    chat_id
):

    telegram.send_message(

        chat_id,

        """
⛔ دەستگەیشتن ڕەتکرایەوە.

تۆ هێشتا ڕێگەپێدراوی بەکارهێنانی
Gold Chart Analyzer PRO نیت.

بۆ داواکاریی دەستڕاگەیشتن:
🔑 /start
""".strip()
    )


# ============================================================
# ACCESS CODE
# ============================================================

def generate_access_code():

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
# SEND ACCESS REQUEST
# ============================================================

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

    last_name = user.get(
        "last_name",
        ""
    )

    username = user.get(
        "username",
        ""
    )


    if is_allowed(
        user_id
    ):

        return False


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

        return True


    code = generate_access_code()


    PENDING_ACCESS_REQUESTS[
        user_id
    ] = {

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
            username
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


    return True


# ============================================================
# ACCESS CALLBACK
# ============================================================

def handle_access_callback(
    callback_query
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

            "⚠️ ئەم Access Code ـە نییە یان بەسەرچووە."
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

            "⚠️ ئەم داواکارییە پێشتر مامەڵەی لەگەڵ کراوە."
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

        telegram.send_message(

            user_id,

            """
✅ ڕێگەپێدراویت!

━━━━━━━━━━━━━━━━━━

🥇 Gold Chart Analyzer PRO

🧠 SNRZ Structure Engine V3 چالاکە.

ئێستا دەتوانیت بۆتەکە بەکاربهێنیت.

📸 H1 یان H4 ـی XAUUSD بنێرە.
""".strip()
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

        telegram.send_message(

            user_id,

            """
❌ داواکارییەکەت ڕەتکرایەوە.

بۆ بەکارهێنانی
Gold Chart Analyzer PRO
پێویستە Admin ڕێگەپێدانت پێبدات.
""".strip()
        )

        return


# ============================================================
# ADMIN COMMANDS
# ============================================================

def handle_admin_command(
    message,
    chat_id,
    text
):

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


        telegram.send_message(

            chat_id,

            f"""
✅ بەکارهێنەر زیادکرا.

👤 User ID:
{new_user_id}

👥 کۆی بەکارهێنەرە ڕێگەپێدراوەکان:
{len(ALLOWED_USER_IDS)}
""".strip()
        )

        return True


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


    if text == "/users":

        users = sorted(
            ALLOWED_USER_IDS
        )

        user_lines = []

        for uid in users:

            if uid == ADMIN_USER_ID:

                user_lines.append(
                    f"👑 {uid} — ADMIN"
                )

            else:

                user_lines.append(
                    f"👤 {uid}"
                )


        telegram.send_message(

            chat_id,

            "👥 ALLOWED USERS\n"
            "━━━━━━━━━━━━━━\n"
            + "\n".join(
                user_lines
            )
            + "\n\n"
            + f"Total: {len(users)}"
        )

        return True


    if text == "/pending":

        if not PENDING_ACCESS_REQUESTS:

            telegram.send_message(

                chat_id,

                """
📭 هیچ Access Request ـێکی چاوەڕوان نییە.
""".strip()
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
            + "\n".join(
                lines
            )
        )

        return True


    if text == "/admin":

        telegram.send_message(

            chat_id,

            """
👑 ADMIN PANEL
━━━━━━━━━━━━━━━━━━

➕ زیادکردنی بەکارهێنەر:

/adduser USER_ID

➖ سڕینەوەی بەکارهێنەر:

/removeuser USER_ID

👥 لیستی بەکارهێنەران:

/users

⏳ داواکارییە چاوەوانەکان:

/pending

📢 ناردنی پەیام بۆ هەموو بەکارهێنەران:

/broadcast YOUR MESSAGE

━━━━━━━━━━━━━━━━━━

🔐 Access Request ـەکان:
تەنها Admin دەتوانێت
Approve / Reject بکات.
""".strip()
        )

        return True


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


    return False


# ============================================================
# SNRZ SYSTEM PROMPT — V3
# ============================================================

SYSTEM_PROMPT = r"""
You are an ELITE XAUUSD SNRZ STRUCTURE ANALYST.

Your priority is STRUCTURAL ACCURACY.

You must be extremely selective.

Do NOT create BUY or SELL signals simply because a chart
looks bullish or bearish.

The structure must be VISUALLY PROVEN.

============================================================
LANGUAGE
============================================================

ALL explanatory text inside JSON must be written in
Sorani Kurdish.

These technical names must remain EXACTLY in English:

VS
VR
I.VS
I.VR
RBS
SBR
SRR
RSS
PO2
Zone
Entry
SL
TP
RR
BUY
SELL
WAIT
H1
H4
M1
M5
HTF
LTF

============================================================
IMAGE ORDER
============================================================

IMAGE 1 = H1/H4 HTF chart.

IMAGE 2 = M1/M5 LTF confirmation chart.

The first image determines the HTF structure.

The second image determines Pullback / Confirmation.

============================================================
ABSOLUTE VISUAL RULE
============================================================

You must inspect visible candles from LEFT TO RIGHT.

Do not infer hidden candles.

Do not invent missing candles.

Do not assume a breakout.

Do not assume a breakdown.

Do not use current price alone as proof of a historical break.

Do not use approximate levels as proof.

Do not use a wick alone as a break.

Do not use a touch as a break.

Do not use rejection as a break.

Only visually supported evidence can be marked true.

============================================================
IMPORTANT V3 CHANGE
============================================================

You MUST return STRUCTURED EVIDENCE.

Do not rely only on a natural-language sequence.

Every VS and VR candidate must contain explicit boolean
evidence fields.

A structure is valid ONLY if the required evidence fields
are all true.

============================================================
VS — VALID SUPPORT
============================================================

Required chronological structure:

1. ORIGINAL Support exists.

2. Price moves UP from that Support.

3. A NEW Resistance forms AFTER the original Support.

4. Price moves UP AGAIN after the new Resistance.

5. Price BREAKS ABOVE THAT SAME NEW Resistance.

Then:

original Support = VS.

The Resistance formed BEFORE the Support is irrelevant.

The validation Resistance MUST be created AFTER the
original Support.

============================================================
VS REQUIRED EVIDENCE
============================================================

For a valid VS:

"original_level_visible" = true

"first_move_confirmed" = true

"new_level_formed_after_original" = true

"second_move_confirmed" = true

"same_level_broken" = true

"break_confirmed" = true

"valid" = true

If any one is false:

valid = false

break_confirmed = false

============================================================
VS BREAK
============================================================

A valid break requires visible price movement above the
SAME new Resistance.

Not enough:

touch

wick

rejection

equal high

approximate high

unclear candle

current price above level without historical proof

The break candle must be visually identifiable.

If unsure:

break_confirmed = false

same_level_broken = false

valid = false

============================================================
VR — VALID RESISTANCE
============================================================

Required chronological structure:

1. ORIGINAL Resistance exists.

2. Price moves DOWN from that Resistance.

3. A NEW Support forms AFTER the original Resistance.

4. Price moves DOWN AGAIN after the new Support.

5. Price BREAKS BELOW THAT SAME NEW Support.

Then:

original Resistance = VR.

The Support formed BEFORE the Resistance is irrelevant.

The validation Support MUST be created AFTER the
original Resistance.

============================================================
VR REQUIRED EVIDENCE
============================================================

For a valid VR:

"original_level_visible" = true

"first_move_confirmed" = true

"new_level_formed_after_original" = true

"second_move_confirmed" = true

"same_level_broken" = true

"break_confirmed" = true

"valid" = true

If any one is false:

valid = false

break_confirmed = false

============================================================
VR BREAK
============================================================

A valid break requires visible price movement below the
SAME new Support.

Not enough:

touch

wick

rejection

approximate low

unclear candle

current price below level without historical proof

The break candle must be visually identifiable.

If unsure:

break_confirmed = false

same_level_broken = false

valid = false

============================================================
BOTH STRUCTURES MUST ALWAYS BE SCANNED
============================================================

Always scan:

VS

AND

VR

Even if one appears obvious.

Even if the expected signal is BUY.

Even if the expected signal is SELL.

Even if the final answer is WAIT.

============================================================
STRUCTURE DATA
============================================================

For VS return:

original_level
formation_candle
validation_level
break_price
break_candle
sequence

For VR return:

original_level
formation_candle
validation_level
break_price
break_candle
sequence

Use "N/A" if not visibly known.

Never invent a price.

============================================================
ZONE
============================================================

Zone exists ONLY after a valid VS or valid VR.

After a valid VS/VR:

1. Identify the candle where the original VS/VR is formed.

2. Identify the immediately previous candle.

3. Compare BODY SIZE.

4. Select the SHORTER BODY candle.

5. Zone = complete HIGH-to-LOW range of that candle.

Do NOT use only the body.

Do NOT use engulfing.

Do NOT use Bullish Engulfing.

Do NOT use Bearish Engulfing.

Return:

zone_source_candle

zone_high

zone_low

zone_price

If the structure is invalid:

zone = "N/A"

zone_price = "N/A"

zone_high = "N/A"

zone_low = "N/A"

============================================================
PULLBACK
============================================================

The required order is:

VALID VS/VR
→ Zone
→ Price Pullback / Retest
→ M1/M5 Confirmation
→ Strong Signal
→ Entry

Confirmation before Pullback is invalid.

Return:

pullback_confirmed
confirmation_after_pullback

Both must be true for BUY or SELL.

============================================================
BUY
============================================================

BUY must use valid VS.

Allowed LTF confirmations:

RBS
SRR
I.VR
PO2

============================================================
SELL
============================================================

SELL must use valid VR.

Allowed LTF confirmations:

SBR
RSS
I.VS
PO2

============================================================
I.VS / I.VR
============================================================

Treat I.VS and I.VR as technical confirmation names only.

Do NOT invent additional definitions.

If clearly visible and valid according to the chart,
report the exact name.

BUY can use I.VR.

SELL can use I.VS.

============================================================
HTF / LTF AGREEMENT
============================================================

Return:

"htf_ltf_agreement": true or false

The signal cannot be STRONG unless this is true.

============================================================
NO REJECTION
============================================================

Return:

"no_rejection": true or false

If there is strong rejection against the proposed entry:

no_rejection = false

Then signal must be WAIT.

============================================================
STRONG SIGNAL
============================================================

BUY or SELL ONLY when ALL are true:

valid VS or VR

valid Zone

price reached/retested Zone

Pullback confirmed

confirmation_after_pullback = true

valid LTF confirmation

HTF/LTF agreement

logical Entry

logical SL

logical TP

RR >= 1:2

Score >= 80

Confidence >= 80

no_rejection = true

If ANY condition is missing:

WAIT.

============================================================
WAIT
============================================================

WAIT when:

structure incomplete

break unclear

valid VS/VR missing

Zone missing

price has not returned to Zone

Pullback missing

Confirmation missing

Confirmation occurred before Pullback

HTF/LTF disagreement

rejection present

RR < 1:2

Score < 80

Confidence < 80

============================================================
IMPORTANT
============================================================

Never downgrade a visually proven structure just because
a natural-language sentence is imperfect.

The boolean evidence fields are authoritative.

However, do NOT mark evidence true unless the chart
visually supports it.

============================================================
JSON
============================================================

Return ONLY valid JSON.

Use EXACTLY this structure:

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
  "zone_high": "...",
  "zone_low": "...",
  "zone_source_candle": "...",

  "htf_zones": "...",

  "vs_detected": {
    "valid": false,
    "original_level": "...",
    "formation_candle": "...",
    "validation_level": "...",
    "break_price": "...",
    "break_candle": "...",
    "sequence": "...",

    "original_level_visible": false,
    "first_move_confirmed": false,
    "new_level_formed_after_original": false,
    "second_move_confirmed": false,
    "same_level_broken": false,
    "break_confirmed": false
  },

  "vr_detected": {
    "valid": false,
    "original_level": "...",
    "formation_candle": "...",
    "validation_level": "...",
    "break_price": "...",
    "break_candle": "...",
    "sequence": "...",

    "original_level_visible": false,
    "first_move_confirmed": false,
    "new_level_formed_after_original": false,
    "second_move_confirmed": false,
    "same_level_broken": false,
    "break_confirmed": false
  },

  "pullback_confirmed": false,
  "confirmation_after_pullback": false,
  "htf_ltf_agreement": false,
  "no_rejection": false,

  "confirmation": "...",
  "trend": "...",
  "reasoning": "...",
  "checks": "...",
  "rejection_reason": "...",
  "wait_for": "..."
}

============================================================
FINAL RULE
============================================================

STRUCTURE FIRST.

VISUAL EVIDENCE
→ VS / VR V3 VERIFICATION
→ Zone
→ Pullback
→ LTF Confirmation
→ HTF/LTF Agreement
→ Strong Signal Filters
→ BUY / SELL

Otherwise:

WAIT.
"""


# ============================================================
# USER PROMPT
# ============================================================

USER_ANALYSIS_PROMPT = r"""
هەردوو وێنەی XAUUSD بە وردی و بە شێوەیەکی
VISUAL / STRUCTURED شیکەرەوە.

IMAGE 1 = H1/H4
IMAGE 2 = M1/M5

============================================================
H1/H4
============================================================

هەموو candle ـە دیارەکان لە چەپ بۆ ڕاست پشکنە.

سەرەتا VS بدۆزەرەوە.

پاشان VR بدۆزەرەوە.

هەردووکیان بە جیاوازی verify بکە.

بەتایبەتی:

VS:

Support
→ Up
→ NEW Resistance AFTER Support
→ Up AGAIN
→ BREAK SAME Resistance
→ VS

VR:

Resistance
→ Down
→ NEW Support AFTER Resistance
→ Down AGAIN
→ BREAK SAME Support
→ VR

============================================================
IMPORTANT
============================================================

بۆ هەر structure ـێک boolean evidence ـەکان بە ڕاستی
لەسەر chart پڕبکەرەوە.

هیچ evidence ـێک بە guessing true مەکە.

ئەگەر breakout بە ڕوونی نادیارە:

break_confirmed = false
same_level_broken = false
valid = false

ئەگەر breakout بە ڕوونی دیارە:

break_confirmed = true
same_level_broken = true

ئەگەر هەموو sequence ـەکە تەواوە:

valid = true

============================================================
ZONE
============================================================

دوای valid VS/VR:

کەندڵی formation دیاری بکە.

کەندڵی پێش formation دیاری بکە.

BODY SIZE بەراورد بکە.

کەندڵی BODY ـی کورتتر هەڵبژێرە.

تەواوی HIGH تا LOW ـی ئەو candle ـە Zone ـە.

============================================================
M1/M5
============================================================

پشکنین بکە:

Pullback / Retest

پاشان Confirmation.

Confirmation پێش Pullback قبوڵ مەکە.

BUY:

RBS
SRR
I.VR
PO2

SELL:

SBR
RSS
I.VS
PO2

============================================================
STRONG SIGNAL
============================================================

تەنها کاتێک BUY/SELL:

Score >= 80
Confidence >= 80
RR >= 1:2
Valid VS/VR
Valid Zone
Pullback
Confirmation after Pullback
HTF/LTF agreement
No rejection
Entry
SL
TP

ئەگەر یەکێک نەبێت:

WAIT.

Return ONLY valid JSON.
"""


# ============================================================
# JSON CLEANER
# ============================================================

def clean_json(
    text
):

    if not text:

        raise RuntimeError(
            "Gemini returned an empty response."
        )

    text = str(
        text
    ).strip()

    text = text.replace(
        "```json",
        ""
    )

    text = text.replace(
        "```JSON",
        ""
    )

    text = text.replace(
        "```",
        ""
    )

    start = text.find(
        "{"
    )

    end = text.rfind(
        "}"
    )

    if start == -1 or end == -1:

        raise RuntimeError(
            "Gemini did not return valid JSON."
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

        value = str(
            value
        )

        value = value.replace(
            ",",
            ""
        )

        match = re.search(
            r"-?\d+(?:\.\d+)?",
            value
        )

        if not match:

            return None

        return float(
            match.group()
        )

    except Exception:

        return None


# ============================================================
# SAFE BOOL
# ============================================================

def safe_bool(
    value
):

    if isinstance(
        value,
        bool
    ):

        return value

    if isinstance(
        value,
        (int, float)
    ):

        return value != 0

    if value is None:

        return False

    text = str(
        value
    ).strip().upper()

    return text in (
        "TRUE",
        "YES",
        "Y",
        "1",
        "VALID",
        "CONFIRMED",
        "بەڵێ"
    )


# ============================================================
# NORMALIZE STRUCTURE
# ============================================================

def normalize_structure(
    structure
):

    if not isinstance(
        structure,
        dict
    ):

        structure = {}


    normalized = dict(
        structure
    )


    boolean_fields = [

        "valid",

        "original_level_visible",

        "first_move_confirmed",

        "new_level_formed_after_original",

        "second_move_confirmed",

        "same_level_broken",

        "break_confirmed"
    ]


    for field in boolean_fields:

        normalized[field] = safe_bool(
            normalized.get(
                field,
                False
            )
        )


    string_fields = [

        "original_level",

        "formation_candle",

        "validation_level",

        "break_price",

        "break_candle",

        "sequence"
    ]


    for field in string_fields:

        value = normalized.get(
            field,
            "N/A"
        )

        if value is None:

            value = "N/A"

        value = str(
            value
        ).strip()

        if not value:

            value = "N/A"

        normalized[field] = value


    return normalized


# ============================================================
# STRUCTURE EVIDENCE SCORE
# ============================================================

def structure_evidence_score(
    structure
):

    structure = normalize_structure(
        structure
    )

    fields = [

        "original_level_visible",

        "first_move_confirmed",

        "new_level_formed_after_original",

        "second_move_confirmed",

        "same_level_broken",

        "break_confirmed"
    ]

    return sum(
        1
        for field in fields
        if structure.get(
            field,
            False
        )
    )


# ============================================================
# VERIFY VS — ENGINE V3
# ============================================================

def verify_vs_v3(
    vs_data
):

    vs_data = normalize_structure(
        vs_data
    )


    # --------------------------------------------------------
    # REQUIRED EVIDENCE
    # --------------------------------------------------------

    required = [

        "original_level_visible",

        "first_move_confirmed",

        "new_level_formed_after_original",

        "second_move_confirmed",

        "same_level_broken",

        "break_confirmed"
    ]


    for field in required:

        if not vs_data.get(
            field,
            False
        ):

            return False


    # --------------------------------------------------------
    # VALID MUST ALSO BE TRUE
    # --------------------------------------------------------

    if not vs_data.get(
        "valid",
        False
    ):

        return False


    # --------------------------------------------------------
    # REQUIRED DATA
    # --------------------------------------------------------

    original_level = safe_float(
        vs_data.get(
            "original_level"
        )
    )

    validation_level = safe_float(
        vs_data.get(
            "validation_level"
        )
    )


    if original_level is None:

        return False


    if validation_level is None:

        return False


    # --------------------------------------------------------
    # VS CHRONOLOGY
    #
    # The NEW Resistance must be above original Support.
    # --------------------------------------------------------

    if validation_level <= original_level:

        return False


    # --------------------------------------------------------
    # FORMATION / BREAK EVIDENCE
    # --------------------------------------------------------

    formation = str(
        vs_data.get(
            "formation_candle",
            ""
        )
    ).strip()

    break_candle = str(
        vs_data.get(
            "break_candle",
            ""
        )
    ).strip()


    if formation.upper() in (
        "",
        "N/A",
        "NONE",
        "UNKNOWN",
        "NULL",
        "..."
    ):

        return False


    if break_candle.upper() in (
        "",
        "N/A",
        "NONE",
        "UNKNOWN",
        "NULL",
        "..."
    ):

        return False


    # --------------------------------------------------------
    # BREAK PRICE
    # --------------------------------------------------------

    break_price = safe_float(
        vs_data.get(
            "break_price"
        )
    )


    if break_price is None:

        return False


    if break_price <= validation_level:

        return False


    return True


# ============================================================
# VERIFY VR — ENGINE V3
# ============================================================

def verify_vr_v3(
    vr_data
):

    vr_data = normalize_structure(
        vr_data
    )


    # --------------------------------------------------------
    # REQUIRED EVIDENCE
    # --------------------------------------------------------

    required = [

        "original_level_visible",

        "first_move_confirmed",

        "new_level_formed_after_original",

        "second_move_confirmed",

        "same_level_broken",

        "break_confirmed"
    ]


    for field in required:

        if not vr_data.get(
            field,
            False
        ):

            return False


    # --------------------------------------------------------
    # VALID MUST ALSO BE TRUE
    # --------------------------------------------------------

    if not vr_data.get(
        "valid",
        False
    ):

        return False


    # --------------------------------------------------------
    # REQUIRED DATA
    # --------------------------------------------------------

    original_level = safe_float(
        vr_data.get(
            "original_level"
        )
    )

    validation_level = safe_float(
        vr_data.get(
            "validation_level"
        )
    )


    if original_level is None:

        return False


    if validation_level is None:

        return False


    # --------------------------------------------------------
    # VR CHRONOLOGY
    #
    # The NEW Support must be below original Resistance.
    # --------------------------------------------------------

    if validation_level >= original_level:

        return False


    # --------------------------------------------------------
    # FORMATION / BREAK EVIDENCE
    # --------------------------------------------------------

    formation = str(
        vr_data.get(
            "formation_candle",
            ""
        )
    ).strip()

    break_candle = str(
        vr_data.get(
            "break_candle",
            ""
        )
    ).strip()


    if formation.upper() in (
        "",
        "N/A",
        "NONE",
        "UNKNOWN",
        "NULL",
        "..."
    ):

        return False


    if break_candle.upper() in (
        "",
        "N/A",
        "NONE",
        "UNKNOWN",
        "NULL",
        "..."
    ):

        return False


    # --------------------------------------------------------
    # BREAK PRICE
    # --------------------------------------------------------

    break_price = safe_float(
        vr_data.get(
            "break_price"
        )
    )


    if break_price is None:

        return False


    if break_price >= validation_level:

        return False


    return True


# ============================================================
# VALID STRUCTURE CHECK
# ============================================================

def get_valid_structures(
    data
):

    vs_data = normalize_structure(
        data.get(
            "vs_detected",
            {}
        )
    )

    vr_data = normalize_structure(
        data.get(
            "vr_detected",
            {}
        )
    )


    vs_valid = verify_vs_v3(
        vs_data
    )

    vr_valid = verify_vr_v3(
        vr_data
    )


    data[
        "vs_detected"
    ] = vs_data

    data[
        "vr_detected"
    ] = vr_data


    return (
        vs_valid,
        vr_valid
    )


# ============================================================
# CONFIRMATION VALIDATION
# ============================================================

def confirmation_is_valid(
    signal,
    confirmation
):

    signal = str(
        signal
    ).upper()

    confirmation = str(
        confirmation
        or ""
    ).upper()


    if signal == "BUY":

        return (
            "RBS" in confirmation
            or
            "SRR" in confirmation
            or
            "I.VR" in confirmation
            or
            "PO2" in confirmation
        )


    if signal == "SELL":

        return (
            "SBR" in confirmation
            or
            "RSS" in confirmation
            or
            "I.VS" in confirmation
            or
            "PO2" in confirmation
        )


    return False


# ============================================================
# ZONE VALIDATION
# ============================================================

def zone_is_valid(
    data,
    vs_valid,
    vr_valid
):

    if not (
        vs_valid
        or
        vr_valid
    ):

        return False


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


    zone_high = safe_float(
        data.get(
            "zone_high"
        )
    )

    zone_low = safe_float(
        data.get(
            "zone_low"
        )
    )


    if zone.upper() in (
        "",
        "N/A",
        "NONE",
        "UNKNOWN",
        "NULL"
    ):

        return False


    if zone_price.upper() in (
        "",
        "N/A",
        "NONE",
        "UNKNOWN",
        "NULL"
    ):

        return False


    if zone_high is None:

        return False


    if zone_low is None:

        return False


    if zone_high <= zone_low:

        return False


    source_candle = str(
        data.get(
            "zone_source_candle",
            ""
        )
    ).strip()


    if source_candle.upper() in (
        "",
        "N/A",
        "NONE",
        "UNKNOWN",
        "NULL"
    ):

        return False


    return True


# ============================================================
# RR CALCULATOR
# ============================================================

def calculate_rr(
    data
):

    signal = str(
        data.get(
            "signal",
            "WAIT"
        )
    ).upper()

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
# STRONG SIGNAL ENGINE V3
# ============================================================

def strong_signal_engine(
    data
):

    if not isinstance(
        data,
        dict
    ):

        data = {}


    # ========================================================
    # NORMALIZE BASIC DATA
    # ========================================================

    signal = str(
        data.get(
            "signal",
            "WAIT"
        )
    ).upper().strip()


    score = safe_float(
        data.get(
            "score",
            0
        )
    )

    confidence = safe_float(
        data.get(
            "confidence",
            0
        )
    )


    if score is None:

        score = 0


    if confidence is None:

        confidence = 0


    confirmation = str(
        data.get(
            "confirmation",
            ""
        )
    )


    # ========================================================
    # NORMALIZE STRUCTURES
    # ========================================================

    vs_valid, vr_valid = (
        get_valid_structures(
            data
        )
    )


    data[
        "vs_detected"
    ][
        "engine_valid"
    ] = vs_valid


    data[
        "vr_detected"
    ][
        "engine_valid"
    ] = vr_valid


    data[
        "vs_detected"
    ][
        "evidence_score"
    ] = structure_evidence_score(
        data["vs_detected"]
    )


    data[
        "vr_detected"
    ][
        "evidence_score"
    ] = structure_evidence_score(
        data["vr_detected"]
    )


    # ========================================================
    # STRUCTURE STATUS
    # ========================================================

    if not vs_valid and not vr_valid:

        data[
            "zone"
        ] = "N/A"

        data[
            "zone_price"
        ] = "N/A"

        data[
            "zone_high"
        ] = "N/A"

        data[
            "zone_low"
        ] = "N/A"

        data[
            "zone_source_candle"
        ] = "N/A"


    # ========================================================
    # ZONE
    # ========================================================

    valid_zone = zone_is_valid(
        data,
        vs_valid,
        vr_valid
    )


    # ========================================================
    # PULLBACK
    # ========================================================

    pullback_confirmed = safe_bool(
        data.get(
            "pullback_confirmed",
            False
        )
    )


    confirmation_after_pullback = safe_bool(
        data.get(
            "confirmation_after_pullback",
            False
        )
    )


    htf_ltf_agreement = safe_bool(
        data.get(
            "htf_ltf_agreement",
            False
        )
    )


    no_rejection = safe_bool(
        data.get(
            "no_rejection",
            False
        )
    )


    # ========================================================
    # REJECTION LIST
    # ========================================================

    rejection_reasons = []


    # ========================================================
    # SIGNAL TYPE
    # ========================================================

    if signal not in (
        "BUY",
        "SELL",
        "WAIT"
    ):

        rejection_reasons.append(
            "جۆری سیگناڵ نادروستە."
        )

        signal = "WAIT"


    # ========================================================
    # AI WAIT
    # ========================================================

    if signal == "WAIT":

        rejection_reasons.append(
            "AI هیچ setup ـێکی STRONG پشتڕاست نەکردووەتەوە."
        )


    # ========================================================
    # SCORE
    # ========================================================

    if score < MIN_STRONG_SCORE:

        rejection_reasons.append(
            f"Score = {score:.0f}/100 ـە؛ "
            f"پێویستە کەمترین {MIN_STRONG_SCORE}/100 بێت."
        )


    # ========================================================
    # CONFIDENCE
    # ========================================================

    if confidence < MIN_STRONG_CONFIDENCE:

        rejection_reasons.append(
            f"Confidence = {confidence:.0f}% ـە؛ "
            f"پێویستە کەمترین {MIN_STRONG_CONFIDENCE}% بێت."
        )


    # ========================================================
    # BUY STRUCTURE
    # ========================================================

    if signal == "BUY":

        if not vs_valid:

            rejection_reasons.append(
                "BUY پێویستی بە VS ـی تەواو و V3 verified هەیە."
            )


    # ========================================================
    # SELL STRUCTURE
    # ========================================================

    if signal == "SELL":

        if not vr_valid:

            rejection_reasons.append(
                "SELL پێویستی بە VR ـی تەواو و V3 verified هەیە."
            )


    # ========================================================
    # ZONE
    # ========================================================

    if not valid_zone:

        if vs_valid or vr_valid:

            rejection_reasons.append(
                "VS/VR هەیە، بەڵام Zone بە شێوەی دروست پشتڕاست نەکراوەتەوە."
            )

        else:

            rejection_reasons.append(
                "هیچ VS یان VR ـێکی V3 verified نییە."
            )


    # ========================================================
    # PULLBACK
    # ========================================================

    if signal in (
        "BUY",
        "SELL"
    ):

        if not pullback_confirmed:

            rejection_reasons.append(
                "نرخ هێشتا Pullback / Retest ـی Zone پشتڕاست نەکردووەتەوە."
            )


    # ========================================================
    # CONFIRMATION AFTER PULLBACK
    # ========================================================

    if signal in (
        "BUY",
        "SELL"
    ):

        if not confirmation_after_pullback:

            rejection_reasons.append(
                "Confirmation دوای Pullback بە ڕوونی پشتڕاست نەکراوەتەوە."
            )


    # ========================================================
    # CONFIRMATION TYPE
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
                "Confirmation ـەکە لەگەڵ SNRZ ـی ئەم ئاراستەیە ناگونجێت."
            )


    # ========================================================
    # HTF / LTF AGREEMENT
    # ========================================================

    if signal in (
        "BUY",
        "SELL"
    ):

        if not htf_ltf_agreement:

            rejection_reasons.append(
                "HTF و LTF یەک ئاراستە پشتڕاست نەدەکەن."
            )


    # ========================================================
    # REJECTION
    # ========================================================

    if signal in (
        "BUY",
        "SELL"
    ):

        if not no_rejection:

            rejection_reasons.append(
                "Rejection ـێکی دژ بە Entry هەیە یان بە ڕوونی ڕەت نەکراوەتەوە."
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
        ).strip()

        sl = str(
            data.get(
                "sl",
                "N/A"
            )
        ).strip()

        tp1 = str(
            data.get(
                "tp1",
                "N/A"
            )
        ).strip()


        if entry.upper() in (
            "",
            "N/A",
            "NONE",
            "UNKNOWN",
            "NULL"
        ):

            rejection_reasons.append(
                "Entry دیاری نەکراوە."
            )


        if sl.upper() in (
            "",
            "N/A",
            "NONE",
            "UNKNOWN",
            "NULL"
        ):

            rejection_reasons.append(
                "SL دیاری نەکراوە."
            )


        if tp1.upper() in (
            "",
            "N/A",
            "NONE",
            "UNKNOWN",
            "NULL"
        ):

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
                "RR بە شێوەی دروست حساب نەکرا."
            )

        elif calculated_rr < MIN_RR:

            rejection_reasons.append(
                f"RR = 1:{calculated_rr:.2f} ـە؛ "
                "کەمترە لە 1:2."
            )


    # ========================================================
    # FINAL DECISION
    # ========================================================

    if rejection_reasons:

        data[
            "signal"
        ] = "WAIT"


        data[
            "entry"
        ] = "N/A"

        data[
            "sl"
        ] = "N/A"

        data[
            "tp1"
        ] = "N/A"

        data[
            "tp2"
        ] = "N/A"

        data[
            "tp3"
        ] = "N/A"

        data[
            "rr"
        ] = "N/A"


        data[
            "rejection_reason"
        ] = " ".join(
            rejection_reasons
        )


        zone_price = str(
            data.get(
                "zone_price",
                "N/A"
            )
        ).strip()


        # ----------------------------------------------------
        # VALID STRUCTURE EXISTS
        # ----------------------------------------------------

        if (
            (vs_valid or vr_valid)
            and
            zone_price.upper()
            not in (
                "",
                "N/A",
                "NONE",
                "UNKNOWN",
                "NULL"
            )
        ):

            data[
                "rejection_reason"
            ] = (
                f"📍 Zone Price: {zone_price}\n"
                + data[
                    "rejection_reason"
                ]
            )


            wait_for = str(
                data.get(
                    "wait_for",
                    ""
                )
            ).strip()


            if not wait_for:

                if not pullback_confirmed:

                    wait_for = (
                        f"چاوەڕێ بکە نرخ بگەڕێتەوە "
                        f"بۆ Zone ـی {zone_price}."
                    )

                elif not confirmation_after_pullback:

                    wait_for = (
                        "چاوەڕێی Confirmation ـێکی دروست "
                        "دوای Pullback بکە."
                    )

                else:

                    wait_for = (
                        "هەموو Strong Signal filters ـەکان "
                        "پشتڕاست بکە."
                    )


            if zone_price not in wait_for:

                wait_for += (
                    f"\n📍 Zone Price: {zone_price}"
                )


            data[
                "wait_for"
            ] = wait_for


        # ----------------------------------------------------
        # NO VALID STRUCTURE
        # ----------------------------------------------------

        else:

            data[
                "zone"
            ] = "N/A"

            data[
                "zone_price"
            ] = "N/A"

            data[
                "zone_high"
            ] = "N/A"

            data[
                "zone_low"
            ] = "N/A"

            data[
                "zone_source_candle"
            ] = "N/A"


            wait_for = str(
                data.get(
                    "wait_for",
                    ""
                )
            ).strip()


            if not wait_for:

                wait_for = (
                    "چاوەڕێی VS یان VR ـێکی تەواو "
                    "و V3 verified بکە."
                )


            data[
                "wait_for"
            ] = wait_for


        return data


    # ========================================================
    # ACCEPT STRONG SIGNAL
    # ========================================================

    data[
        "signal"
    ] = signal


    if calculated_rr is not None:

        data[
            "rr"
        ] = f"1:{calculated_rr:.2f}"


    data[
        "rejection_reason"
    ] = (
        "هیچ rejection filter ـێک نەشکا."
    )


    data[
        "wait_for"
    ] = "N/A"


    return data


# ============================================================
# GEMINI IMAGE ANALYSIS
# ============================================================

def analyze_two_charts(
    zone_image,
    confirmation_image
):

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


    try:

        interaction = gemini.interactions.create(

            model=GEMINI_MODEL,

            system_instruction=SYSTEM_PROMPT,

            input=[

                {
                    "type": "text",
                    "text": USER_ANALYSIS_PROMPT
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


        if not isinstance(
            result,
            dict
        ):

            raise RuntimeError(
                "Gemini JSON is not an object."
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
# FORMAT STRUCTURE
# ============================================================

def format_structure(
    data,
    kind
):

    if not isinstance(
        data,
        dict
    ):

        return (
            "هیچ زانیارییەک بەردەست نییە."
        )


    data = normalize_structure(
        data
    )


    valid = data.get(
        "engine_valid",
        False
    )


    original = data.get(
        "original_level",
        "N/A"
    )


    formation = data.get(
        "formation_candle",
        "N/A"
    )


    validation = data.get(
        "validation_level",
        "N/A"
    )


    break_price = data.get(
        "break_price",
        "N/A"
    )


    break_candle = data.get(
        "break_candle",
        "N/A"
    )


    sequence = data.get(
        "sequence",
        "N/A"
    )


    break_confirmed = data.get(
        "break_confirmed",
        False
    )


    evidence_score = data.get(
        "evidence_score",
        structure_evidence_score(
            data
        )
    )


    status = (
        "پشتڕاستکراوە بە Engine V3 ✅"
        if valid
        else
        "پشتڕاست نەکراوەتەوە ❌"
    )


    break_text = (
        "بەڵێ، شکاندن پشتڕاستکراوە ✅"
        if break_confirmed
        else
        "نەخێر، شکاندن پشتڕاست نەکراوە ❌"
    )


    original_visible = (
        "بەڵێ ✅"
        if data.get(
            "original_level_visible",
            False
        )
        else
        "نەخێر ❌"
    )


    first_move = (
        "بەڵێ ✅"
        if data.get(
            "first_move_confirmed",
            False
        )
        else
        "نەخێر ❌"
    )


    new_level_after = (
        "بەڵێ ✅"
        if data.get(
            "new_level_formed_after_original",
            False
        )
        else
        "نەخێر ❌"
    )


    second_move = (
        "بەڵێ ✅"
        if data.get(
            "second_move_confirmed",
            False
        )
        else
        "نەخێر ❌"
    )


    same_level = (
        "بەڵێ ✅"
        if data.get(
            "same_level_broken",
            False
        )
        else
        "نەخێر ❌"
    )


    if kind == "VS":

        return f"""
دۆخی VS:
{status}

🧠 Evidence:
{evidence_score}/6

📍 Support ـی سەرەکی:
{original}

👁️ Support لە chart ـەکەدا:
{original_visible}

🕯️ کەندڵی دروستبوون:
{formation}

⬆️ یەکەم بەرزبوونەوە:
{first_move}

🎯 Resistance ـی نوێ دوای Support:
{validation}

⏱️ Resistance دوای Support دروستبووە:
{new_level_after}

⬆️ بەرزبوونەوەی دووەم:
{second_move}

💥 Break Price:
{break_price}

🕯️ Break Candle:
{break_candle}

🎯 هەمان Resistance شکێندراوە:
{same_level}

💥 شکاندنی هەمان Resistance:
{break_text}

🔄 زنجیرە:
{sequence}
""".strip()


    if kind == "VR":

        return f"""
دۆخی VR:
{status}

🧠 Evidence:
{evidence_score}/6

📍 Resistance ـی سەرەکی:
{original}

👁️ Resistance لە chart ـەکەدا:
{original_visible}

🕯️ کەندڵی دروستبوون:
{formation}

⬇️ یەکەم دابەزین:
{first_move}

🎯 Support ـی نوێ دوای Resistance:
{validation}

⏱️ Support دوای Resistance دروستبووە:
{new_level_after}

⬇️ دابەزینەوەی دووەم:
{second_move}

💥 Break Price:
{break_price}

🕯️ Break Candle:
{break_candle}

🎯 هەمان Support شکێندراوە:
{same_level}

💥 شکاندنی هەمان Support:
{break_text}

🔄 زنجیرە:
{sequence}
""".strip()


    return (
        "هیچ زانیارییەک بەردەست نییە."
    )


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(
    data
):

    if not isinstance(
        data,
        dict
    ):

        data = {}


    signal = str(
        data.get(
            "signal",
            "WAIT"
        )
    ).upper()


    if signal == "BUY":

        title = (
            "🟢 سیگناڵی STRONG BUY"
        )

    elif signal == "SELL":

        title = (
            "🔴 سیگناڵی STRONG SELL"
        )

    else:

        title = (
            "🟡 چاوەڕوان بە"
        )

        signal = "WAIT"


    zone_price = str(
        data.get(
            "zone_price",
            "N/A"
        )
    ).strip()


    if not zone_price:

        zone_price = "N/A"


    vs_text = format_structure(
        data.get(
            "vs_detected",
            {}
        ),
        "VS"
    )


    vr_text = format_structure(
        data.get(
            "vr_detected",
            {}
        ),
        "VR"
    )


    pullback = (
        "بەڵێ ✅"
        if safe_bool(
            data.get(
                "pullback_confirmed",
                False
            )
        )
        else
        "نەخێر ❌"
    )


    confirmation_after = (
        "بەڵێ ✅"
        if safe_bool(
            data.get(
                "confirmation_after_pullback",
                False
            )
        )
        else
        "نەخێر ❌"
    )


    agreement = (
        "بەڵێ ✅"
        if safe_bool(
            data.get(
                "htf_ltf_agreement",
                False
            )
        )
        else
        "نەخێر ❌"
    )


    no_rejection = (
        "بەڵێ ✅"
        if safe_bool(
            data.get(
                "no_rejection",
                False
            )
        )
        else
        "نەخێر ❌"
    )


    text = f"""
{title}
━━━━━━━━━━━━━━━━━━
🥇 XAUUSD

📊 Score:
{data.get("score", 0)}/100

💪 Confidence:
{data.get("confidence", 0)}%

📈 ئاراستە:
{data.get("trend", "N/A")}

🧠 پێکهاتە:
{data.get("setup", "N/A")}

🟦 Zone:
{data.get("zone", "N/A")}

📍 نرخی Zone:
{zone_price}

🔎 Zone ـەکانی HTF:
{data.get("htf_zones", "N/A")}

━━━━━━━━━━━━━━━━━━
🟢 VS — V3
━━━━━━━━━━━━━━━━━━
{vs_text}

━━━━━━━━━━━━━━━━━━
🔴 VR — V3
━━━━━━━━━━━━━━━━━━
{vr_text}

━━━━━━━━━━━━━━━━━━
🔎 Confirmation:
{data.get("confirmation", "N/A")}

🔄 Pullback / Retest:
{pullback}

⏱️ Confirmation دوای Pullback:
{confirmation_after}

🤝 HTF + LTF:
{agreement}

🛡️ No Rejection:
{no_rejection}
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
🔎 هۆکاری شیکردنەوە:
{data.get(
    "reasoning",
    "هیچ زانیارییەک بەردەست نییە."
)}

✅ پشکنینەکان:
{data.get(
    "checks",
    "هیچ زانیارییەک بەردەست نییە."
)}
"""


    if signal == "WAIT":

        text += f"""
━━━━━━━━━━━━━━━━━━
🚫 هۆکاری چاوەڕوانبوون:
{data.get(
    "rejection_reason",
    "پێکهاتەیەکی بەهێزی SNRZ پشتڕاست نەکراوەتەوە."
)}

👀 چاوەڕێی چی بکەین؟
{data.get(
    "wait_for",
    "چاوەڕێی VS/VR ـی تەواو بکە."
)}
"""


    else:

        text += """
━━━━━━━━━━━━━━━━━━
🟢 پێکهاتەی STRONG SNRZ V3 پشتڕاست کراوەتەوە.

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


    return telegram.download_file(
        file_path
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
    # ADMIN COMMANDS
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
    # ACCESS CONTROL
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

            "confirmation_image": None
        }


        telegram.send_message(

            chat_id,

            """
🥇 Gold Chart Analyzer PRO

🧠 SNRZ Structure Engine V3 چالاکە.

V3 سەرەتا هەردوو VS و VR بە structured
visual evidence پشکنین دەکات.

پاشان:

VALID VS/VR
→ Zone
→ Pullback / Retest
→ M1/M5 Confirmation
→ HTF + LTF
→ Strong Signal Filters

هەنگاوی 1️⃣:
📸 H1 یان H4 ـی XAUUSD بنێرە.

هەنگاوی 2️⃣:
📸 M1 یان M5 ـی XAUUSD بنێرە.

دەرئەنجام:

🟢 STRONG BUY
🔴 STRONG SELL
🟡 WAIT
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
📚 SNRZ Structure Engine V3

━━━━━━━━━━━━━━━━━━

🟢 VS:

Support
→ بەرزبوونەوە
→ NEW Resistance دوای Support
→ بەرزبوونەوەی دووبارە
→ Break هەمان Resistance
→ VS

🔴 VR:

Resistance
→ دابەزین
→ NEW Support دوای Resistance
→ دابەزینەوەی دووبارە
→ Break هەمان Support
→ VR

━━━━━━━━━━━━━━━━━━

🧠 V3 Evidence:

Original Level
First Move
New Level AFTER Original
Second Move
Same Level Broken
Break Confirmed

هەموویان دەبێت پشتڕاست بن بۆ valid structure.

━━━━━━━━━━━━━━━━━━

🟦 Zone:

کەندڵی VS/VR
+
کەندڵی پێش ئەو

BODY SIZE بەراورد دەکرێت.

کەندڵی BODY ـی کورتتر هەڵدەبژێردرێت.

تەواوی HIGH تا LOW:
Zone

━━━━━━━━━━━━━━━━━━

🔄 Flow:

VALID VS/VR
→ Zone
→ Pullback / Retest
→ M1/M5 Confirmation
→ HTF + LTF
→ Strong Signal

━━━━━━━━━━━━━━━━━━

🟢 BUY:

RBS
SRR
I.VR
PO2

🔴 SELL:

SBR
RSS
I.VS
PO2

━━━━━━━━━━━━━━━━━━

🔥 Strong Signal:

Score >= 80
Confidence >= 80%
RR >= 1:2
Valid VS/VR
Valid Zone
Pullback / Retest
Confirmation after Pullback
HTF + LTF agreement
No Rejection

ئەگەر یەکێک لەمانە نەبێت:

🟡 WAIT

━━━━━━━━━━━━━━━━━━

⚠️ Touch یان Wick یان Rejection بە Break دانانرێت.

Break دەبێت بە ڕوونی لە chart ـەکە ببینرێت.
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

            "♻️ Session reset کرا. ئێستا H1 یان H4 بنێرە."
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
                "confirmation_image": None
            }
        )


        # ----------------------------------------------------
        # FIRST IMAGE
        # ----------------------------------------------------

        if session[
            "zone_image"
        ] is None:

            session[
                "zone_image"
            ] = photo


            telegram.send_message(

                chat_id,

                """
✅ H1/H4 وەرگیرا.

🔎 ئێستا VS و VR بە
SNRZ Verification Engine V3
پشکنین دەکەین.

V3 هەموو evidence ـەکانی structure
بە جیاوازی verify دەکات.

پاشان:
📍 Zone ـی تەنها VS/VR ـی valid دیاری دەکەین.

دوای ئەوە:
📸 M1 یان M5 بۆ Pullback و Confirmation.
""".strip()
            )

            return


        # ----------------------------------------------------
        # SECOND IMAGE
        # ----------------------------------------------------

        if session[
            "confirmation_image"
        ] is None:

            session[
                "confirmation_image"
            ] = photo


            telegram.send_message(

                chat_id,

                """
⏳ هەردوو chart وەرگیرا.

🧠 SNRZ Verification Engine V3

VS Evidence
VR Evidence
→ Zone
→ Pullback
→ Confirmation
→ HTF + LTF
→ Score
→ Confidence
→ RR
→ Filters

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

تکایە هەردوو chart ـەکە بە quality ـی باشتر دووبارە بنێرە.
""".strip()
                )


            USER_SESSIONS.pop(
                chat_id,
                None
            )

            return


        return


    # ========================================================
    # OTHER TEXT
    # ========================================================

    telegram.send_message(

        chat_id,

        """
تکایە سەرەتا H1 یان H4 ـی XAUUSD بنێرە.

یان:

/start

بۆ دەستپێکردنەوە.
""".strip()
    )


# ============================================================
# MAIN LOOP
# ============================================================

def run():

    logger.info(
        "Gold Chart Analyzer PRO V3 started."
    )

    logger.info(
        f"Gemini model: {GEMINI_MODEL}"
    )

    logger.info(
        f"Admin ID: {ADMIN_USER_ID}"
    )

    logger.info(
        f"Allowed users: {len(ALLOWED_USER_IDS)}"
    )

    logger.info(
        f"Pending requests: "
        f"{len(PENDING_ACCESS_REQUESTS)}"
    )

    logger.info(
        f"Minimum score: {MIN_STRONG_SCORE}"
    )

    logger.info(
        f"Minimum confidence: "
        f"{MIN_STRONG_CONFIDENCE}%"
    )

    logger.info(
        f"Minimum RR: 1:{MIN_RR}"
    )


    # --------------------------------------------------------
    # TELEGRAM CONNECTION
    # --------------------------------------------------------

    me = telegram.get_me()

    logger.info(
        f"Telegram connected: "
        f"@{me.get('username')}"
    )


    # --------------------------------------------------------
    # REMOVE WEBHOOK
    # --------------------------------------------------------

    telegram.delete_webhook()

    logger.info(
        "Telegram webhook removed."
    )


    offset = None


    # ========================================================
    # POLLING
    # ========================================================

    while True:

        try:

            updates = telegram.get_updates(

                offset=offset,

                timeout=30
            )


            for update in updates:

                offset = (
                    update["update_id"]
                    + 1
                )


                # ------------------------------------------------
                # CALLBACK QUERY
                # ------------------------------------------------

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
                            "Access callback handling error."
                        )

                    continue


                # ------------------------------------------------
                # MESSAGE
                # ------------------------------------------------

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
                    "Telegram 409 Conflict: "
                    "another bot instance is running."
                )

                logger.error(
                    "Stop every other running "
                    "instance using this token."
                )

                time.sleep(
                    10
                )


            else:

                logger.exception(
                    "Telegram polling error. "
                    "Retrying in 5 seconds..."
                )

                time.sleep(
                    5
                )


        except Exception:

            logger.exception(
                "Unexpected error. "
                "Retrying in 5 seconds..."
            )

            time.sleep(
                5
            )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    run()
