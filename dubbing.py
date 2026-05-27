"""
TTS dubbing engine.
Providers: Edge TTS (free) · OpenAI TTS · FPT.AI (Vietnamese regional voices)
Timing: each clip is speed-adjusted to fit within its subtitle duration.
"""

import asyncio
import os
import subprocess
import tempfile
import time
from typing import Callable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from subtitle_utils import SubtitleEntry

# ── Voice catalogs ────────────────────────────────────────────────────────────

EDGE_VOICES = {
    "Nữ — HoaiMy": "vi-VN-HoaiMyNeural",
    "Nam — NamMinh": "vi-VN-NamMinhNeural",
}

OPENAI_VOICES = {
    "Nova  (nữ, tự nhiên)": "nova",
    "Shimmer  (nữ, nhẹ nhàng)": "shimmer",
    "Alloy  (trung tính)": "alloy",
    "Echo  (nam)": "echo",
    "Fable  (nam, biểu cảm)": "fable",
    "Onyx  (nam, trầm ấm)": "onyx",
}

FPTAI_VOICES = {
    "Ban Mai  (Nữ miền Bắc) ⭐": "banmai",
    "Thu Minh  (Nữ miền Bắc)": "thuminh",
    "Lê Minh  (Nam miền Bắc)": "leminh",
    "Mỹ An  (Nữ miền Trung)": "myan",
    "Gia Huy  (Nam miền Trung)": "giahuy",
    "Ngọc Lam  (Nữ miền Trung)": "ngoclam",
    "Lan Nhi  (Nữ miền Nam)": "lannhi",
    "Linh San  (Nữ miền Nam)": "linhsan",
    "Minh Quang  (Nam miền Nam)": "minhquang",
}

TTS_PROVIDERS = {
    "Edge TTS  (miễn phí, 2 giọng)": "edge",
    "OpenAI TTS  (6 giọng, cần API key)": "openai",
    "FPT.AI  (9 giọng Việt vùng miền, cần API key)": "fptai",
}

PROVIDER_VOICES: dict[str, dict] = {
    "edge":   EDGE_VOICES,
    "openai": OPENAI_VOICES,
    "fptai":  FPTAI_VOICES,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def srt_time_to_ms(t: str) -> int:
    t = t.replace(",", ".")
    h, m, s = t.split(":")
    return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)


def _adjust_speed(src_path: str, speed: float) -> str:
    """
    Return path to a new WAV whose playback speed is multiplied by `speed`.
    Uses ffmpeg atempo (range 0.5–2.0 per filter; chained for >2.0).
    """
    speed = max(0.5, min(4.0, speed))
    if abs(speed - 1.0) < 0.07:
        return src_path          # nothing to do

    out = tempfile.mktemp(suffix=".wav")

    # atempo supports 0.5–2.0 per stage; chain two stages for higher values
    if speed <= 2.0:
        atempo = f"atempo={speed:.4f}"
    else:
        # e.g. speed=2.8 → atempo=2.0,atempo=1.4
        a1 = 2.0
        a2 = speed / a1
        atempo = f"atempo={a1:.4f},atempo={a2:.4f}"

    cmd = ["ffmpeg", "-y", "-i", src_path, "-filter:a", atempo, out]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not os.path.exists(out):
        return src_path          # fall back to original on error
    return out


# ── TTS backends ──────────────────────────────────────────────────────────────

async def _edge_async(text: str, voice: str, path: str) -> None:
    import edge_tts
    await edge_tts.Communicate(text, voice).save(path)


def _tts_edge(text: str, voice: str, path: str, speed_pct: int = 100, **_) -> None:
    """
    Primary: gTTS (Google TTS) — ổn định, miễn phí, không cần API key.
    Fallback: edge-tts nếu gTTS lỗi.
    Speed: áp dụng qua FFmpeg atempo sau khi generate.
    """
    generated = False

    # ── Primary: gTTS ─────────────────────────────────────────────────────────
    try:
        from gtts import gTTS
        gTTS(text=text, lang="vi", slow=False).save(path)
        if os.path.exists(path) and os.path.getsize(path) > 500:
            generated = True
    except Exception as e:
        print(f"[gTTS] Lỗi: {e} — dùng edge-tts fallback")

    # ── Fallback: edge-tts ────────────────────────────────────────────────────
    if not generated:
        try:
            asyncio.run(_edge_async(text, voice, path))
            if os.path.exists(path) and os.path.getsize(path) > 500:
                generated = True
        except Exception as e:
            raise RuntimeError(f"TTS thất bại: {e}")

    if not generated:
        raise RuntimeError("TTS trả về file trống")

    # ── Speed adjustment ──────────────────────────────────────────────────────
    if speed_pct != 100:
        adjusted = _adjust_speed(path, speed_pct / 100.0)
        if adjusted != path:
            os.replace(adjusted, path)


def _tts_openai(text: str, voice: str, path: str, api_key: str = "", speed_pct: int = 100, **_) -> None:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("Chưa cài openai.\nChạy: pip install openai")
    client = OpenAI(api_key=api_key)
    resp = client.audio.speech.create(model="tts-1", voice=voice, input=text)
    resp.stream_to_file(path)
    # Apply speed via atempo if not normal
    if speed_pct != 100:
        adjusted = _adjust_speed(path, speed_pct / 100.0)
        if adjusted != path:
            os.replace(adjusted, path)


def _tts_fptai(text: str, voice: str, path: str, api_key: str = "", **_) -> None:
    import requests as req
    url = "https://api.fpt.ai/hmi/tts/v5"
    headers = {
        "api-key": api_key,
        "voice": voice,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    r = req.post(url, headers=headers, data=text.encode("utf-8"), timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("error", 1) != 0:
        raise RuntimeError(f"FPT.AI lỗi: {data.get('message', 'unknown')}")

    audio_url = data["async"]
    # FPT.AI renders asynchronously — poll until the MP3 is ready
    for _ in range(15):
        time.sleep(1.5)
        ar = req.get(audio_url, timeout=15)
        if ar.status_code == 200 and len(ar.content) > 500:
            with open(path, "wb") as f:
                f.write(ar.content)
            return
    raise RuntimeError("FPT.AI: Audio chưa sẵn sàng sau 22 giây.")


_BACKENDS = {
    "edge":   _tts_edge,
    "openai": _tts_openai,
    "fptai":  _tts_fptai,
}


# ── Main dubbed track builder ─────────────────────────────────────────────────

def create_dubbed_track(
    entries: "List[SubtitleEntry]",
    video_duration_ms: int,
    voice: str = "vi-VN-NamMinhNeural",
    provider: str = "edge",
    api_key: str = "",
    speed_pct: int = 100,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> str:
    """
    1. Generate a TTS clip per subtitle entry.
    2. Speed-adjust each clip to fit within its subtitle duration.
    3. Overlay all clips onto a silent base track at the correct timestamps.
    4. Export and return path to the mixed WAV file.
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        raise RuntimeError("Chưa cài pydub.\nChạy: pip install pydub")

    backend = _BACKENDS.get(provider, _tts_edge)
    total = len(entries)
    generated: list[tuple] = [None] * total  # type: ignore

    # ── Step 1: generate raw TTS clips (parallel) ─────────────────────────────
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    done_count = 0
    lock = threading.Lock()

    def _generate_one(idx: int, entry):
        nonlocal done_count
        text = (entry.translated_text or entry.original_text).strip()
        if not text:
            return idx, entry, None
        raw_path = tempfile.mktemp(suffix=".mp3")
        try:
            backend(text, voice, raw_path, api_key=api_key, speed_pct=speed_pct)
            return idx, entry, raw_path
        except Exception as exc:
            print(f"[TTS] Bỏ qua dòng {idx+1}: {exc}")
            return idx, entry, None

    # FPT.AI rate-limits heavily → keep sequential; others can run in parallel
    max_workers = 1 if provider == "fptai" else 4

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_generate_one, i, e): i for i, e in enumerate(entries)}
        for fut in as_completed(futures):
            idx, entry, raw_path = fut.result()
            generated[idx] = (entry, raw_path)
            with lock:
                done_count += 1
            if progress_callback:
                progress_callback(
                    f"Đang tạo giọng đọc... ({done_count}/{total})",
                    done_count / total * 0.75,
                )

    # ── Step 2 & 3: adjust speed then overlay ────────────────────────────────
    if progress_callback:
        progress_callback("Đang căn chỉnh timing và ghép âm thanh...", 0.80)

    base = AudioSegment.silent(duration=video_duration_ms + 3000)
    adjusted_tmp: list[str] = []

    for entry, raw_path in generated:
        if raw_path is None or not os.path.exists(raw_path):
            continue

        start_ms  = srt_time_to_ms(entry.start_time)
        end_ms    = srt_time_to_ms(entry.end_time)
        seg_ms    = max(end_ms - start_ms, 200)   # guard against 0-length

        try:
            clip = AudioSegment.from_file(raw_path)
            clip_ms = len(clip)

            if clip_ms > seg_ms:
                speed      = clip_ms / seg_ms
                adj_path   = _adjust_speed(raw_path, speed)
                if adj_path != raw_path:
                    adjusted_tmp.append(adj_path)
                    clip = AudioSegment.from_file(adj_path)

            base = base.overlay(clip, position=start_ms)
        except Exception as exc:
            print(f"[Mix] Lỗi: {exc}")
        finally:
            try:
                os.remove(raw_path)
            except OSError:
                pass

    for p in adjusted_tmp:
        try:
            os.remove(p)
        except OSError:
            pass

    # ── Step 4: export ───────────────────────────────────────────────────────
    out_wav = tempfile.mktemp(suffix=".wav")
    base.export(out_wav, format="wav")

    if progress_callback:
        progress_callback("Tạo giọng lồng tiếng hoàn thành!", 1.0)

    return out_wav
