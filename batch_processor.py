"""
Batch processor — Google Sheets via Service Account JSON.
Yêu cầu: file JSON Service Account từ Google Cloud Console.

Thiết lập (1 lần duy nhất):
1. Vào https://console.cloud.google.com
2. Tạo project → Enable "Google Sheets API"
3. IAM & Admin → Service Accounts → Create service account
4. Tạo key JSON → tải về máy
5. Mở Google Sheet → Share → thêm email của service account (Editor)
6. Dán đường dẫn file JSON và URL sheet vào ứng dụng
"""

import os
import tempfile
import time
from typing import Callable, Dict, List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials

# ── Status constants ──────────────────────────────────────────────────────────

ST_NEW         = "new"
ST_DOWNLOADING = "đang tải video"
ST_DOWNLOADED  = "đã tải xong"
ST_PROCESSING  = "đang xử lý"
ST_SUCCESS     = "xử lý thành công"
ST_ERROR       = "lỗi"

COL_LINK   = 1   # A
COL_STATUS = 2   # B
COL_ERROR  = 3   # C
COL_OUTPUT = 4   # D — đường dẫn video hoàn thành

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# ── Sheet Client ──────────────────────────────────────────────────────────────

class SheetClient:
    """Kết nối Google Sheets qua Service Account JSON."""

    def __init__(self, json_path: str, sheet_url: str):
        creds = Credentials.from_service_account_file(json_path, scopes=_SCOPES)
        gc = gspread.authorize(creds)
        if sheet_url.startswith("https://"):
            self._ws = gc.open_by_url(sheet_url).sheet1
        else:
            self._ws = gc.open_by_key(sheet_url).sheet1

    def read_all(self) -> List[List[str]]:
        """Trả về tất cả hàng dưới dạng list of lists."""
        return self._ws.get_all_values()

    def write_cell(self, row: int, col: int, value: str) -> None:
        """Ghi một ô (1-indexed)."""
        self._ws.update_cell(row, col, value)

    def write_hyperlink(self, row: int, col: int, path: str, label: str = "📁 Mở video") -> None:
        """Ghi đường dẫn file dưới dạng hyperlink có thể bấm được."""
        from urllib.parse import quote
        # Chuyển Windows path → file URI, encode ký tự đặc biệt/tiếng Việt
        forward = path.replace("\\", "/")
        encoded = quote(forward, safe="/:@")
        uri = "file:///" + encoded.lstrip("/")
        # Escape dấu nháy kép trong label
        safe_label = label.replace('"', "'")[:80]
        formula = f'=HYPERLINK("{uri}","{safe_label}")'
        col_letter = chr(ord("A") + col - 1)
        cell = f"{col_letter}{row}"
        self._ws.update([[formula]], cell, value_input_option="USER_ENTERED")

    def ensure_header(self) -> None:
        """Đảm bảo hàng 1 có header đúng."""
        rows = self.read_all()
        headers = ["Link video", "Trạng thái", "Lý do lỗi", "Video hoàn thành"]
        if not rows or rows[0][:4] != headers:
            self._ws.update("A1:D1", [headers])


def _build_title_from_entries(entries, max_len: int = 100) -> str:
    """Ghép các câu phụ đề đầu tiên thành tên file ngắn gọn (fallback)."""
    parts = []
    total = 0
    for e in entries:
        text = (e.translated_text or e.original_text or "").strip().replace("\n", " ")
        if not text:
            continue
        if total + len(text) > max_len:
            remaining = max_len - total
            if remaining > 10:
                parts.append(text[:remaining].rstrip())
            break
        parts.append(text)
        total += len(text) + 1
        if total >= max_len:
            break
    title = " ".join(parts).strip()
    return title if title else "video"


def _generate_title_with_ai(entries, settings: dict) -> str:
    """Dùng AI tóm tắt nội dung phụ đề thành tiêu đề ngắn gọn (~100 ký tự).
    Fallback về _build_title_from_entries nếu không có API key."""

    # Gom toàn bộ phụ đề đã dịch (tối đa 3000 ký tự để tránh tốn token)
    all_text = " ".join(
        (e.translated_text or e.original_text or "").strip().replace("\n", " ")
        for e in entries if (e.translated_text or e.original_text)
    )[:3000]

    if not all_text:
        return _build_title_from_entries(entries)

    prompt = (
        "Dựa vào nội dung phụ đề video dưới đây, hãy tạo một tiêu đề tiếng Việt "
        "ngắn gọn, súc tích, mô tả đúng chủ đề video. "
        "Tiêu đề tối đa 100 ký tự, không dùng ký tự đặc biệt như / \\ : * ? \" < > |. "
        "Chỉ trả về tiêu đề, không giải thích.\n\n"
        f"Nội dung:\n{all_text}"
    )

    provider  = settings.get("trans_provider", "google")
    api_key   = settings.get("trans_api_key", "")
    ai_model  = settings.get("trans_model", "")

    try:
        if provider == "openai" and api_key:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model=ai_model or "gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
                temperature=0.3,
            )
            title = resp.choices[0].message.content.strip()

        elif provider == "anthropic" and api_key:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=ai_model or "claude-haiku-4-5-20251001",
                max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
            title = resp.content[0].text.strip()

        else:
            return _build_title_from_entries(entries)

        # Bỏ dấu nháy bọc ngoài nếu AI trả về có dấu nháy
        title = title.strip('"\'""''')
        return title[:100] if title else _build_title_from_entries(entries)

    except Exception:
        return _build_title_from_entries(entries)


def get_pending_rows(rows: List[List[str]]) -> List[Tuple[int, str]]:
    """Trả về (sheet_row_number, link) cho các hàng có status 'new'."""
    pending = []
    for i, row in enumerate(rows):
        if i == 0:
            continue   # bỏ qua header
        link   = row[0].strip() if len(row) > 0 else ""
        status = row[1].strip().lower() if len(row) > 1 else ""
        if link and status == ST_NEW:
            pending.append((i + 1, link))   # sheet rows 1-indexed
    return pending


def test_connection(json_path: str, sheet_url: str) -> Tuple[bool, str]:
    """Kiểm tra kết nối. Trả về (ok, message)."""
    try:
        client = SheetClient(json_path, sheet_url)
        rows   = client.read_all()
        return True, f"Kết nối thành công! Sheet có {len(rows)} hàng."
    except Exception as e:
        return False, str(e)


# ── Main batch pipeline ───────────────────────────────────────────────────────

class BatchProcessor:
    def __init__(
        self,
        json_path: str,
        sheet_url: str,
        download_dir: str,
        output_dir: str,
        settings: Dict,
        log_cb:        Optional[Callable[[str], None]]           = None,
        progress_cb:   Optional[Callable[[int, int], None]]      = None,
        row_update_cb: Optional[Callable[[int, str, str, str], None]] = None,
    ):
        self.json_path     = json_path
        self.sheet_url     = sheet_url
        self.download_dir  = download_dir
        self.output_dir    = output_dir
        self.settings      = settings
        self.log_cb        = log_cb        or print
        self.progress_cb   = progress_cb   or (lambda d, t: None)
        self.row_update_cb = row_update_cb or (lambda r, s, e: None)
        self._stop         = False
        self._client: Optional[SheetClient] = None

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            self.log_cb("🔗  Đang kết nối Google Sheets qua Service Account...")
            self._client = SheetClient(self.json_path, self.sheet_url)
            self._client.ensure_header()

            all_rows = self._client.read_all()
            rows     = get_pending_rows(all_rows)

            if not rows:
                self.log_cb("ℹ️  Không có hàng nào có trạng thái 'new'.")
                return

            total = len(rows)
            self.log_cb(f"📋  Tìm thấy {total} video cần xử lý.")

            for done, (row_num, link) in enumerate(rows):
                if self._stop:
                    self.log_cb("⏹  Đã dừng theo yêu cầu.")
                    break

                self.log_cb(f"\n── Video {done+1}/{total}  (hàng {row_num}) ──")
                self.log_cb(f"   {link[:70]}")
                self.progress_cb(done, total)

                try:
                    self._process_one(row_num, link)
                except Exception as exc:
                    err = str(exc)[:300]
                    self.log_cb(f"❌  Lỗi: {err}")
                    self._set(row_num, ST_ERROR, err)

            self.progress_cb(total, total)
            self.log_cb("\n✅  Hoàn thành toàn bộ batch!")

        except Exception as exc:
            self.log_cb(f"❌  Lỗi kết nối sheet: {exc}")

    def _process_one(self, row_num: int, link: str) -> None:
        # 1 ── Download
        self._set(row_num, ST_DOWNLOADING)
        self.log_cb("  📥  Đang tải video...")
        from downloader import download_video, extract_url
        clean = extract_url(link) or link
        os.makedirs(self.download_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        video = download_video(clean, self.download_dir,
                               progress_callback=lambda m, p: self.log_cb(f"  {m}"))
        self._set(row_num, ST_DOWNLOADED)
        self.log_cb(f"  ✅  Đã tải: {os.path.basename(video)[:50]}")

        # 2 ── Transcribe
        self._set(row_num, ST_PROCESSING, "nhận dạng giọng nói...")
        self.log_cb("  🎙  Whisper đang nhận dạng...")
        from transcriber import transcribe_video
        from subtitle_utils import whisper_to_entries
        segs    = transcribe_video(
            video,
            model_size=self.settings.get("whisper_model", "small"),
            language=self.settings.get("whisper_lang", "zh"),
            progress_callback=lambda m, p: self.log_cb(f"  {m}"),
        )
        entries = whisper_to_entries(segs)
        if not entries:
            raise RuntimeError("Không nhận dạng được giọng nói.")
        self.log_cb(f"  ✅  Nhận dạng xong: {len(entries)} câu")

        # 3 ── Translate
        self._set(row_num, ST_PROCESSING, "đang dịch...")
        self.log_cb("  🌐  Đang dịch tiếng Việt...")
        from translator import translate_entries
        translate_entries(
            entries,
            source_lang=self.settings.get("trans_lang", "zh-CN"),
            target_lang="vi",
            provider=self.settings.get("trans_provider", "google"),
            api_key=self.settings.get("trans_api_key", ""),
            model=self.settings.get("trans_model", ""),
            progress_callback=lambda m, p: self.log_cb(f"  {m}"),
        )
        self.log_cb("  ✅  Dịch xong")

        # 4 ── TTS
        self._set(row_num, ST_PROCESSING, "tạo lồng tiếng...")
        self.log_cb("  🔊  Đang tạo lồng tiếng...")
        from dubbing import create_dubbed_track
        from video_processor import get_video_duration
        dur_ms = int(get_video_duration(video) * 1000) or 600_000
        dubbed = create_dubbed_track(
            entries, dur_ms,
            voice=self.settings.get("tts_voice", "vi-VN-NamMinhNeural"),
            provider=self.settings.get("tts_provider", "edge"),
            api_key=self.settings.get("tts_api_key", ""),
            speed_pct=self.settings.get("tts_speed", 100),
            progress_callback=lambda m, p: self.log_cb(f"  {m}"),
        )
        self.log_cb("  ✅  Lồng tiếng xong")

        # 5 ── Export
        self._set(row_num, ST_PROCESSING, "render video...")
        self.log_cb("  🎬  Đang render video...")
        from subtitle_utils import write_srt
        from video_processor import export_with_dubbing
        from subtitle_styles import DEFAULT_STYLE

        srt_tmp = tempfile.mktemp(suffix=".srt")
        with open(srt_tmp, "w", encoding="utf-8-sig") as f:
            f.write(write_srt(entries, use_translation=True))

        # Đặt tên file bằng AI dựa trên nội dung phụ đề
        import re as _re
        self.log_cb("  🤖  AI đang tạo tiêu đề cho video...")
        content_title = _generate_title_with_ai(entries, self.settings)
        safe_name = _re.sub(r'[\\/:*?"<>|]', "_", content_title).strip() or "video"
        self.log_cb(f"  📝  Tiêu đề: {safe_name}")
        out_mp4 = os.path.join(self.output_dir, f"{safe_name}.mp4")

        from video_processor import pick_random_music
        music_path = None
        music_vol  = 0.0
        if self.settings.get("music_enabled", True):
            music_path = pick_random_music()
            music_vol  = self.settings.get("music_volume", 0.12)
            if music_path:
                self.log_cb(f"  🎵  Nhạc nền: {os.path.basename(music_path)}")

        logo_path    = None
        logo_opacity = 0.5
        logo_size    = 150
        if self.settings.get("logo_enabled") and self.settings.get("logo_path"):
            logo_path    = self.settings["logo_path"]
            logo_opacity = self.settings.get("logo_opacity", 0.5)
            logo_size    = self.settings.get("logo_size", 150)
            if logo_path:
                self.log_cb(f"  🔲  Logo: {os.path.basename(logo_path)}")

        export_with_dubbing(
            video, dubbed, srt_tmp, out_mp4,
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
        )

        for f in [srt_tmp, dubbed]:
            try:
                if f and os.path.exists(f): os.remove(f)
            except OSError:
                pass

        self.log_cb(f"  ✅  Lưu: {os.path.basename(out_mp4)}")
        self._set(row_num, ST_SUCCESS)
        # Ghi đường dẫn video hoàn thành vào cột D (có thể bấm mở)
        try:
            self._client.write_hyperlink(row_num, COL_OUTPUT, out_mp4,
                                         label=os.path.basename(out_mp4))
        except Exception:
            self._client.write_cell(row_num, COL_OUTPUT, out_mp4)
        self.row_update_cb(row_num, ST_SUCCESS, "", out_mp4)

    def _set(self, row: int, status: str, error: str = "") -> None:
        self._client.write_cell(row, COL_STATUS, status)
        if error:
            self._client.write_cell(row, COL_ERROR, error)
        elif status == ST_SUCCESS:
            self._client.write_cell(row, COL_ERROR, "")
        self.row_update_cb(row, status, error, "")
        time.sleep(0.2)
