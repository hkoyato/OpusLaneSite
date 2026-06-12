"""
Adaptive detection controller for Rekognition.

Dynamically adjusts detection interval and image resolution based on:
- Vehicle count changes (new vehicles entering/leaving)
- Movement intensity (how much vehicles are moving)
- Scene stability (steady queue vs active traffic)

Goal: minimize API calls when nothing is happening, increase frequency
when the scene is changing rapidly.
"""

import numpy as np
from collections import deque


class AdaptiveController:
    """
    Dynamically adjusts detection parameters based on scene activity.

    When the scene is stable (no new vehicles, minimal movement), detection
    interval increases and resolution decreases to save API calls.
    When activity spikes (vehicles entering/leaving, fast movement),
    interval shrinks and resolution increases for accuracy.

    Parameters
    ----------
    min_interval : int
        Minimum detection interval (frames). Never faster than this.
    max_interval : int
        Maximum detection interval (frames). Never slower than this.
    min_resolution : int
        Minimum image dimension for API upload (pixels).
    max_resolution : int
        Maximum image dimension for API upload (pixels).
    sensitivity : float
        How quickly to react to changes (0-1). Higher = more reactive.
    """

    def __init__(
        self,
        min_interval=1,
        max_interval=30,
        min_resolution=640,
        max_resolution=1920,
        sensitivity=0.5,
    ):
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.min_resolution = min_resolution
        self.max_resolution = max_resolution
        self.sensitivity = sensitivity

        # Current adaptive values — START AGGRESSIVE
        # Begin at minimum interval (every frame) to catch vehicles immediately.
        # Only relax once the scene is confirmed stable.
        self.current_interval = min_interval
        self.current_resolution = max_resolution

        # Activity tracking
        self._prev_vehicle_count = 0
        self._prev_bboxes = []
        self._activity_history = deque(maxlen=30)  # Last 30 decisions
        self._count_change_history = deque(maxlen=10)
        self._movement_history = deque(maxlen=10)
        self._frames_processed = 0
        self._warmup_frames = 60  # Stay aggressive for first 60 frames (~2-3s)

        # Thresholds
        self._high_activity_threshold = 0.4
        self._low_activity_threshold = 0.15

    def update(self, active_tracks):
        """
        Analyze current scene and update detection parameters.

        Call this every frame (cheap — just math on track data).

        Parameters
        ----------
        active_tracks : list of TrackedVehicle
            Currently active tracks from the tracker.

        Returns
        -------
        dict
            {
                'detect_interval': int,
                'resolution': int,
                'reason': str,  # Human-readable reason for current settings
            }
        """
        self._frames_processed += 1

        # Calculate activity metrics
        current_count = len([t for t in active_tracks if t.frames_since_seen == 0])
        count_change = abs(current_count - self._prev_vehicle_count)
        movement = self._calculate_movement(active_tracks)

        self._count_change_history.append(count_change)
        self._movement_history.append(movement)

        # WARMUP PHASE: stay at minimum interval until we've seen enough frames
        # to understand the scene. This prevents missing vehicles at the start.
        if self._frames_processed < self._warmup_frames:
            # Still track activity during warmup so the transition is smooth
            activity_score = self._compute_activity_score(
                current_count, count_change, movement
            )
            self._activity_history.append(activity_score)

            self._prev_vehicle_count = current_count
            self._prev_bboxes = [
                t.bbox for t in active_tracks if t.frames_since_seen == 0
            ]
            reason = f"WARMUP ({self._frames_processed}/{self._warmup_frames}) | interval={self.current_interval}f | vehicles={current_count}"
            return {
                "detect_interval": self.current_interval,
                "resolution": self.current_resolution,
                "reason": reason,
            }

        # INSTANT REACT: if vehicles just appeared (0 → N), go to max frequency
        instant_react = (self._prev_vehicle_count == 0 and current_count > 0)
        if instant_react:
            self.current_interval = self.min_interval
            self.current_resolution = self.max_resolution
            self._activity_history.clear()  # Reset history on major change

        # Compute activity score (0 = dead calm, 1 = maximum activity)
        activity_score = self._compute_activity_score(
            current_count, count_change, movement
        )
        self._activity_history.append(activity_score)

        # Smooth activity over recent history to avoid jitter
        smoothed_activity = np.mean(self._activity_history)

        # Skip adaptive computation on instant react frame — keep min interval
        if not instant_react:
            if current_count > 0:
                # Vehicles present: never go above moderate interval
                max_allowed = min(self.max_interval, max(self.min_interval * 5, 10))
                self.current_interval = self._compute_interval(smoothed_activity)
                self.current_interval = min(self.current_interval, max_allowed)
                # Keep resolution at least moderate when vehicles are being tracked
                self.current_resolution = self._compute_resolution(smoothed_activity)
                self.current_resolution = max(self.current_resolution, 960)
            else:
                # No vehicles: can relax fully
                self.current_interval = self._compute_interval(smoothed_activity)
                self.current_resolution = self._compute_resolution(smoothed_activity)
        # else: instant_react keeps min_interval and max_resolution as set above

        # Store state for next frame
        self._prev_vehicle_count = current_count
        self._prev_bboxes = [
            t.bbox for t in active_tracks if t.frames_since_seen == 0
        ]

        reason = self._describe_state(smoothed_activity, current_count, movement)

        return {
            "detect_interval": self.current_interval,
            "resolution": self.current_resolution,
            "reason": reason,
        }

    def should_detect(self, frame_idx):
        """Check if detection should run on this frame."""
        return frame_idx % self.current_interval == 0

    def get_resolution(self):
        """Get current target resolution for API upload."""
        return self.current_resolution

    def _calculate_movement(self, active_tracks):
        """
        Calculate average movement of tracked vehicles (pixels/frame).
        Higher movement = more activity = need more frequent detection.
        """
        if not self._prev_bboxes or not active_tracks:
            return 0.0

        movements = []
        current_bboxes = [
            t.bbox for t in active_tracks if t.frames_since_seen == 0
        ]

        for curr_bbox in current_bboxes:
            curr_cx = (curr_bbox[0] + curr_bbox[2]) / 2
            curr_cy = (curr_bbox[1] + curr_bbox[3]) / 2

            # Find closest previous bbox (simple nearest-neighbor)
            min_dist = float("inf")
            for prev_bbox in self._prev_bboxes:
                prev_cx = (prev_bbox[0] + prev_bbox[2]) / 2
                prev_cy = (prev_bbox[1] + prev_bbox[3]) / 2
                dist = np.sqrt((curr_cx - prev_cx) ** 2 + (curr_cy - prev_cy) ** 2)
                min_dist = min(min_dist, dist)

            if min_dist < float("inf"):
                movements.append(min_dist)

        return np.mean(movements) if movements else 0.0

    def _compute_activity_score(self, current_count, count_change, movement):
        """
        Compute overall activity score (0-1).

        Factors:
        - Count changes (vehicles entering/leaving) — strong signal
        - Movement intensity — moderate signal
        - Absolute vehicle count — weak signal (more vehicles = more to track)
        """
        # Count change score (0-1): any change is significant
        count_score = min(count_change / 3.0, 1.0)

        # Movement score (0-1): normalized by typical pixel movement
        # >30px/frame is fast, <5px/frame is stationary
        movement_score = min(movement / 30.0, 1.0)

        # Density score (0-1): more vehicles need more attention
        density_score = min(current_count / 10.0, 1.0)

        # Weighted combination
        activity = (
            count_score * 0.5 +      # Count changes matter most
            movement_score * 0.35 +   # Movement matters
            density_score * 0.15      # Density is a minor factor
        )

        return min(activity, 1.0)

    def _compute_interval(self, activity_score):
        """Map activity score to detection interval."""
        # High activity → low interval (frequent detection)
        # Low activity → high interval (save API calls)
        # Apply sensitivity: higher sensitivity = more reactive
        adjusted = activity_score ** (1.0 / (self.sensitivity + 0.1))

        # Inverse mapping: activity 1.0 → min_interval, activity 0.0 → max_interval
        interval_range = self.max_interval - self.min_interval
        interval = self.max_interval - int(adjusted * interval_range)

        return max(self.min_interval, min(self.max_interval, interval))

    def _compute_resolution(self, activity_score):
        """Map activity score to upload resolution."""
        # High activity → high resolution (need accuracy)
        # Low activity → low resolution (save bandwidth)
        res_range = self.max_resolution - self.min_resolution
        resolution = self.min_resolution + int(activity_score * res_range)

        # Round to nearest 64 for clean scaling
        resolution = (resolution // 64) * 64
        return max(self.min_resolution, min(self.max_resolution, resolution))

    def _describe_state(self, activity, count, movement):
        """Human-readable description of current adaptive state."""
        if activity > self._high_activity_threshold:
            state = "HIGH ACTIVITY"
        elif activity < self._low_activity_threshold:
            state = "LOW ACTIVITY"
        else:
            state = "MODERATE"

        return (
            f"{state} | interval={self.current_interval}f "
            f"res={self.current_resolution}px | "
            f"vehicles={count} movement={movement:.0f}px"
        )
