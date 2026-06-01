"""
Local Folder Batch Window — Hàng Loạt từ Thư mục
Giao diện cấu hình + bảng trạng thái cho xử lý hàng loạt video cục bộ.
"""

import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

import customtkinter as ctk

import config as cfg
from local_batch_processor import (
    LocalBatchProcessor, scan_videos,
    NAMING_AI, NAMING_SUFFIX, NAMING_PREFIX,
    ST_PENDING, ST_RUNNING, ST_SUCCESS, ST_ERROR, ST_SKIPPED,
)

# ── Hằng số tham chiếu từ app_window (tránh circular import) ─────────────────

_LANGUAGES = {
    "Tiếng Trung (Giản thể)": ("zh-CN", "zh"),
    "Tiếng Trung (Phồn thể)": ("zh-TW", "zh"),
    "Tiếng Anh":              ("en",    "en"),
    "Tiếng Hàn":              ("ko",    "ko"),
    "Tiếng Nhật":             ("ja",    "ja"),
    "Tiếng Nga":              ("ru",    "ru"),
    "Tiếng Pháp":             ("fr",    "fr"),
    "Tiếng Tây Ban Nha":      ("es",    "es"),
    "Tiếng Thái":             ("th",    "th"),
}

_WHISPER_MODELS = {
    "tiny  — nhanh nhất":      "tiny",
    "base  — khuyến nghị":     "base",
    "small — cân bằng hơn":    "small",
    "medium — chính xác nhất": "medium",
}

_STATUS_LABEL = {
    ST_PENDING: "⏳ Chờ",
    ST_RUNNING: "🔄 Đang xử lý",
    ST_SUCCESS: "✅ Xong",
    ST_ERROR:   "❌ Lỗi",
    ST_SKIPPED: "⏭️ Bỏ qua",
}

_STATUS_TAG = {
    ST_PENDING: "pending",
    ST_RUNNING: "running",
    ST_SUCCESS: "success",
    ST_ERROR:   "error",
    ST_SKIPPED: "skipped",
}

_CFG_KEY = "local_batch"   # khoá lưu trong config.json


class LocalBatchWindow(ctk.CTkToplevel):

    def __init__(self, parent, app_settings: dict):
        super().__init__(parent)
        self.title("🗂️  Hàng Loạt từ Thư mục")
        self.geometry("1060x760")
        self.minsize(900, 600)
        self.transient(parent)

        self._app_settings = app_settings  # từ app_window (_get_tts_settings, etc.)
        self._processor: Optional[LocalBatchProcessor] = None
        self._running   = False
        self._videos:   List[str] = []
        self._tree_ids: List[str] = []   # iid trong Treeview theo thứ tự video

        # Trạng thái logo path (ngoài StringVar để có thể lưu path dài)
        self._logo_path = app_settings.get("logo_path", "") or ""

        self._build_ui()
        self._load_saved_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, lambda: (self.lift(), self.focus_force()))

    # =========================================================================
    #  UI
    # =========================================================================

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)   # bảng mở rộng

        # ── Tiêu đề ───────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self, text="🗂️  Hàng Loạt từ Thư mục",
            font=ctk.CTkFont(size=18, weight="bold"), anchor="w",
        ).grid(row=0, column=0, padx=20, pady=(12, 4), sticky="ew")

        # ── Khu cấu hình (scrollable) ─────────────────────────────────────────
        cfg_scroll = ctk.CTkScrollableFrame(self, height=310, fg_color="transparent")
        cfg_scroll.grid(row=1, column=0, padx=14, pady=(0, 4), sticky="ew")
        cfg_scroll.grid_columnconfigure(0, weight=1)
        self._build_config(cfg_scroll)

        # ── Nút hành động ─────────────────────────────────────────────────────
        act = ctk.CTkFrame(self, fg_color="transparent")
        act.grid(row=2, column=0, padx=14, pady=(0, 4), sticky="ew")
        act.grid_columnconfigure(2, weight=1)

        self._scan_btn = ctk.CTkButton(
            act, text="🔍  Quét thư mục", width=150, height=36,
            fg_color=("#1565C0", "#0D47A1"), hover_color=("#0D47A1", "#082a60"),
            command=self._scan,
        )
        self._scan_btn.grid(row=0, column=0, padx=(0, 8))

        self._start_btn = ctk.CTkButton(
            act, text="▶  Bắt đầu xử lý", width=160, height=36,
            font=ctk.CTkFont(weight="bold"),
            fg_color="#2E7D32", hover_color="#1B5E20",
            state="disabled", command=self._start,
        )
        self._start_btn.grid(row=0, column=1, padx=(0, 8))

        self._stop_btn = ctk.CTkButton(
            act, text="⏹  Dừng", width=100, height=36,
            fg_color=("#B71C1C", "#7f1d1d"), hover_color=("#C62828", "#991b1b"),
            state="disabled", command=self._stop,
        )
        self._stop_btn.grid(row=0, column=2, sticky="w")

        self._scan_lbl = ctk.CTkLabel(
            act, text="", font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60"),
        )
        self._scan_lbl.grid(row=0, column=3, padx=12, sticky="e")

        # ── Bảng trạng thái ───────────────────────────────────────────────────
        tbl_wrap = ctk.CTkFrame(self)
        tbl_wrap.grid(row=4, column=0, padx=14, pady=4, sticky="nsew")
        tbl_wrap.grid_columnconfigure(0, weight=1)
        tbl_wrap.grid_rowconfigure(0, weight=1)
        self._build_table(tbl_wrap)

        # ── Log panel scrollable ──────────────────────────────────────────────
        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=5, column=0, padx=14, pady=(4, 0), sticky="ew")
        log_frame.grid_columnconfigure(0, weight=1)

        log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 2))
        ctk.CTkLabel(
            log_header, text="📋  Log chi tiết",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray50", "gray60"),
        ).pack(side="left")
        ctk.CTkButton(
            log_header, text="🗑  Xóa log", width=80, height=22,
            font=ctk.CTkFont(size=10),
            fg_color="transparent", border_width=1,
            border_color=("gray65", "gray40"),
            text_color=("gray50", "gray60"),
            hover_color=("gray80", "gray25"),
            command=self._clear_log,
        ).pack(side="right")

        self._log_box = tk.Text(
            log_frame,
            height=7, wrap="word",
            font=("Consolas", 9),
            bg="#1a1a2e", fg="#cdd6f4",
            insertbackground="white",
            relief="flat", bd=0,
            state="disabled",
        )
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self._log_box.yview)
        self._log_box.configure(yscrollcommand=log_vsb.set)
        self._log_box.grid(row=1, column=0, sticky="ew", padx=(8, 0), pady=(0, 4))
        log_vsb.grid(row=1, column=1, sticky="ns", padx=(0, 8), pady=(0, 4))

        # tag màu cho từng loại dòng log
        self._log_box.tag_configure("ok",    foreground="#81C784")
        self._log_box.tag_configure("err",   foreground="#EF9A9A")
        self._log_box.tag_configure("info",  foreground="#64B5F6")
        self._log_box.tag_configure("ffmpeg",foreground="#888888")
        self._log_box.tag_configure("head",  foreground="#FFD54F", font=("Consolas", 9, "bold"))

        # ── Progress bar ──────────────────────────────────────────────────────
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.grid(row=6, column=0, padx=14, pady=(2, 10), sticky="ew")
        bot.grid_columnconfigure(0, weight=1)

        self._prog_bar = ctk.CTkProgressBar(bot)
        self._prog_bar.set(0)
        self._prog_bar.grid(row=0, column=0, sticky="ew")

        self._prog_lbl = ctk.CTkLabel(
            bot, text="", width=70,
            font=ctk.CTkFont(size=11, weight="bold"), anchor="e",
        )
        self._prog_lbl.grid(row=0, column=1, padx=(8, 0))

        self._log("Chọn thư mục và nhấn 🔍 Quét để bắt đầu.")

    # ── Config section ────────────────────────────────────────────────────────

    def _build_config(self, parent):
        """Tất cả cài đặt trong khung scrollable."""

        def card(title):
            outer = ctk.CTkFrame(parent, corner_radius=10)
            outer.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(outer, text=title, font=ctk.CTkFont(size=12, weight="bold"),
                         anchor="w").grid(row=0, column=0, padx=12, pady=(8, 2), sticky="ew")
            ctk.CTkFrame(outer, height=1, fg_color=("gray75", "gray35")
                         ).grid(row=1, column=0, padx=10, sticky="ew")
            inner = ctk.CTkFrame(outer, fg_color="transparent")
            inner.grid(row=2, column=0, sticky="ew")
            inner.grid_columnconfigure(0, weight=1)
            return outer, inner

        # ── Card 1: Thư mục ───────────────────────────────────────────────────
        c_out, c_in = card("📁  Thư mục")
        c_out.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        c_in.grid_columnconfigure(1, weight=1)

        self._input_var  = tk.StringVar()
        self._output_var = tk.StringVar()

        for r, (lbl, var, title) in enumerate([
            ("Video gốc:",  self._input_var,  "Chọn thư mục chứa video cần xử lý"),
            ("Xuất ra:",    self._output_var, "Chọn thư mục lưu video đã dịch"),
        ]):
            ctk.CTkLabel(c_in, text=lbl, font=ctk.CTkFont(weight="bold"),
                         width=90).grid(row=r, column=0, padx=(12, 6), pady=6, sticky="w")
            ctk.CTkEntry(c_in, textvariable=var,
                         placeholder_text=title, height=30
                         ).grid(row=r, column=1, padx=4, pady=6, sticky="ew")
            ctk.CTkButton(
                c_in, text="📂", width=34, height=30,
                command=lambda v=var: self._browse_dir(v),
            ).grid(row=r, column=2, padx=(4, 12), pady=6)

        # ── Card 2: Nhận dạng & Dịch ──────────────────────────────────────────
        c_out2, c_in2 = card("⚙️  Nhận dạng & Dịch")
        c_out2.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        c_in2.grid_columnconfigure((1, 3), weight=1)

        from domain_presets import domain_labels

        self._lang_var    = ctk.StringVar(value="Tiếng Trung (Giản thể)")
        self._domain_var  = ctk.StringVar(value="Chung (không chọn)")
        self._model_var   = ctk.StringVar(value="small — cân bằng hơn")
        self._prov_var    = ctk.StringVar(value="Google Translate (miễn phí)")

        specs = [
            ("Ngôn ngữ gốc:", self._lang_var,   list(_LANGUAGES.keys()),   0, 0),
            ("Lĩnh vực:",     self._domain_var,  domain_labels(),           0, 2),
            ("Mô hình STT:",  self._model_var,   list(_WHISPER_MODELS.keys()), 1, 0),
            ("Dịch bằng:",    self._prov_var,    list(cfg.PROVIDER_LABELS.values()), 1, 2),
        ]
        for lbl, var, vals, row, col in specs:
            ctk.CTkLabel(c_in2, text=lbl, font=ctk.CTkFont(size=11, weight="bold"),
                         width=110).grid(row=row, column=col, padx=(12 if col == 0 else 8, 4),
                                         pady=6, sticky="w")
            ctk.CTkOptionMenu(c_in2, variable=var, values=vals, width=220
                              ).grid(row=row, column=col + 1, padx=(0, 4), pady=6, sticky="w")

        # ── Card 3: Lồng tiếng ────────────────────────────────────────────────
        c_out3, c_in3 = card("🎙️  Lồng tiếng")
        c_out3.grid(row=2, column=0, sticky="ew", padx=4, pady=4)
        c_in3.grid_columnconfigure((1, 3), weight=1)

        # Giọng đọc
        voice_row = ctk.CTkFrame(c_in3, fg_color="transparent")
        voice_row.grid(row=0, column=0, columnspan=4, padx=12, pady=(8, 4), sticky="w")

        ctk.CTkLabel(voice_row, text="Giọng đọc:", font=ctk.CTkFont(size=11, weight="bold"),
                     width=90).pack(side="left", padx=(0, 8))

        self._voice_var = ctk.StringVar(value="vi-VN-NamMinhNeural")
        self._btn_female = ctk.CTkButton(
            voice_row, text="♀  Nữ — HoaiMy", width=155, height=34,
            font=ctk.CTkFont(size=12),
            fg_color=("gray60", "gray35"), hover_color=("#1565C0", "#0D47A1"),
            command=lambda: self._set_voice("vi-VN-HoaiMyNeural"),
        )
        self._btn_female.pack(side="left", padx=(0, 6))

        self._btn_male = ctk.CTkButton(
            voice_row, text="♂  Nam — NamMinh", width=155, height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1565C0", hover_color="#0D47A1",
            command=lambda: self._set_voice("vi-VN-NamMinhNeural"),
        )
        self._btn_male.pack(side="left")

        # Volume sliders
        vol_row = ctk.CTkFrame(c_in3, fg_color="transparent")
        vol_row.grid(row=1, column=0, columnspan=4, padx=12, pady=(0, 4), sticky="ew")
        vol_row.grid_columnconfigure((1, 3), weight=1)

        self._orig_vol = tk.IntVar(value=5)
        self._dub_vol  = tk.IntVar(value=100)
        self._speed    = tk.IntVar(value=100)

        for c, (lbl, var, default, maxv) in enumerate([
            ("🔊 Tiếng gốc:", self._orig_vol, 5,   100),
            ("🎤 Lồng tiếng:", self._dub_vol, 100, 200),
        ]):
            c0 = c * 2
            ctk.CTkLabel(vol_row, text=lbl, font=ctk.CTkFont(size=11)
                         ).grid(row=0, column=c0, padx=(0, 6), sticky="w")
            vlbl = ctk.CTkLabel(vol_row, text=f"{default}%", width=44,
                                font=ctk.CTkFont(size=11, weight="bold"))
            vlbl.grid(row=0, column=c0 + 1, sticky="w")
            ctk.CTkSlider(
                vol_row, from_=0, to=maxv, variable=var, width=180,
                command=lambda v, lb=vlbl: lb.configure(text=f"{int(v)}%"),
            ).grid(row=0, column=c0 + 1, padx=(44, 20 if c == 0 else 0), sticky="ew")

        # Speed
        sp_row = ctk.CTkFrame(c_in3, fg_color="transparent")
        sp_row.grid(row=2, column=0, columnspan=4, padx=12, pady=(0, 8), sticky="w")
        ctk.CTkLabel(sp_row, text="⚡ Tốc độ:", font=ctk.CTkFont(size=11)
                     ).pack(side="left", padx=(0, 8))
        sp_lbl = ctk.CTkLabel(sp_row, text="100%", width=100,
                               font=ctk.CTkFont(size=11, weight="bold"))
        sp_lbl.pack(side="left")
        ctk.CTkSlider(
            sp_row, from_=50, to=200, variable=self._speed, width=180,
            number_of_steps=150,
            command=lambda v: sp_lbl.configure(text=f"{int(v)}%"),
        ).pack(side="left")

        # ── Card 4: Nhạc nền & Logo ───────────────────────────────────────────
        c_out4, c_in4 = card("🎵  Nhạc nền & Logo")
        c_out4.grid(row=3, column=0, sticky="ew", padx=4, pady=4)
        c_in4.grid_columnconfigure(0, weight=1)

        # Nhạc nền
        mu_row = ctk.CTkFrame(c_in4, fg_color="transparent")
        mu_row.grid(row=0, column=0, padx=12, pady=(8, 4), sticky="w")
        self._music_en  = tk.BooleanVar(value=True)
        self._music_vol = tk.IntVar(value=8)
        ctk.CTkCheckBox(mu_row, text="Nhạc nền", variable=self._music_en,
                        font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(mu_row, text="Âm lượng:", font=ctk.CTkFont(size=11)
                     ).pack(side="left", padx=(0, 6))
        mu_lbl = ctk.CTkLabel(mu_row, text="8%", width=42,
                               font=ctk.CTkFont(size=11, weight="bold"))
        mu_lbl.pack(side="left")
        ctk.CTkSlider(
            mu_row, from_=0, to=50, variable=self._music_vol, width=160,
            command=lambda v: mu_lbl.configure(text=f"{int(v)}%"),
        ).pack(side="left")

        # Logo
        lo_row = ctk.CTkFrame(c_in4, fg_color="transparent")
        lo_row.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")
        lo_row.grid_columnconfigure(2, weight=1)

        self._logo_en      = tk.BooleanVar(value=False)
        self._logo_opacity = tk.IntVar(value=30)
        self._logo_size    = tk.IntVar(value=120)

        ctk.CTkCheckBox(lo_row, text="Logo", variable=self._logo_en,
                        font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(0, 12))
        self._logo_lbl = ctk.CTkLabel(
            lo_row, text="  Chưa chọn file logo...",
            anchor="w", fg_color=("gray82", "gray22"), corner_radius=6, height=28,
        )
        self._logo_lbl.grid(row=0, column=2, padx=(0, 6), sticky="ew")
        ctk.CTkButton(lo_row, text="📂", width=34, height=28,
                      command=self._browse_logo).grid(row=0, column=3, padx=(0, 12))

        ctk.CTkLabel(lo_row, text="🌫", font=ctk.CTkFont(size=11)).grid(row=0, column=4, padx=(0, 2))
        lo_lbl = ctk.CTkLabel(lo_row, text="30%", width=36,
                               font=ctk.CTkFont(size=11, weight="bold"))
        lo_lbl.grid(row=0, column=5)
        ctk.CTkSlider(lo_row, from_=1, to=100, variable=self._logo_opacity, width=90,
                      command=lambda v: lo_lbl.configure(text=f"{int(v)}%")
                      ).grid(row=0, column=6, padx=(0, 10))

        ctk.CTkLabel(lo_row, text="📐", font=ctk.CTkFont(size=11)).grid(row=0, column=7, padx=(0, 2))
        ls_lbl = ctk.CTkLabel(lo_row, text="120px", width=44,
                               font=ctk.CTkFont(size=11, weight="bold"))
        ls_lbl.grid(row=0, column=8)
        ctk.CTkSlider(lo_row, from_=20, to=400, variable=self._logo_size, width=90,
                      command=lambda v: ls_lbl.configure(text=f"{int(v)}px")
                      ).grid(row=0, column=9)

        # ── Card 5: Quy tắc đặt tên ──────────────────────────────────────────
        c_out5, c_in5 = card("📝  Quy tắc đặt tên file xuất")
        c_out5.grid(row=4, column=0, sticky="ew", padx=4, pady=4)

        self._naming_var  = tk.StringVar(value=NAMING_AI)
        self._prefix_var  = tk.StringVar()

        naming_opts = [
            (NAMING_AI,     "🤖  Dùng AI tạo tiêu đề từ nội dung video  (vd: Kỹ thuật smash cầu lông.mp4)"),
            (NAMING_SUFFIX, "📄  Giữ tên gốc + hậu tố _vi               (vd: DSC_0012_vi.mp4)"),
            (NAMING_PREFIX, "🏷️   Thêm tiền tố + giữ tên gốc"),
        ]
        for val, label in naming_opts:
            rb = tk.Radiobutton(
                c_in5, text=label, variable=self._naming_var, value=val,
                font=("Segoe UI", 11),
                bg="#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#f0f0f0",
                fg="white" if ctk.get_appearance_mode() == "Dark" else "black",
                selectcolor="#1565C0",
                activebackground="#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#f0f0f0",
                border=0, pady=2,
                command=self._on_naming_change,
            )
            rb.pack(anchor="w", padx=16, pady=2)

        pf_row = ctk.CTkFrame(c_in5, fg_color="transparent")
        pf_row.pack(anchor="w", padx=32, pady=(0, 8))
        ctk.CTkLabel(pf_row, text="Tiền tố:", font=ctk.CTkFont(size=11)
                     ).pack(side="left", padx=(0, 8))
        self._prefix_entry = ctk.CTkEntry(
            pf_row, textvariable=self._prefix_var, width=200, height=28,
            placeholder_text="ví dụ:  CL_  hoặc  2024_",
            state="disabled",
        )
        self._prefix_entry.pack(side="left")

    # ── Table ─────────────────────────────────────────────────────────────────

    def _build_table(self, parent):
        style = ttk.Style()
        style.configure("LB.Treeview",
                        background="#1e1e2e", foreground="#cdd6f4",
                        fieldbackground="#1e1e2e", rowheight=42,
                        font=("Segoe UI", 10))
        style.configure("LB.Treeview.Heading",
                        background="#1f538d", foreground="white",
                        font=("Segoe UI", 10, "bold"))
        style.map("LB.Treeview", background=[("selected", "#313244")])

        self._tree = ttk.Treeview(
            parent, style="LB.Treeview",
            columns=("no", "source", "status", "detail", "output"),
            show="headings", selectmode="browse",
        )
        self._tree.heading("no",     text="#",          anchor="center")
        self._tree.heading("source", text="File gốc")
        self._tree.heading("status", text="Trạng thái", anchor="center")
        self._tree.heading("detail", text="Chi tiết")
        self._tree.heading("output", text="File xuất ra")

        self._tree.column("no",     width=44,  minwidth=36,  anchor="center", stretch=False)
        self._tree.column("source", width=230, minwidth=150)
        self._tree.column("status", width=140, minwidth=100, anchor="center", stretch=False)
        self._tree.column("detail", width=220, minwidth=100)
        self._tree.column("output", width=280, minwidth=150)

        vsb = ttk.Scrollbar(parent, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._tree.tag_configure("pending", foreground="#888888")
        self._tree.tag_configure("running", foreground="#FFD54F")
        self._tree.tag_configure("success", foreground="#81C784")
        self._tree.tag_configure("error",   foreground="#EF9A9A")
        self._tree.tag_configure("skipped", foreground="#64B5F6")

        self._tree.bind("<Double-1>", self._on_row_dblclick)

    # =========================================================================
    #  Actions
    # =========================================================================

    def _browse_dir(self, var: tk.StringVar):
        p = filedialog.askdirectory(parent=self)
        if p:
            var.set(p)

    def _browse_logo(self):
        p = filedialog.askopenfilename(
            parent=self, title="Chọn ảnh logo",
            filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Tất cả", "*.*")],
        )
        if p:
            self._logo_path = p
            self._logo_lbl.configure(text=f"  {os.path.basename(p)}")
            self._logo_en.set(True)

    def _set_voice(self, voice_id: str):
        self._voice_var.set(voice_id)
        is_female = "HoaiMy" in voice_id
        self._btn_female.configure(
            fg_color="#1565C0" if is_female else ("gray60", "gray35"),
            font=ctk.CTkFont(size=12, weight="bold" if is_female else "normal"),
        )
        self._btn_male.configure(
            fg_color="#1565C0" if not is_female else ("gray60", "gray35"),
            font=ctk.CTkFont(size=12, weight="bold" if not is_female else "normal"),
        )

    def _on_naming_change(self):
        mode = self._naming_var.get()
        self._prefix_entry.configure(
            state="normal" if mode == NAMING_PREFIX else "disabled"
        )

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _scan(self):
        folder = self._input_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Thiếu thư mục", "Hãy chọn thư mục chứa video!", parent=self)
            return

        self._videos = scan_videos(folder)
        self._populate_table(self._videos)

        n = len(self._videos)
        if n == 0:
            self._scan_lbl.configure(text="Không tìm thấy video nào.")
            self._start_btn.configure(state="disabled")
        else:
            self._scan_lbl.configure(text=f"Tìm thấy {n} video.")
            self._start_btn.configure(state="normal")
        self._log(f"📁  {n} video trong thư mục.")

    def _populate_table(self, videos: List[str]):
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._tree_ids.clear()

        for i, path in enumerate(videos):
            iid = self._tree.insert(
                "", "end",
                values=(i + 1, os.path.basename(path), "⏳ Chờ", "", ""),
                tags=("pending",),
            )
            self._tree_ids.append(iid)

        self._prog_bar.set(0)
        self._prog_lbl.configure(text="")

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def _start(self):
        if self._running:
            return

        inp = self._input_var.get().strip()
        out = self._output_var.get().strip()

        if not inp or not os.path.isdir(inp):
            messagebox.showwarning("Thiếu thư mục gốc", "Hãy chọn thư mục chứa video!", parent=self)
            return
        if not out:
            messagebox.showwarning("Thiếu thư mục xuất", "Hãy chọn thư mục lưu video đã xử lý!", parent=self)
            return
        if not self._videos:
            self._scan()
            if not self._videos:
                return

        self._save_settings()
        self._running = True
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._prog_bar.set(0)

        settings = self._collect_settings()

        self._processor = LocalBatchProcessor(
            input_folder=inp,
            output_folder=out,
            settings=settings,
            log_cb=lambda m: self.after(0, lambda msg=m: self._log(msg)),
            row_cb=lambda i, s, d, o: self.after(
                0, lambda ii=i, ss=s, dd=d, oo=o: self._update_row(ii, ss, dd, oo)
            ),
            progress_cb=lambda done, total: self.after(
                0, lambda d=done, t=total: self._update_progress(d, t)
            ),
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
        self._log("⏹  Đang dừng sau khi xử lý xong video hiện tại...")
        self._stop_btn.configure(state="disabled")

    # ── Collect settings ──────────────────────────────────────────────────────

    def _collect_settings(self) -> dict:
        lang_label  = self._lang_var.get()
        trans_lang, whisper_lang = _LANGUAGES.get(lang_label, ("zh-CN", "zh"))
        model_size  = _WHISPER_MODELS.get(self._model_var.get(), "small")
        prov_label  = self._prov_var.get()
        provider    = next(
            (k for k, v in cfg.PROVIDER_LABELS.items() if v == prov_label), "google"
        )
        saved       = cfg.load()

        return {
            # STT
            "whisper_model": model_size,
            "whisper_lang":  whisper_lang,
            # Translation
            "trans_lang":    trans_lang,
            "trans_provider": provider,
            "trans_api_key": (saved.get("openai_api_key", "") if provider == "openai"
                              else saved.get("anthropic_api_key", "")),
            "trans_model":   (saved.get("openai_model", "") if provider == "openai"
                              else saved.get("anthropic_model", "")),
            "domain":        self._domain_var.get(),
            # TTS
            "tts_provider":  "edge",
            "tts_voice":     self._voice_var.get(),
            "tts_api_key":   "",
            "tts_speed":     100,
            # Volume
            "orig_vol":      self._orig_vol.get()  / 100.0,
            "dub_vol":       self._dub_vol.get()   / 100.0,
            # Music
            "music_enabled": self._music_en.get(),
            "music_volume":  self._music_vol.get() / 100.0,
            # Logo
            "logo_enabled":  self._logo_en.get(),
            "logo_path":     self._logo_path,
            "logo_opacity":  self._logo_opacity.get() / 100.0,
            "logo_size":     self._logo_size.get(),
            # Subtitle
            "font_size":     self._app_settings.get("font_size", 9),
            "sub_style":     self._app_settings.get("sub_style", "Mặc định"),
            # Naming
            "naming_mode":   self._naming_var.get(),
            "naming_prefix": self._prefix_var.get().strip(),
        }

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        """Thêm dòng log vào textbox, tự cuộn xuống cuối."""
        line = msg.strip()
        if not line:
            return

        # Bỏ qua các warning nhiễu từ FFmpeg/encoder
        _NOISE = (
            "non-monotonic dts",
            "this may result in incorrect timestamps",
            "application provided invalid",
            "deprecated pixel format",
            "encoder did not produce proper pts",
        )
        if any(n in line.lower() for n in _NOISE):
            return

        # Rút gọn dòng frame= để không chiếm quá nhiều chỗ
        if line.startswith("frame=") or "  frame=" in line:
            # Chỉ giữ: fps, time, speed, elapsed
            import re
            m = re.search(
                r"fps=\s*(\S+).*?time=(\S+).*?speed=\s*(\S+)(?:.*?elapsed=(\S+))?",
                line,
            )
            if m:
                fps, t, spd, ela = m.group(1), m.group(2), m.group(3), m.group(4) or ""
                ela_str = f"  đã chạy {ela}" if ela else ""
                line = f"  🎬 fps={fps}  thời gian={t}  tốc độ={spd}{ela_str}"
            tag = "ffmpeg"
        elif line.startswith("──") or line.startswith("==="):
            tag = "head"
        elif "✅" in line or "xong" in line.lower() or "thành công" in line.lower():
            tag = "ok"
        elif "❌" in line or "lỗi" in line.lower() or "error" in line.lower():
            tag = "err"
        else:
            tag = "info"

        self._log_box.configure(state="normal")
        self._log_box.insert("end", line + "\n", tag)
        # Giới hạn 500 dòng để tránh lag
        lines = int(self._log_box.index("end-1c").split(".")[0])
        if lines > 500:
            self._log_box.delete("1.0", "50.0")
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    def _clear_log(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    def _update_progress(self, done: int, total: int):
        if total > 0:
            self._prog_bar.set(done / total)
            self._prog_lbl.configure(text=f"{done}/{total}")

    def _update_row(self, idx: int, status: str, detail: str, output: str):
        if idx >= len(self._tree_ids):
            return
        iid   = self._tree_ids[idx]
        tag   = _STATUS_TAG.get(status, "pending")
        label = _STATUS_LABEL.get(status, status)
        vals  = list(self._tree.item(iid, "values"))
        while len(vals) < 5:
            vals.append("")
        vals[2] = label
        vals[3] = detail[:60] if detail else ""
        if output:
            vals[4] = os.path.basename(output)
        self._tree.item(iid, values=vals, tags=(tag,))
        self._tree.see(iid)

    def _on_row_dblclick(self, event):
        """Double-click vào cột File xuất ra → mở Explorer."""
        col    = self._tree.identify_column(event.x)
        row_id = self._tree.identify_row(event.y)
        if col != "#5" or not row_id:
            return
        vals    = self._tree.item(row_id, "values")
        fname   = vals[4] if len(vals) > 4 else ""
        out_dir = self._output_var.get().strip()
        if not fname or not out_dir:
            return
        full = os.path.join(out_dir, fname)
        if os.path.exists(full):
            subprocess.Popen(f'explorer /select,"{full}"')
        elif os.path.isdir(out_dir):
            subprocess.Popen(f'explorer "{out_dir}"')

    # ── Persist settings ──────────────────────────────────────────────────────

    def _save_settings(self):
        data = cfg.load()
        data[_CFG_KEY] = {
            "input_folder":  self._input_var.get(),
            "output_folder": self._output_var.get(),
            "lang":          self._lang_var.get(),
            "domain":        self._domain_var.get(),
            "model":         self._model_var.get(),
            "provider":      self._prov_var.get(),
            "voice":         self._voice_var.get(),
            "orig_vol":      self._orig_vol.get(),
            "dub_vol":       self._dub_vol.get(),
            "speed":         self._speed.get(),
            "music_en":      self._music_en.get(),
            "music_vol":     self._music_vol.get(),
            "logo_en":       self._logo_en.get(),
            "logo_path":     self._logo_path,
            "logo_opacity":  self._logo_opacity.get(),
            "logo_size":     self._logo_size.get(),
            "naming_mode":   self._naming_var.get(),
            "naming_prefix": self._prefix_var.get(),
        }
        cfg.save(data)

    def _load_saved_settings(self):
        saved = cfg.load().get(_CFG_KEY, {})
        if not saved:
            return

        def _set(var, key, default=None):
            val = saved.get(key, default)
            if val is not None:
                var.set(val)

        _set(self._input_var,  "input_folder")
        _set(self._output_var, "output_folder")
        _set(self._lang_var,   "lang")
        _set(self._domain_var, "domain")
        _set(self._model_var,  "model")
        _set(self._prov_var,   "provider")
        _set(self._orig_vol,   "orig_vol")
        _set(self._dub_vol,    "dub_vol")
        _set(self._speed,      "speed")
        _set(self._music_en,   "music_en")
        _set(self._music_vol,  "music_vol")
        _set(self._logo_en,    "logo_en")
        _set(self._logo_opacity, "logo_opacity")
        _set(self._logo_size,  "logo_size")
        _set(self._naming_var, "naming_mode")
        _set(self._prefix_var, "naming_prefix")

        voice = saved.get("voice", "vi-VN-NamMinhNeural")
        self._set_voice(voice)

        lp = saved.get("logo_path", "")
        if lp:
            self._logo_path = lp
            self._logo_lbl.configure(text=f"  {os.path.basename(lp)}")

        # Cập nhật trạng thái prefix entry
        self._on_naming_change()

    def _on_close(self):
        if self._processor:
            self._processor.stop()
        self.destroy()
