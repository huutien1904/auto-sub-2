import os, glob, subprocess, tempfile, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from subtitle_styles import build_ffmpeg_style, DEFAULT_STYLE

dl_dir = os.path.join(os.path.expanduser('~'), 'Downloads', 'VideoTranslatorVI')
videos = glob.glob(os.path.join(dl_dir, '*.mp4'))
if not videos:
    dl_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
    videos = glob.glob(os.path.join(dl_dir, '*.mp4'))

if not videos:
    print('Không tìm thấy video')
    sys.exit(1)

video = videos[0]
print('Video:', os.path.basename(video)[:60])

srt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp_preview.srt')
with open(srt_path, 'w', encoding='utf-8') as f:
    f.write('1\n00:00:02,000 --> 00:00:05,000\nnhu vay trong tam se don ve phia truoc\n')

style = build_ffmpeg_style(DEFAULT_STYLE, font_size=12)

# Escape Windows path for FFmpeg subtitles filter
srt_ffmpeg = srt_path.replace('\\', '/').replace('C:/', 'C\\:/')
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'subtitle_preview.jpg')

cmd = [
    'ffmpeg', '-y', '-ss', '2', '-i', video,
    '-vf', f"subtitles='{srt_ffmpeg}':force_style='{style}'",
    '-vframes', '1', '-update', '1',
    out
]

print('Running FFmpeg...')
r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
print('Return code:', r.returncode)

if r.returncode == 0 and os.path.exists(out):
    print('SUCCESS - Preview saved:', out)
    os.startfile(out)
else:
    # Try simpler version without subtitle filter to see if video opens
    print('STDERR (last 300):', r.stderr[-300:])

    # Fallback: open video directly in VLC to preview
    vlc = next((p for p in [
        r'C:\Program Files\VideoLAN\VLC\vlc.exe',
        r'C:\Program Files (x86)\VideoLAN\VLC\vlc.exe'
    ] if os.path.exists(p)), None)
    if vlc:
        print('Opening video in VLC for manual preview...')
        subprocess.Popen([vlc, video])

if os.path.exists(srt_path):
    os.remove(srt_path)
