"""
Intent classification + structured extraction via Gemini 2.5 Flash.
Dual-brain pattern from RADMAX: REPORT (log) vs QUERY (retrieve).
Phase 2: multimodal support — audio transcription + image analysis.
"""
import os
import json
import re
import base64
import google.generativeai as genai
from models import (
    Intent, ExtractedReport, ExtractedQuery,
    RecordType, QueryType,
)

genai.configure(api_key=os.getenv("GOOGLE_API_KEY", ""))
_model = genai.GenerativeModel("gemini-2.5-flash")

_CLASSIFY_PROMPT = """\
你是台灣托嬰中心合規紀錄助理，協助保育員快速記錄日常照護動作。
依據桃園市及台北市 114-116 年度托嬰中心評鑑基準設計。

【REPORT 範例（紀錄動作）】
嬰幼兒照護：
- 「小明剛換尿布，屁股有點紅」→ diaper_change
- 「量了小花體溫 37.2」→ temperature
- 「餵小華 150ml 配方奶」→ feeding
- 「小明睡著了」→ sleep
- 「小花換好了」（回應逾時警示）→ diaper_change
- 「小明今天量身高 72cm 體重 9.2kg」→ growth_measurement
- 「小花的寢具洗好了」→ bedding_wash
- 「給小明吃醫生開的藥，1 顆」→ medication
- 「尿布台消毒好了」→ diaper_table_clean
- 「換完尿布台已清潔」→ diaper_table_clean

環境衛生：
- 「B室玩具消毒完畢」→ decontamination
- 「廚房冷藏 4 度，冷凍 -19 度」→ fridge_temp
- 「今天午餐留了食物樣品」→ food_sample

【QUERY 範例（查詢資訊）】
- 「小明上次換尿布幾點」
- 「今天有哪些逾時」
- 「我現在該做什麼」
- 「冰箱上次幾點量的」

回覆規則：
1. 只輸出純 JSON，不要 markdown、不要說明文字。
2. 若為 REPORT，使用以下格式：
{
  "intent": "REPORT",
  "record_type": "diaper_change|temperature|feeding|sleep|health_note|medication|growth_measurement|bedding_wash|diaper_table_clean|decontamination|fridge_temp|food_sample",
  "baby_name": "嬰兒名字（環境類紀錄填 null）",
  "environment_zone": "環境區域，如 B室、廚房、地板（非環境類填 null）",
  "value": 數值（體溫°C、餵食ml、冰箱冷藏°C 用數字；無則填 null）,
  "value2": 數值（冰箱冷凍°C；體位測量時填體重kg；無則填 null）,
  "value3": 數值（體位測量時填頭圍cm；無則填 null）,
  "notes": "備註文字（無則填 null）",
  "confidence": 0.0 到 1.0
}
3. 若為 QUERY，使用以下格式：
{
  "intent": "QUERY",
  "query_type": "last_record|overdue_list|todo_list|summary",
  "record_type": "若查詢特定類型填入，否則 null",
  "baby_name": "若查詢特定嬰兒填入，否則 null"
}

訊息：「{message}」
"""


def safe_parse_json(text: str) -> dict:
    """Robustly extract JSON from Gemini output (handles markdown fences, extra text)."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown code fence
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Find first JSON object anywhere in the string
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def classify_and_extract(message: str) -> ExtractedReport | ExtractedQuery:
    """Main entry point: classify intent and extract structured data."""
    prompt = _CLASSIFY_PROMPT.replace("{message}", message)
    response = _model.generate_content(prompt)
    parsed = safe_parse_json(response.text)

    intent_str = parsed.get("intent", "UNKNOWN")

    if intent_str == "REPORT":
        try:
            record_type = RecordType(parsed.get("record_type", ""))
        except ValueError:
            record_type = None

        return ExtractedReport(
            intent=Intent.REPORT,
            record_type=record_type,
            baby_name=parsed.get("baby_name"),
            environment_zone=parsed.get("environment_zone"),
            value=parsed.get("value"),
            value2=parsed.get("value2"),
            value3=parsed.get("value3"),
            notes=parsed.get("notes"),
            confidence=float(parsed.get("confidence", 0.8)),
        )

    if intent_str == "QUERY":
        try:
            query_type = QueryType(parsed.get("query_type", "summary"))
        except ValueError:
            query_type = QueryType.SUMMARY
        try:
            record_type = RecordType(parsed["record_type"]) if parsed.get("record_type") else None
        except ValueError:
            record_type = None

        return ExtractedQuery(
            intent=Intent.QUERY,
            query_type=query_type,
            record_type=record_type,
            baby_name=parsed.get("baby_name"),
        )

    # Fallback
    return ExtractedQuery(intent=Intent.UNKNOWN, query_type=QueryType.SUMMARY)


# ── Phase 2: Multimodal ────────────────────────────────────────────────────────

_TRANSCRIBE_PROMPT = """\
轉錄任務：請將音頻中說的話逐字轉錄為繁體中文。
規則：只輸出說話者說的文字內容，不加任何說明、標點修飾或額外文字。
"""

_IMAGE_PROMPT = """\
你是台灣托嬰中心合規紀錄助理。
請分析這張照片，辨識它代表哪種托嬰紀錄，並提取相關資料。

照片可能是：
- 體溫計顯示（→ temperature，讀取°C數值）
- 冰箱溫度顯示（→ fridge_temp，讀取冷藏和/或冷凍°C）
- 藥品標籤或藥袋（→ medication，讀取藥名、劑量）
- 寶寶皮膚狀況（→ health_note，描述狀況）
- 環境消毒後（→ decontamination，辨識區域）
- 尿布台（→ diaper_table_clean）
- 食物樣品（→ food_sample）

回覆規則：
1. 只輸出純 JSON，不要 markdown、不要說明文字。
2. 使用與文字分類相同的格式：
{
  "intent": "REPORT",
  "record_type": "temperature|fridge_temp|medication|health_note|decontamination|diaper_table_clean|food_sample|...",
  "baby_name": null,
  "environment_zone": "若為環境類填入區域，否則 null",
  "value": 數值（體溫°C 或 冷藏°C；無則 null）,
  "value2": 數值（冷凍°C；無則 null）,
  "value3": null,
  "notes": "照片中可見的補充資訊（藥名、皮膚描述等）",
  "confidence": 0.0 到 1.0
}
3. 若無法辨識，回傳 {"intent": "UNKNOWN"}
"""


def transcribe_and_route(audio_bytes: bytes) -> "ExtractedReport | ExtractedQuery":
    """
    Phase 2: Audio pipeline.
    1. Send audio bytes to Gemini → get Mandarin transcript text.
    2. Feed transcript through the standard classify_and_extract().
    """
    b64 = base64.b64encode(audio_bytes).decode("utf-8")
    response = _model.generate_content([
        {"inline_data": {"mime_type": "audio/mp4", "data": b64}},
        _TRANSCRIBE_PROMPT,
    ])
    transcript = response.text.strip()
    if not transcript:
        return ExtractedQuery(intent=Intent.UNKNOWN, query_type=QueryType.SUMMARY)

    # Strip prompt leakage: Gemini sometimes echoes system prompt text into the transcript.
    # Keep only the text BEFORE any known prompt phrase appears.
    _PROMPT_LEAK_MARKERS = [
        "你是台灣托嬰中心",
        "語音助理",
        "請將以下音頻",
        "只輸出轉錄文字",
    ]
    for marker in _PROMPT_LEAK_MARKERS:
        idx = transcript.find(marker)
        if idx > 0:
            transcript = transcript[:idx].strip()
        elif idx == 0:
            # Entire output is prompt text — discard
            transcript = ""
            break

    if not transcript:
        return ExtractedQuery(intent=Intent.UNKNOWN, query_type=QueryType.SUMMARY)

    return classify_and_extract(transcript)


def classify_image(image_bytes: bytes) -> "ExtractedReport | ExtractedQuery":
    """
    Phase 2: Image pipeline.
    Send image bytes directly to Gemini vision → structured JSON → parsed result.
    Handles: thermometer, fridge display, medication label, baby skin, environment photos.
    """
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    response = _model.generate_content([
        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
        _IMAGE_PROMPT,
    ])
    parsed = safe_parse_json(response.text)

    intent_str = parsed.get("intent", "UNKNOWN")
    if intent_str != "REPORT":
        return ExtractedQuery(intent=Intent.UNKNOWN, query_type=QueryType.SUMMARY)

    try:
        record_type = RecordType(parsed.get("record_type", ""))
    except ValueError:
        record_type = None

    return ExtractedReport(
        intent=Intent.REPORT,
        record_type=record_type,
        baby_name=parsed.get("baby_name"),
        environment_zone=parsed.get("environment_zone"),
        value=parsed.get("value"),
        value2=parsed.get("value2"),
        value3=parsed.get("value3"),
        notes=parsed.get("notes"),
        confidence=float(parsed.get("confidence", 0.7)),
    )
