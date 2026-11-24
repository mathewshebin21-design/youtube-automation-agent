"""Overlay / third-party text flagging (gate: overlays_third_parties_cleared).

Phase 2.7: review.py precheck scans the PRE-EDIT render (<stem>.preedit.mp4, before our captions/effects are
burned in) so our own captions do not raise false flags. If no pre-edit render exists but captions are burned,
the caption band (and progress bar) is masked with a flat fill before detection (mask_bands).

This only FLAGS. It never clears a clip: overlays_third_parties_cleared is a human check that is always
required. When this scan flags something, or cannot run, the sign-off needs a written note.

Two detectors (both run when available):
  ocr    - tesseract (if on PATH): words with confidence >= 60 and 3+ letters or digits. Only counts and boxes
           are stored, never the text (it may contain viewer usernames).
  edges  - OpenCV edge density: a grid cell that is both edge-dense (Canny) and static across sampled frames
           looks like a chat box, alert, name tag or HUD. Moving gameplay is dense but not static, and a
           blurred region is static but not dense, so neither is flagged.
"""
import csv
import io
import pathlib
import shutil
import subprocess
import tempfile

EDGE_MIN = 0.06      # share of edge pixels in a cell
STATIC_MAX = 8.0     # mean per-pixel temporal std (0-255) inside a cell
GRID = (6, 10)       # columns x rows on the 9:16 frame
OCR_MIN_CONF = 60
OCR_MIN_WORDS = 3


def _frames(video, samples=8):
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    out = []
    for i in range(samples):
        if n:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (i + 0.5) / samples))
        ok, frame = cap.read()
        if ok:
            out.append(frame)
    cap.release()
    return out


def edge_cells(frames):
    import cv2
    import numpy as np
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
    h, w = grays[0].shape
    edges = np.mean([cv2.Canny(g, 100, 200) > 0 for g in grays], axis=0)
    std = np.std(np.stack(grays).astype("float32"), axis=0)
    cols, rows = GRID
    cells = []
    for r in range(rows):
        for c in range(cols):
            y0, y1, x0, x1 = r * h // rows, (r + 1) * h // rows, c * w // cols, (c + 1) * w // cols
            dens, still = float(edges[y0:y1, x0:x1].mean()), float(std[y0:y1, x0:x1].mean())
            if dens >= EDGE_MIN and still <= STATIC_MAX:
                cells.append([round(c / cols, 3), round(r / rows, 3), round(1 / cols, 3), round(1 / rows, 3)])
    return cells


def ocr_words(frame, run=subprocess.run):
    """Returns [(x, y, w, h) normalized] for confident words in one frame, via the tesseract CLI."""
    import cv2
    h, w = frame.shape[:2]
    with tempfile.TemporaryDirectory() as d:
        png = pathlib.Path(d) / "f.png"
        cv2.imwrite(str(png), frame)
        p = run(["tesseract", str(png), "stdout", "--psm", "11", "tsv"], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("tesseract failed")
    boxes = []
    for row in csv.DictReader(io.StringIO(p.stdout), delimiter="\t"):
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            continue
        text = "".join(ch for ch in (row.get("text") or "") if ch.isalnum())
        if conf >= OCR_MIN_CONF and len(text) >= 3:
            boxes.append([round(int(row["left"]) / w, 3), round(int(row["top"]) / h, 3),
                          round(int(row["width"]) / w, 3), round(int(row["height"]) / h, 3)])
    return boxes


def mask(frames, bands):
    """Flat-fill horizontal bands [(y0, y1) fractions of the height]: no edges, no OCR text inside them."""
    for f in frames:
        h = f.shape[0]
        for y0, y1 in bands:
            f[int(h * y0):int(round(h * y1)), :] = 128
    return frames


def scan(video, file_sha256, samples=8, which=shutil.which, run=subprocess.run, mask_bands=None):
    result = {"file_sha256": file_sha256, "methods": [], "flagged": None, "regions": [], "frames": 0,
              "note": "flagging only; a human must still sign overlays_third_parties_cleared"}
    frames = _frames(video, samples)
    if not frames:
        result["error"] = "OpenCV not installed or no frames read: scan unavailable"
        return result
    if mask_bands:
        mask(frames, mask_bands)
        result["masked_bands"] = [list(b) for b in mask_bands]
    result["frames"] = len(frames)
    flagged = False
    cells = edge_cells(frames)
    result["methods"].append("edge-density")
    result["edge_cells"] = cells
    flagged |= bool(cells)
    if which("tesseract"):
        try:
            per_frame = [ocr_words(f, run) for f in frames]
            result["methods"].append("tesseract")
            hits = [b for b in per_frame if len(b) >= OCR_MIN_WORDS]
            result["ocr_frames_with_text"] = len(hits)
            result["ocr_boxes"] = [box for b in hits for box in b][:50]
            flagged |= len(hits) >= 2
        except RuntimeError as e:
            result["ocr_error"] = str(e)
    else:
        result["ocr"] = "tesseract not installed (edge-density only)"
    result["flagged"] = flagged
    result["regions"] = cells + result.get("ocr_boxes", [])
    return result
