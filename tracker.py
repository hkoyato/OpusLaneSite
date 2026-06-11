"""
DeepSORT-style multi-object tracker with Kalman filter prediction
and appearance-based re-identification.
"""

import numpy as np
from scipy.optimize import linear_sum_assignment


def compute_iou(box_a, box_b):
    """Compute IoU between two boxes [x1, y1, x2, y2]."""
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])

    inter_area = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])

    union_area = area_a + area_b - inter_area
    if union_area == 0:
        return 0.0
    return inter_area / union_area


def bbox_to_z(bbox):
    """Convert [x1, y1, x2, y2] to [cx, cy, area, aspect_ratio]."""
    x1, y1, x2, y2 = bbox
    w = x2 - x1
    h = y2 - y1
    cx = x1 + w / 2.0
    cy = y1 + h / 2.0
    area = w * h
    r = w / float(h) if h > 0 else 1.0
    return np.array([cx, cy, area, r]).reshape((4, 1))


def z_to_bbox(z):
    """Convert [cx, cy, area, aspect_ratio] back to [x1, y1, x2, y2]."""
    cx, cy, area, r = z.flatten()
    w = np.sqrt(area * r)
    h = area / w if w > 0 else 0
    return np.array([
        cx - w / 2.0,
        cy - h / 2.0,
        cx + w / 2.0,
        cy + h / 2.0,
    ])


class KalmanBoxTracker:
    """
    Kalman filter tracker for a single bounding box.

    State vector: [cx, cy, area, aspect_ratio, vx, vy, va]
    Measurement:  [cx, cy, area, aspect_ratio]
    """

    def __init__(self, bbox):
        # State: [cx, cy, s, r, vx, vy, vs]
        self.dim_x = 7
        self.dim_z = 4

        # State transition matrix
        self.F = np.eye(self.dim_x)
        self.F[0, 4] = 1  # cx += vx
        self.F[1, 5] = 1  # cy += vy
        self.F[2, 6] = 1  # s += vs

        # Measurement matrix
        self.H = np.zeros((self.dim_z, self.dim_x))
        self.H[0, 0] = 1
        self.H[1, 1] = 1
        self.H[2, 2] = 1
        self.H[3, 3] = 1

        # Measurement noise
        self.R = np.eye(self.dim_z) * 10.0
        self.R[2, 2] = 100.0  # area has more noise

        # Process noise
        self.Q = np.eye(self.dim_x)
        self.Q[4:, 4:] *= 0.01
        self.Q[2, 2] *= 10.0
        self.Q[6, 6] *= 0.01

        # Covariance
        self.P = np.eye(self.dim_x) * 10.0
        self.P[4:, 4:] *= 1000.0  # high uncertainty for velocities

        # Initial state
        self.x = np.zeros((self.dim_x, 1))
        z = bbox_to_z(bbox)
        self.x[:4] = z

    def predict(self):
        """Predict next state."""
        # Prevent area from going negative
        if self.x[2] + self.x[6] <= 0:
            self.x[6] = 0.0

        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return z_to_bbox(self.x[:4])

    def update(self, bbox):
        """Update state with new measurement."""
        z = bbox_to_z(bbox)
        y = z - self.H @ self.x  # Innovation
        S = self.H @ self.P @ self.H.T + self.R  # Innovation covariance
        K = self.P @ self.H.T @ np.linalg.inv(S)  # Kalman gain

        self.x = self.x + K @ y
        self.P = (np.eye(self.dim_x) - K @ self.H) @ self.P

    def get_state(self):
        """Get current bbox estimate."""
        return z_to_bbox(self.x[:4])


class TrackedVehicle:
    """Represents a single tracked vehicle with Kalman filter."""

    def __init__(self, vehicle_id, bbox, frame_idx, plate_bbox=None):
        self.vehicle_id = vehicle_id
        self.bbox = bbox
        self.plate_bbox = plate_bbox
        self.plate_text = ""
        self.plate_confidence = 0.0
        self.first_frame = frame_idx
        self.last_frame = frame_idx
        self.frames_since_seen = 0
        self.hit_count = 1
        self.kalman = KalmanBoxTracker(bbox)

        # Appearance feature history for re-id
        self.appearance_features = []
        self._max_features = 30

    def predict(self):
        """Predict next position using Kalman filter."""
        predicted_bbox = self.kalman.predict()
        self.bbox = tuple(predicted_bbox.astype(int))
        self.frames_since_seen += 1

    def update(self, bbox, frame_idx, plate_bbox=None):
        """Update track with new detection."""
        self.kalman.update(bbox)
        self.bbox = bbox
        self.last_frame = frame_idx
        self.frames_since_seen = 0
        self.hit_count += 1
        if plate_bbox is not None:
            self.plate_bbox = plate_bbox

    def update_plate_text(self, text, confidence):
        """Update plate text if new reading has higher confidence."""
        if confidence > self.plate_confidence:
            self.plate_text = text
            self.plate_confidence = confidence

    def add_appearance(self, feature):
        """Store appearance feature for re-identification."""
        self.appearance_features.append(feature)
        if len(self.appearance_features) > self._max_features:
            self.appearance_features.pop(0)

    def get_appearance_similarity(self, feature):
        """Compute cosine similarity between feature and stored history."""
        if not self.appearance_features or feature is None:
            return 0.0

        similarities = []
        for stored in self.appearance_features:
            sim = np.dot(feature, stored) / (
                np.linalg.norm(feature) * np.linalg.norm(stored) + 1e-6
            )
            similarities.append(sim)

        return max(similarities)


class VehicleTracker:
    """
    DeepSORT-style tracker with Kalman filter prediction
    and optional appearance-based matching.

    Parameters
    ----------
    iou_threshold : float
        Minimum IoU for matching detections to tracks.
    max_lost : int
        Max frames a track survives without matches.
    min_hits : int
        Minimum detections before a track is considered confirmed.
    appearance_weight : float
        Weight for appearance similarity in cost (0 = IoU only, 1 = appearance only).
    """

    def __init__(
        self,
        iou_threshold=0.3,
        max_lost=30,
        min_hits=3,
        appearance_weight=0.3,
    ):
        self.iou_threshold = iou_threshold
        self.max_lost = max_lost
        self.min_hits = min_hits
        self.appearance_weight = appearance_weight
        self.tracks: list[TrackedVehicle] = []
        self.next_id = 1
        self.finished_tracks: list[TrackedVehicle] = []

    def update(self, detections, frame_idx, features=None):
        """
        Update tracks with new detections.

        Parameters
        ----------
        detections : list of dict
            Each dict has keys: 'bbox', 'plate_bbox' (or None).
        frame_idx : int
            Current frame index.
        features : list of np.ndarray or None
            Appearance feature vectors for each detection (optional).

        Returns
        -------
        list of TrackedVehicle
            Active tracks after update.
        """
        # Predict new positions for all tracks
        for track in self.tracks:
            track.predict()

        if not detections:
            self._remove_lost_tracks()
            return self._get_confirmed_tracks()

        detection_bboxes = [d["bbox"] for d in detections]
        n_tracks = len(self.tracks)
        n_dets = len(detections)

        if n_tracks == 0:
            # No existing tracks, create new ones
            for d_idx, det in enumerate(detections):
                self._create_track(det, frame_idx, features, d_idx)
            return self._get_confirmed_tracks()

        # Build cost matrix combining IoU and appearance
        cost_matrix = np.zeros((n_tracks, n_dets))

        for t_idx, track in enumerate(self.tracks):
            for d_idx, det_bbox in enumerate(detection_bboxes):
                iou = compute_iou(track.bbox, det_bbox)
                iou_cost = 1.0 - iou

                # Appearance cost
                app_cost = 1.0
                if (
                    features is not None
                    and features[d_idx] is not None
                    and track.appearance_features
                ):
                    app_sim = track.get_appearance_similarity(features[d_idx])
                    app_cost = 1.0 - app_sim

                # Combined cost
                w = self.appearance_weight
                cost_matrix[t_idx, d_idx] = (1 - w) * iou_cost + w * app_cost

        # Hungarian algorithm for optimal assignment
        row_indices, col_indices = linear_sum_assignment(cost_matrix)

        matched_tracks = set()
        matched_detections = set()

        for t_idx, d_idx in zip(row_indices, col_indices):
            # Check if match is acceptable (IoU gate)
            iou = compute_iou(self.tracks[t_idx].bbox, detection_bboxes[d_idx])
            if iou < self.iou_threshold:
                continue

            self.tracks[t_idx].update(
                detection_bboxes[d_idx],
                frame_idx,
                detections[d_idx].get("plate_bbox"),
            )
            # Store appearance feature
            if features is not None and features[d_idx] is not None:
                self.tracks[t_idx].add_appearance(features[d_idx])

            matched_tracks.add(t_idx)
            matched_detections.add(d_idx)

        # Create new tracks for unmatched detections
        for d_idx in range(n_dets):
            if d_idx not in matched_detections:
                self._create_track(detections[d_idx], frame_idx, features, d_idx)

        self._remove_lost_tracks()
        return self._get_confirmed_tracks()

    def _create_track(self, detection, frame_idx, features, d_idx):
        """Create a new track from a detection."""
        new_track = TrackedVehicle(
            vehicle_id=self.next_id,
            bbox=detection["bbox"],
            frame_idx=frame_idx,
            plate_bbox=detection.get("plate_bbox"),
        )
        if features is not None and features[d_idx] is not None:
            new_track.add_appearance(features[d_idx])
        self.tracks.append(new_track)
        self.next_id += 1

    def _remove_lost_tracks(self):
        """Move lost tracks to finished list."""
        still_active = []
        for track in self.tracks:
            if track.frames_since_seen > self.max_lost:
                self.finished_tracks.append(track)
            else:
                still_active.append(track)
        self.tracks = still_active

    def _get_confirmed_tracks(self):
        """Return only tracks that have enough hits to be confirmed."""
        return [t for t in self.tracks if t.hit_count >= self.min_hits]

    def get_all_tracks(self):
        """Return all tracks (active + finished) that were confirmed."""
        all_tracks = self.tracks + self.finished_tracks
        return [t for t in all_tracks if t.hit_count >= self.min_hits]
