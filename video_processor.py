"""FFmpeg-based video processing: burn subtitles into video."""

import os
import random
import subprocess
import tempfile
from typing import Callable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from player_window import BlurRegion

_MUSIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music")
_MUSIC_EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}

_encoder_cache: list[list[str]] = []

def _best_encoder() -> list[str]:
    """Chọn encoder nhanh nhất có sẵn: NVENC (GPU Nvidia) > AMF (GPU AMD) > CPU ultrafast."""
    if _encoder_cache:
        return _encoder_cache[0]

    candidates = [
        # NVIDIA GPU
        ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "23"],
        # AMD GPU
        ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "23"],
        # Intel Quick Sync
        ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23"],
        # CPU fallback — ultrafast thay vì fast
        ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"],
    ]

    for args in candidates:
        test = subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=1",
             *args, "-f", "null", "-"],
            capture_output=True,
        )
        if test.returncode == 0:
            encoder = args[1]
            print(f"[Encoder] Dùng: {encoder}")
            _encoder_cache.append(args)
            return args

    fallback = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
    _encoder_cache.append(fallback)
    return fallback


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

        encode_args = _best_encoder()
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", vf_filter,
            "-c:a", "copy",
            *encode_args,
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
    blur_regions: Optional[list] = None,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> None:
    """
    Render video with:
      - dubbed Vietnamese audio mixed with (reduced) original audio
      - optionally burned Vietnamese subtitles
      - optionally blurred regions
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
        use_blur  = bool(blur_regions)

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
        video_filter_parts: List[str] = []
        cur_v = "0:v"   # current video label (no brackets yet)

        # Step 1: Blur regions (applied first, before subtitle burn)
        if use_blur:
            video_w, video_h, _, _ = get_video_info(video_path)
            blur_str, blur_out = build_blur_filter(blur_regions, video_w, video_h, cur_v)
            if blur_str:
                video_filter_parts.append(blur_str)
                cur_v = blur_out.strip("[]")

        # Step 2: Burn subtitles
        if safe_srt:
            from subtitle_styles import build_ffmpeg_style
            srt_ffmpeg = safe_srt.replace("\\", "/")
            if len(srt_ffmpeg) >= 2 and srt_ffmpeg[1] == ":":
                srt_ffmpeg = srt_ffmpeg[0] + "\\:" + srt_ffmpeg[2:]
            subtitle_style = build_ffmpeg_style(style_name, font_size=font_size)
            video_filter_parts.append(
                f"[{cur_v}]subtitles='{srt_ffmpeg}':force_style='{subtitle_style}'[vsub]"
            )
            cur_v = "vsub"

        # Step 3: Overlay logo
        if use_logo:
            dur    = get_video_duration(video_path) or 60.0
            margin = 20
            lx = f"(W-w-{margin})*(1-t/{dur:.2f})+{margin}*(t/{dur:.2f})"
            ly = f"{margin}+(H-h-{margin})*(t/{dur:.2f})"
            video_filter_parts.append(
                f"[{logo_input_idx}:v]scale={logo_size}:-1,format=rgba,"
                f"colorchannelmixer=aa={logo_opacity:.2f}[logo]"
            )
            video_filter_parts.append(
                f"[{cur_v}][logo]overlay=x='{lx}':y='{ly}'[vfinal]"
            )
            cur_v = "vfinal"

        # ── Assemble filter_complex ───────────────────────────────────────────
        all_parts = [audio_filter] + video_filter_parts
        filter_complex = ";".join(all_parts)

        # Map args
        if cur_v == "0:v":
            # No video filters applied at all
            map_args = ["-map", "0:v", "-map", "[audio_out]"]
        else:
            map_args = ["-map", f"[{cur_v}]", "-map", "[audio_out]"]

        # ── Build FFmpeg command ───────────────────────────────────────────────
        cmd = ["ffmpeg", "-y", "-i", video_path, "-i", dubbed_audio_path]
        if use_music:
            cmd += ["-stream_loop", "-1", "-i", music_path]
        if use_logo:
            cmd += ["-loop", "1", "-framerate", "25", "-i", logo_path]
        encode_args = _best_encoder()
        cmd += [
            "-filter_complex", filter_complex,
            *map_args,
            *encode_args,
            "-c:a", "aac",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
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


def get_video_info(video_path: str):
    """Return (width, height, fps, duration_sec) using FFprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        # lines: width, height, r_frame_rate (e.g. "30000/1001"), duration
        w = int(lines[0]) if len(lines) > 0 else 1920
        h = int(lines[1]) if len(lines) > 1 else 1080
        fps_str = lines[2] if len(lines) > 2 else "30/1"
        if "/" in fps_str:
            a, b = fps_str.split("/")
            fps = float(a) / float(b) if float(b) else 30.0
        else:
            fps = float(fps_str)
        dur = float(lines[3]) if len(lines) > 3 else 0.0
        return w, h, fps, dur
    except Exception:
        return 1920, 1080, 30.0, 0.0


def build_blur_filter(blur_regions: list, video_w: int, video_h: int,
                      input_label: str = "0:v"):
    """
    Build an FFmpeg filter_complex chain that applies all blur regions.

    Each region is a BlurRegion with percentage coords and a time range.
    Returns (filter_str, output_video_label) or (None, input_label) if no regions.

    The chain works by splitting the stream at each step:
      [prev] split [base][crop_input]
      [crop_input] crop=W:H:X:Y, avgblur=20 [blurred]
      [base][blurred] overlay=X:Y:enable='between(t,s,e)' [next]
    """
    if not blur_regions:
        return None, f"[{input_label}]"

    parts: List[str] = []
    current = input_label

    for i, region in enumerate(blur_regions):
        x = int(region.x_pct * video_w)
        y = int(region.y_pct * video_h)
        w = max(2, int(region.w_pct * video_w))
        h = max(2, int(region.h_pct * video_h))
        # FFmpeg requires even dimensions for most encoders
        w += w % 2
        h += h % 2
        # Clamp to video bounds
        x = min(x, video_w - w)
        y = min(y, video_h - h)

        base_lbl  = f"vbase{i}"
        crop_lbl  = f"vcrop{i}"
        blur_lbl  = f"vblr{i}"
        out_lbl   = f"vout{i}"
        t_expr    = f"between(t,{region.start_sec:.3f},{region.end_sec:.3f})"

        parts.append(f"[{current}]split=2[{base_lbl}][{crop_lbl}]")
        parts.append(f"[{crop_lbl}]crop={w}:{h}:{x}:{y},avgblur=20[{blur_lbl}]")
        parts.append(
            f"[{base_lbl}][{blur_lbl}]overlay={x}:{y}:enable='{t_expr}'[{out_lbl}]"
        )
        current = out_lbl

    return ";".join(parts), f"[{current}]"


def burn_subtitles(
    video_path: str,
    srt_path: str,
    output_path: str,
    font_size: int = 9,
    style_name: str = "Mặc định",
    blur_regions: Optional[list] = None,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> None:
    """
    Burn SRT subtitles into video, optionally applying blur regions.
    The SRT file path must not contain special characters for FFmpeg filter.
    We copy it to a safe temp location if needed.
    """
    if progress_callback:
        progress_callback("Đang chuẩn bị ghi phụ đề...", 0.05)

    # Copy SRT to a safe temp path (no spaces, no special chars)
    safe_srt = tempfile.mktemp(dir=tempfile.gettempdir(), suffix=".srt")
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    with open(safe_srt, "w", encoding="utf-8") as f:
        f.write(content)

    try:
        # On Windows, FFmpeg subtitles filter needs forward slashes and escaped colon
        srt_ffmpeg = safe_srt.replace("\\", "/")
        if len(srt_ffmpeg) >= 2 and srt_ffmpeg[1] == ":":
            srt_ffmpeg = srt_ffmpeg[0] + "\\:" + srt_ffmpeg[2:]

        from subtitle_styles import build_ffmpeg_style
        subtitle_style = build_ffmpeg_style(style_name, font_size=font_size)

        encode_args = _best_encoder()

        # ── With blur regions: use filter_complex ─────────────────────────────
        if blur_regions:
            video_w, video_h, _, _ = get_video_info(video_path)
            blur_filter, blur_out = build_blur_filter(blur_regions, video_w, video_h, "0:v")
            sub_filter = (
                f"{blur_out}subtitles='{srt_ffmpeg}':force_style='{subtitle_style}'[vfinal]"
            )
            filter_complex = f"{blur_filter};{sub_filter}" if blur_filter else sub_filter.replace(blur_out, "[0:v]")
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-filter_complex", filter_complex,
                "-map", "[vfinal]", "-map", "0:a",
                "-c:a", "copy",
                *encode_args,
                output_path,
            ]
        else:
            # ── No blur: use simple -vf ───────────────────────────────────────
            vf_filter = f"subtitles='{srt_ffmpeg}':force_style='{subtitle_style}'"
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vf", vf_filter,
                "-c:a", "copy",
                *encode_args,
                output_path,
            ]

        if progress_callback:
            progress_callback("Đang render video (có thể mất vài phút)...", 0.10)

        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")

        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg gặp lỗi khi ghi phụ đề:\n{result.stderr[-800:]}"
            )

        if progress_callback:
            progress_callback("Ghi phụ đề vào video thành công!", 1.0)

    finally:
        if os.path.exists(safe_srt):
            os.remove(safe_srt)
