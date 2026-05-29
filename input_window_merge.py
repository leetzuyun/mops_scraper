import tkinter as tk
from tkinter import ttk, messagebox
import threading
from pathlib import Path

from scraper import run_jobs_financial_reports, crawl_multiple_announcements

root = tk.Tk()
root.title("MOPS Scraper - 財報與公告下載")
root.geometry("450x350")

# 變量定義
mode_var = tk.StringVar(value="report")     # 功能模式: report (財報) / announcement (公告)
market_var = tk.StringVar(value="sii")       # 市場別 (上市sii/上櫃otc/興櫃rotc/公發pub)
year_var = tk.StringVar(value="2026")        # 年度
co_id_var = tk.StringVar()                   # 公司代號 (財報模式才用得到)
season_var = tk.StringVar(value="Q1")        # 季度 (財報模式才用得到)

# ─── 區塊 1：選擇功能模式 ───
mode_frame = ttk.LabelFrame(root, text=" 選擇功能模式 ", padding=10)
mode_frame.pack(fill="x", padx=15, pady=5)

def toggle_mode():
    """根據選擇的功能，動態隱藏/顯示非必填的欄位"""
    if mode_var.get() == "announcement":
        # 公告模式：隱藏公司代號與季度 (因為只需市場別與年度)
        co_id_label.pack_forget()
        co_id_entry.pack_forget()
        season_label.pack_forget()
        season_combo.pack_forget()
    else:
        # 財報模式：重新顯示
        co_id_label.pack(side="left", padx=5)
        co_id_entry.pack(side="left", padx=5)
        season_label.pack(side="left", padx=5)
        season_combo.pack(side="left", padx=5)

ttk.Radiobutton(mode_frame, text="財報下載與表格提取", variable=mode_var, value="report", command=toggle_mode).pack(side="left", padx=20)
ttk.Radiobutton(mode_frame, text="債券相關處分公告", variable=mode_var, value="announcement", command=toggle_mode).pack(side="left", padx=20)


# ─── 區塊 2：輸入參數區 ───
param_frame = ttk.LabelFrame(root, text=" 查詢參數 (必填) ", padding=10)
param_frame.pack(fill="x", padx=15, pady=5)

# 1. 年度
ttk.Label(param_frame, text="年度 (西元):").grid(row=0, column=0, sticky="w", pady=5)
ttk.Entry(param_frame, textvariable=year_var, width=15).grid(row=0, column=1, sticky="w", pady=5)

# 2. 市場別
ttk.Label(param_frame, text="市場別:").grid(row=1, column=0, sticky="w", pady=5)
market_combo = ttk.Combobox(param_frame, textvariable=market_var, values=["sii", "otc", "rotc", "pub"], width=13, state="readonly")
market_combo.grid(row=1, column=1, sticky="w", pady=5)
# 提示使用者：sii=上市, otc=上櫃, rotc=興櫃, pub=公發
ttk.Label(param_frame, text="(sii:上市 | otc:上櫃 | rotc:興櫃)", font=("Arial", 9), foreground="gray").grid(row=1, column=2, sticky="w", padx=5)


# ─── 區塊 3：動態顯示區 (財報專用欄位) ───
dynamic_frame = ttk.Frame(root, padding=10)
dynamic_frame.pack(fill="x", padx=15, pady=5)

co_id_label = ttk.Label(dynamic_frame, text="公司代號:")
co_id_label.pack(side="left", padx=5)
co_id_entry = ttk.Entry(dynamic_frame, textvariable=co_id_var, width=10)
co_id_entry.pack(side="left", padx=5)

season_label = ttk.Label(dynamic_frame, text="季度:")
season_label.pack(side="left", padx=5)
season_combo = ttk.Combobox(dynamic_frame, textvariable=season_var, values=["Q1", "Q2", "Q3", "Q4"], width=6, state="readonly")
season_combo.pack(side="left", padx=5)


# ─── 區塊 4：執行與線程控管 ───
def _worker_thread(mode, year, market, co_id, season):
    try:
        target_folder = "downloads"
        
        if mode == "announcement":
            # 💡 執行新加入的公告爬蟲功能
            msg = crawl_multiple_announcements(
                year=int(year),
                typek=market,
                download_dir=target_folder
            )
            root.after(0, lambda: messagebox.showinfo("查詢結果", msg))
            
        else:
            # 原始的財報提取功能
            if not co_id.strip():
                root.after(0, lambda: messagebox.showwarning("提示", "財報模式下，公司代號為必填！"))
                return
            jobs = [{"co_id": co_id.strip(), "year": year, "season": season}]
            run_jobs_financial_reports(jobs, download_dir=target_folder)
            root.after(0, lambda: messagebox.showinfo("完成", f"財報表格提取已完成！"))
            
    except Exception as e:
        error_message = str(e)
        root.after(0, lambda msg=error_message: messagebox.showerror("錯誤", f"執行失敗：\n{msg}"))
    finally:
        root.after(0, lambda: run_btn.configure(state="normal", text="開始執行"))

def start_process():
    # 簡易驗證
    if not year_var.get().strip():
        messagebox.showwarning("提示", "請輸入年度！")
        return
        
    run_btn.configure(state="disabled", text="處理中...")
    
    # 建立外掛線程，避免 GUI 凍結卡死
    t = threading.Thread(
        target=_worker_thread,
        args=(mode_var.get(), year_var.get(), market_var.get(), co_id_var.get(), season_var.get()),
        daemon=True
    )
    t.start()

run_btn = ttk.Button(root, text="開始執行", command=start_process, width=20)
run_btn.pack(pady=20)

# 初始化畫面配置
toggle_mode()

root.mainloop()