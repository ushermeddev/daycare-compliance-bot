"""
LINE Messaging API webhook handler.
Orchestrates: receive → route → extract → store/query → reply.
"""
import os
from datetime import datetime, timezone, timedelta

from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent,
    AudioMessageContent, ImageMessageContent,
)
from linebot.v3.messaging import (
    AsyncApiClient, AsyncMessagingApi, Configuration,
    ReplyMessageRequest, TextMessage,
    ShowLoadingAnimationRequest,
)

from router import classify_and_extract, transcribe_and_route, classify_image
from media import download_content
from models import Intent, RecordType, QueryType, ExtractedReport, ExtractedQuery
from database import (
    get_or_create_staff, find_baby_by_name, save_record,
    get_last_record, get_all_last_records_for_center,
    get_compliance_rules, add_baby, deactivate_baby, list_active_babies,
    get_today_record_counts,
)

_config = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""))


async def _reply(reply_token: str, text: str):
    async with AsyncApiClient(_config) as client:
        api = AsyncMessagingApi(client)
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )


async def _show_loading(user_id: str, seconds: int = 20):
    """
    Show LINE 'typing...' animation while processing media.
    FREE — does NOT consume the reply token.
    seconds must be 5–60 in multiples of 5.
    """
    async with AsyncApiClient(_config) as client:
        api = AsyncMessagingApi(client)
        await api.show_loading_animation(
            ShowLoadingAnimationRequest(chat_id=user_id, loading_seconds=seconds)
        )


# ── Main handler ───────────────────────────────────────────────────────────────

async def handle_line_event(event):
    if not isinstance(event, MessageEvent):
        return

    user_id = event.source.user_id
    reply_token = event.reply_token

    # Get or register staff
    staff = get_or_create_staff(user_id)
    staff_id = staff["id"]
    staff_name = staff["name"]

    # ── Route by message type ──────────────────────────────────────────────────
    if isinstance(event.message, TextMessageContent):
        message = event.message.text.strip()

        # Admin commands (prefix-based, no AI needed)
        admin_reply = _handle_admin_command(message)
        if admin_reply is not None:
            await _reply(reply_token, admin_reply)
            return

        extracted = classify_and_extract(message)

    elif isinstance(event.message, AudioMessageContent):
        # Show typing indicator (FREE, does not consume reply token)
        await _show_loading(user_id, seconds=20)
        try:
            audio_bytes = await download_content(event.message.id)
            extracted = transcribe_and_route(audio_bytes)
        except Exception as e:
            await _reply(reply_token, f"⚠️ 語音辨識失敗，請改用文字輸入。\n（{e}）")
            return

    elif isinstance(event.message, ImageMessageContent):
        # Show typing indicator (FREE, does not consume reply token)
        await _show_loading(user_id, seconds=20)
        try:
            image_bytes = await download_content(event.message.id)
            extracted = classify_image(image_bytes)
            # Attach LINE message_id so image is traceable after analysis
            extracted._line_message_id = event.message.id
        except Exception as e:
            await _reply(reply_token, f"⚠️ 照片分析失敗，請改用文字輸入。\n（{e}）")
            return

    else:
        return  # Sticker, location, etc. — ignore

    # raw_input for audit trail — use text if available, else media type label
    raw_input = (
        message if isinstance(event.message, TextMessageContent)
        else f"[語音訊息 {event.message.id}]" if isinstance(event.message, AudioMessageContent)
        else f"[照片訊息 {event.message.id}]"
    )

    if extracted.intent == Intent.REPORT:
        reply = await _handle_report(extracted, staff_id, staff_name, raw_input)
    elif extracted.intent == Intent.QUERY:
        reply = await _handle_query(extracted)
    else:
        reply = (
            "抱歉，我不太理解這則訊息。\n\n"
            "💡 嬰幼兒照護：\n"
            "• 「小明剛換尿布」\n"
            "• 「尿布台消毒好了」\n"
            "• 「小花體溫 37.2」\n"
            "• 「餵小華 150ml」\n"
            "• 「給小明吃安滅達，1顆，飯後」\n"
            "• 「小明身高 72cm 體重 9.2kg」\n"
            "• 「小花的寢具洗好了」\n\n"
            "🏠 環境衛生：\n"
            "• 「B室玩具消毒完畢」\n"
            "• 「冷藏 4 度 冷凍 -19 度」\n"
            "• 「午餐留了食物樣品」\n\n"
            "🔍 查詢：\n"
            "• 「今日紀錄」\n"
            "• 「今天有哪些逾時」\n"
            "• 「我現在該做什麼」"
        )

    await _reply(reply_token, reply)


# ── Admin command handler ──────────────────────────────────────────────────────

def _handle_admin_command(message: str) -> str | None:
    """
    Handle simple admin commands without invoking AI.
    Returns a reply string if the message matched, None otherwise.

    Commands:
      新增寶寶 小明              → add baby with nickname 小明
      新增寶寶 小明 全名:王小明   → add with full name
      嬰兒名單                   → list all active babies
      離托 小明                  → deactivate baby
    """
    msg = message.strip()

    # ── 新增寶寶 ──────────────────────────────────────────────────────────────
    if msg.startswith("新增寶寶"):
        parts = msg[len("新增寶寶"):].strip()
        if not parts:
            return "請輸入寶寶的暱稱，例如：\n新增寶寶 小明\n新增寶寶 小明 全名:王小明"

        nickname = None
        full_name = None

        if "全名:" in parts or "全名：" in parts:
            sep = "全名:" if "全名:" in parts else "全名："
            halves = parts.split(sep, 1)
            nickname = halves[0].strip()
            full_name = halves[1].strip()
        else:
            nickname = parts.split()[0]

        # Check for duplicates
        existing = find_baby_by_name(nickname)
        if existing:
            display = existing.get("nickname") or existing.get("name")
            return f"⚠️ 已有相同名字的寶寶：{display}，請確認是否重複。"

        baby = add_baby(nickname=nickname, full_name=full_name)
        name_display = baby.get("nickname") or baby.get("name")
        full_display = f"（{baby.get('name')}）" if full_name else ""
        return f"✅ 已新增寶寶：{name_display}{full_display}\n\n可以開始用「{name_display}剛換尿布」等指令紀錄。"

    # ── 嬰兒名單 ──────────────────────────────────────────────────────────────
    if msg in ("嬰兒名單", "寶寶名單", "目前寶寶"):
        babies = list_active_babies()
        if not babies:
            return "目前沒有在托寶寶。\n\n新增請輸入：新增寶寶 小明"
        lines = []
        for b in babies:
            nick = b.get("nickname") or ""
            name = b.get("name") or ""
            if nick and nick != name:
                lines.append(f"• {nick}（{name}）")
            else:
                lines.append(f"• {name}")
        return f"👶 目前在托寶寶（共 {len(babies)} 位）\n" + "\n".join(lines)

    # ── 離托 ──────────────────────────────────────────────────────────────────
    if msg.startswith("離托"):
        nickname = msg[len("離托"):].strip()
        if not nickname:
            return "請輸入寶寶暱稱，例如：離托 小明"
        found = deactivate_baby(nickname)
        if found:
            return f"✅ {nickname} 已標記為離托，後續不再出現於紀錄與待辦清單。"
        return f"⚠️ 找不到寶寶「{nickname}」，請確認暱稱是否正確。"

    # ── 今日紀錄 ──────────────────────────────────────────────────────────────
    if msg in ("今日紀錄", "今天紀錄", "今日紀錄摘要", "今天有記錄嗎"):
        return _build_daily_summary()

    # ── 說明 / Help ───────────────────────────────────────────────────────────
    if msg in ("你可以做什麼", "功能", "說明", "help", "Help", "HELP",
               "怎麼用", "使用說明", "選單", "menu"):
        return (
            "👋 我是托嬰合規助理！\n\n"
            "【第一步】先新增寶寶\n"
            "新增寶寶 小明\n"
            "新增寶寶 小明 全名:王小明\n\n"
            "【嬰幼兒照護紀錄】\n"
            "• 小明剛換尿布\n"
            "• 小明體溫 37.2\n"
            "• 餵小明 150ml 配方奶\n"
            "• 小明睡著了\n"
            "• 給小明吃安滅達，1顆，飯後\n"
            "• 小明身高 72cm 體重 9.2kg\n"
            "• 小花的寢具洗好了\n\n"
            "【環境衛生】\n"
            "• 尿布台消毒好了\n"
            "• B室玩具消毒完畢\n"
            "• 冷藏 4 度 冷凍 -19 度\n"
            "• 午餐留了食物樣品\n\n"
            "【查詢】\n"
            "• 今日紀錄\n"
            "• 今天有哪些逾時\n"
            "• 小明上次換尿布幾點\n\n"
            "【管理】\n"
            "• 嬰兒名單\n"
            "• 離托 小明\n\n"
            "也支援語音訊息和照片（體溫計、冰箱溫度顯示）📷🎙️"
        )

    return None  # not an admin command


# ── REPORT handler ─────────────────────────────────────────────────────────────

async def _handle_report(
    extracted: ExtractedReport,
    staff_id: str,
    staff_name: str,
    raw_input: str,
) -> str:
    if not extracted.record_type:
        return "⚠️ 無法辨識紀錄類型，請重新描述（例如：換尿布、體溫、消毒）。"

    now_tw = datetime.now(timezone(timedelta(hours=8)))
    time_str = now_tw.strftime("%H:%M")

    # Resolve baby
    baby_id = None
    baby_display = None
    if extracted.baby_name:
        baby = find_baby_by_name(extracted.baby_name)
        if baby:
            baby_id = baby["id"]
            baby_display = baby.get("nickname") or baby.get("name")
        else:
            return f"⚠️ 找不到嬰兒「{extracted.baby_name}」，請確認名字是否正確。"

    # Build data payload per record type
    data: dict = {}
    summary_lines = []

    if extracted.record_type == RecordType.DIAPER_CHANGE:
        data = {"skin_condition": extracted.notes}
        summary_lines = [
            f"嬰兒：{baby_display}",
            f"時間：{time_str}",
        ]
        if extracted.notes:
            summary_lines.append(f"狀況：{extracted.notes}")
        summary_lines.append(f"下次換尿布提醒：{_add_minutes(now_tw, 180).strftime('%H:%M')} 前")
        summary_lines.append("🧹 提醒：請立即消毒尿布台（評鑑項目）")

    elif extracted.record_type == RecordType.TEMPERATURE:
        temp = extracted.value
        data = {"temperature_c": temp}
        summary_lines = [
            f"嬰兒：{baby_display}",
            f"時間：{time_str}",
            f"體溫：{temp}°C" if temp else "體溫：未填",
        ]
        if temp:
            t = float(temp)
            if t >= 38.0:
                summary_lines.append("🚨 發燒（≥38°C），請立即通知家長及主管！")
            elif t >= 37.5:
                summary_lines.append("⚠️ 體溫偏高（37.5–38°C），請持續觀察。")

    elif extracted.record_type == RecordType.DECONTAMINATION:
        zone = extracted.environment_zone or "（未指定區域）"
        data = {"zone": zone, "method": extracted.notes}
        summary_lines = [
            f"區域：{zone}",
            f"時間：{time_str}",
        ]
        if extracted.notes:
            summary_lines.append(f"方法：{extracted.notes}")

    elif extracted.record_type == RecordType.FEEDING:
        data = {"amount_ml": extracted.value, "type": extracted.notes}
        summary_lines = [
            f"嬰兒：{baby_display}",
            f"時間：{time_str}",
            f"用量：{extracted.value} ml" if extracted.value else "",
        ]
        summary_lines.append(f"下次餵食提醒：{_add_minutes(now_tw, 240).strftime('%H:%M')} 前")

    elif extracted.record_type == RecordType.GROWTH_MEASUREMENT:
        # value=身高cm, value2=體重kg, value3=頭圍cm
        height = extracted.value
        weight = extracted.value2
        head = extracted.value3
        data = {"height_cm": height, "weight_kg": weight, "head_circumference_cm": head}
        summary_lines = [f"嬰兒：{baby_display}", f"時間：{time_str}"]
        if height:
            summary_lines.append(f"身高：{height} cm")
        if weight:
            summary_lines.append(f"體重：{weight} kg")
        if head:
            summary_lines.append(f"頭圍：{head} cm")

    elif extracted.record_type == RecordType.SLEEP:
        data = {"notes": extracted.notes}
        summary_lines = [
            f"嬰兒：{baby_display}",
            f"時間：{time_str}",
        ]
        if extracted.notes:
            summary_lines.append(f"備註：{extracted.notes}")

    elif extracted.record_type == RecordType.HEALTH_NOTE:
        data = {"notes": extracted.notes, "value": extracted.value}
        condition = extracted.notes or "（請補充說明）"
        summary_lines = [
            f"嬰兒：{baby_display}",
            f"時間：{time_str}",
            f"狀況：{condition}",
        ]
        summary_lines.append("📋 如有異常請通知家長並填寫健康觀察紀錄")

    elif extracted.record_type == RecordType.MEDICATION:
        # Require drug name + dose — top violation: incomplete medication delegation forms
        if not extracted.notes:
            return (
                "⚠️ 給藥紀錄需填寫藥品資訊。\n\n"
                "請重新輸入，例如：\n"
                "「給小明吃安滅達，1顆，飯後」\n\n"
                "📋 評鑑要求：給藥委託書需含藥名、劑量、頻次，且家長已簽署。"
            )
        data = {"drug_info": extracted.notes, "amount": extracted.value}
        summary_lines = [
            f"嬰兒：{baby_display}",
            f"時間：{time_str}",
            f"藥品：{extracted.notes}",
        ]
        if extracted.value:
            summary_lines.append(f"劑量：{extracted.value}")
        summary_lines.append("📋 請確認家長已簽署給藥委託書（須含藥名、劑量、頻次）")

    elif extracted.record_type == RecordType.BEDDING_WASH:
        data = {"notes": extracted.notes}
        summary_lines = [
            f"嬰兒：{baby_display}",
            f"時間：{time_str}",
            "下次清洗提醒：7 天後",
        ]

    elif extracted.record_type == RecordType.DIAPER_TABLE_CLEAN:
        zone = extracted.environment_zone or "換尿布台"
        data = {"zone": zone, "notes": extracted.notes}
        summary_lines = [
            f"區域：{zone}",
            f"時間：{time_str}",
            "✅ 每次換尿布後消毒（評鑑項目 50）",
        ]

    elif extracted.record_type == RecordType.FRIDGE_TEMP:
        cold = extracted.value    # 冷藏°C
        frozen = extracted.value2 # 冷凍°C
        zone = extracted.environment_zone or "廚房"
        data = {"cold_c": cold, "frozen_c": frozen, "zone": zone}
        summary_lines = [f"區域：{zone}", f"時間：{time_str}"]
        warnings = []
        if cold is not None:
            summary_lines.append(f"冷藏：{cold}°C")
            if float(cold) > 7:
                warnings.append(f"🚨 冷藏溫度 {cold}°C 超標（應 ≤7°C）！")
        if frozen is not None:
            summary_lines.append(f"冷凍：{frozen}°C")
            if float(frozen) > -18:
                warnings.append(f"🚨 冷凍溫度 {frozen}°C 超標（應 ≤-18°C）！")
        summary_lines.extend(warnings)

    elif extracted.record_type == RecordType.FOOD_SAMPLE:
        zone = extracted.environment_zone or "廚房"
        meal = extracted.notes or "餐點"
        expiry_tw = _add_minutes(now_tw, 48 * 60)
        data = {"zone": zone, "meal_desc": meal, "expires_at": expiry_tw.isoformat()}
        summary_lines = [
            f"餐次：{meal}",
            f"留樣時間：{time_str}",
            f"保存至：{expiry_tw.strftime('%m/%d %H:%M')}（48小時）",
            "📦 請密封冷藏 ≤7°C",
        ]

    else:
        data = {"value": extracted.value, "notes": extracted.notes}
        summary_lines = [f"嬰兒：{baby_display}", f"時間：{time_str}"]

    # Attach photo evidence reference if this record came from an image
    line_msg_id = getattr(extracted, "_line_message_id", None)
    if line_msg_id:
        data["line_image_id"] = line_msg_id  # traceable for 30 days via LINE API

    # Persist
    save_record(
        record_type=extracted.record_type,
        staff_id=staff_id,
        data=data,
        raw_input=raw_input,
        baby_id=baby_id,
        ai_confidence=extracted.confidence,
        notes=extracted.notes,
    )

    label = _record_label(extracted.record_type)
    detail = "\n".join(l for l in summary_lines if l)
    return f"✅ {label}已紀錄\n{detail}"


# ── QUERY handler ──────────────────────────────────────────────────────────────

async def _handle_query(extracted: ExtractedQuery) -> str:
    now_utc = datetime.now(timezone.utc)

    if extracted.query_type == QueryType.LAST_RECORD:
        if not extracted.record_type:
            return "請指定查詢類型（例如：「小明上次換尿布幾點？」）"
        baby = find_baby_by_name(extracted.baby_name) if extracted.baby_name else None
        record = get_last_record(extracted.record_type, baby_id=baby["id"] if baby else None)
        if not record:
            return f"尚無 {_record_label(extracted.record_type)} 紀錄。"
        recorded_at = _parse_dt(record["recorded_at"])
        elapsed = _elapsed_str(now_utc - recorded_at)
        name = (baby.get("nickname") or baby.get("name")) if baby else "（所有嬰兒）"
        return (
            f"📋 最後 {_record_label(extracted.record_type)}\n"
            f"嬰兒：{name}\n"
            f"時間：{_tw_time(recorded_at)}\n"
            f"距今：{elapsed}"
        )

    if extracted.query_type == QueryType.OVERDUE_LIST:
        return await _build_overdue_list(now_utc)

    if extracted.query_type == QueryType.TODO_LIST:
        return await _build_todo_list(now_utc)

    return "請問需要查詢什麼？\n• 「今天有哪些逾時」\n• 「我現在該做什麼」\n• 「小明上次換尿布幾點」"


async def _build_overdue_list(now_utc: datetime) -> str:
    rules = get_compliance_rules()
    if not rules:
        return "⚠️ 尚未設定合規規則，請聯絡主管。"

    lines = []
    for rule in rules:
        rt = RecordType(rule["record_type"])
        records = get_all_last_records_for_center(rt)
        for rec in records:
            recorded_at = _parse_dt(rec["recorded_at"])
            elapsed_min = (now_utc - recorded_at).total_seconds() / 60
            if elapsed_min > rule["max_interval_minutes"]:
                baby_name = rec.get("baby_name") or rec.get("zone") or "（未知）"
                over_min = int(elapsed_min - rule["max_interval_minutes"])
                lines.append(f"🔴 {baby_name} — {_record_label(rt)} 逾時 {over_min} 分鐘")

    if not lines:
        return "✅ 目前所有紀錄均在合規範圍內。"
    return "⚠️ 逾時清單\n" + "\n".join(lines)


async def _build_todo_list(now_utc: datetime) -> str:
    rules = get_compliance_rules()
    if not rules:
        return "⚠️ 尚未設定合規規則，請聯絡主管。"

    urgent, upcoming, ok = [], [], []
    for rule in rules:
        rt = RecordType(rule["record_type"])
        records = get_all_last_records_for_center(rt)
        for rec in records:
            recorded_at = _parse_dt(rec["recorded_at"])
            elapsed_min = (now_utc - recorded_at).total_seconds() / 60
            max_min = rule["max_interval_minutes"]
            threshold_min = rule.get("alert_threshold_minutes", 30)
            baby_name = rec.get("baby_name") or rec.get("zone") or "（未知）"
            label = f"{baby_name} {_record_label(rt)}"
            if elapsed_min > max_min:
                over = int(elapsed_min - max_min)
                urgent.append(f"🔴 [緊急] {label}（已逾時 {over} 分鐘）")
            elif elapsed_min > max_min - threshold_min:
                remaining = int(max_min - elapsed_min)
                upcoming.append(f"🟡 [待辦] {label}（{remaining} 分鐘後到期）")
            else:
                ok.append(f"🟢 {label}（正常）")

    now_tw = now_utc.astimezone(timezone(timedelta(hours=8))).strftime("%H:%M")
    parts = [f"📋 待辦清單（{now_tw}）"]
    parts.extend(urgent)
    parts.extend(upcoming)
    parts.extend(ok[:3])  # show up to 3 OK items to avoid flooding
    return "\n".join(parts) if len(parts) > 1 else "✅ 目前所有項目均正常。"


# ── Daily summary ──────────────────────────────────────────────────────────────

def _build_daily_summary() -> str:
    """
    Show today's record counts per baby and per environment type.
    Flags babies missing critical daily items (temperature < 2×, feeding < 4×).
    Helps supervisors spot missing log entries before end of day.
    """
    records = get_today_record_counts()
    now_tw = datetime.now(timezone(timedelta(hours=8)))
    date_str = now_tw.strftime("%m/%d")

    if not records:
        return f"📊 今日紀錄（{date_str}）\n尚無任何紀錄。"

    # Group by baby
    baby_counts: dict[str, dict] = {}   # baby_display → {record_type: count}
    env_counts: dict[str, int] = {}     # record_type → count (baby_id is None)

    BABY_TYPES = {
        RecordType.DIAPER_CHANGE, RecordType.TEMPERATURE, RecordType.FEEDING,
        RecordType.SLEEP, RecordType.HEALTH_NOTE, RecordType.MEDICATION,
        RecordType.GROWTH_MEASUREMENT, RecordType.BEDDING_WASH,
        RecordType.DIAPER_TABLE_CLEAN,
    }

    for row in records:
        rt_str = row.get("record_type", "")
        baby_info = row.get("babies")   # joined object or None
        if baby_info:
            display = baby_info.get("nickname") or baby_info.get("name") or "（未知）"
            if display not in baby_counts:
                baby_counts[display] = {}
            baby_counts[display][rt_str] = baby_counts[display].get(rt_str, 0) + 1
        else:
            env_counts[rt_str] = env_counts.get(rt_str, 0) + 1

    lines = [f"📊 今日紀錄（{date_str}）"]

    # Per-baby section
    LABEL = {
        "diaper_change": "換尿布", "temperature": "體溫", "feeding": "餵食",
        "sleep": "睡眠", "medication": "給藥", "health_note": "健康",
        "growth_measurement": "體位", "bedding_wash": "寢具清洗",
        "diaper_table_clean": "尿布台消毒",
    }
    for baby, counts in sorted(baby_counts.items()):
        parts = [f"{LABEL.get(k, k)}×{v}" for k, v in counts.items()]
        warnings = []
        # Frequency checks based on evaluation criteria
        if counts.get("temperature", 0) < 2:
            warnings.append("⚠️體溫不足2次")
        if counts.get("feeding", 0) < 3:
            warnings.append("⚠️餵食不足3次")
        warn_str = "  " + " ".join(warnings) if warnings else ""
        lines.append(f"👶 {baby}：{' '.join(parts)}{warn_str}")

    # Environment section
    if env_counts:
        env_parts = [f"{LABEL.get(k, k)}×{v}" for k, v in env_counts.items()]
        lines.append(f"🏠 環境：{' '.join(env_parts)}")

    lines.append("\n輸入「今天有哪些逾時」查看逾時清單")
    return "\n".join(lines)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _record_label(rt: RecordType) -> str:
    return {
        RecordType.DIAPER_CHANGE:      "換尿布",
        RecordType.TEMPERATURE:        "體溫量測",
        RecordType.FEEDING:            "餵食",
        RecordType.SLEEP:              "睡眠",
        RecordType.HEALTH_NOTE:        "身體狀況",
        RecordType.MEDICATION:         "用藥紀錄",
        RecordType.GROWTH_MEASUREMENT: "體位測量",
        RecordType.BEDDING_WASH:       "寢具清洗",
        RecordType.DIAPER_TABLE_CLEAN: "尿布台消毒",
        RecordType.DECONTAMINATION:    "環境消毒",
        RecordType.FRIDGE_TEMP:        "冰箱溫度",
        RecordType.FOOD_SAMPLE:        "食物樣品",
    }.get(rt, rt.value)


def _add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _tw_time(dt: datetime) -> str:
    tw = dt.astimezone(timezone(timedelta(hours=8)))
    return tw.strftime("%H:%M")


def _elapsed_str(delta: timedelta) -> str:
    total_min = int(delta.total_seconds() / 60)
    if total_min < 60:
        return f"{total_min} 分鐘前"
    h, m = divmod(total_min, 60)
    return f"{h} 小時 {m} 分鐘前"
