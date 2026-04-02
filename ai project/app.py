"""
MoncifEdits AI — Flask Backend
Beat-synced cinematic video editing engine
"""

import os
import json
import uuid
import math
import random
import threading
import multiprocessing
import tempfile
import numpy as np
from flask import Flask, render_template, request, jsonify, send_file, url_for

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max upload

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "moncifedits_uploads")
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "moncifedits_output")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Job status tracking
jobs = {}


# ============================================================
#  PRESET DEFINITIONS
# ============================================================

PRESETS = {
    "velocity": {
        "name": "Velocity",
        "icon": "⚡",
        "desc": "Speed ramps synced to beats — slow on hits, fast transitions",
        "effects": ["velocity", "zoom"],
        "zoom_strength": 0.08,
        "shake_strength": 0,
        "flash_strength": 0,
        "slow_factor": 0.5,
        "fast_factor": 2.0,
        "use_cuts": False,
    },
    "hard_edit": {
        "name": "Hard Edit",
        "icon": "🔥",
        "desc": "Aggressive cuts + shake + zoom on every beat",
        "effects": ["cuts", "zoom", "shake", "flash"],
        "zoom_strength": 0.15,
        "shake_strength": 12,
        "flash_strength": 0.25,
        "slow_factor": 0.7,
        "fast_factor": 1.5,
        "use_cuts": True,
    },
    "funk_bounce": {
        "name": "Funk Bounce",
        "icon": "🎵",
        "desc": "Groove-synced zoom pulses + bass shake for funk beats",
        "effects": ["zoom", "shake", "flash"],
        "zoom_strength": 0.12,
        "shake_strength": 6,
        "flash_strength": 0.2,
        "slow_factor": 0.7,
        "fast_factor": 1.3,
        "use_cuts": False,
    },
    "smooth_flow": {
        "name": "Smooth Flow",
        "icon": "🌊",
        "desc": "Gentle zoom + subtle motion — clean and cinematic",
        "effects": ["zoom"],
        "zoom_strength": 0.06,
        "shake_strength": 0,
        "flash_strength": 0.1,
        "slow_factor": 0.8,
        "fast_factor": 1.2,
        "use_cuts": False,
    },
}


# ============================================================
#  BEAT DETECTION ENGINE
# ============================================================

def detect_beats(audio_path):
    import librosa
    y, sr = librosa.load(audio_path, sr=22050)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units='frames')
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units='frames')
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)
    rms = librosa.feature.rms(y=y)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)

    if hasattr(tempo, '__len__'):
        tempo = float(tempo[0]) if len(tempo) > 0 else 120.0
    else:
        tempo = float(tempo)

    return {
        'tempo': tempo,
        'beat_times': beat_times,
        'onset_times': onset_times,
        'rms': rms,
        'rms_times': rms_times,
        'duration': len(y) / sr
    }


# ============================================================
#  AI SUBJECT TRACKING ENGINE (YOLOv8)
# ============================================================

def extract_tracking_path(v_path, fps=10):
    try:
        from ultralytics import YOLO
        import cv2
    except ImportError:
        return None

    try:
        model = YOLO("yolov8n.pt")
    except Exception:
        return None

    cap = cv2.VideoCapture(v_path)
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    if not video_fps or video_fps <= 0: video_fps = 30.0
    
    frame_interval = max(1, int(video_fps / fps))
    tracking = []
    times = []
    
    frame_count = 0
    fallback_w, fallback_h = 0, 0
    
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        if frame_count == 0:
            fallback_h, fallback_w = frame.shape[:2]

        if frame_count % frame_interval == 0:
            # Predict
            results = model(frame, verbose=False)
            best_conf = 0.0
            best_center = None
            
            for box in results[0].boxes:
                conf = box.conf[0].item()
                cls_id = int(box.cls[0].item())
                # 0:person, 2:car, 3:motorcycle, 5:bus, 7:truck
                if cls_id in [0, 2, 3, 5, 7] and conf > best_conf: 
                    best_conf = conf
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    best_center = ((x1+x2)/2, (y1+y2)/2)
            
            if best_center:
                tracking.append(best_center)
            elif tracking:
                tracking.append(tracking[-1])
            else:
                tracking.append((fallback_w/2, fallback_h/2))
            times.append(frame_count / video_fps)
            
        frame_count += 1
    
    cap.release()
    
    if not tracking:
        return None
        
    tx = [p[0] for p in tracking]
    ty = [p[1] for p in tracking]
    
    # Smooth the camera path
    def smooth(arr, w=7):
        if len(arr) < w: return arr
        padded = np.pad(arr, (w//2, w-1-w//2), mode='edge')
        return np.convolve(padded, np.ones(w)/w, mode='valid').tolist()
        
    return {'times': times, 'tx': smooth(tx), 'ty': smooth(ty)}



# ============================================================
#  VIDEO EFFECTS ENGINE
# ============================================================

def get_intensity_at_time(t, beat_data, decay=0.15):
    if beat_data is None or len(beat_data['beat_times']) == 0:
        return 0
    diffs = np.abs(beat_data['beat_times'] - t)
    min_diff = np.min(diffs)
    return max(0, 1.0 - (min_diff / decay))


def apply_zoom_pulse(clip, beat_data, strength=0.12, tracking_path=None):
    def zoom_effect(get_frame, t):
        frame = get_frame(t)
        intensity = get_intensity_at_time(t, beat_data)
        scale = 1.0 + (intensity * strength)
        if scale <= 1.001:
            return frame
        h, w = frame.shape[:2]
        new_h, new_w = int(h * scale), int(w * scale)
        from PIL import Image
        img = Image.fromarray(frame)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        
        # Center of original frame
        cx, cy = w / 2, h / 2
        
        # Dynamic AI pan offset
        if tracking_path and len(tracking_path['times']) > 0:
            times = tracking_path['times']
            idx = np.searchsorted(times, t)
            if idx >= len(times): idx = len(times) - 1
            # Get smoothed target center and scale it
            cx_target, cy_target = tracking_path['tx'][idx], tracking_path['ty'][idx]
            cx = cx_target * scale
            cy = cy_target * scale

        # Ensure we don't go out of bounds
        left = int(max(0, min(cx - w / 2, new_w - w)))
        top = int(max(0, min(cy - h / 2, new_h - h)))
        
        img = img.crop((left, top, left + w, top + h))
        return np.array(img)
    return clip.fl(zoom_effect)


def apply_shake(clip, beat_data, strength=8):
    def shake_effect(get_frame, t):
        frame = get_frame(t)
        intensity = get_intensity_at_time(t, beat_data, decay=0.08)
        if intensity < 0.3:
            return frame
        nearest_idx = np.argmin(np.abs(beat_data['beat_times'] - t))
        seed_val = int(beat_data['beat_times'][nearest_idx] * 1000)
        rng = random.Random(seed_val + int(t * 100))
        dx = int(rng.randint(-strength, strength) * intensity)
        dy = int(rng.randint(-strength, strength) * intensity)
        h, w = frame.shape[:2]
        result = np.zeros_like(frame)
        src_x1, src_y1 = max(0, -dx), max(0, -dy)
        src_x2, src_y2 = min(w, w - dx), min(h, h - dy)
        dst_x1, dst_y1 = max(0, dx), max(0, dy)
        dst_x2, dst_y2 = min(w, w + dx), min(h, h + dy)
        cw = min(src_x2 - src_x1, dst_x2 - dst_x1)
        ch = min(src_y2 - src_y1, dst_y2 - dst_y1)
        if cw > 0 and ch > 0:
            result[dst_y1:dst_y1+ch, dst_x1:dst_x1+cw] = frame[src_y1:src_y1+ch, src_x1:src_x1+cw]
        return result
    return clip.fl(shake_effect)


def apply_brightness_flash(clip, beat_data, strength=0.3):
    def flash_effect(get_frame, t):
        frame = get_frame(t)
        intensity = get_intensity_at_time(t, beat_data, decay=0.1)
        if intensity < 0.2:
            return frame
        boost = 1.0 + (intensity * strength)
        return np.clip(frame.astype(np.float32) * boost, 0, 255).astype(np.uint8)
    return clip.fl(flash_effect)


def apply_velocity_ramp(clip, beat_data, video_duration, slow_factor=0.6, fast_factor=1.8):
    import moviepy.editor as mpe
    beat_times = beat_data['beat_times']
    if len(beat_times) < 2:
        return clip
    segments = []
    for i in range(len(beat_times) - 1):
        bt = beat_times[i]
        bt_next = beat_times[i + 1]
        gap = bt_next - bt
        if gap < 0.1:
            continue
        slow_end = bt + gap * 0.3
        if bt < video_duration and slow_end < video_duration:
            seg = clip.subclip(max(0, bt), min(slow_end, video_duration))
            segments.append(seg.fx(mpe.vfx.speedx, slow_factor))
        fast_start = slow_end
        if fast_start < video_duration and bt_next <= video_duration:
            seg = clip.subclip(fast_start, min(bt_next, video_duration))
            segments.append(seg.fx(mpe.vfx.speedx, fast_factor))
    if not segments:
        return clip
    try:
        return mpe.concatenate_videoclips(segments)
    except Exception:
        return clip


def apply_beat_cuts(clip, beat_data, video_duration):
    import moviepy.editor as mpe
    beat_times = beat_data['beat_times']
    if len(beat_times) < 3:
        return clip
    segment_sources = []
    for i in range(len(beat_times) - 1):
        dur = beat_times[i + 1] - beat_times[i]
        if dur < 0.05:
            continue
        segment_sources.append((beat_times[i], dur))
    if not segment_sources:
        return clip
    total = len(segment_sources)
    evens = list(range(0, total, 2))
    odds = list(range(1, total, 2))
    mixed = []
    for e, o in zip(evens, odds):
        mixed.extend([e, o])
    if len(evens) > len(odds):
        mixed.append(evens[-1])
    segments = []
    for idx in mixed:
        start, dur = segment_sources[idx]
        if start + dur <= video_duration:
            try:
                segments.append(clip.subclip(start, start + dur))
            except Exception:
                continue
    if not segments:
        return clip
    try:
        return mpe.concatenate_videoclips(segments)
    except Exception:
        return clip


# ============================================================
#  RENDER ENGINE (runs in background thread)
# ============================================================

def render_job(job_id, v_path, a_path, preset_key, intensity_mult, quality):
    try:
        import moviepy.editor as mpe
        
        jobs[job_id]['status'] = 'analyzing'
        jobs[job_id]['progress'] = 10
        beat_data = detect_beats(a_path)
        if beat_data is None:
            jobs[job_id]['status'] = 'error'
            jobs[job_id]['error'] = 'Beat detection failed'
            return

        jobs[job_id]['tempo'] = beat_data['tempo']
        jobs[job_id]['beats'] = len(beat_data['beat_times'])
        
        jobs[job_id]['step'] = 'AI Visual Subject Tracking...'
        jobs[job_id]['progress'] = 15
        tracking_path = extract_tracking_path(v_path)
        
        jobs[job_id]['status'] = 'processing'
        jobs[job_id]['progress'] = 20

        preset = PRESETS[preset_key]
        video = mpe.VideoFileClip(v_path)
        audio = mpe.AudioFileClip(a_path)

        if audio.duration > video.duration:
            audio = audio.subclip(0, video.duration)
        video_duration = video.duration

        edited = video
        effects = preset["effects"]
        step = 20
        step_inc = 50 // max(len(effects), 1)

        if preset.get("use_cuts") and "cuts" in effects:
            jobs[job_id]['step'] = 'Creating beat cuts...'
            edited = apply_beat_cuts(edited, beat_data, video_duration)
            step += step_inc
            jobs[job_id]['progress'] = step

        if "zoom" in effects:
            jobs[job_id]['step'] = 'Applying zoom pulses...'
            edited = apply_zoom_pulse(edited, beat_data, strength=preset["zoom_strength"] * intensity_mult, tracking_path=tracking_path)
            step += step_inc
            jobs[job_id]['progress'] = step

        if "shake" in effects and preset["shake_strength"] > 0:
            jobs[job_id]['step'] = 'Adding beat shake...'
            edited = apply_shake(edited, beat_data, strength=int(preset["shake_strength"] * intensity_mult))
            step += step_inc
            jobs[job_id]['progress'] = step

        if "flash" in effects and preset["flash_strength"] > 0:
            jobs[job_id]['step'] = 'Adding beat flash...'
            edited = apply_brightness_flash(edited, beat_data, strength=preset["flash_strength"] * intensity_mult)
            step += step_inc
            jobs[job_id]['progress'] = step

        if "velocity" in effects:
            jobs[job_id]['step'] = 'Applying velocity ramp...'
            edited = apply_velocity_ramp(edited, beat_data, video_duration,
                                         slow_factor=preset["slow_factor"],
                                         fast_factor=preset["fast_factor"])
            step += step_inc
            jobs[job_id]['progress'] = step

        jobs[job_id]['step'] = 'Syncing audio...'
        jobs[job_id]['progress'] = 75
        if audio.duration > edited.duration:
            audio = audio.subclip(0, edited.duration)
        elif audio.duration < edited.duration:
            edited = edited.subclip(0, audio.duration)
        edited = edited.set_audio(audio)

        fps_map = {"stable": 24, "hd": 30, "ultra": 30}
        bitrate_map = {"stable": "8000k", "hd": "20000k", "ultra": "50000k"}
        crf_map = {"stable": "23", "hd": "18", "ultra": "15"}

        out_name = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")
        cores = multiprocessing.cpu_count()

        jobs[job_id]['step'] = 'Rendering final edit...'
        jobs[job_id]['progress'] = 80
        edited.write_videofile(
            out_name,
            fps=fps_map.get(quality, 30),
            codec="libx264",
            audio_codec="aac",
            bitrate=bitrate_map.get(quality, "20000k"),
            threads=cores,
            preset="ultrafast",
            ffmpeg_params=["-pix_fmt", "yuv420p", "-crf", crf_map.get(quality, "18")]
        )

        video.close()
        audio.close()
        edited.close()

        jobs[job_id]['status'] = 'done'
        jobs[job_id]['progress'] = 100
        jobs[job_id]['output'] = out_name

    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['error'] = str(e)


# ============================================================
#  ROUTES
# ============================================================

@app.route('/')
def index():
    return render_template('index.html', presets=PRESETS)


@app.route('/render', methods=['POST'])
def start_render():
    video = request.files.get('video')
    audio = request.files.get('audio')
    preset = request.form.get('preset', 'funk_bounce')
    intensity = float(request.form.get('intensity', 1.0))
    quality = request.form.get('quality', 'hd')

    if not video or not audio:
        return jsonify({'error': 'Missing video or audio file'}), 400

    job_id = str(uuid.uuid4())[:8]
    v_path = os.path.join(UPLOAD_DIR, f"{job_id}_video.mp4")
    a_path = os.path.join(UPLOAD_DIR, f"{job_id}_audio.mp3")
    video.save(v_path)
    audio.save(a_path)

    jobs[job_id] = {
        'status': 'starting',
        'progress': 0,
        'step': 'Initializing...',
        'tempo': 0,
        'beats': 0,
        'error': None,
        'output': None
    }

    thread = threading.Thread(target=render_job, args=(job_id, v_path, a_path, preset, intensity, quality))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id})


@app.route('/status/<job_id>')
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)


@app.route('/download/<job_id>')
def download(job_id):
    job = jobs.get(job_id)
    if not job or job['status'] != 'done':
        return jsonify({'error': 'Not ready'}), 404
    return send_file(job['output'], as_attachment=True, download_name=f"MoncifEdit_{job_id}.mp4")


if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)