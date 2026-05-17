"""FFmpeg-based video processing: burn subtitles into video."""

import os
import subprocess
import tempfile
from typing import Callable, Optional


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
        # Build filter_complex
        # [0:a] = original audio at reduced volume
        # [1:a] = dubbed Vietnamese track
        # mix both, then optionally burn subtitles onto video
        # BUG FIX 2: normalize=0 giữ nguyên volume, không chia đôi
        # BUG FIX 3: dùng dubbed_volume thực sự từ slider
        audio_filter = (
            f"[0:a]volume={original_volume:.2f}[orig];"
            f"[1:a]volume={dubbed_volume:.2f}[dub];"
            "[orig][dub]amix=inputs=2:duration=longest:normalize=0:dropout_transition=0[audio_out]"
        )

        if safe_srt:
            from subtitle_styles import build_ffmpeg_style
            srt_ffmpeg = safe_srt.replace("\\", "/")
            if len(srt_ffmpeg) >= 2 and srt_ffmpeg[1] == ":":
                srt_ffmpeg = srt_ffmpeg[0] + "\\:" + srt_ffmpeg[2:]
            subtitle_style = build_ffmpeg_style(style_name, font_size=font_size)
            video_filter = f"[0:v]subtitles='{srt_ffmpeg}':force_style='{subtitle_style}'[video_out]"
            filter_complex = audio_filter + ";" + video_filter
            map_args = ["-map", "[video_out]", "-map", "[audio_out]"]
        else:
            filter_complex = audio_filter
            map_args = ["-map", "0:v", "-map", "[audio_out]"]

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", dubbed_audio_path,
            "-filter_complex", filter_complex,
            *map_args,
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
