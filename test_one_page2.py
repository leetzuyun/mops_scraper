# test_one_page.py (v10) – 把整頁所有 table 寫成同一個 .xlsx；每個 table 一個 sheet
# 仍保留：AJAX直抓、下載鈕/ server-java 下載、錯誤自動回退、--insecure/--host/--parameters/--force-table
# 檔名一律用查詢條件 (tag)；下載檔的副檔名依 Content-Type 決定，但檔名使用 tag

import re, sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
import pandas as pd
from bs4 import BeautifulSoup
from io import StringIO

try:
    from urllib3.exceptions import InsecureRequestWarning
    import urllib3
except Exception:
    InsecureRequestWarning = None
    urllib3 = None

DEFAULT_HOSTS = [
    "https://mops.twse.com.tw",
    "https://mopsc.twse.com.tw",
    "https://mopsov.twse.com.tw",
]

OUT_DIR = Path("debug_out"); OUT_DIR.mkdir(exist_ok=True)

CSV_BTN_SEL = 'input[value="另存CSV"], a:has-text("另存CSV")'
TABLE_FIRST_SEL = "table.hasBorder"
TABLE_FALLBACK_SEL = "table"

ERROR_KEYWORDS = ("公開資訊觀測站", "錯誤", "參數", "step", "傳入錯誤")

def to_roc(y: int) -> int:
    return y - 1911 if y >= 1911 else y

def make_session(insecure: bool):
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MOPS-Grab/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    s.verify = not insecure
    if insecure and urllib3 and InsecureRequestWarning:
        urllib3.disable_warnings(InsecureRequestWarning)
    return s

def fetch_by_parameters(session: requests.Session, parameters_url: str) -> tuple[str, str]:
    print("[GET]", parameters_url[:150] + ("..." if len(parameters_url) > 150 else ""))
    r = session.get(parameters_url, timeout=60)
    r.raise_for_status()
    r.encoding = "utf-8"
    base = f"{urlparse(parameters_url).scheme}://{urlparse(parameters_url).netloc}"
    return r.text, base

def fetch_by_post(session: requests.Session, typek: str, year: int, season: int, host_hint: str|None) -> tuple[str, str]:
    payload = {
        "encodeURIComponent": 1,
        "step": 1,
        "firstin": 1,
        "off": 1,
        "TYPEK": typek,
        "year": str(to_roc(year)),
        "season": str(int(season)),
    }
    hosts = [host_hint] + [h for h in DEFAULT_HOSTS if h != host_hint] if host_hint else DEFAULT_HOSTS
    last_err = None
    for host in hosts:
        try:
            url = host + "/mops/web/ajax_t163sb05"
            print("[POST]", url, payload, "| verify=", session.verify)
            r = session.post(url, data=payload, timeout=60)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text, host
        except Exception as e:
            last_err = e
            print("  -> fail on", host, ":", e)
    raise RuntimeError(f"All hosts failed; last error: {last_err}")

def _collect_form_inputs(form: BeautifulSoup) -> dict:
    data = {}
    for inp in form.find_all("input"):
        n = inp.get("name")
        if not n: continue
        t = (inp.get("type") or "").lower()
        if t in ("submit", "button", "image"):
            continue
        data[n] = inp.get("value","")
    return data

def try_find_download_action(soup: BeautifulSoup, base: str):
    # (1) 另存 CSV 的 <a>
    a = soup.select_one('a:-soup-contains("另存CSV")')    
    if a and a.get("href"):
        return {"method": "GET", "url": urljoin(base, a["href"]), "data": None}
    # (2) <a>...bu_03.gif</a>
    a2 = soup.select_one('a:has(img[src*="bu_03.gif"])')
    if a2 and a2.get("href") and not a2.get("href").startswith("javascript"):
        return {"method": "GET", "url": urljoin(base, a2["href"]), "data": None}
    # (3) <input type=image src=bu_03.gif>
    img_input = soup.select_one('input[type="image"][src*="bu_03.gif"]')
    if img_input:
        form = img_input.find_parent("form")
        if form and form.get("action"):
            action = urljoin(base, form["action"])
            data = _collect_form_inputs(form)
            name = img_input.get("name")
            if name:
                data[f"{name}.x"] = "10"; data[f"{name}.y"] = "10"
            return {"method": (form.get("method","POST").upper()), "url": action, "data": data}
    # (4) /server-java/XXXX
    btn = soup.find("button", attrs={"onclick": re.compile(r"action=['\"]/server-java/[^'\"]+['\"];submit\(\)")})
    if btn:
        m = re.search(r"action=/server-java/[^'\"]+['\"]", btn.get("onclick",""))
        if m:
            action_path = m.group(0).split("=",1)[1].strip("'\"")
            form = btn.find_parent("form")
            if form:
                action = urljoin(base, action_path)
                data = _collect_form_inputs(form)
                return {"method": (form.get("method","POST").upper()), "url": action, "data": data}
            else:
                return {"method": "GET", "url": urljoin(base, action_path), "data": None}
    # (5) 兜底：任何 FileDownLoad/Download 類連結
    link = soup.find("a", href=re.compile(r"FileDownLoad|Download", re.I))
    if link and link.get("href"):
        return {"method": "GET", "url": urljoin(base, link["href"]), "data": None}
    return None

def looks_like_error(content_bytes: bytes, headers: dict) -> bool:
    ctype = headers.get("Content-Type","").lower()
    if ("csv" in ctype) or ("excel" in ctype) or ("sheet" in ctype):
        return False
    text = ""
    try:
        text = content_bytes.decode("utf-8", errors="ignore")
    except Exception:
        pass
    if any(k in text for k in ("<html",)) and len(content_bytes) < 8_000:
        return True
    if any(k in text for k in ERROR_KEYWORDS):
        return True
    return False

def save_download(session: requests.Session, dl, tag: str, skip_download: bool):
    """下載官方檔案（若 skip_download=True 則直接返回 None）"""
    if skip_download:
        return None
    method, url, data = dl["method"], dl["url"], dl["data"]
    print(f"[DL] {method} {url} data={bool(data)} | verify={session.verify}")
    r = session.post(url, data=data, timeout=90, stream=True) if method == "POST" else \
        session.get(url, params=data, timeout=90, stream=True)
    r.raise_for_status()
    raw = b"".join(r.iter_content(1024*64))
    if looks_like_error(raw, r.headers):
        print("[DL] 回應不像 CSV/XLS（或疑似錯誤訊息）→ 回退表格解析")
        return None
    # 檔名一律使用查詢條件（忽略網站檔名）；只根據 MIME 選副檔名
    ctype = r.headers.get("Content-Type","").lower()
    ext = ".csv" if "csv" in ctype else (".xls" if "excel" in ctype or "sheet" in ctype else ".bin")
    fn = f"{tag}{ext}"
    out = OUT_DIR / fn
    with open(out, "wb") as f:
        f.write(raw)
    print("[OK] saved:", out.resolve())
    return out

# ---------- 新增：把整頁所有表格寫進同一個 xlsx，每表一個 sheet ----------
def _sheet_name_from_table(soup_table, idx: int) -> str:
    # 就近找上一個 h1~h4 當標題；否則用第一欄名；最後退回 "Table{n}"
    heading = soup_table.find_previous(["h1", "h2", "h3", "h4"])
    if heading and heading.get_text(strip=True):
        name = heading.get_text(strip=True)
    else:
        # 嘗試第一個 header cell
        th = soup_table.find("th")
        name = th.get_text(strip=True) if th and th.get_text(strip=True) else f"Table{idx+1}"
    # 清理非法字元與長度
    name = re.sub(r"[\\/*?:\\[\\]]", "_", name)  # Excel 禁字
    name = name[:31] if name else f"Table{idx+1}"
    return name or f"Table{idx+1}"

def export_tables_to_excel(html: str, tag: str):
    """搜集整頁所有表格（優先 hasBorder），逐表清理，寫入同一個 xlsx（每表一個 sheet）"""
    soup = BeautifulSoup(html, "lxml")
    tables = soup.select(TABLE_FIRST_SEL)
    if not tables:
        tables = soup.select(TABLE_FALLBACK_SEL)
    if not tables:
        print("[WARN] 找不到任何 <table>；已輸出 result.html 供檢視")
        return None

    # 逐表讀取與清理
    dfs = []
    names = []

    for idx, t in enumerate(tables):
        try:
            html_snippet = StringIO(str(t))
            df_list = pd.read_html(html_snippet)
        except ValueError:
            continue
        if not df_list:
            continue
        df = df_list[0]
        # 清理：去空列；若第一列與欄名相同，去掉第一列
        import numpy as np
        df = df.replace(r"^\s*$", np.nan, regex=True).dropna(how="all")
        if len(df) > 1 and list(df.columns) == list(df.iloc[0].fillna("").tolist()):
            df = df.iloc[1:]
        # 產生唯一 sheet 名
        base = _sheet_name_from_table(t, idx)
        name = base
        used = set(names)
        suffix = 2
        while name in used:
            left = 31 - len(f"_{suffix}")
            name = (base[:left] if left > 0 else base[:31]) + f"_{suffix}"
            suffix += 1
        dfs.append(df)
        names.append(name)

    if not dfs:
        print("[WARN] 沒有可寫入的表格")
        return None

    # 寫入同一個 xlsx
    xlsx = OUT_DIR / f"{tag}.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        for df, name in zip(dfs, names):
            df.to_excel(writer, index=False, sheet_name=name)
    print("[OK] excel →", xlsx.resolve())
    return xlsx
# --------------------------------------------------------------------

def export_tables_csv_legacy(html: str, tag: str):
    """若你還想保留舊的一張 CSV（合併全部表格），可用這個；預設不再呼叫。"""
    soup = BeautifulSoup(html, "lxml")
    tables = soup.select(TABLE_FIRST_SEL) or soup.select(TABLE_FALLBACK_SEL)
    dfs = []
    for t in tables:
        try:              
            dfs_for_one = pd.read_html(StringIO(str(t)))
            dfs += dfs_for_one
        except ValueError:
            pass
    if not dfs:
        print("[WARN] 沒抓到任何 <table>；已輸出 result.html 供檢視")
        return None
    import numpy as np
    df = pd.concat(dfs, ignore_index=True)
    df = df.replace(r"^\s*$", np.nan, regex=True).dropna(how="all")
    if len(df) > 1 and list(df.columns) == list(df.iloc[0].fillna("").tolist()):
        df = df.iloc[1:]
    out = OUT_DIR / f"{tag}.csv"
    df.to_csv(out, index=False)
    print("[OK] csv →", out.resolve())
    return out

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--parameters", help="F12 抓到的 ajax_t163sb05?parameters=... 直接貼")
    ap.add_argument("--typek", help="sii/otc/rotc/pub")
    ap.add_argument("--year", type=int)
    ap.add_argument("--season", type=int)
    ap.add_argument("--insecure", action="store_true", help="跳過 TLS 驗證（開發測試用）")
    ap.add_argument("--host", help="強制指定主機（mops.twse.com.tw / mopsc.twse.com.tw / mopsov.twse.com.tw）")
    ap.add_argument("--force-table", dest="force_table", action="store_true", help="略過下載鈕，直接表格→Excel")
    ap.add_argument("--no-download", action="store_true", help="不要儲存官方下載檔（只產出 Excel）")
    args = ap.parse_args()

    session = make_session(args.insecure)

    if args.parameters:
        html, base = fetch_by_parameters(session, args.parameters.strip())
        tag = "資產負債表-parameters"
    else:
        if not (args.typek and args.year and args.season):
            print("請用 --parameters 或 --typek/--year/--season 指定其一"); sys.exit(1)
        host_hint = None
        if args.host:
            hh = args.host.strip().lower()
            if not hh.startswith("http"): hh = "https://" + hh
            host_hint = hh
        html, base = fetch_by_post(session, args.typek, args.year, args.season, host_hint=host_hint)
        # 你也可改成含公司代號：資產負債表-sii-2025-Q4-2330
        tag = f"資產負債表-{args.typek}-{args.year}-Q{args.season}"

    # 存下 HTML 供檢視
    (OUT_DIR/"result.html").write_text(html, encoding="utf-8")

    # ① 若要走官方下載（非必須；你要的 Excel 會在 ③ 產出）
    if not args.force_table:
        soup = BeautifulSoup(html, "lxml")
        dl = try_find_download_action(soup, base)
        _ = save_download(session, dl, tag, skip_download=args.no_download) if dl else None

    # ② 無論是否下載成功，都輸出一份 Excel：整頁所有表格 → 同一檔、不同 sheet
    export_tables_to_excel(html, tag)

if __name__ == "__main__":
    main()