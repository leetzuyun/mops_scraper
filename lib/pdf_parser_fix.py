import pdfplumber
import pandas as pd
import re
import io

def clean_cell_text(cell):
    if cell is None:
        return ""
    return str(cell).replace('\n', '|NEWLINE|').strip()

def _is_packed_format(df: pd.DataFrame) -> bool:
    """
    判斷是否為「多筆塞在一格」的格式。
    以第二欄（有價證券名稱）為準，若超過半數的列都有 |NEWLINE| 且分割數 > 3，
    就認定為 packed 格式。
    """
    if df.shape[1] < 2:
        return False
    col = df.iloc[:, 1].astype(str)
    packed_count = sum(1 for v in col if v.count('|NEWLINE|') > 3)
    return packed_count >= max(1, len(df) * 0.3)


def _expand_merged_rows(df: pd.DataFrame) -> pd.DataFrame:
    expanded = []

    for _, row in df.iterrows():
        split_cells = [str(v).split('|NEWLINE|') for v in row]

        numeric_counts = []
        for col_idx in range(4, len(split_cells)):
            parts = [p.strip() for p in split_cells[col_idx] if p.strip()]
            if parts:
                numeric_counts.append(len(parts))

        n_records = min(numeric_counts) if numeric_counts else max(len(p) for p in split_cells)

        if n_records <= 1:
            expanded.append([' '.join(p.strip() for p in parts).strip()
                             for parts in split_cells])
            continue

        padded = []
        for col_idx, parts in enumerate(split_cells):
            cleaned = [p.strip() for p in parts if p.strip()]

            if not cleaned:
                padded.append([''] * n_records)

            elif len(cleaned) == n_records:
                padded.append(cleaned)

            elif len(cleaned) < n_records:
                if col_idx == 0:
                    while len(cleaned) < n_records:
                        cleaned.append(cleaned[-1])
                else:
                    while len(cleaned) < n_records:
                        cleaned.append('')
                padded.append(cleaned)

            else:
                per_record = len(cleaned) / n_records
                merged = []
                for i in range(n_records):
                    start = round(i * per_record)
                    end = round((i + 1) * per_record)
                    merged.append(' '.join(cleaned[start:end]))
                padded.append(merged)

        for line_idx in range(n_records):
            expanded.append([padded[c][line_idx] for c in range(len(split_cells))])

    return pd.DataFrame(expanded, columns=df.columns)

def _clean_newlines(df: pd.DataFrame) -> pd.DataFrame:
    """格式 B：把殘留的 |NEWLINE| 換成空格就好"""
    return df.map(lambda v: str(v).replace('|NEWLINE|', ' ').strip())


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
    
    pdf_file = io.BytesIO(pdf_bytes)
    
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        
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
            
        # 找表格
        target_page_num = None
        all_table_rows = []
        global_header = None
        """        
        for page_idx in range(toc_page_idx + 1, total_pages):
            current_page = pdf.pages[page_idx]
            page_text = current_page.extract_text() or ""
            compressed_page_text = re.sub(r'\s+', '', page_text)
            if target_page_num is None:
                    if target_appendix in compressed_page_text and "有價證券" in compressed_page_text:
                        target_page_num = page_idx
                        if current_page.extract_tables():
                            print(f"📌 在第 {page_idx + 1} 頁找到真實的 {target_appendix} 表格起點。")
                        else:
                            print(f"📌 在第 {page_idx + 1} 頁找到 {target_appendix} 標題，繼續往後找表格...")
                            continue  # 標題頁沒有表格，跳到下一頁
            
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
        """
        for page_idx in range(toc_page_idx + 1, total_pages):
            current_page = pdf.pages[page_idx]
            page_text = current_page.extract_text() or ""
            compressed_page_text = re.sub(r'\s+', '', page_text)
            
            # 1. 判定並鎖定目標附表的起始頁面
            if target_page_num is None:
                if target_appendix in compressed_page_text and "有價證券" in compressed_page_text:
                    target_page_num = page_idx
                    print(f"📌 鎖定第 {page_idx + 1} 頁為 {target_appendix} 的目標頁面。")
            
            # 2. 開始處理目標頁面的資料
            if target_page_num is not None:
                # 如果已經走到後面頁數，且發現了下一個附表，此時才安全退出
                current_page_appendixes = set(appendix_pattern.findall(compressed_page_text))
                other_appendixes = current_page_appendixes - {target_appendix}
                
                if other_appendixes and page_idx > target_page_num:
                    print(f"🛑 偵測到下一個附表 {other_appendixes}，於第 {page_idx + 1} 頁停止擷取。")
                    break
                # --- 用不同策略抓取表格 ---
                # 策略 A：使用預設的格線偵測
                tables = current_page.extract_tables()
                # 策略 B：如果策略 A 失敗 (通常因為是無格線表格)，改用文字對齊偵測
                if not tables or len(tables) == 0:
                    text_settings = {
                        "vertical_strategy": "text",      # 依據文字垂直對齊線來切分欄位
                        "horizontal_strategy": "text",    # 依據文字換行切分列
                        "snap_tolerance": 3,
                    }
                    tables = current_page.extract_tables(table_settings=text_settings)
                # 如果兩種策略都全空，才代表這頁真的沒表格
                if not tables:
                    continue
                    
                # --- 開始解析抓到的表格資料 ---
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

        if _is_packed_format(df):
            print("   📦 偵測到 packed 格式，執行展開...")
            df = _expand_merged_rows(df)
        else:
            print("   📄 偵測到一般格式，清理換行符...")
            df = _clean_newlines(df)

        df = _resolve_ditto(df)

        # 把第一欄空值往前填充
        first_col = df.columns[0]
        df[first_col] = df[first_col].replace('', pd.NA).ffill()

        # 過濾重複表頭列
        header_keywords = ['股數', '單位數', '帳面金額', '持股比例', '公允價值', '股 數']
        df = df[~df.apply(
            lambda r: any(any(k in str(v) for k in header_keywords) for v in r.iloc[1:3]),
            axis=1
        )]

        df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)]
        df = df.reset_index(drop=True)

        print(f"🎉 擷取成功！總共抓取 {len(df)} 筆資料。")
        return df
    else:
        print("❌ 未能成功解析出結構化表格資料。")
        return None