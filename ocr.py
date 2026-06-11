"""
License plate OCR module.
Uses multiple preprocessing pipelines and multi-frame voting
for robust plate text recognition.
"""

import cv2
import numpy as np
import easyocr
from collections import Counter


class PlateOCR:
    """
    Reads license plate text with high accuracy using:
    - Multiple preprocessing pipelines (picks best result)
    - Tuned EasyOCR parameters for plate characters
    - Character allowlist to reduce noise
    - Multi-frame voting for consensus reading

    Parameters
    ----------
    languages : list of str
        Language codes for EasyOCR (e.g., ['en'], ['en', 'ch_sim']).
    gpu : bool
        Whether to use GPU for OCR inference.
    """

    def __init__(self, languages=None, gpu=True):
        if languages is None:
            languages = ["en"]
        self.reader = easyocr.Reader(languages, gpu=gpu)
        # Characters commonly found on license plates
        self.allowlist = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"

    def read_plate(self, frame, plate_bbox):
        """
        Extract and read text from a license plate region.
        Runs multiple preprocessing variants and picks the best result.

        Parameters
        ----------
        frame : np.ndarray
            Full BGR frame.
        plate_bbox : tuple
            (x1, y1, x2, y2) bounding box of the plate.

        Returns
        -------
        str
            Recognized plate text, or empty string.
        float
            Confidence score (0-1).
        """
        if plate_bbox is None:
            return "", 0.0

        x1, y1, x2, y2 = plate_bbox
        h, w = frame.shape[:2]

        # Clamp coordinates
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        plate_crop = frame[y1:y2, x1:x2]
        if plate_crop.size == 0 or plate_crop.shape[0] < 5 or plate_crop.shape[1] < 10:
            return "", 0.0

        # Expand crop slightly for better OCR context (10% padding)
        pad_x = int((x2 - x1) * 0.1)
        pad_y = int((y2 - y1) * 0.15)
        ex1, ey1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
        ex2, ey2 = min(w, x2 + pad_x), min(h, y2 + pad_y)
        plate_crop = frame[ey1:ey2, ex1:ex2]

        # Generate multiple preprocessed versions
        preprocessed_images = self._multi_preprocess(plate_crop)

        # Run OCR on each and collect results
        all_results = []
        for img in preprocessed_images:
            text, conf = self._run_ocr(img)
            if text:
                all_results.append((text, conf))

        if not all_results:
            return "", 0.0

        # Pick the result with highest confidence
        all_results.sort(key=lambda x: x[1], reverse=True)
        return all_results[0]

    def _multi_preprocess(self, plate_img):
        """
        Generate multiple preprocessed versions of the plate crop.
        Different preprocessing works better for different conditions
        (lighting, blur, contrast).
        """
        images = []
        h, w = plate_img.shape[:2]

        # Upscale small plates
        target_h = 100
        scale = max(target_h / h, 1.0)
        if scale > 1.0:
            plate_img = cv2.resize(
                plate_img,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_CUBIC,
            )

        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)

        # Pipeline 1: CLAHE + bilateral filter
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        enhanced = clahe.apply(gray)
        denoised = cv2.bilateralFilter(enhanced, 9, 75, 75)
        images.append(denoised)

        # Pipeline 2: Adaptive threshold (good for high contrast plates)
        adaptive = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4
        )
        images.append(adaptive)

        # Pipeline 3: Otsu threshold after Gaussian blur
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        images.append(otsu)

        # Pipeline 4: Inverted (for dark plates with light text)
        inverted = cv2.bitwise_not(otsu)
        images.append(inverted)

        # Pipeline 5: Sharpen + CLAHE (for slightly blurry plates)
        sharpen_kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharpened = cv2.filter2D(gray, -1, sharpen_kernel)
        sharp_enhanced = clahe.apply(sharpened)
        images.append(sharp_enhanced)

        # Pipeline 6: Original color (EasyOCR sometimes works better with color)
        images.append(plate_img)

        return images

    def _run_ocr(self, img):
        """
        Run EasyOCR on a single preprocessed image with plate-tuned parameters.
        """
        try:
            results = self.reader.readtext(
                img,
                detail=1,
                paragraph=False,
                allowlist=self.allowlist,
                batch_size=1,
                min_size=10,
                text_threshold=0.6,
                low_text=0.3,
                width_ths=0.8,  # Merge close text boxes
            )
        except Exception:
            return "", 0.0

        if not results:
            return "", 0.0

        # Sort by x position (left to right reading)
        results.sort(key=lambda r: r[0][0][0])

        texts = []
        confs = []

        for bbox, text, conf in results:
            cleaned = self._clean_plate_text(text)
            if cleaned and len(cleaned) >= 2:  # Ignore single-char noise
                texts.append(cleaned)
                confs.append(conf)

        if not texts:
            return "", 0.0

        combined = "".join(texts)
        avg_conf = sum(confs) / len(confs)

        # Reject very short results (likely noise)
        if len(combined) < 3:
            return "", 0.0

        return combined, avg_conf

    def _clean_plate_text(self, text):
        """Clean OCR output for plate characters."""
        cleaned = ""
        for ch in text.upper():
            if ch.isalnum() or ch == "-":
                cleaned += ch
        return cleaned


class PlateTextAggregator:
    """
    Aggregates plate text readings across multiple frames for each vehicle.
    Uses voting to determine the most likely correct plate text.

    This is much more reliable than a single-frame reading because:
    - Motion blur affects different frames differently
    - Lighting changes across frames
    - OCR may partially read a plate in some frames

    Parameters
    ----------
    min_readings : int
        Minimum readings before producing a consensus result.
    agreement_threshold : float
        Fraction of readings that must agree for consensus.
    """

    def __init__(self, min_readings=3, agreement_threshold=0.4):
        self.min_readings = min_readings
        self.agreement_threshold = agreement_threshold
        # vehicle_id -> list of (text, confidence)
        self.readings: dict[int, list[tuple[str, float]]] = {}

    def add_reading(self, vehicle_id, text, confidence):
        """Add a new plate reading for a vehicle."""
        if not text:
            return
        if vehicle_id not in self.readings:
            self.readings[vehicle_id] = []
        self.readings[vehicle_id].append((text, confidence))

    def get_consensus(self, vehicle_id):
        """
        Get the consensus plate text for a vehicle.

        Uses weighted voting: each reading's vote weight = its confidence.
        Also considers edit-distance similarity to group near-matches.

        Returns
        -------
        str
            Consensus plate text, or empty string if no consensus.
        float
            Confidence score.
        """
        if vehicle_id not in self.readings:
            return "", 0.0

        readings = self.readings[vehicle_id]
        if len(readings) < self.min_readings:
            # Not enough readings yet, return best single reading
            if readings:
                best = max(readings, key=lambda r: r[1])
                return best
            return "", 0.0

        # Group similar readings (allow 1-2 char differences)
        groups = self._group_similar(readings)

        if not groups:
            return "", 0.0

        # Pick the group with highest total weighted confidence
        best_group = max(groups, key=lambda g: g["score"])

        return best_group["text"], best_group["confidence"]

    def _group_similar(self, readings):
        """Group readings by similarity using edit distance."""
        groups = []

        for text, conf in readings:
            matched = False
            for group in groups:
                if self._is_similar(text, group["text"]):
                    group["count"] += 1
                    group["score"] += conf
                    # Update representative text if this reading has higher conf
                    if conf > group["confidence"]:
                        group["text"] = text
                        group["confidence"] = conf
                    matched = True
                    break

            if not matched:
                groups.append({
                    "text": text,
                    "confidence": conf,
                    "count": 1,
                    "score": conf,
                })

        return groups

    def _is_similar(self, text_a, text_b):
        """Check if two plate texts are similar (edit distance <= 2)."""
        if abs(len(text_a) - len(text_b)) > 2:
            return False

        # Simple Levenshtein check
        distance = self._edit_distance(text_a, text_b)
        max_len = max(len(text_a), len(text_b))
        if max_len == 0:
            return True
        return distance <= max(2, max_len * 0.3)

    def _edit_distance(self, s1, s2):
        """Compute Levenshtein edit distance."""
        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                dp[i][j] = min(
                    dp[i - 1][j] + 1,
                    dp[i][j - 1] + 1,
                    dp[i - 1][j - 1] + cost,
                )

        return dp[m][n]
