# OpusLaneSite - Vehicle Wait Time Analyzer

Analyzes video clips to detect cars, locate license plates, read plate text via OCR, and calculate how long each vehicle is visible in the camera (wait time).

## Features

- Vehicle detection using YOLOv8 (car, truck, bus, motorcycle)
- License plate localization (YOLO model or heuristic fallback)
- Plate text OCR via EasyOCR (multi-language support)
- DeepSORT-style tracking: Kalman filter + appearance re-identification
- Wait time calculation with statistics
- Annotated output video with IDs and plate text overlay

## Setup

```bash
pip install -r requirements.txt
```

### Dependencies

- `ultralytics` - YOLOv8 for object detection
- `opencv-python` - Video I/O and image processing
- `easyocr` - License plate text recognition
- `scipy` - Hungarian algorithm for optimal track assignment
- `filterpy` - Kalman filter utilities
- `numpy` - Numerical operations

## Usage

```bash
# Basic usage
python main.py --video path/to/video.mp4

# With live preview
python main.py --video video.mp4 --show

# With dedicated plate detection model
python main.py --video video.mp4 --plate-model plate_detect.pt

# Chinese plates
python main.py --video video.mp4 --ocr-lang en ch_sim

# Fast mode (no OCR)
python main.py --video video.mp4 --no-ocr

# Adjust OCR frequency (every 5 frames instead of default 10)
python main.py --video video.mp4 --ocr-interval 5
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--video` | Path to input video file | (required) |
| `--output` | Path to save annotated output video | `output.mp4` |
| `--conf` | Detection confidence threshold | `0.5` |
| `--show` | Display video while processing | `False` |
| `--plate-model` | Path to YOLO plate detection model | None (heuristic) |
| `--ocr-lang` | OCR language codes | `en` |
| `--ocr-interval` | Run OCR every N frames | `10` |
| `--no-ocr` | Disable OCR for faster processing | `False` |

## Output

```
==========================================================================================
VEHICLE WAIT TIME ANALYSIS RESULTS
==========================================================================================
Vehicle ID  Plate Text      Confidence  Enter (s)   Leave (s)   Wait Time (s)
------------------------------------------------------------------------------------------
1           ABC1234         0.92        0.50        4.20        3.70
2           XYZ5678         0.87        1.00        5.80        4.80
3           N/A             -           2.30        3.10        0.80
==========================================================================================
Total vehicles tracked: 3
Average wait time: 3.10s
Max wait time: 4.80s
Min wait time: 0.80s
```

## Architecture

```
main.py              # Entry point, CLI, video pipeline
detector.py          # YOLOv8 vehicle + plate detection
tracker.py           # DeepSORT tracker (Kalman + Hungarian assignment)
appearance.py        # Color histogram feature extractor for re-ID
ocr.py               # EasyOCR plate text reader with preprocessing
```

### How It Works

1. **Detection** (`detector.py`) - YOLOv8 detects vehicles in each frame. For each vehicle, a plate region is localized using either a dedicated model or a heuristic.

2. **Appearance** (`appearance.py`) - Extracts color histogram features from each vehicle crop (HSV space, spatial grid). Used by the tracker to re-identify vehicles after occlusions.

3. **Tracking** (`tracker.py`) - DeepSORT-style tracker:
   - Kalman filter predicts vehicle positions between frames
   - Hungarian algorithm finds optimal detection-to-track assignment
   - Combined IoU + appearance cost for robust matching
   - Handles occlusions and brief disappearances

4. **OCR** (`ocr.py`) - Periodically reads plate text from detected plate regions:
   - Preprocessing: grayscale, resize, CLAHE, denoising
   - EasyOCR inference with multi-language support
   - Confidence-based updates (keeps best reading per vehicle)

5. **Timing** - First and last frame of each track → converted to seconds via FPS → wait time
