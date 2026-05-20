"""FFmpeg-based video processing: burn subtitles into video."""

import os
import random
import subprocess
import tempfile
from typing import Callable, Optional

_MUSIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music")
_MUSIC_EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}


def pick_random_music() -> Optional[str]:
    """Chọn ngẫu nhiên 1 file nhạc từ thư mục music/. Trả về None nếu không có."""
    if not os.path.isdir(_MUSIC_DIR):
        return None
    files = [
        os.path.join(_MUSIC_DIR, f)
        for f in os.listdir(_MUSIC_DIR)
        if os.path.splitext(f)[1].lower() in _MUSIC_EXTS
    ]
    return random.choice(files) if files else None


def check_ffmpeg() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _get_vietnamese_font() -> str:
    """Return path to a font that supports Vietnamese characters on Windows."""
    candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\times.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def burn_subtitles(
    video_path: str,
    srt_path: str,
    output_path: str,
    font_size: int = 9,
    style_name: str = "Mặc định",
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> None:
    """
    Burn SRT subtitles into video.
    The SRT file path must not contain special characters for FFmpeg filter.
    We copy it to a safe temp location if needed.
    """
    if progress_callback:
        progress_callback("Đang chuẩn bị ghi phụ đề...", 0.05)

    # Copy SRT to a safe temp path (no spaces, no special chars)
    safe_srt = tempfile.mktemp(dir=tempfile.gettempdir(), suffix=".srt")
    # Overwrite with same content to get a clean path
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    with open(safe_srt, "w", encoding="utf-8") as f:
        f.write(content)

    try:
        # On Windows, FFmpeg subtitles filter needs forward slashes and escaped colon
        srt_ffmpeg = safe_srt.replace("\\", "/")
        # Escape colon in drive letter: C:/... → C\:/...
        if len(srt_ffmpeg) >= 2 and srt_ffmpeg[1] == ":":
            srt_ffmpeg = srt_ffmpeg[0] + "\\:" + srt_ffmpeg[2:]

        from subtitle_styles import build_ffmpeg_style
        subtitle_style = build_ffmpeg_style(style_name, font_size=font_size)

        vf_filter = f"subtitles='{srt_ffmpeg}':force_style='{subtitle_style}'"

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", vf_filter,
            "-c:a", "copy",
            "-preset", "fast",
            "-crf", "23",
            output_path,
        ]

        if progress_callback:
            progress_callback("Đang render video (có thể mất vài phút)...", 0.10)

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg gặp lỗi khi ghi phụ đề:\n{result.stderr[-800:]}"
            )

        if progress_callback:
            progress_callback("Ghi phụ đề vào video thành công!", 1.0)

    finally:
        if os.path.exists(safe_srt):
            os.remove(safe_srt)


def export_with_dubbing(
    video_path: str,
    dubbed_audio_path: str,
    srt_path: Optional[str],
    output_path: str,
    original_volume: float = 0.15,
    dubbed_volume: float = 1.0,
    font_size: int = 9,
    style_name: str = "Mặc định",
    music_path: Optional[str] = None,
    music_volume: float = 0.12,
    logo_path: Optional[str] = None,
    logo_opacity: float = 0.5,
    logo_size: int = 150,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> None:
    """
    Render video with:
      - dubbed Vietnamese audio mixed with (reduced) original audio
      - optionally burned Vietnamese subtitles
    """
    if progress_callback:
        progress_callback("Đang render video lồng tiếng...", 0.05)

    safe_srt: Optional[str] = None
    if srt_path:
        safe_srt = tempfile.mktemp(dir=tempfile.gettempdir(), suffix=".srt")
        with open(srt_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        with open(safe_srt, "w", encoding="utf-8") as f:
            f.write(content)

    try:
        use_music = bool(music_path and os.path.exists(music_path))
        use_logo  = bool(logo_path  and os.path.exists(logo_path))

        # Input index: 0=video, 1=dubbed, 2=music(nếu có), 2or3=logo(nếu có)
        logo_input_idx = 2 + (1 if use_music else 0)

        # ── Audio filter ──────────────────────────────────────────────────────
        if use_music:
            audio_filter = (
                f"[0:a]volume={original_volume:.2f}[orig];"
                f"[1:a]volume={dubbed_volume:.2f}[dub];"
                f"[2:a]volume={music_volume:.2f}[music];"
                "[orig][dub][music]amix=inputs=3:duration=first:normalize=0:dropout_transition=0[audio_out]"
            )
        else:
            audio_filter = (
                f"[0:a]volume={original_volume:.2f}[orig];"
                f"[1:a]volume={dubbed_volume:.2f}[dub];"
                "[orig][dub]amix=inputs=2:duration=longest:normalize=0:dropout_transition=0[audio_out]"
            )

        # ── Video filter chain ────────────────────────────────────────────────
        video_filters = []
        cur_v = "[0:v]"   # label của video stream hiện tại

        if safe_srt:
            from subtitle_styles import build_ffmpeg_style
            srt_ffmpeg = safe_srt.replace("\\", "/")
            if len(srt_ffmpeg) >= 2 and srt_ffmpeg[1] == ":":
                srt_ffmpeg = srt_ffmpeg[0] + "\\:" + srt_ffmpeg[2:]
            subtitle_style = build_ffmpeg_style(style_name, font_size=font_size)
            video_filters.append(
                f"[0:v]subtitles='{srt_ffmpeg}':force_style='{subtitle_style}'[vsub]"
            )
            cur_v = "[vsub]"

        if use_logo:
            dur    = get_video_duration(video_path) or 60.0
            margin = 20
            lx = f"(W-w-{margin})*(1-t/{dur:.2f})+{margin}*(t/{dur:.2f})"
            ly = f"{margin}+(H-h-{margin})*(t/{dur:.2f})"
            video_filters.append(
                f"[{logo_input_idx}:v]scale={logo_size}:-1,format=rgba,"
                f"colorchannelmixer=aa={logo_opacity:.2f}[logo]"
            )
            video_filters.append(
                f"{cur_v}[logo]overlay=x='{lx}':y='{ly}'[vfinal]"
            )
            cur_v = "[vfinal]"

        # Ghép toàn bộ filter
        all_filters = [audio_filter] + video_filters
        filter_complex = ";".join(all_filters)

        # Map args
        map_args = ["-map", cur_v, "-map", "[audio_out]"]
        # Nếu không có video filter nào → dùng stream copy
        if cur_v == "[0:v]":
            map_args = ["-map", "0:v", "-map", "[audio_out]"]

        # ── Build FFmpeg command ───────────────────────────────────────────────
        cmd = ["ffmpeg", "-y", "-i", video_path, "-i", dubbed_audio_path]
        if use_music:
            # -stream_loop -1 loop nhạc vô hạn, tự cắt theo độ dài video
            cmd += ["-stream_loop", "-1", "-i", music_path]
        if use_logo:
            cmd += ["-i", logo_path]
        cmd += [
            "-filter_complex", filter_complex,
            *map_args,
            "-c:v", "libx264",   # ép H.264 — tương thích mọi thiết bị
            "-c:a", "aac",
            "-preset", "fast",
            "-crf", "23",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg lỗi lồng tiếng:\n{result.stderr[-800:]}")

        if progress_callback:
            progress_callback("✅  Xuất video lồng tiếng thành công!", 1.0)

    finally:
        if safe_srt and os.path.exists(safe_srt):
            os.remove(safe_srt)


def get_video_duration(video_path: str) -> float:
    """Return video duration in seconds using FFprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0
