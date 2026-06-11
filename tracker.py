"""
DeepSORT-style multi-object tracker with Kalman filter prediction,
appearance-based re-identification, and occlusion-aware track management.

Key design to avoid duplicate counting during occlusions:
- Tracks survive much longer without detections (configurable max_lost)
- Recently finished tracks are kept in a "gallery" for re-identification
- New detections are matched against the gallery using appearance + plate text
- If a match is found, the old track is revived instead of creating a duplicate
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
    w = np.sqrt(max(area * r, 0))
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
        self.R[2, 2] = 100.0

        # Process noise
        self.Q = np.eye(self.dim_x)
        self.Q[4:, 4:] *= 0.01
        self.Q[2, 2] *= 10.0
        self.Q[6, 6] *= 0.01

        # Covariance
        self.P = np.eye(self.dim_x) * 10.0
        self.P[4:, 4:] *= 1000.0

        # Initial state
        self.x = np.zeros((self.dim_x, 1))
        z = bbox_to_z(bbox)
        self.x[:4] = z

    def predict(self):
        """Predict next state."""
        if self.x[2] + self.x[6] <= 0:
            self.x[6] = 0.0
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return z_to_bbox(self.x[:4])

    def update(self, bbox):
        """Update state with new measurement."""
        z = bbox_to_z(bbox)
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(self.dim_x) - K @ self.H) @ self.P

    def get_state(self):
        """Get current bbox estimate."""
        return z_to_bbox(self.x[:4])


class TrackedVehicle:
    """Represents a single tracked vehicle with Kalman filter and re-ID features."""

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
        self._max_features = 50

        # Track state
        self.is_occluded = False
        self.occlusion_count = 0  # How many times this track was occluded and recovered

    def predict(self):
        """Predict next position using Kalman filter."""
        predicted_bbox = self.kalman.predict()
        self.bbox = tuple(predicted_bbox.astype(int))
        self.frames_since_seen += 1
        # Mark as potentially occluded after several missing frames
        if self.frames_since_seen > 5:
            self.is_occluded = True

    def update(self, bbox, frame_idx, plate_bbox=None):
        """Update track with new detection."""
        self.kalman.update(bbox)
        self.bbox = bbox
        self.last_frame = frame_idx
        if self.is_occluded:
            self.occlusion_count += 1
            self.is_occluded = False
        self.frames_since_seen = 0
        self.hit_count += 1
        if plate_bbox is not None:
            self.plate_bbox = plate_bbox

    def revive(self, bbox, frame_idx, plate_bbox=None):
        """Revive a finished track with a new detection (re-identification)."""
        self.kalman = KalmanBoxTracker(bbox)
        self.bbox = bbox
        self.last_frame = frame_idx
        self.frames_since_seen = 0
        self.is_occluded = False
        self.occlusion_count += 1
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
        if feature is None:
            return
        self.appearance_features.append(feature)
        if len(self.appearance_features) > self._max_features:
            self.appearance_features.pop(0)

    def get_appearance_similarity(self, feature):
        """Compute cosine similarity between feature and stored history."""
        if not self.appearance_features or feature is None:
            return 0.0

        similarities = []
        for stored in self.appearance_features:
            norm_a = np.linalg.norm(feature)
            norm_b = np.linalg.norm(stored)
            if norm_a < 1e-6 or norm_b < 1e-6:
                continue
            sim = np.dot(feature, stored) / (norm_a * norm_b)
            similarities.append(sim)

        return max(similarities) if similarities else 0.0

    def get_avg_appearance(self):
        """Get average appearance feature (for gallery matching)."""
        if not self.appearance_features:
            return None
        avg = np.mean(self.appearance_features, axis=0)
        norm = np.linalg.norm(avg)
        if norm > 0:
            avg /= norm
        return avg


class VehicleTracker:
    """
    DeepSORT-style tracker with occlusion-aware re-identification.

    When a vehicle is occluded and the track is lost, it moves to a "gallery"
    of recently finished tracks. New unmatched detections are compared against
    the gallery using appearance similarity and plate text. If a strong match
    is found, the old track is revived instead of creating a duplicate.

    Parameters
    ----------
    iou_threshold : float
        Minimum IoU for matching detections to active tracks.
    max_lost : int
        Max frames a track survives without detections before moving to gallery.
    min_hits : int
        Minimum detections before a track is considered confirmed.
    appearance_weight : float
        Weight for appearance in combined cost (0=IoU only, 1=appearance only).
    reid_threshold : float
        Minimum appearance similarity to re-identify a vehicle from gallery.
    gallery_max_age : int
        Max frames a track stays in the gallery before permanent removal.
    """

    def __init__(
        self,
        iou_threshold=0.3,
        max_lost=60,
        min_hits=3,
        appearance_weight=0.4,
        reid_threshold=0.5,
        gallery_max_age=300,
    ):
        self.iou_threshold = iou_threshold
        self.max_lost = max_lost
        self.min_hits = min_hits
        self.appearance_weight = appearance_weight
        self.reid_threshold = reid_threshold
        self.gallery_max_age = gallery_max_age

        self.tracks: list[TrackedVehicle] = []
        self.next_id = 1

        # Gallery: recently lost tracks available for re-identification
        self.gallery: list[TrackedVehicle] = []
        # Permanently finished (left camera or too old for re-id)
        self.finished_tracks: list[TrackedVehicle] = []

    def update(self, detections, frame_idx, features=None):
        """
        Update tracks with new detections.

        Three-stage matching:
        1. Match detections to active tracks (IoU + appearance)
        2. Match remaining detections to gallery tracks (appearance + plate re-ID)
        3. Create new tracks only for truly unmatched detections

        Parameters
        ----------
        detections : list of dict
            Each dict has keys: 'bbox', 'plate_bbox' (or None).
        frame_idx : int
            Current frame index.
        features : list of np.ndarray or None
            Appearance feature vectors for each detection.

        Returns
        -------
        list of TrackedVehicle
            Active confirmed tracks after update.
        """
        # Predict new positions for all active tracks
        for track in self.tracks:
            track.predict()

        if not detections:
            self._manage_lost_tracks(frame_idx)
            return self._get_confirmed_tracks()

        detection_bboxes = [d["bbox"] for d in detections]
        n_dets = len(detections)

        # === Stage 1: Match detections to active tracks ===
        matched_detections = set()

        if self.tracks:
            matched_tracks_set, matched_dets_set = self._match_active_tracks(
                detections, detection_bboxes, features, frame_idx
            )
            matched_detections = matched_dets_set

        # === Stage 2: Re-identify unmatched detections against gallery ===
        unmatched_det_indices = [
            i for i in range(n_dets) if i not in matched_detections
        ]

        if unmatched_det_indices and self.gallery:
            revived_dets = self._match_gallery(
                detections, detection_bboxes, features,
                unmatched_det_indices, frame_idx
            )
            matched_detections.update(revived_dets)

        # === Stage 3: Create new tracks for remaining unmatched detections ===
        for d_idx in range(n_dets):
            if d_idx not in matched_detections:
                self._create_track(detections[d_idx], frame_idx, features, d_idx)

        self._manage_lost_tracks(frame_idx)
        return self._get_confirmed_tracks()

    def _match_active_tracks(
        self, detections, detection_bboxes, features, frame_idx
    ):
        """Stage 1: Match detections to active tracks using IoU + appearance."""
        n_tracks = len(self.tracks)
        n_dets = len(detections)

        cost_matrix = np.full((n_tracks, n_dets), 1e5)

        for t_idx, track in enumerate(self.tracks):
            for d_idx, det_bbox in enumerate(detection_bboxes):
                iou = compute_iou(track.bbox, det_bbox)

                # Gate: skip if IoU is too low (not even close)
                if iou < 0.05:
                    continue

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

                w = self.appearance_weight
                cost_matrix[t_idx, d_idx] = (1 - w) * iou_cost + w * app_cost

        # Hungarian assignment
        row_indices, col_indices = linear_sum_assignment(cost_matrix)

        matched_tracks = set()
        matched_detections = set()

        for t_idx, d_idx in zip(row_indices, col_indices):
            # Accept match if cost is reasonable
            if cost_matrix[t_idx, d_idx] > 0.8:
                continue

            self.tracks[t_idx].update(
                detection_bboxes[d_idx],
                frame_idx,
                detections[d_idx].get("plate_bbox"),
            )
            if features is not None and features[d_idx] is not None:
                self.tracks[t_idx].add_appearance(features[d_idx])

            matched_tracks.add(t_idx)
            matched_detections.add(d_idx)

        return matched_tracks, matched_detections

    def _match_gallery(
        self, detections, detection_bboxes, features,
        unmatched_det_indices, frame_idx
    ):
        """
        Stage 2: Try to re-identify unmatched detections against gallery.

        Uses appearance similarity + plate text matching to find vehicles
        that reappeared after occlusion.
        """
        revived_detections = set()

        if not self.gallery:
            return revived_detections

        n_gallery = len(self.gallery)
        n_unmatched = len(unmatched_det_indices)

        # Build re-ID cost matrix
        reid_cost = np.full((n_gallery, n_unmatched), 1e5)

        for g_idx, gallery_track in enumerate(self.gallery):
            for u_idx, d_idx in enumerate(unmatched_det_indices):
                score = 0.0
                score_count = 0

                # Appearance similarity
                if (
                    features is not None
                    and features[d_idx] is not None
                    and gallery_track.appearance_features
                ):
                    app_sim = gallery_track.get_appearance_similarity(
                        features[d_idx]
                    )
                    score += app_sim
                    score_count += 1

                # Plate text similarity (strong signal if both have plate text)
                if gallery_track.plate_text:
                    # We'll check plate text after OCR runs, but for now
                    # use spatial proximity as additional cue
                    pass

                # Spatial proximity: vehicle shouldn't teleport
                # Use relaxed IoU or center distance
                det_bbox = detection_bboxes[d_idx]
                last_bbox = gallery_track.bbox
                center_dist = self._center_distance(det_bbox, last_bbox)
                frame_gap = frame_idx - gallery_track.last_frame

                # Max reasonable movement: scale with time gap
                # Assume max ~50 pixels per frame of movement
                max_dist = min(frame_gap * 50, 500)
                if center_dist < max_dist:
                    spatial_sim = 1.0 - (center_dist / max_dist)
                    score += spatial_sim * 0.5
                    score_count += 1

                # Size similarity
                size_sim = self._size_similarity(det_bbox, last_bbox)
                score += size_sim * 0.3
                score_count += 1

                if score_count > 0:
                    avg_score = score / score_count
                    reid_cost[g_idx, u_idx] = 1.0 - avg_score

        # Hungarian assignment for re-ID
        if n_gallery > 0 and n_unmatched > 0:
            row_indices, col_indices = linear_sum_assignment(reid_cost)

            for g_idx, u_idx in zip(row_indices, col_indices):
                cost = reid_cost[g_idx, u_idx]
                # Only accept if similarity is above threshold
                similarity = 1.0 - cost
                if similarity < self.reid_threshold:
                    continue

                d_idx = unmatched_det_indices[u_idx]
                gallery_track = self.gallery[g_idx]

                # Revive the gallery track
                gallery_track.revive(
                    detection_bboxes[d_idx],
                    frame_idx,
                    detections[d_idx].get("plate_bbox"),
                )
                if features is not None and features[d_idx] is not None:
                    gallery_track.add_appearance(features[d_idx])

                # Move back to active tracks
                self.tracks.append(gallery_track)
                revived_detections.add(d_idx)

            # Remove revived tracks from gallery
            revived_ids = {
                self.gallery[g_idx].vehicle_id
                for g_idx, u_idx in zip(row_indices, col_indices)
                if (1.0 - reid_cost[g_idx, u_idx]) >= self.reid_threshold
            }
            self.gallery = [
                t for t in self.gallery if t.vehicle_id not in revived_ids
            ]

        return revived_detections

    def _center_distance(self, bbox_a, bbox_b):
        """Euclidean distance between centers of two bboxes."""
        cx_a = (bbox_a[0] + bbox_a[2]) / 2
        cy_a = (bbox_a[1] + bbox_a[3]) / 2
        cx_b = (bbox_b[0] + bbox_b[2]) / 2
        cy_b = (bbox_b[1] + bbox_b[3]) / 2
        return np.sqrt((cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2)

    def _size_similarity(self, bbox_a, bbox_b):
        """Compute size similarity between two bboxes (0-1)."""
        area_a = (bbox_a[2] - bbox_a[0]) * (bbox_a[3] - bbox_a[1])
        area_b = (bbox_b[2] - bbox_b[0]) * (bbox_b[3] - bbox_b[1])
        if area_a == 0 or area_b == 0:
            return 0.0
        ratio = min(area_a, area_b) / max(area_a, area_b)
        return ratio

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

    def _manage_lost_tracks(self, frame_idx):
        """
        Move lost tracks to gallery, and age out old gallery entries.

        Tracks that exceed max_lost go to gallery for re-ID.
        Gallery tracks that exceed gallery_max_age are permanently finished.
        """
        still_active = []
        for track in self.tracks:
            if track.frames_since_seen > self.max_lost:
                # Move to gallery for potential re-identification
                self.gallery.append(track)
            else:
                still_active.append(track)
        self.tracks = still_active

        # Age out old gallery entries
        still_in_gallery = []
        for track in self.gallery:
            age = frame_idx - track.last_frame
            if age > self.gallery_max_age:
                self.finished_tracks.append(track)
            else:
                still_in_gallery.append(track)
        self.gallery = still_in_gallery

    def _get_confirmed_tracks(self):
        """Return only tracks that have enough hits to be confirmed."""
        return [t for t in self.tracks if t.hit_count >= self.min_hits]

    def get_all_tracks(self):
        """Return all confirmed tracks (active + gallery + finished)."""
        all_tracks = self.tracks + self.gallery + self.finished_tracks
        return [t for t in all_tracks if t.hit_count >= self.min_hits]
