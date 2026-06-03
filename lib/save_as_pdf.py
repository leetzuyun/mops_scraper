from pypdf import PdfReader, PdfWriter
import re
import io

def clean_cell_text(cell):
    if cell is None:
        return ""
    return str(cell).replace('\n', '|NEWLINE|').strip()

def extract_securities_pdf_pages(pdf_bytes: bytes) -> bytes:
    """
    回傳全新純淨版 PDF 的二進位資料 (bytes)。
    """
    target_title = "期末持有之重大有價證券"
    appendix_pattern = re.compile(r"(附表[一二三四五六七八九十]+)")
    
    target_appendix = None
    toc_page_idx = -1
    
    print("\n🚀 啟動 pypdf 高速文字串流掃描...")
    
    # 1. 初始化 PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    total_pages = len(reader.pages)
    
    # 2. 第一階段：掃描目錄區，找出目標附表編號
    for page_idx in range(total_pages):
        page = reader.pages[page_idx]
        text = page.extract_text() or ""
        # 壓縮空白字元，精準對齊字串
        compressed_text = re.sub(r'\s+', '', text)
        
        if target_title in compressed_text:
            title_idx = compressed_text.find(target_title)
            text_after_title = compressed_text[title_idx:]
            
            match = appendix_pattern.search(text_after_title)
            if match:
                target_appendix = match.group(1)
                toc_page_idx = page_idx
                print(f"🔍 [pypdf] 成功在第 {page_idx + 1} 頁(目錄區)定位：【{target_title}】 屬於 【{target_appendix}】")
                break
                
    if not target_appendix:
        print(f"❌ 找不到『{target_title}』對應的附表編號。")
        return None
        
    # 3. 第二階段：尋找該附表的真實起始頁面與結束頁面
    target_page_num = None
    end_page_num = total_pages  # 預設切到最後一頁
    
    for page_idx in range(toc_page_idx + 1, total_pages):
        current_page = reader.pages[page_idx]
        page_text = current_page.extract_text() or ""
        compressed_page_text = re.sub(r'\s+', '', page_text)
        
        # 判定起始頁：同時包含附表編號與關鍵字
        if target_page_num is None:
            if target_appendix in compressed_page_text and "有價證券" in compressed_page_text:
                target_page_num = page_idx
                print(f"📌 [pypdf] 鎖定第 {page_idx + 1} 頁為 {target_appendix} 的目標頁面起點。")
        
        # 判定結束頁：發現下一個附表標題就卡斷
        if target_page_num is not None:
            current_page_appendixes = set(appendix_pattern.findall(compressed_page_text))
            other_appendixes = current_page_appendixes - {target_appendix}
            
            if other_appendixes and page_idx > target_page_num:
                end_page_num = page_idx
                print(f"🛑 [pypdf] 偵測到下一個附表 {other_appendixes}，將於第 {page_idx + 1} 頁前截斷。")
                break

    # 4. 第三階段：精準頁面切片與導出
    if target_page_num is not None:
        print(f"✂️  準備切片：提取原 PDF 第 {target_page_num + 1} 頁 至 第 {end_page_num} 頁...")
        
        writer = PdfWriter()
        for i in range(target_page_num, end_page_num):
            writer.add_page(reader.pages[i])
            
        output_stream = io.BytesIO()
        writer.write(output_stream)
        return output_stream.getvalue()
    else:
        print("❌ 未能成功定位目標附表的頁面起點。")
        return None