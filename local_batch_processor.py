"""
Local Folder Batch Processor
Pipeline: Scan folder → Transcribe → Translate → TTS → Export
Không cần Google Sheets hay bất kỳ API nào ngoài translator/TTS đã cấu hình.
"""

import os
import re
import tempfile
from typing import Callable, Dict, List, Optional, Tuple

# ── Constants ─────────────────────────────────────────────────────────────────

VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"}

NAMING_AI     = "ai"       # AI sinh tiêu đề từ nội dung video
NAMING_SUFFIX = "suffix"   # Tên gốc + "_vi"
NAMING_PREFIX = "prefix"   # [tiền_tố] + tên gốc

ST_PENDING = "pending"
ST_RUNNING = "running"
ST_SUCCESS = "success"
ST_ERROR   = "error"
ST_SKIPPED = "skipped"


# ── Helpers ───────────────────────────────────────────────────────────────────

def scan_videos(folder: str) -> List[str]:
    """Quét thư mục, trả về danh sách đường dẫn video (sắp xếp theo tên)."""
    result = []
    try:
        for name in sorted(os.listdir(folder)):
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                result.append(os.path.join(folder, name))
    except Exception:
        pass
    return result


def _safe_name(title: str) -> str:
    """Loại bỏ ký tự không hợp lệ trong tên file Windows."""
    name = re.sub(r'[\\/:*?"<>|]', "_", title).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:120] or "video"


def _unique_path(path: str) -> str:
    """Nếu file đã tồn tại, thêm _2, _3... vào tên."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{base}_{i}{ext}"):
        i += 1
    return f"{base}_{i}{ext}"


def _output_path_for(video_path: str, output_folder: str, settings: dict) -> Optional[str]:
    """
    Trả về đường dẫn file xuất dự kiến nếu naming_mode là suffix/prefix,
    dùng để kiểm tra resume. Trả về None nếu chế độ AI (không đoán trước được).
    """
    name  = os.path.basename(video_path)
    stem  = os.path.splitext(name)[0]
    mode  = settings.get("naming_mode", NAMING_AI)
    pfx   = _safe_name(settings.get("naming_prefix", "")) if settings.get("naming_prefix") else ""

    if mode == NAMING_SUFFIX:
        return os.path.join(output_folder, f"{stem}_vi.mp4")
    if mode == NAMING_PREFIX:
        return os.path.join(output_folder, f"{pfx}{stem}.mp4")
    return None


# ── Main processor ────────────────────────────────────────────────────────────

class LocalBatchProcessor:
    """
    Xử lý hàng loạt video từ thư mục cục bộ.

    Callbacks:
        log_cb(msg)                      — log từng dòng
        row_cb(idx, status, detail, out) — cập nhật trạng thái video thứ idx
        progress_cb(done, total)         — cập nhật thanh tiến độ
    """

    def __init__(
        self,
        input_folder:  str,
        output_folder: str,
        settings:      Dict,
        log_cb:        Optional[Callable[[str], None]]                  = None,
        row_cb:        Optional[Callable[[int, str, str, str], None]]   = None,
        progress_cb:   Optional[Callable[[int, int], None]]             = None,
    ):
        self.input_folder  = input_folder
        self.output_folder = output_folder
        self.settings      = settings
        self.log_cb        = log_cb        or print
        self.row_cb        = row_cb        or (lambda i, s, d, o: None)
        self.progress_cb   = progress_cb   or (lambda d, t: None)
        self._stopped      = False

    def stop(self) -> None:
        self._stopped = True

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> None:
        os.makedirs(self.output_folder, exist_ok=True)
        videos = scan_videos(self.input_folder)

        if not videos:
            self.log_cb("⚠️  Không tìm thấy video nào trong thư mục!")
            return

        total = len(videos)
        self.log_cb(f"📁  Tìm thấy {total} video. Bắt đầu xử lý...")
        self.progress_cb(0, total)

        succeeded = 0
        for idx, video_path in enumerate(videos):
            if self._stopped:
                self.log_cb("⏹  Đã dừng theo yêu cầu.")
                break

            name = os.path.basename(video_path)
            self.log_cb(f"\n── Video {idx+1}/{total}: {name} ──")

            # Resume check (chế độ suffix/prefix)
            candidate = _output_path_for(video_path, self.output_folder, self.settings)
            if candidate and os.path.exists(candidate):
                self.log_cb(f"  ⏭️  Đã có output, bỏ qua: {os.path.basename(candidate)}")
                self.row_cb(idx, ST_SKIPPED, "Đã xử lý trước đó", candidate)
                self.progress_cb(idx + 1, total)
                succeeded += 1
                continue

            self.row_cb(idx, ST_RUNNING, "Đang xử lý...", "")
            try:
                out = self._process_one(idx, video_path)
                self.row_cb(idx, ST_SUCCESS, "", out)
                succeeded += 1
            except Exception as exc:
                err = str(exc)[:250]
                self.log_cb(f"❌  Lỗi: {err}")
                self.row_cb(idx, ST_ERROR, err, "")

            self.progress_cb(idx + 1, total)

        self.log_cb(f"\n✅  Hoàn thành {succeeded}/{total} video!")

    # ── Pipeline for one video ────────────────────────────────────────────────

    def _process_one(self, idx: int, video_path: str) -> str:
        name = os.path.basename(video_path)

        # ── 1: Transcribe ─────────────────────────────────────────────────────
        self._status(idx, "Nhận dạng giọng nói...")
        self.log_cb("  🎙  Whisper đang nhận dạng...")
        from transcriber import transcribe_video
        from subtitle_utils import whisper_to_entries

        segs = transcribe_video(
            video_path,
            model_size=self.settings.get("whisper_model", "small"),
            language=self.settings.get("whisper_lang", "zh"),
            progress_callback=lambda m, p: self.log_cb(f"  {m}"),
        )
        entries = whisper_to_entries(segs)
        if not entries:
            raise RuntimeError("Whisper không nhận dạng được giọng nói.")
        self.log_cb(f"  ✅  {len(entries)} câu")

        # ── 2: Translate ──────────────────────────────────────────────────────
        self._status(idx, "Đang dịch...")
        self.log_cb("  🌐  Đang dịch tiếng Việt...")
        from translator import translate_entries

        translate_entries(
            entries,
            source_lang=self.settings.get("trans_lang", "zh-CN"),
            target_lang="vi",
            provider=self.settings.get("trans_provider", "google"),
            api_key=self.settings.get("trans_api_key", ""),
            model=self.settings.get("trans_model", ""),
            domain=self.settings.get("domain", ""),
            progress_callback=lambda m, p: self.log_cb(f"  {m}"),
        )
        self.log_cb("  ✅  Dịch xong")

        # ── 3: TTS ────────────────────────────────────────────────────────────
        self._status(idx, "Tạo lồng tiếng...")
        self.log_cb("  🔊  Đang tạo lồng tiếng...")
        from dubbing import create_dubbed_track
        from video_processor import get_video_duration

        dur_ms = int(get_video_duration(video_path) * 1000) or 600_000
        dubbed = create_dubbed_track(
            entries, dur_ms,
            voice=self.settings.get("tts_voice", "vi-VN-NamMinhNeural"),
            provider=self.settings.get("tts_provider", "edge"),
            api_key=self.settings.get("tts_api_key", ""),
            speed_pct=self.settings.get("tts_speed", 100),
            progress_callback=lambda m, p: self.log_cb(f"  {m}"),
        )
        self.log_cb("  ✅  Lồng tiếng xong")

        # ── 4: Tên file output ────────────────────────────────────────────────
        self._status(idx, "Tạo tên file...")
        mode   = self.settings.get("naming_mode", NAMING_AI)
        stem   = os.path.splitext(name)[0]

        if mode == NAMING_AI:
            self.log_cb("  🤖  AI đang tạo tiêu đề...")
            from batch_processor import _generate_title_with_ai
            raw = _generate_title_with_ai(entries, {
                "trans_provider": self.settings.get("trans_provider", "google"),
                "trans_api_key":  self.settings.get("trans_api_key", ""),
                "trans_model":    self.settings.get("trans_model", ""),
            })
            safe_stem = _safe_name(raw)
            out_path  = _unique_path(os.path.join(self.output_folder, f"{safe_stem}.mp4"))
        elif mode == NAMING_SUFFIX:
            out_path = _unique_path(os.path.join(self.output_folder, f"{stem}_vi.mp4"))
        else:
            pfx = _safe_name(self.settings.get("naming_prefix", ""))
            out_path = _unique_path(os.path.join(self.output_folder, f"{pfx}{stem}.mp4"))

        self.log_cb(f"  📝  Tên xuất: {os.path.basename(out_path)}")

        # ── 5: Export ─────────────────────────────────────────────────────────
        self._status(idx, "Render video...")
        self.log_cb("  🎬  Đang render video...")
        from subtitle_utils import write_srt
        from video_processor import export_with_dubbing, pick_random_music
        from subtitle_styles import DEFAULT_STYLE

        srt_tmp = tempfile.mktemp(suffix=".srt")
        with open(srt_tmp, "w", encoding="utf-8-sig") as f:
            f.write(write_srt(entries, use_translation=True))

        music_path = None
        music_vol  = 0.0
        if self.settings.get("music_enabled", True):
            music_path = pick_random_music()
            music_vol  = self.settings.get("music_volume", 0.08)
            if music_path:
                self.log_cb(f"  🎵  Nhạc: {os.path.basename(music_path)}")

        logo_path    = None
        logo_opacity = 0.3
        logo_size    = 120
        lp = self.settings.get("logo_path", "")
        if self.settings.get("logo_enabled") and lp and os.path.exists(lp):
            logo_path    = lp
            logo_opacity = self.settings.get("logo_opacity", 0.3)
            logo_size    = self.settings.get("logo_size", 120)
            self.log_cb(f"  🔲  Logo: {os.path.basename(logo_path)}")

        export_with_dubbing(
            video_path, dubbed, srt_tmp, out_path,
            original_volume=self.settings.get("orig_vol", 0.05),
            dubbed_volume=self.settings.get("dub_vol", 1.0),
            font_size=self.settings.get("font_size", 9),
            style_name=self.settings.get("sub_style", DEFAULT_STYLE),
            music_path=music_path,
            music_volume=music_vol,
            logo_path=logo_path,
            logo_opacity=logo_opacity,
            logo_size=logo_size,
            progress_callback=lambda m, p: self.log_cb(f"  {m}"),
            stderr_callback=lambda line: self.log_cb(f"  {line}"),
        )

        for f in [srt_tmp, dubbed]:
            try:
                if f and os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass

        self.log_cb(f"  ✅  Lưu: {os.path.basename(out_path)}")
        return out_path

    def _status(self, idx: int, detail: str) -> None:
        self.row_cb(idx, ST_RUNNING, detail, "")
