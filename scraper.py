from __future__ import annotations
import time
import random
import re
import io
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urljoin
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

from lib.pdf_parser import extract_securities_table_from_bytes
from lib.excel_writer import COLUMN_SPECS, get_feature_key, save_records_to_excel

try:
    from urllib3.exceptions import InsecureRequestWarning
    import urllib3
    urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

# ==============================================================================
# 🎯 統一設定區 (鎖定舊版主機 mopsov)
# ==============================================================================
OLD_SITE_BASE = "https://mopsov.twse.com.tw"

ITEM_SPECS = {
    "財務報告書": {
        "ajax": "/mops/web/ajax_t57sb01_q1", 
        "required": ["co_id", "year"], 
    },
    "私募公告": {
        "ajax": "/mops/web/ajax_t116sb02",
        "required": ["TYPEK", "year"],
    }
}

# ==============================================================================
# 🛠️ 共用核心工具函數
# ==============================================================================
def _to_roc(year: int) -> int:
    return year - 1911 if year >= 1911 else year

def _get_standard_session(referer_url: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/x-www-form-urlencoded", 
        "Origin": "https://mopsov.twse.com.tw",
        "Referer": referer_url,
        "Connection": "keep-alive"
    })
    retries = Retry(
        total=5, 
        backoff_factor=2, # 改為 2，重試間隔會變為 2, 4, 8...秒，給伺服器更多喘息空間
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

def _request_with_retry(session: requests.Session, method: str, url: str, max_retries: int = 3, **kwargs) -> requests.Response:
    """針對 doc 主機特別設計的重試工具函數"""
    for attempt in range(max_retries):
        try:
            # 確保有設定超時，避免無限卡死
            if 'timeout' not in kwargs:
                kwargs['timeout'] = (30, 120)  # (連線超時, 讀取超時)
                
            r = session.request(method, url, **kwargs)
            r.raise_for_status()
            return r
        except (requests.exceptions.RequestException, Exception) as e:
            if attempt == max_retries - 1:
                print(f"   ❌ [嚴重錯誤] 已重試 {max_retries} 次仍失敗，放棄該目標。")
                raise e
            
            # 隨機退避時間，避免連續撞擊伺服器
            sleep_time = (attempt + 1) * 5 + random.uniform(2, 5)
            print(f"   ⚠️ 電子書系統回應異常 ({type(e).__name__})，將於 {sleep_time:.1f} 秒後進行第 {attempt + 1} 次重試...")
            time.sleep(sleep_time)

def _fetch_old_site(session: requests.Session, item: str, payload: Dict) -> str:
    ajax_url = OLD_SITE_BASE + ITEM_SPECS[item]["ajax"]
    print(f"🚀 正在請求舊版主機: {ajax_url}")
    r = _request_with_retry(
            session=session, 
            method="POST", 
            url=ajax_url, 
            data=payload, 
            max_retries=3, 
            timeout=(30, 60), 
            verify=False
        )
    r.encoding = "utf-8"
    return r.text

# ==============================================================================
# 📂 模組一：財務報告書下載與解析流程
# ==============================================================================
def _download_and_extract_table(session: requests.Session, html: str, base: str, job: Dict, dl_dir: Path) -> bool:
    soup = BeautifulSoup(html, 'lxml')
    raw_season = job.get("season")
    
    clean_s = "ALL"
    season_keywords = []
    if raw_season and str(raw_season).strip():
        clean_s = str(raw_season).upper().replace('Q', '')
        season_keywords = [f"第{clean_s}季", f"Q{clean_s}"]
        if clean_s == '1': season_keywords.append("第一季")
        elif clean_s == '2': season_keywords.append("第二季")
        elif clean_s == '3': season_keywords.append("第三季")
        elif clean_s == '4': season_keywords.append("第四季")

    a_tags = soup.find_all("a", href=re.compile(r"readfile2"))
    found_any = False
    
    for a_tag in a_tags:
        tr = a_tag.find_parent("tr")
        if not tr: continue
        row_text = tr.get_text(" ", strip=True)
        
        if season_keywords and not any(k in row_text for k in season_keywords): continue
        if "合併" not in row_text or "英文版" in row_text: continue
            
        href = a_tag.get("href", "")
        m = re.search(r'readfile2\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)', href)
        if m:
            kind, co_id, filename = m.groups()
            dl_url = "https://doc.twse.com.tw/server-java/t57sb01"
            data = {"step": "9", "kind": kind, "co_id": co_id, "filename": filename}
            
            try:
                # 🎯 重試點 2: 模擬點擊下載按鈕的中轉請求
                r_transit = _request_with_retry(session, "POST", dl_url, data=data, timeout=(30, 120), verify=False)
                
                pdf_bytes = b""
                if "<html" in r_transit.text.lower():
                    transit_soup = BeautifulSoup(r_transit.text, 'lxml')
                    pdf_link = transit_soup.find("a", href=re.compile(r"\.pdf$", re.I))
                    if pdf_link and pdf_link.get("href"):
                        real_pdf_url = urljoin("https://doc.twse.com.tw", pdf_link["href"])
                        
                        # 🎯 重試點 3: 真正下載 PDF 串流檔案（檔案通常很大，給予 180 秒讀取超時）
                        r_pdf = _request_with_retry(session, "GET", real_pdf_url, timeout=(30, 180), verify=False)
                        pdf_bytes = r_pdf.content
                else:
                    pdf_bytes = r_transit.content

                if pdf_bytes and extract_securities_table_from_bytes:
                    print(f" [處理中] 已將 PDF 載入記憶體，開始提取目標表格...")
                    df_table = extract_securities_table_from_bytes(pdf_bytes)
                    
                    if df_table is not None and not df_table.empty:
                        s_tag = f"Q{clean_s}" if raw_season and str(raw_season).strip() else "ALL"
                        out_excel_name = f"{co_id}_{job.get('year')}_{s_tag}_重大有價證券.xlsx"
                        out_path = dl_dir / out_excel_name
                        
                        df_table.to_excel(out_path, index=False, engine='openpyxl')
                        print(f" 🎉 [OK] 成功提取表格並儲存至: {out_path.name}")
                        found_any = True
                    else:
                        print(" ❌ [WARN] PDF 讀取成功，但找不到目標表格內容")
                        
            except Exception as e:
                print(f" ❌ [ERR] 處理 PDF 流程中斷: {e}")
                
    return found_any


def run_jobs_financial_reports(jobs: List[Dict], download_dir: str = "downloads"):
    dl_dir = Path(download_dir); dl_dir.mkdir(parents=True, exist_ok=True)
    referer_url = "https://mopsov.twse.com.tw/mops/web/t57sb01"
    session = _get_standard_session(referer_url=referer_url)

    for job in jobs:
        time.sleep(random.uniform(1.5, 3.5)) 
        roc_year = _to_roc(int(job["year"]))
        
        payload = {
            "encodeURIComponent": "1",
            "step": "1",
            "firstin": "1",
            "co_id": job["co_id"],
            "year": str(roc_year)
        }
        
        try:
            html = _fetch_old_site(session, "財務報告書", payload)
            
            match = re.search(r"https://doc.twse.com.tw/server-java/t57sb01?[^'\"]+", html)
            if not match:
                real_doc_url = f"https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&co_id={job['co_id']}&year={roc_year}&seamon=&mtype=A&"
            else:
                real_doc_url = match.group(0)
                
            # 🎯 重試點 1: 進入電子書系統索引頁面
            res_doc = _request_with_retry(session, "GET", real_doc_url, timeout=(30, 90), verify=False)
            res_doc.encoding = "big5"
            
            _download_and_extract_table(session, res_doc.text, "https://doc.twse.com.tw", job, dl_dir)
            
        except Exception as e:
            print(f" ❌ [{job.get('co_id')}] 最終抓取失敗: {e}")


# ==============================================================================
# 📂 模組二（精準過濾版）：多種類公告整合爬蟲與標的物去股化
# ==============================================================================

def crawl_multiple_announcements(year: int, typek: str, download_dir: str = "downloads"):
    """
    一次查詢多個公告種類，執行主旨篩選與標的物「去股化」，
    並將合格資料以「橫向字典」收集，最後交由 excel_writer 模組輸出整合表。
    """
    dl_dir = Path(download_dir)
    dl_dir.mkdir(parents=True, exist_ok=True)
    roc_year = _to_roc(year)
    
    TARGET_ANNOUNCEMENTS = {
        "取得或處分私募有價證券公告": "/mops/web/ajax_t116sb02",
        "取得或處分資產公告": "/mops/web/ajax_t67sb07"
    }
    
    INCLUDE_KEYWORDS = ["債", "固定收益", "有價證券"]
    # SECTION_KEYWORDS = ["有價證券","資產"]

    EXCLUDE_FIELD_MAP = {
        "取得或處分私募有價證券公告": ["標的物之名稱及性質"],
        "取得或處分資產公告":        ["證券名稱", "交易數量、每單位價格及交易總金額"],
    }
    EQUITY_KEYWORDS = ["普通股", "特別股", "優先股", "股票"]


    for category_name, ajax_path in TARGET_ANNOUNCEMENTS.items():
        if "t67sb07" in ajax_path:
            date1_key   = "DATE1"
            seq_no_key  = "SKEY"
            date1_pattern  = re.compile(r"DATE1\.value\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
            seq_no_pattern = re.compile(r"SKEY\.value\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
        else:
            date1_key   = "date1"
            seq_no_key  = "seq_no"
            date1_pattern  = re.compile(r"date1\.value\s*=\s*['\"]([^'\"]+)['\"]")
            seq_no_pattern = re.compile(r"seq_no\.value\s*=\s*['\"]([^'\"]+)['\"]")
        
        co_id_pattern  = re.compile(r"co_id\.value\s*=\s*['\"]([^'\"]+)['\"]")
        action_pattern = re.compile(r'action\s*=\s*["\']([^"\']+)["\']')

        print(f"\n====================================================================")
        print(f"🎬 開始處理類別：【{category_name}】")
        print(f"====================================================================")
        
        parent_page = ajax_path.replace("ajax_", "") 
        referer_url = f"https://mopsov.twse.com.tw{parent_page}"
        session = _get_standard_session(referer_url=referer_url)
        time.sleep(random.uniform(3.0, 5.0))
        
        payload_list = {
            "encodeURIComponent": "1",
            "step": "1",
            "firstin": "1",
            "TYPEK": typek,
            "year": str(roc_year),
            "co_id": ""
        }
        
        ITEM_SPECS[category_name] = {"ajax": ajax_path}
        
        try:
            html = _fetch_old_site(session, category_name, payload_list)
        except Exception as e:
            print(f" ❌ {category_name} 第一階段連線錯誤: {e}")
            session.close()
            continue
        soup = BeautifulSoup(html, "lxml")

        if "t67sb07" in ajax_path:
            all_report_sections = soup.find_all("table", class_="noBorder")
            matched_rows = []
            
            for section_table in all_report_sections:
                title_td = section_table.find(class_="reportName")
                if not title_td:
                    continue
                section_title = title_td.get_text(strip=True)
                
                if not any(k in section_title for k in INCLUDE_KEYWORDS):
                    print(f"   ⏭️ 跳過區塊：{section_title}")
                    continue
                
                print(f"   ✅ 命中區塊：{section_title}")
                
                next_noborder = section_table.find_next_sibling("table", class_="noBorder")
                all_hasborder = section_table.find_all_next("table", class_="hasBorder")
                
                for candidate in all_hasborder:
                    if next_noborder is None or candidate.find_next("table", class_="noBorder") == next_noborder or not candidate.find_next("table", class_="noBorder"):
                        section_rows = candidate.find_all("tr", class_=lambda x: x in ["even", "odd"])
                        matched_rows.extend(section_rows)
                        print(f"   → 該區塊 {len(section_rows)} 筆")
                        break
            
            rows = matched_rows  # ✅ 這行
        
        else:
            rows = soup.find_all("tr", class_=lambda x: x in ["even", "odd"])
        
        if not rows:
            print(f" 📭 找不到符合條件的區塊資料")
            session.close()
            continue

        all_extracted_records = []     
        for row_idx, row in enumerate(rows):
            tds = row.find_all("td")
            
            if len(tds) == 5:
                co_id_name = tds[0].get_text(strip=True) + " " + tds[1].get_text(strip=True)
                pub_date   = tds[2].get_text(strip=True)
                subject    = tds[3].get_text(strip=True)
                btn_td     = tds[4]
            elif len(tds) == 4:
                co_id_name = tds[0].get_text(strip=True)
                pub_date   = tds[1].get_text(strip=True)
                subject    = tds[2].get_text(strip=True)
                btn_td     = tds[3]
            else:
                continue
            
            if not any(k in subject for k in INCLUDE_KEYWORDS):
                continue
            
            btn = btn_td.find("input", type="button", onclick=True)
            if not btn:
                continue
            
            onclick_text = btn["onclick"]
            m_co_id  = co_id_pattern.search(onclick_text)
            m_date1  = date1_pattern.search(onclick_text)
            m_seq_no = seq_no_pattern.search(onclick_text)
            m_action = action_pattern.search(onclick_text)
            
            if row_idx < 3:
                print(f"   co_id={m_co_id and m_co_id.group(1)!r}, date1={m_date1 and m_date1.group(1)!r}, seq_no={m_seq_no and m_seq_no.group(1)!r}, action={m_action and m_action.group(1)!r}")
            
            if not (m_co_id and m_date1 and m_seq_no):
                if row_idx < 3:
                    print(f"   ❌ 跳過：pattern 抓不到")
                continue
            if row_idx < 3:
                print(f"   ✅ 通過所有篩選")

            co_id = m_co_id.group(1)
            date1 = m_date1.group(1)
            seq_no = m_seq_no.group(1)
            print(f"   onclick 原文: {onclick_text}")
            print(f"🔍 發現潛在目標！[{co_id_name}] 日期: {pub_date} | 主旨: {subject[:25]}...")
            detail_ajax = m_action.group(1) if m_action else ajax_path
            ITEM_SPECS[detail_ajax] = {"ajax": detail_ajax}
            if "t59sb03" in detail_ajax:
                exclude_fields = ["證券名稱", "交易數量、每單位價格及交易總金額"]
                payload_detail = {
                    "encodeURIComponent": "1",
                    "step": "2a",
                    "firstin": "1",
                    "TYPEK": typek,
                    "YEAR": str(roc_year),
                    "MONTH": "all",
                    "SDAY": "1",
                    "EDAY": "31",
                    "co_id": co_id,
                    "DATE1": date1,
                    "SKEY": seq_no,
                    "kind": "",
                    "id": "",
                    "colorchg": "",
                    "co_id1": "",
                    "co_id2": "",
                }
            elif "t67sb03" in detail_ajax:
                exclude_fields = ["標的物之名稱及性質"]
                payload_detail = {
                    "encodeURIComponent": "1",
                    "step": "2",
                    "firstin": "1",
                    "TYPEK": typek,
                    "YEAR": str(roc_year),
                    "co_id": co_id,
                    "DATE1": date1,
                    "SKEY": seq_no,
                }
            elif "t116sb02" in detail_ajax:
                exclude_fields = ["標的物之名稱及性質"]
                payload_detail = {
                    "encodeURIComponent": "1",
                    "step": "2",
                    "firstin": "1",
                    "co_id": co_id,
                    date1_key: date1,
                    seq_no_key: seq_no,
                    "TYPEK": typek,
                    "year": str(roc_year)
                }
            else:
                exclude_fields = EXCLUDE_FIELD_MAP.get(category_name, [])
                payload_detail = {
                    "encodeURIComponent": "1",
                    "step": "2",
                    "firstin": "1",
                    "co_id": co_id,
                    date1_key: date1,
                    seq_no_key: seq_no,
                    "TYPEK": typek,
                    "year": str(roc_year)
                }
            # if "t59sb03" in detail_ajax:
            #     exclude_fields = ["證券名稱", "交易數量、每單位價格及交易總金額"]
            # elif "t67sb03" in detail_ajax:
            #     exclude_fields = ["標的物之名稱及性質"]
            # elif "t116sb02" in detail_ajax:
            #     exclude_fields = ["標的物之名稱及性質"]
            # else:
            #     exclude_fields = EXCLUDE_FIELD_MAP.get(category_name, [])
                
            # if "t67sb03" in detail_ajax:
            #     payload_detail = {
            #         "encodeURIComponent": "1",
            #         "step": "2",           # ← 需要確認，先試 2
            #         "firstin": "1",
            #         "TYPEK": typek,
            #         "YEAR": str(roc_year),
            #         "co_id": co_id,
            #         "DATE1": date1,
            #         "SKEY": seq_no,
            #     }
            # elif "t67sb07" in ajax_path:
            #     payload_detail = {
            #         "encodeURIComponent": "1",
            #         "step": "2a",
            #         "firstin": "1",
            #         "TYPEK": typek,
            #         "YEAR": str(roc_year),
            #         "MONTH": "all",
            #         "SDAY": "1",
            #         "EDAY": "31",
            #         "co_id": co_id,
            #         "DATE1": date1,
            #         "SKEY": seq_no,
            #         "kind": "",
            #         "id": "",
            #         "colorchg": "",
            #         "co_id1": "",
            #         "co_id2": "",
            #     }
            # else:
            #     payload_detail = {
            #         "encodeURIComponent": "1",
            #         "step": "2",
            #         "firstin": "1",
            #         "co_id": co_id,
            #         date1_key:  date1,
            #         seq_no_key: seq_no,
            #         "TYPEK": typek,
            #         "year": str(roc_year)
            #     }
            
            try:
                detail_html = _fetch_old_site(session, detail_ajax, payload_detail)
                print(f"   --- DETAIL HTML 長度={len(detail_html)} ---")
                print(detail_html[:1000])

                tables = pd.read_html(io.StringIO(detail_html), flavor="lxml")

                print(f"   --- tables 數量: {len(tables)} ---")
                for i, t in enumerate(tables):
                    print(f"   table[{i}] shape={t.shape}, 前兩列:")
                    print(t.head(2).to_string())

                if tables:
                    df_detail = tables[-1].dropna(how="all").fillna("")
                    exclude_flag = False
                                        
                    current_record = {col: "" for col in COLUMN_SPECS[category_name]}
                    current_record["公司代號"] = co_id_name
                    current_record["主旨"] = subject
                    for idx, row_data in df_detail.iterrows():
                        cells = [str(cell).strip() for cell in row_data.values]
                        if len(cells) < 2:
                            continue
                        field_title = cells[0].replace(" ", "")
                        field_value = cells[1]
                        for ef in exclude_fields:
                            if ef.replace(" ", "") in field_title:
                                if any(k in field_value for k in EQUITY_KEYWORDS):
                                    exclude_flag = True
                                    break
                        if exclude_flag:
                            break
                        for col_name in COLUMN_SPECS[category_name]:
                            if col_name in ["公司代號", "主旨"]:
                                continue
                            feature_key = get_feature_key(col_name)
                            if feature_key in field_title:
                                current_record[col_name] = field_value
                                break
                                
                    if exclude_flag:
                        print(f"   [標的排除] 發現股權類資產，依規定放棄儲存。")
                        continue
                    
                    all_extracted_records.append(current_record)
                    print(f"   [核准擷取] 成功擷取資料。")
                    
            except Exception as e:
                print(f"   擷取詳細資料失敗 ({co_id}): {e}")               
            time.sleep(random.uniform(1.0, 2.0)) 
        session.close()
        save_records_to_excel(
            records=all_extracted_records, 
            category_name=category_name, 
            download_dir=dl_dir
        )
