"""
Appearance feature extractor for vehicle re-identification.
Uses color histograms and simple CNN features for matching vehicles
across frames even after brief occlusions.
"""

import cv2
import numpy as np


class AppearanceExtractor:
    """
    Extracts appearance features from vehicle crops for re-identification.

    Uses a combination of:
    - Color histogram in HSV space (robust to lighting changes)
    - Spatial color distribution (divides vehicle into grid cells)

    Parameters
    ----------
    feature_dim : int
        Dimensionality of the output feature vector.
    grid_size : tuple
        (rows, cols) grid to divide the vehicle crop for spatial features.
    """

    def __init__(self, feature_dim=128, grid_size=(4, 4)):
        self.feature_dim = feature_dim
        self.grid_size = grid_size

    def extract(self, frame, bbox):
        """
        Extract appearance feature vector from a vehicle bounding box.

        Parameters
        ----------
        frame : np.ndarray
            Full BGR frame.
        bbox : tuple
            (x1, y1, x2, y2) bounding box.

        Returns
        -------
        np.ndarray or None
            Normalized feature vector of shape (feature_dim,), or None if invalid.
        """
        x1, y1, x2, y2 = [int(c) for c in bbox]
        h, w = frame.shape[:2]

        # Clamp to frame bounds
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
            return None

        # Resize to standard size for consistent features
        crop_resized = cv2.resize(crop, (64, 128))
        hsv = cv2.cvtColor(crop_resized, cv2.COLOR_BGR2HSV)

        features = []

        # Spatial grid color histograms
        rows, cols = self.grid_size
        cell_h = 128 // rows
        cell_w = 64 // cols

        for r in range(rows):
            for c in range(cols):
                cell = hsv[
                    r * cell_h : (r + 1) * cell_h,
                    c * cell_w : (c + 1) * cell_w,
                ]
                # H channel histogram (16 bins)
                hist_h = cv2.calcHist(
                    [cell], [0], None, [8], [0, 180]
                ).flatten()
                # S channel histogram (8 bins)
                hist_s = cv2.calcHist(
                    [cell], [1], None, [4], [0, 256]
                ).flatten()

                features.extend(hist_h)
                features.extend(hist_s)

        feature_vec = np.array(features, dtype=np.float32)

        # Normalize to unit length
        norm = np.linalg.norm(feature_vec)
        if norm > 0:
            feature_vec /= norm

        # Truncate or pad to fixed dimension
        if len(feature_vec) > self.feature_dim:
            feature_vec = feature_vec[: self.feature_dim]
        elif len(feature_vec) < self.feature_dim:
            feature_vec = np.pad(
                feature_vec, (0, self.feature_dim - len(feature_vec))
            )

        return feature_vec

    def extract_batch(self, frame, bboxes):
        """
        Extract features for multiple bounding boxes.

        Parameters
        ----------
        frame : np.ndarray
            Full BGR frame.
        bboxes : list of tuple
            List of (x1, y1, x2, y2) bounding boxes.

        Returns
        -------
        list of np.ndarray or None
            Feature vectors for each bbox.
        """
        return [self.extract(frame, bbox) for bbox in bboxes]
