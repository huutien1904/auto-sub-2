"""Glossary — bảng thuật ngữ cố định để tránh dịch sai."""

import re
from typing import List, Tuple

import config as cfg


def load() -> List[Tuple[str, str]]:
    """Trả về list (từ_gốc, dịch_sang) từ config."""
    data = cfg.load()
    return [(item["source"], item["target"])
            for item in data.get("glossary", [])
            if item.get("source") and item.get("target")]


def save(terms: List[Tuple[str, str]]) -> None:
    """Lưu danh sách thuật ngữ vào config."""
    data = cfg.load()
    data["glossary"] = [{"source": s, "target": t} for s, t in terms if s and t]
    cfg.save(data)


def apply(text: str, terms: List[Tuple[str, str]]) -> Tuple[str, dict]:
    """
    Thay thế từ gốc bằng placeholder trước khi dịch.
    Trả về (text_đã_thay, reverse_map).
    reverse_map: {placeholder: dịch_sang}
    """
    if not terms:
        return text, {}

    reverse_map = {}
    result = text
    for i, (source, target) in enumerate(terms):
        if not source:
            continue
        placeholder = f"__GTERM{i}__"
        # Thay thế case-insensitive, giữ nguyên dấu cách xung quanh
        pattern = re.compile(re.escape(source), re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(placeholder, result)
            reverse_map[placeholder] = target
    return result, reverse_map


def restore(text: str, reverse_map: dict) -> str:
    """Khôi phục placeholder → từ dịch đúng sau khi dịch xong."""
    for placeholder, target in reverse_map.items():
        text = text.replace(placeholder, target)
    return text


def apply_to_entries(entries, terms: List[Tuple[str, str]]) -> List[dict]:
    """
    Áp dụng glossary cho danh sách subtitle entries.
    Lưu reverse_map vào mỗi entry để restore sau khi dịch.
    Trả về list reverse_maps tương ứng.
    """
    reverse_maps = []
    for entry in entries:
        modified, rmap = apply(entry.original_text, terms)
        entry.original_text = modified
        reverse_maps.append(rmap)
    return reverse_maps


def restore_entries(entries, reverse_maps: List[dict]) -> None:
    """Khôi phục original_text và translated_text sau khi dịch."""
    for entry, rmap in zip(entries, reverse_maps):
        if rmap:
            entry.original_text   = restore(entry.original_text, rmap)
            entry.translated_text = restore(entry.translated_text, rmap)
