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

# --- 3. 匯出 Excel 的獨立函數 ---
def save_records_to_excel(records: list, category_name: str, download_dir: Path):
    """
    接收爬蟲抓好的資料清單，將其轉為 DataFrame 並存成水平 Excel 檔案。
    """
    if not records:
        print(f"🏁 【{category_name}】處理完畢，沒有符合條件的資料，不產生 Excel。")
        return

    df_final = pd.DataFrame(records)
    excel_name = download_dir / f"[{category_name}]_整合總表.xlsx"
    
    # 寫入 Excel
    df_final.to_excel(excel_name, index=False, sheet_name=category_name)
    print(f"🏁 【{category_name}】處理完畢！成功導出 {len(records)} 筆水平整合資料 💾 -> {excel_name.name}")