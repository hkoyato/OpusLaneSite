"""
Dedicated license plate detection module.
Uses contour-based detection as a robust fallback when no YOLO plate model
is available. Much more accurate than a fixed heuristic region.
"""

import cv2
import numpy as np


class PlateDetector:
    """
    Detects license plate regions within a vehicle crop using
    image processing techniques (edge detection + contour analysis).

    This is significantly more accurate than a fixed heuristic because
    it actually looks for rectangular, high-contrast regions typical of
    license plates.

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
    """

    def __init__(
        self,
        min_area_ratio=0.005,
        max_area_ratio=0.15,
        min_aspect=1.5,
        max_aspect=6.0,
    ):
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio
        self.min_aspect = min_aspect
        self.max_aspect = max_aspect

    def detect(self, vehicle_crop):
        """
        Detect license plate region within a vehicle crop.

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

        candidates = []

        # Method 1: Edge-based detection
        result = self._edge_based_detection(vehicle_crop)
        if result is not None:
            candidates.append(result)

        # Method 2: Morphology-based detection
        result = self._morph_based_detection(vehicle_crop)
        if result is not None:
            candidates.append(result)

        # Method 3: Color-based detection (for plates with distinct colors)
        result = self._color_based_detection(vehicle_crop)
        if result is not None:
            candidates.append(result)

        if not candidates:
            # Final fallback: bottom-center heuristic but tighter
            return self._tight_heuristic(vehicle_crop)

        # Score candidates and return best
        best = self._score_candidates(candidates, vehicle_crop)
        return best

    def _edge_based_detection(self, crop):
        """Detect plate using Canny edges + contour approximation."""
        h, w = crop.shape[:2]
        vehicle_area = h * w

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # Bilateral filter to smooth while preserving edges
        gray = cv2.bilateralFilter(gray, 11, 17, 17)

        # Canny edge detection
        edges = cv2.Canny(gray, 30, 200)

        # Dilate to connect nearby edges
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=1)

        # Find contours
        contours, _ = cv2.findContours(
            edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )

        plate_candidates = []
        for contour in contours:
            area = cv2.contourArea(contour)
            area_ratio = area / vehicle_area

            if area_ratio < self.min_area_ratio or area_ratio > self.max_area_ratio:
                continue

            # Approximate contour to polygon
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

            # Plates are roughly rectangular (4 corners)
            if 4 <= len(approx) <= 6:
                x, y, bw, bh = cv2.boundingRect(approx)
                if bh == 0:
                    continue
                aspect = bw / bh

                if self.min_aspect <= aspect <= self.max_aspect:
                    # Prefer candidates in lower half of vehicle
                    position_score = y / h  # Higher = lower in image = better
                    plate_candidates.append((x, y, bw, bh, position_score))

        if not plate_candidates:
            return None

        # Best candidate: good position (lower half) + reasonable size
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

        # Threshold
        _, thresh = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Close to connect characters into a blob
        close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 5))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, close_kernel)

        # Find contours of text-dense regions
        contours, _ = cv2.findContours(
            closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        for contour in sorted(contours, key=cv2.contourArea, reverse=True):
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
        """Detect plate based on color (white/yellow plates common in many countries)."""
        h, w = crop.shape[:2]
        vehicle_area = h * w
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        # White plate mask
        white_lower = np.array([0, 0, 180])
        white_upper = np.array([180, 50, 255])
        white_mask = cv2.inRange(hsv, white_lower, white_upper)

        # Yellow plate mask
        yellow_lower = np.array([15, 80, 150])
        yellow_upper = np.array([35, 255, 255])
        yellow_mask = cv2.inRange(hsv, yellow_lower, yellow_upper)

        # Blue plate mask (common in China, EU)
        blue_lower = np.array([100, 80, 80])
        blue_upper = np.array([130, 255, 255])
        blue_mask = cv2.inRange(hsv, blue_lower, blue_upper)

        combined_mask = white_mask | yellow_mask | blue_mask

        # Clean up mask
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
        cleaned = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(
            cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        for contour in sorted(contours, key=cv2.contourArea, reverse=True):
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

    def _tight_heuristic(self, crop):
        """Tighter heuristic fallback - bottom 40%, center 50%."""
        h, w = crop.shape[:2]
        x = int(w * 0.25)
        y = int(h * 0.6)
        bw = int(w * 0.5)
        bh = int(h * 0.25)
        return (x, y, bw, bh)

    def _score_candidates(self, candidates, crop):
        """Score and select the best plate candidate."""
        h, w = crop.shape[:2]
        best_score = -1
        best = candidates[0]

        for (x, y, bw, bh) in candidates:
            # Position score: lower in image is better for rear plates
            pos_score = (y + bh / 2) / h

            # Aspect ratio score: closer to 3.0 (typical plate) is better
            aspect = bw / bh if bh > 0 else 0
            aspect_score = 1.0 - abs(aspect - 3.5) / 3.5
            aspect_score = max(0, aspect_score)

            # Size score: not too small, not too big
            area_ratio = (bw * bh) / (w * h)
            size_score = min(area_ratio / 0.03, 1.0)

            score = pos_score * 0.3 + aspect_score * 0.4 + size_score * 0.3
            if score > best_score:
                best_score = score
                best = (x, y, bw, bh)

        return best
