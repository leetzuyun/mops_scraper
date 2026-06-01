import pandas as pd
from pathlib import Path

# --- 1. 定義各類別專屬欄位結構 ---
COLUMN_SPECS = {
    "取得或處分私募有價證券公告": [
        "公司代號", "主旨",
        "標的物之名稱及性質（屬特別股者，並應標明特別股約定發行條件，如股息率等）",
        "事實發生日",
        "交易單位數量、每單位價格及交易總金額",
        "迄目前為止，累積持有本交易證券（含本次交易）之數量、金額、持股比例及權利受限情形（如質押情形）",
        "迄目前為止，私募有價證券投資（含本次交易）占公司最近期財務報表中總資產及歸屬於母公司業主之權益之比例暨最近期財務報表中營運資金數額",
        "經理人及經紀費用",
        "取得或處分之具體目的或用途",
        "其他敘明事項"
    ],
    "取得或處分資產公告": [
        "公司代號", "主旨",
        "證券名稱", "交易日期",
        "交易數量、每單位價格及交易總金額",
        "迄目前為止，累積持有本交易證券（含本次交易）之數量、金額、持股比例及權利受限情形（如質押情形）",
        "迄目前為止，依「公開發行公司取得或處分資產處理準則」第三條所列之有價證券投資（含本次交易）占公司最近期財務報表中總資產及歸屬於母公司業主之權益之比例暨最近期財務報表中營運資金數額",
        "取得或處分之具體目的",
        "其他敘明事項"
    ]
}

# --- 2. 標題模糊比對函數 ---
def get_feature_key(col_name: str) -> str:
    """提取核心關鍵字，用來對付 MOPS 變幻莫測的表格標題"""
    if "標的物" in col_name: return "標的物之名稱"
    if "證券名稱" in col_name: return "證券名稱"
    if "事實發生日" in col_name: return "事實發生日"
    if "交易日期" in col_name: return "交易日期"
    if "交易單位數量" in col_name: return "交易單位數量"
    if "交易數量" in col_name: return "交易數量"
    if "累積持有本交易證券" in col_name: return "累積持有"
    if "私募有價證券投資" in col_name: return "私募有價證券投資"
    if "公開發行公司" in col_name: return "處理準則"
    if "經理人及" in col_name: return "經理人及"
    if "具體目的" in col_name: return "具體目的"
    if "其他敘明" in col_name: return "其他敘明"
    return col_name

def resolve_official_col_name(raw_col_name: str, category_name: str) -> str:
    """
    不管 MOPS 網頁上的欄位叫「證券名稱」還是「標的物...」，
    都會自動轉換成該 category_name 在 COLUMN_SPECS 中規定的正確官方長檔名。
    """
    # 取得當前公告種類的標準欄位列表
    specs = COLUMN_SPECS.get(category_name, [])
    if not specs:
        return raw_col_name
    # 概念 1：標的名稱 (只要出現標的物或證券名稱，就去 specs 找對應的長字串)
    if any(k in raw_col_name for k in ["標的物", "證券名稱"]):
        return next((col for col in specs if "標的物" in col or "證券名稱" in col), raw_col_name)
    # 概念 2：日期
    if any(k in raw_col_name for k in ["事實發生日", "交易日期"]):
        return next((col for col in specs if "事實發生日" in col or "交易日期" in col), raw_col_name)
    # 概念 3：數量與金額
    if any(k in raw_col_name for k in ["交易單位數量", "交易數量"]):
        return next((col for col in specs if "數量" in col and "金額" in col), raw_col_name)
    # 概念 4：累積持有
    if "累積持有" in raw_col_name:
        return next((col for col in specs if "累積持有" in col), raw_col_name)
    # 概念 5：總資產與財務比例
    if any(k in raw_col_name for k in ["私募有價證券投資", "公開發行公司", "總資產"]):
        return next((col for col in specs if "總資產" in col or "營運資金" in col), raw_col_name)
    # 概念 6：經理人與費用
    if "經理人" in raw_col_name:
        return next((col for col in specs if "經理人" in col), raw_col_name)
    # 概念 7：目的用途
    if "目的" in raw_col_name or "用途" in raw_col_name:
        return next((col for col in specs if "目的" in col or "用途" in col), raw_col_name)
    # 概念 8：其他
    if "其他敘明" in raw_col_name:
        return next((col for col in specs if "其他敘明" in col), raw_col_name)
    # 如果完全無法分類，就回傳原抓取字串
    return raw_col_name

# --- 3. 匯出 Excel 的獨立函數 ---
def save_records_to_excel(all_category_records: dict, download_dir: Path):
    # 檢查是否所有種類都沒有資料
    total = sum(len(v) for v in all_category_records.values())
    if total == 0:
        print(f"🏁 所有類別均無符合條件的資料，不產生 Excel。")
        return

    excel_name = download_dir / "取得或處分債券相關公告_整合總表.xlsx"
    
    with pd.ExcelWriter(excel_name, engine="openpyxl") as writer:
        for category_name, records in all_category_records.items():
            if not records:
                print(f"   ⚠️ 【{category_name}】無資料，略過此底稿。")
                continue
            
            df_final = pd.DataFrame(records, columns=COLUMN_SPECS[category_name])
            sheet_name = category_name[:31]
            df_final.to_excel(writer, index=False, sheet_name=sheet_name)
            print(f"   ✅ 【{category_name}】寫入 {len(records)} 筆")
    
    print(f"🏁 完成！已匯出至 💾 -> {excel_name.name}")