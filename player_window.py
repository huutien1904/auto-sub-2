"""
Embedded video player with blur region selector.

Features:
  - Plays video directly inside the app (cv2 + ImageTk)
  - Audio playback via pygame.mixer (dubbed WAV or original audio)
  - Subtitle overlay per-frame from SubtitleEntry list
  - Blur-selection mode: drag mouse to mark region, set time range
  - Returns list of BlurRegion to parent for use in final render
"""

import os
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
from typing import List, Optional, Tuple, Callable, TYPE_CHECKING

import cv2
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageFont

if TYPE_CHECKING:
    from subtitle_utils import SubtitleEntry

# ── Optional pygame audio ────────────────────────────────────────────────────
try:
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    _HAS_PYGAME = True
except Exception:
    _HAS_PYGAME = False

# ── Constants ────────────────────────────────────────────────────────────────
CANVAS_W = 720
CANVAS_H = 405   # 16:9 default; canvas resizes to fit


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class BlurRegion:
    """One rectangular blur region, active during [start_sec, end_sec]."""
    x_pct:     float   # left  edge as fraction of video width  (0–1)
    y_pct:     float   # top   edge as fraction of video height (0–1)
    w_pct:     float   # width  as fraction of video width
    h_pct:     float   # height as fraction of video height
    start_sec: float
    end_sec:   float

    def label(self) -> str:
        return (f"{_fmt_time(self.start_sec)} → {_fmt_time(self.end_sec)}  "
                f"({self.w_pct:.0%} × {self.h_pct:.0%})")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_time(sec: float) -> str:
    sec = max(0.0, sec)
    m = int(sec) // 60
    s = int(sec) % 60
    return f"{m:02d}:{s:02d}"


def _parse_time(s: str) -> float:
    """Parse 'MM:SS', 'HH:MM:SS', or bare seconds string → float seconds."""
    s = s.strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(s)


def _srt_to_sec(t: str) -> float:
    """'00:01:02,500' → 62.5"""
    t = t.replace(",", ".")
    parts = t.split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


# ── Time-range dialog ─────────────────────────────────────────────────────────

class _TimeDialog(ctk.CTkToplevel):
    """Modal dialog: set start/end time for a blur region."""

    def __init__(self, parent, default_start: float, default_end: float):
        super().__init__(parent)
        self.title("⏱  Khoảng thời gian blur")
        self.geometry("320x180")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)
        self.result: Optional[Tuple[float, float]] = None

        ctk.CTkLabel(self, text="Đặt khoảng thời gian hiệu ứng blur:",
                     font=ctk.CTkFont(size=12, weight="bold")
                     ).grid(row=0, column=0, columnspan=3, padx=16, pady=(14, 8), sticky="w")

        for row, (lbl, val) in enumerate(
            [("Từ (MM:SS):", default_start), ("Đến (MM:SS):", default_end)], start=1
        ):
            ctk.CTkLabel(self, text=lbl, width=90).grid(row=row, column=0, padx=(16, 4), pady=4, sticky="w")
            var = tk.StringVar(value=_fmt_time(val))
            ctk.CTkEntry(self, textvariable=var, width=110).grid(row=row, column=1, padx=4, pady=4)
            setattr(self, f"_var{row}", var)

        ctk.CTkButton(self, text="✅  Xác nhận",
                      fg_color="#2E7D32", hover_color="#1B5E20",
                      command=self._confirm
                      ).grid(row=3, column=0, columnspan=3, padx=16, pady=(10, 8), sticky="ew")

    def _confirm(self):
        try:
            s = _parse_time(self._var1.get())
            e = _parse_time(self._var2.get())
            if e <= s:
                messagebox.showerror("Lỗi", "Thời gian kết thúc phải lớn hơn bắt đầu!", parent=self)
                return
            self.result = (s, e)
            self.destroy()
        except Exception as ex:
            messagebox.showerror("Lỗi định dạng", f"Dùng MM:SS, ví dụ 01:30\n\n{ex}", parent=self)


# ── Main player window ────────────────────────────────────────────────────────

class PlayerWindow(ctk.CTkToplevel):
    """
    Embedded video player with blur-region selector.

    Parameters
    ----------
    video_path   : path to video file to play
    entries      : list of SubtitleEntry for overlay
    dubbed_wav   : optional dubbed audio WAV to play instead of video audio
    blur_regions : pre-existing blur regions (editable)
    on_save      : callback(List[BlurRegion]) called when user saves & closes
    """

    def __init__(
        self,
        parent,
        video_path: str,
        entries: Optional[List["SubtitleEntry"]] = None,
        dubbed_wav: Optional[str] = None,
        music_path: Optional[str] = None,
        orig_vol: float = 0.10,
        dub_vol: float = 1.0,
        music_vol: float = 0.08,
        tts_settings: Optional[dict] = None,
        blur_regions: Optional[List[BlurRegion]] = None,
        on_save: Optional[Callable[[List[BlurRegion]], None]] = None,
    ):
        super().__init__(parent)
        self.title("▶  Xem trước & Chọn vùng Blur")
        self.geometry("1100x660")
        self.minsize(900, 540)

        self._video_path  = video_path
        self._entries     = entries or []
        self._dubbed_wav  = dubbed_wav
        self._music_path   = music_path
        self._orig_vol     = orig_vol
        self._dub_vol      = dub_vol
        self._music_vol    = music_vol
        self._tts_settings = tts_settings or {}
        self._on_save      = on_save
        self._blur_regions: List[BlurRegion] = list(blur_regions or [])
        self._temp_mix_wav: Optional[str] = None
        self._audio_ready  = False

        # ── Video state ───────────────────────────────────────────────────────
        self._cap: Optional[cv2.VideoCapture] = None
        self._total_frames  = 0
        self._fps           = 30.0
        self._duration_sec  = 0.0
        self._cur_frame_idx = 0
        self._playing       = False
        self._seek_lock     = threading.Lock()
        self._photo_ref     = None          # keep ImageTk reference alive

        # ── Display geometry (letterbox offset inside canvas) ─────────────────
        self._disp_x = 0
        self._disp_y = 0
        self._disp_w = CANVAS_W
        self._disp_h = CANVAS_H
        self._seeking = False               # suppress spurious seek callbacks

        # ── Blur selection state ──────────────────────────────────────────────
        self._blur_mode   = False
        self._drag_start: Optional[Tuple[int, int]] = None
        self._drag_rect_id = None           # canvas rectangle item

        self._build_ui()
        self._open_video()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # =========================================================================
    #  UI CONSTRUCTION
    # =========================================================================

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── LEFT: video area ──────────────────────────────────────────────────
        left = ctk.CTkFrame(self, fg_color=("#111111", "#0a0a0a"), corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        # Canvas
        canvas_wrap = ctk.CTkFrame(left, fg_color="black", corner_radius=6)
        canvas_wrap.grid(row=1, column=0, sticky="nsew", padx=8, pady=(8, 4))
        canvas_wrap.grid_propagate(False)

        self._canvas = tk.Canvas(
            canvas_wrap, bg="black",
            width=CANVAS_W, height=CANVAS_H,
            highlightthickness=0, cursor="arrow",
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<ButtonPress-1>",   self._mouse_press)
        self._canvas.bind("<B1-Motion>",        self._mouse_drag)
        self._canvas.bind("<ButtonRelease-1>",  self._mouse_release)

        # Seekbar row
        seek_row = ctk.CTkFrame(left, fg_color="transparent", height=28)
        seek_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(2, 0))
        seek_row.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Player.Horizontal.TScale",
                        troughcolor="#2a2a2a", background="#1565C0", sliderlength=14)

        self._seek_var = tk.DoubleVar(value=0)
        self._seekbar  = ttk.Scale(
            seek_row, from_=0, to=1000,
            orient="horizontal", variable=self._seek_var,
            style="Player.Horizontal.TScale",
            command=self._on_seekbar_move,
        )
        self._seekbar.grid(row=0, column=0, sticky="ew")

        # Controls row
        ctrl = ctk.CTkFrame(left, fg_color="transparent")
        ctrl.grid(row=3, column=0, padx=8, pady=(4, 8), sticky="ew")

        self._play_btn = ctk.CTkButton(
            ctrl, text="▶  Phát", width=100, height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1565C0", hover_color="#0D47A1",
            command=self._toggle_play,
        )
        self._play_btn.pack(side="left", padx=(0, 8))

        self._time_lbl = ctk.CTkLabel(
            ctrl, text="00:00 / 00:00",
            font=ctk.CTkFont(size=12), text_color=("gray55", "gray65"),
        )
        self._time_lbl.pack(side="left")

        # Blur mode toggle (right side of controls)
        self._blur_btn = ctk.CTkButton(
            ctrl, text="🎯  Chọn vùng Blur", width=170, height=36,
            font=ctk.CTkFont(size=12),
            fg_color=("gray60", "gray30"), hover_color=("#6A1B9A", "#4A148C"),
            command=self._toggle_blur_mode,
        )
        self._blur_btn.pack(side="right")

        # Blur mode hint label (above canvas, hidden by default)
        self._mode_lbl = ctk.CTkLabel(
            left, text="",
            font=ctk.CTkFont(size=11), text_color=("#9C27B0", "#CE93D8"),
        )
        self._mode_lbl.grid(row=0, column=0, pady=(4, 0))

        # ── RIGHT: sidebar ────────────────────────────────────────────────────
        right = ctk.CTkFrame(self, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 8), pady=8)
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right, text="🎯  Vùng Blur",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")

        # Instruction text
        self._hint_lbl = ctk.CTkLabel(
            right,
            text="Nhấn nút '🎯 Chọn vùng Blur'\nrồi kéo chuột trên video\nđể đánh dấu vùng cần làm mờ.",
            font=ctk.CTkFont(size=11),
            text_color=("gray55", "gray65"),
            justify="left",
        )
        self._hint_lbl.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="nw")

        # Region list (scrollable)
        self._regions_scroll = ctk.CTkScrollableFrame(right, label_text="")
        self._regions_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=0)
        self._regions_scroll.grid_columnconfigure(0, weight=1)

        # Save button
        ctk.CTkButton(
            right, text="✅  Lưu & Đóng",
            height=38, font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2E7D32", hover_color="#1B5E20",
            command=self._save_and_close,
        ).grid(row=3, column=0, padx=10, pady=(8, 12), sticky="ew")

        self._refresh_regions_list()

    # =========================================================================
    #  VIDEO PLAYBACK
    # =========================================================================

    def _open_video(self):
        self._cap = cv2.VideoCapture(self._video_path)
        if not self._cap.isOpened():
            self._show_error("Không thể mở video!")
            return

        self._fps           = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._total_frames  = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._duration_sec  = self._total_frames / self._fps

        self._seek_to_frame(0)

        if _HAS_PYGAME:
            need_tts = (self._dubbed_wav is None and
                        bool(self._tts_settings) and
                        bool(self._entries))
            target = self._generate_then_prepare if need_tts else self._prepare_audio
            threading.Thread(target=target, daemon=True).start()

    def _generate_then_prepare(self):
        """Tự động tạo lồng tiếng TTS rồi mix audio (chạy trong background thread)."""
        self.after(0, lambda: self._mode_lbl.configure(
            text="🎙  Đang tạo lồng tiếng... (có thể mất vài phút)"
        ))
        try:
            from dubbing import create_dubbed_track
            from video_processor import get_video_duration

            provider = self._tts_settings.get("provider", "edge")
            voice_id = self._tts_settings.get("voice_id", "vi-VN-NamMinhNeural")
            api_key  = self._tts_settings.get("api_key", "")
            dur_ms   = int(get_video_duration(self._video_path) * 1000) or 600_000

            def _cb(msg, prog):
                self.after(0, lambda m=msg: self._mode_lbl.configure(text=f"🎙  {m}"))

            self._dubbed_wav = create_dubbed_track(
                self._entries, dur_ms,
                voice=voice_id, provider=provider, api_key=api_key,
                progress_callback=_cb,
            )
        except Exception as exc:
            self.after(0, lambda e=str(exc): self._mode_lbl.configure(
                text=f"⚠️  TTS thất bại: {e[:60]}"
            ))

        self._prepare_audio()

    def _prepare_audio(self):
        """Background thread: FFmpeg-mix original + dubbed + music → load into pygame."""
        self.after(0, lambda: self._mode_lbl.configure(
            text="⏳  Đang chuẩn bị âm thanh hỗn hợp (original + lồng tiếng + nhạc)..."
        ))
        try:
            from video_processor import build_preview_audio
            mixed = build_preview_audio(
                self._video_path,
                dubbed_wav=self._dubbed_wav,
                music_path=self._music_path,
                orig_vol=self._orig_vol,
                dub_vol=self._dub_vol,
                music_vol=self._music_vol,
            )
            if mixed:
                self._temp_mix_wav = mixed
                pygame.mixer.music.load(mixed)
                self._audio_ready = True
                self.after(0, self._on_audio_ready)
            else:
                if self._dubbed_wav and os.path.exists(self._dubbed_wav):
                    pygame.mixer.music.load(self._dubbed_wav)
                    self._audio_ready = True
                    self.after(0, self._on_audio_ready)
                self.after(0, lambda: self._mode_lbl.configure(
                    text="⚠️  Mix âm thanh thất bại — chỉ phát lồng tiếng"
                ))
        except Exception as exc:
            self.after(0, lambda e=str(exc): self._mode_lbl.configure(
                text=f"⚠️  Lỗi âm thanh: {e[:60]}"
            ))

    def _on_audio_ready(self):
        """Gọi từ main thread khi audio đã load xong. Tự sync nếu video đang phát."""
        self._mode_lbl.configure(text="")
        if self._playing:
            try:
                pos_sec = self._cur_frame_idx / self._fps
                pygame.mixer.music.play(start=pos_sec)
            except Exception:
                pass

    def _toggle_play(self):
        if self._playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        if self._playing or self._cap is None:
            return
        self._playing = True
        self._play_btn.configure(text="⏸  Dừng")

        if _HAS_PYGAME and self._audio_ready:
            try:
                pos_sec = self._cur_frame_idx / self._fps
                pygame.mixer.music.play(start=pos_sec)
            except Exception:
                pass

        threading.Thread(target=self._play_loop, daemon=True).start()

    def _pause(self):
        self._playing = False
        self._play_btn.configure(text="▶  Phát")
        if _HAS_PYGAME:
            try:
                pygame.mixer.music.pause()
            except Exception:
                pass

    def _play_loop(self):
        """Background thread: read frames and schedule display via after()."""
        interval = 1.0 / self._fps
        while self._playing:
            t_start = time.perf_counter()

            with self._seek_lock:
                ret, frame = self._cap.read()
                if not ret:
                    # End of video
                    self._playing = False
                    self.after(0, lambda: self._play_btn.configure(text="▶  Phát"))
                    break
                idx = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                self._cur_frame_idx = idx

            # Schedule display in main thread
            self.after(0, self._display_frame_data, frame, idx)

            elapsed = time.perf_counter() - t_start
            time.sleep(max(0.0, interval - elapsed))

    def _seek_to_frame(self, frame_idx: int):
        """Seek to a specific frame (safe to call from any thread via after())."""
        was_playing = self._playing
        if was_playing:
            self._pause()
            time.sleep(0.05)

        frame_idx = max(0, min(frame_idx, max(0, self._total_frames - 1)))

        with self._seek_lock:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = self._cap.read()
            self._cur_frame_idx = frame_idx

        if ret:
            self._display_frame_data(frame, frame_idx)

        if was_playing:
            self.after(80, self._play)

    def _on_seekbar_move(self, val: str):
        if self._seeking:
            return
        if self._total_frames == 0:
            return
        pct = float(val) / 1000.0
        frame_idx = int(pct * self._total_frames)
        self._seek_to_frame(frame_idx)

    # ── Frame rendering ───────────────────────────────────────────────────────

    def _display_frame_data(self, frame, frame_idx: int):
        """Convert cv2 BGR frame → PIL → draw overlays → put on canvas."""
        try:
            cw = self._canvas.winfo_width()  or CANVAS_W
            ch = self._canvas.winfo_height() or CANVAS_H

            # BGR → RGB
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            vw, vh = img.size

            # Fit inside canvas (letterbox)
            scale = min(cw / vw, ch / vh)
            nw, nh = int(vw * scale), int(vh * scale)
            img = img.resize((nw, nh), Image.LANCZOS)

            # Store letterbox offset for blur coord conversion
            self._disp_x = (cw - nw) // 2
            self._disp_y = (ch - nh) // 2
            self._disp_w = nw
            self._disp_h = nh

            cur_sec = frame_idx / self._fps

            # Draw subtitle overlay
            img = self._overlay_subtitle(img, cur_sec)

            # Draw active blur-region previews
            img = self._overlay_blur_regions(img, cur_sec)

            # Compose on black background
            bg = Image.new("RGB", (cw, ch), (0, 0, 0))
            bg.paste(img, (self._disp_x, self._disp_y))

            self._photo_ref = ImageTk.PhotoImage(bg)
            self._canvas.delete("frame")
            self._canvas.create_image(0, 0, anchor="nw",
                                      image=self._photo_ref, tags="frame")

            # Update seekbar (without triggering seek callback)
            if self._total_frames > 0:
                self._seeking = True
                self._seek_var.set((frame_idx / self._total_frames) * 1000)
                self._seeking = False

            # Update time label
            self._time_lbl.configure(
                text=f"{_fmt_time(cur_sec)} / {_fmt_time(self._duration_sec)}"
            )

        except Exception as e:
            pass   # Don't crash the UI on a bad frame

    def _overlay_subtitle(self, img: Image.Image, cur_sec: float) -> Image.Image:
        if not self._entries:
            return img
        entry = next(
            (e for e in self._entries
             if _srt_to_sec(e.start_time) <= cur_sec <= _srt_to_sec(e.end_time)),
            None,
        )
        if entry is None:
            return img

        text = (entry.translated_text or entry.original_text).replace("\n", " ").strip()
        if not text:
            return img

        draw  = ImageDraw.Draw(img, "RGBA")
        w, h  = img.size
        fsize = max(13, h // 18)

        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", fsize)
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (w - tw) // 2
        y = h - th - int(h * 0.06)
        pad = 7

        draw.rounded_rectangle([x - pad, y - pad, x + tw + pad, y + th + pad],
                                radius=4, fill=(0, 0, 0, 170))
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
        return img

    def _overlay_blur_regions(self, img: Image.Image, cur_sec: float) -> Image.Image:
        """Show blur regions as semi-transparent gray boxes on the preview."""
        w, h = img.size
        draw = ImageDraw.Draw(img, "RGBA")
        for region in self._blur_regions:
            if region.start_sec <= cur_sec <= region.end_sec:
                x  = int(region.x_pct * w)
                y  = int(region.y_pct * h)
                x2 = x + int(region.w_pct * w)
                y2 = y + int(region.h_pct * h)
                draw.rectangle([x, y, x2, y2], fill=(80, 80, 80, 140))
                draw.rectangle([x, y, x2, y2], outline=(0, 200, 255, 230), width=2)
        return img

    # =========================================================================
    #  BLUR REGION SELECTION
    # =========================================================================

    def _toggle_blur_mode(self):
        self._blur_mode = not self._blur_mode
        if self._blur_mode:
            if self._playing:
                self._pause()
            self._canvas.configure(cursor="crosshair")
            self._blur_btn.configure(
                text="✕  Thoát chọn Blur",
                fg_color=("#7B1FA2", "#4A148C"),
                hover_color=("#6A1B9A", "#38006b"),
            )
            self._mode_lbl.configure(
                text="🎯  Đang ở chế độ chọn vùng Blur — kéo chuột trên video"
            )
        else:
            self._canvas.configure(cursor="arrow")
            self._blur_btn.configure(
                text="🎯  Chọn vùng Blur",
                fg_color=("gray60", "gray30"),
                hover_color=("#6A1B9A", "#4A148C"),
            )
            self._mode_lbl.configure(text="")
            # Clean up any dangling drag rectangle
            if self._drag_rect_id:
                self._canvas.delete(self._drag_rect_id)
                self._drag_rect_id = None
            self._drag_start = None

    def _mouse_press(self, event):
        if not self._blur_mode:
            return
        self._drag_start = (event.x, event.y)
        if self._drag_rect_id:
            self._canvas.delete(self._drag_rect_id)
            self._drag_rect_id = None

    def _mouse_drag(self, event):
        if not self._blur_mode or self._drag_start is None:
            return
        if self._drag_rect_id:
            self._canvas.delete(self._drag_rect_id)
        x0, y0 = self._drag_start
        self._drag_rect_id = self._canvas.create_rectangle(
            x0, y0, event.x, event.y,
            outline="#00C8FF", width=2, dash=(5, 3),
            tags="blur_drag",
        )

    def _mouse_release(self, event):
        if not self._blur_mode or self._drag_start is None:
            return

        x0, y0 = self._drag_start
        x1, y1 = event.x, event.y

        # Clean up drag rect
        if self._drag_rect_id:
            self._canvas.delete(self._drag_rect_id)
            self._drag_rect_id = None
        self._drag_start = None

        # Normalize coords
        if x0 > x1: x0, x1 = x1, x0
        if y0 > y1: y0, y1 = y1, y0

        if (x1 - x0) < 8 or (y1 - y0) < 8:
            return   # Too small — ignore

        # Convert canvas px → video-relative fractions (remove letterbox offset)
        vx0 = max(0, x0 - self._disp_x)
        vy0 = max(0, y0 - self._disp_y)
        vx1 = min(self._disp_w, x1 - self._disp_x)
        vy1 = min(self._disp_h, y1 - self._disp_y)

        if vx1 <= vx0 or vy1 <= vy0:
            return

        x_pct = vx0 / self._disp_w
        y_pct = vy0 / self._disp_h
        w_pct = (vx1 - vx0) / self._disp_w
        h_pct = (vy1 - vy0) / self._disp_h

        cur_sec = self._cur_frame_idx / self._fps
        self._open_time_dialog(x_pct, y_pct, w_pct, h_pct, cur_sec)

    def _open_time_dialog(self, x_pct, y_pct, w_pct, h_pct, cur_sec):
        dlg = _TimeDialog(
            self,
            default_start=max(0.0, cur_sec),
            default_end=min(self._duration_sec, cur_sec + 5.0),
        )
        self.wait_window(dlg)
        if dlg.result is None:
            return   # Cancelled

        start_sec, end_sec = dlg.result
        region = BlurRegion(x_pct, y_pct, w_pct, h_pct, start_sec, end_sec)
        self._blur_regions.append(region)
        self._refresh_regions_list()

        # Exit blur mode after adding a region
        if self._blur_mode:
            self._toggle_blur_mode()

        # Refresh canvas to show new region
        self._seek_to_frame(self._cur_frame_idx)

    # =========================================================================
    #  BLUR REGION LIST SIDEBAR
    # =========================================================================

    def _refresh_regions_list(self):
        for w in self._regions_scroll.winfo_children():
            w.destroy()

        if not self._blur_regions:
            ctk.CTkLabel(
                self._regions_scroll,
                text="Chưa có vùng blur nào.",
                font=ctk.CTkFont(size=11),
                text_color=("gray55", "gray65"),
            ).grid(row=0, column=0, padx=8, pady=12, sticky="w")
            return

        for i, region in enumerate(self._blur_regions):
            self._build_region_card(i, region)

        # "Add more" button
        ctk.CTkButton(
            self._regions_scroll,
            text="＋  Thêm vùng blur khác",
            height=28, font=ctk.CTkFont(size=11),
            fg_color="transparent",
            border_width=1, border_color=("gray65", "gray45"),
            text_color=("gray50", "gray60"),
            hover_color=("gray80", "gray25"),
            command=self._add_another,
        ).grid(row=len(self._blur_regions), column=0, padx=4, pady=(6, 2), sticky="ew")

    def _build_region_card(self, idx: int, region: BlurRegion):
        card = ctk.CTkFrame(
            self._regions_scroll,
            fg_color=("gray83", "#1e1e30"),
            corner_radius=8,
        )
        card.grid(row=idx, column=0, sticky="ew", padx=4, pady=3)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=f"  Vùng {idx + 1}",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
            text_color=("#00695C", "#4CAF50"),
        ).grid(row=0, column=0, padx=8, pady=(7, 1), sticky="w")

        ctk.CTkLabel(
            card,
            text=f"  ⏱  {_fmt_time(region.start_sec)}  →  {_fmt_time(region.end_sec)}",
            font=ctk.CTkFont(size=11),
            anchor="w",
            text_color=("gray30", "gray80"),
        ).grid(row=1, column=0, padx=8, pady=0, sticky="w")

        ctk.CTkLabel(
            card,
            text=f"  📐  {region.w_pct:.0%} × {region.h_pct:.0%}"
                 f"   at ({region.x_pct:.0%}, {region.y_pct:.0%})",
            font=ctk.CTkFont(size=10),
            anchor="w",
            text_color=("gray50", "gray60"),
        ).grid(row=2, column=0, padx=8, pady=(0, 6), sticky="w")

        ctk.CTkButton(
            card, text="🗑", width=32, height=32,
            fg_color=("#B71C1C", "#7f1d1d"),
            hover_color=("#C62828", "#991b1b"),
            font=ctk.CTkFont(size=14),
            command=lambda j=idx: self._delete_region(j),
        ).grid(row=0, column=1, rowspan=3, padx=(4, 8), pady=6)

        # Click to seek to region start
        ctk.CTkButton(
            card, text="▶", width=30, height=30,
            fg_color=("gray65", "gray35"),
            hover_color=("#1565C0", "#0D47A1"),
            font=ctk.CTkFont(size=12),
            command=lambda r=region: self._seek_to_frame(int(r.start_sec * self._fps)),
        ).grid(row=0, column=2, rowspan=3, padx=(0, 8), pady=6)

    def _delete_region(self, idx: int):
        if 0 <= idx < len(self._blur_regions):
            self._blur_regions.pop(idx)
            self._refresh_regions_list()
            self._seek_to_frame(self._cur_frame_idx)

    def _add_another(self):
        if not self._blur_mode:
            self._toggle_blur_mode()

    # =========================================================================
    #  MISC
    # =========================================================================

    def _save_and_close(self):
        if self._on_save:
            self._on_save(list(self._blur_regions))
        self._on_close()

    def _on_close(self):
        self._playing = False
        if _HAS_PYGAME:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        if self._cap:
            self._cap.release()
            self._cap = None
        if self._temp_mix_wav and os.path.exists(self._temp_mix_wav):
            try:
                os.remove(self._temp_mix_wav)
            except OSError:
                pass
        self.destroy()

    def _show_error(self, msg: str):
        self._canvas.create_text(
            CANVAS_W // 2, CANVAS_H // 2,
            text=f"❌  {msg}",
            fill="red", font=("Segoe UI", 14),
        )
