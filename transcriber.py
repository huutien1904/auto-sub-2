"""Whisper-based speech-to-text transcription."""

import os
import subprocess
import tempfile
from typing import Callable, List, Optional


def check_ffmpeg() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def extract_audio(video_path: str) -> str:
    """Extract mono 16kHz WAV from video using FFmpeg. Returns temp file path."""
    temp_audio = tempfile.mktemp(suffix=".wav")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        temp_audio,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg không thể trích xuất âm thanh:\n{result.stderr[-500:]}")
    return temp_audio


def transcribe_video(
    video_path: str,
    model_size: str = "base",
    language: str = "zh",
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> List[dict]:
    """Full pipeline: extract audio then transcribe with Whisper."""
    import whisper

    if progress_callback:
        progress_callback("Đang trích xuất âm thanh...", 0.02)

    audio_path = extract_audio(video_path)

    try:
        if progress_callback:
            progress_callback(f"Đang tải mô hình Whisper ({model_size})...", 0.08)

        model = whisper.load_model(model_size)

        if progress_callback:
            progress_callback("Đang nhận dạng giọng nói (có thể mất vài phút)...", 0.15)

        result = model.transcribe(
            audio_path,
            language=language,
            task="transcribe",
            verbose=False,
            fp16=False,
        )

        if progress_callback:
            progress_callback("Nhận dạng giọng nói hoàn thành!", 0.60)

        return result["segments"]

    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)
