import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from scraper import run_jobs_newsite, TARGET_ITEMS, ITEM_SPECS

MARKETS = [("上市","sii"),("上櫃","otc"),("興櫃","rotc"),("公開發行","pub")]
ITEMS = list(TARGET_ITEMS.keys())

jobs = []

FIELD_ROWS = {}

def _set_row_visible(row_widgets, visible: bool):
    for w in row_widgets:
        if visible:
            w.grid()
        else:
            w.grid_remove()

def refresh_form_by_item(*_):
    item = item_var.get().strip()
    spec = ITEM_SPECS.get(item, {"required": ["TYPEK","year","season"], "optional": ["co_id"]})
    req = set(spec.get("required", []))
    opt = set(spec.get("optional", []))

    _set_row_visible(FIELD_ROWS['year'], ('year' in req) or ('year' in opt))
    _set_row_visible(FIELD_ROWS['season'], ('season' in req) or ('season' in opt))
    _set_row_visible(FIELD_ROWS['co_id'], ('co_id' in req) or ('co_id' in opt))

    year_lbl.configure(text=f"年度：{'*' if 'year' in req else ''}")
    season_lbl.configure(text=f"季別：{'*' if 'season' in req else ''}")
    co_lbl.configure(text=f"公司代號/簡稱（{'必填' if 'co_id' in req else '可空'}）：")


def add_job():
    item = item_var.get().strip()
    market = market_var.get()
    year = year_var.get().strip()
    season = season_var.get().strip()
    co_id = code_var.get().strip()

    if not item:
        messagebox.showwarning("缺少項目", "請選擇項目"); return

    spec = ITEM_SPECS.get(item, {"required": ["TYPEK","year","season"], "optional": ["co_id"]})
    req = set(spec.get("required", []))

    # 年度
    if ('year' in req):
        if not year.isdigit():
            messagebox.showwarning("年度錯誤", "年度請輸入民國或西元整數"); return
    else:
        year = year if year.isdigit() else ""

    # 季別
    if ('season' in req):
        if season not in ("1","2","3","4"):
            messagebox.showwarning("季別錯誤", "季別請選 1/2/3/4"); return
    else:
        season = season if season in ("1","2","3","4") else ""

    # 公司代號
    if ('co_id' in req) and not co_id:
        messagebox.showwarning("公司代號缺少", "此項目需填公司代號/簡稱"); return

    job = {
        "item": item,
        "market": market,
        "year": int(year) if year else None,
        "season": season or None,
        "co_id": co_id or None,
    }
    jobs.append(job)

    tree.insert("", "end", values=(item, market, year or "", season or "", co_id))
    code_var.set("")


def remove_selected():
    sel = tree.selection()
    if not sel: return
    for iid in sel:
        vals = tree.item(iid, "values")
        for idx, j in enumerate(jobs):
            if (j["item"], j["market"], str(j.get("year") or ""), str(j.get("season") or ""), str(j.get("co_id") or "")) == vals:
                jobs.pop(idx); break
        tree.delete(iid)


def clear_jobs():
    jobs.clear()
    for iid in tree.get_children():
        tree.delete(iid)


def run_all():
    if not jobs:
        messagebox.showwarning("無任務", "請先加入至少一筆任務"); return
    out_folder = out_dir_var.get().strip() or "financial_reports"
    try:
        run_jobs_newsite(
            jobs,
            out_dir=out_folder,
            download_dir="downloads",
            insecure=insecure_var.get()
        )
        messagebox.showinfo("完成", f"已完成，請查看資料夾：{out_folder}")
    except Exception as e:
        messagebox.showerror("錯誤", str(e))

# ==== UI ====
root = tk.Tk()
root.title("MOPS 新站｜彙總報表/財務報表下載")
root.geometry("860x560")

frm = ttk.Frame(root, padding=12); frm.pack(fill="both", expand=True)

# 左：建任務區
lf = ttk.LabelFrame(frm, text="建立任務"); lf.grid(row=0, column=0, sticky="nwe", padx=6, pady=6)

# 項目
ttk.Label(lf, text="項目：").grid(row=0, column=0, sticky="w", pady=4)
item_var = tk.StringVar()
item_cb = ttk.Combobox(lf, textvariable=item_var, values=ITEMS, state="readonly", width=28)
item_cb.grid(row=0, column=1, sticky="w")
item_cb.bind("<<ComboboxSelected>>", refresh_form_by_item)

# 市場
ttk.Label(lf, text="市場別：").grid(row=1, column=0, sticky="w", pady=4)
market_var = tk.StringVar(value="sii")
cbm = ttk.Combobox(lf, values=[m[0] for m in MARKETS], state="readonly", width=14)
cbm.grid(row=1, column=1, sticky="w"); cbm.current(0)

def on_market(evt): market_var.set(dict(MARKETS)[cbm.get()])
cbm.bind("<<ComboboxSelected>>", on_market)

# 年度
year_lbl = ttk.Label(lf, text="年度：")
year_lbl.grid(row=2, column=0, sticky="w", pady=4)
year_var = tk.StringVar(value="114")
year_row = ttk.Entry(lf, textvariable=year_var, width=12)
year_row.grid(row=2, column=1, sticky="w")

# 季別
season_lbl = ttk.Label(lf, text="季別：")
season_lbl.grid(row=3, column=0, sticky="w", pady=4)
season_var = tk.StringVar(value="4")
season_row = ttk.Combobox(lf, textvariable=season_var, values=["1","2","3","4"], state="readonly", width=10)
season_row.grid(row=3, column=1, sticky="w")

# 公司代號
co_lbl = ttk.Label(lf, text="公司代號/簡稱（可空）：")
co_lbl.grid(row=4, column=0, sticky="w", pady=4)
code_var = tk.StringVar()
co_row = ttk.Entry(lf, textvariable=code_var, width=18)
co_row.grid(row=4, column=1, sticky="w")

FIELD_ROWS['year'] = (year_lbl, year_row)
FIELD_ROWS['season'] = (season_lbl, season_row)
FIELD_ROWS['co_id'] = (co_lbl, co_row)

# 加入佇列按鈕
ttk.Button(lf, text="加入佇列", command=add_job).grid(row=5, column=0, columnspan=2, pady=8, sticky="we")

# 右：任務清單
rf = ttk.LabelFrame(frm, text="任務清單（可多筆、逐筆執行）")
rf.grid(row=0, column=1, sticky="nswe", padx=6, pady=6)
rf.columnconfigure(0, weight=1); rf.rowconfigure(0, weight=1)

cols = ("項目","市場","年度","季別","公司")

style = ttk.Style()
style.configure('Treeview', rowheight=22)

tree = ttk.Treeview(rf, columns=cols, show="headings", height=14)
for c in cols:
    tree.heading(c, text=c)
    width = {"項目":220, "市場":60, "年度":70, "季別":50, "公司":120}[c]
    tree.column(c, width=width, anchor="center")

tree.grid(row=0, column=0, sticky="nswe")

btns = ttk.Frame(rf); btns.grid(row=1, column=0, pady=8, sticky="we")
ttk.Button(btns, text="移除選取", command=remove_selected).grid(row=0, column=0, padx=4)
ttk.Button(btns, text="清空清單", command=clear_jobs).grid(row=0, column=1, padx=4)

# 輸出與執行
bf = ttk.LabelFrame(frm, text="執行")
bf.grid(row=1, column=0, columnspan=2, sticky="we", padx=6, pady=6)

ttk.Label(bf, text="輸出資料夾：").grid(row=0, column=0, sticky="w", pady=6)
out_dir_var = tk.StringVar(value="financial_reports")
ttk.Entry(bf, textvariable=out_dir_var, width=40).grid(row=0, column=1, sticky="w")

def browse_out_dir():
    path = filedialog.askdirectory()
    if path: out_dir_var.set(path)

ttk.Button(bf, text="瀏覽…", command=browse_out_dir).grid(row=0, column=2, padx=8)

insecure_var = tk.BooleanVar(value=False)
ttk.Checkbutton(bf, text="跳過 TLS 驗證（測試用）", variable=insecure_var).grid(row=0, column=3, padx=8)

ttk.Button(bf, text="開始", command=run_all).grid(row=0, column=4, padx=8)

root.after(50, refresh_form_by_item)
root.mainloop()
