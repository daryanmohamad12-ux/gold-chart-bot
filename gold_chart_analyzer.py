# ============================================================
# gold_chart_analyzer.py
# SNRZ GOLD CHART ANALYZER PRO
# ADMIN + ACCESS REQUEST SYSTEM + ALLOWED USERS
# VS / VR STRUCTURE ENGINE + STRONG SIGNAL ENGINE
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
# TELEGRAM
# ============================================================

class TelegramAPIError(Exception):
    pass


class TelegramBot:

    def __init__(self, token):

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

        url = f"{self.base_url}/{method}"

        try:

            response = requests.post(
                url,
                json=data or {},
                timeout=timeout,
            )

            response.raise_for_status()

            result = response.json()

            if not result.get("ok"):

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
            ],
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

        MAX_LENGTH = 4000

        if not isinstance(
            text,
            str
        ):

            text = str(text)

        if len(text) <= MAX_LENGTH:

            return self.call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": text,
                }
            )

        results = []

        for i in range(
            0,
            len(text),
            MAX_LENGTH
        ):

            chunk = text[
                i:i + MAX_LENGTH
            ]

            results.append(
                self.call(
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text": chunk,
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
            "message_id": message_id,
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

def is_admin(user_id):

    return user_id == ADMIN_USER_ID


def is_allowed(user_id):

    return (
        user_id in ALLOWED_USER_IDS
    )


def deny_access(chat_id):

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


    # --------------------------------------------------------
    # Already allowed
    # --------------------------------------------------------

    if is_allowed(
        user_id
    ):

        return False


    # --------------------------------------------------------
    # Existing request
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Create request
    # --------------------------------------------------------

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
            username,
    }


    ACCESS_CODES[
        code
    ] = user_id


    # --------------------------------------------------------
    # USER MESSAGE
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # ADMIN MESSAGE
    # --------------------------------------------------------

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
                keyboard,

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


    # --------------------------------------------------------
    # ADMIN ONLY
    # --------------------------------------------------------

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


    # ========================================================
    # APPROVE
    # ========================================================

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

🧠 SNRZ Structure Engine چالاکە.

ئێستا دەتوانیت بۆتەکە بەکاربهێنیت.

📸 H1 یان H4 ـی XAUUSD بنێرە.
""".strip()
        )


        return


    # ========================================================
    # REJECT
    # ========================================================

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


    # ========================================================
    # ADD USER
    # ========================================================

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


    # ========================================================
    # REMOVE USER
    # ========================================================

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


    # ========================================================
    # USERS
    # ========================================================

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


    # ========================================================
    # PENDING
    # ========================================================

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


    # ========================================================
    # ADMIN HELP
    # ========================================================

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

⏳ داواکارییە چاوەڕوانەکان:

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


    # ========================================================
    # BROADCAST
    # ========================================================

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
# SNRZ SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = r"""
You are an ELITE XAUUSD SNRZ STRUCTURE ANALYST.

Your main job is to correctly identify:

1. VS = Valid Support
2. VR = Valid Resistance
3. I.VS
4. I.VR
5. RBS
6. SBR
7. SRR
8. RSS
9. PO2

You must analyze the charts candle-by-candle.

IMPORTANT:

A normal Support is NOT automatically a VS.

A normal Resistance is NOT automatically a VR.

You must prove the complete structure.

============================================================
TIMEFRAME STRUCTURE
============================================================

IMAGE 1:

H1 or H4.

This is the HIGHER TIMEFRAME.

Its job is to identify important SNRZ structures:

VS
VR
Support zones
Resistance zones
Breaks
Retests
Major direction

IMAGE 2:

M1 or M5.

This is the LOWER TIMEFRAME.

Its job is confirmation.

============================================================
VS — VALID SUPPORT
============================================================

THIS RULE IS CRITICAL.

For VS, ONLY the Resistance that is CREATED AFTER
the Support is relevant.

Any Resistance that existed BEFORE the Support
is COMPLETELY IRRELEVANT to the VS calculation.

DO NOT use any Resistance before the Support
to validate the Support.

The structure MUST be:

SUPPORT
→ UP
→ NEW RESISTANCE CREATED AFTER THAT SUPPORT
→ UP AGAIN
→ BREAK THAT SAME RESISTANCE

Only after that exact structure is completed:

SUPPORT = VS

Detailed rules:

STEP 1:
First identify a meaningful SUPPORT.

STEP 2:
Price must move UP from that Support.

STEP 3:
After the Support, the upward move creates a NEW
RESISTANCE / swing-high area.

THIS IS THE ONLY RESISTANCE THAT COUNTS FOR THIS VS.

STEP 4:
Price moves UP again.

STEP 5:
Price BREAKS the NEW RESISTANCE that was created
AFTER the Support.

When that resistance is broken:

the ORIGINAL SUPPORT becomes:

VS = VALID SUPPORT.

CRITICAL:

If there is an old Resistance before the Support,
IGNORE it.

If the new Resistance after Support has not been broken:

NOT VS.

If the complete structure is not visible:

NOT VS.

A normal Support is NOT automatically a VS.

============================================================
VR — VALID RESISTANCE
============================================================

THIS RULE IS ALSO CRITICAL.

For VR, ONLY the Support that is CREATED AFTER
the Resistance is relevant.

Any Support that existed BEFORE the Resistance
is COMPLETELY IRRELEVANT to the VR calculation.

DO NOT use any Support before the Resistance
to validate the Resistance.

The structure MUST be:

RESISTANCE
→ DOWN
→ NEW SUPPORT CREATED AFTER THAT RESISTANCE
→ DOWN AGAIN
→ BREAK THAT SAME SUPPORT

Only after that exact structure is completed:

RESISTANCE = VR

Detailed rules:

STEP 1:
First identify a meaningful RESISTANCE.

STEP 2:
Price must move DOWN from that Resistance.

STEP 3:
After the Resistance, the downward move creates a NEW
SUPPORT / swing-low area.

THIS IS THE ONLY SUPPORT THAT COUNTS FOR THIS VR.

STEP 4:
Price moves DOWN again.

STEP 5:
Price BREAKS the NEW SUPPORT that was created
AFTER the Resistance.

When that support is broken:

the ORIGINAL RESISTANCE becomes:

VR = VALID RESISTANCE.

CRITICAL:

If there is an old Support before the Resistance,
IGNORE it.

If the new Support after Resistance has not been broken:

NOT VR.

If the complete structure is not visible:

NOT VR.

A normal Resistance is NOT automatically a VR.

============================================================
VS / VR DETECTION RULE
============================================================

Before analyzing any BUY or SELL setup:

FIRST scan the complete H1/H4 chart.

Find ALL clearly visible and COMPLETELY PROVEN:

VS
VR

Only COMPLETED structures can be recorded as VS or VR.

For EVERY VS/VR candidate, you MUST explicitly prove:

- The original Support/Resistance
- The NEW opposite level formed AFTER it
- The second move in the same direction
- The break of that SAME new opposite level
- The complete sequence
- Whether the break is confirmed
- Whether the structure is valid

If any part is missing or unclear:

valid = false.

Do NOT infer missing candles.

Do NOT guess.

============================================================
ZONE DETERMINATION — CRITICAL
============================================================

The Zone MUST be determined ONLY from the confirmed VS or VR.

After identifying a valid VS or VR:

1. Identify the candle where the VS or VR is formed.
2. Look at the candle immediately BEFORE that VS/VR candle.
3. Compare the BODY SIZE of these two candles.
4. Choose the candle with the SHORTER BODY.
5. The ENTIRE selected candle becomes the Zone.
6. The Zone MUST cover the complete candle from HIGH to LOW.

IMPORTANT:

The Zone is NOT only the candle body.

The Zone is the FULL HIGH-to-LOW range of the selected candle.

Do NOT use Bullish Engulf.

Do NOT use Bearish Engulf.

Do NOT use any other Zone calculation method.

============================================================
PULLBACK → CONFIRMATION SEQUENCE — CRITICAL
============================================================

The bot MUST follow:

VALID VS/VR
→ ZONE
→ PULLBACK / RETEST
→ CONFIRMATION
→ ENTRY

If price has NOT returned to the Zone:

WAIT.

ONLY AFTER price reaches/retests the Zone,
start searching for M1/M5 confirmation.

BUY:

VS Zone
→ Pullback / Retest
→ RBS / SRR / I.VR / complete PO2
→ Strong Signal checks
→ BUY

SELL:

VR Zone
→ Pullback / Retest
→ SBR / RSS / I.VS / complete PO2
→ Strong Signal checks
→ SELL

Never issue BUY or SELL before the required
Pullback / Retest → Confirmation sequence is complete.

============================================================
BUY CONFIRMATIONS
============================================================

BUY confirmations ONLY:

RBS
SRR
I.VR
PO2

============================================================
SELL CONFIRMATIONS
============================================================

SELL confirmations ONLY:

SBR
RSS
I.VS
PO2

============================================================
STRONG SIGNAL ENGINE
============================================================

WAIT is preferred over a weak setup.

BUY or SELL ONLY when:

1. Clear VS/VR.
2. Price is at or retesting Zone.
3. Valid confirmation.
4. Confirmation complete.
5. HTF/LTF agree.
6. Logical Entry.
7. Logical SL.
8. Logical TP.
9. RR >= 1:2.
10. Score >= 80.
11. Confidence >= 80.
12. No rejection filter.

============================================================
REJECTION FILTERS
============================================================

WAIT if:

- VS/VR is not clearly proven.
- Zone is ordinary support/resistance.
- Structure incomplete.
- Price far from Zone.
- Price in middle of range.
- Confirmation missing.
- Confirmation incomplete.
- HTF/LTF conflict.
- Entry unclear.
- SL unclear.
- TP unclear.
- RR < 1:2.
- Score < 80.
- Confidence < 80.
- Guessing.
- One candle only.
- Fake breakout suspected.
- Retest missing.
- Chart quality insufficient.

============================================================
WAIT NEXT-ACTION ENGINE
============================================================

When signal = WAIT:

Explain exactly what needs to happen next.

If VS exists but price has not reached it:

"چاوەڕێ بکە نرخ بگەڕێتەوە بۆ Zone ـەکە."

If price reached VS but confirmation missing:

"VS بەردەستە، بەڵام چاوەڕێی RBS یان SRR یان I.VR بکە."

If VR exists but price is not there:

"چاوەڕێ بکە نرخ بگاتە Zone ـەکە."

If price reached VR but confirmation missing:

"VR بەردەستە، بەڵام چاوەڕێی SBR یان RSS یان I.VS بکە."

If breakout happened but retest missing:

"چاوەڕێی retest بکە."

If RR insufficient:

"چاوەڕێی entry ـێکی باشتر یان target ـێکی ڕوونتر بکە."

IMPORTANT:

If a valid Zone exists,
ALWAYS provide its actual price range in:

"zone_price"

If WAIT:

wait_for MUST mention the Zone Price
whenever zone_price is available.

Example:

"Zone Price: 2380.00 - 2382.00"

"چاوەڕێ بکە نرخ بگەڕێتەوە بۆ Zone ـی
2380.00 - 2382.00."

Never invent prices.

============================================================
OUTPUT
============================================================

Return ONLY valid JSON.

No markdown.

No code fences.

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
VS / VR JSON REQUIREMENT
============================================================

For VS:

"vs_detected": {
  "valid": true,
  "original_level": "original Support price/range",
  "formation_candle": "description of original Support candle",
  "validation_level": "NEW Resistance formed AFTER Support",
  "sequence": "SUPPORT → UP → NEW RESISTANCE AFTER SUPPORT → UP AGAIN → BREAK SAME RESISTANCE",
  "break_confirmed": true
}

For invalid VS:

"vs_detected": {
  "valid": false,
  "original_level": "...",
  "formation_candle": "...",
  "validation_level": "N/A",
  "sequence": "Incomplete VS structure",
  "break_confirmed": false
}

For VR:

"vr_detected": {
  "valid": true,
  "original_level": "original Resistance price/range",
  "formation_candle": "description of original Resistance candle",
  "validation_level": "NEW Support formed AFTER Resistance",
  "sequence": "RESISTANCE → DOWN → NEW SUPPORT AFTER RESISTANCE → DOWN AGAIN → BREAK SAME SUPPORT",
  "break_confirmed": true
}

For invalid VR:

"vr_detected": {
  "valid": false,
  "original_level": "...",
  "formation_candle": "...",
  "validation_level": "N/A",
  "sequence": "Incomplete VR structure",
  "break_confirmed": false
}

IMPORTANT:

Do NOT set valid=true unless the COMPLETE structure
is visually proven.

Do NOT use text labels alone.

Do NOT call a normal Support VS.

Do NOT call a normal Resistance VR.

============================================================
LANGUAGE
============================================================

All explanatory text must be Sorani Kurdish.

Technical SNRZ names remain exactly in English.

============================================================
WAIT OUTPUT
============================================================

If WAIT:

entry = "N/A"
sl = "N/A"
tp1 = "N/A"
tp2 = "N/A"
tp3 = "N/A"
rr = "N/A"

wait_for MUST explain what the trader should wait for.

If Zone exists,
wait_for MUST include the actual Zone Price.

============================================================
FINAL PRINCIPLE
============================================================

Do not search for a signal.

Search for the STRUCTURE.

VALID VS/VR
→ ZONE
→ PULLBACK / RETEST
→ CONFIRMATION
→ STRONG SIGNAL CHECK
→ BUY / SELL.

If price has not returned to Zone:

WAIT.

If confirmation has not formed:

WAIT.

If all conditions pass:

BUY / SELL.

If structure does not exist:

WAIT.
"""


# ============================================================
# JSON CLEANER
# ============================================================

def clean_json(text):

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

    start = text.find("{")
    end = text.rfind("}")

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

def safe_float(value):

    try:

        if value is None:
            return None

        if isinstance(
            value,
            (int, float)
        ):

            return float(value)

        value = str(value)

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
# CALCULATE RR
# ============================================================

def calculate_rr(data):

    signal = str(
        data.get(
            "signal",
            "WAIT"
        )
    ).upper()

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


# ============================================================
# DETECT CONFIRMATION
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
            or "SRR" in confirmation
            or "I.VR" in confirmation
            or "PO2" in confirmation
        )

    if signal == "SELL":

        return (
            "SBR" in confirmation
            or "RSS" in confirmation
            or "I.VS" in confirmation
            or "PO2" in confirmation
        )

    return False


# ============================================================
# STRICT VS / VR VALIDATION
# ============================================================

def validate_vs_vr(
    data,
    signal
):

    """
    STRICT STRUCTURE VALIDATION.

    VS:
    SUPPORT
    → UP
    → NEW RESISTANCE AFTER SUPPORT
    → UP AGAIN
    → BREAK SAME RESISTANCE
    → VALID VS

    VR:
    RESISTANCE
    → DOWN
    → NEW SUPPORT AFTER RESISTANCE
    → DOWN AGAIN
    → BREAK SAME SUPPORT
    → VALID VR

    Text labels alone are NEVER enough.
    """

    if signal not in (
        "BUY",
        "SELL"
    ):

        return False


    # ========================================================
    # BUY → VS ONLY
    # ========================================================

    if signal == "BUY":

        vs_data = data.get(
            "vs_detected"
        )

        if not isinstance(
            vs_data,
            dict
        ):

            return False


        valid = (
            vs_data.get(
                "valid",
                False
            )
            is True
        )

        break_confirmed = (
            vs_data.get(
                "break_confirmed",
                False
            )
            is True
        )


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
        ).strip().upper()


        if not valid:

            return False


        if not break_confirmed:

            return False


        if not original_level:

            return False


        if not formation_candle:

            return False


        if not validation_level:

            return False


        if validation_level.upper() in (
            "N/A",
            "NONE",
            "UNKNOWN"
        ):

            return False


        # ----------------------------------------------------
        # REQUIRED STRUCTURAL WORDS
        # ----------------------------------------------------

        required_words = [
            "SUPPORT",
            "RESISTANCE",
            "BREAK"
        ]

        for word in required_words:

            if word not in sequence:

                return False


        # ----------------------------------------------------
        # REQUIRED ORDER
        # ----------------------------------------------------

        support_pos = sequence.find(
            "SUPPORT"
        )

        resistance_pos = sequence.find(
            "RESISTANCE"
        )

        break_pos = sequence.find(
            "BREAK"
        )


        if support_pos == -1:

            return False

        if resistance_pos == -1:

            return False

        if break_pos == -1:

            return False


        if not (
            support_pos
            <
            resistance_pos
            <
            break_pos
        ):

            return False


        # ----------------------------------------------------
        # NEW RESISTANCE MUST BE AFTER SUPPORT
        # ----------------------------------------------------

        if (
            "AFTER SUPPORT"
            not in sequence
        ):

            return False


        # ----------------------------------------------------
        # SECOND UP MOVE MUST EXIST
        # ----------------------------------------------------

        if "UP AGAIN" not in sequence:

            return False


        # ----------------------------------------------------
        # SAME RESISTANCE MUST BE BROKEN
        # ----------------------------------------------------

        if (
            "SAME RESISTANCE"
            not in sequence
        ):

            return False


        return True


    # ========================================================
    # SELL → VR ONLY
    # ========================================================

    if signal == "SELL":

        vr_data = data.get(
            "vr_detected"
        )

        if not isinstance(
            vr_data,
            dict
        ):

            return False


        valid = (
            vr_data.get(
                "valid",
                False
            )
            is True
        )

        break_confirmed = (
            vr_data.get(
                "break_confirmed",
                False
            )
            is True
        )


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
        ).strip().upper()


        if not valid:

            return False


        if not break_confirmed:

            return False


        if not original_level:

            return False


        if not formation_candle:

            return False


        if not validation_level:

            return False


        if validation_level.upper() in (
            "N/A",
            "NONE",
            "UNKNOWN"
        ):

            return False


        # ----------------------------------------------------
        # REQUIRED STRUCTURAL WORDS
        # ----------------------------------------------------

        required_words = [
            "RESISTANCE",
            "SUPPORT",
            "BREAK"
        ]

        for word in required_words:

            if word not in sequence:

                return False


        # ----------------------------------------------------
        # REQUIRED ORDER
        # ----------------------------------------------------

        resistance_pos = sequence.find(
            "RESISTANCE"
        )

        support_pos = sequence.find(
            "SUPPORT"
        )

        break_pos = sequence.find(
            "BREAK"
        )


        if resistance_pos == -1:

            return False

        if support_pos == -1:

            return False

        if break_pos == -1:

            return False


        if not (
            resistance_pos
            <
            support_pos
            <
            break_pos
        ):

            return False


        # ----------------------------------------------------
        # NEW SUPPORT MUST BE AFTER RESISTANCE
        # ----------------------------------------------------

        if (
            "AFTER RESISTANCE"
            not in sequence
        ):

            return False


        # ----------------------------------------------------
        # SECOND DOWN MOVE MUST EXIST
        # ----------------------------------------------------

        if "DOWN AGAIN" not in sequence:

            return False


        # ----------------------------------------------------
        # SAME SUPPORT MUST BE BROKEN
        # ----------------------------------------------------

        if (
            "SAME SUPPORT"
            not in sequence
        ):

            return False


        return True


    return False


# ============================================================
# STRONG SIGNAL ENGINE
# ============================================================

def strong_signal_engine(data):

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

    zone = str(
        data.get(
            "zone",
            ""
        )
    )

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
    # AI WAIT
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
                "هیچ VS/VR ـێکی HTF بە شێوەیەکی ڕوون و بە sequence ـی تەواو پشتڕاست نەکراوەتەوە."
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
                f"📍 Zone Price: {zone_price}\n"
                + data["rejection_reason"]
            )


            if wait_for:

                if zone_price not in wait_for:

                    wait_for = (
                        f"{wait_for}\n"
                        f"📍 Zone Price: {zone_price}"
                    )

            else:

                wait_for = (
                    f"چاوەڕێ بکە نرخ بگەڕێتەوە "
                    f"بۆ Zone ـی {zone_price}."
                )

        else:

            if not wait_for:

                wait_for = (
                    "چاوەڕێی structure ـێکی تەواوی SNRZ "
                    "و confirmation ـی ڕوون بکە."
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

    data["wait_for"] = (
        "N/A"
    )

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
Analyze both XAUUSD chart images.

IMAGE 1 = H1/H4.
IMAGE 2 = M1/M5.

Follow the complete SNRZ structure.

FIRST:

Scan the entire H1/H4 chart.

Identify valid VS and VR only when the complete
structure is proven.

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

CRITICAL:

For VS, the Resistance MUST be created AFTER
the original Support.

For VR, the Support MUST be created AFTER
the original Resistance.

Old Resistance before Support is irrelevant to VS.

Old Support before Resistance is irrelevant to VR.

If the complete sequence is not visible:

valid = false.

Do NOT guess.

For every valid VS/VR provide:

- original_level
- formation_candle
- validation_level
- sequence
- break_confirmed
- valid

ZONE:

VS/VR candle + immediately previous candle
→ compare BODY size
→ shorter BODY wins
→ entire candle HIGH-to-LOW = Zone.

PULLBACK:

VALID VS/VR
→ ZONE
→ PRICE RETURNS/RETESTS ZONE
→ M1/M5 CONFIRMATION
→ STRONG SIGNAL CHECK
→ ENTRY

Never accept confirmation before the Pullback.

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

def format_signal(data):

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

        title = (
            "🟡 WAIT"
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

        text += f# ============================================================
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
    # ADMIN COMMANDS FIRST
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
    # ACCESS REQUEST FOR UNAUTHORIZED USER
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

        }


        telegram.send_message(

            chat_id,

            """
🥇 Gold Chart Analyzer PRO

🧠 SNRZ Structure Engine چالاکە.

سیستەم سەرەتا VS و VR ـی H1/H4 دەناسێت،
پاشان نرخ چاوەڕێ دەکات بگەڕێتەوە بۆ Zone،
دوای Pullback/Retest تەنها confirmation ـی M1/M5 دەپشکنێت.

هەنگاوی 1️⃣:
📸 H1 یان H4 ـی XAUUSD بنێرە.

هەنگاوی 2️⃣:
📸 M1 یان M5 ـی XAUUSD بنێرە.

پاشان تەنها:

🟢 STRONG BUY
🔴 STRONG SELL

یان:

🟡 WAIT

ئەگەر WAIT بوو،
بۆتەکە هۆکاری WAIT و Zone Price ـەکە
بە ڕوونی پیشان دەدات.
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
📚 SNRZ Structure Engine

HTF:
H1 / H4

LTF:
M1 / M5

VS:
Support → Up → NEW Resistance AFTER Support
→ Up → Break NEW Resistance

VR:
Resistance → Down → NEW Support AFTER Resistance
→ Down → Break NEW Support

ZONE:
VS/VR candle + previous candle
→ compare body size
→ shorter body wins
→ entire candle HIGH-to-LOW = Zone

PULLBACK:
Zone
→ wait for price to return/retest Zone
→ ONLY THEN search for Confirmation

BUY:
RBS / SRR / I.VR / PO2

SELL:
SBR / RSS / I.VS / PO2

🔥 Strong Signal:

Score >= 80
Confidence >= 80%
RR >= 1:2
Clear VS/VR
Price has retested Zone
Clear confirmation AFTER Pullback
HTF + LTF agreement

Sequence:

VS/VR
→ Zone
→ Pullback / Retest
→ Confirmation
→ Strong Signal Check
→ Entry

ئەگەر مەرجەکان تەواو نەبن:

🟡 WAIT

هۆکاری WAIT + Zone Price بە ڕوونی پیشان دەدرێت.
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
                "confirmation_image": None,
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

🔎 ئێستا سەرەتا VS و VR ـەکان دەناسین.

پاشان:
📍 چاوەڕێی Pullback / Retest بۆ Zone دەکەین،
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

🧠 SNRZ Structure Engine
VS / VR → Zone → Pullback → Confirmation → Score → Filters

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
        "Gold Chart Analyzer PRO started."
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


            # ------------------------------------------------
            # 409 CONFLICT
            # ------------------------------------------------

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
