"""Video downloader via yt-dlp — Douyin, Bilibili, Kuaishou, RedNote + 1000+ sites."""

import os
import re
from typing import Callable, Optional


PLATFORM_MAP = {
    "douyin.com":       "Douyin",
    "iesdouyin.com":    "Douyin",
    "v.douyin.com":     "Douyin",
    "bilibili.com":     "Bilibili",
    "b23.tv":           "Bilibili",
    "kuaishou.com":     "Kuaishou",
    "gifshow.com":      "Kuaishou",
    "xiaohongshu.com":  "RedNote (小红书)",
    "xhslink.com":      "RedNote (小红书)",
    "rednote.com":      "RedNote (小红书)",
    "youtube.com":      "YouTube",
    "youtu.be":         "YouTube",
    "tiktok.com":       "TikTok",
    "twitter.com":      "Twitter/X",
    "x.com":            "Twitter/X",
    "facebook.com":     "Facebook",
    "instagram.com":    "Instagram",
}


def detect_platform(url: str) -> str:
    url_lower = url.lower()
    for domain, name in PLATFORM_MAP.items():
        if domain in url_lower:
            return name
    return "Unknown"


def extract_url(text: str) -> Optional[str]:
    """
    Extract the first http/https URL from a block of text.
    Handles Douyin/Kuaishou/RedNote share snippets that mix Chinese text with a URL.
    Example input:
      '1.53 d@N.WZ ... 今天教你... https://v.douyin.com/U5q6EzxzU_8/ 复制此链接...'
    Returns:
      'https://v.douyin.com/U5q6EzxzU_8/'
    """
    import re
    # Find all http/https tokens (stop at whitespace)
    matches = re.findall(r'https?://\S+', text)
    if not matches:
        return None

    url = matches[0]
    # Strip trailing Chinese/full-width punctuation and common junk chars
    url = re.sub(r'[　-〿一-鿿＀-￯，。！？、；：""''（）【】《》]+$', '', url)
    url = url.rstrip('.,!?;:)>]')
    return url if url.startswith('http') else None


_COOKIES_SAVE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cookies.txt"
)


def _find_saved_cookies() -> Optional[str]:
    """Return path to saved cookies.txt if it exists and has content."""
    if os.path.exists(_COOKIES_SAVE_PATH) and os.path.getsize(_COOKIES_SAVE_PATH) > 50:
        return _COOKIES_SAVE_PATH
    return None


def save_cookies_file(src_path: str) -> str:
    """Copy a cookies.txt file to the app directory for reuse. Returns dest path."""
    import shutil
    shutil.copy2(src_path, _COOKIES_SAVE_PATH)
    return _COOKIES_SAVE_PATH


def clear_cookies_file() -> None:
    if os.path.exists(_COOKIES_SAVE_PATH):
        os.remove(_COOKIES_SAVE_PATH)


def _add_browser_cookies(ydl_opts: dict) -> bool:
    """
    Try to find an installed browser and use its cookies.
    Returns True if a browser was found and configured.
    Priority: Chrome → Edge → Firefox → Brave → Opera
    """
    import subprocess, shutil

    BROWSERS = [
        ("chrome",  r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("chrome",  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ("edge",    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ("edge",    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ("firefox", r"C:\Program Files\Mozilla Firefox\firefox.exe"),
        ("brave",   r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ("opera",   r"C:\Users\NITRO\AppData\Local\Programs\Opera\launcher.exe"),
    ]

    for browser_name, exe_path in BROWSERS:
        if os.path.exists(exe_path):
            ydl_opts["cookiesfrombrowser"] = (browser_name, None, None, None)
            return True

    # Fallback: check PATH
    for browser_name in ("chrome", "chromium", "edge", "firefox"):
        if shutil.which(browser_name):
            ydl_opts["cookiesfrombrowser"] = (browser_name, None, None, None)
            return True

    return False


def _playwright_download(
    url: str,
    output_dir: str,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> str:
    """
    Download Douyin/Kuaishou/RedNote video by intercepting actual stream URLs
    via a headless Playwright browser. Bypasses yt-dlp extractor issues.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Chưa cài playwright.\nChạy: pip install playwright && playwright install chromium")

    import requests as req

    video_urls: list[str] = []
    page_title = ["video"]

    STREAM_DOMAINS = [
        "douyinvod.com", "zjcdn.com", "dy-o.zjcdn", "ixigua.com",
        "kuaishouzt.com", "kspkg.com", "liveztb.com",
        "xiaohongshu.com/media", "xhscdn.com",
        "aweme/v1/play", "snssdk.com",
    ]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            viewport={"width": 1280, "height": 720},
        )

        page = ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        def _on_response(resp):
            rurl = resp.url
            if any(d in rurl for d in STREAM_DOMAINS):
                if rurl not in video_urls:
                    video_urls.append(rurl)

        page.on("response", _on_response)

        if progress_callback:
            progress_callback("Đang mở trang video...", 0.05)

        try:
            page.goto(url, timeout=30000, wait_until="networkidle")
        except Exception:
            pass  # Timeout is fine — networkidle may never fire, we just need intercepts
        page.wait_for_timeout(4000)

        try:
            page_title[0] = page.title().strip()[:60] or "video"
        except Exception:
            pass

        # Get cookies for download requests
        cookies = {c["name"]: c["value"] for c in ctx.cookies() if c["value"]}
        browser.close()

    if not video_urls:
        raise RuntimeError(
            "Không tìm thấy URL video trong trang.\n"
            "Video có thể đã bị xóa hoặc cần đăng nhập."
        )

    if progress_callback:
        progress_callback(f"Tìm thấy {len(video_urls)} URL video, đang tải...", 0.20)

    # Pick best quality URL
    def _priority(u: str) -> int:
        if "aweme/v1/play" in u:  return 0   # direct Douyin play URL
        if "v3-web-prime" in u:   return 1
        if "v3-web" in u:         return 2
        if "douyinvod" in u:      return 3
        return 10

    video_urls.sort(key=_priority)
    best_url = video_urls[0]

    os.makedirs(output_dir, exist_ok=True)
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", page_title[0]) or "douyin_video"
    out_path = os.path.join(output_dir, f"{safe_title}.mp4")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
    }

    with req.get(best_url, headers=headers, cookies=cookies, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                f.write(chunk)
                done += len(chunk)
                if total > 0 and progress_callback:
                    pct = done / total
                    mb_done  = done  / 1_048_576
                    mb_total = total / 1_048_576
                    progress_callback(
                        f"Đang tải... ({mb_done:.1f}/{mb_total:.1f} MB)",
                        0.20 + pct * 0.78,
                    )

    if progress_callback:
        progress_callback("✅  Tải video thành công!", 1.0)

    return os.path.abspath(out_path)


# Platforms to use Playwright downloader instead of yt-dlp
_PLAYWRIGHT_PLATFORMS = [
    "douyin.com", "iesdouyin.com", "v.douyin.com",
    "kuaishou.com", "gifshow.com",
    "xiaohongshu.com", "xhslink.com",
]


def download_video(
    url: str,
    output_dir: str,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> str:
    """
    Download best-quality video to output_dir.
    Returns absolute path of the downloaded MP4.
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError(
            "Chưa cài yt-dlp.\nChạy lệnh:  pip install yt-dlp"
        )

    os.makedirs(output_dir, exist_ok=True)
    result_path: list[str] = []

    def _hook(d: dict):
        status = d.get("status")
        if status == "downloading":
            total   = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done    = d.get("downloaded_bytes", 0)
            speed   = d.get("speed") or 0
            spd_str = f"  {speed / 1_048_576:.1f} MB/s" if speed else ""

            if total > 0:
                pct = done / total
                done_mb  = done  / 1_048_576
                total_mb = total / 1_048_576
                msg = f"Đang tải{spd_str}  ({done_mb:.1f} / {total_mb:.1f} MB)"
            else:
                msg = f"Đang tải{spd_str}  ({done / 1_048_576:.1f} MB)"
                pct = 0.35

            if progress_callback:
                progress_callback(msg, pct * 0.88)

        elif status == "finished":
            result_path.append(d.get("filename", ""))
            if progress_callback:
                progress_callback("Đang ghép / chuyển đổi...", 0.92)

    # Use Playwright for platforms with broken yt-dlp extractors
    use_playwright = any(d in url.lower() for d in _PLAYWRIGHT_PLATFORMS)
    if use_playwright:
        return _playwright_download(url, output_dir, progress_callback)

    ydl_opts = {
        "outtmpl":             os.path.join(output_dir, "%(title).80s.%(ext)s"),
        "format":              "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "progress_hooks":      [_hook],
        "noplaylist":          True,
        "quiet":               True,
        "no_warnings":         True,
        "retries":             5,
        "extractor_args":      {"douyin": {"embed_metadata": False}},
    }

    # Use saved cookies.txt if available (most reliable method)
    cookies_file = _find_saved_cookies()
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
        if progress_callback:
            progress_callback("Đang dùng cookies đã lưu...", 0.01)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info     = ydl.extract_info(url, download=True)
            prepared = ydl.prepare_filename(info)
        except Exception as e:
            err_str = str(e)
            # Give helpful error for platforms that need cookies
            if "cookies" in err_str.lower() or "login" in err_str.lower():
                raise RuntimeError(
                    "Video này cần cookies để tải.\n\n"
                    "Cách lấy cookies:\n"
                    "1. Cài extension 'Get cookies.txt LOCALLY' trên Chrome\n"
                    "2. Vào douyin.com (không cần đăng nhập)\n"
                    "3. Nhấn extension → Export → lưu file cookies.txt\n"
                    "4. Trong app nhấn '🍪 Import Cookies' và chọn file đó\n\n"
                    f"Lỗi gốc: {err_str[:100]}"
                ) from e
            raise

    # Prefer what the hook reported; fall back to prepared name
    final = result_path[0] if result_path else prepared

    # yt-dlp might write .webm even with merge_output_format=mp4 on some builds
    if not os.path.exists(final):
        mp4_alt = os.path.splitext(final)[0] + ".mp4"
        if os.path.exists(mp4_alt):
            final = mp4_alt

    if progress_callback:
        progress_callback("✅  Tải video thành công!", 1.0)

    return os.path.abspath(final)
