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

        # Pick the result with highest confidence that passes validation
        all_results.sort(key=lambda x: x[1], reverse=True)
        for text, conf in all_results:
            if self._is_valid_plate_text(text, conf):
                return text, conf

        return "", 0.0

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
                text_threshold=0.5,
                low_text=0.3,
                width_ths=1.0,
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
            # Reject very low confidence individual detections
            if conf < 0.2:
                continue
            cleaned = self._clean_plate_text(text)
            if cleaned and len(cleaned) >= 1:
                texts.append(cleaned)
                confs.append(conf)

        if not texts:
            return "", 0.0

        combined = "".join(texts)
        avg_conf = sum(confs) / len(confs)

        # Reject very short or very long results
        if len(combined) < 3 or len(combined) > 12:
            return "", 0.0

        return combined, avg_conf

    def _is_valid_plate_text(self, text, confidence):
        """
        Validate that OCR result looks like a real license plate.

        Real plates typically:
        - Are 4-10 characters
        - Contain both letters and digits (most formats)
        - Have confidence > 0.4
        - Don't have too many repeated characters
        - Don't contain common vehicle words/logos
        """
        if not text or confidence < 0.4:
            return False

        length = len(text)
        if length < 4 or length > 10:
            return False

        # Reject common vehicle body text / logos (not plates)
        text_upper = text.upper()
        non_plate_words = [
            "TAXI", "POLICE", "AMBULANCE", "FIRE", "SCHOOL",
            "BUS", "UBER", "LYFT", "FEDEX", "UPS", "DHL",
            "FORD", "HONDA", "TOYOTA", "BMW", "AUDI", "BENZ",
            "CHEVR", "NISSAN", "HYUNDAI", "KIA", "VOLVO",
            "DIESEL", "HYBRID", "TURBO", "SPORT", "EDITION",
        ]
        for word in non_plate_words:
            if word in text_upper:
                return False

        # Reject if text starts with a common logo/brand word pattern
        # Real plates don't usually start with full English words > 3 chars
        if length >= 5:
            alpha_prefix = ""
            for ch in text_upper:
                if ch.isalpha():
                    alpha_prefix += ch
                else:
                    break
            if len(alpha_prefix) >= 4 and alpha_prefix in [
                "TAXI", "UBER", "LYFT", "FORD", "JEEP", "MINI",
                "FIRE", "CITY", "AUTO", "RENT", "FREE", "CALL",
            ]:
                return False

        # Must contain at least one digit
        has_digit = any(c.isdigit() for c in text)
        # Must contain at least one letter
        has_letter = any(c.isalpha() for c in text)

        if not has_digit or not has_letter:
            return False

        # Reject if too many repeated characters (e.g., "AAAAAAA" from noise)
        char_counts = Counter(text)
        most_common_count = char_counts.most_common(1)[0][1]
        if most_common_count > length * 0.6:
            return False

        # Reject obvious non-plate patterns
        unique_chars = len(set(text))
        if unique_chars < 2:
            return False

        return True

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
        """Group readings by similarity using OCR-aware normalization."""
        groups = []

        for text, conf in readings:
            matched = False
            for group in groups:
                if self._is_similar(text, group["representative"]):
                    group["count"] += 1
                    group["score"] += conf
                    group["all_texts"].append((text, conf))
                    matched = True
                    break

            if not matched:
                groups.append({
                    "representative": text,
                    "count": 1,
                    "score": conf,
                    "all_texts": [(text, conf)],
                })

        # For each group, pick the best representative text:
        # - If one reading is a substring of another (normalized), prefer shorter
        # - Otherwise prefer the most frequent reading; break ties by shortest
        for group in groups:
            text_counts = {}
            for t, c in group["all_texts"]:
                if t not in text_counts:
                    text_counts[t] = {"count": 0, "max_conf": 0.0}
                text_counts[t]["count"] += 1
                text_counts[t]["max_conf"] = max(text_counts[t]["max_conf"], c)

            unique_texts = list(text_counts.keys())

            # Check substring relationships — shorter is likely correct
            chosen = None
            unique_texts_sorted = sorted(unique_texts, key=len)
            for i, shorter in enumerate(unique_texts_sorted):
                norm_short = self._normalize(shorter)
                for j in range(i + 1, len(unique_texts_sorted)):
                    longer = unique_texts_sorted[j]
                    norm_long = self._normalize(longer)
                    if norm_short in norm_long:
                        chosen = shorter
                        break
                if chosen:
                    break

            if chosen is None:
                # No substring relation — pick most frequent, then shortest
                chosen = max(
                    unique_texts,
                    key=lambda t: (text_counts[t]["count"], -len(t)),
                )

            group["text"] = chosen
            group["confidence"] = text_counts[chosen]["max_conf"]

        return groups

    def _is_similar(self, text_a, text_b):
        """
        Check if two plate texts are similar, accounting for OCR errors.
        Uses character normalization (1↔7, 0↔O, etc.) before comparing.
        """
        if abs(len(text_a) - len(text_b)) > 2:
            return False

        # Normalize OCR-confusable characters
        norm_a = self._normalize(text_a)
        norm_b = self._normalize(text_b)

        # Exact match after normalization
        if norm_a == norm_b:
            return True

        # Substring check (handles extra leading/trailing noise chars)
        if norm_a in norm_b or norm_b in norm_a:
            return True

        # Edit distance on normalized text
        distance = self._edit_distance(norm_a, norm_b)
        max_len = max(len(norm_a), len(norm_b))
        if max_len == 0:
            return True
        return distance <= max(2, int(max_len * 0.3))

    def _normalize(self, text):
        """Normalize OCR-confusable characters to canonical forms."""
        char_map = {
            "O": "0",
            "I": "1",
            "L": "1",
            "Z": "2",
            "S": "5",
            "B": "8",
            "G": "6",
            "7": "1",
        }
        return "".join(char_map.get(ch, ch) for ch in text.upper())

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
