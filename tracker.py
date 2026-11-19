import os
import math
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

HERE = Path(__file__).resolve().parent
MODELS_DIR = HERE / "models"
YOLOX_MODEL = MODELS_DIR / "person_yolox_s_2022nov.onnx"
YUNET_MODEL = MODELS_DIR / "face_detection_yunet_2023mar.onnx"

_YOLOX_SESSION = None
_GRID = None


def _get_yolox_session():
    global _YOLOX_SESSION
    if _YOLOX_SESSION is None:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        _YOLOX_SESSION = ort.InferenceSession(str(YOLOX_MODEL), opts, providers=["CPUExecutionProvider"])
    return _YOLOX_SESSION


def _generate_grids():
    rows = []
    for stride in (8, 16, 32):
        n = 640 // stride
        ys, xs = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        rows.append(np.stack([xs.ravel(), ys.ravel(), np.full(n * n, stride)], axis=1))
    return np.concatenate(rows).astype(np.float32)


def detect_people(frame, conf: float = 0.35) -> List[Tuple[float, float, float, float, float]]:
    """Detects person bounding boxes [x, y, w, h, score] using YOLOX-S."""
    import cv2
    global _GRID
    if _GRID is None:
        _GRID = _generate_grids()

    h, w = frame.shape[:2]
    r = min(640 / w, 640 / h)
    img = np.full((640, 640, 3), 114, dtype=np.uint8)
    rw, rh = round(w * r), round(h * r)
    img[:rh, :rw] = cv2.resize(frame, (rw, rh))

    blob = img.transpose(2, 0, 1)[None].astype(np.float32)
    session = _get_yolox_session()
    out = session.run(None, {"images": blob})[0][0]

    xy = (out[:, :2] + _GRID[:, :2]) * _GRID[:, 2:3]
    wh = np.exp(out[:, 2:4]) * _GRID[:, 2:3]
    score = out[:, 4] * out[:, 5]

    keep = score > conf
    if not keep.any():
        return []

    xy, wh, score = xy[keep] / r, wh[keep] / r, score[keep]
    boxes = [[float(x - bw / 2), float(y - bh / 2), float(bw), float(bh)] for (x, y), (bw, bh) in zip(xy, wh)]
    idx = cv2.dnn.NMSBoxes(boxes, score.tolist(), conf, 0.45)
    if len(idx) == 0:
        return []
    return [(*boxes[i], float(score[i])) for i in np.array(idx).ravel()]


def pick_player(people: List[Any], frame_w: int, frame_h: int, prev_x: Optional[float] = None) -> Optional[float]:
    """Identifies player character: large person in lower-middle with minimum cost."""
    best, best_cost = None, None
    for x, y, w, h, s in people:
        if h < frame_h * 0.12:  # Ignore distant background NPCs
            continue
        cx = (x + w / 2) / frame_w
        cy = (y + h / 2) / frame_h
        if cx < 0.10 or cx > 0.90:  # Far edges rarely player
            continue
        cost = abs(cx - 0.48) * 1.2 + abs(cy - 0.62) * 0.6 - (h / frame_h) * 1.5
        if prev_x is not None:
            cost += abs(cx - prev_x) * 1.5
        if best_cost is None or cost < best_cost:
            best, best_cost = cx, cost
    return best


def smooth_path(times: List[float], xs: List[Optional[float]], default: float = 0.5, max_speed: float = 0.15) -> List[float]:
    """Applies median filter + speed-limited easing to prevent camera jitter."""
    filled, last = [], None
    for x in xs:
        if x is None:
            x = last
        filled.append(x)
        if x is not None:
            last = x
    first = next((x for x in filled if x is not None), default)
    filled = [first if x is None else x for x in filled]

    med = [float(np.median(filled[max(0, i - 1):i + 2])) for i in range(len(filled))]
    out = [med[0]]
    for i in range(1, len(med)):
        dt = max(1e-3, times[i] - times[i - 1])
        step = max(-max_speed * dt, min(max_speed * dt, med[i] - out[-1]))
        out.append(out[-1] + step)
    return out


def track_player(video_path: str, fps: float = 1.0) -> Optional[List[Tuple[float, float]]]:
    """
    Samples video at 1 fps, detects player character with YOLOX-S,
    and returns smoothed keyframes [(t_sec, x_center_fraction)].
    Returns None if no player found or portrait source.
    """
    if not YOLOX_MODEL.exists():
        return None

    import cv2
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if fw <= 0 or fh <= 0 or fw / fh < 1.2:
        cap.release()
        return None

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    every = max(1, round(src_fps / fps))
    times, xs, prev = [], [], None
    frame_idx = 0

    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            if frame_idx % every == 0:
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    break
                x = pick_player(detect_people(frame), fw, fh, prev)
                if x is not None:
                    prev = x
                times.append(frame_idx / src_fps)
                xs.append(x)
            frame_idx += 1
    finally:
        cap.release()

    valid_count = sum(x is not None for x in xs)
    if valid_count < max(2, len(xs) // 5):
        return None

    smoothed = smooth_path(times, xs)
    return list(zip(times, smoothed))


def generate_panning_crop_expr(keys: List[Tuple[float, float]], out_w: int = 1080) -> str:
    """
    Builds piecewise-linear FFmpeg expression for crop x coordinate.
    Input stream is expected to be scaled to 1920 height.
    """
    if not keys:
        return f"(in_w-{out_w})/2"

    def at_x(x_val: float) -> str:
        return f"(in_w*{x_val:.4f}-{out_w // 2})"

    expr = at_x(keys[-1][1])
    for (t0, x0), (t1, x1) in reversed(list(zip(keys, keys[1:]))):
        if t1 <= t0:
            continue
        seg = f"({at_x(x0)}+({at_x(x1)}-{at_x(x0)})*(t-{t0:.2f})/{t1 - t0:.2f})"
        expr = f"if(lt(t\\,{t1:.2f})\\,{seg}\\,{expr})"

    return f"max(0\\,min(in_w-{out_w}\\,{expr}))"


def detect_facecam(video_path: str, sample_count: int = 10) -> Optional[Dict[str, Any]]:
    """
    Detects streamer facecam overlays using OpenCV YuNet.
    Analyzes corner quadrants (TL, TR, BL, BR) for persistent faces across video.
    Uses fast sequential grabbing to avoid slow seek operations.
    """
    if not YUNET_MODEL.exists():
        return None

    import cv2
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if total_frames <= 0 or fw <= 0 or fh <= 0:
        cap.release()
        return None

    every = max(1, total_frames // max(1, sample_count))
    detector = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (320, 320), 0.75, 0.3, 5000)

    corner_hits = {"top-left": 0, "top-right": 0, "bottom-left": 0, "bottom-right": 0}
    sampled = 0
    frame_idx = 0

    try:
        while sampled < sample_count:
            ok = cap.grab()
            if not ok:
                break
            if frame_idx % every == 0:
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    break
                sampled += 1

                # Resize small for lightning fast face detection
                h, w = frame.shape[:2]
                r = 320.0 / max(w, h)
                small_w, small_h = int(w * r), int(h * r)
                small_frame = cv2.resize(frame, (small_w, small_h))

                detector.setInputSize((small_w, small_h))
                _, faces = detector.detect(small_frame)
                if faces is not None:
                    for face in faces:
                        fx, fy, fw_box, fh_box = face[:4]
                        fcx, fcy = (fx + fw_box / 2) / small_w, (fy + fh_box / 2) / small_h
                        if fcx < 0.35 and fcy < 0.45:
                            corner_hits["top-left"] += 1
                        elif fcx > 0.65 and fcy < 0.45:
                            corner_hits["top-right"] += 1
                        elif fcx < 0.35 and fcy > 0.55:
                            corner_hits["bottom-left"] += 1
                        elif fcx > 0.65 and fcy > 0.55:
                            corner_hits["bottom-right"] += 1
            frame_idx += 1
    finally:
        cap.release()

    threshold = max(3, int(sampled * 0.35))
    for pos, hits in corner_hits.items():
        if hits >= threshold:
            return {"position": pos, "confidence": hits / max(1, sampled)}

    return None
