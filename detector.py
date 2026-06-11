"""
Vehicle and license plate detection using YOLOv8.
"""

from ultralytics import YOLO
import numpy as np


# COCO class IDs for vehicles
VEHICLE_CLASS_IDS = {2, 3, 5, 7}  # car, motorcycle, bus, truck


class VehicleDetector:
    """
    Detects vehicles and license plates in video frames.

    Uses YOLOv8 for vehicle detection. For license plate localization,
    it uses a secondary YOLO model trained on plates, or falls back to
    a heuristic region proposal within the vehicle bounding box.

    Parameters
    ----------
    vehicle_model_path : str
        Path or name of the YOLOv8 model for vehicles (e.g., 'yolov8n.pt').
    plate_model_path : str or None
        Path to a YOLO model trained for plate detection. If None, uses
        a heuristic approach to estimate plate location.
    confidence : float
        Minimum confidence threshold for detections.
    """

    def __init__(
        self,
        vehicle_model_path="yolov8n.pt",
        plate_model_path=None,
        confidence=0.5,
    ):
        self.vehicle_model = YOLO(vehicle_model_path)
        self.plate_model = YOLO(plate_model_path) if plate_model_path else None
        self.confidence = confidence

    def detect(self, frame):
        """
        Detect vehicles and their license plates in a single frame.

        Parameters
        ----------
        frame : np.ndarray
            BGR image (OpenCV format).

        Returns
        -------
        list of dict
            Each dict contains:
            - 'bbox': (x1, y1, x2, y2) vehicle bounding box
            - 'plate_bbox': (x1, y1, x2, y2) plate bounding box or None
            - 'vehicle_conf': float confidence score
        """
        results = self.vehicle_model(frame, conf=self.confidence, verbose=False)
        detections = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                if cls_id not in VEHICLE_CLASS_IDS:
                    continue

                conf = float(boxes.conf[i].item())
                x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy().astype(int)
                vehicle_bbox = (int(x1), int(y1), int(x2), int(y2))

                # Locate plate within vehicle region
                plate_bbox = self._detect_plate(frame, vehicle_bbox)

                detections.append(
                    {
                        "bbox": vehicle_bbox,
                        "plate_bbox": plate_bbox,
                        "vehicle_conf": conf,
                    }
                )

        return detections

    def _detect_plate(self, frame, vehicle_bbox):
        """
        Detect license plate within a vehicle bounding box.

        If a plate model is available, runs inference on the cropped region.
        Otherwise, uses a heuristic: plates are typically in the lower-center
        portion of the vehicle bounding box.

        Returns
        -------
        tuple or None
            (x1, y1, x2, y2) in frame coordinates, or None if not found.
        """
        x1, y1, x2, y2 = vehicle_bbox
        vehicle_crop = frame[y1:y2, x1:x2]

        if vehicle_crop.size == 0:
            return None

        if self.plate_model is not None:
            plate_results = self.plate_model(
                vehicle_crop, conf=self.confidence, verbose=False
            )
            for result in plate_results:
                if result.boxes is not None and len(result.boxes) > 0:
                    # Take the highest confidence plate detection
                    best_idx = result.boxes.conf.argmax()
                    px1, py1, px2, py2 = (
                        result.boxes.xyxy[best_idx].cpu().numpy().astype(int)
                    )
                    # Convert back to frame coordinates
                    return (
                        int(x1 + px1),
                        int(y1 + py1),
                        int(x1 + px2),
                        int(y1 + py2),
                    )
            return None

        # Heuristic fallback: estimate plate in lower-center of vehicle box
        return self._heuristic_plate_region(vehicle_bbox)

    def _heuristic_plate_region(self, vehicle_bbox):
        """
        Estimate plate location heuristically.

        Assumes plate is in the lower 30% vertically and center 40% horizontally
        of the vehicle bounding box.
        """
        x1, y1, x2, y2 = vehicle_bbox
        w = x2 - x1
        h = y2 - y1

        # Plate is typically in lower portion, center of vehicle
        plate_x1 = x1 + int(w * 0.3)
        plate_x2 = x1 + int(w * 0.7)
        plate_y1 = y1 + int(h * 0.7)
        plate_y2 = y1 + int(h * 0.9)

        return (plate_x1, plate_y1, plate_x2, plate_y2)
