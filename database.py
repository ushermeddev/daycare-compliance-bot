import os
from datetime import datetime, timezone
from typing import Optional
from supabase import create_client, Client
from models import RecordType

supabase: Client = create_client(
    os.getenv("SUPABASE_URL", ""),
    os.getenv("SUPABASE_KEY", ""),
)

CENTER_ID = os.getenv("CENTER_ID", "")


# ── Staff ──────────────────────────────────────────────────────────────────────

def get_or_create_staff(line_user_id: str, display_name: str = "保育員") -> dict:
    result = (
        supabase.table("staff")
        .select("*")
        .eq("line_user_id", line_user_id)
        .execute()
    )
    if result.data:
        return result.data[0]
    new = supabase.table("staff").insert({
        "name": display_name,
        "line_user_id": line_user_id,
        "role": "staff",
        "center_id": CENTER_ID,
    }).execute()
    return new.data[0]


# ── Babies ─────────────────────────────────────────────────────────────────────

def get_all_active_babies() -> list[dict]:
    result = (
        supabase.table("babies")
        .select("*")
        .eq("is_active", True)
        .execute()
    )
    return result.data or []


def find_baby_by_name(name: str) -> Optional[dict]:
    """Fuzzy match: checks if the given name appears in nickname or full name."""
    for baby in get_all_active_babies():
        if name in (baby.get("nickname") or "") or name in (baby.get("name") or ""):
            return baby
    return None


# ── Records ────────────────────────────────────────────────────────────────────

def save_record(
    record_type: RecordType,
    staff_id: str,
    data: dict,
    raw_input: str,
    baby_id: Optional[str] = None,
    ai_confidence: float = 1.0,
    notes: Optional[str] = None,
) -> dict:
    payload = {
        "center_id": CENTER_ID,
        "baby_id": baby_id,
        "record_type": record_type.value,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "recorded_by": staff_id,
        "data": data,
        "raw_input": raw_input,
        "ai_confidence": ai_confidence,
        "notes": notes,
    }
    result = supabase.table("compliance_records").insert(payload).execute()
    return result.data[0]


def get_last_record(
    record_type: RecordType,
    baby_id: Optional[str] = None,
    environment_zone: Optional[str] = None,
) -> Optional[dict]:
    q = (
        supabase.table("compliance_records")
        .select("*, staff(name), babies(name, nickname)")
        .eq("record_type", record_type.value)
        .eq("center_id", CENTER_ID)
        .order("recorded_at", desc=True)
        .limit(1)
    )
    if baby_id:
        q = q.eq("baby_id", baby_id)
    result = q.execute()
    return result.data[0] if result.data else None


def get_all_last_records_for_center(record_type: RecordType) -> list[dict]:
    """Most recent record per baby for a given type (uses DB function)."""
    result = supabase.rpc("get_last_records_per_baby", {
        "p_record_type": record_type.value,
        "p_center_id": CENTER_ID,
    }).execute()
    return result.data or []


def get_compliance_rules() -> list[dict]:
    result = (
        supabase.table("compliance_rules")
        .select("*")
        .eq("center_id", CENTER_ID)
        .execute()
    )
    return result.data or []


# ── Baby management ────────────────────────────────────────────────────────────

def add_baby(nickname: str, full_name: Optional[str] = None) -> dict:
    payload = {
        "nickname": nickname,
        "name": full_name or nickname,
        "center_id": CENTER_ID,
        "is_active": True,
    }
    result = supabase.table("babies").insert(payload).execute()
    return result.data[0]


def deactivate_baby(nickname: str) -> bool:
    """Mark baby as inactive (離托). Returns True if found and updated."""
    baby = find_baby_by_name(nickname)
    if not baby:
        return False
    supabase.table("babies").update({"is_active": False}).eq("id", baby["id"]).execute()
    return True


def list_active_babies() -> list[dict]:
    result = (
        supabase.table("babies")
        .select("name, nickname")
        .eq("center_id", CENTER_ID)
        .eq("is_active", True)
        .order("created_at")
        .execute()
    )
    return result.data or []


# ── Today's records ────────────────────────────────────────────────────────────

def get_today_record_counts() -> list[dict]:
    """
    Return all compliance_records created since today's midnight (Taiwan time).
    Used by the 今日紀錄 summary command.
    """
    tz_tw = timezone(timedelta(hours=8))
    today_start = datetime.now(tz_tw).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_start_utc = today_start.astimezone(timezone.utc).isoformat()

    result = (
        supabase.table("compliance_records")
        .select("baby_id, record_type, babies(name, nickname)")
        .eq("center_id", CENTER_ID)
        .gte("recorded_at", today_start_utc)
        .execute()
    )
    return result.data or []


# ── Alerts ─────────────────────────────────────────────────────────────────────

def log_alert(baby_id: Optional[str], record_type: str):
    supabase.table("alerts").insert({
        "center_id": CENTER_ID,
        "baby_id": baby_id,
        "record_type": record_type,
    }).execute()
