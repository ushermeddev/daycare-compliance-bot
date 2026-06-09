"""
Background compliance engine.
Runs on a schedule, checks intervals, pushes LINE alerts when overdue.
"""
import os
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from linebot.v3.messaging import (
    AsyncApiClient, AsyncMessagingApi, Configuration,
    PushMessageRequest, TextMessage,
)

from database import get_compliance_rules, get_all_last_records_for_center, log_alert
from models import RecordType

_config = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""))
ADMIN_LINE_GROUP_ID = os.getenv("ADMIN_LINE_GROUP_ID", "")  # main alert channel


_RECORD_LABELS = {
    "diaper_change": "換尿布",
    "temperature": "體溫量測",
    "decontamination": "環境消毒",
    "feeding": "餵食",
    "sleep": "睡眠",
    "health_note": "身體狀況",
    "medication": "用藥紀錄",
}


async def _push(target_id: str, text: str):
    if not target_id:
        return
    async with AsyncApiClient(_config) as client:
        api = AsyncMessagingApi(client)
        await api.push_message(
            PushMessageRequest(
                to=target_id,
                messages=[TextMessage(text=text)],
            )
        )


async def run_compliance_check():
    """Called by APScheduler every N minutes."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Running compliance check...")
    rules = get_compliance_rules()
    now_utc = datetime.now(timezone.utc)

    for rule in rules:
        record_type = rule["record_type"]
        max_minutes = rule["max_interval_minutes"]
        if not max_minutes:
            continue

        try:
            rt = RecordType(record_type)
        except ValueError:
            continue

        records = get_all_last_records_for_center(rt)
        for rec in records:
            recorded_at = _parse_dt(rec["recorded_at"])
            elapsed_min = (now_utc - recorded_at).total_seconds() / 60

            if elapsed_min > max_minutes:
                await _fire_alert(rec, rt, elapsed_min, max_minutes)


async def _fire_alert(rec: dict, rt: RecordType, elapsed_min: float, max_min: int):
    baby_name = rec.get("baby_name") or rec.get("zone") or "（未知）"
    label = _RECORD_LABELS.get(rt.value, rt.value)
    over_min = int(elapsed_min - max_min)
    last_time = _tw_time(_parse_dt(rec["recorded_at"]))
    staff_name = rec.get("staff_name", "上一位保育員")

    alert_text = (
        f"🔴 【逾時警示】\n"
        f"{baby_name} 的{label}已超過 {int(elapsed_min)} 分鐘！\n"
        f"（規定上限：{max_min} 分鐘）\n"
        f"最後紀錄：{last_time} by {staff_name}\n\n"
        f"請立即處理 👉 回覆「{baby_name}換好了」快速完成紀錄"
    )

    # Push to admin group
    await _push(ADMIN_LINE_GROUP_ID, alert_text)

    # Log alert
    log_alert(
        baby_id=rec.get("baby_id"),
        record_type=rt.value,
    )
    print(f"  ⚠️  Alert fired: {baby_name} / {label} / {over_min}min over")


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _tw_time(dt: datetime) -> str:
    tw = dt.astimezone(timezone(timedelta(hours=8)))
    return tw.strftime("%H:%M")
