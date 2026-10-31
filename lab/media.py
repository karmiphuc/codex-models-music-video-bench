"""Shared audio preparation and mechanical video checks; no model calls."""
from contextlib import ExitStack
import json
import math
from pathlib import Path
import subprocess
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw


def call(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def probe(path):
    return json.loads(call(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                            "-of", "json", str(path)]))


def demo_audio(path, duration=12, bpm=100):
    """Original synthetic fixture, separate from user-supplied music."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 22050
    t = np.arange(round(duration * rate)) / rate
    pulse = np.mod(t, 60 / bpm)
    rng = np.random.default_rng(41)
    kick = np.sin(2 * np.pi * (55 * pulse + 3 * (1 - np.exp(-25 * pulse)))) * np.exp(-16 * pulse)
    hat = rng.normal(0, 1, len(t)) * np.exp(-100 * np.mod(t, 30 / bpm))
    bass = np.sin(2 * np.pi * 55 * t) * (0.6 + 0.4 * np.cos(2 * np.pi * bpm / 60 * t))
    sound = (0.4 * kick + 0.04 * hat + 0.14 * bass)
    fade = np.minimum(1, np.minimum(t / 0.05, (duration - t) / 0.2))
    pcm = np.clip(sound * fade * 32767, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())


def prepare_audio(source, target, start, duration=None, bpm=None, cues=None, demo=False,
                  title=None, artist=None):
    source, target = Path(source).resolve(), Path(target)
    if not source.is_file():
        raise ValueError(f"Audio missing: {source}. Supply an audio file for your chosen song.")
    source_duration = float(probe(source)["format"]["duration"])
    if duration is None:
        duration = source_duration - start
    if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0 or start + duration > source_duration + 0.02:
        raise ValueError(f"Excerpt {start:g}–{start + duration:g}s exceeds source duration {source_duration:g}s.")
    if bpm is not None and (not math.isfinite(bpm) or bpm <= 0):
        raise ValueError("BPM must be a positive finite number.")
    cue_data = json.loads(Path(cues).read_text()) if cues else {"sections": [], "lyrics": []}
    target.mkdir(parents=True, exist_ok=False)
    call(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(source),
          "-t", str(duration), "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le",
          str(target / "audio.wav")])
    with wave.open(str(target / "audio.wav"), "rb") as stream:
        rate = stream.getframerate()
        data = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(float) / 32768
    hop, window = 2205, 4410
    energy = np.array([np.sqrt(np.mean(data[i:i + window] ** 2))
                       for i in range(0, len(data), hop)])
    peak = float(energy.max()) or 1
    actual_duration = len(data) / rate
    # Deliberately simple, transparent candidates, not a transcription or beat tracker.
    flux = np.maximum(0, np.diff(energy, prepend=energy[0]))
    threshold = float(np.percentile(flux, 80))
    accents, last = [], -1.0
    for i in range(1, len(flux) - 1):
        t = i * hop / rate
        if flux[i] > threshold and flux[i] >= flux[i-1] and flux[i] >= flux[i+1] and t-last >= 0.25:
            accents.append(round(t, 3))
            last = t
    summary = {
        "track": "Synthetic test fixture" if demo else (title or source.stem),
        "artist": "Generated locally" if demo else artist,
        "is_demo": demo, "source_start_seconds": start,
        "duration_seconds": actual_duration, "bpm": bpm,
        "beat_grid_seconds": [round(float(t), 4) for t in np.arange(0, actual_duration, 60 / bpm)] if bpm else [],
        "beat_grid_note": "User BPM, anchored at excerpt zero; verify downbeat offset." if bpm else "Unavailable; supply --bpm after verifying tempo.",
        "accent_candidates_seconds": accents,
        "energy": [{"time": round(i * hop / rate, 3), "value": round(float(e / peak), 4)}
                   for i, e in enumerate(energy)],
        "sections": cue_data.get("sections", []), "lyrics": cue_data.get("lyrics", []),
        "analysis_limits": "Energy and amplitude-rise candidates only. Lyrics, instruments, mood, downbeats and narrative are not inferred. Supplied cue times must be relative to this excerpt.",
    }
    (target / "audio-map.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def _audio_comparison(video, source_audio, duration_seconds, tolerance):
    """Compare decoded PCM at offset zero, without a search that could hide drift."""
    rate = 22050
    result = {"passed": False, "sample_rate": rate, "comparison_offset_samples": 0,
              "limits": {"minimum_correlation": 0.98, "maximum_relative_rms_error": 0.20,
                         "minimum_rms_ratio": 0.90, "maximum_rms_ratio": 1.10},
              "limitations": "AAC-tolerant comparison at zero offset, without lag or gain fitting. "
                             "Cannot distinguish changes below these tolerances or prove perceptual sync."}
    source_audio = Path(source_audio)
    if not source_audio.is_file():
        result["error"] = "Expected source audio is missing"
        return result
    try:
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as mappings:
            decoded = []
            for index, audio_path in enumerate([source_audio, video]):
                destination = Path(temporary) / f"audio-{index}.f32"
                call(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(audio_path),
                      "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(rate),
                      "-c:a", "pcm_f32le", "-f", "f32le", str(destination)])
                if destination.stat().st_size == 0:
                    raise ValueError("Decoded audio contains no samples")
                mapping = np.memmap(destination, mode="r", dtype="<f4")
                mappings.callback(mapping._mmap.close)
                decoded.append(mapping)
            reference, actual = decoded
            count = min(len(reference), len(actual))
            sum_reference = sum_actual = power_reference = power_actual = cross_power = 0.0
            # Bound working memory even for a long supplied track.
            for start in range(0, count, 262144):
                left = np.asarray(reference[start:start + 262144], dtype=np.float64)
                right = np.asarray(actual[start:start + 262144], dtype=np.float64)
                # Only compare common samples; AAC can pad a short final packet.
                length = min(len(left), len(right), count - start)
                left, right = left[:length], right[:length]
                sum_reference += float(left.sum())
                sum_actual += float(right.sum())
                power_reference += float(np.dot(left, left))
                power_actual += float(np.dot(right, right))
                cross_power += float(np.dot(left, right))
            reference_variance = max(0.0, power_reference - sum_reference ** 2 / count)
            actual_variance = max(0.0, power_actual - sum_actual ** 2 / count)
            denominator = math.sqrt(reference_variance * actual_variance)
            correlation = ((cross_power - sum_reference * sum_actual / count) / denominator
                           if denominator > 0 else 0.0)
            source_rms = math.sqrt(power_reference / count)
            output_rms = math.sqrt(power_actual / count)
            relative_error = (math.sqrt(max(0.0, power_reference + power_actual - 2 * cross_power) /
                                        power_reference) if power_reference > 0 else None)
            rms_ratio = output_rms / source_rms if source_rms > 0 else None
            sample_tolerance = math.ceil(tolerance * rate)
            checks = {
                "source_duration": abs(len(reference) - duration_seconds * rate) <= sample_tolerance,
                "sample_count": abs(len(reference) - len(actual)) <= sample_tolerance,
                "non_silent": source_rms > 1e-5 and output_rms > 1e-5 and
                              reference_variance / count > 1e-10 and actual_variance / count > 1e-10,
                "zero_offset_correlation": math.isfinite(correlation) and correlation >= 0.98,
                "relative_rms_error": relative_error is not None and math.isfinite(relative_error) and relative_error <= 0.20,
                "rms_ratio": rms_ratio is not None and math.isfinite(rms_ratio) and 0.90 <= rms_ratio <= 1.10,
            }
            result.update(passed=all(checks.values()), checks=checks,
                          source_samples=len(reference), output_samples=len(actual), compared_samples=count,
                          correlation=correlation, relative_rms_error=relative_error,
                          source_rms=source_rms, output_rms=output_rms, rms_ratio=rms_ratio)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        result["error"] = (error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error))[:1000]
    return result


def validate_video(path, spec, source_audio=None):
    path = Path(path)
    try:
        info = probe(path)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return {"passed": False, "checks": {"readable_video": False}}
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    try:
        duration = float((video or {}).get("duration", info["format"].get("duration", 0)))
        numerator, denominator = (video or {}).get("avg_frame_rate", "0/1").split("/")
        fps = float(numerator) / (float(denominator) or 1)
        audio_duration = float((audio or {}).get("duration", 0))
        video_start = float((video or {}).get("start_time", "nan"))
        audio_start = float((audio or {}).get("start_time", "nan"))
    except (TypeError, ValueError, KeyError):
        return {"passed": False, "checks": {"readable_metadata": False}}
    tolerance = max(0.15, 2 / spec["fps"])
    checks = {
        "video_stream": video is not None, "audio_stream": audio is not None,
        "duration": abs(duration - spec["duration_seconds"]) <= tolerance,
        "resolution": bool(video and (video["width"], video["height"]) == (spec["width"], spec["height"])),
        "fps": abs(fps - spec["fps"]) < 0.01,
        "h264": bool(video and video.get("codec_name") == "h264"),
        "aac": bool(audio and audio.get("codec_name") == "aac"),
        "audio_duration": bool(audio and abs(audio_duration - spec["duration_seconds"]) <= tolerance),
        "yuv420p": bool(video and video.get("pix_fmt") == "yuv420p"),
        # PCM extraction alone can discard a mux-only timestamp delay.
        "stream_start_alignment": math.isfinite(video_start) and math.isfinite(audio_start) and
                                  abs(video_start) <= 0.005 and abs(audio_start) <= 0.005 and
                                  abs(video_start - audio_start) <= 0.005,
    }
    decode_error = None
    try:
        call(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
              "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"])
        checks["full_decode"] = True
    except (OSError, subprocess.CalledProcessError) as error:
        checks["full_decode"] = False
        decode_error = (error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error))[:1000]
    audio_result = _audio_comparison(path, source_audio if source_audio is not None else path.parent.parent / "audio.wav",
                                     spec["duration_seconds"], tolerance)
    checks["soundtrack_matches_at_zero_offset"] = audio_result["passed"]
    return {"passed": all(checks.values()), "checks": checks,
            "duration_seconds": duration, "fps": fps,
            "stream_start_times": {"video_seconds": video_start if math.isfinite(video_start) else None,
                                   "audio_seconds": audio_start if math.isfinite(audio_start) else None,
                                   "tolerance_seconds": 0.005},
            "audio_comparison": audio_result, "decode_error": decode_error,
            "limitations": "Metadata, full decode health and AAC-tolerant source audio comparison at zero offset. "
                           "Does not certify perceptual sync, visual quality or flash safety; audio changes below "
                           "the reported tolerances can pass."}


def contact_sheet(video, output, count=12):
    import tempfile
    duration = float(probe(video)["format"]["duration"])
    tiles = []
    with tempfile.TemporaryDirectory() as temp:
        for i in range(count):
            t = duration * (i + 0.5) / count
            frame = Path(temp) / f"{i}.png"
            call(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video),
                  "-frames:v", "1", "-vf", "scale=320:180", str(frame)])
            tile = Image.new("RGB", (320, 204), "#10141d")
            with Image.open(frame) as img:
                tile.paste(img.convert("RGB"), (0, 0))
            ImageDraw.Draw(tile).text((8, 185), f"{t:.2f}s", fill="white")
            tiles.append(tile)
    sheet = Image.new("RGB", (1280, math.ceil(count / 4) * 204), "#10141d")
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % 4) * 320, (i // 4) * 204))
    sheet.save(output)
