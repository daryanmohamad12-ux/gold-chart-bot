# ============================================================
# gold_chart_analyzer.py
# SNRZ GOLD CHART ANALYZER PRO
# ADMIN + ACCESS REQUEST SYSTEM + ALLOWED USERS
# VS / VR VERIFICATION ENGINE V2
# STRONG SIGNAL ENGINE
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

            data = json.load(file)

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

🧠 SNRZ Structure Engine V2 چالاکە.

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
# SNRZ SYSTEM PROMPT — V2
# ============================================================

SYSTEM_PROMPT = r"""
You are an ELITE XAUUSD SNRZ STRUCTURE ANALYST.

Your job is NOT to search for frequent signals.

Your job is to identify COMPLETE, VISUALLY PROVEN
VS and VR structures from the H1/H4 chart.

You must verify the structure before allowing any Zone.

============================================================
LANGUAGE
============================================================

ALL explanatory text inside JSON must be written in
Sorani Kurdish.

Technical SNRZ names must remain EXACTLY in English:

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
IMPORTANT — VISUAL VERIFICATION V2
============================================================

Do NOT determine VS/VR from nearby Support/Resistance
levels alone.

Do NOT simply compare the highest and lowest visible
prices.

You MUST visually trace the candle sequence from LEFT
TO RIGHT across the visible H1/H4 chart.

You must use only information that is visibly present
on the chart.

Never invent hidden candles.

Never assume a missing move.

Never assume a breakout that cannot be seen.

============================================================
VS — VALID SUPPORT
============================================================

A normal Support is NOT VS.

For VS, follow this exact chronological structure:

STEP 1:
Find an ORIGINAL Support.

STEP 2:
Confirm price moves UP from that Support.

STEP 3:
After that Support, identify a NEW Resistance.

IMPORTANT:
The Resistance MUST be created AFTER the original Support.

Any Resistance that existed BEFORE the Support is irrelevant.

STEP 4:
After the NEW Resistance is formed, price must move UP AGAIN.

STEP 5:
Price must then BREAK ABOVE THAT SAME NEW Resistance.

The break must be visually clear.

Only after all five steps are visible:

VS = valid.

The original Support becomes VS.

============================================================
VS BREAK RULE
============================================================

A break means price clearly moves beyond the SAME
new Resistance created after the Support.

The following are NOT sufficient:

- touching Resistance
- wick touching Resistance
- rejection from Resistance
- approaching Resistance
- equal high
- approximate high
- unclear candle
- assumed breakout
- current price being above the level without clear
  historical evidence

If the chart clearly shows a candle breaking above the
same Resistance, then break_confirmed = true.

If the break is not visually clear:

break_confirmed = false
valid = false

============================================================
VR — VALID RESISTANCE
============================================================

A normal Resistance is NOT VR.

For VR, follow this exact chronological structure:

STEP 1:
Find an ORIGINAL Resistance.

STEP 2:
Confirm price moves DOWN from that Resistance.

STEP 3:
After that Resistance, identify a NEW Support.

IMPORTANT:
The Support MUST be created AFTER the original Resistance.

Any Support that existed BEFORE the Resistance is irrelevant.

STEP 4:
After the NEW Support is formed, price must move DOWN AGAIN.

STEP 5:
Price must then BREAK BELOW THAT SAME NEW Support.

The break must be visually clear.

Only after all five steps are visible:

VR = valid.

The original Resistance becomes VR.

============================================================
VR BREAK RULE
============================================================

A break means price clearly moves below the SAME
new Support created after the Resistance.

The following are NOT sufficient:

- touching Support
- wick touching Support
- rejection from Support
- approaching Support
- approximate low
- unclear candle
- assumed breakdown
- current price being below the level without clear
  historical evidence

If the chart clearly shows a candle breaking below the
same Support, then break_confirmed = true.

If the break is not visually clear:

break_confirmed = false
valid = false

============================================================
FULL VS/VR SCAN
============================================================

ALWAYS scan BOTH structures independently.

Do this even if the final signal is WAIT.

You must determine:

1. VS status.
2. VR status.
3. Original level.
4. Formation candle.
5. New opposite level.
6. Second directional move.
7. Break of the SAME new opposite level.
8. Break confirmation.
9. Final validity.

Never stop after finding only one candidate.

============================================================
CRITICAL CHRONOLOGY
============================================================

For VS:

Support
→ Up
→ NEW Resistance AFTER Support
→ Up AGAIN
→ BREAK SAME Resistance
→ VS

For VR:

Resistance
→ Down
→ NEW Support AFTER Resistance
→ Down AGAIN
→ BREAK SAME Support
→ VR

The word "AFTER" is chronological.

Do NOT reverse the order.

============================================================
ZONE RULE
============================================================

Zone exists ONLY if VS or VR is valid.

Never create a Zone from:

- normal Support
- normal Resistance
- possible VS
- possible VR
- unconfirmed structure
- random candle
- engulfing pattern

After a VALID VS/VR:

1. Identify the exact candle where the VS/VR is formed.
2. Identify the immediately previous candle.
3. Compare BODY SIZE.
4. Select the candle with the SHORTER BODY.
5. Zone = complete HIGH-to-LOW range of that selected candle.

The Zone is the complete candle range.

Do NOT use only the candle body.

Do NOT use Bullish Engulfing.

Do NOT use Bearish Engulfing.

============================================================
PULLBACK / RETEST
============================================================

The required flow is:

VALID VS/VR
→ Zone
→ Price Pullback / Retest
→ M1/M5 Confirmation
→ Strong Signal Check
→ Entry

Confirmation before Pullback is INVALID.

============================================================
BUY CONFIRMATION
============================================================

Allowed BUY confirmation:

RBS
SRR
I.VR
PO2

============================================================
SELL CONFIRMATION
============================================================

Allowed SELL confirmation:

SBR
RSS
I.VS
PO2

============================================================
STRONG SIGNAL
============================================================

BUY or SELL ONLY when ALL are true:

- Valid VS or VR.
- Valid Zone.
- Price has reached/retested Zone.
- Confirmation formed AFTER Pullback.
- Confirmation is valid.
- HTF/LTF agree.
- Entry is logical.
- SL is logical.
- TP is logical.
- RR >= 1:2.
- Score >= 80.
- Confidence >= 80%.
- No rejection filter.

If ANY condition is missing:

WAIT.

============================================================
WAIT
============================================================

If VS/VR is incomplete:

WAIT.

If valid VS/VR exists but price has not returned to Zone:

WAIT.

If price is at Zone but confirmation is missing:

WAIT.

If confirmation is before Pullback:

WAIT.

If RR < 1:2:

WAIT.

If Score < 80:

WAIT.

If Confidence < 80:

WAIT.

============================================================
ZONE PRICE
============================================================

If there is NO valid VS or VR:

zone = "N/A"
zone_price = "N/A"

If there IS a valid VS or VR:

provide exact Zone Price from the chart.

Never invent a price.

============================================================
JSON
============================================================

Return ONLY valid JSON.

Use EXACTLY these keys:

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

  "vs_detected": {
    "valid": false,
    "original_level": "...",
    "formation_candle": "...",
    "validation_level": "...",
    "sequence": "...",
    "break_confirmed": false
  },

  "vr_detected": {
    "valid": false,
    "original_level": "...",
    "formation_candle": "...",
    "validation_level": "...",
    "sequence": "...",
    "break_confirmed": false
  },

  "confirmation": "...",
  "trend": "...",
  "reasoning": "...",
  "checks": "...",
  "rejection_reason": "...",
  "wait_for": "..."
}

============================================================
IMPORTANT OUTPUT RULE
============================================================

If VS is valid:

vs_detected.valid = true
vs_detected.break_confirmed = true

If VR is valid:

vr_detected.valid = true
vr_detected.break_confirmed = true

If either break is not visually proven:

valid = false
break_confirmed = false

Do NOT mark a structure valid only because the levels
look approximately correct.

============================================================
FINAL PRINCIPLE
============================================================

STRUCTURE FIRST.

VS/VR VERIFICATION V2
→ VALID VS/VR
→ Zone
→ Pullback / Retest
→ LTF Confirmation
→ Strong Signal Filters
→ BUY / SELL

Otherwise:

WAIT.
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

    text = text.strip()

    text = text.replace(
        "```json",
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
# TEXT HELPERS
# ============================================================

def contains_any(
    text,
    phrases
):

    text = str(
        text or ""
    ).upper()

    for phrase in phrases:

        if phrase.upper() in text:

            return True

    return False


def contains_all(
    text,
    phrases
):

    text = str(
        text or ""
    ).upper()

    for phrase in phrases:

        if phrase.upper() not in text:

            return False

    return True


def first_position(
    text,
    phrases
):

    text = str(
        text or ""
    ).upper()

    positions = []

    for phrase in phrases:

        position = text.find(
            phrase.upper()
        )

        if position != -1:

            positions.append(
                position
            )

    if not positions:

        return -1

    return min(
        positions
    )


# ============================================================
# VERIFY VS — ENGINE V2
# ============================================================

def verify_vs_v2(
    vs_data
):

    if not isinstance(
        vs_data,
        dict
    ):

        return False


    if vs_data.get(
        "valid",
        False
    ) is not True:

        return False


    if vs_data.get(
        "break_confirmed",
        False
    ) is not True:

        return False


    original_level = str(
        vs_data.get(
            "original_level",
            ""
        )
    ).strip()

    formation_candle = str(
        vs_data.get(
            "formation_candle",
            ""
        )
    ).strip()

    validation_level = str(
        vs_data.get(
            "validation_level",
            ""
        )
    ).strip()

    sequence = str(
        vs_data.get(
            "sequence",
            ""
        )
    ).strip()


    if not original_level:

        return False


    if not formation_candle:

        return False


    if not validation_level:

        return False


    if validation_level.upper() in (
        "N/A",
        "NONE",
        "UNKNOWN",
        "NULL",
        "..."
    ):

        return False


    if not sequence:

        return False


    sequence_upper = sequence.upper()


    # --------------------------------------------------------
    # REQUIRED TECHNICAL LEVELS
    # --------------------------------------------------------

    if "SUPPORT" not in sequence_upper:

        return False


    if "RESISTANCE" not in sequence_upper:

        return False


    # --------------------------------------------------------
    # REQUIRED BREAK
    # --------------------------------------------------------

    break_exists = contains_any(
        sequence_upper,
        [
            "BREAK",
            "شکاند",
            "پەڕاند",
            "تێپەڕاند"
        ]
    )

    if not break_exists:

        return False


    # --------------------------------------------------------
    # CHRONOLOGICAL ORDER
    # --------------------------------------------------------

    support_pos = first_position(
        sequence_upper,
        [
            "SUPPORT"
        ]
    )

    resistance_pos = first_position(
        sequence_upper,
        [
            "RESISTANCE"
        ]
    )

    break_pos = first_position(
        sequence_upper,
        [
            "BREAK",
            "شکاند",
            "پەڕاند",
            "تێپەڕاند"
        ]
    )


    if (
        support_pos == -1
        or
        resistance_pos == -1
        or
        break_pos == -1
    ):

        return False


    if not (
        support_pos
        <
        resistance_pos
        <
        break_pos
    ):

        return False


    # --------------------------------------------------------
    # RESISTANCE MUST BE AFTER SUPPORT
    # --------------------------------------------------------

    after_support = contains_any(
        sequence_upper,
        [
            "AFTER SUPPORT",
            "دوای SUPPORT",
            "لە دوای SUPPORT"
        ]
    )

    if not after_support:

        return False


    # --------------------------------------------------------
    # SECOND UP MOVE
    # --------------------------------------------------------

    second_up = (
        contains_any(
            sequence_upper,
            [
                "UP AGAIN",
                "UP AGAIN",
                "دووبارە"
            ]
        )
        and
        contains_any(
            sequence_upper,
            [
                "UP",
                "سەرەوە",
                "بەرزبوونەوە"
            ]
        )
    )

    if not second_up:

        return False


    # --------------------------------------------------------
    # SAME RESISTANCE
    # --------------------------------------------------------

    same_resistance = contains_any(
        sequence_upper,
        [
            "SAME RESISTANCE",
            "هەمان RESISTANCE"
        ]
    )

    if not same_resistance:

        return False


    return True


# ============================================================
# VERIFY VR — ENGINE V2
# ============================================================

def verify_vr_v2(
    vr_data
):

    if not isinstance(
        vr_data,
        dict
    ):

        return False


    if vr_data.get(
        "valid",
        False
    ) is not True:

        return False


    if vr_data.get(
        "break_confirmed",
        False
    ) is not True:

        return False


    original_level = str(
        vr_data.get(
            "original_level",
            ""
        )
    ).strip()

    formation_candle = str(
        vr_data.get(
            "formation_candle",
            ""
        )
    ).strip()

    validation_level = str(
        vr_data.get(
            "validation_level",
            ""
        )
    ).strip()

    sequence = str(
        vr_data.get(
            "sequence",
            ""
        )
    ).strip()


    if not original_level:

        return False


    if not formation_candle:

        return False


    if not validation_level:

        return False


    if validation_level.upper() in (
        "N/A",
        "NONE",
        "UNKNOWN",
        "NULL",
        "..."
    ):

        return False


    if not sequence:

        return False


    sequence_upper = sequence.upper()


    # --------------------------------------------------------
    # REQUIRED TECHNICAL LEVELS
    # --------------------------------------------------------

    if "RESISTANCE" not in sequence_upper:

        return False


    if "SUPPORT" not in sequence_upper:

        return False


    # --------------------------------------------------------
    # REQUIRED BREAK
    # --------------------------------------------------------

    break_exists = contains_any(
        sequence_upper,
        [
            "BREAK",
            "شکاند",
            "پەڕاند",
            "تێپەڕاند"
        ]
    )

    if not break_exists:

        return False


    # --------------------------------------------------------
    # CHRONOLOGICAL ORDER
    # --------------------------------------------------------

    resistance_pos = first_position(
        sequence_upper,
        [
            "RESISTANCE"
        ]
    )

    support_pos = first_position(
        sequence_upper,
        [
            "SUPPORT"
        ]
    )

    break_pos = first_position(
        sequence_upper,
        [
            "BREAK",
            "شکاند",
            "پەڕاند",
            "تێپەڕاند"
        ]
    )


    if (
        resistance_pos == -1
        or
        support_pos == -1
        or
        break_pos == -1
    ):

        return False


    if not (
        resistance_pos
        <
        support_pos
        <
        break_pos
    ):

        return False


    # --------------------------------------------------------
    # SUPPORT MUST BE AFTER RESISTANCE
    # --------------------------------------------------------

    after_resistance = contains_any(
        sequence_upper,
        [
            "AFTER RESISTANCE",
            "دوای RESISTANCE",
            "لە دوای RESISTANCE"
        ]
    )

    if not after_resistance:

        return False


    # --------------------------------------------------------
    # SECOND DOWN MOVE
    # --------------------------------------------------------

    second_down = (
        contains_any(
            sequence_upper,
            [
                "DOWN AGAIN",
                "دووبارە"
            ]
        )
        and
        contains_any(
            sequence_upper,
            [
                "DOWN",
                "خوارەوە",
                "دابەزین"
            ]
        )
    )

    if not second_down:

        return False


    # --------------------------------------------------------
    # SAME SUPPORT
    # --------------------------------------------------------

    same_support = contains_any(
        sequence_upper,
        [
            "SAME SUPPORT",
            "هەمان SUPPORT"
        ]
    )

    if not same_support:

        return False


    return True


# ============================================================
# VALID STRUCTURE CHECK
# ============================================================

def get_valid_structures(
    data
):

    vs_data = data.get(
        "vs_detected",
        {}
    )

    vr_data = data.get(
        "vr_detected",
        {}
    )


    vs_valid = verify_vs_v2(
        vs_data
    )

    vr_valid = verify_vr_v2(
        vr_data
    )


    return (
        vs_valid,
        vr_valid
    )


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

        data = {}


    signal = str(
        data.get(
            "signal",
            "WAIT"
        )
    ).upper()


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
    # VERIFY BOTH STRUCTURES FIRST
    # ========================================================

    vs_valid, vr_valid = (
        get_valid_structures(
            data
        )
    )


    # ========================================================
    # FORCE INTERNAL STRUCTURE STATUS
    # ========================================================

    if isinstance(
        data.get(
            "vs_detected"
        ),
        dict
    ):

        data[
            "vs_detected"
        ][
            "engine_valid"
        ] = vs_valid


    if isinstance(
        data.get(
            "vr_detected"
        ),
        dict
    ):

        data[
            "vr_detected"
        ][
            "engine_valid"
        ] = vr_valid


    # ========================================================
    # IMPORTANT:
    # ZONE ONLY EXISTS WITH VALID VS OR VR
    # ========================================================

    if not vs_valid and not vr_valid:

        data["zone"] = "N/A"
        data["zone_price"] = "N/A"


    zone = str(
        data.get(
            "zone",
            ""
        )
    ).strip()


    zone_price = str(
        data.get(
            "zone_price",
            "N/A"
        )
    ).strip()


    if not zone_price:

        zone_price = "N/A"


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
    # WAIT FROM AI
    # ========================================================

    if signal == "WAIT":

        rejection_reasons.append(
            "AI setup ـێکی بەهێزی SNRZ پشتڕاست نەکردووەتەوە."
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
    # BUY → MUST HAVE VALID VS
    # ========================================================

    if signal == "BUY":

        if not vs_valid:

            rejection_reasons.append(
                "VS ـی تەواو و پشتڕاستکراوە نییە."
            )


    # ========================================================
    # SELL → MUST HAVE VALID VR
    # ========================================================

    if signal == "SELL":

        if not vr_valid:

            rejection_reasons.append(
                "VR ـی تەواو و پشتڕاستکراوە نییە."
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
                "Confirmation ـی دروستی SNRZ نییە."
            )


    # ========================================================
    # ZONE
    # ========================================================

    if not vs_valid and not vr_valid:

        rejection_reasons.append(
            "هیچ VS یان VR ـێکی HTF بە تەواوی پشتڕاست نەکراوەتەوە."
        )

    else:

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


        if entry.upper() in (
            "",
            "N/A",
            "NONE",
            "UNKNOWN"
        ):

            rejection_reasons.append(
                "Entry دیاری نەکراوە."
            )


        if sl.upper() in (
            "",
            "N/A",
            "NONE",
            "UNKNOWN"
        ):

            rejection_reasons.append(
                "SL دیاری نەکراوە."
            )


        if tp1.upper() in (
            "",
            "N/A",
            "NONE",
            "UNKNOWN"
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
                "RR بە شێوەیەکی دروست حساب ناکرێت."
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
        # VALID ZONE EXISTS
        # ----------------------------------------------------

        if (
            (vs_valid or vr_valid)
            and
            zone_price
            and
            zone_price.upper()
            not in (
                "N/A",
                "NONE",
                "UNKNOWN"
            )
        ):

            data["rejection_reason"] = (
                f"📍 Zone Price: {zone_price}\n"
                + data["rejection_reason"]
            )


            if not wait_for:

                wait_for = (
                    f"چاوەڕێ بکە نرخ بگەڕێتەوە "
                    f"بۆ Zone ـی {zone_price}."
                )

            elif zone_price not in wait_for:

                wait_for = (
                    f"{wait_for}\n"
                    f"📍 Zone Price: {zone_price}"
                )


        # ----------------------------------------------------
        # NO VALID STRUCTURE
        # ----------------------------------------------------

        else:

            data["zone"] = "N/A"
            data["zone_price"] = "N/A"


            if not wait_for:

                wait_for = (
                    "چاوەڕێی VS یان VR ـێکی تەواو و "
                    "پشتڕاستکراوە بکە."
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


    user_prompt = r"""
هەردوو وێنەی XAUUSD بە وردی شیکەرەوە.

IMAGE 1 = H1/H4
IMAGE 2 = M1/M5

============================================================
STEP 1 — H1/H4 FULL SCAN
============================================================

پێش هەر بڕیارێک:

هەموو candle ـە دیارەکانی H1/H4 لە چەپ بۆ ڕاست
بپشکنە.

تەنها ئەو شتانە بەکاربهێنە کە بە ڕوونی لە chart ـەکە
دەبینرێن.

هیچ candle ـێک مەخەملێنە.

هیچ breakout ـێک مەخەملێنە.

============================================================
STEP 2 — VS VERIFICATION V2
============================================================

Support
→ Up
→ NEW Resistance AFTER Support
→ Up AGAIN
→ BREAK SAME Resistance
→ VS

تەنها Resistance ـێک بەکاربهێنە کە دوای Support دروست بووە.

Resistance ـی پێش Support بە تەواوی پشتگوێ بخە.

Touch = Break نییە.

Wick = بە تەنیا Break نییە.

Rejection = Break نییە.

ئەگەر candle ـی Break بە ڕوونی نەبینرێت:

break_confirmed = false
valid = false

ئەگەر هەموو sequence ـەکە بە ڕوونی هەبێت:

break_confirmed = true
valid = true

============================================================
STEP 3 — VR VERIFICATION V2
============================================================

Resistance
→ Down
→ NEW Support AFTER Resistance
→ Down AGAIN
→ BREAK SAME Support
→ VR

تەنها Support ـێک بەکاربهێنە کە دوای Resistance دروست بووە.

Support ـی پێش Resistance بە تەواوی پشتگوێ بخە.

Touch = Break نییە.

Wick = بە تەنیا Break نییە.

Rejection = Break نییە.

ئەگەر candle ـی Break بە ڕوونی نەبینرێت:

break_confirmed = false
valid = false

ئەگەر هەموو sequence ـەکە بە ڕوونی هەبێت:

break_confirmed = true
valid = true

============================================================
STEP 4 — BOTH
============================================================

هەردووکیان بپشکنە:

VS
VR

تەنانەت ئەگەر signal = WAIT بێت.

============================================================
STEP 5 — ZONE
============================================================

Zone تەنها دوای VS/VR ـی valid دروست دەکرێت.

کەندڵی دروستبوونی VS/VR بدۆزەرەوە.

کەندڵی پێش ئەویش بدۆزەرەوە.

BODY SIZE ـەکانیان بەراورد بکە.

ئەوەی BODY ـی کورتتری هەیە هەڵبژێرە.

تەواوی HIGH تا LOW ـی ئەو candle ـە:

Zone

هیچ Engulfing Zone ـێک بەکارمەهێنە.

============================================================
STEP 6 — PULLBACK
============================================================

VALID VS/VR
→ Zone
→ Price returns/retests Zone
→ M1/M5 Confirmation
→ Strong Signal
→ Entry

ئەگەر Pullback نەکراوە:

WAIT.

============================================================
STEP 7 — CONFIRMATION
============================================================

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

Confirmation پێش Pullback قبوڵ مەکە.

============================================================
STEP 8 — STRONG SIGNAL
============================================================

Score >= 80

Confidence >= 80%

RR >= 1:2

Valid VS/VR

Valid Zone

Pullback / Retest

Valid LTF Confirmation

HTF/LTF agreement

Entry

SL

TP

هەر یەکێک نەبێت:

WAIT.

============================================================
LANGUAGE
============================================================

هەموو explanatory text ـەکان بە کوردی سۆرانی بن.

تەنها ئەم technical names ـانە English بن:

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
SEQUENCE FORMAT
============================================================

VS:

"Support → بەرزبوونەوە → Resistance ـێکی نوێ دوای Support → بەرزبوونەوەی دووبارە → شکاندنی هەمان Resistance"

VR:

"Resistance → دابەزین → Support ـێکی نوێ دوای Resistance → دابەزینەوەی دووبارە → شکاندنی هەمان Support"

============================================================
FINAL RULE
============================================================

ئەگەر structure بە ڕوونی هەیە و Break ـەکەش بە ڕوونی
لە chart ـەکە دەبینرێت، valid بکە.

ئەگەر structure ناقصە یان Break ـەکە ڕوون نییە،
invalid بکە.

هیچ شتێک مەخەملێنە.

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
# FORMAT VS / VR
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


    sequence = data.get(
        "sequence",
        "N/A"
    )


    break_confirmed = data.get(
        "break_confirmed",
        False
    )


    status = (
        "پشتڕاستکراوە بە Engine V2 ✅"
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


    if kind == "VS":

        return f"""
دۆخی VS:
{status}

📍 Support ـی سەرەکی:
{original}

🕯️ کەندڵی دروستبوونی Support:
{formation}

🎯 Resistance ـی نوێ دوای Support:
{validation}

🔄 زنجیرەی پێکهاتە:
{sequence}

💥 شکاندنی هەمان Resistance:
{break_text}
""".strip()


    if kind == "VR":

        return f"""
دۆخی VR:
{status}

📍 Resistance ـی سەرەکی:
{original}

🕯️ کەندڵی دروستبوونی Resistance:
{formation}

🎯 Support ـی نوێ دوای Resistance:
{validation}

🔄 زنجیرەی پێکهاتە:
{sequence}

💥 شکاندنی هەمان Support:
{break_text}
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
🟢 VS
━━━━━━━━━━━━━━━━━━
{vs_text}

━━━━━━━━━━━━━━━━━━
🔴 VR
━━━━━━━━━━━━━━━━━━
{vr_text}

━━━━━━━━━━━━━━━━━━
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
🟢 پێکهاتەی STRONG SNRZ پشتڕاست کراوەتەوە.

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

🧠 SNRZ Structure Engine V2 چالاکە.

سیستەم سەرەتا هەردوو VS و VR ـی H1/H4 بە وردی
پشکنین دەکات.

پاشان:

VS/VR
→ Zone
→ Pullback / Retest
→ M1/M5 Confirmation
→ Strong Signal Check

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
📚 SNRZ Structure Engine V2

━━━━━━━━━━━━━━━━━━

🟢 VS:

Support
→ بەرزبوونەوە
→ Resistance ـێکی نوێ دوای Support
→ بەرزبوونەوەی دووبارە
→ شکاندنی هەمان Resistance
→ VS

🔴 VR:

Resistance
→ دابەزین
→ Support ـێکی نوێ دوای Resistance
→ دابەزینەوەی دووبارە
→ شکاندنی هەمان Support
→ VR

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
→ Strong Signal Check
→ Entry

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
VS/VR ـی valid
Zone ـی valid
Pullback / Retest
Confirmation ـی دوای Pullback
HTF + LTF agreement

ئەگەر یەکێک لەمانە نەبێت:

🟡 WAIT

━━━━━━━━━━━━━━━━━━

⚠️ Touch یان rejection بە Break دانانرێت.

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

🔎 ئێستا VS و VR ـی تەواوی H1/H4
بە Verification Engine V2 پشکنین دەکەین.

پاشان:
📍 Zone ـی تەنها VS/VR ـی valid دیاری دەکەین.

دوای ئەوە:
📸 M1 یان M5 بۆ Confirmation.
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

🧠 SNRZ Verification Engine V2

VS
VR
→ Zone
→ Pullback
→ Confirmation
→ Score
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
        "Gold Chart Analyzer PRO V2 started."
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
