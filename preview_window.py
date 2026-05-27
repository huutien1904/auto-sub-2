"""
Full-featured preview & edit window:
  - Video frame with draggable subtitle (position saved for export)
  - 14 subtitle style presets
  - Card-based subtitle editor
  - VLC preview with style + dubbed audio
  - Generate dubbing in-window
"""

import os
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageFont

from subtitle_styles import STYLES, DEFAULT_STYLE, build_ffmpeg_style, get_canvas_colors, get_use_blur

if TYPE_CHECKING:
    from subtitle_utils import SubtitleEntry

_VLC_EXE: Optional[str] = next(
    (p for p in [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ] if os.path.exists(p)),
    None,
)

PREVIEW_W, PREVIEW_H = 480, 270   # canvas dimensions


def _write_srt(entries, path: str) -> None:
    from subtitle_utils import write_srt
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(write_srt(entries, use_translation=True))


def _get_video_frame(video_path: str, sec: float = 2.0) -> Optional[Image.Image]:
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
        ret, frame = cap.read()
        cap.release()
        if ret:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return Image.fromarray(rgb)
    except Exception:
        pass
    return None


class PreviewWindow(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        video_path: str,
        entries: "List[SubtitleEntry]",
        tts_settings: Optional[Dict] = None,
        dubbed_wav: Optional[str] = None,
        on_save_cb: Optional[Callable] = None,
        initial_style: str = DEFAULT_STYLE,
        initial_pos: Tuple[float, float] = (0.5, 0.88),   # (x%, y%) of video
    ):
        super().__init__(parent)
        self.title("👁  Xem trước & Chỉnh sửa")
        self.geometry("1100x700")
        self.minsize(900, 580)

        self._video_path    = video_path
        self._entries       = entries
        self._tts_settings  = tts_settings or {}
        self._dubbed_wav    = dubbed_wav
        self._on_save_cb    = on_save_cb
        self._selected_idx  = -1
        self._generating    = False
        self._temp_srt      = None

        # Style & position state
        self._current_style = tk.StringVar(value=initial_style)
        self._sub_x_pct     = initial_pos[0]   # 0.0–1.0
        self._sub_y_pct     = initial_pos[1]

        # Canvas drag state
        self._drag_start: Optional[Tuple[int, int]] = None
        self._canvas_img    = None   # keep reference
        self._frame_img: Optional[Image.Image] = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._load_frame)
        self.after(400, self._auto_open_vlc)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        # ── LEFT: video preview + drag ────────────────────────────────────────
        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(10, 4), pady=10)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Kéo phụ đề để thay đổi vị trí",
                     font=ctk.CTkFont(size=11), text_color=("gray50","gray60")
                     ).grid(row=0, column=0, pady=(8, 2))

        # Canvas for video frame
        canvas_wrap = ctk.CTkFrame(left, fg_color="black", corner_radius=8)
        canvas_wrap.grid(row=1, column=0, padx=10, pady=4, sticky="nsew")
        canvas_wrap.grid_propagate(False)

        self._canvas = tk.Canvas(
            canvas_wrap, bg="black",
            width=PREVIEW_W, height=PREVIEW_H,
            highlightthickness=0, cursor="hand2",
        )
        self._canvas.pack(expand=True, fill="both", padx=2, pady=2)
        self._canvas.bind("<ButtonPress-1>",   self._drag_start_cb)
        self._canvas.bind("<B1-Motion>",       self._drag_move_cb)
        self._canvas.bind("<ButtonRelease-1>", self._drag_end_cb)

        # Status bar
        self._status_lbl = ctk.CTkLabel(
            left, text="⏳ Đang tải...",
            font=ctk.CTkFont(size=11), anchor="w",
        )
        self._status_lbl.grid(row=2, column=0, padx=12, pady=(2, 4), sticky="ew")

        # Action buttons
        act = ctk.CTkFrame(left, fg_color="transparent")
        act.grid(row=3, column=0, padx=10, pady=(0, 8), sticky="ew")

        ctk.CTkButton(
            act, text="▶  Xem trong VLC",
            font=ctk.CTkFont(size=12, weight="bold"), height=36,
            fg_color=("#00695C","#004D40"), hover_color=("#00796B","#00695C"),
            command=self._refresh_vlc,
        ).pack(side="left", padx=(0, 6))

        self._dub_btn = ctk.CTkButton(
            act, text="🎙  Tạo & Xem trước lồng tiếng",
            font=ctk.CTkFont(size=12, weight="bold"), height=36,
            fg_color=("#6A1B9A","#4A148C"), hover_color=("#7B1FA2","#38006b"),
            command=self._generate_dub_preview,
        )
        self._dub_btn.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            act, text="❌", width=36, height=36,
            fg_color=("#B71C1C","#7f1d1d"), hover_color=("#C62828","#991b1b"),
            command=self._on_close,
        ).pack(side="right")

        # Progress
        prog_f = ctk.CTkFrame(left, fg_color="transparent")
        prog_f.grid(row=4, column=0, padx=10, pady=(0, 8), sticky="ew")
        self._prog_lbl = ctk.CTkLabel(prog_f, text="", font=ctk.CTkFont(size=11), anchor="w")
        self._prog_lbl.pack(side="top", anchor="w")
        self._prog_bar = ctk.CTkProgressBar(prog_f)
        self._prog_bar.set(0)
        self._prog_bar_visible = False

        # ── RIGHT: tabs (styles + subtitle list) ──────────────────────────────
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 10), pady=10)
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        tabs = ctk.CTkTabview(right, height=560)
        tabs.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        tabs.add("🎨  Kiểu phụ đề")
        tabs.add("📝  Danh sách phụ đề")

        self._build_style_tab(tabs.tab("🎨  Kiểu phụ đề"))
        self._build_subtitle_tab(tabs.tab("📝  Danh sách phụ đề"))

    # ── Style selector tab ────────────────────────────────────────────────────

    def _build_style_tab(self, tab):
        tab.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(tab, text="Chọn kiểu hiển thị phụ đề:",
                     font=ctk.CTkFont(size=12, weight="bold")
                     ).grid(row=0, column=0, columnspan=2, padx=8, pady=(8, 6), sticky="w")

        self._style_btns: Dict[str, ctk.CTkButton] = {}
        style_names = list(STYLES.keys())

        for i, name in enumerate(style_names):
            r, c = divmod(i, 2)
            txt_col, bg_col, _ = get_canvas_colors(name)
            btn = ctk.CTkButton(
                tab,
                text=name,
                height=36, width=145,
                font=ctk.CTkFont(size=11),
                fg_color=("gray75", "gray25"),
                hover_color=("gray65", "gray35"),
                text_color=("gray10", "gray90"),
                corner_radius=8,
                command=lambda n=name: self._select_style(n),
            )
            btn.grid(row=r + 1, column=c, padx=6, pady=4, sticky="ew")
            self._style_btns[name] = btn

        # Highlight current style
        self._select_style(self._current_style.get(), update_canvas=False)

    def _select_style(self, name: str, update_canvas: bool = True):
        self._current_style.set(name)
        # Reset all buttons
        for n, b in self._style_btns.items():
            b.configure(
                fg_color=("gray75", "gray25") if n != name else ("#1B5E20", "#2E7D32"),
                text_color=("gray10", "gray90") if n != name else "white",
                font=ctk.CTkFont(size=11, weight="normal" if n != name else "bold"),
            )
        if update_canvas:
            self._redraw_canvas()

    # ── Subtitle list tab ─────────────────────────────────────────────────────

    def _build_subtitle_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # Scrollable list of subtitle cards
        self._cards_frame = ctk.CTkScrollableFrame(tab, label_text="")
        self._cards_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self._cards_frame.grid_columnconfigure(0, weight=1)

        # Edit panel at bottom
        edit_f = ctk.CTkFrame(tab, height=80)
        edit_f.grid(row=1, column=0, sticky="ew", padx=0, pady=(4, 0))
        edit_f.grid_propagate(False)
        edit_f.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(edit_f, text="Sửa:", width=44,
                     font=ctk.CTkFont(weight="bold")
                     ).grid(row=0, column=0, padx=(10, 4), pady=(8, 4), sticky="w")
        self._edit_var = tk.StringVar()
        self._edit_entry = ctk.CTkEntry(
            edit_f, textvariable=self._edit_var,
            font=ctk.CTkFont(size=12),
            placeholder_text="Chọn câu phụ đề để sửa...",
        )
        self._edit_entry.grid(row=0, column=1, padx=4, pady=(8, 4), sticky="ew")
        self._edit_entry.bind("<Return>",   lambda _: self._save_and_next())
        self._edit_entry.bind("<Tab>",      lambda _: self._save_and_next())

        btn_f = ctk.CTkFrame(edit_f, fg_color="transparent")
        btn_f.grid(row=0, column=2, padx=(4, 10), pady=(8, 4))
        ctk.CTkButton(btn_f, text="💾", width=36, height=30,
                      fg_color="#2E7D32", hover_color="#1B5E20",
                      command=self._save_current).pack(side="left", padx=2)
        ctk.CTkButton(btn_f, text="◀", width=30, height=30,
                      fg_color=("gray65","gray35"),
                      command=lambda: self._navigate(-1)).pack(side="left", padx=2)
        ctk.CTkButton(btn_f, text="▶", width=30, height=30,
                      fg_color=("gray65","gray35"),
                      command=lambda: self._navigate(1)).pack(side="left", padx=2)

        self._card_widgets: List[ctk.CTkFrame] = []
        self._populate_cards()

    def _populate_cards(self):
        for w in self._cards_frame.winfo_children():
            w.destroy()
        self._card_widgets.clear()

        for i, entry in enumerate(self._entries):
            card = ctk.CTkFrame(
                self._cards_frame,
                fg_color=("gray88", "#1e1e2e"),
                corner_radius=8,
            )
            card.grid(row=i, column=0, sticky="ew", padx=6, pady=3)
            card.grid_columnconfigure(1, weight=1)

            # Timestamp
            ts = f"{entry.start_time[:5]} - {entry.end_time[:5]}"
            ctk.CTkLabel(card, text=ts, width=80,
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=("#1B5E20","#4CAF50")
                         ).grid(row=0, column=0, rowspan=2, padx=(8,4), pady=6, sticky="ns")

            # Vietnamese text (editable look)
            vi_text = entry.translated_text.replace("\n", " ")[:70]
            vi_lbl = ctk.CTkLabel(card, text=vi_text or "(chưa dịch)",
                                  anchor="w", font=ctk.CTkFont(size=12, weight="bold"),
                                  wraplength=220,
                                  text_color=("gray10", "white"))
            vi_lbl.grid(row=0, column=1, padx=4, pady=(6, 1), sticky="ew")

            # Original text
            orig = entry.original_text.replace("\n", " ")[:70]
            ctk.CTkLabel(card, text=orig,
                         anchor="w", font=ctk.CTkFont(size=10),
                         text_color=("gray50", "gray60"),
                         wraplength=220,
                         ).grid(row=1, column=1, padx=4, pady=(1, 6), sticky="ew")

            # Edit button
            idx_capture = i
            ctk.CTkButton(card, text="Sửa", width=46, height=24,
                          fg_color=("#1565C0","#0D47A1"), hover_color=("#0D47A1","#082a60"),
                          font=ctk.CTkFont(size=10),
                          command=lambda idx=idx_capture: self._select_card(idx)
                          ).grid(row=0, column=2, rowspan=2, padx=(4, 8), pady=6)

            # Click anywhere on card to select
            for child in card.winfo_children():
                child.bind("<Button-1>", lambda e, idx=i: self._select_card(idx))
            card.bind("<Button-1>", lambda e, idx=i: self._select_card(idx))

            self._card_widgets.append(card)

    def _select_card(self, idx: int):
        # Deselect previous
        if 0 <= self._selected_idx < len(self._card_widgets):
            self._card_widgets[self._selected_idx].configure(
                fg_color=("gray88", "#1e1e2e"), border_width=0
            )
        # Select new
        self._selected_idx = idx
        if 0 <= idx < len(self._card_widgets):
            self._card_widgets[idx].configure(
                fg_color=("gray80", "#2a2a3e"), border_width=2,
                border_color=("#2E7D32","#4CAF50")
            )
        entry = self._entries[idx]
        self._edit_var.set(entry.translated_text)
        self._edit_entry.focus_set()
        self._edit_entry.icursor(tk.END)
        # Scroll to card
        self._card_widgets[idx].update_idletasks()

    def _save_current(self):
        if self._selected_idx < 0:
            return
        new_text = self._edit_var.get()
        self._entries[self._selected_idx].translated_text = new_text
        # Update card label
        if self._selected_idx < len(self._card_widgets):
            card = self._card_widgets[self._selected_idx]
            for child in card.winfo_children():
                cfg = child.configure()
                if hasattr(child, 'cget'):
                    try:
                        t = child.cget("font")
                        # Find the big bold label (vi text)
                        if "bold" in str(child.cget("font")):
                            child.configure(text=new_text.replace("\n", " ")[:70])
                            break
                    except Exception:
                        pass
        if self._on_save_cb:
            self._on_save_cb()

    def _save_and_next(self):
        self._save_current()
        self._navigate(1)

    def _navigate(self, delta: int):
        n = len(self._entries)
        if n == 0:
            return
        new_idx = max(0, min(n - 1, self._selected_idx + delta))
        self._select_card(new_idx)

    # ── Canvas: video frame + draggable subtitle ──────────────────────────────

    def _load_frame(self):
        img = _get_video_frame(self._video_path)
        if img:
            self._frame_img = img
        else:
            # Black placeholder
            self._frame_img = Image.new("RGB", (PREVIEW_W, PREVIEW_H), (20, 20, 40))
        self._redraw_canvas()

    def _redraw_canvas(self):
        if self._frame_img is None:
            return
        w, h = PREVIEW_W, PREVIEW_H
        # Fit frame to canvas
        img = self._frame_img.copy()
        img.thumbnail((w, h), Image.LANCZOS)
        # Paste on black bg
        bg = Image.new("RGB", (w, h), (0, 0, 0))
        ox = (w - img.width) // 2
        oy = (h - img.height) // 2
        bg.paste(img, (ox, oy))

        # Draw subtitle overlay
        sample   = self._get_sample_text()
        style    = self._current_style.get()
        txt_col, bg_hex, out_col = get_canvas_colors(style)
        use_blur = get_use_blur(style)
        bg = self._draw_subtitle_on_frame(bg, sample, txt_col, bg_hex, out_col, use_blur)

        self._canvas_img = ImageTk.PhotoImage(bg)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._canvas_img)

        # Invisible drag target over subtitle area
        sx = int(self._sub_x_pct * w)
        sy = int(self._sub_y_pct * h)
        self._canvas.create_rectangle(
            sx - 120, sy - 20, sx + 120, sy + 20,
            fill="", outline="", tags="drag_zone",
        )

    def _draw_subtitle_on_frame(
        self, img: Image.Image,
        text: str, txt_col: str, bg_hex: str, out_col: str,
        use_blur: bool = True,
    ) -> Image.Image:
        draw  = ImageDraw.Draw(img, "RGBA")
        w, h  = img.size
        sx    = int(self._sub_x_pct * w)
        sy    = int(self._sub_y_pct * h)
        fsize = max(14, h // 18)

        try:
            font = ImageFont.truetype("arial.ttf", fsize)
        except Exception:
            font = ImageFont.load_default()

        # Measure text
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = sx - tw // 2
        y = sy - th // 2

        pad = 8
        if use_blur:
            # Frosted-glass blur background
            bx0 = max(0, x - pad)
            by0 = max(0, y - pad)
            bx1 = min(w, x + tw + pad)
            by1 = min(h, y + th + pad)
            if bx1 > bx0 and by1 > by0:
                from PIL import ImageFilter
                region = img.crop((bx0, by0, bx1, by1)).convert("RGBA")
                blurred = region.filter(ImageFilter.GaussianBlur(radius=12))
                dark = Image.new("RGBA", blurred.size, (0, 0, 0, 120))
                blurred = Image.alpha_composite(blurred, dark)
                img.paste(blurred.convert("RGB"), (bx0, by0))
                draw = ImageDraw.Draw(img, "RGBA")
        else:
            # Solid color background (kiểu cũ)
            if bg_hex not in ("transparent", ""):
                col = self._parse_color(bg_hex)
                draw.rounded_rectangle(
                    [x - pad, y - pad, x + tw + pad, y + th + pad],
                    radius=4, fill=col,
                )

        # Draw outline
        if out_col and out_col not in ("transparent",):
            ocol = self._parse_color(out_col)
            for dx in (-2, 0, 2):
                for dy in (-2, 0, 2):
                    if dx or dy:
                        draw.text((x + dx, y + dy), text, font=font, fill=ocol)

        # Draw text
        tcol = self._parse_color(txt_col)
        draw.text((x, y), text, font=font, fill=tcol)
        return img

    def _parse_color(self, c: str):
        """Parse hex color like #RRGGBB or #RRGGBBAA to RGBA tuple."""
        c = c.lstrip("#")
        if len(c) == 6:
            r, g, b = int(c[0:2],16), int(c[2:4],16), int(c[4:6],16)
            return (r, g, b, 255)
        elif len(c) == 8:
            r, g, b, a = int(c[0:2],16), int(c[2:4],16), int(c[4:6],16), int(c[6:8],16)
            return (r, g, b, a)
        # Named colors
        name_map = {"white":(255,255,255,255), "black":(0,0,0,255),
                    "red":(255,0,0,255), "yellow":(255,255,0,255)}
        return name_map.get(c.lower(), (255,255,255,255))

    def _get_sample_text(self) -> str:
        """Return a representative subtitle text for preview."""
        for e in self._entries:
            if e.translated_text and len(e.translated_text) > 4:
                return e.translated_text[:30].replace("\n", " ")
        return "Phụ đề tiếng Việt"

    # ── Canvas drag ───────────────────────────────────────────────────────────

    def _drag_start_cb(self, event):
        self._drag_start = (event.x, event.y)

    def _drag_move_cb(self, event):
        if self._drag_start is None:
            return
        w, h = PREVIEW_W, PREVIEW_H
        self._sub_x_pct = max(0.05, min(0.95, event.x / w))
        self._sub_y_pct = max(0.05, min(0.98, event.y / h))
        self._redraw_canvas()

    def _drag_end_cb(self, event):
        self._drag_start = None

    # ── VLC / player ──────────────────────────────────────────────────────────

    def _auto_open_vlc(self):
        self._set_status("⏳", "Đang mở VLC...")
        threading.Thread(target=self._do_open_vlc, daemon=True).start()

    def _refresh_vlc(self):
        self._set_status("⏳", "Đang cập nhật phụ đề và mở VLC...")
        threading.Thread(target=self._do_open_vlc, daemon=True).start()

    def _do_open_vlc(self, dubbed_wav: Optional[str] = None):
        try:
            srt = tempfile.mktemp(suffix=".srt")
            _write_srt(self._entries, srt)
            self._temp_srt = srt
            wav = dubbed_wav or self._dubbed_wav

            if _VLC_EXE:
                # Convert paths to native Windows format to avoid space issues
                video  = os.path.normpath(self._video_path)
                srt_p  = os.path.normpath(srt)
                cmd = [
                    _VLC_EXE,
                    video,
                    f"--sub-file={srt_p}",
                    "--sub-text-scale=80",
                    "--sub-text-position=90",
                ]
                if wav and os.path.exists(wav):
                    cmd += [f"--input-slave={os.path.normpath(wav)}"]
                subprocess.Popen(cmd)
                extra = " + lồng tiếng" if wav else ""
                self.after(0, lambda: self._set_status(
                    "▶", f"VLC đang phát — phụ đề kiểu '{self._current_style.get()}'{extra}"
                ))
            else:
                out = tempfile.mktemp(suffix=".mp4")
                cmd = [
                    "ffmpeg", "-y",
                    "-i", self._video_path, "-i", srt,
                    "-map", "0:v", "-map", "0:a", "-map", "1:s",
                    "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", out,
                ]
                r = subprocess.run(cmd, capture_output=True)
                if r.returncode == 0:
                    os.startfile(out)
                else:
                    os.startfile(self._video_path)
                self.after(0, lambda: self._set_status("▶", "Đang phát trong trình phát mặc định."))
        except Exception as exc:
            err = str(exc)
            self.after(0, lambda: self._set_status("❌", f"Lỗi: {err}"))

    # ── Dubbing preview ───────────────────────────────────────────────────────

    def _generate_dub_preview(self):
        if self._generating:
            return
        if not self._tts_settings:
            self._set_status("⚠", "Chưa có cài đặt TTS trong cửa sổ chính!")
            return
        self._generating = True
        self._dub_btn.configure(state="disabled", text="⏳  Đang tạo giọng...")
        self._show_progress(True)
        threading.Thread(target=self._run_dub, daemon=True).start()

    def _run_dub(self):
        try:
            from dubbing import create_dubbed_track
            from video_processor import get_video_duration

            provider = self._tts_settings.get("provider", "edge")
            voice_id = self._tts_settings.get("voice_id", "vi-VN-HoaiMyNeural")
            api_key  = self._tts_settings.get("api_key", "")
            dur_ms   = int(get_video_duration(self._video_path) * 1000) or 600_000

            def _cb(msg, prog):
                self.after(0, lambda m=msg, p=prog: (
                    self._prog_lbl.configure(text=m),
                    self._prog_bar.set(p),
                ))

            self._dubbed_wav = create_dubbed_track(
                self._entries, dur_ms,
                voice=voice_id, provider=provider, api_key=api_key,
                progress_callback=_cb,
            )
            self.after(0, lambda: self._set_status("🎙", "Lồng tiếng xong — đang mở VLC..."))
            self._do_open_vlc(dubbed_wav=self._dubbed_wav)
        except Exception as exc:
            err = str(exc)
            self.after(0, lambda: self._set_status("❌", f"Lỗi: {err}"))
        finally:
            self._generating = False
            self.after(0, lambda: (
                self._dub_btn.configure(state="normal", text="🎙  Tạo & Xem trước lồng tiếng"),
                self._show_progress(False),
            ))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, icon: str, text: str):
        self._status_lbl.configure(text=f"{icon}  {text}")

    def _show_progress(self, show: bool):
        if show and not self._prog_bar_visible:
            self._prog_bar.pack(side="top", anchor="w", pady=2)
            self._prog_bar_visible = True
        elif not show and self._prog_bar_visible:
            self._prog_bar.pack_forget()
            self._prog_bar.set(0)
            self._prog_lbl.configure(text="")
            self._prog_bar_visible = False

    def get_style(self) -> str:
        return self._current_style.get()

    def get_position(self) -> Tuple[float, float]:
        return (self._sub_x_pct, self._sub_y_pct)

    def _on_close(self):
        if self._temp_srt and os.path.exists(self._temp_srt):
            try:
                os.remove(self._temp_srt)
            except OSError:
                pass
        self.destroy()
