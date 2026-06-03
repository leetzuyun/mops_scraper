import threading
import flet as ft
from scraper import run_jobs_financial_reports, crawl_multiple_announcements


def main(page: ft.Page):
    page.title = "MOPS Scraper - 財報與公告下載"
    page.window.width = 500
    page.window.height = 450
    page.window.resizable = False
    page.padding = 20

    # ── 舊版相容邊框設定 ────────────────────────────────────
    # 建立一個四面通用的經典邊框，避開 ft.border.all 的報錯
    classic_border = ft.Border(
        top=ft.BorderSide(width=1, color=ft.Colors.GREY_300),
        bottom=ft.BorderSide(width=1, color=ft.Colors.GREY_300),
        left=ft.BorderSide(width=1, color=ft.Colors.GREY_300),
        right=ft.BorderSide(width=1, color=ft.Colors.GREY_300),
    )

    # ── 狀態變數 ──────────────────────────────────────────
    year_field = ft.TextField(value="2026", width=140, label="年度 (西元)")
    market_dd = ft.Dropdown(
        value="sii",
        width=140,
        label="市場別",
        options=[
            ft.dropdown.Option("sii", "sii（上市）"),
            ft.dropdown.Option("otc", "otc（上櫃）"),
            ft.dropdown.Option("rotc", "rotc（興櫃）"),
            ft.dropdown.Option("pub", "pub（公發）"),
        ],
    )
    co_id_field = ft.TextField(value="", width=120, label="公司代號")
    season_dd = ft.Dropdown(
        value="Q1",
        width=100,
        label="季度",
        options=[ft.dropdown.Option(q) for q in ["Q1", "Q2", "Q3", "Q4"]],
    )
    
    run_btn = ft.Button(content=ft.Text("開始執行"), width=160, height=42)
    status_text = ft.Text(value="", color=ft.Colors.GREY_600, size=13)

    # 財報專用欄位列（動態顯示）
    report_row = ft.Row(
        [co_id_field, season_dd],
        spacing=12,
        visible=False,  # 預設公告模式隱藏
    )

    # ── 模式切換 ──────────────────────────────────────────
    def on_mode_change(e):
        report_row.visible = (e.control.value == "report")
        page.update()

    mode_group = ft.RadioGroup(
        value="announcement",
        on_change=on_mode_change,
        content=ft.Row([
            ft.Radio(value="report",       label="財報下載與表格提取"),
            ft.Radio(value="announcement", label="債券相關處分公告"),
        ]),
    )

    # ── 執行邏輯 ──────────────────────────────────────────
    def worker(selected_mode, year, market, co_id, season):
        try:
            target_folder = "downloads"

            if selected_mode == "announcement":
                crawl_multiple_announcements(
                    year=int(year),
                    typek=market,
                    download_dir=target_folder,
                )
                # 舊版 SnackBar 顯示語法
                page.snack_bar = ft.SnackBar(ft.Text("公告爬取完成！"))
                page.snack_bar.open = True
                page.update()

            else:
                if not co_id.strip():
                    # 舊版 AlertDialog 顯示語法
                    page.dialog = ft.AlertDialog(
                        title=ft.Text("提示"),
                        content=ft.Text("財報模式下，公司代號為必填！"),
                    )
                    page.dialog.open = True
                    page.update()
                    return
                
                jobs = [{"co_id": co_id.strip(), "year": year, "season": season}]
                run_jobs_financial_reports(jobs, download_dir=target_folder)
                
                # 舊版 SnackBar 顯示語法
                page.snack_bar = ft.SnackBar(ft.Text("財報表格提取完成！"))
                page.snack_bar.open = True
                page.update()

        except Exception as e:
            # 舊版錯誤彈窗顯示語法
            page.dialog = ft.AlertDialog(
                title=ft.Text("錯誤"),
                content=ft.Text(f"執行失敗：\n{e}"),
            )
            page.dialog.open = True
            page.update()
        finally:
            run_btn.content.value = "開始執行"
            run_btn.disabled = False
            status_text.value = ""
            page.update()

    def on_run(e):
        if not year_field.value.strip():
            page.dialog = ft.AlertDialog(
                title=ft.Text("提示"),
                content=ft.Text("請輸入年度！"),
            )
            page.dialog.open = True
            page.update()
            return

        run_btn.disabled = True
        run_btn.content.value = "處理中..."
        status_text.value = "執行中，請稍候..."
        page.update()

        t = threading.Thread(
            target=worker,
            args=(
                mode_group.value,
                year_field.value,
                market_dd.value,
                co_id_field.value,
                season_dd.value,
            ),
            daemon=True,
        )
        t.start()

    run_btn.on_click = on_run

    # ── 版面配置 ──────────────────────────────────────────
    page.add(
        ft.Column(
            [
                ft.Text("MOPS Scraper", size=20, weight=ft.FontWeight.BOLD),
                ft.Divider(height=6),

                ft.Container(
                    content=ft.Column([
                        ft.Text("選擇功能模式", size=13, weight=ft.FontWeight.W_600),
                        mode_group,
                    ]),
                    border=classic_border,  # 使用相容舊版的邊框
                    border_radius=8,
                    padding=12,
                ),

                ft.Container(
                    content=ft.Column([
                        ft.Text("查詢參數（必填）", size=13, weight=ft.FontWeight.W_600),
                        ft.Row([year_field, market_dd], spacing=12),
                        report_row,
                    ]),
                    border=classic_border,  # 使用相容舊版的邊框
                    border_radius=8,
                    padding=12,
                ),

                ft.Row([run_btn, status_text], alignment=ft.MainAxisAlignment.START, spacing=16),
            ],
            spacing=12,
        )
    )


ft.run(main)