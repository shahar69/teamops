import os
import uuid
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import pyttsx3
import shutil

MEDIA_DIR = Path(os.environ.get('MEDIA_DIR', '/tmp/teamops_media'))
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
BGS_DIR = MEDIA_DIR / 'backgrounds'
BGS_DIR.mkdir(parents=True, exist_ok=True)


def _select_voice(engine, voice_spec: str | None):
    if not voice_spec:
        return
    try:
        voices = engine.getProperty('voices') or []
        vlow = voice_spec.lower()
        for v in voices:
            name = getattr(v, 'name', '') or ''
            lang = ''.join(getattr(v, 'languages', []) or [])
            if vlow in name.lower() or vlow in str(lang).lower():
                engine.setProperty('voice', v.id)
                return
    except Exception:
        return


def _tts_to_wav(text: str, out_path: Path, *, rate: int = 160, voice: str | None = None) -> None:
    """Generate narration WAV.

    Primary: pyttsx3 offline TTS. Fallback: generate silent audio via ffmpeg if TTS fails.
    """
    try:
        engine = pyttsx3.init()
        if rate:
            try:
                engine.setProperty('rate', int(rate))
            except Exception:
                engine.setProperty('rate', 160)
        _select_voice(engine, voice)
        engine.save_to_file(text, str(out_path))
        engine.runAndWait()
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError('pyttsx3 produced no audio')
        return
    except Exception:
        # Try espeak-ng / espeak CLI as a secondary offline TTS
        try:
            speak = shutil.which('espeak-ng') or shutil.which('espeak')
            if speak:
                # Build CLI: espeak-ng -s RATE -w out.wav TEXT
                # Voice selection via -v if provided (best-effort)
                cmd = [speak, '-s', str(int(rate) if rate else 160), '-w', str(out_path)]
                if voice:
                    cmd.extend(['-v', str(voice)])
                # Pass text as the last argument
                cmd.append(str(text))
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                if not out_path.exists() or out_path.stat().st_size == 0:
                    raise RuntimeError('espeak produced no audio')
                return
        except Exception:
            pass
        # Fallback to short silence if no TTS engine available
        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
            '-t', '8',
            str(out_path)
        ]
        try:
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f'Fallback audio generation failed: {e.output.decode()}')


def _make_title_frame(text: str, out_path: Path, size=(720, 1280)) -> None:
    # Simple title frame using Pillow (Pillow 10+: use textbbox instead of deprecated textsize)
    img = Image.new('RGB', size, color=(24, 24, 24))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('DejaVuSans-Bold.ttf', 56)
    except Exception:
        font = ImageFont.load_default()

    # Word-wrap text to fit width with padding
    padding = 60
    max_width = size[0] - padding * 2

    def _bbox(draw_ctx: ImageDraw.ImageDraw, s: str):
        if hasattr(draw_ctx, 'textbbox'):
            return draw_ctx.textbbox((0, 0), s, font=font)
        # Fallback for very old Pillow
        if hasattr(draw_ctx, 'textsize'):
            w, h = draw_ctx.textsize(s, font=font)
            return (0, 0, w, h)
        # Last resort: approximate via font mask
        try:
            mask = font.getmask(s)
            return (0, 0, mask.size[0], mask.size[1])
        except Exception:
            return (0, 0, min(len(s) * 10, max_width), 20)

    def wrap_line(t: str):
        words = (t or '').split()
        lines = []
        cur = ''
        for w in words:
            cand = (cur + ' ' + w).strip()
            bbox = _bbox(draw, cand)
            width = bbox[2] - bbox[0]
            if width <= max_width or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if not lines:
            lines = [t]
        return lines

    lines = []
    for part in (text or '').split('\n'):
        lines.extend(wrap_line(part))

    # Measure line height and total block height
    ascent_bbox = _bbox(draw, 'Ag')
    line_h = (ascent_bbox[3] - ascent_bbox[1]) + 6
    total_h = len(lines) * line_h
    y = max((size[1] - total_h) // 2, padding)

    for line in lines:
        bbox = _bbox(draw, line)
        w = bbox[2] - bbox[0]
        x = max((size[0] - w) // 2, padding)
        draw.text((x, y), line, font=font, fill=(255, 255, 255))
        y += line_h

    img.save(out_path)

def list_backgrounds() -> list:
    """Return a list of available background video filenames in the backgrounds directory."""
    items = []
    for p in sorted(BGS_DIR.glob('*')):
        if p.is_file() and p.suffix.lower() in {'.mp4', '.mov', '.mkv', '.webm'}:
            items.append(p.name)
    return items


def _gen_bg_video(filename: str, lavfi: str, seconds: int = 30) -> Path:
    out = BGS_DIR / filename
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-t', str(int(seconds)),
        '-i', lavfi,
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-r', '30',
        str(out)
    ]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return out
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f'ffmpeg background gen failed: {e.output.decode()}')


def seed_backgrounds() -> dict:
    """Generate a set of dynamic vertical background videos using ffmpeg filters.

    Attempts multiple styles; if a style fails due to missing filter, falls back to a noise-based style.
    Returns a dict with generated filenames.
    """
    results = []
    recipes = [
        # Vibrant bars with hue shift
        (
            'minecraft_parkour_style.mp4',
            "testsrc2=size=720x1280:rate=30,hue=h='t*60':s=2,format=yuv420p"
        ),
        # Colorful blurred noise
        (
            'subway_surfers_style.mp4',
            "noise=s=720x1280:allf=1:all_seed=7,boxblur=2:1,eq=saturation=2.2:contrast=1.1,format=yuv420p"
        ),
        # Soft blurred pattern
        (
            'driving_dashcam_style.mp4',
            "testsrc2=size=720x1280:rate=30,boxblur=1:1,format=yuv420p"
        ),
    ]
    for name, lavfi in recipes:
        try:
            p = _gen_bg_video(name, lavfi)
            results.append(p.name)
        except Exception:
            # Fallback recipe using noise if specific filter not available
            try:
                p = _gen_bg_video(name, "noise=s=720x1280:allf=1:all_seed=23,boxblur=2:1,eq=saturation=2.0:contrast=1.05")
                results.append(p.name)
            except Exception as e2:
                # Skip if even fallback fails
                pass
    return {"generated": results}


def _ffprobe_duration(path: Path) -> float:
    try:
        out = subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(path)
        ], stderr=subprocess.STDOUT).decode().strip()
        return float(out)
    except Exception:
        return 0.0


def _pad_audio_to_duration(in_wav: Path, out_wav: Path, target_seconds: float) -> Path:
    """Pad input audio with silence to at least target_seconds.

    If input is already longer than target, just copy.
    """
    try:
        dur = _ffprobe_duration(in_wav)
        if dur >= (target_seconds - 0.05):
            # no need to pad; copy
            if in_wav != out_wav:
                subprocess.check_output(['ffmpeg', '-y', '-i', str(in_wav), str(out_wav)], stderr=subprocess.STDOUT)
            return out_wav
        pad = max(0.0, target_seconds - dur)
        # create silence of length 'pad' and concat
        sil = out_wav.parent / 'silence.wav'
        cmd_sil = [
            'ffmpeg', '-y',
            '-f', 'lavfi', '-i', f'anullsrc=channel_layout=stereo:sample_rate=44100',
            '-t', f'{pad:.3f}', str(sil)
        ]
        subprocess.check_output(cmd_sil, stderr=subprocess.STDOUT)
        cmd_cat = [
            'ffmpeg', '-y',
            '-i', str(in_wav), '-i', str(sil),
            '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1[out]',
            '-map', '[out]', str(out_wav)
        ]
        subprocess.check_output(cmd_cat, stderr=subprocess.STDOUT)
        return out_wav
    except subprocess.CalledProcessError as e:
        # fall back to copying input
        try:
            if in_wav != out_wav:
                subprocess.check_output(['ffmpeg', '-y', '-i', str(in_wav), str(out_wav)], stderr=subprocess.STDOUT)
        except Exception:
            pass
        return out_wav


def _gen_background_music(out_wav: Path, duration: float, volume: float = 0.15) -> Path:
    """Generate a simple background music/ambience track using ffmpeg lavfi.

    Uses pink noise shaped with lowpass/highpass and a light echo for texture.
    """
    try:
        # Generate a base pink noise and shape it; keep stereo 44.1k
        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi', '-t', f'{duration:.3f}',
            '-i', 'anoisesrc=color=pink:sample_rate=44100:amplitude=0.25',
            '-af', f'lowpass=f=2000,highpass=f=100,volume={volume:.3f},aecho=0.8:0.88:60:0.4',
            str(out_wav)
        ]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return out_wav
    except subprocess.CalledProcessError:
        # Fallback: simple sine tone softly
        try:
            cmd2 = [
                'ffmpeg', '-y',
                '-f', 'lavfi', '-t', f'{duration:.3f}',
                '-i', 'sine=frequency=220:sample_rate=44100:beep_factor=8',
                '-af', f'volume={volume:.3f}', str(out_wav)
            ]
            subprocess.check_output(cmd2, stderr=subprocess.STDOUT)
            return out_wav
        except Exception:
            # Last fallback: silence
            subprocess.check_output([
                'ffmpeg', '-y', '-f', 'lavfi', '-t', f'{duration:.3f}',
                '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100', str(out_wav)
            ], stderr=subprocess.STDOUT)
            return out_wav


def _mix_with_ducking(voice_wav: Path, music_wav: Path, out_wav: Path, *, music_volume: float = 0.15, use_ducking: bool = True) -> Path:
    """Mix narration (voice) with background music, optionally ducking music when narration present.

    Returns path to mixed WAV.
    """
    try:
        if use_ducking:
            # Compress music with voice as sidechain, then mix
            filter_complex = (
                f"[0:a][1:a]sidechaincompress=threshold=0.030:ratio=8:attack=5:release=250:makeup=4[mduck];"
                f"[mduck]volume={music_volume:.3f}[m];"
                f"[m][1:a]amix=inputs=2:duration=longest:dropout_transition=2[aout]"
            )
            cmd = [
                'ffmpeg', '-y',
                '-i', str(music_wav), '-i', str(voice_wav),
                '-filter_complex', filter_complex,
                '-map', '[aout]', str(out_wav)
            ]
        else:
            # Simple amix with lower music volume
            filter_complex = (
                f"[0:a]volume={music_volume:.3f}[m];[m][1:a]amix=inputs=2:duration=longest:dropout_transition=2[aout]"
            )
            cmd = [
                'ffmpeg', '-y',
                '-i', str(music_wav), '-i', str(voice_wav),
                '-filter_complex', filter_complex,
                '-map', '[aout]', str(out_wav)
            ]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return out_wav
    except subprocess.CalledProcessError:
        # Fallback: just copy voice
        subprocess.check_output(['ffmpeg', '-y', '-i', str(voice_wav), str(out_wav)], stderr=subprocess.STDOUT)
        return out_wav


def _split_script(script: str) -> list:
    import re
    raw = re.split(r'[\n\r]+|(?<=[.!?])\s+', script or '')
    parts = [s.strip() for s in raw if s and s.strip()]
    if not parts:
        parts = [(script or '...').strip()]
    return parts


def _write_srt(segments: list, duration: float, out_path: Path) -> None:
    # Allocate times across duration (min 0.8s each)
    n = max(1, len(segments))
    min_seg = 0.8
    total_min = n * min_seg
    dur = max(duration, total_min)
    per = dur / n

    def fmt(t: float) -> str:
        if t < 0:
            t = 0
        ms = int(round((t - int(t)) * 1000))
        s = int(t) % 60
        m = (int(t) // 60) % 60
        h = int(t) // 3600
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with out_path.open('w', encoding='utf-8') as f:
        cur = 0.0
        for idx, line in enumerate(segments, start=1):
            start = cur
            end = min(start + per, dur)
            if end - start < min_seg:
                end = start + min_seg
            f.write(str(idx) + "\n")
            f.write(fmt(start) + " --> " + fmt(end) + "\n")
            f.write(line + "\n\n")
            cur = end


def tts_preview(text: str, *, rate: int | None = None, voice: str | None = None, seconds: float = 3.0) -> dict:
    """Generate a short MP3 preview for the given voice/rate.

    Uses the same offline TTS stack as generate_short. Returns dict with filename and path.
    """
    uid = uuid.uuid4().hex[:8]
    tmp_dir = MEDIA_DIR / f'tmp_prev_{uid}'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    wav_path = tmp_dir / 'prev.wav'
    out_name = f'voice_preview_{uid}.mp3'
    out_path = MEDIA_DIR / out_name
    # Limit text length for preview
    text = (text or 'This is a sample voice.').strip()
    if len(text) > 200:
        text = text[:200]
    try:
        _tts_to_wav(text, wav_path, rate=rate or 160, voice=voice)
        # Convert to MP3 for broad browser compatibility
        subprocess.check_output([
            'ffmpeg', '-y', '-i', str(wav_path), '-vn', '-c:a', 'libmp3lame', '-q:a', '5', str(out_path)
        ], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f'TTS preview failed: {e.output.decode()}')
    finally:
        try:
            for p in tmp_dir.iterdir(): p.unlink()
            tmp_dir.rmdir()
        except Exception:
            pass
    return {"filename": out_name, "path": str(out_path)}


def generate_short(title: str, script: str, *, background_name: str | None = None, subtitles: bool = True, draw_title: bool = True, tts_rate: int | None = None, tts_voice: str | None = None, min_duration_secs: int | None = None, music: bool = False, music_volume: float = 0.15, ducking: bool = True) -> dict:
    """Generate a vertical short: TTS narration with optional background video and burned subtitles.

    - If background_name is provided and exists in BGS_DIR, it will be used; otherwise a static title frame is used.
    - Subtitles are derived from the script and burned into the video if possible.
    Returns metadata dict with filename and path.
    """
    uid = uuid.uuid4().hex[:10]
    video_name = f'short_{uid}.mp4'
    video_path = MEDIA_DIR / video_name

    tmp_dir = MEDIA_DIR / f'tmp_{uid}'
    tmp_dir.mkdir(parents=True, exist_ok=True)

    title_png = tmp_dir / 'title.png'
    audio_wav = tmp_dir / 'audio.wav'
    audio_padded = tmp_dir / 'audio_padded.wav'
    audio_mix = tmp_dir / 'audio_mix.wav'
    srt_file = tmp_dir / 'subs.srt'

    _make_title_frame(title, title_png)
    _tts_to_wav(script, audio_wav, rate=tts_rate or 160, voice=tts_voice)

    # Ensure minimum duration by padding with silence if requested
    final_audio = audio_wav
    try:
        if min_duration_secs and min_duration_secs > 0:
            _pad_audio_to_duration(audio_wav, audio_padded, float(min_duration_secs))
            final_audio = audio_padded
    except Exception:
        final_audio = audio_wav

    # Optional background music with ducking
    if music:
        try:
            target_dur = _ffprobe_duration(final_audio) or 8.0
            music_wav = tmp_dir / 'music.wav'
            _gen_background_music(music_wav, target_dur, volume=music_volume)
            _mix_with_ducking(final_audio, music_wav, audio_mix, music_volume=music_volume, use_ducking=ducking)
            final_audio = audio_mix
        except Exception:
            # if music generation/mix fails, continue with narration-only
            final_audio = final_audio

    # Build SRT for subtitles
    if subtitles:
        segs = _split_script(script)
        dur = _ffprobe_duration(final_audio) or 8.0
        _write_srt(segs, dur, srt_file)

    # Choose background source
    bg_path = None
    if background_name:
        cand = (BGS_DIR / background_name)
        if cand.exists() and cand.is_file():
            bg_path = cand
        else:
            # substring match (case-insensitive)
            for p in BGS_DIR.glob('*'):
                if p.is_file() and p.suffix.lower() in {'.mp4', '.mov', '.mkv', '.webm'}:
                    if background_name.lower() in p.name.lower():
                        bg_path = p
                        break

    if bg_path is not None:
        # Use provided background video
        # Filter: scale/crop to vertical 720x1280; optionally burn subtitles; optionally draw title
        # Portable cover: scale so both dims >= target, then center-crop to 720x1280
        # if(a < 0.5625) height->1280 else width->720
        cover_vf = (
            "scale="
            "if(lt(a,0.5625),ceil(1280*a),720):"  # width
            "if(lt(a,0.5625),1280,ceil(720/a)),"   # height
            "crop=720:1280,format=yuv420p"
        )
        filter_parts = [cover_vf]
        if draw_title and (title or '').strip():
            # draw text at top; attempt DejaVuSans font
            fontfile = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            txt = (title or '').strip().replace(':', r'\:').replace("'", r"\\'")
            filter_parts.append(f"drawtext=fontfile='{fontfile}':text='{txt}':x=(w-text_w)/2:y=40:fontsize=36:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2")
        # Subtitles burn-in
        if subtitles and srt_file.exists():
            # Use absolute path for subtitles filter
            filter_parts.append(f"subtitles='{str(srt_file).replace('\\', '/').replace(':', r'\\:')}'")
        vf = ",".join(filter_parts)
        # Loop background if needed so it lasts until audio ends
        cmd = [
            'ffmpeg', '-y',
            '-stream_loop', '-1', '-i', str(bg_path),
            '-i', str(final_audio),
            '-c:v', 'libx264',
            '-vf', vf,
            '-c:a', 'aac', '-shortest', str(video_path)
        ]
    else:
        # Static title frame fallback
        # Duration dictated by audio via -shortest. Burn subtitles if possible over static.
        filter_parts = ["scale=720:1280,format=yuv420p"]
        if subtitles and srt_file.exists():
            filter_parts.append(f"subtitles='{str(srt_file).replace('\\', '/').replace(':', r'\\:')}'")
        vf = ",".join(filter_parts)
        cmd = [
            'ffmpeg', '-y',
            '-loop', '1', '-i', str(title_png),
            '-i', str(final_audio),
            '-c:v', 'libx264',
            '-vf', vf,
            '-c:a', 'aac', '-shortest', str(video_path)
        ]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        # If subtitles filter failed (e.g., libass missing), retry without subtitles
        if 'subtitles' in ' '.join(cmd):
            try:
                if ' -vf ' in ' '.join(cmd):
                    # rebuild without subtitles
                    if bg_path is not None:
                        vf2 = (
                            "scale="
                            "if(lt(a,0.5625),ceil(1280*a),720):"
                            "if(lt(a,0.5625),1280,ceil(720/a)),"
                            "crop=720:1280,format=yuv420p"
                        )
                        cmd2 = [
                            'ffmpeg', '-y',
                            '-stream_loop', '-1', '-i', str(bg_path),
                            '-i', str(final_audio),
                            '-c:v', 'libx264', '-vf', vf2,
                            '-c:a', 'aac', '-shortest', str(video_path)
                        ]
                    else:
                        vf2 = "scale=720:1280,format=yuv420p"
                        cmd2 = [
                            'ffmpeg', '-y',
                            '-loop', '1', '-i', str(title_png),
                            '-i', str(final_audio),
                            '-c:v', 'libx264', '-vf', vf2,
                            '-c:a', 'aac', '-shortest', str(video_path)
                        ]
                    subprocess.check_output(cmd2, stderr=subprocess.STDOUT)
                else:
                    raise
            except Exception as e2:
                raise RuntimeError(f'ffmpeg failed (with and without subtitles): {e.output.decode()} | fallback: {str(e2)}')
        else:
            raise RuntimeError(f'ffmpeg failed: {e.output.decode()}')

    # Cleanup tmp
    try:
        for p in tmp_dir.iterdir():
            p.unlink()
        tmp_dir.rmdir()
    except Exception:
        pass

    return {
        'filename': video_name,
        'path': str(video_path),
        'created_at': datetime.utcnow().isoformat() + 'Z'
    }
