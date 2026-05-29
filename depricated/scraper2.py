from __future__ import annotations
import re
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
import html as _html
import numpy as np

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    from urllib3.exceptions import InsecureRequestWarning
    import urllib3
except Exception:
    InsecureRequestWarning = None
    urllib3 = None


TARGET_ITEMS = {
    "綜合損益表": "#/web/t163sb04",
    "資產負債表": "#/web/t163sb05",
    "現金流量表": "#/web/t163sb20",
    "會計師查核(核閱)報告": "#/web/t163sb14",
    "財務報告經監察人承認情形": "#/web/t56sb29_q3",
    "財務報告更(補)正查詢作業": "#/web/t56sb31_q1",
    "各產業EPS統計資訊": "#/web/t163sb19",
    "財務報告書": "#/web/t57sb01_q1",  
}

ITEM_SPECS: Dict[str, Dict] = {
    "綜合損益表": {"ajax": "/mops/web/ajax_t163sb04", "page": "/mops/web/t163sb04", "required": ["TYPEK", "year", "season"], "optional": []},
    "資產負債表": {"ajax": "/mops/web/ajax_t163sb05", "page": "/mops/web/t163sb05", "required": ["TYPEK", "year", "season"], "optional": []},
    "現金流量表": {"ajax": "/mops/web/ajax_t163sb20", "page": "/mops/web/t163sb20", "required": ["TYPEK", "year", "season"], "optional": []},
    "會計師查核(核閱)報告": {"ajax": "/mops/web/ajax_t163sb14", "page": "/mops/web/t163sb14", "required": ["TYPEK", "year", "season"], "optional": ["co_id"]},
    "財務報告經監察人承認情形": {"ajax": "/mops/web/ajax_t56sb29_q3", "page": "/mops/web/t56sb29_q3", "required": ["TYPEK", "year", "season"], "optional": ["co_id"]},
    "財務報告更(補)正查詢作業": {"ajax": "/mops/web/ajax_t56sb31_q1", "page": "/mops/web/t56sb31_q1", "required": ["TYPEK"], "optional": ["year", "season", "co_id"]},
    "各產業EPS統計資訊": {"ajax": "/mops/web/ajax_t163sb19", "page": "/mops/web/t163sb19", "required": ["TYPEK", "year", "season"], "optional": ["industry"]},
    "財務報告書": {"ajax": "/mops/web/ajax_t57sb01_q1", "page": "/mops/web/t57sb01_q1", "required": ["co_id", "year"], "optional": []}, 
}

DEFAULT_HOSTS = [
    "https://mopsov.twse.com.tw",  
    "https://mopsc.twse.com.tw",
    "https://mops.twse.com.tw",
]


def _to_roc(year: int) -> int:
    return year - 1911 if year >= 1911 else year


def _make_session(insecure: bool = False) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MOPS-Scraper/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    if insecure:
        try:
            from urllib3.exceptions import InsecureRequestWarning
            import urllib3
            urllib3.disable_warnings(InsecureRequestWarning)
        except Exception:
            pass
        s.verify = False
    return s


def _payload(item: str, job: Dict) -> Dict[str, str]:
    spec = ITEM_SPECS[item]
    p = {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1"}
    
    raw_s = job.get("season")
    clean_s = str(raw_s).upper().replace('Q', '') if raw_s else None
    
    vals = {
        "TYPEK": job.get("market", "sii") if item != "財務報告書" else None,
        "year": str(_to_roc(int(job["year"]))) if job.get("year") else None,
        "season": clean_s,
        "co_id": job.get("co_id"),
        "industry": job.get("industry"),
    }
    for k in spec["required"]:
        if not vals.get(k):
            raise ValueError(f"{item} 缺少必要欄位：{k}")
        p[k] = vals[k]
    for k in spec["optional"]:
        if vals.get(k) is not None:
            p[k] = vals[k]
    return p


def _tag(item: str, job: Dict) -> str:
    y = str(job.get("year", "NA"))
    s = str(job.get("season", "")).upper()
    q = f"Q{s.replace('Q', '')}" if s else "ALL"
    co = job.get("co_id") or "ALL"
    return f"{item}-{job.get('market','sii')}-{y}-{q}-{co}"


def _fetch_html(session: requests.Session, item: str, job: Dict) -> Tuple[str, str]:
    spec = ITEM_SPECS[item]
    p = _payload(item, job)
    last_err = None
    
    for host in DEFAULT_HOSTS:
        try:
            url = host + spec["ajax"]
            print(f"[AJAX] POST {url} data={p}")
            r = session.post(url, data=p, timeout=60)
            r.raise_for_status(); r.encoding = "utf-8"
            return r.text, host
        except Exception as e:
            last_err = e; print("  -> ajax fail:", e)
            
    for host in DEFAULT_HOSTS:
        try:
            url = host + spec["page"]
            print(f"[PAGE] GET  {url}")
            r = session.get(url, timeout=60)
            r.raise_for_status(); r.encoding = "utf-8"
            return r.text, host
        except Exception as e:
            last_err = e; print("  -> page fail:", e)
    raise RuntimeError(f"{item}: 取得頁面失敗：{last_err}")


def _collect_form_inputs(form: BeautifulSoup) -> Dict[str,str]:
    data = {}
    for inp in form.find_all("input"):
        n = inp.get("name");  t = (inp.get("type") or '').lower()
        if not n or t in ("submit","button","image"): continue
        data[n] = inp.get("value","")
    return data


def _find_download_action(soup: BeautifulSoup, base: str):
    a = soup.select_one('a:-soup-contains("另存CSV")')
    if a and a.get("href"):
        return {"method":"GET","url": urljoin(base, a["href"]), "data": None}
    
    a2 = soup.select_one('a:has(img[src*="bu_03.gif"])')
    if a2 and a2.get("href") and not a2.get("href").startswith("javascript"):
        return {"method":"GET","url": urljoin(base, a2["href"]), "data": None}
        
    img = soup.select_one('input[type="image"][src*="bu_03.gif"]')
    if img:
        form = img.find_parent("form")
        if form and form.get("action"):
            data = _collect_form_inputs(form)
            name = img.get("name")
            if name:
                data[f"{name}.x"], data[f"{name}.y"] = "10", "10"
            return {"method":(form.get("method","POST").upper()),
                    "url": urljoin(base, form["action"]), "data": data}
                    
    btn = soup.find("button", attrs={"onclick": re.compile(r"action=['\"]/server-java/[^'\"\"]+['\"];submit\(\)")})
    if btn:
        m = re.search(r"action=/server-java/[^'\"\"]+['\"][ ]*", btn.get("onclick",""))
        if m:
            action_path = m.group(0).split("=",1)[1].strip("'\" ")
            form = btn.find_parent("form")
            if form:
                data = _collect_form_inputs(form)
                return {"method":(form.get("method","POST").upper()),
                        "url": urljoin(base, action_path), "data": data}
            else:
                return {"method":"GET", "url": urljoin(base, action_path), "data": None}
                
    link = soup.find("a", href=re.compile(r"FileDownLoad|Download", re.I))
    if link and link.get("href"):
        return {"method":"GET", "url": urljoin(base, link["href"]), "data": None}
    return None


def _looks_like_error(content: bytes, headers: Dict[str,str]) -> bool:
    ctype = (headers.get("Content-Type") or '').lower()
    if any(k in ctype for k in ("csv","excel","sheet")):
        return False
    txt = ''
    try:
        txt = content.decode('utf-8', errors='ignore')
    except Exception:
        pass
    if len(content) < 8000 and "<html" in txt.lower():
        return True
    for k in ("公開資訊觀測站","錯誤","參數","step","傳入錯誤"):
        if k in txt: return True
    return False


def _try_download(session: requests.Session, dl: Optional[Dict], tag: str, download_dir: Path) -> Optional[Path]:
    if not dl: return None
    m, url, data = dl["method"], dl["url"], dl["data"]
    print(f"[DL] {m} {url} data={bool(data)}")
    r = session.post(url, data=data, timeout=90, stream=True) if m == 'POST' else \
        session.get(url, params=data, timeout=90, stream=True)
    r.raise_for_status()
    raw = b"".join(r.iter_content(65536))
    if _looks_like_error(raw, r.headers):
        print("[DL] 看起來不是資料檔，改用表格解析")
        return None
    ctype = (r.headers.get('Content-Type') or '').lower()
    ext = '.csv' if 'csv' in ctype else ('.xls' if ('excel' in ctype or 'sheet' in ctype) else '.bin')
    out = download_dir / f"{tag}{ext}"
    out.write_bytes(raw)
    print("[OK] saved:", out)
    return out


def _sheet_name_from_table(tbl, idx: int) -> str:
    hd = tbl.find_previous(["h1","h2","h3","h4"])
    if hd and hd.get_text(strip=True):
        name = hd.get_text(strip=True)
    else:
        th = tbl.find("th")
        name = th.get_text(strip=True) if th and th.get_text(strip=True) else f"Table{idx+1}"
    name = re.sub(r"[\\/*?:\[\]]","_", name)[:31] or f"Table{idx+1}"
    return name


def _cell_text(el) -> str:
    return el.get_text(separator=" ", strip=True)


def _parse_onclick_kv(onclick: str) -> dict:
    if not onclick: return {}
    s = _html.unescape(onclick)
    kv = {}
    for m in re.finditer(r'document\.fm\.(\w+)\.value="([^"]*)"', s):
        kv[m.group(1)] = m.group(2)
    return kv


def _table_to_df_robust(tbl) -> Optional[pd.DataFrame]:
    try:
        dfs = pd.read_html(StringIO(str(tbl)))
        if dfs:
            df = dfs[0]
            df = df.replace(r"^\s*$", np.nan, regex=True).dropna(how="all")
            if len(df) > 1 and list(df.columns) == list(df.iloc[0].fillna("").tolist()):
                df = df.iloc[1:]
            return df
    except ValueError:
        pass

    rows = []
    headers = []
    ths = tbl.find_all("th")
    if ths:
        headers = [_cell_text(th) for th in ths]

    for tr in tbl.find_all("tr"):
        tds = tr.find_all("td")
        if not tds: continue

        row = []
        detail_kv = {}
        for td in tds:
            inp = td.find("input", attrs={"type": "button"})
            if inp and (inp.get("value") or "").strip() in ("詳細資料", "明細", "Details"):
                detail_kv = _parse_onclick_kv(inp.get("onclick", ""))
                row.append((inp.get("value") or "").strip())
            else:
                row.append(_cell_text(td))

        if not headers:
            headers = [f"欄位{i+1}" for i in range(len(row))]

        for key in ("SKEY", "CID", "RID", "DTYPE"):
            if key in detail_kv:
                headers += [key] if key not in headers else []
        while len(row) < len(headers):
            row.append(None)
        for k, v in detail_kv.items():
            if k in headers:
                idx = headers.index(k)
                if idx >= len(row):
                    row += [None] * (idx - len(row) + 1)
                row[idx] = v

        rows.append(row)

    if not rows: return None
    max_len = max(len(r) for r in rows)
    if len(headers) < max_len:
        headers += [f"欄位{j+1}" for j in range(len(headers), max_len)]
    norm_rows = [r + [None] * (max_len - len(r)) for r in rows]

    df = pd.DataFrame(norm_rows, columns=headers)
    df = df.dropna(how="all")
    return df if not df.empty else None


def _write_all_tables_to_excel(html: str, writer: pd.ExcelWriter, sheet_prefix: str,
                               also_save_csv: bool = False, csv_dir: Optional[Path] = None,
                               tag_for_csv: Optional[str] = None):
    soup = BeautifulSoup(html, 'lxml')
    tables = soup.select('table.hasBorder') or soup.select('table')
    if not tables:
        return

    used = set()
    for idx, t in enumerate(tables):
        df = _table_to_df_robust(t)
        if df is None or df.empty:
            continue
        base = f"{sheet_prefix}-{_sheet_name_from_table(t, idx)}"
        name = base[:31]
        sfx = 2
        while name in used:
            left = 31 - len(f"_{sfx}")
            name = (base[:left] if left>0 else base[:31]) + f"_{sfx}"
            sfx += 1
        used.add(name)

        df.to_excel(writer, index=False, sheet_name=name)


def _download_financial_report_pdfs(session: requests.Session, html: str, base: str, job: Dict, dl_dir: Path) -> bool:
    debug_html_path = Path("debug_doc_response.html")
    debug_html_path.write_text(html, encoding="utf-8")
    print(f"[DEBUG] 真正的財報列表網頁已存至: {debug_html_path.resolve()}")

    soup = BeautifulSoup(html, 'lxml')
    raw_season = job.get("season")
    
    clean_s = "ALL"
    season_keywords = []
    if raw_season:
        clean_s = str(raw_season).upper().replace('Q', '')
        if clean_s == '1': season_keywords = ["第一季", "第1季", "Q1"]
        elif clean_s == '2': season_keywords = ["第二季", "第2季", "Q2"]
        elif clean_s == '3': season_keywords = ["第三季", "第3季", "Q3"]
        elif clean_s == '4': season_keywords = ["第四季", "第4季", "Q4"]
        
    print(f"[DEBUG] 設定的目標季別關鍵字清單: {season_keywords}")

    a_tags = soup.find_all("a", href=re.compile(r"readfile2"))
    print(f"[DEBUG] 網頁內總共找到包含 'readfile2' 的超連結數量: {len(a_tags)}")

    found_any = False
    
    for idx, a_tag in enumerate(a_tags, 1):
        tr = a_tag.find_parent("tr")
        if not tr:
            continue
            
        row_text = tr.get_text(" ", strip=True)
        print(f"\n--- [檢查第 {idx} 個連結] ---")
        print(f"   該列文字: \"{row_text}\"")
        
        # 季別彈性比對
        if season_keywords and not any(k in row_text for k in season_keywords):
            print(f"   ❌ 遭過濾：未包含季別關鍵字 {season_keywords}")
            continue
            
        # 合併報表檢查
        if "合併" not in row_text:
            print("   ❌ 遭過濾：未包含 '合併' 關鍵字")
            continue
        if "英文版" in row_text:
            print("   ❌ 遭過濾：此列為英文版")
            continue
            
        print("   ✅ 符合條件！開始請求中繼頁面...")
        href = a_tag.get("href", "")
        m = re.search(r'readfile2\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)', href)
        if m:
            kind, co_id, filename = m.groups()
            dl_url = urljoin(base, "/server-java/t57sb01")
            
            data = {
                "step": "9",
                "kind": kind,
                "co_id": co_id,
                "filename": filename
            }
            
            try:
                # 1. 先 POST 取得中繼頁面
                r_transit = session.post(dl_url, data=data, timeout=90)
                r_transit.raise_for_status()
                r_transit.encoding = "big5" 
                
                # 2. 檢查回傳的是否為 HTML 中繼頁
                if "<html" in r_transit.text.lower():
                    transit_soup = BeautifulSoup(r_transit.text, 'lxml')
                    pdf_link = transit_soup.find("a", href=re.compile(r"\.pdf$", re.I))
                    
                    if pdf_link and pdf_link.get("href"):
                        real_pdf_url = urljoin(base, pdf_link["href"])
                        print(f"   -> 取得真實 PDF 網址: {real_pdf_url}")
                        
                        pdf_headers = {
                            "Referer": base,
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                        }
                        
                        max_retries = 3
                        for attempt in range(1, max_retries + 1):
                            try:
                                print(f"   -> 開始下載 PDF (第 {attempt}/{max_retries} 次嘗試)...")
                                r_pdf = session.get(real_pdf_url, headers=pdf_headers, timeout=120, stream=True)
                                r_pdf.raise_for_status()
                                
                                s_tag = f"Q{clean_s}" if raw_season else "ALL"
                                out_name = f"{co_id}_{job.get('year')}_{s_tag}_{filename}"
                                if not out_name.lower().endswith(".pdf"):
                                    out_name += ".pdf"
                                out_path = dl_dir / out_name
                                
                                with open(out_path, "wb") as f:
                                    for chunk in r_pdf.iter_content(chunk_size=65536):
                                        if chunk:
                                            f.write(chunk)
                                
                                print(f"   🎉 [OK] 成功下載並儲存: {out_path.name}")
                                found_any = True
                                break 
                                
                            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as ce:
                                print(f"   ⚠️ 第 {attempt} 次下載逾時: {ce}")
                                if attempt == max_retries:
                                    raise ce
                                import time
                                time.sleep(3)
                        
                        if found_any:
                            continue # 繼續檢查下一個 a 標籤 (萬一有複數符合條件的檔案)
                            
                    else:
                        print("   ❌ [ERR] 在中繼頁面中找不到 PDF 連結！")
                        continue
                else:
                    # 如果系統直接回傳了檔案
                    s_tag = f"Q{clean_s}" if raw_season else "ALL"
                    out_name = f"{co_id}_{job.get('year')}_{s_tag}_{filename}"
                    if not out_name.lower().endswith(".pdf"):
                        out_name += ".pdf"
                    out_path = dl_dir / out_name
                    out_path.write_bytes(r_transit.content)
                    print(f"   🎉 [OK] 成功下載並儲存: {out_path.name}")
                    found_any = True
                    
            except Exception as e:
                print(f"   ❌ [ERR] 下載失敗: {e}")
                
    return found_any


def run_jobs_newsite(
    jobs: List[Dict],
    out_dir: str = "financial_reports",
    download_dir: str = "downloads",
    insecure: bool = False
):
    out_base = Path(out_dir); out_base.mkdir(parents=True, exist_ok=True)
    dl_dir = Path(download_dir); dl_dir.mkdir(parents=True, exist_ok=True)
    session = _make_session(insecure=insecure)

    for i, job in enumerate(jobs, 1):
        item = job.get('item')
        if item not in ITEM_SPECS:
            print(f"[SKIP] 不支援的項目：{item}")
            continue

        tag = _tag(item, job)
        html, base = _fetch_html(session, item, job)

        if item == "財務報告書":
            # 從過渡頁面中把隱藏的真正的 doc.twse.com.tw 網址抓出來
            match = re.search(r"https://doc.twse.com.tw/server-java/t57sb01?[^'\"]+", html)
            if not match:
                print("[WARN] 快顯分頁中找不到 doc.twse.com.tw 網址，嘗試自動拼接備用參數...")
                roc_year = _to_roc(int(job["year"]))
                real_doc_url = f"https://doc.twse.com.tw/server-java/t57sb01?step=1&colorchg=1&co_id={job['co_id']}&year={roc_year}&seamon=&mtype=A&"
            else:
                real_doc_url = match.group(0)
                
            print(f"[REDIRECT] 成功攔截快顯視窗！正在進入真實文件系統:\n -> {real_doc_url}")
            
            try:
                # 前往真正的電子書列表網頁
                res_doc = session.get(real_doc_url, timeout=60)
                res_doc.raise_for_status()
                # 台灣早期政府系統多採用大五碼 (Big5)
                res_doc.encoding = res_doc.apparent_encoding if res_doc.apparent_encoding else "big5"
                doc_html = res_doc.text
                # 丟給下載器解析與下載 PDF
                success = _download_financial_report_pdfs(session, doc_html, "https://doc.twse.com.tw", job, dl_dir)
                if not success:
                    print("[WARN] 沒有找到符合條件的 PDF (合併財報 + 指定季別)")
                else:
                    print(f"[OK] {tag} 下載任務完成。")
            except Exception as e:
                print(f"[ERR] 進入真實電子書資料庫失敗: {e}")
            continue

        dl = _find_download_action(BeautifulSoup(html, 'lxml'), base)
        _ = _try_download(session, dl, tag, dl_dir)

        xlsx = out_base / f"{tag}.xlsx"
        with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
            prefix = f"{i:02d}-{item}"
            _write_all_tables_to_excel(html, writer, sheet_prefix=prefix)

        print(f"[OK] Excel → {xlsx.resolve()}")

    print(f"[DONE] 全部輸出完成，目錄：{out_base.resolve()}")


# if __name__ == "__main__":
#     sample_jobs = [
#         {
#             "item": "財務報告書",
#             "co_id": "2330",
#             "year": 2025,
#             "season": "Q1"  
#         }
#     ]
    
#     run_jobs_newsite(sample_jobs, insecure=True)