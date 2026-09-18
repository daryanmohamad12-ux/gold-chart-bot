# ============================================================
# GOLD CHART ANALYZER PRO - SNRZ
# Clean / deploy-ready version
# ============================================================

import os
import json
import time
import logging
import requests
import base64
import re
import secrets
import math
from google import genai

# ============================================================
# CONFIG
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()

# Default fallback chain:
# 3.8 -> 3.7 -> 3.6
# You can override it with GEMINI_FALLBACK_MODELS in GitHub Secrets/Variables.
_DEFAULT_FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.6-flash"]
_env_fallback = [
    x.strip() for x in os.getenv("GEMINI_FALLBACK_MODELS", "").split(",") if x.strip()
]
GEMINI_FALLBACK_MODELS = _env_fallback or _DEFAULT_FALLBACK_MODELS
GEMINI_MAX_RETRIES = max(1, int(os.getenv("GEMINI_MAX_RETRIES", "2")))
GEMINI_BASE_RETRY_DELAY = max(5, int(os.getenv("GEMINI_BASE_RETRY_DELAY", "25")))
MAX_IMAGE_BYTES = 10 * 1024 * 1024

ADMIN_USER_ID = 5874840448
ACCESS_FILE = "allowed_users.json"    try:
        raw = gemini_request(user_prompt, zone_b64, confirmation_b64)
        result = json.loads(clean_json(raw))

        if locked_setup:
            locked_zone = str(locked_setup.get("zone", "")).strip()
            locked_zone_price = str(locked_setup.get("zone_price", "")).strip()
            locked_vs = str(locked_setup.get("vs_detected", "")).strip()
            locked_vr = str(locked_setup.get("vr_detected", "")).strip()
            locked_htf = str(locked_setup.get("htf_zones", "")).strip()

            if locked_zone and locked_zone.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                result["zone"] = locked_zone

        if locked_zone_price and locked_zone_price.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                result["zone_price"] = locked_zone_price

            if locked_vs and locked_vs.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                result["vs_detected"] = locked_vs

            if locked_vr and locked_vr.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                result["vr_detected"] = locked_vr

            if locked_htf and locked_htf.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                result["htf_zones"] = locked_htf

            logger.info(
                "LOCKED SETUP ENFORCED | Zone=%s | Zone Price=%s | VS=%s | VR=%s",
                result.get("zone"),
                result.get("zone_price"),
                result.get("vs_detected"),
                result.get("vr_detected"),
            )

MIN_STRONG_SCORE = 80
MIN_STRONG_CONFIDENCE = 80
MIN_RR = 2.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("GoldChartAnalyzer")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing.")

# ============================================================
# ACCESS DATABASE
# ============================================================
def load_allowed_users():
    users = {ADMIN_USER_ID}
    if not os.path.exists(ACCESS_FILE):
        return users
    try:
        with open(ACCESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for value in data if isinstance(data, list) else []:
            try:
                users.add(int(value))
            except (ValueError, TypeError):
                pass
    except Exception:
        logger.exception("Could not load allowed users.")
    return users


ALLOWED_USER_IDS = load_allowed_users()
PENDING_ACCESS_REQUESTS = {}
ACCESS_CODES = {}
USER_SESSIONS = {}


def save_allowed_users():
    try:
        with open(ACCESS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(ALLOWED_USER_IDS), f, indent=2, ensure_ascii=False)
    except Exception:
        logger.exception("Could not save allowed users.")


# ============================================================
# TELEGRAM
# ============================================================
class TelegramAPIError(Exception):
    pass


class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"

    def call(self, method, data=None, timeout=60):
        try:
            r = requests.post(
                f"{self.base_url}/{method}",
                json=data or {},
                timeout=timeout,
            )
            r.raise_for_status()
            result = r.json()
            if not result.get("ok"):
                raise TelegramAPIError(result.get("description", "Telegram API error"))
            return result.get("result")
        except requests.RequestException as exc:
            raise TelegramAPIError(f"Telegram request failed: {exc}") from exc

    def get_me(self):
        return self.call("getMe")

    def delete_webhook(self):
        return self.call("deleteWebhook", {"drop_pending_updates": False})

    def get_updates(self, offset=None, timeout=30):
        data = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            data["offset"] = offset
        return self.call("getUpdates", data, timeout=timeout + 15)

    def send_message(self, chat_id, text):
        text = str(text)
        if len(text) <= 4000:
            return self.call("sendMessage", {"chat_id": chat_id, "text": text})
        results = []
        for i in range(0, len(text), 4000):
            results.append(self.call("sendMessage", {
                "chat_id": chat_id,
                "text": text[i:i + 4000],
            }))
        return results

    def answer_callback_query(self, callback_query_id, text=None):
        data = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text
        return self.call("answerCallbackQuery", data)

    def get_file(self, file_id):
        return self.call("getFile", {"file_id": file_id})

    def download_file(self, file_path):
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        return r.content


telegram = TelegramBot(TELEGRAM_BOT_TOKEN)
gemini = genai.Client(api_key=GEMINI_API_KEY)

# ============================================================
# SNRZ PROMPT
# ============================================================
SYSTEM_PROMPT = r"""
You are an ELITE XAUUSD SNRZ STRUCTURE ANALYST.
Analyze ONLY the supplied chart images. Never invent prices or structures.
Return ONLY valid JSON with the exact keys requested below.
All explanatory text must be Sorani Kurdish. Technical names remain English.

IMAGE 1 = H1/H4 (HTF). It identifies VS, VR, zones and major structure.
IMAGE 2 = M1/M5 (LTF). It provides confirmation only.

STRICT VS:
Support -> UP -> NEW Resistance created AFTER that Support -> UP again -> break the SAME new Resistance/body acceptance.
Only then the original Support is VS. Any Resistance before the Support is irrelevant.

STRICT VR:
Resistance -> DOWN -> NEW Support created AFTER that Resistance -> DOWN again -> break the SAME new Support/body acceptance.
Only then the original Resistance is VR. Any Support before the Resistance is irrelevant.

ZONE:
After a valid VS/VR, compare the BODY SIZE of the VS/VR formation candle and the candle immediately before it. The SHORTER BODY wins. The complete selected candle HIGH-to-LOW is the zone. Do not use engulfing rules.

SEQUENCE:
VALID VS/VR -> ZONE -> PRICE RETURNS/RETESTS ZONE -> M1/M5 CONFIRMATION -> STRONG CHECKS -> ENTRY.
Never use a confirmation that happened before the pullback/retest.

BUY confirmation: RBS / SRR / I.VR / COMPLETE PO2.
SELL confirmation: SBR / RSS / I.VS / COMPLETE PO2.

Strong BUY/SELL requires:
- proven VS/VR
- price at/retesting the correct zone
- valid confirmation AFTER retest
- HTF/LTF agreement
- logical Entry/SL/TP
- RR >= 1:2
- Score >= 80
- Confidence >= 80
- no rejection condition

WAIT when structure, zone, retest, confirmation, direction, entry, SL, TP or RR is unclear.
If WAIT, explain exactly what must happen next. If a valid zone exists, ALWAYS include its exact zone_price.
Do not invent prices.

Output exact JSON keys:
{
 "signal":"BUY | SELL | WAIT",
 "symbol":"XAUUSD",
 "setup":"...",
 "entry":"...",
 "sl":"...",
 "tp1":"...",
 "tp2":"...",
 "tp3":"...",
 "rr":"...",
 "confidence":0,
 "score":0,
 "zone":"...",
 "zone_price":"...",
 "htf_zones":"...",
 "vs_detected":"...",
 "vr_detected":"...",
 "confirmation":"...",
 "trend":"...",
 "reasoning":"...",
 "checks":"...",
 "rejection_reason":"...",
 "wait_for":"..."
}

For WAIT, entry/sl/tp1/tp2/tp3/rr must be N/A.
"""

# ============================================================
# HELPERS
# ============================================================
def clean_json(text):
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    text = str(text).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("Gemini did not return valid JSON.")
    return text[start:end + 1]


def safe_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else None


def calculate_rr(data):
    signal = str(data.get("signal", "WAIT")).upper()
    entry, sl, tp1 = map(safe_float, [data.get("entry"), data.get("sl"), data.get("tp1")])
    if None in (entry, sl, tp1):
        return None
    if signal == "BUY":
        risk, reward = entry - sl, tp1 - entry
    elif signal == "SELL":
        risk, reward = sl - entry, entry - tp1
    else:
        return None
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def confirmation_is_valid(signal, confirmation):
    c = str(confirmation).upper()
    if signal == "BUY":
        return any(x in c for x in ("RBS", "SRR", "I.VR", "PO2"))
    if signal == "SELL":
        return any(x in c for x in ("SBR", "RSS", "I.VS", "PO2"))
    return False


def _positive_structure_text(value):
    text = str(value or "").strip().upper()

    negative_words = (
        "NO ",
        "NONE",
        "N/A",
        "NOT ",
        "INVALID",
        "UNCONFIRMED",
        "UNCLEAR",
        "UNKNOWN",
        "NEVER",
        "FALSE",
    )

    if not text:
        return False

    for word in negative_words:
        if word in text:
            return False

    return True


def validate_vs_vr(data, signal):
    signal = str(signal or "WAIT").upper()

    vs = str(data.get("vs_detected", "") or "")
    vr = str(data.get("vr_detected", "") or "")
    zones = str(data.get("htf_zones", "") or "")
    zone = str(data.get("zone", "") or "")

    if signal == "BUY":
        return (
            ("VS" in vs.upper() and _positive_structure_text(vs))
            or
            ("VS" in zones.upper() and _positive_structure_text(zones))
            or
            ("VS" in zone.upper() and _positive_structure_text(zone))
        )

    if signal == "SELL":
        return (
            ("VR" in vr.upper() and _positive_structure_text(vr))
            or
            ("VR" in zones.upper() and _positive_structure_text(zones))
            or
            ("VR" in zone.upper() and _positive_structure_text(zone))
        )

    return False


def strong_signal_engine(data):
    if not isinstance(data, dict):
        data = {}

    # Normalize required fields.
    defaults = {
        "signal": "WAIT", "symbol": "XAUUSD", "setup": "N/A",
        "entry": "N/A", "sl": "N/A", "tp1": "N/A", "tp2": "N/A", "tp3": "N/A",
        "rr": "N/A", "confidence": 0, "score": 0, "zone": "N/A",
        "zone_price": "N/A", "htf_zones": "N/A", "vs_detected": "N/A",
        "vr_detected": "N/A", "confirmation": "N/A", "trend": "N/A",
        "reasoning": "N/A", "checks": "N/A", "rejection_reason": "", "wait_for": "",
    }
    for key, value in defaults.items():
        data.setdefault(key, value)

    signal = str(data.get("signal", "WAIT")).upper().strip()
    if signal not in {"BUY", "SELL", "WAIT"}:
        signal = "WAIT"
        data["signal"] = signal

    score = safe_float(data.get("score")) or 0
    confidence = safe_float(data.get("confidence")) or 0
    data["score"] = round(score, 2)
    data["confidence"] = round(confidence, 2)

    reasons = []
    if signal == "WAIT":
        reasons.append("AI setup ـێکی بەهێزی SNRZ پشتڕاست نەکردووەتەوە.")
    if score < MIN_STRONG_SCORE:
        reasons.append(f"Score = {score:.0f}/100 ـە؛ پێویستە کەمترین {MIN_STRONG_SCORE}/100 بێت.")
    if confidence < MIN_STRONG_CONFIDENCE:
        reasons.append(f"Confidence = {confidence:.0f}% ـە؛ پێویستە کەمترین {MIN_STRONG_CONFIDENCE}% بێت.")

    if signal in {"BUY", "SELL"}:
        if not validate_vs_vr(data, signal):
            reasons.append("VS/VR ـی HTF بە شێوەیەکی ڕوون پشتڕاست نەکراوەتەوە.")
        if not confirmation_is_valid(signal, data.get("confirmation", "")):
            reasons.append("Confirmation ـی دروستی SNRZ نییە.")

    zone = str(data.get("zone", "")).strip()
    zone_price = str(data.get("zone_price", "N/A")).strip() or "N/A"
    if not zone or zone.upper() in {"N/A", "NONE", "UNKNOWN"}:
        reasons.append("Zone ـێکی ڕوونی HTF نییە.")

    if signal in {"BUY", "SELL"}:
        for field, label in (("entry", "Entry"), ("sl", "SL"), ("tp1", "TP1")):
            if str(data.get(field, "N/A")).upper() == "N/A":
                reasons.append(f"{label} دیاری نەکراوە.")
        rr = calculate_rr(data)
        if rr is None:
            reasons.append("RR بە شێوەیەکی دروست حساب ناکرێت.")
        elif rr < MIN_RR:
            reasons.append(f"RR = 1:{rr:.2f} ـە؛ کەمترە لە 1:2.")
    else:
        rr = None

    if reasons:
        data.update({"signal": "WAIT", "entry": "N/A", "sl": "N/A", "tp1": "N/A", "tp2": "N/A", "tp3": "N/A", "rr": "N/A"})
        existing = str(data.get("rejection_reason", "")).strip()
        combined = " ".join(x for x in ([existing] if existing else []) + reasons)
        if zone_price.upper() not in {"N/A", "NONE", "UNKNOWN", ""}:
            combined = f"📍 Zone Price: {zone_price}\n{combined}"
            if not str(data.get("wait_for", "")).strip():
                data["wait_for"] = f"چاوەڕێ بکە نرخ بگەڕێتەوە بۆ Zone ـی {zone_price}."
            elif zone_price not in str(data["wait_for"]):
                data["wait_for"] += f"\n📍 Zone Price: {zone_price}"
        data["rejection_reason"] = combined or "setup ـێکی بەهێز نەدۆزرایەوە."
        if not str(data.get("wait_for", "")).strip():
            data["wait_for"] = "چاوەڕێی structure ـێکی تەواوی SNRZ و confirmation ـی ڕوون بکە."
        return data

    data["signal"] = signal
    data["rr"] = f"1:{rr:.2f}" if rr is not None else str(data.get("rr", "N/A"))
    data["rejection_reason"] = "هیچ rejection filter ـێک نەشکا."
    data["wait_for"] = "N/A"
    return data

# ============================================================
# GEMINI RETRY / FALLBACK
# ============================================================
def extract_retry_seconds(exc):
    text = str(exc)
    match = re.search(r"retry in\s*([0-9.]+)s", text, re.I)
    if match:
        try:
            return max(5, min(120, math.ceil(float(match.group(1))) + 1))
        except ValueError:
            pass
    return None


def is_retryable_gemini_error(exc):
    text = str(exc).lower()
    return any(x in text for x in ("429", "too many requests", "quota", "rate limit", "resource exhausted", "temporarily unavailable"))


def gemini_request(user_prompt, zone_b64, confirmation_b64):
    models = []
    for model in [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS:
        if model and model not in models:
            models.append(model)

    if not models:
        raise RuntimeError("No Gemini model configured.")

    last_error = None
    for model_index, model in enumerate(models):
        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            try:
                logger.info("Gemini request: model=%s attempt=%s/%s", model, attempt, GEMINI_MAX_RETRIES)
                interaction = gemini.interactions.create(
                    model=model,
                    system_instruction=SYSTEM_PROMPT,
                    input=[
                        {"type": "text", "text": user_prompt},
                        {"type": "image", "data": zone_b64, "mime_type": "image/jpeg"},
                        {"type": "image", "data": confirmation_b64, "mime_type": "image/jpeg"},
                    ],
                    generation_config={"thinking_level": "medium"},
                )
                text = getattr(interaction, "output_text", None)
                if not text:
                    raise RuntimeError("Gemini returned an empty output_text.")
                logger.info("Gemini success: model=%s", model)
                return text
            except Exception as exc:
                last_error = exc
                logger.error("Gemini error: model=%s attempt=%s: %s", model, attempt, exc)
                if not is_retryable_gemini_error(exc):
                    break

                # A quota/rate-limit error is usually model-specific.
                # Do NOT waste all retries on the same model; move to the
                # next fallback model first.
                if "429" in str(exc) or "quota" in str(exc).lower() or "too many requests" in str(exc).lower():
                    logger.warning("Quota/rate limit on %s. Switching to next model.", model)
                    break

                if attempt < GEMINI_MAX_RETRIES:
                    suggested = extract_retry_seconds(exc)
                    delay = suggested if suggested is not None else GEMINI_BASE_RETRY_DELAY * (2 ** (attempt - 1))
                    delay = min(delay, 120)
                    logger.info("Retrying Gemini in %ss...", delay)
                    time.sleep(delay)
        if model_index < len(models) - 1:
            logger.warning("Trying Gemini fallback model: %s", models[model_index + 1])

    raise RuntimeError(f"Gemini API failed after retries/fallback: {last_error}")

# ============================================================
# ANALYSIS
# ============================================================
def analyze_two_charts(zone_image, confirmation_image, locked_setup=None):
    if len(zone_image) > MAX_IMAGE_BYTES or len(confirmation_image) > MAX_IMAGE_BYTES:
        raise RuntimeError("وێنەکە لە 10MB زیاترە.")

    zone_b64 = base64.b64encode(zone_image).decode("utf-8")
    confirmation_b64 = base64.b64encode(confirmation_image).decode("utf-8")

    user_prompt = """
    VERY IMPORTANT VS/VR DETECTION RULE:

Do NOT say "no VS/VR" merely because the chart contains multiple structures.

You must scan the ENTIRE H1/H4 chart from left to right and identify EVERY candidate structure.

A chart may contain:
- multiple VS candidates
- multiple VR candidates
- both VS and VR on the same chart

For each candidate, check the COMPLETE sequence.

VALID VS:
1. Support exists.
2. Price moves UP from that Support.
3. A NEW Resistance is created AFTER that Support.
4. Price moves UP again.
5. The SAME NEW Resistance is broken with body acceptance.
Only then mark that Support as VALID VS.

VALID VR:
1. Resistance exists.
2. Price moves DOWN from that Resistance.
3. A NEW Support is created AFTER that Resistance.
4. Price moves DOWN again.
5. The SAME NEW Support is broken with body acceptance.
Only then mark that Resistance as VALID VR.

A previous Resistance before the Support MUST NOT invalidate a VS.
A previous Support before the Resistance MUST NOT invalidate a VR.

If there are 2 VS and 1 VR candidates, inspect all 3 independently.
Do NOT return "no VS/VR" unless every candidate fails the complete sequence.

For each detected structure, state:
- type
- original zone
- formation sequence
- break confirmation
- validity

Only after identifying valid VS/VR, determine the Zone.
Analyze both XAUUSD chart images.
IMAGE 1 = H1/H4. IMAGE 2 = M1/M5.

FIRST scan HTF and prove VS/VR using the strict structures.
VS = Support -> UP -> NEW Resistance after Support -> UP -> break same Resistance.
VR = Resistance -> DOWN -> NEW Support after Resistance -> DOWN -> break same Support.

Then determine Zone from the confirmed VS/VR candle versus the immediately previous candle:
shorter BODY wins; entire selected candle HIGH-to-LOW is the Zone.

Then follow ONLY:
VALID VS/VR -> ZONE -> PULLBACK/RETEST -> M1/M5 CONFIRMATION -> STRONG CHECK -> ENTRY.

BUY = RBS / SRR / I.VR / complete PO2.
SELL = SBR / RSS / I.VS / complete PO2.

Strong requires Score >= 80, Confidence >= 80, RR >= 1:2, valid zone, retest, valid confirmation after retest, HTF/LTF agreement and logical Entry/SL/TP.
Otherwise WAIT.
Never invent prices.
If a valid zone exists, give its exact zone_price. If waiting for the zone, include the zone price in wait_for.
Return ONLY JSON.
"""

    if locked_setup:
        user_prompt += "\nLOCKED SETUP — preserve the same VS/VR and SAME Zone. Do not replace it with a new nearby zone:\n"
        user_prompt += json.dumps(locked_setup, ensure_ascii=False, indent=2)

        try:
        raw = gemini_request(user_prompt, zone_b64, confirmation_b64)
        result = json.loads(clean_json(raw))

        if locked_setup:
            locked_zone = str(locked_setup.get("zone", "")).strip()
            locked_zone_price = str(locked_setup.get("zone_price", "")).strip()
            locked_vs = str(locked_setup.get("vs_detected", "")).strip()
            locked_vr = str(locked_setup.get("vr_detected", "")).strip()
            locked_htf = str(locked_setup.get("htf_zones", "")).strip()

            if locked_zone and locked_zone.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                result["zone"] = locked_zone

            if locked_zone_price and locked_zone_price.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                result["zone_price"] = locked_zone_price

            if locked_vs and locked_vs.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                result["vs_detected"] = locked_vs

            if locked_vr and locked_vr.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                result["vr_detected"] = locked_vr

            if locked_htf and locked_htf.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                result["htf_zones"] = locked_htf

            logger.info(
                "LOCKED SETUP ENFORCED | Zone=%s | Zone Price=%s | VS=%s | VR=%s",
                result.get("zone"),
                result.get("zone_price"),
                result.get("vs_detected"),
                result.get("vr_detected"),
            )
# ============================================================
# HARD LOCK: never allow Gemini to replace a locked setup
# ============================================================
if locked_setup:
    locked_zone = str(locked_setup.get("zone", "")).strip()
    locked_zone_price = str(locked_setup.get("zone_price", "")).strip()
    locked_vs = str(locked_setup.get("vs_detected", "")).strip()
    locked_vr = str(locked_setup.get("vr_detected", "")).strip()
    locked_htf = str(locked_setup.get("htf_zones", "")).strip()

    if locked_zone and locked_zone.upper() not in {"N/A", "NONE", "UNKNOWN"}:
        result["zone"] = locked_zone

    if locked_zone_price and locked_zone_price.upper() not in {"N/A", "NONE", "UNKNOWN"}:
        result["zone_price"] = locked_zone_price

    if locked_vs and locked_vs.upper() not in {"N/A", "NONE", "UNKNOWN"}:
        result["vs_detected"] = locked_vs

    if locked_vr and locked_vr.upper() not in {"N/A", "NONE", "UNKNOWN"}:
        result["vr_detected"] = locked_vr

    if locked_htf and locked_htf.upper() not in {"N/A", "NONE", "UNKNOWN"}:
        result["htf_zones"] = locked_htf

    logger.info(
        "🔒 LOCKED SETUP ENFORCED | Zone=%s | Zone Price=%s | VS=%s | VR=%s",
        result.get("zone"),
        result.get("zone_price"),
        result.get("vs_detected"),
        result.get("vr_detected"),
    )
    
        return strong_signal_engine(result)
    except json.JSONDecodeError as exc:
        logger.exception("Invalid JSON returned by Gemini.")
        raise RuntimeError("AI وەڵامی JSON ـی دروستی نەدا.") from exc
    except Exception as exc:
        logger.exception("Gemini analysis failed.")
        raise RuntimeError(str(exc)) from exc

# ============================================================
# ACCESS
# ============================================================
def is_admin(user_id):
    return user_id == ADMIN_USER_ID


def is_allowed(user_id):
    return user_id in ALLOWED_USER_IDS


def generate_access_code():
    while True:
        code = f"GC-{secrets.token_hex(3).upper()}-{secrets.token_hex(2).upper()}"
        if code not in ACCESS_CODES:
            return code


def send_access_request(message, chat_id, user_id):
    if is_allowed(user_id):
        return False
    if user_id in PENDING_ACCESS_REQUESTS:
        request = PENDING_ACCESS_REQUESTS[user_id]
        telegram.send_message(chat_id, f"⏳ داواکارییەکەت پێشتر نێردراوە.\n\n🔑 Access Code: {request['code']}\n🆔 Telegram ID: {user_id}\n\nتکایە چاوەڕێی Admin بکە.")
        return True

    user = message.get("from", {})
    code = generate_access_code()
    PENDING_ACCESS_REQUESTS[user_id] = {
        "user_id": user_id,
        "chat_id": chat_id,
        "code": code,
        "first_name": user.get("first_name", "Unknown"),
        "last_name": user.get("last_name", ""),
        "username": user.get("username", ""),
    }
    ACCESS_CODES[code] = user_id

    telegram.send_message(chat_id, f"⏳ داواکاریی دەستڕاگەیشتنت نێردرا بۆ Admin.\n\n🔑 Access Code: {code}\n🆔 Telegram ID: {user_id}\n\n👑 Admin پێویستە ڕێگەپێدانت پێبدات.")

    name = f"{user.get('first_name', 'Unknown')} {user.get('last_name', '')}".strip()
    username = f"@{user.get('username')}" if user.get("username") else "N/A"
    keyboard = {"inline_keyboard": [[
        {"text": "✅ APPROVE", "callback_data": f"approve:{code}"},
        {"text": "❌ REJECT", "callback_data": f"reject:{code}"},
    ]]}
    telegram.call("sendMessage", {
        "chat_id": ADMIN_USER_ID,
        "text": f"🆕 NEW ACCESS REQUEST\n━━━━━━━━━━━━━━━━━━\n👤 Name: {name}\n🔗 Username: {username}\n🆔 User ID: {user_id}\n🔑 Access Code: {code}\n━━━━━━━━━━━━━━━━━━",
        "reply_markup": keyboard,
    })
    return True


def handle_access_callback(callback):
    callback_id = callback.get("id")
    admin_id = callback.get("from", {}).get("id")
    data = callback.get("data", "")
    if admin_id != ADMIN_USER_ID:
        telegram.answer_callback_query(callback_id, "⛔ تەنها Admin دەتوانێت ئەم کارە بکات.")
        return
    if ":" not in data:
        telegram.answer_callback_query(callback_id, "❌ Request ـەکە نادروستە.")
        return

    action, code = data.split(":", 1)
    user_id = ACCESS_CODES.get(code)
    request = PENDING_ACCESS_REQUESTS.get(user_id) if user_id else None
    if not user_id or not request:
        telegram.answer_callback_query(callback_id, "⚠️ ئەم داواکارییە پێشتر مامەڵەی لەگەڵ کراوە.")
        return

    if action == "approve":
        ALLOWED_USER_IDS.add(user_id)
        save_allowed_users()
        telegram.answer_callback_query(callback_id, "✅ User approved.")
        telegram.send_message(user_id, "✅ ڕێگەپێدراویت!\n\n🥇 Gold Chart Analyzer PRO\n🧠 SNRZ Structure Engine چالاکە.\n\n📸 H1 یان H4 ـی XAUUSD بنێرە.")
    elif action == "reject":
        telegram.answer_callback_query(callback_id, "❌ User rejected.")
        telegram.send_message(user_id, "❌ داواکارییەکەت ڕەتکرایەوە.")
    else:
        telegram.answer_callback_query(callback_id, "❌ Action نادروستە.")
        return

    PENDING_ACCESS_REQUESTS.pop(user_id, None)
    ACCESS_CODES.pop(code, None)

# ============================================================
# ADMIN COMMANDS
# ============================================================
def handle_admin_command(message, chat_id, text):
    user_id = message.get("from", {}).get("id")
    if not is_admin(user_id):
        return False

    if text.startswith("/adduser"):
        parts = text.split()
        if len(parts) != 2:
            telegram.send_message(chat_id, "❌ /adduser USER_ID")
            return True
        try:
            uid = int(parts[1])
        except ValueError:
            telegram.send_message(chat_id, "❌ User ID دەبێت ژمارە بێت.")
            return True
        ALLOWED_USER_IDS.add(uid)
        save_allowed_users()
        telegram.send_message(chat_id, f"✅ بەکارهێنەر زیادکرا.\n👤 User ID: {uid}")
        return True

    if text.startswith("/removeuser"):
        parts = text.split()
        if len(parts) != 2:
            telegram.send_message(chat_id, "❌ /removeuser USER_ID")
            return True
        try:
            uid = int(parts[1])
        except ValueError:
            telegram.send_message(chat_id, "❌ User ID دەبێت ژمارە بێت.")
            return True
        if uid == ADMIN_USER_ID:
            telegram.send_message(chat_id, "⛔ ناتوانیت Admin بسڕیتەوە.")
            return True
        if uid in ALLOWED_USER_IDS:
            ALLOWED_USER_IDS.remove(uid)
            save_allowed_users()
            telegram.send_message(chat_id, f"✅ بەکارهێنەر سڕایەوە.\n👤 User ID: {uid}")
        else:
            telegram.send_message(chat_id, "ℹ️ ئەم User ID ـە لە لیستدا نییە.")
        return True

    if text == "/users":
        lines = [f"👑 {uid} — ADMIN" if uid == ADMIN_USER_ID else f"👤 {uid}" for uid in sorted(ALLOWED_USER_IDS)]
        telegram.send_message(chat_id, "👥 ALLOWED USERS\n━━━━━━━━━━━━━━\n" + "\n".join(lines) + f"\n\nTotal: {len(lines)}")
        return True

    if text == "/pending":
        if not PENDING_ACCESS_REQUESTS:
            telegram.send_message(chat_id, "📭 هیچ Access Request ـێکی چاوەڕوان نییە.")
            return True
        lines = []
        for uid, req in PENDING_ACCESS_REQUESTS.items():
            username = f"@{req['username']}" if req.get("username") else "N/A"
            lines.append(f"👤 {req.get('first_name', 'Unknown')} | {username} | 🆔 {uid} | 🔑 {req.get('code')}")
        telegram.send_message(chat_id, "⏳ PENDING REQUESTS\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines))
        return True

    if text == "/admin":
        telegram.send_message(chat_id, "👑 ADMIN PANEL\n━━━━━━━━━━━━━━━━━━\n/adduser USER_ID\n/removeuser USER_ID\n/users\n/pending\n/broadcast MESSAGE")
        return True

    if text.startswith("/broadcast"):
        msg = text[len("/broadcast"):].strip()
        if not msg:
            telegram.send_message(chat_id, "❌ /broadcast YOUR MESSAGE")
            return True
        success = failed = 0
        for uid in list(ALLOWED_USER_IDS):
            try:
                telegram.send_message(uid, msg)
                success += 1
            except Exception:
                failed += 1
                logger.exception("Broadcast failed for %s", uid)
        telegram.send_message(chat_id, f"📢 Broadcast تەواوبوو.\n✅ {success}\n❌ {failed}")
        return True

    return False

# ============================================================
# OUTPUT
# ============================================================
def format_signal(data):
    signal = str(data.get("signal", "WAIT")).upper()
    title = "🟢 STRONG BUY SIGNAL" if signal == "BUY" else "🔴 STRONG SELL SIGNAL" if signal == "SELL" else "🟡 WAIT"
    text = f"""{title}
━━━━━━━━━━━━━━
🥇 XAUUSD

📊 Score: {data.get('score', 0)}/100
💪 Confidence: {data.get('confidence', 0)}%
📈 Trend: {data.get('trend', 'N/A')}
🧠 Setup: {data.get('setup', 'N/A')}
🟦 Zone: {data.get('zone', 'N/A')}
📍 Zone Price: {data.get('zone_price', 'N/A')}
🔎 HTF Zones: {data.get('htf_zones', 'N/A')}
🟢 VS: {data.get('vs_detected', 'N/A')}
🔴 VR: {data.get('vr_detected', 'N/A')}
🔎 Confirmation: {data.get('confirmation', 'N/A')}
"""
    if signal in {"BUY", "SELL"}:
        text += f"""
━━━━━━━━━━━━━━
🎯 Entry: {data.get('entry', 'N/A')}
🛑 SL: {data.get('sl', 'N/A')}
🥇 TP1: {data.get('tp1', 'N/A')}
🥈 TP2: {data.get('tp2', 'N/A')}
🥉 TP3: {data.get('tp3', 'N/A')}
📊 R:R: {data.get('rr', 'N/A')}
"""
    text += f"""
━━━━━━━━━━━━━━
🔎 هۆکار: {data.get('reasoning', 'N/A')}
✅ Checks: {data.get('checks', 'N/A')}
"""
    if signal == "WAIT":
        text += f"""
━━━━━━━━━━━━━━
🚫 هۆکاری WAIT: {data.get('rejection_reason', 'setup ـێکی بەهێز نەدۆزرایەوە.')}

👀 چاوەڕێی چی بکەین؟
{data.get('wait_for', 'چاوەڕێی structure ـێکی تەواوی SNRZ بکە.')}
"""
    else:
        text += "\n━━━━━━━━━━━━━━\n🟢 STRONG SNRZ setup هەموو filter ـە سەرەکییەکان تێپەڕاند."
    return text.strip()

# ============================================================
# PHOTO / MESSAGE
# ============================================================
def download_telegram_photo(message):
    photos = message.get("photo")
    if not photos:
        return None
    file_id = photos[-1].get("file_id")
    if not file_id:
        return None
    info = telegram.get_file(file_id)
    file_path = info.get("file_path")
    if not file_path:
        return None
    data = telegram.download_file(file_path)
    if len(data) > MAX_IMAGE_BYTES:
        raise RuntimeError("وێنەکە لە 10MB زیاترە. تکایە screenshot ـێکی کەمتر لە 10MB بنێرە.")
    return data


def handle_message(message):
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    if not chat_id or not user_id:
        return
    text = str(message.get("text", "")).strip()

    if is_admin(user_id) and handle_admin_command(message, chat_id, text):
        return

    if not is_allowed(user_id):
        if text == "/start":
            send_access_request(message, chat_id, user_id)
        else:
            telegram.send_message(chat_id, "⛔ دەستگەیشتن ڕەتکرایەوە.\n\nبۆ داواکاریی دەستڕاگەیشتن: /start")
        return

    if text == "/start":
        USER_SESSIONS[chat_id] = {"zone_image": None, "confirmation_image": None, "locked_setup": None}
        telegram.send_message(chat_id, """🥇 Gold Chart Analyzer PRO
🧠 SNRZ Structure Engine چالاکە.

1️⃣ H1 یان H4 بنێرە.
2️⃣ پاشان M1 یان M5 بنێرە.

سیستەم:
VS/VR → Zone → Pullback/Retest → Confirmation → Strong Check → BUY/SELL
ئەگەر مەرجەکان تەواو نەبن: 🟡 WAIT""")
        return

    if text == "/help":
        telegram.send_message(chat_id, """📚 SNRZ Structure Engine

HTF: H1/H4
LTF: M1/M5
BUY: RBS / SRR / I.VR / PO2
SELL: SBR / RSS / I.VS / PO2

VS/VR → Zone → Pullback/Retest → Confirmation → Strong Check
Score >= 80 | Confidence >= 80% | RR >= 1:2

ئەگەر مەرجەکان تەواو نەبن: 🟡 WAIT""")
        return

    if text == "/reset":
        USER_SESSIONS.pop(chat_id, None)
        telegram.send_message(chat_id, "♻️ Session reset کرا. ئێستا H1 یان H4 بنێرە.")
        return

    if "photo" not in message:
        telegram.send_message(chat_id, "تکایە H1 یان H4 ـی XAUUSD بنێرە، یان /start بنووسە.")
        return

    try:
        photo = download_telegram_photo(message)
    except Exception as exc:
        telegram.send_message(chat_id, f"❌ وێنەکە وەرنەگیرا.\nهۆکار: {exc}")
        return
    if photo is None:
        telegram.send_message(chat_id, "❌ وێنەکە نادروستە.")
        return

    session = USER_SESSIONS.setdefault(chat_id, {"zone_image": None, "confirmation_image": None, "locked_setup": None})

    if session["zone_image"] is None:
        session["zone_image"] = photo
        telegram.send_message(chat_id, "✅ H1/H4 وەرگیرا.\n🔎 ئێستا M1 یان M5 بۆ Confirmation بنێرە.")
        return

    session["confirmation_image"] = photo
    telegram.send_message(chat_id, "⏳ هەردوو chart وەرگیرا.\n🧠 SNRZ → VS/VR → Zone → Retest → Confirmation → Filters\nشیکردنەوە دەکەم...")

    try:
        result = analyze_two_charts(session["zone_image"], session["confirmation_image"], session.get("locked_setup"))
        telegram.send_message(chat_id, format_signal(result))

        if result.get("signal") == "WAIT":
            zone = str(result.get("zone", "")).strip()
            zone_price = str(result.get("zone_price", "N/A")).strip()
            if zone and zone.upper() not in {"N/A", "NONE", "UNKNOWN"} and zone_price and zone_price.upper() not in {"N/A", "NONE", "UNKNOWN"}:
                USER_SESSIONS[chat_id] = {
                    "zone_image": None,
                    "confirmation_image": None,
                    "locked_setup": {
                        "signal": "WAIT",
                        "setup": result.get("setup", ""),
                        "zone": zone,
                        "zone_price": zone_price,
                        "vs_detected": result.get("vs_detected", ""),
                        "vr_detected": result.get("vr_detected", ""),
                        "htf_zones": result.get("htf_zones", ""),
                        "wait_for": result.get("wait_for", ""),
                        "reasoning": result.get("reasoning", ""),
                    },
                }
            else:
                USER_SESSIONS.pop(chat_id, None)
        else:
            USER_SESSIONS.pop(chat_id, None)
    except Exception as exc:
        logger.exception("Analysis failed.")
        telegram.send_message(chat_id, f"❌ شیکردنەوەکە نەکرا.\n\nهۆکار: {exc}\n\nتکایە هەردوو chart ـەکە بە quality ـی باشتر دووبارە بنێرە.")
        USER_SESSIONS.pop(chat_id, None)

# ============================================================
# MAIN LOOP
# ============================================================
def run():
    logger.info("Gold Chart Analyzer PRO started.")
    logger.info("Primary Gemini model: %s", GEMINI_MODEL)
    logger.info("Fallback Gemini models: %s", GEMINI_FALLBACK_MODELS or "none")
    logger.info("Admin ID: %s", ADMIN_USER_ID)
    logger.info("Allowed users: %s", len(ALLOWED_USER_IDS))
    logger.info("Strong score/confidence/RR: %s/%s/1:%s", MIN_STRONG_SCORE, MIN_STRONG_CONFIDENCE, MIN_RR)

    me = telegram.get_me()
    logger.info("Telegram connected: @%s", me.get("username"))
    telegram.delete_webhook()
    logger.info("Telegram webhook removed.")

    offset = None
    while True:
        try:
            updates = telegram.get_updates(offset=offset, timeout=30)
            for update in updates:
                offset = update.get("update_id", 0) + 1
                callback = update.get("callback_query")
                if callback:
                    try:
                        handle_access_callback(callback)
                    except Exception:
                        logger.exception("Callback handling error.")
                    continue
                message = update.get("message")
                if message:
                    try:
                        handle_message(message)
                    except Exception:
                        logger.exception("Message handling error.")
        except TelegramAPIError as exc:
            error = str(exc)
            if "409" in error or "conflict" in error.lower():
                logger.error("Telegram 409 Conflict: another bot instance is running. Waiting 30s.")
                time.sleep(30)
            else:
                logger.error("Telegram polling error: %s", error)
                time.sleep(5)
        except Exception:
            logger.exception("Unexpected main-loop error. Retrying in 5 seconds...")
            time.sleep(5)


if __name__ == "__main__":
    run()
