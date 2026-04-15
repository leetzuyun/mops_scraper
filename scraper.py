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
}

# === 對應 AJAX 與 UI 頁 ===
ITEM_SPECS: Dict[str, Dict] = {
    "綜合損益表": {"ajax": "/mops/web/ajax_t163sb04", "page": "/mops/web/t163sb04", "required": ["TYPEK", "year", "season"], "optional": []},
    "資產負債表": {"ajax": "/mops/web/ajax_t163sb05", "page": "/mops/web/t163sb05", "required": ["TYPEK", "year", "season"], "optional": []},
    "現金流量表": {"ajax": "/mops/web/ajax_t163sb20", "page": "/mops/web/t163sb20", "required": ["TYPEK", "year", "season"], "optional": []},
    "會計師查核(核閱)報告": {"ajax": "/mops/web/ajax_t163sb14", "page": "/mops/web/t163sb14", "required": ["TYPEK", "year", "season"], "optional": ["co_id"]},
    "財務報告經監察人承認情形": {"ajax": "/mops/web/ajax_t56sb29_q3", "page": "/mops/web/t56sb29_q3", "required": ["TYPEK", "year", "season"], "optional": ["co_id"]},
    "財務報告更(補)正查詢作業": {"ajax": "/mops/web/ajax_t56sb31_q1", "page": "/mops/web/t56sb31_q1", "required": ["TYPEK"], "optional": ["year", "season", "co_id"]},
    "各產業EPS統計資訊": {"ajax": "/mops/web/ajax_t163sb19", "page": "/mops/web/t163sb19", "required": ["TYPEK", "year", "season"], "optional": ["industry"]},
}

DEFAULT_HOSTS = [
    "https://mopsov.twse.com.tw",  # 優先用舊站
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
    # 若環境有 TLS 檢測：
    #   1) 推薦設 REQUESTS_CA_BUNDLE 指向公司 CA 憑證
    #   2) 臨時要跳過驗證，可設 insecure=True
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
    vals = {
        "TYPEK": job.get("market", "sii"),
        "year": str(_to_roc(int(job["year"]))) if job.get("year") else None,
        "season": str(int(job.get("season", 4))) if job.get("season") else None,
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
    q = f"Q{job.get('season')}" if job.get("season") else "ALL"
    co = job.get("co_id") or "ALL"
    return f"{item}-{job.get('market','sii')}-{y}-{q}-{co}"


def _fetch_html(session: requests.Session, item: str, job: Dict) -> Tuple[str, str]:
    spec = ITEM_SPECS[item]
    p = _payload(item, job)
    last_err = None
    # 1) AJAX endpoint
    for host in DEFAULT_HOSTS:
        try:
            url = host + spec["ajax"]
            print(f"[AJAX] POST {url} data={p}")
            r = session.post(url, data=p, timeout=60)
            r.raise_for_status(); r.encoding = "utf-8"
            return r.text, host
        except Exception as e:
            last_err = e; print("  -> ajax fail:", e)
    # 2) UI
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
    # 另存CSV（Soupsieve 新語法）
    a = soup.select_one('a:-soup-contains("另存CSV")')
    if a and a.get("href"):
        return {"method":"GET","url": urljoin(base, a["href"]), "data": None}
    # <a>...bu_03.gif</a> (image for 另存 csv)
    a2 = soup.select_one('a:has(img[src*="bu_03.gif"])')
    if a2 and a2.get("href") and not a2.get("href").startswith("javascript"):
        return {"method":"GET","url": urljoin(base, a2["href"]), "data": None}
    # <input type=image>
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
    # /server-java/XXX 按鈕
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
    """
    解析 onclick 內 document.fm.X.value="..." 參數，回傳 dict。
    例: document.fm.SKEY.value="1";document.fm.CID.value="1584";...
    """
    if not onclick:
        return {}
    s = _html.unescape(onclick)  # &quot; -> "
    kv = {}
    for m in re.finditer(r'document\.fm\.(\w+)\.value="([^"]*)"', s):
        kv[m.group(1)] = m.group(2)
    return kv


def _table_to_df_robust(tbl) -> Optional[pd.DataFrame]:
    """
    先嘗試 pandas.read_html；失敗則用 BeautifulSoup 逐列剖析。
    針對「詳細資料」按鈕欄，會把 onclick 的 SKEY/CID/RID/DTYPE 抽成欄位。
    """
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
        if not tds:
            continue

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

    if not rows:
        return None
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
        print('[WARN] 找不到任何 <table>')
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

        if also_save_csv and csv_dir is not None and tag_for_csv:
            csv_dir.mkdir(parents=True, exist_ok=True)
            safe_sheet = re.sub(r'[\\/*?:\\[\\]]', '_', name)
            (csv_dir / f"{tag_for_csv}_T{idx+1}_{safe_sheet}.csv").write_text(
                df.to_csv(index=False), encoding="utf-8-sig"
            )


def run_jobs_newsite(
    jobs: List[Dict],
    out_dir: str = "financial_reports",
    download_dir: str = "downloads",
    insecure: bool = False
):
    """
    對每個 job（查詢條件）：
      1) 先抓 HTML（AJAX → UI）
      2) 嘗試官方下載（若像錯誤頁則略過）
      3) 把「該頁所有 <table>」寫成「一個 Excel」，多個 sheet
    Excel 檔名 = tag（例：資產負債表-sii-2025-Q4-ALL.xlsx）存到 out_dir。
    """
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

        # dbg = Path('debug_out'); dbg.mkdir(exist_ok=True)
        # (dbg / f"{tag}-result.html").write_text(html, encoding='utf-8')

        # 1) 嘗試官方下載（不成功就忽略）
        dl = _find_download_action(BeautifulSoup(html, 'lxml'), base)
        _ = _try_download(session, dl, tag, dl_dir)

        # 2) 寫一個「專屬 Excel」
        xlsx = out_base / f"{tag}.xlsx"
        with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
            prefix = f"{i:02d}-{item}"
            _write_all_tables_to_excel(html, writer, sheet_prefix=prefix)

        print(f"[OK] Excel → {xlsx.resolve()}")

    print(f"[DONE] 全部輸出完成，目錄：{out_base.resolve()}")
