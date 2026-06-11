"""
Vehicle and license plate detection using AWS Rekognition.

Uses Rekognition's DetectLabels API for vehicle detection and
DetectText API for plate text detection within vehicle regions.
"""

import cv2
import numpy as np
import boto3

from plate_detector import PlateDetector


# Rekognition labels that correspond to vehicles
VEHICLE_LABELS = {"Car", "Automobile", "Truck", "Bus", "Van", "Motorcycle", "Vehicle"}


class RekognitionDetector:
    """
    Detects vehicles and license plates using AWS Rekognition.

    Uses DetectLabels for vehicle bounding boxes. For plate detection,
    can use Rekognition's DetectText on the vehicle crop or fall back
    to the local contour-based PlateDetector.

    Parameters
    ----------
    region_name : str
        AWS region for Rekognition API calls.
    confidence : float
        Minimum confidence threshold for detections (0-100 for Rekognition).
    use_rekognition_text : bool
        If True, use Rekognition DetectText for plate localization.
        If False, use local contour-based PlateDetector (saves API calls).
    """

    def __init__(
        self,
        region_name="us-east-1",
        confidence=0.5,
        use_rekognition_text=False,
    ):
        self.client = boto3.client("rekognition", region_name=region_name)
        # Rekognition uses 0-100 confidence scale
        self.confidence = confidence * 100
        self.use_rekognition_text = use_rekognition_text
        self.plate_detector = PlateDetector()

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
            - 'vehicle_conf': float confidence score (0-1)
        """
        h, w = frame.shape[:2]

        # Encode frame as JPEG for Rekognition API
        _, jpeg_bytes = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        image_bytes = jpeg_bytes.tobytes()

        # Call Rekognition DetectLabels
        try:
            response = self.client.detect_labels(
                Image={"Bytes": image_bytes},
                MinConfidence=self.confidence,
                MaxLabels=50,
            )
        except Exception as e:
            print(f"\nRekognition API error: {e}")
            return []

        detections = []

        for label in response.get("Labels", []):
            if label["Name"] not in VEHICLE_LABELS:
                continue

            for instance in label.get("Instances", []):
                bbox_data = instance.get("BoundingBox")
                if bbox_data is None:
                    continue

                conf = instance.get("Confidence", 0) / 100.0

                # Convert Rekognition relative coords to absolute pixels
                x1 = int(bbox_data["Left"] * w)
                y1 = int(bbox_data["Top"] * h)
                x2 = int((bbox_data["Left"] + bbox_data["Width"]) * w)
                y2 = int((bbox_data["Top"] + bbox_data["Height"]) * h)
                vehicle_bbox = (x1, y1, x2, y2)

                # Locate plate (and optionally read text via Rekognition)
                plate_bbox, plate_text, plate_text_conf = self._detect_plate(
                    frame, vehicle_bbox
                )

                detections.append(
                    {
                        "bbox": vehicle_bbox,
                        "plate_bbox": plate_bbox,
                        "vehicle_conf": conf,
                        "plate_text": plate_text,
                        "plate_text_conf": plate_text_conf,
                    }
                )

        return detections

    def _detect_plate(self, frame, vehicle_bbox):
        """
        Detect license plate within a vehicle bounding box.

        Uses Rekognition DetectText or local PlateDetector.

        Returns
        -------
        tuple
            (plate_bbox, plate_text, plate_text_conf) where plate_bbox is
            (x1, y1, x2, y2) or None, plate_text is str or None,
            and plate_text_conf is float or 0.0.
        """
        x1, y1, x2, y2 = vehicle_bbox
        vw = x2 - x1
        vh = y2 - y1

        if vw < 50 or vh < 50:
            return None, None, 0.0

        aspect = vw / vh if vh > 0 else 0
        if aspect > 3.0:
            return None, None, 0.0

        vehicle_crop = frame[y1:y2, x1:x2]
        if vehicle_crop.size == 0:
            return None, None, 0.0

        # Method 1: Rekognition DetectText (finds text regions and reads them)
        if self.use_rekognition_text:
            result = self._rekognition_text_detect(vehicle_crop, vehicle_bbox)
            if result is not None:
                return result

        # Method 2: Local contour-based plate detection (no API call, no text)
        plate_region = self.plate_detector.detect(vehicle_crop)
        if plate_region is not None:
            px, py, pw, ph = plate_region
            return (x1 + px, y1 + py, x1 + px + pw, y1 + py + ph), None, 0.0

        return None, None, 0.0

    def _rekognition_text_detect(self, vehicle_crop, vehicle_bbox):
        """
        Use Rekognition DetectText to find plate-like text in vehicle crop.

        Returns both the plate bounding box and the recognized text,
        eliminating the need for a separate EasyOCR pass.

        Returns
        -------
        tuple or None
            (plate_bbox, plate_text, confidence) or None if no plate found.
        """
        x1_v, y1_v, x2_v, y2_v = vehicle_bbox
        vh, vw = vehicle_crop.shape[:2]

        _, jpeg_bytes = cv2.imencode(
            ".jpg", vehicle_crop, [cv2.IMWRITE_JPEG_QUALITY, 85]
        )

        try:
            response = self.client.detect_text(
                Image={"Bytes": jpeg_bytes.tobytes()},
                Filters={
                    "WordFilter": {"MinConfidence": 70},
                },
            )
        except Exception:
            return None

        best_result = None
        best_score = 0

        for detection in response.get("TextDetections", []):
            if detection["Type"] != "LINE":
                continue

            text = detection["DetectedText"].replace(" ", "").upper()
            if len(text) < 4 or len(text) > 10:
                continue
            if not any(c.isdigit() for c in text):
                continue
            if not any(c.isalpha() for c in text):
                continue

            geo = detection.get("Geometry", {}).get("BoundingBox", {})
            if not geo:
                continue

            px1 = int(geo["Left"] * vw) + x1_v
            py1 = int(geo["Top"] * vh) + y1_v
            px2 = int((geo["Left"] + geo["Width"]) * vw) + x1_v
            py2 = int((geo["Top"] + geo["Height"]) * vh) + y1_v

            pw = px2 - px1
            ph = py2 - py1
            if ph == 0:
                continue
            plate_aspect = pw / ph
            if plate_aspect < 2.0 or plate_aspect > 6.0:
                continue

            position_score = (py1 - y1_v) / vh
            confidence = detection.get("Confidence", 0) / 100.0
            score = confidence * 0.6 + position_score * 0.4

            if score > best_score:
                best_score = score
                best_result = ((px1, py1, px2, py2), text, confidence)

        return best_result
