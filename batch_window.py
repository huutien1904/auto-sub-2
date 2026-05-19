"""Batch processing window — Google Sheets via Service Account JSON."""

import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Optional

import customtkinter as ctk

from batch_processor import (
    BatchProcessor, ST_NEW, ST_SUCCESS, ST_ERROR,
    test_connection, SheetClient, get_pending_rows,
)
import tkinter.messagebox as _mb


STATUS_COLORS = {
    ST_NEW:         ("#888888", "#888888"),
    "đang tải video":   ("#1565C0", "#64B5F6"),
    "đã tải xong":      ("#1565C0", "#64B5F6"),
    "đang xử lý":       ("#F57F17", "#FFD54F"),
    ST_SUCCESS:     ("#2E7D32", "#81C784"),
    ST_ERROR:       ("#B71C1C", "#EF9A9A"),
}


class BatchWindow(ctk.CTkToplevel):
    def __init__(self, parent, app_settings: dict):
        super().__init__(parent)
        self.title("📊  Xử lý hàng loạt từ Google Sheets")
        self.geometry("1000x680")
        self.minsize(820, 520)

        self._settings     = app_settings
        self._processor: Optional[BatchProcessor] = None
        self._running      = False
        self._row_map: dict[int, str] = {}
        self._json_path    = ""
        self._logo_path    = app_settings.get("logo_path", "") or ""

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Giữ cửa sổ luôn nằm trên cửa sổ chính
        self.transient(parent)
        self.after(200, self._init_focus)

    def _init_focus(self):
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)   # bảng chiếm phần lớn

        # ── Header ────────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self, text="📊  Xử lý hàng loạt từ Google Sheets",
            font=ctk.CTkFont(size=18, weight="bold"), anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(14, 4), sticky="ew")

        # ── Config card ───────────────────────────────────────────────────────
        cfg = ctk.CTkFrame(self)
        cfg.grid(row=1, column=0, padx=14, pady=4, sticky="ew")
        cfg.grid_columnconfigure(1, weight=1)

        # Row 0: JSON
        ctk.CTkLabel(cfg, text="🔑  Service Account JSON:", font=ctk.CTkFont(weight="bold"),
                     width=180, anchor="w").grid(row=0, column=0, padx=(14,6), pady=(8,4), sticky="w")
        self._json_lbl = ctk.CTkLabel(cfg, text="  Chưa chọn file...",
                                       anchor="w", fg_color=("gray82","gray22"), corner_radius=6, height=30)
        self._json_lbl.grid(row=0, column=1, padx=4, pady=(8,4), sticky="ew")
        ctk.CTkButton(cfg, text="📂", width=34, height=30, command=self._browse_json
                      ).grid(row=0, column=2, padx=(4,6), pady=(8,4))
        ctk.CTkButton(cfg, text="❓", width=34, height=30,
                      fg_color="transparent", border_width=1,
                      command=self._show_help).grid(row=0, column=3, padx=(0,14), pady=(8,4))

        # Row 1: Sheet URL
        ctk.CTkLabel(cfg, text="📋  Google Sheet URL:", font=ctk.CTkFont(weight="bold"),
                     width=180, anchor="w").grid(row=1, column=0, padx=(14,6), pady=4, sticky="w")
        self._sheet_url = tk.StringVar()
        ctk.CTkEntry(cfg, textvariable=self._sheet_url, height=30,
                     placeholder_text="https://docs.google.com/spreadsheets/d/..."
                     ).grid(row=1, column=1, columnspan=3, padx=(4,14), pady=4, sticky="ew")

        # Row 2: Thư mục tải + hoàn thành (gộp 1 hàng)
        dirs_row = ctk.CTkFrame(cfg, fg_color="transparent")
        dirs_row.grid(row=2, column=0, columnspan=4, padx=10, pady=4, sticky="ew")
        dirs_row.grid_columnconfigure(1, weight=1)
        dirs_row.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(dirs_row, text="📥 Tải về:", font=ctk.CTkFont(size=11, weight="bold"),
                     width=70).grid(row=0, column=0, padx=(4,4), sticky="w")
        self._dl_dir = tk.StringVar()
        ctk.CTkEntry(dirs_row, textvariable=self._dl_dir, height=30,
                     placeholder_text="Thư mục video gốc..."
                     ).grid(row=0, column=1, padx=(0,4), sticky="ew")
        ctk.CTkButton(dirs_row, text="📂", width=32, height=30,
                      command=self._browse_dl_dir).grid(row=0, column=2, padx=(0,12))

        ctk.CTkLabel(dirs_row, text="✅ Hoàn thành:", font=ctk.CTkFont(size=11, weight="bold"),
                     width=90).grid(row=0, column=3, padx=(0,4), sticky="w")
        self._out_dir = tk.StringVar()
        ctk.CTkEntry(dirs_row, textvariable=self._out_dir, height=30,
                     placeholder_text="Thư mục video đã dịch..."
                     ).grid(row=0, column=4, padx=(0,4), sticky="ew")
        dirs_row.grid_columnconfigure(4, weight=1)
        ctk.CTkButton(dirs_row, text="📂", width=32, height=30,
                      command=self._browse_out_dir).grid(row=0, column=5, padx=(0,4))

        # Row 3: Logo (gọn 1 hàng)
        logo_row = ctk.CTkFrame(cfg, fg_color="transparent")
        logo_row.grid(row=3, column=0, columnspan=4, padx=10, pady=(4,8), sticky="ew")
        logo_row.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(logo_row, text="🔲 Logo:", font=ctk.CTkFont(size=11, weight="bold"),
                     width=60).grid(row=0, column=0, padx=(4,6), sticky="w")

        self._logo_enabled_var = tk.BooleanVar(value=bool(self._settings.get("logo_enabled", False)))
        ctk.CTkCheckBox(logo_row, text="Bật", variable=self._logo_enabled_var,
                        width=55).grid(row=0, column=1, padx=(0,8), sticky="w")

        init_logo = os.path.basename(self._logo_path) if self._logo_path else "Chưa chọn file logo..."
        self._logo_lbl = ctk.CTkLabel(logo_row, text=f"  {init_logo}",
                                       anchor="w", fg_color=("gray82","gray22"),
                                       corner_radius=6, height=28)
        self._logo_lbl.grid(row=0, column=2, padx=(0,6), sticky="ew")
        ctk.CTkButton(logo_row, text="📂", width=32, height=28,
                      command=self._browse_logo).grid(row=0, column=3, padx=(0,8))

        ctk.CTkLabel(logo_row, text="🌫", font=ctk.CTkFont(size=11)).grid(row=0, column=4, padx=(0,2))
        self._logo_opacity_var = tk.IntVar(value=int(self._settings.get("logo_opacity", 0.3) * 100))
        self._logo_op_lbl = ctk.CTkLabel(logo_row, text=f"{self._logo_opacity_var.get()}%",
                                          width=34, font=ctk.CTkFont(size=11, weight="bold"))
        self._logo_op_lbl.grid(row=0, column=5)
        ctk.CTkSlider(logo_row, from_=1, to=100, variable=self._logo_opacity_var, width=90,
                      command=lambda v: self._logo_op_lbl.configure(text=f"{int(v)}%")
                      ).grid(row=0, column=6, padx=(0,10))

        ctk.CTkLabel(logo_row, text="📐", font=ctk.CTkFont(size=11)).grid(row=0, column=7, padx=(0,2))
        self._logo_size_var = tk.IntVar(value=self._settings.get("logo_size", 120))
        self._logo_sz_lbl = ctk.CTkLabel(logo_row, text=f"{self._logo_size_var.get()}px",
                                          width=40, font=ctk.CTkFont(size=11, weight="bold"))
        self._logo_sz_lbl.grid(row=0, column=8)
        ctk.CTkSlider(logo_row, from_=20, to=400, variable=self._logo_size_var, width=90,
                      command=lambda v: self._logo_sz_lbl.configure(text=f"{int(v)}px")
                      ).grid(row=0, column=9, padx=(0,4))

        # ── Action buttons — ngoài cfg, luôn hiển thị ─────────────────────────
        act = ctk.CTkFrame(self, fg_color="transparent")
        act.grid(row=2, column=0, padx=14, pady=(2, 6), sticky="w")

        self._connect_btn = ctk.CTkButton(
            act, text="🔗  Kết nối & Xem trước", height=36,
            fg_color=("#1565C0","#0D47A1"), hover_color=("#0D47A1","#082a60"),
            command=self._connect_preview)
        self._connect_btn.pack(side="left", padx=(0, 8))

        self._start_btn = ctk.CTkButton(
            act, text="▶  Bắt đầu xử lý", height=36,
            font=ctk.CTkFont(weight="bold"),
            fg_color="#2E7D32", hover_color="#1B5E20",
            state="disabled", command=self._start)
        self._start_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = ctk.CTkButton(
            act, text="⏹  Dừng", height=36,
            fg_color=("#B71C1C","#7f1d1d"), hover_color=("#C62828","#991b1b"),
            state="disabled", command=self._stop)
        self._stop_btn.pack(side="left")

        # ── Sheet table ───────────────────────────────────────────────────────
        tbl_wrap = ctk.CTkFrame(self)
        tbl_wrap.grid(row=3, column=0, padx=14, pady=4, sticky="nsew")
        tbl_wrap.grid_columnconfigure(0, weight=1)
        tbl_wrap.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("Batch.Treeview",
                        background="#1e1e2e", foreground="#cdd6f4",
                        fieldbackground="#1e1e2e", rowheight=46,
                        font=("Segoe UI", 10))
        style.configure("Batch.Treeview.Heading",
                        background="#1f538d", foreground="white",
                        font=("Segoe UI", 10, "bold"))
        style.map("Batch.Treeview", background=[("selected","#313244")])

        self._tree = ttk.Treeview(
            tbl_wrap, style="Batch.Treeview",
            columns=("no", "link", "status", "error", "output"),
            show="headings", selectmode="browse",
        )
        self._tree.heading("no",     text="#",               anchor="center")
        self._tree.heading("link",   text="Link video")
        self._tree.heading("status", text="Trạng thái",      anchor="center")
        self._tree.heading("error",  text="Lý do lỗi")
        self._tree.heading("output", text="Video hoàn thành")

        self._tree.column("no",     width=40,  minwidth=36,  anchor="center", stretch=False)
        self._tree.column("link",   width=260, minwidth=150)
        self._tree.column("status", width=150, minwidth=110, anchor="center", stretch=False)
        self._tree.column("error",  width=200, minwidth=100)
        self._tree.column("output", width=280, minwidth=150)

        self._tree.bind("<Double-1>", self._on_output_dblclick)

        vsb = ttk.Scrollbar(tbl_wrap, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._tree.tag_configure("new",      foreground="#888888")
        self._tree.tag_configure("running",  foreground="#FFD54F")
        self._tree.tag_configure("success",  foreground="#81C784")
        self._tree.tag_configure("error",    foreground="#EF9A9A")

        # ── Log + progress ────────────────────────────────────────────────────
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=4, column=0, padx=14, pady=(4, 12), sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)

        self._log_var = tk.StringVar(value="Chờ kết nối...")
        ctk.CTkLabel(bottom, textvariable=self._log_var,
                     font=ctk.CTkFont(size=11), anchor="w",
                     text_color=("gray50","gray60")
                     ).grid(row=0, column=0, sticky="ew")

        self._prog_bar = ctk.CTkProgressBar(bottom)
        self._prog_bar.set(0)
        self._prog_bar.grid(row=1, column=0, pady=(4, 0), sticky="ew")

        self._prog_lbl = ctk.CTkLabel(bottom, text="", width=80,
                                       font=ctk.CTkFont(size=11, weight="bold"),
                                       anchor="e")
        self._prog_lbl.grid(row=1, column=1, padx=(8, 0))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse_json(self):
        path = filedialog.askopenfilename(
            title="Chọn file Service Account JSON",
            filetypes=[("JSON", "*.json"), ("Tất cả", "*.*")],
        )
        if path:
            self._json_path = path
            self._json_lbl.configure(text=f"  {os.path.basename(path)}")

    def _show_help(self):
        _mb.showinfo(
            "Cách tạo Service Account JSON",
            "1. Vào https://console.cloud.google.com\n\n"
            "2. Tạo project mới (hoặc chọn project có sẵn)\n\n"
            "3. APIs & Services → Enable APIs\n"
            "   → Tìm 'Google Sheets API' → Enable\n\n"
            "4. IAM & Admin → Service Accounts\n"
            "   → Create Service Account → đặt tên → Done\n\n"
            "5. Click vào service account vừa tạo\n"
            "   → Tab 'Keys' → Add Key → JSON → Download\n\n"
            "6. Mở Google Sheet của bạn\n"
            "   → Share → thêm email của service account\n"
            "   (email dạng: xxx@project.iam.gserviceaccount.com)\n"
            "   → chọn quyền Editor\n\n"
            "7. Dán URL sheet và chọn file JSON vào ứng dụng\n\n"
            "✅ Xong!",
            parent=self,
        )

    def _browse_logo(self):
        path = filedialog.askopenfilename(
            title="Chọn ảnh logo",
            filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Tất cả", "*.*")],
        )
        if path:
            self._logo_path = path
            self._logo_lbl.configure(text=f"  {os.path.basename(path)}")
            self._logo_enabled_var.set(True)

    def _browse_dl_dir(self):
        p = filedialog.askdirectory(title="Chọn thư mục lưu video tải về")
        if p:
            self._dl_dir.set(p)

    def _browse_out_dir(self):
        p = filedialog.askdirectory(title="Chọn thư mục lưu video hoàn thành")
        if p:
            self._out_dir.set(p)

    def _connect_preview(self):
        if not self._json_path:
            _mb.showwarning("Thiếu file JSON", "Vui lòng chọn file Service Account JSON!", parent=self)
            return
        url = self._sheet_url.get().strip()
        if not url or "spreadsheet" not in url:
            _mb.showwarning("URL không hợp lệ",
                "Vui lòng nhập đúng Google Sheet URL.\n\n"
                "Ví dụ:\nhttps://docs.google.com/spreadsheets/d/ABC123.../edit",
                parent=self)
            return
        self._log("🔗  Đang kết nối...")
        self._connect_btn.configure(state="disabled", text="⏳  Đang kết nối...")
        threading.Thread(target=self._do_preview, args=(self._json_path, url), daemon=True).start()

    def _do_preview(self, json_path: str, url: str):
        try:
            client   = SheetClient(json_path, url)
            client.ensure_header()
            all_rows = client.read_all()
            pending  = sum(1 for r in all_rows[1:] if len(r) > 1 and r[1].strip().lower() == "new")
            self.after(0, lambda: self._populate_table(all_rows))
            self.after(0, lambda: self._log(
                f"✅  Kết nối thành công! {len(all_rows)-1} hàng, {pending} hàng 'new'."))
            self.after(0, lambda: self._start_btn.configure(state="normal"))
        except Exception as e:
            err = str(e)
            self.after(0, lambda: self._log(f"❌  Lỗi kết nối: {err}"))
            self.after(0, lambda: _mb.showerror(
                "Lỗi kết nối Google Sheets", err, parent=self))
        finally:
            self.after(0, lambda: self._connect_btn.configure(
                state="normal", text="🔗  Kết nối & Xem trước"))

    def _populate_table(self, all_rows: list):
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._row_map.clear()

        for i, row in enumerate(all_rows):
            if i == 0:
                continue   # skip header
            link   = row[0].strip() if len(row) > 0 else ""
            status = row[1].strip() if len(row) > 1 else ""
            error  = row[2].strip() if len(row) > 2 else ""

            if not link:
                continue

            tag = ("success" if status == "xử lý thành công"
                   else "error" if status == "lỗi"
                   else "new")

            output = row[3].strip() if len(row) > 3 else ""
            item_id = self._tree.insert("", "end",
                                         values=(i, link[:60], status, error[:60], output[:60]),
                                         tags=(tag,))
            self._row_map[i + 1] = item_id   # sheet row = i+1 (1-indexed with header)

    def _start(self):
        if self._running:
            return
        dl_dir  = self._dl_dir.get().strip()
        out_dir = self._out_dir.get().strip()

        if not self._json_path or not self._sheet_url.get().strip() or not dl_dir or not out_dir:
            self._log("⚠  Vui lòng điền đủ JSON, Sheet URL, thư mục tải về và thư mục hoàn thành!")
            return

        self._running = True
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._prog_bar.set(0)

        # Cập nhật logo settings từ UI vào settings
        self._settings["logo_path"]    = self._logo_path
        self._settings["logo_enabled"] = self._logo_enabled_var.get()
        self._settings["logo_opacity"] = self._logo_opacity_var.get() / 100.0
        self._settings["logo_size"]    = self._logo_size_var.get()

        self._processor = BatchProcessor(
            json_path=self._json_path,
            sheet_url=self._sheet_url.get().strip(),
            download_dir=dl_dir,
            output_dir=out_dir,
            settings=self._settings,
            log_cb=lambda m: self.after(0, lambda msg=m: self._log(msg)),
            progress_cb=lambda d, t: self.after(0, lambda done=d, total=t: self._update_progress(done, total)),
            row_update_cb=lambda r, s, e, o="": self.after(0, lambda rr=r, ss=s, ee=e, oo=o: self._update_row(rr, ss, ee, oo)),
        )
        threading.Thread(target=self._run_batch, daemon=True).start()

    def _run_batch(self):
        try:
            self._processor.run()
        finally:
            self._running = False
            self.after(0, lambda: self._start_btn.configure(state="normal"))
            self.after(0, lambda: self._stop_btn.configure(state="disabled"))

    def _stop(self):
        if self._processor:
            self._processor.stop()
        self._log("⏹  Đang dừng sau video hiện tại...")
        self._stop_btn.configure(state="disabled")

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        self._log_var.set(msg.replace("\n", " ").strip())

    def _update_progress(self, done: int, total: int):
        if total > 0:
            self._prog_bar.set(done / total)
            self._prog_lbl.configure(text=f"{done}/{total}")

    def _update_row(self, row_num: int, status: str, error: str, output: str = ""):
        item_id = self._row_map.get(row_num)
        if not item_id:
            return
        tag = ("success" if status == "xử lý thành công"
               else "error"   if status == "lỗi"
               else "running")
        vals = list(self._tree.item(item_id, "values"))
        while len(vals) < 5:
            vals.append("")
        vals[2] = status
        vals[3] = error[:60] if error else ""
        if output:
            vals[4] = os.path.basename(output)
        self._tree.item(item_id, values=vals, tags=(tag,))
        self._tree.see(item_id)

    def _on_output_dblclick(self, event):
        """Double-click vào cột Video hoàn thành → mở file explorer."""
        col = self._tree.identify_column(event.x)
        if col != "#5":
            return
        row_id = self._tree.identify_row(event.y)
        if not row_id:
            return
        vals = self._tree.item(row_id, "values")
        if len(vals) < 5 or not vals[4]:
            return
        # Tìm full path từ output_dir + filename
        out_dir = self._out_dir.get().strip()
        fname   = vals[4]
        full    = os.path.join(out_dir, fname) if out_dir else fname
        if os.path.exists(full):
            import subprocess
            subprocess.Popen(f'explorer /select,"{full}"')
        else:
            import subprocess
            subprocess.Popen(f'explorer "{out_dir}"')

    def _on_close(self):
        if self._processor:
            self._processor.stop()
        self.destroy()
