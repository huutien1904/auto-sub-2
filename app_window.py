"""
Video Translator VI — 3-step workflow UI
Step 1: Input & Transcription
Step 2: Editor & Translation
Step 3: Render & Preview
"""

import os
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk

import config as cfg
from api_settings_dialog import ApiSettingsDialog
from batch_window import BatchWindow
from downloader import download_video, detect_platform, extract_url, save_cookies_file, _find_saved_cookies
from dubbing import TTS_PROVIDERS, PROVIDER_VOICES, create_dubbed_track
from preview_window import PreviewWindow
from subtitle_styles import STYLES, DEFAULT_STYLE, build_ffmpeg_style
from subtitle_utils import SubtitleEntry, parse_srt, whisper_to_entries, write_srt
from transcriber import check_ffmpeg
from translator import translate_entries
from video_processor import burn_subtitles, export_with_dubbing, get_video_duration

# ── Language / model maps ─────────────────────────────────────────────────────

LANGUAGES = {
    "Tiếng Trung (Giản thể)": ("zh-CN", "zh"),
    "Tiếng Trung (Phồn thể)": ("zh-TW", "zh"),
    "Tiếng Anh": ("en", "en"),
    "Tiếng Hàn": ("ko", "ko"),
    "Tiếng Nhật": ("ja", "ja"),
    "Tiếng Nga": ("ru", "ru"),
    "Tiếng Pháp": ("fr", "fr"),
    "Tiếng Tây Ban Nha": ("es", "es"),
    "Tiếng Thái": ("th", "th"),
}

WHISPER_MODELS = {
    "tiny  — nhanh nhất":        "tiny",
    "base  — khuyến nghị":       "base",
    "small — cân bằng hơn":      "small",
    "medium — chính xác nhất":   "medium",
}

DOWNLOAD_PLATFORMS = [
    ("🎵 Douyin",   "douyin",   "#FF0050", "v.douyin.com/xxx  hoặc  douyin.com/video/xxx"),
    ("📺 Bilibili", "bilibili", "#00A1D6", "bilibili.com/video/BVxxx  hoặc  b23.tv/xxx"),
    ("⚡ Kuaishou", "kuaishou", "#FF6500", "kuaishou.com/short-video/xxx"),
    ("📕 RedNote",  "rednote",  "#FF2442", "xiaohongshu.com/explore/xxx  hoặc  xhslink.com/xxx"),
    ("▶ YouTube",  "youtube",  "#CC0000", "youtube.com/watch?v=xxx"),
    ("🎬 TikTok",  "tiktok",   "#010101", "tiktok.com/@user/video/xxx"),
]

STEP_NAMES = ["Nhập & Quét", "Biên tập & Dịch", "Kết xuất & Preview"]


# ── Inline cell editor ────────────────────────────────────────────────────────

class _CellEditor(tk.Entry):
    def __init__(self, tree: ttk.Treeview, row_id: str, col: str, on_save):
        bbox = tree.bbox(row_id, col)
        if not bbox:
            return
        x, y, w, h = bbox
        super().__init__(tree, font=("Segoe UI", 10),
                         bg="#1f538d", fg="white",
                         insertbackground="white", relief="flat", bd=1)
        col_idx = int(col.replace("#", "")) - 1
        vals = tree.item(row_id, "values")
        self.insert(0, vals[col_idx] if col_idx < len(vals) else "")
        self.select_range(0, tk.END)
        self.place(x=x, y=y, width=w, height=h)
        self.focus_set()

        def _save(e=None):
            on_save(self.get())
            self.destroy()

        self.bind("<Return>", _save)
        self.bind("<Tab>",    _save)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<FocusOut>", _save)


# ── Main Application ──────────────────────────────────────────────────────────

class SubtitleBubble(ctk.CTkFrame):
    """
    Chat-style text bubble that shows the current subtitle/translation.
    Updates dynamically when a row is selected or translation is running.
    """

    _BUBBLE_BG    = "white"
    _BUBBLE_FONT  = ("Segoe UI", 12, "italic")   # Inter fallback to Segoe UI
    _TEXT_COLOR   = "#1a1a1a"
    _TIME_COLOR   = "#888888"
    _TAIL_SIZE    = 10   # px for the little triangle tail

    def __init__(self, parent, max_width: int = 520, **kwargs):
        kwargs.setdefault("fg_color", "transparent")
        super().__init__(parent, **kwargs)

        self._max_width = max_width
        self.grid_columnconfigure(0, weight=1)

        # Outer wrapper (left-aligned, like incoming chat message)
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.grid(row=0, column=0, padx=(14, 60), pady=(6, 2), sticky="ew")
        wrap.grid_columnconfigure(0, weight=1)

        # The white bubble frame
        self._bubble = ctk.CTkFrame(
            wrap,
            fg_color=self._BUBBLE_BG,
            corner_radius=16,
            border_width=0,
        )
        self._bubble.grid(row=0, column=0, sticky="ew")
        self._bubble.grid_columnconfigure(0, weight=1)

        # Text label inside bubble
        self._text_lbl = ctk.CTkLabel(
            self._bubble,
            text="Chưa có phụ đề…",
            font=ctk.CTkFont(family="Segoe UI", size=12, slant="italic"),
            text_color=self._TEXT_COLOR,
            wraplength=max_width - 40,
            justify="left",
            anchor="w",
        )
        self._text_lbl.grid(row=0, column=0, padx=18, pady=(12, 10), sticky="ew")

        # Timestamp + index (below bubble, right-aligned)
        self._meta_lbl = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(size=10),
            text_color=self._TIME_COLOR,
            anchor="w",
        )
        self._meta_lbl.grid(row=1, column=0, padx=20, pady=(0, 6), sticky="w")

    # ── Public API ────────────────────────────────────────────────────────────

    def set_text(self, text: str, index: int = 0, total: int = 0,
                 start: str = "", end: str = "") -> None:
        """Update bubble content. Call from any thread (uses after())."""
        display = text.strip() if text.strip() else "…"
        meta    = ""
        if index > 0 and total > 0:
            meta = f"Câu {index}/{total}"
        if start:
            meta += f"   {start[:8]}  →  {end[:8]}" if meta else f"{start[:8]}  →  {end[:8]}"
        self._text_lbl.configure(text=display)
        self._meta_lbl.configure(text=meta)

    def set_placeholder(self, msg: str = "Chọn câu để xem bản dịch…") -> None:
        self._text_lbl.configure(text=msg, text_color=self._TIME_COLOR)
        self._meta_lbl.configure(text="")

    def restore_color(self) -> None:
        self._text_lbl.configure(text_color=self._TEXT_COLOR)


class VideoTranslatorApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("Video Dịch Thuật Tiếng Việt")
        self.geometry("1060x780")
        self.minsize(900, 640)

        # ── Shared state ──────────────────────────────────────────────────────
        self.video_path: Optional[str] = None
        self.subtitle_entries: List[SubtitleEntry] = []
        self._api_cfg = cfg.load()
        self._preview_wav: Optional[str] = None
        self._output_path: Optional[str] = None
        self._current_step = 1
        self._step_done = [False, False, False]
        self._processing = False
        self._selected_row = -1

        self._build_ui()
        self.after(300, self._check_ffmpeg)
        self._show_step(1)

    # =========================================================================
    #  UI CONSTRUCTION
    # =========================================================================

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── App title bar ─────────────────────────────────────────────────────
        title_bar = ctk.CTkFrame(self, fg_color=("#1a237e", "#0d1b4b"), corner_radius=0)
        title_bar.grid(row=0, column=0, sticky="ew")
        title_bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(title_bar, text="🎬  Video Dịch Thuật Tiếng Việt",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color="white").grid(row=0, column=0, padx=20, pady=10, sticky="w")

        ctk.CTkButton(
            title_bar, text="📊  Batch",
            width=100, height=30,
            fg_color=("#00695C","#004D40"), hover_color=("#00796B","#00695C"),
            command=self._open_batch,
        ).grid(row=0, column=2, padx=(0, 6), pady=10)

        self._api_btn = ctk.CTkButton(
            title_bar, text="⚙️  Cài đặt API",
            width=130, height=30,
            fg_color=("#7B1FA2","#4A148C"), hover_color=("#6A1B9A","#38006b"),
            command=self._open_api_settings,
        )
        self._api_btn.grid(row=0, column=3, padx=10, pady=10)

        # ── Step indicator ────────────────────────────────────────────────────
        self._step_indicator = self._build_step_indicator()
        self._step_indicator.grid(row=0, column=1, padx=0, pady=0, sticky="s")

        # ── Step content area ─────────────────────────────────────────────────
        self._content = ctk.CTkFrame(self, fg_color=("gray92", "gray14"), corner_radius=0)
        self._content.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self._step_frames: Dict[int, ctk.CTkFrame] = {}
        for i, builder in enumerate([self._build_step1, self._build_step2, self._build_step3], 1):
            frame = ctk.CTkFrame(self._content, fg_color="transparent")
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_rowconfigure(0, weight=1)
            builder(frame)
            self._step_frames[i] = frame

    # ── Step indicator ────────────────────────────────────────────────────────

    def _build_step_indicator(self) -> ctk.CTkFrame:
        f = ctk.CTkFrame(self, fg_color=("#1a237e","#0d1b4b"), corner_radius=0)
        self._step_btns: Dict[int, ctk.CTkButton] = {}

        for i, name in enumerate(STEP_NAMES, 1):
            col = (i - 1) * 2
            btn = ctk.CTkButton(
                f, text=f"  {i}  ", width=38, height=38,
                corner_radius=19,
                font=ctk.CTkFont(size=14, weight="bold"),
                fg_color="gray45", hover_color="gray35",
                text_color="white",
                command=lambda s=i: self._try_jump_step(s),
            )
            btn.grid(row=0, column=col, padx=(16 if i == 1 else 0, 0), pady=6)
            self._step_btns[i] = btn

            ctk.CTkLabel(f, text=name, font=ctk.CTkFont(size=10),
                         text_color=("gray80","gray80")
                         ).grid(row=1, column=col, padx=0, pady=(0, 6))

            if i < 3:
                ctk.CTkFrame(f, width=60, height=2,
                             fg_color="gray45"
                             ).grid(row=0, column=col + 1, padx=4, pady=6)
        return f

    def _update_step_indicator(self, current: int):
        for i, btn in self._step_btns.items():
            if i < current:
                btn.configure(fg_color="#2E7D32", text=f"✓")
            elif i == current:
                btn.configure(fg_color="#1565C0", text=f"  {i}  ")
            else:
                btn.configure(fg_color="gray45", text=f"  {i}  ")

    def _try_jump_step(self, target: int):
        if target <= self._current_step or self._step_done[target - 2]:
            self._show_step(target)

    def _show_step(self, step: int):
        self._current_step = step
        for s, frame in self._step_frames.items():
            if s == step:
                frame.tkraise()
            else:
                frame.lower()
        self._update_step_indicator(step)

    def _go_next(self):
        if self._current_step < 3:
            self._show_step(self._current_step + 1)

    def _go_back(self):
        if self._current_step > 1:
            self._show_step(self._current_step - 1)

    # =========================================================================
    #  STEP 1 — INPUT & TRANSCRIPTION
    # =========================================================================

    def _build_step1(self, parent: ctk.CTkFrame):
        parent.grid_rowconfigure(1, weight=1)

        # ── Section header ────────────────────────────────────────────────────
        hdr = ctk.CTkLabel(parent,
                           text="Bước 1 — Nhập video & Trích xuất phụ đề",
                           font=ctk.CTkFont(size=16, weight="bold"), anchor="w")
        hdr.grid(row=0, column=0, padx=20, pady=(16, 4), sticky="ew")

        # ── Scrollable content ────────────────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        scroll.grid_columnconfigure(0, weight=1)

        # ── A: Video input card ───────────────────────────────────────────────
        inp_outer, inp_card = self._card(scroll, "📁  Chọn video")
        inp_outer.grid(row=0, column=0, sticky="ew", padx=6, pady=4)
        inp_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(inp_card, text="File video:", font=ctk.CTkFont(weight="bold"),
                     width=90).grid(row=0, column=0, padx=12, pady=10, sticky="w")
        self._s1_file_lbl = ctk.CTkLabel(inp_card, text="  Chưa chọn...",
                                         anchor="w", fg_color=("gray82","gray22"), corner_radius=6)
        self._s1_file_lbl.grid(row=0, column=1, padx=6, pady=10, sticky="ew")
        ctk.CTkButton(inp_card, text="📂  Duyệt", width=100,
                      command=self._s1_pick_file
                      ).grid(row=0, column=2, padx=(6,12), pady=10)

        # ── B: Download card ──────────────────────────────────────────────────
        dl_outer, dl_card = self._card(scroll, "🔗  Tải từ link mạng xã hội")
        dl_outer.grid(row=1, column=0, sticky="ew", padx=6, pady=4)
        dl_card.grid_columnconfigure(0, weight=1)

        # Platform buttons
        pl_row = ctk.CTkFrame(dl_card, fg_color="transparent")
        pl_row.grid(row=0, column=0, padx=12, pady=(10,6), sticky="w")
        self._s1_platform_btns: Dict[str, ctk.CTkButton] = {}
        self._s1_sel_platform = None
        self._s1_sel_color = "#1565C0"
        self._s1_sel_hint = ""

        for label, pid, color, hint in DOWNLOAD_PLATFORMS:
            btn = ctk.CTkButton(pl_row, text=label, width=108, height=32,
                                fg_color=("gray70","gray30"),
                                hover_color=(color, color),
                                text_color=("gray20","gray90"), corner_radius=8,
                                command=lambda p=pid, c=color, h=hint: self._s1_select_platform(p, c, h))
            btn.pack(side="left", padx=3)
            self._s1_platform_btns[pid] = btn

        # URL + download
        url_row = ctk.CTkFrame(dl_card, fg_color="transparent")
        url_row.grid(row=1, column=0, padx=12, pady=(0,4), sticky="ew")
        dl_card.grid_columnconfigure(0, weight=1)
        url_row.grid_columnconfigure(0, weight=1)

        self._s1_url_var = tk.StringVar()
        self._s1_url_entry = ctk.CTkEntry(url_row, textvariable=self._s1_url_var,
                                          placeholder_text="① Chọn nền tảng  →  ② Dán link  →  ③ Nhấn Tải về",
                                          state="disabled", height=34)
        self._s1_url_entry.grid(row=0, column=0, padx=(0,8), sticky="ew")
        self._s1_url_entry.bind("<Return>", lambda _: self._s1_download())
        self._s1_url_entry.bind("<<Paste>>", lambda _: self.after(30, self._s1_auto_extract))

        self._s1_dl_btn = ctk.CTkButton(url_row, text="⬇  Tải về", width=110, height=34,
                                         state="disabled", fg_color=("gray60","gray35"),
                                         command=self._s1_download)
        self._s1_dl_btn.grid(row=0, column=1, padx=(0,8))

        has_ck = bool(_find_saved_cookies())
        self._s1_cookie_btn = ctk.CTkButton(
            url_row, text="🍪 Cookies ✓" if has_ck else "🍪 Cookies",
            width=120, height=34,
            fg_color="#4CAF50" if has_ck else ("gray60","gray35"),
            command=self._s1_manage_cookies)
        self._s1_cookie_btn.grid(row=0, column=2)

        self._s1_dl_hint = ctk.CTkLabel(dl_card, text="",
                                         font=ctk.CTkFont(size=11),
                                         text_color=("gray50","gray60"), anchor="w")
        self._s1_dl_hint.grid(row=2, column=0, padx=14, pady=(0,8), sticky="w")

        # ── C: Settings card ─────────────────────────────────────────────────
        cfg_outer, cfg_card = self._card(scroll, "⚙️  Cài đặt nhận dạng")
        cfg_outer.grid(row=2, column=0, sticky="ew", padx=6, pady=4)
        cfg_card.grid_columnconfigure(1, weight=1)

        r = 0
        for label, attr, values, default in [
            ("Ngôn ngữ gốc:",           "_s1_lang_var",  list(LANGUAGES.keys()),      "Tiếng Trung (Giản thể)"),
            ("Mô hình Whisper (STT):",  "_s1_model_var", list(WHISPER_MODELS.keys()), "small — cân bằng hơn"),
        ]:
            ctk.CTkLabel(cfg_card, text=label, font=ctk.CTkFont(weight="bold"),
                         width=120).grid(row=r, column=0, padx=12, pady=8, sticky="w")
            var = ctk.StringVar(value=default)
            setattr(self, attr, var)
            ctk.CTkOptionMenu(cfg_card, variable=var, values=values, width=280
                              ).grid(row=r, column=1, padx=6, pady=8, sticky="w")
            r += 1

        # ── D: Logo card ──────────────────────────────────────────────────────
        lo_outer, lo_card = self._card(scroll, "🔲  Logo / Watermark")
        lo_outer.grid(row=3, column=0, sticky="ew", padx=6, pady=4)
        lo_card.grid_columnconfigure(1, weight=1)

        self._logo_path: Optional[str] = None
        self._logo_enabled = tk.BooleanVar(value=False)

        lo_row1 = ctk.CTkFrame(lo_card, fg_color="transparent")
        lo_row1.grid(row=0, column=0, columnspan=3, padx=14, pady=(10,4), sticky="ew")
        lo_row1.grid_columnconfigure(1, weight=1)

        ctk.CTkCheckBox(lo_row1, text="Thêm logo vào video",
                        variable=self._logo_enabled,
                        font=ctk.CTkFont(size=13)).grid(row=0, column=0, sticky="w")

        self._logo_lbl = ctk.CTkLabel(
            lo_row1, text="  Chưa chọn ảnh logo...",
            anchor="w", fg_color=("gray82","gray22"), corner_radius=6, height=28)
        self._logo_lbl.grid(row=0, column=1, padx=(12,6), sticky="ew")

        ctk.CTkButton(lo_row1, text="📂", width=36, height=28,
                      command=self._pick_logo).grid(row=0, column=2)

        lo_row2 = ctk.CTkFrame(lo_card, fg_color="transparent")
        lo_row2.grid(row=1, column=0, columnspan=3, padx=14, pady=(0,4), sticky="w")

        ctk.CTkLabel(lo_row2, text="🌫  Độ mờ:",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0,6))
        self._logo_opacity = tk.IntVar(value=30)
        self._logo_op_lbl = ctk.CTkLabel(lo_row2, text="30%", width=40,
                                          font=ctk.CTkFont(size=11, weight="bold"))
        self._logo_op_lbl.pack(side="left")
        ctk.CTkSlider(lo_row2, from_=1, to=100, variable=self._logo_opacity,
                      width=160, command=lambda v: self._logo_op_lbl.configure(
                          text=f"{int(v)}%")).pack(side="left", padx=(0,20))

        ctk.CTkLabel(lo_row2, text="📐  Kích thước:",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0,6))
        self._logo_size = tk.IntVar(value=120)
        self._logo_sz_lbl = ctk.CTkLabel(lo_row2, text="120px", width=50,
                                          font=ctk.CTkFont(size=11, weight="bold"))
        self._logo_sz_lbl.pack(side="left")
        ctk.CTkSlider(lo_row2, from_=20, to=400, variable=self._logo_size,
                      width=160, command=lambda v: self._logo_sz_lbl.configure(
                          text=f"{int(v)}px")).pack(side="left")

        ctk.CTkLabel(lo_card,
                     text="💡 Logo di chuyển từ góc trên phải → góc dưới trái suốt video",
                     font=ctk.CTkFont(size=10), text_color=("gray50","gray55"), anchor="w",
                     ).grid(row=2, column=0, columnspan=3, padx=14, pady=(0,8), sticky="w")

        # ── E: Progress + action ──────────────────────────────────────────────
        act = ctk.CTkFrame(scroll, fg_color="transparent")
        act.grid(row=4, column=0, padx=6, pady=(8, 16), sticky="ew")
        act.grid_columnconfigure(1, weight=1)

        self._s1_start_btn = ctk.CTkButton(
            act, text="▶  Bắt đầu quét",
            font=ctk.CTkFont(size=14, weight="bold"), height=44, width=180,
            fg_color="#1565C0", hover_color="#0D47A1",
            command=self._s1_start)
        self._s1_start_btn.grid(row=0, column=0, padx=(0,16), pady=4)

        prog_col = ctk.CTkFrame(act, fg_color="transparent")
        prog_col.grid(row=0, column=1, sticky="ew")
        prog_col.grid_columnconfigure(0, weight=1)

        self._s1_status = ctk.CTkLabel(prog_col, text="",
                                        font=ctk.CTkFont(size=12), anchor="w")
        self._s1_status.grid(row=0, column=0, sticky="ew")

        self._s1_bar = ctk.CTkProgressBar(prog_col)
        self._s1_bar.set(0)
        self._s1_bar.grid(row=1, column=0, sticky="ew", pady=(2,0))

        self._s1_next_btn = ctk.CTkButton(
            act, text="Bước 2 →",
            font=ctk.CTkFont(size=13, weight="bold"), height=44, width=130,
            fg_color="#2E7D32", hover_color="#1B5E20", state="disabled",
            command=self._s1_to_step2)
        self._s1_next_btn.grid(row=0, column=2, padx=(16,0), pady=4)

    # ── Step 1 logic ──────────────────────────────────────────────────────────

    def _s1_pick_file(self):
        path = filedialog.askopenfilename(
            title="Chọn file video",
            filetypes=[("Video", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.webm *.m4v *.ts"),
                       ("Tất cả", "*.*")])
        if path:
            self.video_path = path
            self._s1_file_lbl.configure(text=f"  {os.path.basename(path)}")

    def _s1_select_platform(self, pid: str, color: str, hint: str):
        self._s1_sel_platform = pid
        self._s1_sel_color    = color
        self._s1_sel_hint     = hint
        for p, b in self._s1_platform_btns.items():
            if p == pid:
                b.configure(fg_color=color, text_color="white",
                            font=ctk.CTkFont(weight="bold"))
            else:
                b.configure(fg_color=("gray70","gray30"),
                            text_color=("gray20","gray90"),
                            font=ctk.CTkFont(weight="normal"))
        self._s1_url_entry.configure(state="normal", placeholder_text=hint)
        self._s1_dl_btn.configure(state="normal", fg_color=color)
        self._s1_url_var.set("")
        self._s1_url_entry.focus_set()

    def _s1_auto_extract(self):
        raw = self._s1_url_var.get().strip()
        if not raw or (raw.startswith("http") and " " not in raw):
            return
        extracted = extract_url(raw)
        if extracted:
            self._s1_url_var.set(extracted)
            self._s1_dl_hint.configure(text=f"✓  Đã trích xuất: {extracted}",
                                        text_color="#4CAF50")

    def _s1_download(self):
        raw = self._s1_url_var.get().strip()
        if not raw:
            messagebox.showwarning("Thiếu link", "Dán link video vào ô trước!")
            return
        url = extract_url(raw) or raw
        if not url.startswith("http"):
            messagebox.showerror("Lỗi", "Không tìm được link hợp lệ!")
            return
        self._s1_url_var.set(url)
        out_dir = os.path.join(os.path.expanduser("~"), "Downloads", "VideoTranslatorVI")
        self._s1_dl_btn.configure(state="disabled", text="Đang tải...")
        self._s1_url_entry.configure(state="disabled")
        self._s1_set(f"Đang kết nối tới {detect_platform(url)}...", 0.02)
        threading.Thread(target=self._s1_run_download,
                         args=(url, out_dir), daemon=True).start()

    def _s1_run_download(self, url: str, out_dir: str):
        try:
            path = download_video(url, out_dir, self._s1_set)
            self.video_path = path
            name = os.path.basename(path)
            self.after(0, lambda: self._s1_file_lbl.configure(text=f"  {name}"))
            self.after(0, lambda: self._s1_dl_hint.configure(
                text=f"✅  Đã tải: {name}", text_color="#4CAF50"))
            self._s1_set("✅  Tải xong — nhấn 'Bắt đầu quét'", 1.0)
        except Exception as exc:
            err = str(exc)
            self.after(0, lambda: messagebox.showerror("Lỗi tải video", err))
            self._s1_set(f"❌  {err[:80]}", 0)
        finally:
            self.after(0, lambda: self._s1_dl_btn.configure(state="normal", text="⬇  Tải về"))
            self.after(0, lambda: self._s1_url_entry.configure(state="normal"))

    def _s1_manage_cookies(self):
        has = bool(_find_saved_cookies())
        if has:
            action = messagebox.askyesnocancel("Cookies",
                "Đã có cookies.\n\nYes = thay mới  |  No = xóa  |  Cancel = đóng")
            if action is None:
                return
            if action is False:
                from downloader import clear_cookies_file
                clear_cookies_file()
                self._s1_cookie_btn.configure(text="🍪 Cookies",
                                               fg_color=("gray60","gray35"))
                return
        else:
            messagebox.showinfo("Hướng dẫn",
                "Để tải Douyin/RedNote cần cookies:\n\n"
                "1. Cài 'Get cookies.txt LOCALLY' trên Chrome\n"
                "2. Vào douyin.com, nhấn extension → Export\n"
                "3. Nhấn OK rồi chọn file cookies.txt")
        path = filedialog.askopenfilename(title="Chọn cookies.txt",
                                          filetypes=[("Cookies","*.txt"),("Tất cả","*.*")])
        if path:
            save_cookies_file(path)
            self._s1_cookie_btn.configure(text="🍪 Cookies ✓", fg_color="#4CAF50")

    def _s1_start(self):
        if not self.video_path:
            messagebox.showwarning("Chưa có video", "Hãy chọn file hoặc tải video trước!")
            return
        if self._processing:
            return
        self._processing = True
        self._s1_start_btn.configure(state="disabled")
        self._s1_next_btn.configure(state="disabled")
        threading.Thread(target=self._s1_pipeline, daemon=True).start()

    def _s1_pipeline(self):
        try:
            lang_name   = self._s1_lang_var.get()
            _, wh_lang  = LANGUAGES[lang_name]
            model_size  = WHISPER_MODELS[self._s1_model_var.get()]

            from transcriber import transcribe_video
            segments = transcribe_video(
                self.video_path, model_size=model_size,
                language=wh_lang, progress_callback=self._s1_set)

            self.subtitle_entries = whisper_to_entries(segments)

            if not self.subtitle_entries:
                raise RuntimeError("Không nhận dạng được giọng nói trong video.")

            self._s1_set(f"✅  Nhận dạng xong — {len(self.subtitle_entries)} câu. Đang chuyển sang bước 2...", 1.0)
            self._step_done[0] = True
            self.after(800, self._s1_to_step2)

        except Exception as exc:
            err = str(exc)
            self._s1_set(f"❌  Lỗi: {err[:100]}", 0)
            self.after(0, lambda: messagebox.showerror("Lỗi xử lý", err))
        finally:
            self._processing = False
            self.after(0, lambda: self._s1_start_btn.configure(state="normal"))

    def _s1_to_step2(self):
        self._show_step(2)
        if self.subtitle_entries and not any(e.translated_text for e in self.subtitle_entries):
            self.after(400, self._s2_auto_translate)
        else:
            self._s2_refresh_table()

    def _s1_set(self, msg: str, prog: float):
        self.after(0, lambda: self._s1_status.configure(text=msg))
        self.after(0, lambda: self._s1_bar.set(min(1.0, max(0.0, prog))))

    # =========================================================================
    #  STEP 2 — EDITOR & TRANSLATION
    # =========================================================================

    def _build_step2(self, parent: ctk.CTkFrame):
        parent.grid_rowconfigure(1, weight=1)

        # ── Header + translation status ───────────────────────────────────────
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        top.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(top, text="Bước 2 — Biên tập & Dịch thuật",
                     font=ctk.CTkFont(size=16, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, sticky="w")

        self._s2_trans_lbl = ctk.CTkLabel(top, text="",
                                           font=ctk.CTkFont(size=11),
                                           text_color=("gray50","gray60"), anchor="e")
        self._s2_trans_lbl.grid(row=0, column=1, sticky="e")

        self._s2_trans_bar = ctk.CTkProgressBar(top, width=200)
        self._s2_trans_bar.set(0)
        self._s2_trans_bar_visible = False

        # ── Subtitle table ────────────────────────────────────────────────────
        tbl_wrap = ctk.CTkFrame(parent)
        tbl_wrap.grid(row=1, column=0, sticky="nsew", padx=10, pady=2)
        tbl_wrap.grid_columnconfigure(0, weight=1)
        tbl_wrap.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        for name, cfg_args in [
            ("S2.Treeview", dict(background="#1e1e2e", foreground="#cdd6f4",
                                  fieldbackground="#1e1e2e", rowheight=50,
                                  font=("Segoe UI", 10))),
            ("S2.Treeview.Heading", dict(background="#1f538d", foreground="white",
                                          font=("Segoe UI", 10, "bold"))),
        ]:
            style.configure(name, **cfg_args)
        style.map("S2.Treeview", background=[("selected","#313244")])

        self._s2_tree = ttk.Treeview(
            tbl_wrap, style="S2.Treeview",
            columns=("no","time","original","vietnamese"),
            show="headings", selectmode="browse")
        self._s2_tree.heading("no",         text="#",    anchor="center")
        self._s2_tree.heading("time",       text="Thời gian", anchor="center")
        self._s2_tree.heading("original",   text="Văn bản gốc")
        self._s2_tree.heading("vietnamese", text="✏️  Văn bản dịch tiếng Việt  (click đôi để sửa)")
        self._s2_tree.column("no",         width=44,  minwidth=36,  anchor="center", stretch=False)
        self._s2_tree.column("time",       width=150, minwidth=120, anchor="center", stretch=False)
        self._s2_tree.column("original",   width=310, minwidth=140)
        self._s2_tree.column("vietnamese", width=340, minwidth=140)

        vsb = ttk.Scrollbar(tbl_wrap, orient="vertical", command=self._s2_tree.yview)
        self._s2_tree.configure(yscrollcommand=vsb.set)
        self._s2_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._s2_tree.tag_configure("odd",  background="#181825")
        self._s2_tree.tag_configure("even", background="#1e1e2e")

        self._s2_tree.bind("<<TreeviewSelect>>", self._s2_on_select)
        self._s2_tree.bind("<Double-1>",         self._s2_on_dblclick)

        # ── Edit panel ────────────────────────────────────────────────────────
        ep = ctk.CTkFrame(parent, height=80)
        ep.grid(row=2, column=0, sticky="ew", padx=10, pady=2)
        ep.grid_propagate(False)
        ep.grid_columnconfigure(1, weight=1)

        nav_f = ctk.CTkFrame(ep, fg_color="transparent")
        nav_f.grid(row=0, column=0, columnspan=3, padx=10, pady=(4,2), sticky="w")
        self._s2_sel_lbl = ctk.CTkLabel(nav_f, text="Click vào một hàng để sửa",
                                         font=ctk.CTkFont(size=11),
                                         text_color=("gray50","gray60"))
        self._s2_sel_lbl.pack(side="left", padx=(0,10))
        ctk.CTkButton(nav_f, text="◀", width=28, height=22,
                      fg_color=("gray65","gray35"),
                      command=lambda: self._s2_navigate(-1)).pack(side="left", padx=2)
        ctk.CTkButton(nav_f, text="▶", width=28, height=22,
                      fg_color=("gray65","gray35"),
                      command=lambda: self._s2_navigate(1)).pack(side="left", padx=2)

        ctk.CTkLabel(ep, text="Dịch:", width=44,
                     font=ctk.CTkFont(weight="bold")
                     ).grid(row=1, column=0, padx=(10,4), pady=(2,6), sticky="w")
        self._s2_edit_var = tk.StringVar()
        self._s2_edit_entry = ctk.CTkEntry(ep, textvariable=self._s2_edit_var,
                                            font=ctk.CTkFont(size=12))
        self._s2_edit_entry.grid(row=1, column=1, padx=4, pady=(2,6), sticky="ew")
        self._s2_edit_entry.bind("<Return>", lambda _: self._s2_save_and_next())
        self._s2_edit_entry.bind("<Tab>",    lambda _: self._s2_save_and_next())
        ctk.CTkButton(ep, text="💾  Lưu", width=80, height=28,
                      fg_color="#2E7D32", hover_color="#1B5E20",
                      command=self._s2_save_current
                      ).grid(row=1, column=2, padx=(4,10), pady=(2,6))

        # ── Subtitle bubble preview ───────────────────────────────────────────
        bubble_outer = ctk.CTkFrame(
            parent,
            fg_color=("gray88", "#1a1a2e"),
            corner_radius=12,
        )
        bubble_outer.grid(row=3, column=0, sticky="ew", padx=10, pady=(2, 2))
        bubble_outer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            bubble_outer,
            text="💬  Xem trước bản dịch",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray50", "gray60"),
            anchor="w",
        ).grid(row=0, column=0, padx=14, pady=(8, 0), sticky="w")

        self._s2_bubble = SubtitleBubble(bubble_outer, max_width=700)
        self._s2_bubble.grid(row=1, column=0, sticky="ew")

        # ── Voice / volume settings ───────────────────────────────────────────
        vset_outer, vset = self._card(parent, "🎙  Cài đặt lồng tiếng AI")
        vset_outer.grid(row=4, column=0, sticky="ew", padx=10, pady=(2,4))
        vset.grid_columnconfigure(1, weight=1)
        vset.grid_columnconfigure(3, weight=1)

        # ── Row 0: Giọng đọc (edge-tts mặc định) ─────────────────────────────
        ctk.CTkLabel(vset, text="Giọng đọc:", font=ctk.CTkFont(size=13, weight="bold"),
                     width=100).grid(row=0, column=0, padx=(14,8), pady=(12,6), sticky="w")

        # Nữ / Nam toggle buttons
        voice_toggle = ctk.CTkFrame(vset, fg_color="transparent")
        voice_toggle.grid(row=0, column=1, padx=0, pady=(12,6), sticky="w")

        self._s2_voice_var = ctk.StringVar(value="vi-VN-NamMinhNeural")
        self._s2_voice_lbl = ctk.StringVar(value="Nữ — HoaiMy")

        self._btn_female = ctk.CTkButton(
            voice_toggle,
            text="♀  Nữ — HoaiMy",
            width=170, height=38,
            font=ctk.CTkFont(size=13),
            fg_color=("gray60","gray35"), hover_color=("#1565C0","#0D47A1"),
            corner_radius=8,
            command=lambda: self._s2_set_voice("vi-VN-HoaiMyNeural", "Nữ — HoaiMy"),
        )
        self._btn_female.pack(side="left", padx=(0, 6))

        self._btn_male = ctk.CTkButton(
            voice_toggle,
            text="♂  Nam — NamMinh",
            width=170, height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1565C0", hover_color="#0D47A1",
            corner_radius=8,
            command=lambda: self._s2_set_voice("vi-VN-NamMinhNeural", "Nam — NamMinh"),
        )
        self._btn_male.pack(side="left")

        # Badge: Microsoft Edge TTS (miễn phí)
        ctk.CTkLabel(
            vset,
            text="Google TTS + Edge TTS  •  Miễn phí  •  Không cần API key",
            font=ctk.CTkFont(size=10),
            text_color=("#2E7D32","#4CAF50"),
        ).grid(row=0, column=2, columnspan=2, padx=(20,14), pady=(12,6), sticky="w")

        # ── Row 1: Advanced engine (ẩn theo mặc định) ─────────────────────────
        adv_toggle = ctk.CTkFrame(vset, fg_color="transparent")
        adv_toggle.grid(row=1, column=0, columnspan=4, padx=14, pady=(0,4), sticky="w")

        self._adv_visible = False
        self._adv_btn = ctk.CTkButton(
            adv_toggle, text="⚙  Dùng engine khác (OpenAI / FPT.AI)",
            height=26, width=280,
            font=ctk.CTkFont(size=11),
            fg_color="transparent", hover_color=("gray80","gray25"),
            text_color=("gray50","gray60"),
            border_width=1, border_color=("gray70","gray40"),
            command=self._s2_toggle_advanced,
        )
        self._adv_btn.pack(side="left")

        self._adv_frame = ctk.CTkFrame(vset, fg_color="transparent")
        self._adv_frame.grid(row=2, column=0, columnspan=4, padx=14, pady=(0,4), sticky="ew")
        self._adv_frame.grid_columnconfigure(1, weight=1)
        self._adv_frame.grid_remove()

        ctk.CTkLabel(self._adv_frame, text="Engine:", width=70,
                     font=ctk.CTkFont(size=11, weight="bold")
                     ).grid(row=0, column=0, padx=(0,6), pady=4, sticky="w")
        self._s2_engine_var = ctk.StringVar(value=list(TTS_PROVIDERS.keys())[0])
        self._s2_engine_menu = ctk.CTkOptionMenu(
            self._adv_frame, variable=self._s2_engine_var,
            values=list(TTS_PROVIDERS.keys()), width=280,
            command=self._s2_on_engine_change)
        self._s2_engine_menu.grid(row=0, column=1, padx=(0,8), pady=4, sticky="w")

        ctk.CTkLabel(self._adv_frame, text="Giọng:", width=70,
                     font=ctk.CTkFont(size=11, weight="bold")
                     ).grid(row=1, column=0, padx=(0,6), pady=(0,4), sticky="w")
        _dv = list(PROVIDER_VOICES["edge"].keys())
        self._s2_adv_voice_menu = ctk.CTkOptionMenu(
            self._adv_frame, variable=self._s2_voice_var,
            values=_dv, width=260)
        self._s2_adv_voice_menu.grid(row=1, column=1, padx=(0,8), pady=(0,4), sticky="w")

        # ── Row 3: Volume + Speed sliders ─────────────────────────────────────
        vol_frame = ctk.CTkFrame(vset, fg_color="transparent")
        vol_frame.grid(row=3, column=0, columnspan=4, padx=14, pady=(4,12), sticky="ew")
        vol_frame.grid_columnconfigure((1, 3), weight=1)

        # Volume sliders
        for col, (lbl, attr, default, max_val) in enumerate([
            ("🔊  Âm lượng gốc:",        "_s2_orig_vol",   5, 100),
            ("🎤  Âm lượng lồng tiếng:", "_s2_dub_vol",  100, 200),
        ]):
            c0 = col * 2
            ctk.CTkLabel(vol_frame, text=lbl, font=ctk.CTkFont(size=11)
                         ).grid(row=0, column=c0, padx=(0, 8), sticky="w")
            var = tk.IntVar(value=default)
            setattr(self, attr, var)
            val_lbl = ctk.CTkLabel(vol_frame, text=f"{default}%", width=48,
                                   font=ctk.CTkFont(size=11, weight="bold"))
            val_lbl.grid(row=0, column=c0 + 1, sticky="w")
            ctk.CTkSlider(
                vol_frame, from_=0, to=max_val, variable=var, width=200,
                command=lambda v, r=val_lbl: r.configure(text=f"{int(v)}%"),
            ).grid(row=0, column=c0 + 1, padx=(48, 20 if col == 0 else 0), sticky="ew")

        # ── Speed slider ────────────────────────────────────────────────────────
        ctk.CTkFrame(vol_frame, height=1, fg_color=("gray75","gray35")
                     ).grid(row=1, column=0, columnspan=4, padx=0, pady=(8,6), sticky="ew")

        ctk.CTkLabel(vol_frame, text="⚡  Tốc độ lồng tiếng:", font=ctk.CTkFont(size=11)
                     ).grid(row=2, column=0, padx=(0,8), sticky="w")

        self._s2_dub_speed = tk.IntVar(value=100)
        speed_lbl = ctk.CTkLabel(vol_frame, text="100%  (bình thường)", width=140,
                                  font=ctk.CTkFont(size=11, weight="bold"))
        speed_lbl.grid(row=2, column=1, sticky="w")

        def _on_speed(v):
            pct = int(float(v))
            if pct < 80:   hint = "rất chậm"
            elif pct < 95: hint = "chậm"
            elif pct <= 105: hint = "bình thường"
            elif pct <= 130: hint = "nhanh"
            else:           hint = "rất nhanh"
            speed_lbl.configure(text=f"{pct}%  ({hint})")

        ctk.CTkSlider(
            vol_frame, from_=50, to=200, variable=self._s2_dub_speed,
            number_of_steps=150, width=200,
            command=_on_speed,
        ).grid(row=2, column=1, padx=(48, 0), columnspan=3, sticky="ew")

        # ── Navigation ────────────────────────────────────────────────────────
        nav = ctk.CTkFrame(parent, fg_color="transparent")
        nav.grid(row=5, column=0, sticky="ew", padx=10, pady=(4,10))

        ctk.CTkButton(nav, text="← Bước 1", width=110, height=36,
                      fg_color=("gray65","gray35"), hover_color=("gray55","gray45"),
                      command=self._go_back).pack(side="left")

        ctk.CTkLabel(nav, text="", width=1).pack(side="left", expand=True, fill="x")

        self._s2_count_lbl = ctk.CTkLabel(nav, text="",
                                           font=ctk.CTkFont(size=11),
                                           text_color=("gray50","gray60"))
        self._s2_count_lbl.pack(side="left", padx=10)

        ctk.CTkButton(
            nav, text="👁  Xem trước phụ đề",
            height=36, width=160,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("#00695C","#004D40"), hover_color=("#00796B","#00695C"),
            command=self._s2_open_preview,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(nav, text="Bước 3 →", width=130, height=36,
                      font=ctk.CTkFont(weight="bold"),
                      fg_color="#1565C0", hover_color="#0D47A1",
                      command=self._go_next).pack(side="right")

    # ── Step 2 logic ──────────────────────────────────────────────────────────

    def _s2_open_preview(self):
        if not self.subtitle_entries:
            messagebox.showwarning("Chưa có phụ đề", "Hãy chạy nhận dạng và dịch trước!")
            return
        if not self.video_path:
            messagebox.showwarning("Chưa có video", "Hãy chọn video ở Bước 1!")
            return
        self._open_preview_window()

    def _s2_auto_translate(self):
        if self._processing or not self.subtitle_entries:
            return
        self._processing = True
        self._s2_trans_lbl.configure(text="⏳ Đang dịch...")
        self._s2_trans_bar.set(0)
        if not self._s2_trans_bar_visible:
            self._s2_trans_bar.grid(row=1, column=1, padx=6, pady=2, sticky="ew")
            self._s2_trans_bar_visible = True
        threading.Thread(target=self._s2_translate_pipeline, daemon=True).start()

    def _s2_translate_pipeline(self):
        try:
            lang_name  = self._s1_lang_var.get()
            trans_lang, _ = LANGUAGES[lang_name]
            provider   = self._api_cfg.get("provider", "google")
            api_key    = self._api_cfg.get(
                "openai_api_key" if provider == "openai" else "anthropic_api_key", "")
            ai_model   = self._api_cfg.get(
                "openai_model" if provider == "openai" else "anthropic_model", "")

            def _cb(msg, prog):
                # Find latest translated entry to show in bubble
                last = next(
                    (e for e in reversed(self.subtitle_entries) if e.translated_text),
                    None,
                )
                self.after(0, lambda m=msg, p=prog, e=last: (
                    self._s2_trans_lbl.configure(text=m),
                    self._s2_trans_bar.set(p),
                    self._s2_bubble.set_text(
                        e.translated_text if e else "Đang dịch…",
                        index=self.subtitle_entries.index(e) + 1 if e else 0,
                        total=len(self.subtitle_entries),
                        start=e.start_time if e else "",
                        end=e.end_time if e else "",
                    ) if e else None,
                ))

            translate_entries(self.subtitle_entries, source_lang=trans_lang,
                              target_lang="vi", provider=provider,
                              api_key=api_key, model=ai_model,
                              progress_callback=_cb)

            self._step_done[1] = True
            self.after(0, lambda: self._s2_trans_lbl.configure(
                text=f"✅  Dịch xong {len(self.subtitle_entries)} câu"))
            self.after(0, self._s2_refresh_table)
        except Exception as exc:
            err = str(exc)
            self.after(0, lambda: self._s2_trans_lbl.configure(
                text=f"❌  Lỗi dịch: {err[:80]}"))
        finally:
            self._processing = False
            if self._s2_trans_bar_visible:
                self.after(2000, self._s2_hide_trans_bar)

    def _s2_hide_trans_bar(self):
        self._s2_trans_bar.grid_forget()
        self._s2_trans_bar_visible = False

    def _s2_refresh_table(self):
        for item in self._s2_tree.get_children():
            self._s2_tree.delete(item)
        for i, e in enumerate(self.subtitle_entries):
            ts   = f"{e.start_time[:8]}  →  {e.end_time[:8]}"
            orig = e.original_text.replace("\n"," ")
            vi   = e.translated_text.replace("\n"," ")
            tag  = "odd" if i % 2 else "even"
            self._s2_tree.insert("","end", values=(i + 1, ts, orig, vi), tags=(tag,))
        cnt = len(self.subtitle_entries)
        self._s2_count_lbl.configure(text=f"{cnt} câu phụ đề")

    def _s2_on_select(self, _evt=None):
        sel = self._s2_tree.selection()
        if not sel:
            return
        idx = self._s2_tree.index(sel[0])
        self._selected_row = idx
        e = self.subtitle_entries[idx]
        total = len(self.subtitle_entries)
        self._s2_sel_lbl.configure(
            text=f"Câu {idx+1}/{total}  —  {e.start_time[:8]} → {e.end_time[:8]}")
        self._s2_edit_var.set(e.translated_text)
        self._s2_edit_entry.focus_set()
        self._s2_edit_entry.icursor(tk.END)
        # Update bubble
        self._s2_bubble.restore_color()
        self._s2_bubble.set_text(
            e.translated_text or e.original_text,
            index=idx + 1, total=total,
            start=e.start_time, end=e.end_time,
        )

    def _s2_on_dblclick(self, event):
        col = self._s2_tree.identify_column(event.x)
        if col != "#4":
            return
        row_id = self._s2_tree.identify_row(event.y)
        if not row_id:
            return
        idx = self._s2_tree.index(row_id)

        def on_save(new_text: str):
            self.subtitle_entries[idx].translated_text = new_text
            vals = list(self._s2_tree.item(row_id,"values"))
            vals[3] = new_text
            self._s2_tree.item(row_id, values=vals)

        _CellEditor(self._s2_tree, row_id, "#4", on_save)

    def _s2_save_current(self):
        if self._selected_row < 0:
            return
        new_text = self._s2_edit_var.get()
        self.subtitle_entries[self._selected_row].translated_text = new_text
        # Reflect edit instantly in bubble
        e = self.subtitle_entries[self._selected_row]
        self._s2_bubble.restore_color()
        self._s2_bubble.set_text(
            new_text, index=self._selected_row + 1,
            total=len(self.subtitle_entries),
            start=e.start_time, end=e.end_time,
        )
        items = self._s2_tree.get_children()
        if self._selected_row < len(items):
            row_id = items[self._selected_row]
            vals   = list(self._s2_tree.item(row_id,"values"))
            vals[3] = new_text
            self._s2_tree.item(row_id, values=vals)

    def _s2_save_and_next(self):
        self._s2_save_current()
        self._s2_navigate(1)

    def _s2_navigate(self, delta: int):
        n = len(self.subtitle_entries)
        if n == 0:
            return
        new_idx = max(0, min(n-1, self._selected_row + delta))
        items = self._s2_tree.get_children()
        if new_idx < len(items):
            self._s2_tree.selection_set(items[new_idx])
            self._s2_tree.see(items[new_idx])

    def _s2_set_voice(self, voice_id: str, label: str):
        """Toggle between Nữ/Nam edge-tts voices with visual button feedback."""
        self._s2_voice_var.set(voice_id)
        is_female = "HoaiMy" in voice_id
        self._btn_female.configure(
            fg_color="#1565C0" if is_female else ("gray60","gray35"),
            font=ctk.CTkFont(size=13, weight="bold" if is_female else "normal"),
        )
        self._btn_male.configure(
            fg_color="#1565C0" if not is_female else ("gray60","gray35"),
            font=ctk.CTkFont(size=13, weight="bold" if not is_female else "normal"),
        )

    def _s2_toggle_advanced(self):
        """Show/hide the advanced engine selector."""
        self._adv_visible = not self._adv_visible
        if self._adv_visible:
            self._adv_frame.grid()
            self._adv_btn.configure(text="⚙  Ẩn cài đặt nâng cao")
        else:
            self._adv_frame.grid_remove()
            self._adv_btn.configure(text="⚙  Dùng engine khác (OpenAI / FPT.AI)")

    def _s2_on_engine_change(self, label: str):
        pid    = TTS_PROVIDERS.get(label, "edge")
        voices = list(PROVIDER_VOICES[pid].keys())
        self._s2_voice_var.set(voices[0])
        # _s2_adv_voice_menu là widget trong advanced frame
        self._s2_adv_voice_menu.configure(values=voices)

    # =========================================================================
    #  STEP 3 — RENDER & PREVIEW
    # =========================================================================

    def _build_step3(self, parent: ctk.CTkFrame):
        parent.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(parent, text="Bước 3 — Kết xuất & Xem trước",
                     font=ctk.CTkFont(size=16, weight="bold"), anchor="w"
                     ).grid(row=0, column=0, padx=20, pady=(12,4), sticky="ew")

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        scroll.grid_columnconfigure(0, weight=1)

        # ── Quick preview card ────────────────────────────────────────────────
        qp_outer, qp_card = self._card(scroll, "👁  Xem trước trước khi xuất")
        qp_outer.grid(row=0, column=0, sticky="ew", padx=6, pady=4)
        qp_card.grid_columnconfigure((0,1,2), weight=1)

        ctk.CTkLabel(
            qp_card,
            text="Kiểm tra phụ đề và lồng tiếng trước khi bắt đầu xuất video.",
            font=ctk.CTkFont(size=11), text_color=("gray50","gray60"), anchor="w",
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(8,6), sticky="ew")

        ctk.CTkButton(
            qp_card, text="📝  Xem trước phụ đề",
            height=38, font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("#00695C","#004D40"), hover_color=("#00796B","#00695C"),
            command=self._open_preview_window,
        ).grid(row=1, column=0, padx=(12,4), pady=(0,12), sticky="ew")

        ctk.CTkButton(
            qp_card, text="🎙  Xem trước lồng tiếng",
            height=38, font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("#6A1B9A","#4A148C"), hover_color=("#7B1FA2","#38006b"),
            command=self._open_preview_with_dub,
        ).grid(row=1, column=1, padx=4, pady=(0,12), sticky="ew")

        ctk.CTkButton(
            qp_card, text="▶  Mở trong VLC",
            height=38, font=ctk.CTkFont(size=12),
            fg_color=("#1565C0","#0D47A1"), hover_color=("#0D47A1","#082a60"),
            command=self._open_vlc_with_subs,
        ).grid(row=1, column=2, padx=(4,12), pady=(0,12), sticky="ew")

        # ── Style card ────────────────────────────────────────────────────────
        sc_outer, style_card = self._card(scroll, "🎨  Kiểu hiển thị phụ đề")
        sc_outer.grid(row=1, column=0, sticky="ew", padx=6, pady=4)
        style_card.grid_columnconfigure(0, weight=1)

        self._s3_style_var = ctk.StringVar(value=DEFAULT_STYLE)
        self._s3_style_btns: Dict[str, ctk.CTkButton] = {}

        style_grid = ctk.CTkFrame(style_card, fg_color="transparent")
        style_grid.grid(row=0, column=0, padx=10, pady=(6,10), sticky="ew")
        style_names = list(STYLES.keys())
        for i, name in enumerate(style_names):
            r, c = divmod(i, 4)
            btn = ctk.CTkButton(
                style_grid, text=name, height=32, width=130,
                font=ctk.CTkFont(size=10), corner_radius=8,
                fg_color=("gray72","gray28"), hover_color=("gray62","gray38"),
                command=lambda n=name: self._s3_select_style(n))
            btn.grid(row=r, column=c, padx=4, pady=3, sticky="ew")
            style_grid.grid_columnconfigure(c, weight=1)
            self._s3_style_btns[name] = btn
        self._s3_select_style(DEFAULT_STYLE)

        # Font size
        fs_row = ctk.CTkFrame(style_card, fg_color="transparent")
        fs_row.grid(row=1, column=0, padx=14, pady=(0,10), sticky="w")
        ctk.CTkLabel(fs_row, text="Cỡ chữ:", font=ctk.CTkFont(weight="bold")
                     ).pack(side="left", padx=(0,8))
        self._s3_font_size = tk.IntVar(value=9)
        self._s3_fs_lbl = ctk.CTkLabel(fs_row, text="9 px", width=48)
        self._s3_fs_lbl.pack(side="right")
        ctk.CTkSlider(fs_row, from_=10, to=36, variable=self._s3_font_size,
                      width=200, number_of_steps=26,
                      command=lambda v: self._s3_fs_lbl.configure(text=f"{int(v)} px")
                      ).pack(side="left")

        # ── Music card ────────────────────────────────────────────────────────
        mu_outer, mu_card = self._card(scroll, "🎵  Nhạc nền")
        mu_outer.grid(row=2, column=0, sticky="ew", padx=6, pady=4)
        mu_card.grid_columnconfigure(1, weight=1)

        self._s3_music_enabled = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            mu_card, text="Thêm nhạc nền vào video",
            variable=self._s3_music_enabled,
            font=ctk.CTkFont(size=13),
            command=self._s3_toggle_music,
        ).grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")

        from video_processor import pick_random_music
        music_files = self._s3_get_music_list()
        music_hint  = f"{len(music_files)} bài — random mỗi lần xuất" if music_files else "Chưa có nhạc — thêm file vào thư mục music/"
        self._s3_music_hint = ctk.CTkLabel(
            mu_card, text=music_hint,
            font=ctk.CTkFont(size=11), text_color=("gray50","gray60"), anchor="w",
        )
        self._s3_music_hint.grid(row=0, column=1, padx=6, pady=(10,4), sticky="w")

        mu_vol_row = ctk.CTkFrame(mu_card, fg_color="transparent")
        mu_vol_row.grid(row=1, column=0, columnspan=2, padx=14, pady=(0,10), sticky="w")
        ctk.CTkLabel(mu_vol_row, text="🔉  Âm lượng nhạc nền:",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0,8))
        self._s3_music_vol = tk.IntVar(value=8)
        self._s3_music_vol_lbl = ctk.CTkLabel(mu_vol_row, text="8%", width=48,
                                               font=ctk.CTkFont(size=11, weight="bold"))
        self._s3_music_vol_lbl.pack(side="right")
        ctk.CTkSlider(
            mu_vol_row, from_=0, to=50, variable=self._s3_music_vol, width=200,
            command=lambda v: self._s3_music_vol_lbl.configure(text=f"{int(v)}%"),
        ).pack(side="left")

        # ── Render action card ────────────────────────────────────────────────
        ac_outer, act_card = self._card(scroll, "🎬  Xuất video")
        ac_outer.grid(row=3, column=0, sticky="ew", padx=6, pady=4)
        act_card.grid_columnconfigure(1, weight=1)

        self._s3_render_btn = ctk.CTkButton(
            act_card, text="▶  Bắt đầu xuất video",
            font=ctk.CTkFont(size=14, weight="bold"), height=44, width=200,
            fg_color="#B71C1C", hover_color="#7f1d1d",
            command=self._s3_start_render)
        self._s3_render_btn.grid(row=0, column=0, padx=12, pady=12)

        prog_col = ctk.CTkFrame(act_card, fg_color="transparent")
        prog_col.grid(row=0, column=1, sticky="ew", padx=(0,12))
        prog_col.grid_columnconfigure(0, weight=1)

        self._s3_stage_lbl = ctk.CTkLabel(prog_col, text="",
                                           font=ctk.CTkFont(size=12, weight="bold"), anchor="w")
        self._s3_stage_lbl.grid(row=0, column=0, sticky="ew")
        self._s3_status_lbl = ctk.CTkLabel(prog_col, text="",
                                            font=ctk.CTkFont(size=11), anchor="w",
                                            text_color=("gray50","gray60"))
        self._s3_status_lbl.grid(row=1, column=0, sticky="ew")
        self._s3_bar = ctk.CTkProgressBar(prog_col)
        self._s3_bar.set(0)
        self._s3_bar.grid(row=2, column=0, sticky="ew", pady=(4,0))

        # ── Preview card (hidden until render done) ───────────────────────────
        self._s3_preview_outer, self._s3_preview_card = self._card(scroll, "✅  Kết quả — Xem trước")
        self._s3_preview_outer.grid(row=4, column=0, sticky="ew", padx=6, pady=4)
        self._s3_preview_outer.grid_remove()

        prev_inner = ctk.CTkFrame(self._s3_preview_card, fg_color="transparent")
        prev_inner.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        prev_inner.grid_columnconfigure(0, weight=1)

        self._s3_thumb = ctk.CTkLabel(prev_inner, text="",
                                       fg_color="black", corner_radius=8)
        self._s3_thumb.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0,10))
        self._s3_thumb.configure(height=160)

        ctk.CTkButton(prev_inner, text="▶  Phát trong VLC", height=38,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color="#1565C0", hover_color="#0D47A1",
                      command=self._s3_open_vlc
                      ).grid(row=1, column=0, padx=(0,8), sticky="ew")

        ctk.CTkButton(prev_inner, text="🎙  Xem trước lồng tiếng", height=38,
                      fg_color=("#6A1B9A","#4A148C"), hover_color=("#7B1FA2","#38006b"),
                      command=self._s3_open_preview_window
                      ).grid(row=1, column=1, padx=(0,8), sticky="ew")

        ctk.CTkButton(prev_inner, text="📂  Mở thư mục", height=38,
                      fg_color=("gray65","gray35"), hover_color=("gray55","gray45"),
                      command=self._s3_open_folder
                      ).grid(row=1, column=2, sticky="ew")

        self._s3_out_lbl = ctk.CTkLabel(prev_inner, text="",
                                         font=ctk.CTkFont(size=11),
                                         text_color=("gray50","gray60"), anchor="w")
        self._s3_out_lbl.grid(row=2, column=0, columnspan=3, pady=(8,0), sticky="ew")

        # ── Navigation ────────────────────────────────────────────────────────
        nav = ctk.CTkFrame(parent, fg_color="transparent")
        nav.grid(row=3, column=0, sticky="ew", padx=10, pady=(4,10))
        ctk.CTkButton(nav, text="← Bước 2", width=110, height=36,
                      fg_color=("gray65","gray35"), hover_color=("gray55","gray45"),
                      command=self._go_back).pack(side="left")

    # ── Step 3 logic ──────────────────────────────────────────────────────────

    def _pick_logo(self):
        path = filedialog.askopenfilename(
            title="Chọn ảnh logo",
            filetypes=[("Ảnh", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Tất cả", "*.*")],
        )
        if path:
            self._logo_path = path
            self._logo_lbl.configure(text=f"  {os.path.basename(path)}")
            self._logo_enabled.set(True)

    def _s3_get_music_list(self):
        from video_processor import _MUSIC_DIR, _MUSIC_EXTS
        if not os.path.isdir(_MUSIC_DIR):
            return []
        return [f for f in os.listdir(_MUSIC_DIR)
                if os.path.splitext(f)[1].lower() in _MUSIC_EXTS]

    def _s3_toggle_music(self):
        files = self._s3_get_music_list()
        if not files:
            self._s3_music_hint.configure(
                text="Chưa có nhạc — thêm file vào thư mục music/",
                text_color=("gray50","gray60"))
        else:
            self._s3_music_hint.configure(
                text=f"{len(files)} bài — random mỗi lần xuất",
                text_color=("gray50","gray60"))

    def _s3_select_style(self, name: str):
        self._s3_style_var.set(name)
        for n, b in self._s3_style_btns.items():
            if n == name:
                b.configure(fg_color=("#1B5E20","#2E7D32"), text_color="white",
                            font=ctk.CTkFont(size=10, weight="bold"))
            else:
                b.configure(fg_color=("gray72","gray28"), text_color=("gray10","gray90"),
                            font=ctk.CTkFont(size=10, weight="normal"))

    def _s3_start_render(self):
        if not self.subtitle_entries:
            messagebox.showwarning("Thiếu phụ đề", "Hãy hoàn thành Bước 2 trước!")
            return
        if not self.video_path:
            messagebox.showwarning("Thiếu video", "Hãy chọn video ở Bước 1!")
            return
        if self._processing:
            return

        out = filedialog.asksaveasfilename(
            title="Lưu video xuất ra",
            defaultextension=".mp4",
            initialfile=f"{os.path.splitext(os.path.basename(self.video_path))[0]}_vi.mp4",
            filetypes=[("MP4","*.mp4"),("Tất cả","*.*")])
        if not out:
            return

        self._output_path = out
        self._processing  = True
        self._s3_render_btn.configure(state="disabled")
        self._s3_preview_card.grid_remove()
        threading.Thread(target=self._s3_render_pipeline, daemon=True).start()

    def _s3_render_pipeline(self):
        try:
            # ── BUG FIX 1: dùng _get_tts_settings() thay vì lookup sai ────────
            tts      = self._get_tts_settings()
            pid      = tts["provider"]
            voice_id = tts["voice_id"]          # đã là voice ID đúng
            api_key  = tts["api_key"]
            orig_vol  = self._s2_orig_vol.get()   / 100.0
            dub_vol   = self._s2_dub_vol.get()   / 100.0
            dub_speed = self._s2_dub_speed.get()          # 50–200 (% tốc độ)
            font_sz  = self._s3_font_size.get()
            style_nm = self._s3_style_var.get()

            # Stage 1: TTS
            self._s3_stage("🎤  Đang tạo file lồng tiếng...", 0)
            dur_ms = int(get_video_duration(self.video_path) * 1000) or 600_000

            def _dub_cb(msg, prog):
                self.after(0, lambda m=msg, p=prog: (
                    self._s3_status_lbl.configure(text=m),
                    self._s3_bar.set(p * 0.45),
                ))

            self._preview_wav = create_dubbed_track(
                self.subtitle_entries, dur_ms,
                voice=voice_id, provider=pid, api_key=api_key,
                speed_pct=dub_speed,
                progress_callback=_dub_cb)

            # Stage 2: Mix
            self._s3_stage("🎚  Đang mix âm thanh...", 0.45)
            srt_tmp = tempfile.mktemp(suffix=".srt")
            with open(srt_tmp, "w", encoding="utf-8-sig") as f:
                f.write(write_srt(self.subtitle_entries, use_translation=True))

            def _mix_cb(msg, prog):
                self.after(0, lambda m=msg, p=prog: (
                    self._s3_status_lbl.configure(text=m),
                    self._s3_bar.set(0.45 + p * 0.55),
                ))

            # Stage 3: Render
            self._s3_stage("🎬  Đang render video...", 0.50)
            # Validate dubbed WAV trước khi render
            if not self._preview_wav or not os.path.exists(self._preview_wav):
                raise RuntimeError("File lồng tiếng không tồn tại. TTS có thể đã lỗi.")
            if os.path.getsize(self._preview_wav) < 1024:
                raise RuntimeError("File lồng tiếng bị trống (TTS thất bại). Kiểm tra internet hoặc thử lại.")

            from video_processor import pick_random_music
            music_path = None
            music_vol  = 0.0
            if getattr(self, '_s3_music_enabled', None) and self._s3_music_enabled.get():
                music_path = pick_random_music()
                music_vol  = self._s3_music_vol.get() / 100.0
                if music_path:
                    self._s3_stage(f"🎵  Nhạc nền: {os.path.basename(music_path)}", 0.50)

            logo_path = None
            logo_opacity = 0.30
            logo_size = 120
            if self._logo_enabled.get() and self._logo_path:
                logo_path    = self._logo_path
                logo_opacity = self._logo_opacity.get() / 100.0
                logo_size    = self._logo_size.get()
                if os.path.exists(logo_path):
                    self._s3_stage(
                        f"🔲  Logo: {os.path.basename(logo_path)} ({int(logo_opacity*100)}%)", 0.50)
                else:
                    logo_path = None
                    self._s3_stage("⚠️  Không tìm thấy file logo, bỏ qua", 0.50)

            export_with_dubbing(
                self.video_path, self._preview_wav, srt_tmp,
                self._output_path,
                original_volume=orig_vol,
                dubbed_volume=dub_vol,
                font_size=font_sz, style_name=style_nm,
                music_path=music_path,
                music_volume=music_vol,
                logo_path=logo_path,
                logo_opacity=logo_opacity,
                logo_size=logo_size,
                progress_callback=_mix_cb)

            if os.path.exists(srt_tmp):
                os.remove(srt_tmp)

            self._s3_stage("✅  Xuất video thành công!", 1.0)
            self._step_done[2] = True
            self.after(0, self._s3_show_preview)

        except Exception as exc:
            err = str(exc)
            self._s3_stage(f"❌  Lỗi: {err[:100]}", 0)
            self.after(0, lambda: messagebox.showerror("Lỗi xuất video", err))
        finally:
            self._processing = False
            self.after(0, lambda: self._s3_render_btn.configure(state="normal"))

    def _s3_stage(self, msg: str, prog: float):
        self.after(0, lambda: self._s3_stage_lbl.configure(text=msg))
        self.after(0, lambda: self._s3_bar.set(min(1.0, max(0.0, prog))))

    def _s3_show_preview(self):
        self._s3_preview_outer.grid()

        # Thumbnail from rendered video
        try:
            import cv2
            from PIL import Image, ImageTk
            cap = cv2.VideoCapture(self._output_path)
            cap.set(cv2.CAP_PROP_POS_MSEC, 3000)
            ret, frame = cap.read()
            cap.release()
            if ret:
                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                img.thumbnail((600, 160), Image.LANCZOS)
                ph  = ImageTk.PhotoImage(img)
                self._s3_thumb.configure(image=ph, text="")
                self._s3_thumb._image = ph  # keep reference
        except Exception:
            self._s3_thumb.configure(text="(Xem trước ảnh không khả dụng)")

        self._s3_out_lbl.configure(text=f"Đã lưu: {self._output_path}")

    def _s3_open_vlc(self):
        if not self._output_path or not os.path.exists(self._output_path):
            return
        vlc_exe = next(
            (p for p in [r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                          r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"]
             if os.path.exists(p)), None)
        if vlc_exe:
            subprocess.Popen([vlc_exe, os.path.normpath(self._output_path)])
        else:
            os.startfile(self._output_path)

    def _s3_open_preview_window(self):
        self._open_preview_window()

    def _s3_open_folder(self):
        if self._output_path:
            folder = os.path.dirname(self._output_path)
            os.startfile(folder)

    # =========================================================================
    #  SHARED PREVIEW HELPERS  (used from both Step 2 and Step 3)
    # =========================================================================

    def _get_tts_settings(self) -> dict:
        # If advanced engine mode is hidden, always use edge-tts with selected voice
        if not getattr(self, "_adv_visible", False):
            return {
                "provider": "edge",
                "voice_id": self._s2_voice_var.get() or "vi-VN-NamMinhNeural",
                "api_key":  "",
            }
        # Advanced mode: use the chosen engine
        pid     = TTS_PROVIDERS.get(self._s2_engine_var.get(), "edge")
        voice   = self._s2_voice_var.get() or list(PROVIDER_VOICES[pid].values())[0]
        api_key = self._api_cfg.get(
            "openai_api_key" if pid == "openai" else "fptai_api_key", ""
        )
        return {"provider": pid, "voice_id": voice, "api_key": api_key}

    def _open_preview_window(self):
        """Open PreviewWindow — subtitles only (no dubbing yet)."""
        if not self.subtitle_entries:
            messagebox.showwarning("Chưa có phụ đề", "Hãy hoàn thành Bước 1 & 2 trước!")
            return
        if not self.video_path:
            messagebox.showwarning("Chưa có video", "Hãy chọn video ở Bước 1!")
            return
        PreviewWindow(
            self,
            video_path=self.video_path,
            entries=self.subtitle_entries,
            tts_settings=self._get_tts_settings(),
            dubbed_wav=self._preview_wav,
            on_save_cb=self._s2_refresh_table,
            initial_style=self._s3_style_var.get() if hasattr(self, "_s3_style_var") else DEFAULT_STYLE,
        )

    def _open_preview_with_dub(self):
        """Open PreviewWindow and immediately start TTS generation."""
        if not self.subtitle_entries:
            messagebox.showwarning("Chưa có phụ đề", "Hãy hoàn thành Bước 1 & 2 trước!")
            return
        if not self.video_path:
            messagebox.showwarning("Chưa có video", "Hãy chọn video ở Bước 1!")
            return
        win = PreviewWindow(
            self,
            video_path=self.video_path,
            entries=self.subtitle_entries,
            tts_settings=self._get_tts_settings(),
            dubbed_wav=self._preview_wav,
            on_save_cb=self._s2_refresh_table,
            initial_style=self._s3_style_var.get() if hasattr(self, "_s3_style_var") else DEFAULT_STYLE,
        )
        # Auto-trigger dubbing generation after window opens
        win.after(500, win._generate_dub_preview)

    def _open_vlc_with_subs(self):
        """Quick open VLC with current subtitles (no re-render)."""
        if not self.subtitle_entries or not self.video_path:
            messagebox.showwarning("Chưa sẵn sàng", "Cần có video và phụ đề để xem trước!")
            return

        srt_tmp = tempfile.mktemp(suffix=".srt")
        with open(srt_tmp, "w", encoding="utf-8-sig") as f:
            f.write(write_srt(self.subtitle_entries, use_translation=True))

        # Use normpath to handle spaces in directory names
        video_p = os.path.normpath(self.video_path)
        srt_p   = os.path.normpath(srt_tmp)

        vlc_exe = next(
            (p for p in [r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                          r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"]
             if os.path.exists(p)), None
        )
        if vlc_exe:
            subprocess.Popen([
                vlc_exe,
                video_p,
                f"--sub-file={srt_p}",
                "--sub-text-scale=80",
            ])
        else:
            os.startfile(self.video_path)

    # =========================================================================
    #  SHARED HELPERS
    # =========================================================================

    @staticmethod
    def _card(parent, title: str) -> Tuple[ctk.CTkFrame, ctk.CTkFrame]:
        """Create a titled card. Returns (outer_frame, content_frame).
        Caller must .grid() the outer_frame; add children to content_frame."""
        outer = ctk.CTkFrame(parent, corner_radius=10)
        outer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(outer, text=title, font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w"
                     ).grid(row=0, column=0, padx=12, pady=(8, 2), sticky="ew")
        ctk.CTkFrame(outer, height=1, fg_color=("gray75", "gray35")
                     ).grid(row=1, column=0, padx=10, sticky="ew")
        content = ctk.CTkFrame(outer, fg_color="transparent")
        content.grid(row=2, column=0, sticky="ew")
        content.grid_columnconfigure(0, weight=1)
        return outer, content

    def _check_ffmpeg(self):
        if not check_ffmpeg():
            messagebox.showwarning("Thiếu FFmpeg",
                "FFmpeg chưa được cài!\n\nChạy: winget install ffmpeg")

    def _open_batch(self):
        """Open batch processing window with current app settings."""
        tts = self._get_tts_settings() if hasattr(self, '_adv_visible') else {
            "provider": "edge", "voice_id": "vi-VN-NamMinhNeural", "api_key": ""
        }
        lang_name = self._s1_lang_var.get() if hasattr(self, '_s1_lang_var') else "Tiếng Trung (Giản thể)"
        trans_lang, whisper_lang = LANGUAGES.get(lang_name, ("zh-CN", "zh"))

        settings = {
            "whisper_model":  WHISPER_MODELS.get(
                self._s1_model_var.get() if hasattr(self, '_s1_model_var') else "", "small"),
            "whisper_lang":   whisper_lang,
            "trans_lang":     trans_lang,
            "trans_provider": self._api_cfg.get("provider", "google"),
            "trans_api_key":  self._api_cfg.get("openai_api_key", ""),
            "trans_model":    self._api_cfg.get("openai_model", "gpt-4o-mini"),
            "tts_provider":   tts["provider"],
            "tts_voice":      tts["voice_id"],
            "tts_api_key":    tts["api_key"],
            "tts_speed":      self._s2_dub_speed.get() if hasattr(self, '_s2_dub_speed') else 100,
            "orig_vol":       (self._s2_orig_vol.get() / 100.0) if hasattr(self, '_s2_orig_vol') else 0.05,
            "dub_vol":        (self._s2_dub_vol.get()  / 100.0) if hasattr(self, '_s2_dub_vol')  else 1.0,
            "font_size":      self._s3_font_size.get() if hasattr(self, '_s3_font_size') else 9,
            "sub_style":      self._s3_style_var.get() if hasattr(self, '_s3_style_var') else "Mặc định",
            "music_enabled":  self._s3_music_enabled.get() if hasattr(self, '_s3_music_enabled') else True,
            "music_volume":   (self._s3_music_vol.get() / 100.0) if hasattr(self, '_s3_music_vol') else 0.08,
            "logo_path":      self._logo_path,
            "logo_enabled":   self._logo_enabled.get(),
            "logo_opacity":   self._logo_opacity.get() / 100.0,
            "logo_size":      self._logo_size.get(),
        }
        BatchWindow(self, settings)

    def _open_api_settings(self):
        ApiSettingsDialog(self, on_saved=self._on_api_saved)

    def _on_api_saved(self, new_cfg: dict):
        self._api_cfg = new_cfg


import subprocess
