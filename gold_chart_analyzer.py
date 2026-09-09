# ============================================================
# GOLD CHART ANALYZER PRO V7 - SNRZ EDITION
# ============================================================
# Flow:
# H1/H4 -> VS/VR -> Zone -> Retest -> M1/M5 Confirmation
# -> HTF/LTF Agreement -> Entry/SL/TP -> RR -> BUY/SELL/WAIT
# Gemini = visual analyst | Python = deterministic validator
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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.7-flash").strip()
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "5874840448"))
ACCESS_FILE = os.getenv("ACCESS_FILE", "allowed_users.json")

MIN_STRONG_SCORE = 80
MIN_STRONG_CONFIDENCE = 80
MIN_RR = 2.0
TELEGRAM_POLL_TIMEOUT = 30
TELEGRAM_RETRY_DELAY = 5
GEMINI_RETRIES = 3
GEMINI_RETRY_DELAY = 3
MAX_TELEGRAM_MESSAGE_LENGTH = 4000
SESSION_TTL_SECONDS = 60 * 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("GoldChartAnalyzerV7")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing.")

gemini = genai.Client(api_key=GEMINI_API_KEY)


class TelegramAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"

    def call(self, method: str, data: Optional[Dict[str, Any]] = None, timeout: int = 60):
        try:
            response = requests.post(f"{self.base_url}/{method}", json=data or {}, timeout=timeout)
        except requests.RequestException as exc:
            raise TelegramAPIError(f"Telegram request failed: {exc}") from exc
        status_code = response.status_code
        try:
            result = response.json()
        except ValueError as exc:
            raise TelegramAPIError(f"Telegram returned invalid JSON (HTTP {status_code}).") from exc
        if status_code != 200:
            raise TelegramAPIError(result.get("description", f"HTTP {status_code}"), status_code)
        if not result.get("ok"):
            raise TelegramAPIError(result.get("description", "Telegram API error"), status_code)
        return result.get("result")

    def get_me(self):
        return self.call("getMe")

    def delete_webhook(self, drop_pending_updates: bool = False):
        return self.call("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    def get_updates(self, offset: Optional[int] = None, timeout: int = TELEGRAM_POLL_TIMEOUT):
        payload = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload, timeout=timeout + 15)

    def send_message(self, chat_id: int, text: str):
        text = str(text or "")
        if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            return self.call("sendMessage", {"chat_id": chat_id, "text": text})
        results = []
        for start in range(0, len(text), MAX_TELEGRAM_MESSAGE_LENGTH):
            results.append(self.call("sendMessage", {"chat_id": chat_id, "text": text[start:start + MAX_TELEGRAM_MESSAGE_LENGTH]}))
        return results

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None):
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self.call("answerCallbackQuery", payload)

    def get_file(self, file_id: str):
        return self.call("getFile", {"file_id": file_id})

    def download_file(self, file_path: str):
        try:
            response = requests.get(f"https://api.telegram.org/file/bot{self.token}/{file_path}", timeout=60)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            raise TelegramAPIError(f"File download failed: {exc}") from exc


telegram = TelegramBot(TELEGRAM_BOT_TOKEN)


# ============================================================
# ACCESS / SESSIONS
# ============================================================

def load_allowed_users() -> set:
    users = {ADMIN_USER_ID}
    if not os.path.exists(ACCESS_FILE):
        return users
    try:
        with open(ACCESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for uid in data:
                try:
                    users.add(int(uid))
                except (ValueError, TypeError):
                    pass
    except Exception:
        logger.exception("Could not load allowed users.")
    users.add(ADMIN_USER_ID)
    return users


ALLOWED_USER_IDS = load_allowed_users()
PENDING_ACCESS_REQUESTS: Dict[int, Dict[str, Any]] = {}
ACCESS_CODES: Dict[str, int] = {}
USER_SESSIONS: Dict[int, Dict[str, Any]] = {}


def save_allowed_users():
    try:
        with open(ACCESS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(ALLOWED_USER_IDS), f, indent=2, ensure_ascii=False)
    except Exception:
        logger.exception("Could not save allowed users.")


def reset_session(chat_id: int):
    USER_SESSIONS.pop(chat_id, None)


def get_session(chat_id: int) -> Dict[str, Any]:
    now = time.time()
    session = USER_SESSIONS.get(chat_id)
    if session and now - session.get("created_at", now) > SESSION_TTL_SECONDS:
        USER_SESSIONS.pop(chat_id, None)
        session = None
    if session is None:
        session = {"zone_image": None, "confirmation_image": None, "created_at": now}
        USER_SESSIONS[chat_id] = session
    return session


def cleanup_sessions():
    now = time.time()
    for chat_id, session in list(USER_SESSIONS.items()):
        if now - session.get("created_at", now) > SESSION_TTL_SECONDS:
            USER_SESSIONS.pop(chat_id, None)


def is_admin(user_id: Optional[int]) -> bool:
    return user_id == ADMIN_USER_ID


def is_allowed(user_id: Optional[int]) -> bool:
    return user_id in ALLOWED_USER_IDS


def deny_access(chat_id: int):
    telegram.send_message(chat_id, "⛔ دەستگەیشتن ڕەتکرایەوە.\n\nبۆ داواکاریی دەستڕاگەیشتن:\n🔑 /start")


def generate_access_code() -> str:
    while True:
        code = "GC-" + secrets.token_hex(3).upper() + "-" + secrets.token_hex(2).upper()
        if code not in ACCESS_CODES:
            return code


def send_access_request(message: Dict[str, Any], chat_id: int, user_id: int):
    if is_allowed(user_id):
        return False
    user = message.get("from", {})
    first_name = user.get("first_name", "Unknown")
    last_name = user.get("last_name", "")
    username = user.get("username", "")
    if user_id in PENDING_ACCESS_REQUESTS:
        request = PENDING_ACCESS_REQUESTS[user_id]
        telegram.send_message(chat_id, f"⏳ داواکارییەکەت پێشتر نێردراوە.\n\n🔑 Access Code:\n{request.get('code', 'N/A')}\n\n🆔 Telegram ID:\n{user_id}\n\nتکایە چاوەڕێی Admin بکە.")
        return True
    code = generate_access_code()
    PENDING_ACCESS_REQUESTS[user_id] = {"user_id": user_id, "chat_id": chat_id, "code": code, "first_name": first_name, "last_name": last_name, "username": username, "created_at": time.time()}
    ACCESS_CODES[code] = user_id
    telegram.send_message(chat_id, f"⏳ داواکاریی دەستڕاگەیشتنت نێردرا بۆ Admin.\n\n🔑 Access Code:\n{code}\n\n🆔 Telegram ID:\n{user_id}\n\n👑 چاوەڕێی Admin بکە.")
    full_name = f"{first_name} {last_name}".strip()
    username_text = f"@{username}" if username else "N/A"
    admin_text = f"🆕 NEW ACCESS REQUEST\n━━━━━━━━━━━━━━━━━━\n👤 Name:\n{full_name}\n\n🔗 Username:\n{username_text}\n\n🆔 User ID:\n{user_id}\n\n🔑 Access Code:\n{code}\n━━━━━━━━━━━━━━━━━━"
    keyboard = {"inline_keyboard": [[{"text": "✅ APPROVE", "callback_data": f"approve:{code}"}, {"text": "❌ REJECT", "callback_data": f"reject:{code}"}]]}
    try:
        telegram.call("sendMessage", {"chat_id": ADMIN_USER_ID, "text": admin_text, "reply_markup": keyboard})
    except Exception:
        logger.exception("Could not notify admin.")
    return True


def handle_access_callback(callback_query: Dict[str, Any]):
    callback_id = callback_query.get("id")
    admin_id = callback_query.get("from", {}).get("id")
    data = callback_query.get("data", "")
    if admin_id != ADMIN_USER_ID:
        telegram.answer_callback_query(callback_id, "⛔ تەنها Admin دەتوانێت.")
        return
    if ":" not in data:
        telegram.answer_callback_query(callback_id, "❌ Request ـەکە نادروستە.")
        return
    action, code = data.split(":", 1)
    user_id = ACCESS_CODES.get(code)
    request = PENDING_ACCESS_REQUESTS.get(user_id) if user_id else None
    if not user_id or not request:
        telegram.answer_callback_query(callback_id, "⚠️ Request نییە یان پێشتر مامەڵەی لەگەڵ کراوە.")
        return
    if action == "approve":
        ALLOWED_USER_IDS.add(user_id)
        save_allowed_users()
        PENDING_ACCESS_REQUESTS.pop(user_id, None)
        ACCESS_CODES.pop(code, None)
        telegram.answer_callback_query(callback_id, "✅ User approved.")
        try:
            telegram.send_message(user_id, "✅ ڕێگەپێدراویت!\n\n🥇 Gold Chart Analyzer PRO V7\n🧠 SNRZ Structure Engine چالاکە.\n\n📸 H1 یان H4 ـی XAUUSD بنێرە.")
        except Exception:
            logger.exception("Could not notify approved user.")
    elif action == "reject":
        PENDING_ACCESS_REQUESTS.pop(user_id, None)
        ACCESS_CODES.pop(code, None)
        telegram.answer_callback_query(callback_id, "❌ User rejected.")
        try:
            telegram.send_message(user_id, "❌ داواکارییەکەت ڕەتکرایەوە.")
        except Exception:
            logger.exception("Could not notify rejected user.")


# ============================================================
# ADMIN COMMANDS
# ============================================================

def handle_admin_command(message: Dict[str, Any], chat_id: int, text: str) -> bool:
    user_id = message.get("from", {}).get("id")
    if not is_admin(user_id):
        return False
    raw_text = str(text or "").strip()
    if not raw_text:
        return False
    parts = raw_text.split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower() if parts else ""
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command == "/adduser":
        if not argument:
            telegram.send_message(chat_id, "❌ نموونە:\n/adduser USER_ID")
            return True
        try:
            new_user_id = int(argument.split()[0])
        except (ValueError, TypeError):
            telegram.send_message(chat_id, "❌ User ID دەبێت ژمارە بێت.")
            return True
        if new_user_id <= 0:
            telegram.send_message(chat_id, "❌ User ID ـەکە دروست نییە.")
            return True
        existed = new_user_id in ALLOWED_USER_IDS
        ALLOWED_USER_IDS.add(new_user_id)
        save_allowed_users()
        req = PENDING_ACCESS_REQUESTS.pop(new_user_id, None)
        if req:
            ACCESS_CODES.pop(req.get("code"), None)
        telegram.send_message(chat_id, f"{'ℹ️ پێشتر ڕێگەپێدراوە' if existed else '✅ بەکارهێنەر زیادکرا'}\n🆔 {new_user_id}\n👥 Total: {len(ALLOWED_USER_IDS)}")
        return True

    if command == "/removeuser":
        if not argument:
            telegram.send_message(chat_id, "❌ نموونە:\n/removeuser USER_ID")
            return True
        try:
            remove_user_id = int(argument.split()[0])
        except (ValueError, TypeError):
            telegram.send_message(chat_id, "❌ User ID دەبێت ژمارە بێت.")
            return True
        if remove_user_id == ADMIN_USER_ID:
            telegram.send_message(chat_id, "⛔ ناتوانیت Admin بسڕیتەوە.")
            return True
        if remove_user_id in ALLOWED_USER_IDS:
            ALLOWED_USER_IDS.remove(remove_user_id)
            save_allowed_users()
            reset_session(remove_user_id)
            telegram.send_message(chat_id, f"✅ User سڕایەوە.\n🆔 {remove_user_id}\n👥 Total: {len(ALLOWED_USER_IDS)}")
        else:
            telegram.send_message(chat_id, f"ℹ️ ئەم User ID ـە لە لیستی Allowed Users ـدا نییە.\n🆔 {remove_user_id}")
        return True

    if command == "/users":
        lines = [f"👑 {uid} — ADMIN" if uid == ADMIN_USER_ID else f"👤 {uid}" for uid in sorted(ALLOWED_USER_IDS)]
        telegram.send_message(chat_id, "👥 ALLOWED USERS\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines) + f"\n\n📊 Total: {len(ALLOWED_USER_IDS)}")
        return True

    if command == "/pending":
        if not PENDING_ACCESS_REQUESTS:
            telegram.send_message(chat_id, "📭 هیچ request ـێکی چاوەڕوان نییە.")
            return True
        lines = []
        for uid, req in PENDING_ACCESS_REQUESTS.items():
            name = f"{req.get('first_name', 'Unknown')} {req.get('last_name', '')}".strip()
            username = f"@{req.get('username')}" if req.get('username') else "N/A"
            lines.append(f"👤 {name}\n🔗 {username}\n🆔 {uid}\n🔑 {req.get('code', 'N/A')}\n━━━━━━━━━━━━━━━━━━")
        telegram.send_message(chat_id, "⏳ PENDING REQUESTS\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines))
        return True

    if command == "/broadcast":
        if not argument:
            telegram.send_message(chat_id, "❌ نموونە:\n/broadcast Hello everyone")
            return True
        success = failed = 0
        for uid in list(ALLOWED_USER_IDS):
            try:
                telegram.send_message(uid, argument)
                success += 1
            except Exception:
                failed += 1
        telegram.send_message(chat_id, f"📢 Broadcast تەواوبوو.\n\n✅ نێردراو: {success}\n❌ سەرکەوتوو نەبوو: {failed}")
        return True

    if command == "/admin":
        telegram.send_message(chat_id, "👑 ADMIN PANEL\n━━━━━━━━━━━━━━━━━━\n➕ /adduser USER_ID\n➖ /removeuser USER_ID\n👥 /users\n⏳ /pending\n📢 /broadcast MESSAGE")
        return True

    if command.startswith("/"):
        telegram.send_message(chat_id, "❌ فەرمانەکە نەناسراوە.\n\n/admin\n/adduser USER_ID\n/removeuser USER_ID\n/users\n/pending\n/broadcast MESSAGE")
        return True
    return False


# ============================================================
# GEMINI PROMPT - CANONICAL STRUCTURE OUTPUT
# ============================================================

SYSTEM_PROMPT = r'''
You are an ELITE XAUUSD SNRZ VISUAL STRUCTURE ANALYST.
Python is the final validator. NEVER invent a trade.

IMAGE 1 = HTF H1/H4. IMAGE 2 = LTF M1/M5.

============================================================
STRICT SNRZ STRUCTURE
============================================================

VS VALID ONLY IF ALL FIVE VISUAL STEPS EXIST IN CHRONOLOGICAL ORDER:
1) SUPPORT
2) UP
3) NEW RESISTANCE CREATED AFTER STEP 1 SUPPORT
4) UP AGAIN
5) BREAK OF THE SAME NEW RESISTANCE FROM STEP 3

VR VALID ONLY IF ALL FIVE VISUAL STEPS EXIST IN CHRONOLOGICAL ORDER:
1) RESISTANCE
2) DOWN
3) NEW SUPPORT CREATED AFTER STEP 1 RESISTANCE
4) DOWN AGAIN
5) BREAK OF THE SAME NEW SUPPORT FROM STEP 3

CRITICAL:
- An old/existing resistance before the support is NOT VS.
- An old/existing support before the resistance is NOT VR.
- Step 3 must explicitly be NEW and AFTER step 1.
- Step 5 must explicitly break the SAME level created in step 3.
- If the chart does not clearly prove this sequence, structure_valid=false and structure_direction=NONE.
- Do not choose VS/VR merely because the chart is bullish/bearish.
- Normal support/resistance alone is NOT VS/VR.

IMPORTANT OUTPUT FORMAT FOR STRUCTURE STEPS:
The five structure_step fields MUST use these canonical English labels plus short evidence, so Python can validate them:
VS example:
"SUPPORT | clear support visible"
"UP | bullish move from support"
"NEW RESISTANCE AFTER SUPPORT | new high/resistance formed after support"
"UP AGAIN | second bullish move"
"BREAK SAME NEW RESISTANCE | same step-3 resistance broken"

VR example:
"RESISTANCE | clear resistance visible"
"DOWN | bearish move from resistance"
"NEW SUPPORT AFTER RESISTANCE | new low/support formed after resistance"
"DOWN AGAIN | second bearish move"
"BREAK SAME NEW SUPPORT | same step-3 support broken"

If a step is not visually proven, write "NOT PROVEN" for that step and set structure_valid=false.

============================================================
ZONE
============================================================
After a valid VS/VR:
- Compare formation candle body with immediately previous candle body.
- SHORTER BODY wins.
- Selected candle FULL HIGH-to-LOW is the Zone.
- Never use wick comparison to choose the candle.
- Never invent Zone prices.

============================================================
SEQUENCE
============================================================
VALID VS/VR -> ZONE -> PRICE RETURNS/RETESTS ZONE -> CONFIRMATION -> ENTRY.
Confirmation before retest is INVALID.

============================================================
CONFIRMATIONS
============================================================
BUY: RBS, SRR, I.VR, PO2
SELL: SBR, RSS, I.VS, PO2

============================================================
HTF/LTF
============================================================
BUY requires HTF=BULLISH and LTF=BULLISH.
SELL requires HTF=BEARISH and LTF=BEARISH.

============================================================
TRADE LEVELS
============================================================
BUY: SL < Entry < TP1.
SELL: TP1 < Entry < SL.
RR >= 1:2 required.
Strong rejection/fake breakout => WAIT.

============================================================
NO GUESSING
============================================================
If any required visual evidence is unclear, mark the related boolean false.
If structure is incomplete, structure_valid=false and structure_direction=NONE.
Return JSON ONLY. All explanations except canonical SNRZ labels may be Sorani Kurdish.
'''


GEMINI_SCHEMA = {
    "type": "object",
    "properties": {
        "signal": {"type": "string"}, "symbol": {"type": "string"},
        "structure_direction": {"type": "string"}, "structure_valid": {"type": "boolean"},
        "structure_step_1": {"type": "string"}, "structure_step_2": {"type": "string"},
        "structure_step_3": {"type": "string"}, "structure_step_4": {"type": "string"},
        "structure_step_5": {"type": "string"}, "vs_detected": {"type": "string"}, "vr_detected": {"type": "string"},
        "zone_valid": {"type": "boolean"}, "zone_low": {"type": "string"}, "zone_high": {"type": "string"},
        "zone": {"type": "string"}, "zone_price": {"type": "string"}, "zone_candle": {"type": "string"},
        "previous_candle": {"type": "string"}, "selected_candle": {"type": "string"}, "selected_body": {"type": "string"},
        "price_at_zone": {"type": "boolean"}, "pullback_valid": {"type": "boolean"}, "pullback_evidence": {"type": "string"},
        "confirmation": {"type": "string"}, "confirmation_valid": {"type": "boolean"},
        "confirmation_after_retest": {"type": "boolean"}, "confirmation_evidence": {"type": "string"},
        "htf_direction": {"type": "string"}, "ltf_direction": {"type": "string"}, "htf_ltf_agreement": {"type": "boolean"},
        "entry_valid": {"type": "boolean"}, "sl_valid": {"type": "boolean"}, "tp_valid": {"type": "boolean"},
        "entry": {"type": "string"}, "sl": {"type": "string"}, "tp1": {"type": "string"}, "tp2": {"type": "string"}, "tp3": {"type": "string"}, "rr": {"type": "string"},
        "setup": {"type": "string"}, "trend": {"type": "string"}, "reasoning": {"type": "string"}, "checks": {"type": "string"},
        "rejection_present": {"type": "boolean"}, "rejection_reason": {"type": "string"}, "wait_for": {"type": "string"},
        "score": {"type": "number"}, "confidence": {"type": "number"}
    },
    "required": [
        "signal","symbol","structure_direction","structure_valid","structure_step_1","structure_step_2","structure_step_3","structure_step_4","structure_step_5","vs_detected","vr_detected","zone_valid","zone_low","zone_high","zone","zone_price","zone_candle","previous_candle","selected_candle","selected_body","price_at_zone","pullback_valid","pullback_evidence","confirmation","confirmation_valid","confirmation_after_retest","confirmation_evidence","htf_direction","ltf_direction","htf_ltf_agreement","entry_valid","sl_valid","tp_valid","entry","sl","tp1","tp2","tp3","rr","setup","trend","reasoning","checks","rejection_present","rejection_reason","wait_for","score","confidence"
    ]
}

DEFAULT_FIELDS = list(GEMINI_SCHEMA["required"])


def clean_text(value: Any, default: str = "N/A") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
        return float(match.group()) if match else None
    except Exception:
        return None


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "yes", "valid", "confirmed", "complete"}


def normalize_side(value: Any) -> str:
    text = clean_text(value, "WAIT").upper()
    return text if text in {"BUY", "SELL"} else "WAIT"


def normalize_structure(value: Any) -> str:
    text = clean_text(value, "NONE").upper()
    return text if text in {"VS", "VR"} else "NONE"


def normalize_result(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    result = {key: data.get(key) for key in DEFAULT_FIELDS}
    result["signal"] = normalize_side(result.get("signal"))
    result["symbol"] = "XAUUSD"
    result["structure_direction"] = normalize_structure(result.get("structure_direction"))
    for key in ["structure_valid","zone_valid","price_at_zone","pullback_valid","confirmation_valid","confirmation_after_retest","htf_ltf_agreement","entry_valid","sl_valid","tp_valid","rejection_present"]:
        result[key] = parse_bool(result.get(key))
    return result


def clean_json(text: str) -> str:
    if not text:
        raise RuntimeError("Gemini returned empty response.")
    text = re.sub(r"^```json\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError("Gemini did not return JSON.")
    return text[start:end + 1]


def parse_zone_range(low_value: Any, high_value: Any) -> Optional[Tuple[float, float]]:
    low, high = safe_float(low_value), safe_float(high_value)
    if low is None or high is None or high <= low:
        return None
    return low, high


def zone_from_data(data: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    zone = parse_zone_range(data.get("zone_low"), data.get("zone_high"))
    if zone:
        return zone
    numbers = re.findall(r"-?\d+(?:\.\d+)?", clean_text(data.get("zone_price"), "").replace(",", ""))
    if len(numbers) >= 2:
        a, b = float(numbers[0]), float(numbers[1])
        if a != b:
            return min(a, b), max(a, b)
    return None


# ============================================================
# ROBUST VS/VR VALIDATION
# ============================================================

VS_SUPPORT = ("SUPPORT", "SUP", "پشتگیری", "پاڵپشتی", "پاڵپشت")
VS_UP = ("UP", "BULL", "BULLISH", "سەر", "بەرز", "بەرەو سەر")
VS_RESISTANCE = ("RESISTANCE", "RES", "بەرگری", "ڕێگر", "مقاومەت")
VR_DOWN = ("DOWN", "BEAR", "BEARISH", "خوار", "دابەزین", "بەرەو خوار")
VR_SUPPORT = VS_SUPPORT
VR_RESISTANCE = VS_RESISTANCE
NEW_WORDS = ("NEW", "نوێ", "دروست", "دروستکرا")
AFTER_WORDS = ("AFTER", "POST", "دوای", "پاش", "لە دوای")
SAME_WORDS = ("SAME", "هەمان", "هەمانە")
BREAK_WORDS = ("BREAK", "شکاند", "شکێند", "شکاندنی", "شکاندرا")
FORBIDDEN_OLD = ("OLD", "PREVIOUS", "EXISTING BEFORE", "BEFORE SUPPORT", "BEFORE RESISTANCE", "کۆن", "پێشتر", "پێش")


def contains_any(text: str, words: Tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def structure_steps_valid(data: Dict[str, Any], direction: str) -> bool:
    if data.get("structure_valid") is not True:
        return False
    if normalize_structure(data.get("structure_direction")) != direction:
        return False
    steps = [clean_text(data.get(f"structure_step_{i}"), "").strip().upper() for i in range(1, 6)]
    if any(not step or step == "NOT PROVEN" for step in steps):
        return False

    if direction == "VS":
        if not contains_any(steps[0], VS_SUPPORT):
            return False
        if not contains_any(steps[1], VS_UP):
            return False
        if not contains_any(steps[2], VS_RESISTANCE) or not contains_any(steps[2], NEW_WORDS) or not contains_any(steps[2], AFTER_WORDS):
            return False
        if contains_any(steps[2], ("BEFORE SUPPORT", "EXISTED BEFORE", "OLD RESISTANCE", "PREVIOUS RESISTANCE")):
            return False
        if not contains_any(steps[3], VS_UP):
            return False
        if not contains_any(steps[4], BREAK_WORDS) or not contains_any(steps[4], VS_RESISTANCE):
            return False
        if not contains_any(steps[4], SAME_WORDS) and "NEW RESISTANCE" not in steps[4]:
            return False
        if contains_any(steps[4], ("OLD RESISTANCE", "PREVIOUS RESISTANCE", "DIFFERENT RESISTANCE", "ANOTHER RESISTANCE")):
            return False
        return True

    if direction == "VR":
        if not contains_any(steps[0], VR_RESISTANCE):
            return False
        if not contains_any(steps[1], VR_DOWN):
            return False
        if not contains_any(steps[2], VR_SUPPORT) or not contains_any(steps[2], NEW_WORDS) or not contains_any(steps[2], AFTER_WORDS):
            return False
        if contains_any(steps[2], ("BEFORE RESISTANCE", "EXISTED BEFORE", "OLD SUPPORT", "PREVIOUS SUPPORT")):
            return False
        if not contains_any(steps[3], VR_DOWN):
            return False
        if not contains_any(steps[4], BREAK_WORDS) or not contains_any(steps[4], VR_SUPPORT):
            return False
        if not contains_any(steps[4], SAME_WORDS) and "NEW SUPPORT" not in steps[4]:
            return False
        if contains_any(steps[4], ("OLD SUPPORT", "PREVIOUS SUPPORT", "DIFFERENT SUPPORT", "ANOTHER SUPPORT")):
            return False
        return True
    return False


def validate_structure(data: Dict[str, Any], signal_side: str) -> bool:
    expected = "VS" if signal_side == "BUY" else "VR" if signal_side == "SELL" else "NONE"
    if expected == "NONE":
        return False
    structure = normalize_structure(data.get("structure_direction"))
    if structure != expected:
        return False
    # Never allow both structures to be declared at the same time.
    vs_text = clean_text(data.get("vs_detected"), "").upper()
    vr_text = clean_text(data.get("vr_detected"), "").upper()
    if structure == "VS" and contains_any(vr_text, ("VALID", "CONFIRMED")) and "INVALID" not in vr_text:
        return False
    if structure == "VR" and contains_any(vs_text, ("VALID", "CONFIRMED")) and "INVALID" not in vs_text:
        return False
    return structure_steps_valid(data, expected)


# ============================================================
# ZONE / RETEST / CONFIRMATION / LEVELS
# ============================================================

def validate_zone(data: Dict[str, Any], signal_side: str) -> bool:
    if data.get("zone_valid") is not True:
        return False
    expected = "VS" if signal_side == "BUY" else "VR"
    if normalize_structure(data.get("structure_direction")) != expected:
        return False
    if zone_from_data(data) is None:
        return False
    if not clean_text(data.get("selected_candle"), "") or not clean_text(data.get("previous_candle"), ""):
        return False
    body = clean_text(data.get("selected_body"), "").upper()
    return contains_any(body, ("SHORTER", "SMALLER", "کورت", "بچووک"))


def validate_price_at_zone(data: Dict[str, Any]) -> bool:
    return data.get("price_at_zone") is True


def validate_pullback(data: Dict[str, Any]) -> bool:
    return data.get("pullback_valid") is True and bool(clean_text(data.get("pullback_evidence"), ""))


BUY_CONFIRMATIONS = {"RBS", "SRR", "I.VR", "PO2"}
SELL_CONFIRMATIONS = {"SBR", "RSS", "I.VS", "PO2"}


def confirmation_name(value: Any) -> str:
    text = clean_text(value, "").upper()
    for name in ("I.VR", "I.VS", "RBS", "SBR", "SRR", "RSS", "PO2"):
        if name in text:
            return name
    return ""


def validate_confirmation(data: Dict[str, Any], signal_side: str) -> bool:
    name = confirmation_name(data.get("confirmation"))
    allowed = BUY_CONFIRMATIONS if signal_side == "BUY" else SELL_CONFIRMATIONS if signal_side == "SELL" else set()
    return bool(name and name in allowed and data.get("confirmation_valid") is True and data.get("confirmation_after_retest") is True and clean_text(data.get("confirmation_evidence"), ""))


def validate_htf_ltf(data: Dict[str, Any], signal_side: str) -> bool:
    htf = clean_text(data.get("htf_direction"), "UNKNOWN").upper()
    ltf = clean_text(data.get("ltf_direction"), "UNKNOWN").upper()
    if signal_side == "BUY":
        return htf == "BULLISH" and ltf == "BULLISH" and data.get("htf_ltf_agreement") is True
    if signal_side == "SELL":
        return htf == "BEARISH" and ltf == "BEARISH" and data.get("htf_ltf_agreement") is True
    return False


def calculate_rr(data: Dict[str, Any], signal_side: str) -> Optional[float]:
    entry, sl, tp1 = safe_float(data.get("entry")), safe_float(data.get("sl")), safe_float(data.get("tp1"))
    if None in (entry, sl, tp1):
        return None
    if signal_side == "BUY":
        risk, reward = entry - sl, tp1 - entry
    elif signal_side == "SELL":
        risk, reward = sl - entry, entry - tp1
    else:
        return None
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def validate_trade_levels(data: Dict[str, Any], signal_side: str) -> bool:
    entry, sl, tp1 = safe_float(data.get("entry")), safe_float(data.get("sl")), safe_float(data.get("tp1"))
    if None in (entry, sl, tp1):
        return False
    if not (data.get("entry_valid") is True and data.get("sl_valid") is True and data.get("tp_valid") is True):
        return False
    return (sl < entry < tp1) if signal_side == "BUY" else (tp1 < entry < sl) if signal_side == "SELL" else False


def validate_rejection(data: Dict[str, Any]) -> bool:
    return data.get("rejection_present") is not True


# ============================================================
# FINAL DETERMINISTIC ENGINE
# ============================================================

def validation_checks(data: Dict[str, Any], signal_side: str) -> Dict[str, bool]:
    rr = calculate_rr(data, signal_side)
    return {
        "structure": validate_structure(data, signal_side),
        "zone": validate_zone(data, signal_side),
        "price_at_zone": validate_price_at_zone(data),
        "pullback": validate_pullback(data),
        "confirmation": validate_confirmation(data, signal_side),
        "htf_ltf": validate_htf_ltf(data, signal_side),
        "levels": validate_trade_levels(data, signal_side),
        "rr": rr is not None and rr >= MIN_RR,
        "no_rejection": validate_rejection(data),
    }


def deterministic_score(checks: Dict[str, bool]) -> int:
    weights = {"structure": 20, "zone": 15, "price_at_zone": 10, "pullback": 10, "confirmation": 15, "htf_ltf": 10, "levels": 5, "rr": 10, "no_rejection": 5}
    return min(100, sum(weight for key, weight in weights.items() if checks.get(key, False)))


def deterministic_confidence(checks: Dict[str, bool], score: int, rr: Optional[float]) -> int:
    confidence = score
    if rr is not None:
        if rr >= 3.0:
            confidence += 5
        elif rr >= 2.5:
            confidence += 3
        elif rr >= 2.0:
            confidence += 1
    if not checks.get("no_rejection", False):
        confidence -= 20
    return max(0, min(100, confidence))


def determine_direction(data: Dict[str, Any]) -> str:
    structure = normalize_structure(data.get("structure_direction"))
    return "BUY" if structure == "VS" else "SELL" if structure == "VR" else "WAIT"


def missing_reasons(data: Dict[str, Any], signal_side: str, checks: Dict[str, bool]) -> List[str]:
    reasons = []
    if not checks["structure"]:
        reasons.append("SNRZ structure ـی 5 step بە تەواوی پشتڕاست نەکراوەتەوە.")
    if not checks["zone"]:
        reasons.append("Zone بە یاسای shorter body پشتڕاست نەکراوەتەوە.")
    if not checks["price_at_zone"]:
        reasons.append("نرخ هێشتا بە ڕوونی نەگەڕاوەتەوە بۆ Zone.")
    if not checks["pullback"]:
        reasons.append("Pullback / Retest هێشتا پشتڕاست نەکراوەتەوە.")
    if not checks["confirmation"]:
        reasons.append(f"Confirmation ـی {signal_side} دوای Retest نییە.")
    if not checks["htf_ltf"]:
        reasons.append("HTF و LTF بە یەک ئاراستەی پێویست نین.")
    if not checks["levels"]:
        reasons.append("Entry / SL / TP بە شێوەی لۆجیکی پشتڕاست نەکراونەتەوە.")
    if not checks["rr"]:
        reasons.append("RR کەمترە لە 1:2 یان ناتوانرێت بە دروستی حساب بکرێت.")
    if not checks["no_rejection"]:
        reasons.append("Strong rejection یان fake breakout هەیە.")
    return reasons


def next_action(data: Dict[str, Any], signal_side: str, checks: Dict[str, bool]) -> str:
    zone = zone_from_data(data)
    zone_text = f"{zone[0]:.2f} - {zone[1]:.2f}" if zone else "N/A"
    if not checks["structure"]:
        return "چاوەڕێی VS بکە: Support → Up → NEW Resistance → Up Again → Break SAME NEW Resistance." if signal_side == "BUY" else "چاوەڕێی VR بکە: Resistance → Down → NEW Support → Down Again → Break SAME NEW Support." if signal_side == "SELL" else "چاوەڕێی VS یان VR ـی تەواو بکە."
    if not checks["zone"]:
        return "Zone هێشتا بە یاسای shorter body پشتڕاست نەکراوەتەوە."
    if not checks["price_at_zone"]:
        return f"چاوەڕێ بکە نرخ بگەڕێتەوە بۆ Zone: {zone_text}"
    if not checks["pullback"]:
        return f"نرخ لە Zone ـە، بەڵام Retest هێشتا تەواو نییە.\n📍 Zone: {zone_text}"
    if not checks["confirmation"]:
        return "Retest تەواوە؛ چاوەڕێی Confirmation ـی BUY: RBS / SRR / I.VR / PO2 بکە." if signal_side == "BUY" else "Retest تەواوە؛ چاوەڕێی Confirmation ـی SELL: SBR / RSS / I.VS / PO2 بکە."
    if not checks["htf_ltf"]:
        return "چاوەڕێ بکە HTF و LTF لە یەک ئاراستەی پێویست کۆببنەوە."
    if not checks["levels"]:
        return "چاوەڕێی Entry / SL / TP ـی لۆجیکی بکە."
    if not checks["rr"]:
        return "چاوەڕێی setup ـێک بکە کە RR ـی لانیکەم 1:2 هەبێت."
    if not checks["no_rejection"]:
        return "چاوەڕێی setup ـێکی پاک بکە کە rejection یان fake breakout تێدا نەبێت."
    return "هەموو مەرجەکان هێشتا کۆنەبوونەتەوە."


def run_final_engine(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    data = normalize_result(raw_data)
    structure = normalize_structure(data.get("structure_direction"))
    if structure == "NONE":
        data.update({"signal": "WAIT", "entry": "N/A", "sl": "N/A", "tp1": "N/A", "tp2": "N/A", "tp3": "N/A", "rr": "N/A", "score": 0, "confidence": 0})
        data["rejection_reason"] = "VS یان VR ـی تەواو بە دڵنیایی نەدۆزرایەوە."
        data["wait_for"] = "چاوەڕێی VS یان VR ـی تەواو بکە."
        return data
    signal_side = determine_direction(data)
    checks = validation_checks(data, signal_side)
    score = deterministic_score(checks)
    rr = calculate_rr(data, signal_side)
    confidence = deterministic_confidence(checks, score, rr)
    valid = all(checks.values()) and score >= MIN_STRONG_SCORE and confidence >= MIN_STRONG_CONFIDENCE
    data["score"], data["confidence"] = score, confidence
    if valid:
        data["signal"] = signal_side
        data["rr"] = f"1:{rr:.2f}" if rr is not None else "N/A"
        data["wait_for"] = "N/A"
        data["rejection_reason"] = "هیچ rejection ـێکی بەهێز نییە."
        return data
    data["signal"] = "WAIT"
    data["entry"] = data["sl"] = data["tp1"] = data["tp2"] = data["tp3"] = data["rr"] = "N/A"
    reasons = missing_reasons(data, signal_side, checks)
    data["rejection_reason"] = "\n".join(f"❌ {r}" for r in reasons) if reasons else "هەموو مەرجەکانی Strong Signal تەواو نەبوون."
    data["wait_for"] = next_action(data, signal_side, checks)
    return data


# ============================================================
# GEMINI
# ============================================================

def make_image_part(image_bytes: bytes, mime_type: str = "image/jpeg"):
    return types.Part.from_bytes(data=image_bytes, mime_type=mime_type)


def call_gemini_model(model_name: str, zone_image: bytes, confirmation_image: bytes) -> str:
    prompt = r'''
Analyze TWO XAUUSD screenshots.
IMAGE 1 = H1/H4 HTF. IMAGE 2 = M1/M5 LTF.

Follow the system prompt exactly.

Before declaring VS or VR, verify all five steps visually and chronologically.
For structure_step_1..5 use the canonical English labels exactly:
VS: SUPPORT | ..., UP | ..., NEW RESISTANCE AFTER SUPPORT | ..., UP AGAIN | ..., BREAK SAME NEW RESISTANCE | ...
VR: RESISTANCE | ..., DOWN | ..., NEW SUPPORT AFTER RESISTANCE | ..., DOWN AGAIN | ..., BREAK SAME NEW SUPPORT | ...
If not visually proven, use NOT PROVEN and structure_valid=false, structure_direction=NONE.

Do not guess Zone, prices, retest, confirmation, or levels.
Return JSON ONLY.
'''
    image1 = make_image_part(zone_image)
    image2 = make_image_part(confirmation_image)
    config = types.GenerateContentConfig(temperature=0.1, response_mime_type="application/json", response_schema=GEMINI_SCHEMA)
    try:
        response = gemini.models.generate_content(model=model_name, contents=[SYSTEM_PROMPT, prompt, image1, image2], config=config)
    except TypeError:
        response = gemini.models.generate_content(model=model_name, contents=[SYSTEM_PROMPT, prompt, image1, image2], config={"temperature": 0.1, "response_mime_type": "application/json", "response_schema": GEMINI_SCHEMA})
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini returned empty response.")
    return text


def retryable_gemini_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(word in text for word in ("429", "500", "502", "503", "504", "timeout", "temporarily", "unavailable", "resource exhausted", "rate limit"))


def analyze_two_charts(zone_image: bytes, confirmation_image: bytes) -> Dict[str, Any]:
    models = [m for m in (GEMINI_MODEL, GEMINI_FALLBACK_MODEL) if m]
    models = list(dict.fromkeys(models))
    last_error = None
    for model_name in models:
        for attempt in range(1, GEMINI_RETRIES + 1):
            try:
                logger.info(f"Gemini model={model_name} attempt={attempt}/{GEMINI_RETRIES}")
                raw = call_gemini_model(model_name, zone_image, confirmation_image)
                parsed = json.loads(clean_json(raw))
                return run_final_engine(normalize_result(parsed))
            except Exception as exc:
                last_error = exc
                logger.exception("Gemini analysis failed.")
                if attempt < GEMINI_RETRIES and retryable_gemini_error(exc):
                    time.sleep(GEMINI_RETRY_DELAY * attempt)
                    continue
                break
    raise RuntimeError(f"Gemini analysis failed: {last_error}")


# ============================================================
# TELEGRAM OUTPUT
# ============================================================

def download_telegram_photo(message: Dict[str, Any]) -> Optional[bytes]:
    photos = message.get("photo")
    if not photos:
        return None
    file_id = photos[-1].get("file_id")
    if not file_id:
        return None
    info = telegram.get_file(file_id)
    path = info.get("file_path")
    if not path:
        raise RuntimeError("Telegram file_path missing.")
    return telegram.download_file(path)


def format_checks(data: Dict[str, Any]) -> str:
    signal_side = normalize_side(data.get("signal"))
    if signal_side not in {"BUY", "SELL"}:
        signal_side = determine_direction(data)
    if signal_side not in {"BUY", "SELL"}:
        return "❌ Strong validation path نییە."
    checks = validation_checks(data, signal_side)
    names = [("SNRZ Structure", "structure"), ("Zone", "zone"), ("Price at Zone", "price_at_zone"), ("Pullback / Retest", "pullback"), ("Confirmation", "confirmation"), ("HTF / LTF", "htf_ltf"), ("Entry / SL / TP", "levels"), ("RR >= 1:2", "rr"), ("No Rejection", "no_rejection")]
    return "\n".join(f"{'✅' if checks[key] else '❌'} {name}" for name, key in names)


def format_signal(data: Dict[str, Any]) -> str:
    signal_side = normalize_side(data.get("signal"))
    title = "🟢 STRONG BUY SIGNAL" if signal_side == "BUY" else "🔴 STRONG SELL SIGNAL" if signal_side == "SELL" else "🟡 WAIT"
    score = safe_float(data.get("score"))
    confidence = safe_float(data.get("confidence"))
    zone = zone_from_data(data)
    zone_price = f"{zone[0]:.2f} - {zone[1]:.2f}" if zone else clean_text(data.get("zone_price"), "N/A")
    score_text = f"{score:.0f}/100" if score is not None else "0/100"
    confidence_text = f"{confidence:.0f}%" if confidence is not None else "0%"
    text = f'''{title}
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
{clean_text(data.get("vs_detected"), "نادیارە")}

🔴 VR:
{clean_text(data.get("vr_detected"), "نادیارە")}

🔎 Confirmation:
{clean_text(data.get("confirmation"), "NONE")}

📊 HTF:
{clean_text(data.get("htf_direction"), "UNKNOWN")}

📊 LTF:
{clean_text(data.get("ltf_direction"), "UNKNOWN")}
'''
    text = text.strip()
    if signal_side in {"BUY", "SELL"}:
        text += f'''\n\n━━━━━━━━━━━━━━━━━━

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
'''
    text += f'''\n━━━━━━━━━━━━━━━━━━

🔎 هۆکاری شیکردنەوە:

{clean_text(data.get("reasoning"), "هیچ بەڵگەی تەواو نییە.")}

━━━━━━━━━━━━━━━━━━

✅ Final Checks:

{format_checks(data)}'''
    if signal_side == "WAIT":
        text += f'''\n\n━━━━━━━━━━━━━━━━━━

🚫 هۆکاری WAIT:

{clean_text(data.get("rejection_reason"), "هەموو مەرجەکانی Strong Signal تەواو نەبوون.")}

━━━━━━━━━━━━━━━━━━

👀 چاوەڕێی چی بکەین؟

{clean_text(data.get("wait_for"), "چاوەڕێی setup ـێکی تەواو بکە.")}

━━━━━━━━━━━━━━━━━━

⚠️ هیچ Entry ـێک تا تەواوبوونی
هەموو مەرجە سەرەکییەکان نابێت.'''
    else:
        text += "\n\n━━━━━━━━━━━━━━━━━━\n\n🔥 STRONG SNRZ SETUP\n\nهەموو مەرجە سەرەکییەکانی SNRZ validation تێپەڕێنراون.\n\n⚠️ ئەمە شیکردنەوەی تەکنیکییە؛ دڵنیایی بە قازانج نادات."
    return text.strip()


START_MESSAGE = """🥇 Gold Chart Analyzer PRO V7

🧠 SNRZ Structure Engine
━━━━━━━━━━━━━━━━━━

VS / VR → Zone → Pullback / Retest → M1/M5 Confirmation → HTF/LTF Agreement → RR → BUY / SELL / WAIT

📸 هەنگاوی 1: H1 یان H4 ـی XAUUSD بنێرە.
📸 هەنگاوی 2: M1 یان M5 بنێرە.

ئەگەر مەرجەکان تەواو نەبن: 🟡 WAIT

/reset
/help"""

HELP_MESSAGE = """📚 Gold Chart Analyzer PRO V7
━━━━━━━━━━━━━━━━━━

🟢 VS:
Support → Up → NEW Resistance → Up Again → Break SAME NEW Resistance

🔴 VR:
Resistance → Down → NEW Support → Down Again → Break SAME NEW Support

🟦 Zone:
Formation candle + immediately previous candle → shorter BODY wins → full HIGH-to-LOW

🔄 Sequence:
VS/VR → Zone → Retest → Confirmation → Entry

🟢 BUY: RBS / SRR / I.VR / PO2
🔴 SELL: SBR / RSS / I.VS / PO2

🔥 STRONG: Score >= 80, Confidence >= 80%, RR >= 1:2

Otherwise: 🟡 WAIT

/reset"""


# ============================================================
# MESSAGE / UPDATE HANDLERS
# ============================================================

def handle_message(message: Dict[str, Any]):
    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        return
    user_id = message.get("from", {}).get("id")
    text = clean_text(message.get("text"), "").strip()

    if is_admin(user_id) and handle_admin_command(message, chat_id, text):
        return
    if not is_allowed(user_id):
        if text == "/start":
            send_access_request(message, chat_id, user_id)
        else:
            deny_access(chat_id)
        return
    if text == "/start":
        reset_session(chat_id)
        get_session(chat_id)
        telegram.send_message(chat_id, START_MESSAGE)
        return
    if text == "/help":
        telegram.send_message(chat_id, HELP_MESSAGE)
        return
    if text == "/reset":
        reset_session(chat_id)
        telegram.send_message(chat_id, "♻️ Session reset کرا.\n\n📸 ئێستا H1 یان H4 ـی XAUUSD بنێرە.")
        return

    photo = download_telegram_photo(message)
    if photo is not None:
        session = get_session(chat_id)
        if session.get("zone_image") is None:
            session["zone_image"] = photo
            telegram.send_message(chat_id, "✅ H1/H4 وەرگیرا.\n\n🧠 HTF: VS / VR → Zone\n\n📸 ئێستا M1 یان M5 بنێرە بۆ Retest + Confirmation.")
            return
        if session.get("confirmation_image") is None:
            session["confirmation_image"] = photo
            telegram.send_message(chat_id, "⏳ هەردوو chart وەرگیرا.\n\n🧠 V7 Engine: VS/VR → Zone → Retest → Confirmation → HTF/LTF → RR → Final Validation\n\n⏳ تکایە چاوەڕێ بکە...")
            try:
                result = analyze_two_charts(session["zone_image"], session["confirmation_image"])
                telegram.send_message(chat_id, format_signal(result))
            except Exception as exc:
                logger.exception("Analysis failed.")
                telegram.send_message(chat_id, f"❌ شیکردنەوەکە نەکرا.\n\nهۆکار:\n{exc}\n\n/reset")
            finally:
                reset_session(chat_id)
            return

    telegram.send_message(chat_id, "تکایە chart بنێرە:\n\n1️⃣ H1 یان H4\n2️⃣ M1 یان M5\n\nیان /help /reset")


def handle_update(update: Dict[str, Any]):
    callback_query = update.get("callback_query")
    if callback_query:
        try:
            handle_access_callback(callback_query)
        except Exception:
            logger.exception("Callback handling error.")
        return
    message = update.get("message")
    if not message:
        return
    try:
        handle_message(message)
    except TelegramAPIError:
        logger.exception("Telegram API error.")
    except Exception:
        logger.exception("Message handling error.")


def initialize_telegram():
    logger.info("Connecting to Telegram...")
    me = telegram.get_me()
    logger.info(f"Telegram connected: @{me.get('username', 'unknown')}")
    telegram.delete_webhook(drop_pending_updates=False)
    logger.info("Webhook removed. Long polling ready.")


RUNNING = True


def stop_bot(signum, frame):
    global RUNNING
    logger.info(f"Shutdown signal received: {signum}")
    RUNNING = False


signal.signal(signal.SIGINT, stop_bot)
signal.signal(signal.SIGTERM, stop_bot)


def run():
    logger.info("==================================================")
    logger.info("Gold Chart Analyzer PRO V7 starting...")
    logger.info(f"Gemini model: {GEMINI_MODEL}")
    logger.info(f"Gemini fallback: {GEMINI_FALLBACK_MODEL}")
    logger.info(f"Admin ID: {ADMIN_USER_ID}")
    logger.info(f"Allowed users: {len(ALLOWED_USER_IDS)}")
    logger.info(f"Minimum score: {MIN_STRONG_SCORE}")
    logger.info(f"Minimum confidence: {MIN_STRONG_CONFIDENCE}%")
    logger.info(f"Minimum RR: 1:{MIN_RR}")
    logger.info("==================================================")

    while RUNNING:
        try:
            initialize_telegram()
            break
        except TelegramAPIError as exc:
            logger.error(f"Telegram initialization failed: {exc}")
            time.sleep(TELEGRAM_RETRY_DELAY)
        except Exception:
            logger.exception("Initialization error.")
            time.sleep(TELEGRAM_RETRY_DELAY)

    offset = None
    while RUNNING:
        try:
            cleanup_sessions()
            updates = telegram.get_updates(offset=offset, timeout=TELEGRAM_POLL_TIMEOUT)
            if not updates:
                continue
            for update in updates:
                if not RUNNING:
                    break
                update_id = update.get("update_id")
                if update_id is not None:
                    offset = update_id + 1
                handle_update(update)
        except TelegramAPIError as exc:
            text = str(exc).lower()
            if exc.status_code == 409 or "409" in text or "conflict" in text:
                logger.error("TELEGRAM 409 CONFLICT: another process is polling this bot token. Only ONE instance is allowed.")
                time.sleep(10)
            else:
                logger.exception("Telegram polling error.")
                time.sleep(TELEGRAM_RETRY_DELAY)
        except KeyboardInterrupt:
            break
        except Exception:
            logger.exception("Unexpected polling error.")
            time.sleep(TELEGRAM_RETRY_DELAY)
    logger.info("Gold Chart Analyzer PRO V7 stopped.")


if __name__ == "__main__":
    run()
