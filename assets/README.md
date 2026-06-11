# Opus LaneSight — Assets

Runtime assets that are loaded by the application at execution time. These are
kept separate from `gui/resources/` (bundled UI assets such as the logo, window
icon, and fonts) because they are larger, optional, or user-supplied.

## Layout

```text
assets/
  models/        ML model weights (YOLOv8 vehicle/plate detectors, etc.)
    yolov8n.pt   Default vehicle detection model (place here)
```

## Where the app looks for model weights

The application resolves a model file (for example `yolov8n.pt`) by checking the
following locations in order and using the first one that exists:

1. An explicit path supplied via settings or the CLI.
2. The `LANESIGHT_MODELS_DIR` environment variable, if set.
3. `assets/models/` next to the application (this folder).
4. The application base directory (next to the executable / repo root).
5. The current working directory (legacy behaviour).

Resolution is implemented in `gui/assets.py`. Place model weights in
`assets/models/` so they are found regardless of the directory the app is
launched from.

## Version control

Model weights (`*.pt`, `*.onnx`) are intentionally git-ignored. Only the folder
structure (via `.gitkeep`) and this README are tracked. Obtain weights by
downloading them (for example the Ultralytics `yolov8n.pt`) or training your own,
then drop them into `assets/models/`.
