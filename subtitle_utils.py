"""SRT subtitle file parsing and writing utilities."""

import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class SubtitleEntry:
    index: int
    start_time: str
    end_time: str
    original_text: str
    translated_text: str = ""


def parse_srt(content: str) -> List[SubtitleEntry]:
    entries = []
    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
            time_match = re.match(
                r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
                lines[1].strip(),
            )
            if not time_match:
                continue
            start_time = time_match.group(1).replace(".", ",")
            end_time = time_match.group(2).replace(".", ",")
            text = "\n".join(lines[2:]).strip()
            entries.append(
                SubtitleEntry(
                    index=index,
                    start_time=start_time,
                    end_time=end_time,
                    original_text=text,
                )
            )
        except (ValueError, IndexError):
            continue

    return entries


def write_srt(entries: List[SubtitleEntry], use_translation: bool = True) -> str:
    lines = []
    for i, entry in enumerate(entries, 1):
        text = (
            entry.translated_text
            if use_translation and entry.translated_text.strip()
            else entry.original_text
        )
        lines.append(str(i))
        lines.append(f"{entry.start_time} --> {entry.end_time}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def whisper_to_entries(segments: list) -> List[SubtitleEntry]:
    entries = []
    if not segments:
        return entries
    for i, seg in enumerate(segments, 1):
        if seg is None:
            continue
        try:
            start = _seconds_to_srt_time(seg.get("start", 0) or 0)
            end   = _seconds_to_srt_time(seg.get("end",   0) or 0)
            text  = (seg.get("text") or "").strip()
        except Exception:
            continue
        if text:
            entries.append(
                SubtitleEntry(
                    index=i,
                    start_time=start,
                    end_time=end,
                    original_text=text,
                )
            )
    return entries


def _seconds_to_srt_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
