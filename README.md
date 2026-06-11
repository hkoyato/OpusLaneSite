# Opus LaneSight — Vehicle Wait Time Analyzer

AI-powered station wait-time intelligence. Detects vehicles from video clips or live camera streams, locates license plates, reads plate text via OCR, tracks vehicles with DeepSORT, and calculates how long each vehicle is visible in the camera (wait time).

## Features

- Vehicle detection using YOLOv8 (local) or AWS Rekognition (cloud)
- License plate localization (multi-method: YOLO model, contour, morphology, color)
- Plate text OCR via EasyOCR with multi-frame voting consensus
- DeepSORT-style tracking: Kalman filter + appearance re-identification
- Occlusion-aware tracking with gallery-based re-ID
- Wait time calculation with statistics
- Supports both video files and live RTSP/RTMP/HTTP streams
- Annotated output video with vehicle IDs and plate text overlay
- Auto-reconnection for unreliable streams

## Setup

```bash
pip install -r requirements.txt
```

### Dependencies

| Package | Role |
|---------|------|
| `ultralytics` | YOLOv8 local vehicle detection |
| `opencv-python` | Video I/O, image processing, annotation |
| `easyocr` | License plate text recognition |
| `scipy` | Hungarian algorithm for optimal track assignment |
| `numpy` | Numerical operations |
| `boto3` | AWS Rekognition API (optional, only for `--detector rekognition`) |

### AWS Rekognition setup (optional)

Only needed if you want to use `--detector rekognition`:

```bash
pip install awscli
aws configure
```

Required IAM permissions: `rekognition:DetectLabels`, `rekognition:DetectText`.

## Usage

### Input source (required, pick one)

| Flag | Description |
|------|-------------|
| `--video PATH` | Path to a video file (MP4, AVI, MKV, MOV, etc.) |
| `--stream URL` | RTSP/RTMP/HTTP live stream URL |

These are mutually exclusive — use one or the other.

### All options

| Flag | Description | Default |
|------|-------------|---------|
| `--video PATH` | Input video file path | — |
| `--stream URL` | Live stream URL (RTSP/RTMP/HTTP) | — |
| `--output PATH` | Path to save annotated output video | `output.mp4` (file mode), none (stream mode) |
| `--no-output` | Disable saving output video entirely | `False` |
| `--detector {yolo,rekognition}` | Detection backend | `yolo` |
| `--aws-region REGION` | AWS region for Rekognition | `us-east-1` |
| `--conf FLOAT` | Detection confidence threshold (0-1) | `0.5` |
| `--detect-interval N` | Run detection every N frames (Kalman predicts between) | `1` |
| `--show` | Display live preview window | `False` |
| `--display-width PX` | Preview window width in pixels (maintains aspect ratio) | `1280` |
| `--plate-model PATH` | Path to YOLO model for plate detection | None (uses contour fallback) |
| `--ocr-lang LANG [LANG ...]` | OCR language codes | `en` |
| `--ocr-interval N` | Run OCR every N frames | `10` |
| `--no-ocr` | Disable plate text OCR (faster processing) | `False` |

## Command Examples

### Basic video file processing

```bash
# Process video, save annotated output, show preview
python main.py --video clip.mp4 --show

# Process without preview (headless)
python main.py --video clip.mp4

# No output video, just console results
python main.py --video clip.mp4 --no-output

# Custom output path
python main.py --video clip.mp4 --output result.mp4
```

### Live stream

```bash
# RTSP IP camera
python main.py --stream rtsp://admin:password@192.168.1.100:554/stream1

# RTMP stream
python main.py --stream rtmp://server.com/live/channel

# HTTP MJPEG stream
python main.py --stream http://camera.example.com/video.mjpg

# Stream with recording to file
python main.py --stream rtsp://192.168.1.100:554/stream --output recording.mp4
```

### Detection backend

```bash
# Local YOLOv8 (default, free, fast, needs GPU for best performance)
python main.py --video clip.mp4 --detector yolo --show

# AWS Rekognition (cloud API, no local GPU needed)
python main.py --video clip.mp4 --detector rekognition --show

# Rekognition with specific region
python main.py --video clip.mp4 --detector rekognition --aws-region eu-west-1

# Rekognition with frame skipping to reduce API costs
python main.py --video clip.mp4 --detector rekognition --detect-interval 5 --show
```

### Performance tuning

```bash
# Skip frames for faster processing (tracker predicts between)
python main.py --video clip.mp4 --detect-interval 3 --show

# Lower confidence threshold (detect more vehicles, may include false positives)
python main.py --video clip.mp4 --conf 0.3 --show

# Higher confidence (fewer false positives, may miss distant vehicles)
python main.py --video clip.mp4 --conf 0.7 --show

# Disable OCR for maximum speed
python main.py --video clip.mp4 --no-ocr --show

# More frequent OCR (better plate reading, slower)
python main.py --video clip.mp4 --ocr-interval 5 --show

# Less frequent OCR (faster, still aggregates across frames)
python main.py --video clip.mp4 --ocr-interval 30 --show
```

### Display options

```bash
# Smaller preview window (laptop screen)
python main.py --video clip.mp4 --show --display-width 800

# Larger preview window (external monitor)
python main.py --video clip.mp4 --show --display-width 1920

# Full HD preview
python main.py --video clip.mp4 --show --display-width 1920
```

### OCR language

```bash
# English plates (default)
python main.py --video clip.mp4 --ocr-lang en --show

# Chinese + English plates
python main.py --video clip.mp4 --ocr-lang en ch_sim --show

# Korean plates
python main.py --video clip.mp4 --ocr-lang en ko --show
```

### Plate detection model

```bash
# Use a dedicated YOLO plate detection model (most accurate)
python main.py --video clip.mp4 --plate-model plate_detect.pt --show

# Without plate model (uses contour/morphology/color fallback)
python main.py --video clip.mp4 --show
```

### Combined examples

```bash
# Full-featured: Rekognition + OCR + stream + recording
python main.py --stream rtsp://192.168.1.100:554/cam1 \
  --detector rekognition --aws-region us-west-2 \
  --detect-interval 5 --ocr-lang en \
  --output station_recording.mp4 --show --display-width 1280

# Fast local processing: YOLO + no OCR + no output
python main.py --video clip.mp4 --detector yolo --no-ocr --no-output --show

# Hackathon demo: local YOLO + OCR disabled (privacy-preserving)
python main.py --video demo_station.mp4 --no-ocr --show --display-width 1280
```

## Output

### Console output

```
==========================================================================================
VEHICLE WAIT TIME ANALYSIS RESULTS
==========================================================================================
Vehicle ID  Plate Text      Confidence  Enter (s)   Leave (s)   Wait Time (s)
------------------------------------------------------------------------------------------
1           W1771TX         0.84        0.00        10.12       10.12
2           W36283M         0.99        0.00        6.60        6.60
3           N/A             -           0.32        2.92        2.60
4           N/A             -           3.96        6.08        2.12
==========================================================================================
Total vehicles tracked: 4
Average wait time: 5.36s
Max wait time: 10.12s
Min wait time: 2.12s
```

### Annotated video

The output video includes:
- Green bounding boxes around detected vehicles
- Vehicle ID labels
- Blue bounding boxes around detected plates
- Plate text overlay (when OCR is enabled)
- Live stream overlay with elapsed time and FPS (stream mode)

## Architecture

```
main.py                  CLI entry point, video/stream I/O loop, orchestration
detector.py              YOLOv8 local vehicle + plate detection
detector_rekognition.py  AWS Rekognition vehicle + plate detection
plate_detector.py        Contour/morphology/color plate region detection
tracker.py               DeepSORT tracker (Kalman + Hungarian + gallery re-ID)
appearance.py            HSV color histogram feature extractor for re-ID
ocr.py                   EasyOCR plate reader + multi-frame voting aggregator
```

## Privacy note

LaneSight uses temporary anonymous vehicle session IDs for wait-time calculation. License plates and driver identities are not stored. OCR can be fully disabled with `--no-ocr` for privacy-preserving deployments.

## Keyboard controls

| Key | Action |
|-----|--------|
| `q` | Stop processing and show results |
