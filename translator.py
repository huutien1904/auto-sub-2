"""Translation engine — supports Google Translate (free), OpenAI, and Anthropic Claude."""

import time
from typing import Callable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from subtitle_utils import SubtitleEntry


def translate_entries(
    entries: "List[SubtitleEntry]",
    source_lang: str = "zh-CN",
    target_lang: str = "vi",
    provider: str = "google",
    api_key: str = "",
    model: str = "",
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> None:
    """Translate subtitle entries in-place (modifies translated_text)."""
    if provider == "openai":
        _translate_openai(entries, source_lang, target_lang, api_key, model, progress_callback)
    elif provider == "claude":
        _translate_claude(entries, source_lang, target_lang, api_key, model, progress_callback)
    else:
        _translate_google(entries, source_lang, target_lang, progress_callback)


# ── Google Translate (free) ───────────────────────────────────────────────────

def _translate_google(entries, source_lang, target_lang, progress_callback):
    from deep_translator import GoogleTranslator

    translator = GoogleTranslator(source=source_lang, target=target_lang)
    total = len(entries)

    for i, entry in enumerate(entries):
        text = entry.original_text.strip()
        if not text:
            entry.translated_text = ""
            continue
        try:
            result = translator.translate(text[:4500])
            entry.translated_text = result or text
        except Exception as exc:
            print(f"[Google] Lỗi dòng {i+1}: {exc}")
            entry.translated_text = text

        if progress_callback:
            progress_callback(f"[Google Translate]  Đang dịch... ({i+1}/{total})", (i+1) / total)

        time.sleep(0.08)


# ── OpenAI ────────────────────────────────────────────────────────────────────

def _translate_openai(entries, source_lang, target_lang, api_key, model, progress_callback):
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "Chưa cài thư viện openai.\nChạy lệnh: pip install openai"
        )

    client = OpenAI(api_key=api_key)
    model = model or "gpt-4o-mini"
    total = len(entries)
    BATCH = 25

    system_prompt = (
        "Bạn là một chuyên gia dịch thuật và biên kịch xuất sắc, chuyên xử lý phụ đề cho video ngắn "
        "(TikTok, Reels, Shorts). Nhiệm vụ của bạn là dịch danh sách phụ đề từ ngôn ngữ gốc sang Tiếng Việt.\n\n"
        "Hãy tuân thủ nghiêm ngặt các quy tắc sau:\n"
        "1. KHÔNG dịch word-by-word. Hãy dịch thoát ý, tự nhiên, mượt mà theo đúng ngữ cảnh "
        "văn phong nói của đời sống hoặc giới trẻ Việt Nam.\n"
        "2. Bản dịch phải ngắn gọn, súc tích để người nghe kịp hiểu trong video ngắn.\n"
        "3. Chú ý ngữ cảnh của các đại từ nhân xưng (Tôi - Bạn, Anh - Em, Anh ấy, Cô ấy...) "
        "sao cho đồng nhất từ đầu đến cuối video dựa vào nội dung câu thoại.\n"
        "4. Giữ nguyên các thuật ngữ chuyên ngành, tên riêng, hoặc từ mượn phổ biến "
        "nếu dịch sang tiếng Việt nghe bị sượng.\n"
        "5. Giữ nguyên định dạng số thứ tự và cấu trúc dòng để không làm lệch phụ đề."
    )

    for batch_start in range(0, total, BATCH):
        batch = entries[batch_start : batch_start + BATCH]
        # Build numbered list, skip empty
        lines = [(j + 1, e.original_text.strip()) for j, e in enumerate(batch) if e.original_text.strip()]
        if not lines:
            continue

        numbered = "\n".join(f"{n}. {t}" for n, t in lines)
        prompt = (
            "Dịch các câu phụ đề sau sang tiếng Việt, giữ nguyên số thứ tự.\n"
            "Chỉ trả về danh sách: số. bản dịch — không giải thích, không thêm bất kỳ nội dung nào khác.\n\n"
            + numbered
        )

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.3,
            )
            translated_map = _parse_numbered(resp.choices[0].message.content)
            for j, entry in enumerate(batch):
                entry.translated_text = translated_map.get(j + 1, entry.original_text)
        except Exception as exc:
            for entry in batch:
                entry.translated_text = entry.original_text
            raise RuntimeError(f"OpenAI API lỗi: {exc}")

        done = min(batch_start + BATCH, total)
        if progress_callback:
            progress_callback(f"[OpenAI {model}]  Đang dịch... ({done}/{total})", done / total)

        time.sleep(0.3)


# ── Anthropic Claude ──────────────────────────────────────────────────────────

def _translate_claude(entries, source_lang, target_lang, api_key, model, progress_callback):
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "Chưa cài thư viện anthropic.\nChạy lệnh: pip install anthropic"
        )

    client = anthropic.Anthropic(api_key=api_key)
    model = model or "claude-haiku-4-5-20251001"
    total = len(entries)
    BATCH = 25

    system_prompt = (
        "Bạn là một chuyên gia dịch thuật và biên kịch xuất sắc, chuyên xử lý phụ đề cho video ngắn "
        "(TikTok, Reels, Shorts). Nhiệm vụ của bạn là dịch danh sách phụ đề từ ngôn ngữ gốc sang Tiếng Việt.\n\n"
        "Hãy tuân thủ nghiêm ngặt các quy tắc sau:\n"
        "1. KHÔNG dịch word-by-word. Hãy dịch thoát ý, tự nhiên, mượt mà theo đúng ngữ cảnh "
        "văn phong nói của đời sống hoặc giới trẻ Việt Nam.\n"
        "2. Bản dịch phải ngắn gọn, súc tích để người nghe kịp hiểu trong video ngắn.\n"
        "3. Chú ý ngữ cảnh của các đại từ nhân xưng (Tôi - Bạn, Anh - Em, Anh ấy, Cô ấy...) "
        "sao cho đồng nhất từ đầu đến cuối video dựa vào nội dung câu thoại.\n"
        "4. Giữ nguyên các thuật ngữ chuyên ngành, tên riêng, hoặc từ mượn phổ biến "
        "nếu dịch sang tiếng Việt nghe bị sượng.\n"
        "5. Giữ nguyên định dạng số thứ tự và cấu trúc dòng để không làm lệch phụ đề."
    )

    for batch_start in range(0, total, BATCH):
        batch = entries[batch_start : batch_start + BATCH]
        lines = [(j + 1, e.original_text.strip()) for j, e in enumerate(batch) if e.original_text.strip()]
        if not lines:
            continue

        numbered = "\n".join(f"{n}. {t}" for n, t in lines)
        prompt = (
            "Dịch các câu phụ đề sau sang tiếng Việt, giữ nguyên số thứ tự.\n"
            "Chỉ trả về danh sách: số. bản dịch — không giải thích, không thêm bất kỳ nội dung nào khác.\n\n"
            + numbered
        )

        try:
            msg = client.messages.create(
                model=model,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            translated_map = _parse_numbered(msg.content[0].text)
            for j, entry in enumerate(batch):
                entry.translated_text = translated_map.get(j + 1, entry.original_text)
        except Exception as exc:
            for entry in batch:
                entry.translated_text = entry.original_text
            raise RuntimeError(f"Claude API lỗi: {exc}")

        done = min(batch_start + BATCH, total)
        if progress_callback:
            progress_callback(f"[Claude {model}]  Đang dịch... ({done}/{total})", done / total)

        time.sleep(0.2)


# ── Utility ───────────────────────────────────────────────────────────────────

def _parse_numbered(text: str) -> dict:
    """Parse '1. translated text' lines → {1: 'translated text', ...}"""
    result = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        dot = line.find(".")
        if dot > 0:
            try:
                num = int(line[:dot].strip())
                content = line[dot + 1:].strip()
                if content:
                    result[num] = content
            except ValueError:
                pass
    return result
