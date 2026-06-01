import pdfplumber
import pandas as pd
import re
import io

def clean_cell_text(cell):
    if cell is None:
        return ""
    # ✅ 保留換行，用特殊分隔符替換，之後展開用
    return str(cell).replace('\n', '|NEWLINE|').strip()


def _expand_merged_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    將同一儲存格內用 |NEWLINE| 分隔的多筆資料展開成多列。
    以第一欄為基準決定要展開幾列。
    """
    expanded = []
    
    for _, row in df.iterrows():
        # 以各欄的 |NEWLINE| 分割，找出最多幾筆
        split_cells = [str(v).split('|NEWLINE|') for v in row]
        max_lines = max(len(parts) for parts in split_cells)
        
        if max_lines <= 1:
            # 單筆，直接清除分隔符後加入
            expanded.append([v.replace('|NEWLINE|', ' ').strip() for v in row])
            continue
        
        # 多筆，逐行展開
        for line_idx in range(max_lines):
            new_row = []
            for parts in split_cells:
                if line_idx < len(parts):
                    val = parts[line_idx].strip()
                else:
                    # 該欄沒有這一行，沿用最後一個值（〃 同上邏輯）
                    val = parts[-1].strip()
                new_row.append(val)
            expanded.append(new_row)
    
    return pd.DataFrame(expanded, columns=df.columns)


def _resolve_ditto(df: pd.DataFrame) -> pd.DataFrame:
    """
    將「〃」（同上符號）替換為上一列的同欄值。
    """
    df = df.copy()
    for col in df.columns:
        for i in range(1, len(df)):
            if df.at[i, col] in ('〃', '″', '"', '同上', ''):
                if df.at[i, col] == '〃' or df.at[i, col] == '″':
                    df.at[i, col] = df.at[i - 1, col]
    return df

def extract_securities_table_from_bytes(pdf_bytes: bytes):
    """
    接收 PDF 的二進位資料，在記憶體中解析出「期末持有之重大有價證券」表格，
    並回傳 pandas DataFrame。如果找不到則回傳 None。
    """
    target_title = "期末持有之重大有價證券"
    appendix_pattern = re.compile(r"(附表[一二三四五六七八九十]+)")
    
    target_appendix = None
    toc_page_idx = -1
    
    print("\n🚀 開始在記憶體中解析 PDF...")
    
    # 💡 關鍵修改：將 bytes 轉為虛擬檔案物件
    pdf_file = io.BytesIO(pdf_bytes)
    
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        
        # 💡 第一階段：找出目錄頁與對應的附表編號
        for page_idx in range(total_pages):
            page = pdf.pages[page_idx]
            text = page.extract_text() or ""
            compressed_text = re.sub(r'\s+', '', text)
            
            if target_title in compressed_text:
                title_idx = compressed_text.find(target_title)
                text_after_title = compressed_text[title_idx:]
                
                match = appendix_pattern.search(text_after_title)
                if match:
                    target_appendix = match.group(1)
                    toc_page_idx = page_idx
                    print(f"🔍 成功在第 {page_idx + 1} 頁(目錄區)抓出對應關係：【{target_title}】 屬於 【{target_appendix}】")
                    break
                    
        if not target_appendix:
            print(f"❌ 找不到『{target_title}』對應的附表編號。")
            return None
            
        # 💡 第二階段：找真實表格
        target_page_num = None
        all_table_rows = []
        global_header = None
        
        for page_idx in range(toc_page_idx + 1, total_pages):
            current_page = pdf.pages[page_idx]
            page_text = current_page.extract_text() or ""
            compressed_page_text = re.sub(r'\s+', '', page_text)
            
            if target_page_num is None:
                if target_appendix in compressed_page_text and "有價證券" in compressed_page_text:
                    if current_page.extract_tables():
                        target_page_num = page_idx
                        print(f"📌 成功避開目錄！在第 {page_idx + 1} 頁找到真實的 {target_appendix} 表格起點。")
                    else:
                        continue
            
            if target_page_num is not None:
                current_page_appendixes = set(appendix_pattern.findall(compressed_page_text))
                other_appendixes = current_page_appendixes - {target_appendix}
                
                if other_appendixes and page_idx > target_page_num:
                    print(f"🛑 偵測到下一個附表 {other_appendixes}，於第 {page_idx + 1} 頁停止擷取。")
                    break
                    
                tables = current_page.extract_tables()
                if not tables:
                    continue
                    
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                        
                    if global_header is None:
                        global_header = [clean_cell_text(c) for c in table[0]]
                        global_header = [h if h else f"欄位_{i}" for i, h in enumerate(global_header)]
                        data_rows = table[1:]
                    else:
                        first_row_clean = [clean_cell_text(c) for c in table[0]]
                        if any(h in first_row_clean for h in global_header if h and len(h) > 1):
                            data_rows = table[1:]
                        else:
                            data_rows = table
                            
                    for row in data_rows:
                        clean_row = [clean_cell_text(c) for c in row]
                        if len(clean_row) < len(global_header):
                            clean_row += [""] * (len(global_header) - len(clean_row))
                        else:
                            clean_row = clean_row[:len(global_header)]
                        all_table_rows.append(clean_row)

    # 💡 第三階段：回傳 DataFrame，不直接存檔
    if all_table_rows and global_header:
        df = pd.DataFrame(all_table_rows, columns=global_header)
        df = df.dropna(how='all')
        
        # ✅ 展開多筆合併列
        df = _expand_merged_rows(df)
        
        # ✅ 解析「〃」同上符號
        df = _resolve_ditto(df)
        
        # ✅ 過濾全空列
        df = df[df.apply(lambda r: any(v.strip() for v in r), axis=1)]
        
        print(f"🎉 擷取成功！總共抓取 {len(df)} 筆資料。")
        return df
    else:
        print("❌ 未能成功解析出結構化表格資料。")
        return None  # ✅ 呼叫端已有接住，不會出錯