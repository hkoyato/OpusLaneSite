"""
Dedicated license plate detection module.
Uses contour-based detection with strict validation to avoid false positives.
Only returns a plate region when there is strong evidence one exists.
"""

import cv2
import numpy as np


class PlateDetector:
    """
    Detects license plate regions within a vehicle crop using
    image processing with strict validation to minimize false positives.

    Key design: returns None rather than guessing when no plate is confidently found.

    Parameters
    ----------
    min_area_ratio : float
        Minimum plate area as ratio of vehicle area.
    max_area_ratio : float
        Maximum plate area as ratio of vehicle area.
    min_aspect : float
        Minimum plate aspect ratio (width/height).
    max_aspect : float
        Maximum plate aspect ratio (width/height).
    min_confidence : float
        Minimum confidence score (0-1) to accept a candidate.
    """

    def __init__(
        self,
        min_area_ratio=0.008,
        max_area_ratio=0.12,
        min_aspect=2.0,
        max_aspect=5.5,
        min_confidence=0.3,
    ):
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio
        self.min_aspect = min_aspect
        self.max_aspect = max_aspect
        self.min_confidence = min_confidence

    def detect(self, vehicle_crop):
        """
        Detect license plate region within a vehicle crop.

        Returns None only if no method finds anything AND the heuristic
        region fails text validation.

        Parameters
        ----------
        vehicle_crop : np.ndarray
            BGR image of the vehicle region.

        Returns
        -------
        tuple or None
            (x, y, w, h) bounding box in crop coordinates, or None.
        """
        if vehicle_crop.size == 0:
            return None

        h, w = vehicle_crop.shape[:2]
        # Skip very small crops where plate detection is unreliable
        if h < 50 or w < 50:
            return None

        candidates = []

        # Method 1: Edge-based detection
        result = self._edge_based_detection(vehicle_crop)
        if result is not None:
            candidates.append(("edge", result))

        # Method 2: Morphology-based detection
        result = self._morph_based_detection(vehicle_crop)
        if result is not None:
            candidates.append(("morph", result))

        # Method 3: Color-based detection
        result = self._color_based_detection(vehicle_crop)
        if result is not None:
            candidates.append(("color", result))

        if candidates:
            # Require consensus or validation
            best = self._select_best_candidate(candidates, vehicle_crop)
            if best is not None:
                return best

        # Fallback: conservative heuristic region (bottom-center of vehicle).
        # Only return it if the region passes relaxed validation — this lets
        # the OCR module decide if there's actually readable text there.
        heuristic = self._heuristic_region(vehicle_crop)
        if self._validate_plate_region(vehicle_crop, heuristic, strict=False):
            return heuristic

        return None

    def _heuristic_region(self, crop):
        """
        Conservative heuristic: plates are typically in the bottom 30%,
        center 60% of the vehicle bounding box.

        Only used as fallback when detection methods fail.
        """
        h, w = crop.shape[:2]
        x = int(w * 0.2)
        y = int(h * 0.65)
        bw = int(w * 0.6)
        bh = int(h * 0.25)
        return (x, y, bw, bh)

    def _select_best_candidate(self, candidates, crop):
        """
        Select best candidate. Accept if:
        - Two methods agree on location (consensus), OR
        - One method finds a region that passes text validation

        Designed to avoid false positives while not being so strict
        that real plates are missed.
        """
        h, w = crop.shape[:2]

        # First: check if at least 2 candidates overlap (strong evidence)
        if len(candidates) >= 2:
            for i in range(len(candidates)):
                for j in range(i + 1, len(candidates)):
                    box_a = candidates[i][1]
                    box_b = candidates[j][1]
                    iou = self._box_iou(box_a, box_b)
                    if iou > 0.3:
                        # Two methods agree — accept with lighter validation
                        merged = self._merge_boxes(box_a, box_b)
                        if self._validate_plate_region(crop, merged, strict=False):
                            return merged

        # Single-method candidates: validate each one
        scored = []
        for method, box in candidates:
            if self._validate_plate_region(crop, box, strict=True):
                score = self._score_candidate(box, crop)
                scored.append((score, box))

        if not scored:
            # Fallback: try lighter validation for any candidate
            for method, box in candidates:
                if self._validate_plate_region(crop, box, strict=False):
                    score = self._score_candidate(box, crop)
                    scored.append((score, box))

        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_box = scored[0]

        if best_score < self.min_confidence:
            return None

        return best_box

    def _validate_plate_region(self, crop, box, strict=True):
        """
        Validate that a candidate region actually looks like a license plate.

        Parameters
        ----------
        strict : bool
            If True, applies all checks. If False (consensus mode), uses
            relaxed thresholds since two methods already agreed.
        """
        x, y, bw, bh = box
        h, w = crop.shape[:2]

        # Clamp to crop bounds
        x = max(0, x)
        y = max(0, y)
        bw = min(bw, w - x)
        bh = min(bh, h - y)

        if bw < 10 or bh < 5:
            return False

        region = crop[y:y + bh, x:x + bw]
        if region.size == 0:
            return False

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

        # Check 1: Edge density — plates have edges from characters
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / edges.size

        min_edge = 0.05 if not strict else 0.08
        max_edge = 0.75 if not strict else 0.7
        if edge_density < min_edge or edge_density > max_edge:
            return False

        # Check 2: Contrast — plates have visible text
        std_dev = np.std(gray)
        min_std = 20 if not strict else 30
        if std_dev < min_std:
            return False

        # Check 3: Vertical edge energy (character strokes)
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        vert_energy = np.mean(np.abs(sobel_x))
        min_energy = 3 if not strict else 5
        if vert_energy < min_energy:
            return False

        # Check 4: Background uniformity (only in strict mode)
        if strict:
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            white_ratio = np.sum(binary > 0) / binary.size
            if white_ratio < 0.12 or white_ratio > 0.92:
                return False

        return True

    def _edge_based_detection(self, crop):
        """Detect plate using Canny edges + contour approximation."""
        h, w = crop.shape[:2]
        vehicle_area = h * w

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 11, 17, 17)

        edges = cv2.Canny(gray, 50, 200)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(
            edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )

        plate_candidates = []
        for contour in contours:
            area = cv2.contourArea(contour)
            area_ratio = area / vehicle_area

            if area_ratio < self.min_area_ratio or area_ratio > self.max_area_ratio:
                continue

            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

            if 4 <= len(approx) <= 6:
                x, y, bw, bh = cv2.boundingRect(approx)
                if bh == 0:
                    continue
                aspect = bw / bh

                if self.min_aspect <= aspect <= self.max_aspect:
                    # Rectangularity: how well does the contour fill its bounding box
                    rect_fill = area / (bw * bh) if bw * bh > 0 else 0
                    if rect_fill > 0.5:  # Plates are mostly rectangular
                        plate_candidates.append((x, y, bw, bh, rect_fill))

        if not plate_candidates:
            return None

        # Best: highest rectangularity among valid candidates
        plate_candidates.sort(key=lambda c: c[4], reverse=True)
        x, y, bw, bh, _ = plate_candidates[0]
        return (x, y, bw, bh)

    def _morph_based_detection(self, crop):
        """Detect plate using morphological operations to find text-dense regions."""
        h, w = crop.shape[:2]
        vehicle_area = h * w

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        # Blackhat to reveal dark text on light background
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
        blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)

        _, thresh = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Close to connect characters into a blob
        close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 5))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, close_kernel)

        contours, _ = cv2.findContours(
            closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            x, y, bw, bh = cv2.boundingRect(contour)
            area_ratio = (bw * bh) / vehicle_area

            if area_ratio < self.min_area_ratio or area_ratio > self.max_area_ratio:
                continue

            if bh == 0:
                continue
            aspect = bw / bh
            if self.min_aspect <= aspect <= self.max_aspect:
                return (x, y, bw, bh)

        return None

    def _color_based_detection(self, crop):
        """Detect plate based on distinct plate colors (white/yellow/blue)."""
        h, w = crop.shape[:2]
        vehicle_area = h * w
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        # White plate mask (stricter saturation range)
        white_lower = np.array([0, 0, 200])
        white_upper = np.array([180, 40, 255])
        white_mask = cv2.inRange(hsv, white_lower, white_upper)

        # Yellow plate mask
        yellow_lower = np.array([18, 100, 150])
        yellow_upper = np.array([32, 255, 255])
        yellow_mask = cv2.inRange(hsv, yellow_lower, yellow_upper)

        # Blue plate mask (China, EU)
        blue_lower = np.array([100, 100, 80])
        blue_upper = np.array([125, 255, 255])
        blue_mask = cv2.inRange(hsv, blue_lower, blue_upper)

        combined_mask = white_mask | yellow_mask | blue_mask

        # Morphological cleanup
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (12, 4))
        cleaned = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(
            cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
            x, y, bw, bh = cv2.boundingRect(contour)
            area_ratio = (bw * bh) / vehicle_area

            if area_ratio < self.min_area_ratio or area_ratio > self.max_area_ratio:
                continue

            if bh == 0:
                continue
            aspect = bw / bh
            if self.min_aspect <= aspect <= self.max_aspect:
                return (x, y, bw, bh)

        return None

    def _score_candidate(self, box, crop):
        """Score a validated candidate (0-1)."""
        x, y, bw, bh = box
        h, w = crop.shape[:2]

        # Position: lower half is better (rear plates)
        pos_score = min((y + bh / 2) / h, 1.0)

        # Aspect ratio: closer to typical plate ratio (3.0-4.0)
        aspect = bw / bh if bh > 0 else 0
        ideal_aspect = 3.5
        aspect_score = max(0, 1.0 - abs(aspect - ideal_aspect) / ideal_aspect)

        # Size: reasonable fraction of vehicle
        area_ratio = (bw * bh) / (w * h)
        size_score = min(area_ratio / 0.02, 1.0) if area_ratio > 0.005 else 0.0

        return pos_score * 0.25 + aspect_score * 0.45 + size_score * 0.30

    def _box_iou(self, box_a, box_b):
        """Compute IoU between two (x, y, w, h) boxes."""
        ax1, ay1, aw, ah = box_a
        bx1, by1, bw, bh = box_b

        ax2, ay2 = ax1 + aw, ay1 + ah
        bx2, by2 = bx1 + bw, by1 + bh

        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)

        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        union = aw * ah + bw * bh - inter

        return inter / union if union > 0 else 0.0

    def _merge_boxes(self, box_a, box_b):
        """Merge two overlapping boxes into their union."""
        ax1, ay1, aw, ah = box_a
        bx1, by1, bw, bh = box_b

        x1 = min(ax1, bx1)
        y1 = min(ay1, by1)
        x2 = max(ax1 + aw, bx1 + bw)
        y2 = max(ay1 + ah, by1 + bh)

        return (x1, y1, x2 - x1, y2 - y1)
