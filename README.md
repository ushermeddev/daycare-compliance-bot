# 托嬰合規助理 — 系統架構設計
### PoC: LINE-based Day-Care Compliance Recording System (Taiwan)

---

## 1. 核心定位與市場切入策略

### 目標問題
桃園市（及全台）托嬰中心每日需記錄大量合規資料，以符合衛福部及桃園市婦幼發展局評鑑要求。現行痛點：
- 雙手忙碌時難以開 App 操作（愛托付需逐步點按）
- 消毒/換尿布時間超過間隔時**無主動警示**，常在評鑑當天才發現紀錄缺漏
- 合規紀錄查詢分散，評鑑委員來訪時需臨時翻找

### 市場現況與定位

台灣約有 1,500+ 間托嬰中心，愛托付為目前市場主流電子聯絡簿，擁有台北市/新北市托嬰協會背書，並在保育從業者培訓課程中被推薦。**愛托付的核心強項是親師溝通**（照片、影片、即時通知），家長高度依賴，這部分不應競爭。

**本系統定位：愛托付的合規強化層（Compliance Overlay），而非替代品。**

目標客戶：**已使用愛托付、但在評鑑或訪視輔導中曾被提醒合規紀錄缺失的桃園市托嬰中心。**

```
親師溝通、成長紀錄、家長通知  →  繼續使用愛托付（不動）
合規紀錄快速輸入 + 逾時警示   →  本系統（LINE Bot）
```

### 功能邊界（與愛托付的分工）

| 功能 | 愛托付 | 本系統 |
|---|---|---|
| 家長照片/影片通知 | ✅ 核心強項 | ❌ 不做 |
| 成長曲線、發展檢核 | ✅ | ❌ 不做 |
| 接送委託、用藥委託（家長簽名）| ✅ | ❌ 不做 |
| 合規間隔紀錄（換尿布/消毒/體溫）| ✅ 被動記錄 | ✅ **主動警示 + 語音快速輸入** |
| 逾時警報推送 | ❌ 無 | ✅ **核心功能** |
| 評鑑格式報表 | 匯出 Excel/PDF | ✅ **對應桃園市評鑑指標格式** |
| AI 語音/自然語言輸入 | ❌ | ✅ |
| RAG 合規建議查詢 | ❌ | ✅ |

---

## 2. 技術棧（直接延用 RADMAX）

| 層級 | 技術 | 說明 |
|---|---|---|
| 通訊介面 | **LINE Messaging API v3** | Webhook 接收訊息，主動推送警示 |
| AI 核心 | **Google Gemini 2.5 Flash** | 意圖辨識、結構化萃取、語音轉文字 |
| 後端框架 | **FastAPI (Python 3.13)** | 與 RADMAX 相同 |
| 資料庫 | **Supabase (PostgreSQL)** | 結構化記錄 + RPC 模糊搜尋 |
| 知識庫 | **AnythingLLM** | 上傳桃園市評鑑 PDF，提供合規建議 |
| 開發維運 | **Docker + ngrok** | 本地開發與 Webhook 隧道 |
| 報表匯出 | Python (pandas + reportlab) | 生成 PDF / Excel 合規報表 |

---

## 3. 使用者角色（僅限院所內部人員）

> ⚠️ 家長端功能不在本系統範疇，由愛托付負責。

```
┌──────────────────────────────────────────┐
│               LINE 介面                   │
├──────────────────┬───────────────────────┤
│  保育員           │  園所主管              │
│  (Staff)         │  (Admin)               │
│                  │                        │
│ • 語音/文字快速紀錄│ • 逾時警示通知         │
│ • 查詢個人待辦    │ • 查詢全班合規狀態     │
│ • 拍照上傳消毒紀錄│ • 產生評鑑報表         │
│                  │ • 設定合規規則閾值     │
└──────────────────┴───────────────────────┘
```

---

## 4. 合規紀錄項目（對應桃園市 115–117 年評鑑指標）

### 4.1 衛生保健類（最高優先）

| 紀錄項目 | 必填欄位 | 合規間隔 | 評鑑指標對應 |
|---|---|---|---|
| **換尿布** (diaper_change) | 嬰兒ID、時間、保育員、皮膚狀況 | ≤ 3 小時 | 衛生保健指標 |
| **體溫量測** (temperature) | 嬰兒ID、時間、溫度(°C)、部位 | ≤ 2 次/日（早晚）| 衛生保健指標 |
| **環境消毒** (decontamination) | 區域/器材、方法、保育員、時間 | 依場所規定 | 衛生保健指標 |
| **用藥紀錄** (medication) | 嬰兒ID、藥名、劑量、給藥員 | 每次用藥 | 衛生保健指標 |

### 4.2 托育活動類

| 紀錄項目 | 必填欄位 | 備註 |
|---|---|---|
| **餵食** (feeding) | 嬰兒ID、時間、類型(母乳/配方奶)、量(ml) | |
| **睡眠** (sleep) | 嬰兒ID、入睡/起床時間 | |
| **身體狀況** (health_note) | 嬰兒ID、描述、保育員 | 異常狀況記錄 |

### 4.3 行政管理類

| 紀錄項目 | 說明 |
|---|---|
| **教育訓練** (training_log) | 保育員訓練紀錄（評鑑須知） |

---

## 5. LINE Bot 互動流程（核心設計）

### 5.1 雙大腦分流（沿用 RADMAX 架構）

```
使用者訊息（文字/語音/圖片）
          │
          ▼
   Gemini 意圖辨識
          │
    ┌─────┴─────┐
    ▼           ▼
 REPORT       QUERY
 (紀錄)       (查詢)
    │           │
    ▼           ▼
結構化JSON萃取  檢索 Supabase
    │           │
    ▼           ▼
寫入資料庫   AI 彙整回覆
    │
    ▼
觸發合規警示引擎
```

### 5.2 典型對話範例

**保育員快速紀錄（語音）：**
```
👩‍🦱 保育員：「小明剛換尿布，屁股有點紅」
🤖 Bot：✅ 已紀錄
         嬰兒：小明
         時間：14:32
         狀況：皮膚發紅（已加備註）
         下次換尿布提醒：17:32 前
```

**逾時後快速回報（一句話完成）：**
```
🔴 【逾時警示】
小花的尿布已超過 3 小時未換！
最後紀錄：上午 10:15 by 林老師
請立即處理 👉 回覆「小花換好了」快速完成紀錄

👩‍🦱 保育員：「小花換好了」
🤖 Bot：✅ 已紀錄 14:28，感謝！
```

**主管查詢逾時清單：**
```
👩‍💼 主管：「今天有哪些逾時？」
🤖 Bot：⚠️ 逾時提醒清單（06/07）
         🔴 小華 — 換尿布 已超過 3.5 小時（最後：10:15）
         🟡 環境消毒 — B室玩具 距上次消毒 5.2 小時
         🟢 其他嬰兒 — 均正常
```

**保育員查詢待辦：**
```
👩‍🦱 保育員：「我現在該做什麼？」
🤖 Bot：📋 你的待辦（14:45）
         🔴 [緊急] 小美 換尿布（已 3h 10m）
         🟡 [待辦] 小華 體溫量測（下午班應量）
         🟢 [OK] 小明 剛換完（14:32）
```

**照片輸入（消毒紀錄）：**
```
👩‍🦱 保育員：[上傳消毒液使用照片] + 「B室地板消毒完畢」
🤖 Bot：✅ 消毒紀錄已儲存
         區域：B室地板
         方法：AI 辨識消毒液品牌 → 次氯酸鈉
         時間：14:47
```

**主管產生評鑑報表：**
```
👩‍💼 主管：「產生本週評鑑報表」
🤖 Bot：📄 正在生成 06/01–06/07 合規報表...
         [PDF 檔案] 桃園市衛生保健評鑑紀錄_20260607.pdf
         換尿布完整率：97%（1 次逾時）
         體溫量測完整率：100%
         消毒紀錄完整率：100%
```

---

## 6. 資料庫 Schema（Supabase / PostgreSQL）

```sql
-- 嬰兒基本資料
CREATE TABLE babies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  nickname TEXT,
  dob DATE,
  room TEXT,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
  -- 注意：不儲存家長 LINE ID，家長通知由愛托付負責
);

-- 保育員
CREATE TABLE staff (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  line_user_id TEXT UNIQUE,
  role TEXT CHECK (role IN ('staff', 'admin')),
  center_id UUID,
  is_active BOOLEAN DEFAULT true
);

-- 托嬰中心
CREATE TABLE centers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  line_group_id TEXT,   -- LINE 群組 ID（主管警示頻道）
  city TEXT DEFAULT '桃園市'
);

-- 合規紀錄（核心表）
CREATE TABLE compliance_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  center_id UUID REFERENCES centers(id),
  baby_id UUID REFERENCES babies(id),    -- NULL for environment records
  record_type TEXT NOT NULL,             -- diaper_change / temperature / decontamination / etc.
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  recorded_by UUID REFERENCES staff(id),
  data JSONB NOT NULL,                   -- 彈性欄位：溫度、用量、區域等
  raw_input TEXT,                        -- 原始使用者輸入（保留供 audit）
  ai_confidence FLOAT,                   -- Gemini 萃取信心度
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 合規規則（可設定各中心自訂閾值）
CREATE TABLE compliance_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  center_id UUID REFERENCES centers(id),
  record_type TEXT NOT NULL,
  max_interval_minutes INTEGER,          -- 換尿布：180, 體溫：720 等
  applies_to TEXT DEFAULT 'baby',        -- 'baby' or 'environment'
  alert_threshold_minutes INTEGER        -- 提前幾分鐘預警
);

-- 警示日誌
CREATE TABLE alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  center_id UUID REFERENCES centers(id),
  baby_id UUID REFERENCES babies(id),
  record_type TEXT,
  alerted_at TIMESTAMPTZ DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  resolved_by UUID REFERENCES staff(id)
);
```

---

## 7. 合規警示引擎

```python
# 核心邏輯（FastAPI 背景排程，每 10 分鐘執行）
async def compliance_check():
    rules = await get_all_rules()          # 從 Supabase 取得各中心規則
    for rule in rules:
        last_records = await get_last_records(rule)
        for item in last_records:
            elapsed = now() - item.recorded_at
            if elapsed > rule.max_interval_minutes:
                await push_line_alert(item, elapsed)   # 推送 LINE 警示給保育員
                await push_line_alert_admin(item)      # 同時通知主管
                await log_alert(item)                  # 寫入 alerts 表
```

---

## 8. 系統架構圖

```
┌──────────────────────────────────────────────────────────────────┐
│                        LINE Platform                              │
│  保育員 / 主管 ──── LINE Messaging API ──── Webhook              │
│  （家長端維持使用愛托付，不在本系統範疇）                          │
└──────────────────────────────────────┬───────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    FastAPI Application                            │
│                                                                   │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐  │
│  │ Intent Router│ → │ Gemini 2.5   │ → │ Record Extractor     │  │
│  │ (Zero-shot)  │   │ Flash        │   │ (safe_parse_json)    │  │
│  └──────────────┘   └──────────────┘   └──────────────────────┘  │
│                                                 │                 │
│  ┌──────────────────────────────────────────────▼──────────────┐  │
│  │              Compliance Engine                               │  │
│  │  • 寫入紀錄 → 更新最後記錄時間                               │  │
│  │  • 排程掃描 → 超時觸發 LINE 推送（保育員 + 主管）             │  │
│  │  • RAG 查詢 → 合規建議（AnythingLLM）                        │  │
│  │  • 報表產生 → 對應桃園市評鑑指標格式                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────┬─────────────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         ▼                               ▼
 ┌───────────────┐               ┌───────────────┐
 │   Supabase    │               │  AnythingLLM  │
 │  PostgreSQL   │               │  (本地 RAG)   │
 │               │               │               │
 │ • 紀錄資料    │               │ • 桃園市評鑑  │
 │ • 嬰兒資料    │               │   指標 PDF    │
 │ • 警示日誌    │               │ • 感染管制手冊│
 └───────────────┘               └───────────────┘
```

---

## 9. PoC 開發優先順序

### Phase 1（MVP，2 週）
1. FastAPI + LINE Webhook 基礎架構
2. 換尿布、體溫、消毒三種紀錄類型
3. Gemini 文字輸入萃取 + Supabase 寫入
4. 基本 QUERY（「上次換尿布幾點？」「我現在該做什麼？」）

### Phase 2（合規警示，+1 週）
5. 合規規則引擎 + 定時警示推送（保育員 + 主管同步）
6. 逾時後一句話回報流程（「小花換好了」）
7. 語音輸入支援（Gemini multimodal）

### Phase 3（報表，+1 週）
8. 對應桃園市評鑑指標格式的 PDF 報表
9. AnythingLLM 整合（上傳評鑑 PDF 知識庫）
10. 完整率統計儀表板（主管查詢用）

> ❌ 已移除：家長通知推送（由愛托付負責，不重複建造）

---

## 10. RAG 知識庫文件清單（AnythingLLM）

上傳以下文件作為合規建議依據：

| 文件 | 來源 |
|---|---|
| 115-117年桃園市評鑑指標【衛生保健】.pdf | 桃園市婦幼發展局 |
| 115-117年桃園市評鑑指標【行政管理】.pdf | 桃園市婦幼發展局 |
| 115-117年桃園市評鑑指標【托育活動】.pdf | 桃園市婦幼發展局 |
| 桃園市托嬰中心營運管理手冊 | 桃園市婦幼發展局 |
| 托嬰中心感染管制手冊 | 衛福部疾管署 |

---

## 11. 環境變數（`.env`）

```env
# 沿用 RADMAX 結構
LINE_CHANNEL_ACCESS_TOKEN="your_token"
LINE_CHANNEL_SECRET="your_secret"
GOOGLE_API_KEY="your_gemini_key"
SUPABASE_URL="your_supabase_url"
SUPABASE_KEY="your_supabase_key"
ANYTHINGLLM_API_KEY="your_anythingllm_key"
ANYTHINGLLM_WORKSPACE="daycare-compliance"
ANYTHINGLLM_URL="http://localhost:3001/api/v1"

# 新增
CENTER_ID="your_center_uuid"          # 單一中心 PoC 先寫死
COMPLIANCE_CHECK_INTERVAL_MINUTES=10  # 警示引擎掃描頻率
```

---

## 12. 待確認事項

1. **LINE 群組 vs 個人對話**：保育員用個人對話紀錄？還是班級群組？建議個人對話（確保紀錄歸屬明確）。主管另設一個警示群組（含所有保育員＋主管）。
2. **桃園市評鑑 PDF 取得**：需手動從婦幼發展局網站下載後上傳 AnythingLLM。
3. **PDPA 個資法合規**：嬰兒資料需加密儲存，LINE user ID 與保育員資料關聯需告知員工。
4. **PoC 目標中心確認**：建議找一間已使用愛托付、且曾在訪視輔導中被指出合規紀錄缺失的桃園市托嬰中心作為第一個客戶。

---

*文件版本：v0.2 — 2026/06/07*
*更新內容：重新定位為愛托付合規強化層；移除家長端功能；新增功能邊界分工表；更新目標客戶定義。*
*參考來源：RADMAX 架構、桃園市婦幼發展局 115–117 評鑑指標、愛托付功能文件與用戶評價*
