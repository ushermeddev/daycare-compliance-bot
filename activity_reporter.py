"""
功能一：活動描述生成
老師傳「活動主題：感官探索 — 沙池」進入活動模式，
之後每張照片都會生成家長友善的活動說明文字。
"""
import base64
import os
import google.generativeai as genai

genai.configure(api_key=os.getenv("GOOGLE_API_KEY", ""))
_model = genai.GenerativeModel("gemini-2.5-flash")

_ACTIVITY_PROMPT = """\
你是台灣托嬰中心與家長之間的溝通橋樑，幫助保育員把活動照片轉化為家長易懂的說明。

活動主題：{theme}
月齡：{age_group}

請根據這張照片，用溫暖、親切的繁體中文，寫出 4-6 句說明：
1. 今天進行了什麼活動（具體描述孩子在做什麼）
2. 這個活動對孩子的發展有什麼幫助（對應發展領域，不要用艱澀術語）
3. 孩子的反應 / 表現（從照片中觀察到的）
4. 一句家長可以在家延伸的互動建議

語氣規則：
- 溫暖、正向，像是老師在和家長聊天
- 不要用「研究顯示」「專家建議」等說法
- 不要用學術術語（例如不說「精細動作發展」，改說「手指靈活度」）
- 每段 2-3 行，不要用條列式
- 結尾加一個相關的 emoji

只輸出說明文字，不要其他格式或說明。
"""


def describe_activity(
    image_bytes: bytes,
    theme: str,
    age_group: str | None = None,
) -> str:
    """
    Send image + theme to Gemini Vision.
    Returns parent-friendly Traditional Chinese description.
    """
    age_str = age_group if age_group else "未指定"
    prompt = _ACTIVITY_PROMPT.format(theme=theme, age_group=age_str)

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    response = _model.generate_content([
        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
        prompt,
    ])
    return response.text.strip()
