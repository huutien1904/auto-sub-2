"""
Batch processor — Google Sheets via Apps Script Web App.
Không cần Service Account JSON, không cần Google Cloud Console.
Chỉ cần URL của Apps Script Web App đã deploy.

Thiết lập (1 lần duy nhất):
1. Mở Google Sheet của bạn
2. Extensions → Apps Script → dán đoạn script bên dưới → Save
3. Deploy → New deployment → Web app → Execute as: Me, Who has access: Anyone → Deploy
4. Copy URL dán vào ứng dụng

======= APPS SCRIPT CODE (copy vào Google Apps Script) =======

function doGet(e) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const data  = sheet.getDataRange().getValues();
  return ContentService
    .createTextOutput(JSON.stringify({ok:true, data:data}))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    const p     = JSON.parse(e.postData.contents);
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    sheet.getRange(p.row, p.col).setValue(p.value);
    return ContentService
      .createTextOutput(JSON.stringify({ok:true}))
      .setMimeType(ContentService.MimeType.JSON);
  } catch(err) {
    return ContentService
      .createTextOutput(JSON.stringify({ok:false, error:err.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

==============================================================
"""

import os
import tempfile
import time
from typing import Callable, Dict, List, Optional, Tuple

import requests as _req

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


# ── Apps Script API ───────────────────────────────────────────────────────────

class SheetClient:
    """Thin wrapper around Apps Script Web App endpoints."""

    def __init__(self, web_app_url: str):
        self.url = web_app_url.strip()

    def read_all(self) -> List[List[str]]:
        """Return all rows as list of lists."""
        r = _req.get(self.url, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Apps Script lỗi: {data}")
        return data["data"]

    def write_cell(self, row: int, col: int, value: str) -> None:
        """Write a single cell (1-indexed)."""
        r = _req.post(
            self.url,
            json={"row": row, "col": col, "value": value},
            timeout=15,
        )
        r.raise_for_status()

    def ensure_header(self) -> None:
        """Make sure row 1 has correct headers."""
        rows = self.read_all()
        if not rows or rows[0][:3] != ["Link video", "Trạng thái", "Lý do lỗi"]:
            for col, hdr in enumerate(["Link video", "Trạng thái", "Lý do lỗi"], 1):
                self.write_cell(1, col, hdr)


def get_pending_rows(rows: List[List[str]]) -> List[Tuple[int, str]]:
    """Return (sheet_row_number, link) for rows with status 'new'."""
    pending = []
    for i, row in enumerate(rows):
        if i == 0:
            continue   # skip header
        link   = row[0].strip() if len(row) > 0 else ""
        status = row[1].strip().lower() if len(row) > 1 else ""
        if link and status == ST_NEW:
            pending.append((i + 1, link))   # sheet rows are 1-indexed
    return pending


def test_connection(web_app_url: str) -> Tuple[bool, str]:
    """Return (ok, message)."""
    try:
        client = SheetClient(web_app_url)
        rows   = client.read_all()
        return True, f"Kết nối thành công! Sheet có {len(rows)} hàng."
    except Exception as e:
        return False, str(e)


# ── Main batch pipeline ───────────────────────────────────────────────────────

class BatchProcessor:
    def __init__(
        self,
        web_app_url: str,
        output_dir: str,
        settings: Dict,
        log_cb:        Optional[Callable[[str], None]]        = None,
        progress_cb:   Optional[Callable[[int, int], None]]   = None,
        row_update_cb: Optional[Callable[[int, str, str], None]] = None,
    ):
        self.url           = web_app_url
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
            self.log_cb("🔗  Đang kết nối Google Sheets qua Apps Script...")
            self._client = SheetClient(self.url)
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
        os.makedirs(self.output_dir, exist_ok=True)
        video = download_video(clean, self.output_dir,
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

        base    = os.path.splitext(os.path.basename(video))[0][:40]
        out_mp4 = os.path.join(self.output_dir, f"{base}_vi.mp4")

        export_with_dubbing(
            video, dubbed, srt_tmp, out_mp4,
            original_volume=self.settings.get("orig_vol", 0.05),
            dubbed_volume=self.settings.get("dub_vol", 1.0),
            font_size=self.settings.get("font_size", 9),
            style_name=self.settings.get("sub_style", DEFAULT_STYLE),
            progress_callback=lambda m, p: self.log_cb(f"  {m}"),
        )

        for f in [srt_tmp, dubbed]:
            try:
                if f and os.path.exists(f): os.remove(f)
            except OSError:
                pass

        self.log_cb(f"  ✅  Lưu: {os.path.basename(out_mp4)}")
        self._set(row_num, ST_SUCCESS)

    def _set(self, row: int, status: str, error: str = "") -> None:
        self._client.write_cell(row, COL_STATUS, status)
        if error:
            self._client.write_cell(row, COL_ERROR, error)
        elif status == ST_SUCCESS:
            self._client.write_cell(row, COL_ERROR, "")
        self.row_update_cb(row, status, error)
        time.sleep(0.2)
