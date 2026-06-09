from pydantic import BaseModel
from typing import Optional, Any
from enum import Enum


class RecordType(str, Enum):
    # ── 嬰幼兒照護 ───────────────────────────────────────────────────────────
    DIAPER_CHANGE       = "diaper_change"       # 換尿布   (Item 26)
    TEMPERATURE         = "temperature"         # 體溫量測 (Item 39)
    FEEDING             = "feeding"             # 餵食     (Item 25)
    SLEEP               = "sleep"               # 睡眠     (Item 29)
    HEALTH_NOTE         = "health_note"         # 健康紀錄 (Item 39)
    MEDICATION          = "medication"          # 給藥     (Item 59)
    GROWTH_MEASUREMENT  = "growth_measurement"  # 體位測量 (Item 37)
    BEDDING_WASH        = "bedding_wash"        # 寢具清洗 (Item 48)
    DIAPER_TABLE_CLEAN  = "diaper_table_clean"  # 尿布台消毒（每次使用後）
    # ── 環境衛生 ─────────────────────────────────────────────────────────────
    DECONTAMINATION     = "decontamination"     # 環境消毒 (Item 50)
    FRIDGE_TEMP         = "fridge_temp"         # 冰箱溫度 (Item 46)
    FOOD_SAMPLE         = "food_sample"         # 食物樣品 (Item 44)


class Intent(str, Enum):
    REPORT = "REPORT"
    QUERY = "QUERY"
    UNKNOWN = "UNKNOWN"


class QueryType(str, Enum):
    LAST_RECORD = "last_record"
    OVERDUE_LIST = "overdue_list"
    TODO_LIST = "todo_list"
    SUMMARY = "summary"


class ExtractedReport(BaseModel):
    intent: Intent = Intent.REPORT
    record_type: Optional[RecordType] = None
    baby_name: Optional[str] = None          # None for environment records
    environment_zone: Optional[str] = None   # e.g. "B室玩具", "廚房"
    value: Optional[Any] = None              # primary value: temp°C / feeding ml / fridge cold°C / height cm
    value2: Optional[Any] = None             # secondary: fridge freezer°C / weight kg
    value3: Optional[Any] = None             # tertiary: head circumference cm
    notes: Optional[str] = None
    confidence: float = 1.0


class ExtractedQuery(BaseModel):
    intent: Intent = Intent.QUERY
    query_type: QueryType = QueryType.SUMMARY
    record_type: Optional[RecordType] = None
    baby_name: Optional[str] = None
