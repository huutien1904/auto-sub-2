"""
Subtitle style presets for FFmpeg ASS/SRT rendering.
Each style defines colors, font, outline, shadow.
ASS color format: &HAABBGGRR  (AA=alpha 00=opaque, BB=blue, GG=green, RR=red)
"""

from typing import Dict, Tuple

# (canvas_text_color, canvas_bg_color, canvas_outline)
CanvasPreview = Tuple[str, str, str]

STYLES: Dict[str, dict] = {
    "Mặc định": {
        "FontName": "Arial", "Bold": 0, "Italic": -1,
        "PrimaryColour": "&H00000000",   # chữ đen
        "OutlineColour": "&H00FFFFFF",   # viền trắng (màu box)
        "BackColour":    "&H00FFFFFF",   # nền trắng đục
        "BorderStyle": 3,                # opaque box (chat bubble)
        "Outline": 8, "Shadow": 0,       # Outline=8 tạo padding trong bubble
        "_canvas": ("black", "white", "white"),
    },
    "Karaoke Vàng": {
        "FontName": "Arial Black", "Bold": 1, "Italic": -1,
        "PrimaryColour": "&H0000FFFF", "OutlineColour": "&H000000AA",
        "BackColour": "&H00000000", "BorderStyle": 1,
        "Outline": 3, "Shadow": 2,
        "_canvas": ("#FFFF00", "transparent", "#000088"),
    },
    "Highlight Xanh": {
        "FontName": "Arial", "Bold": 1, "Italic": -1,
        "PrimaryColour": "&H00FFFFFF", "OutlineColour": "&H00000000",
        "BackColour": "&HB4009900", "BorderStyle": 3,
        "Outline": 0, "Shadow": 0,
        "_canvas": ("white", "#009900AA", "black"),
    },
    "Tối giản": {
        "FontName": "Arial", "Bold": 0, "Italic": -1,
        "PrimaryColour": "&H00FFFFFF", "OutlineColour": "&H00333333",
        "BackColour": "&H00000000", "BorderStyle": 1,
        "Outline": 1, "Shadow": 0,
        "_canvas": ("white", "transparent", "#333333"),
    },
    "Mờ Dần": {
        "FontName": "Arial", "Bold": 0, "Italic": -1,
        "PrimaryColour": "&H00E8E8E8", "OutlineColour": "&H00222222",
        "BackColour": "&H60000000", "BorderStyle": 3,
        "Outline": 1, "Shadow": 1,
        "_canvas": ("#E8E8E8", "#00000099", "#222222"),
    },
    "Sạch đẹp": {
        "FontName": "Segoe UI", "Bold": 0, "Italic": -1,
        "PrimaryColour": "&H00FFFFFF", "OutlineColour": "&H00000000",
        "BackColour": "&H90000000", "BorderStyle": 3,
        "Outline": 2, "Shadow": 0,
        "_canvas": ("white", "#000000AA", "black"),
    },
    "Dễ đọc": {
        "FontName": "Arial", "Bold": 1, "Italic": -1,
        "PrimaryColour": "&H0000FFFF", "OutlineColour": "&H00000000",
        "BackColour": "&H00000000", "BorderStyle": 1,
        "Outline": 3, "Shadow": 2,
        "_canvas": ("#FFFF00", "transparent", "black"),
    },
    "Rạp phim": {
        "FontName": "Times New Roman", "Bold": 0, "Italic": -1,
        "PrimaryColour": "&H00FFFFFF", "OutlineColour": "&H00000000",
        "BackColour": "&HFF000000", "BorderStyle": 3,
        "Outline": 0, "Shadow": 0,
        "_canvas": ("white", "black", "black"),
    },
    "TikTok": {
        "FontName": "Arial Black", "Bold": 1, "Italic": -1,
        "PrimaryColour": "&H00FFFFFF", "OutlineColour": "&H00000000",
        "BackColour": "&H00000000", "BorderStyle": 1,
        "Outline": 3, "Shadow": 3,
        "_canvas": ("white", "transparent", "black"),
    },
    "TikTok Trắng": {
        "FontName": "Arial Black", "Bold": 1, "Italic": -1,
        "PrimaryColour": "&H00000000", "OutlineColour": "&H00FFFFFF",
        "BackColour": "&H00FFFFFF", "BorderStyle": 3,
        "Outline": 2, "Shadow": 0,
        "_canvas": ("black", "white", "white"),
    },
    "Reels Vàng": {
        "FontName": "Arial Black", "Bold": 1, "Italic": -1,
        "PrimaryColour": "&H0000D7FF", "OutlineColour": "&H00000000",
        "BackColour": "&H00000000", "BorderStyle": 1,
        "Outline": 3, "Shadow": 2,
        "_canvas": ("#FFD700", "transparent", "black"),
    },
    "Đậm Hiện Đại": {
        "FontName": "Arial Black", "Bold": 1, "Italic": -1,
        "PrimaryColour": "&H00FFFFFF", "OutlineColour": "&H00000000",
        "BackColour": "&HD0000000", "BorderStyle": 3,
        "Outline": 0, "Shadow": 0,
        "_canvas": ("white", "#000000DD", "black"),
    },
    "Vàng Nổi Bật": {
        "FontName": "Impact", "Bold": 1, "Italic": -1,
        "PrimaryColour": "&H0000FFFF", "OutlineColour": "&H00000000",
        "BackColour": "&H00000000", "BorderStyle": 1,
        "Outline": 4, "Shadow": 2,
        "_canvas": ("#FFFF00", "transparent", "black"),
    },
    "Trending Trắng": {
        "FontName": "Arial", "Bold": 1, "Italic": -1,
        "PrimaryColour": "&H00FFFFFF", "OutlineColour": "&H00AAAAAA",
        "BackColour": "&H40000000", "BorderStyle": 3,
        "Outline": 1, "Shadow": 1,
        "_canvas": ("white", "#00000066", "#AAAAAA"),
    },
}

DEFAULT_STYLE = "Mặc định"


def build_ffmpeg_style(style_name: str, font_size: int = 9,
                       margin_v: int = 25, margin_h: int = 15) -> str:
    """Return the force_style string for FFmpeg subtitles filter."""
    s = STYLES.get(style_name, STYLES[DEFAULT_STYLE])
    italic = s.get("Italic", -1)   # -1 = italic ON (ASS standard), 0 = off
    parts = [
        f"FontName={s['FontName']}",
        f"FontSize={font_size}",
        f"Bold={s['Bold']}",
        f"Italic={italic}",
        f"PrimaryColour={s['PrimaryColour']}",
        f"OutlineColour={s['OutlineColour']}",
        f"BackColour={s['BackColour']}",
        f"BorderStyle={s.get('BorderStyle', 1)}",
        f"Outline={s['Outline']}",
        f"Shadow={s['Shadow']}",
        f"MarginV={margin_v}",
        f"MarginL={margin_h}",
        f"MarginR={margin_h}",
        "Alignment=2",
    ]
    return ",".join(parts)


def get_canvas_colors(style_name: str) -> CanvasPreview:
    s = STYLES.get(style_name, STYLES[DEFAULT_STYLE])
    return s.get("_canvas", ("white", "#00000088", "black"))
