"""
Vehicle Wait Time Analyzer

Processes a video to detect vehicles, locate license plates, read plate text
via OCR, track vehicles using DeepSORT (Kalman + appearance), and calculate
how long each vehicle is visible in the camera (wait time).
"""

import argparse
import cv2
import numpy as np

from detector import VehicleDetector
from detector_rekognition import RekognitionDetector
from tracker import VehicleTracker
from ocr import PlateOCR, PlateTextAggregator
from appearance import AppearanceExtractor
from plate_utils import plates_are_similar, normalize_plate, edit_distance, pick_best_plate


def _resize_for_display(frame, target_width):
    """Resize frame to target width while maintaining aspect ratio."""
    h, w = frame.shape[:2]
    if w == target_width:
        return frame
    scale = target_width / w
    target_height = int(h * scale)
    return cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)


def _deduplicate_by_plate(tracks):
    """
    Merge tracks that have the same or similar plate text.
    Uses fuzzy matching from plate_utils to handle OCR errors.
    """
    plate_tracks = []
    no_plate_tracks = []

    for track in tracks:
        if track.plate_text and len(track.plate_text) >= 3:
            plate_tracks.append(track)
        else:
            no_plate_tracks.append(track)

    if not plate_tracks:
        return tracks

    groups = []
    used = set()

    plate_tracks.sort(key=lambda t: t.plate_confidence, reverse=True)

    for i, track in enumerate(plate_tracks):
        if i in used:
            continue
        group = [track]
        used.add(i)

        for j in range(i + 1, len(plate_tracks)):
            if j in used:
                continue
            if plates_are_similar(track.plate_text, plate_tracks[j].plate_text):
                group.append(plate_tracks[j])
                used.add(j)

        groups.append(group)

    merged_tracks = []
    for group in groups:
        if len(group) == 1:
            merged_tracks.append(group[0])
        else:
            best_plate = pick_best_plate([t.plate_text for t in group])

            group.sort(key=lambda t: t.hit_count, reverse=True)
            primary = group[0]
            primary.plate_text = best_plate
            primary.plate_confidence = max(t.plate_confidence for t in group)
            for other in group[1:]:
                primary.first_frame = min(primary.first_frame, other.first_frame)
                primary.last_frame = max(primary.last_frame, other.last_frame)
                primary.hit_count += other.hit_count
            merged_tracks.append(primary)

    return merged_tracks + no_plate_tracks


def draw_annotations(frame, tracks):
    """Draw bounding boxes, IDs, and plate text on the frame."""
    for track in tracks:
        if track.frames_since_seen > 0:
            continue

        x1, y1, x2, y2 = track.bbox
        # Vehicle box (green)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        # Label with ID and plate text
        label = f"ID:{track.vehicle_id}"
        if track.plate_text:
            label += f" [{track.plate_text}]"
        cv2.putText(
            frame, label, (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2,
        )

        # Plate box (blue)
        if track.plate_bbox is not None:
            px1, py1, px2, py2 = track.plate_bbox
            cv2.rectangle(frame, (px1, py1), (px2, py2), (255, 0, 0), 2)
            plate_label = track.plate_text if track.plate_text else "Plate"
            cv2.putText(
                frame, plate_label, (px1, py1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1,
            )

    return frame


def print_results(tracks, fps):
    """Print wait time summary for all tracked vehicles."""
    print("\n" + "=" * 90)
    print("VEHICLE WAIT TIME ANALYSIS RESULTS")
    print("=" * 90)
    print(
        f"{'Vehicle ID':<12}{'Plate Text':<16}{'Confidence':<12}"
        f"{'Enter (s)':<12}{'Leave (s)':<12}{'Wait Time (s)':<14}"
    )
    print("-" * 90)

    for track in sorted(tracks, key=lambda t: t.first_frame):
        enter_time = track.first_frame / fps
        leave_time = track.last_frame / fps
        wait_time = leave_time - enter_time

        plate_str = track.plate_text if track.plate_text else "N/A"
        conf_str = f"{track.plate_confidence:.2f}" if track.plate_text else "-"

        print(
            f"{track.vehicle_id:<12}{plate_str:<16}{conf_str:<12}"
            f"{enter_time:<12.2f}{leave_time:<12.2f}{wait_time:<14.2f}"
        )

    print("=" * 90)
    print(f"Total vehicles tracked: {len(tracks)}")

    # Statistics
    wait_times = [
        (t.last_frame - t.first_frame) / fps for t in tracks
    ]
    if wait_times:
        print(f"Average wait time: {np.mean(wait_times):.2f}s")
        print(f"Max wait time: {max(wait_times):.2f}s")
        print(f"Min wait time: {min(wait_times):.2f}s")
    print()


def process_video(
    video_path,
    stream_url,
    output_path,
    confidence,
    show,
    plate_model_path,
    ocr_languages,
    ocr_interval,
    no_ocr,
    display_width,
    detector_backend,
    aws_region,
    detect_interval,
):
    """Main processing pipeline. Handles both file and live stream input."""
    import time as _time

    # Determine input source
    is_stream = stream_url is not None
    source = stream_url if is_stream else video_path

    if not source:
        print("Error: Provide --video (file) or --stream (RTSP/RTMP URL)")
        return

    # Initialize video capture
    cap = cv2.VideoCapture(source)
    if is_stream:
        # Optimize for live streams: reduce buffer to minimize latency
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)

    if not cap.isOpened():
        print(f"Error: Cannot open {'stream' if is_stream else 'video'}: '{source}'")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or is_stream:
        fps = 25.0  # Default FPS for streams that don't report it
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if not is_stream else -1

    if is_stream:
        print(f"Stream: {source}")
        print(f"Resolution: {width}x{height}, FPS: {fps:.1f} (estimated)")
        print("Press 'q' in the display window to stop.")
    else:
        print(f"Video: {source}")
        print(f"Resolution: {width}x{height}, FPS: {fps:.1f}, Frames: {total_frames}")
    print(f"OCR: {'disabled' if no_ocr else f'enabled (languages={ocr_languages}, interval={ocr_interval} frames)'}")
    if detect_interval > 1:
        print(f"Detection interval: every {detect_interval} frames (Kalman prediction between)")
    print()

    # Initialize components
    if detector_backend == "rekognition":
        print(f"Using AWS Rekognition detector (region: {aws_region})")
        detector = RekognitionDetector(
            region_name=aws_region,
            confidence=confidence,
            use_rekognition_text=True,
        )
    else:
        print("Using YOLOv8 local detector")
        detector = VehicleDetector(
            vehicle_model_path="yolov8n.pt",
            plate_model_path=plate_model_path,
            confidence=confidence,
        )

    tracker = VehicleTracker(
        iou_threshold=0.3,
        max_lost=int(fps * 4),        # Keep tracks alive 4 seconds during occlusion
        min_hits=3,
        appearance_weight=0.4,
        reid_threshold=0.45,           # Re-ID sensitivity
        gallery_max_age=int(fps * 30), # Keep in gallery up to 30 seconds
    )

    appearance_extractor = AppearanceExtractor(feature_dim=128)

    # Always create aggregator when Rekognition is the backend (it reads text for free)
    plate_ocr = None
    text_aggregator = None
    if not no_ocr:
        print("Initializing OCR engine...")
        plate_ocr = PlateOCR(languages=ocr_languages, gpu=True)
        text_aggregator = PlateTextAggregator(min_readings=3, agreement_threshold=0.4)
        print("OCR ready.")
    elif detector_backend == "rekognition":
        text_aggregator = PlateTextAggregator(min_readings=2, agreement_threshold=0.4)
        print("Using Rekognition text detection (EasyOCR disabled).")

    # Initialize video writer (only for file input or if explicitly requested for stream)
    writer = None
    if output_path and not is_stream:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    elif output_path and is_stream:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        print(f"Recording stream to: {output_path}")

    frame_idx = 0
    start_time = _time.time()
    reconnect_attempts = 0
    max_reconnect = 5

    while True:
        ret, frame = cap.read()

        if not ret:
            if is_stream:
                # Stream disconnected — attempt reconnection
                reconnect_attempts += 1
                if reconnect_attempts > max_reconnect:
                    print(f"\nStream lost after {max_reconnect} reconnection attempts.")
                    break
                print(f"\nStream interrupted. Reconnecting ({reconnect_attempts}/{max_reconnect})...")
                _time.sleep(2)
                cap.release()
                cap = cv2.VideoCapture(source)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
                if cap.isOpened():
                    print("Reconnected.")
                    reconnect_attempts = 0
                continue
            else:
                break  # End of file

        reconnect_attempts = 0  # Reset on successful read

        # Detect vehicles and plates (skip frames to reduce API/GPU load)
        run_detection = (frame_idx % detect_interval == 0)

        if run_detection:
            detections = detector.detect(frame)

            # Extract appearance features for all detections
            features = None
            if detections:
                bboxes = [d["bbox"] for d in detections]
                features = appearance_extractor.extract_batch(frame, bboxes)

            # Update tracker with detections and features
            active_tracks = tracker.update(detections, frame_idx, features)

            # Feed Rekognition plate text directly into aggregator (avoids EasyOCR)
            if text_aggregator and detector_backend == "rekognition":
                for det in detections:
                    plate_text = det.get("plate_text")
                    plate_conf = det.get("plate_text_conf", 0.0)
                    if plate_text and plate_conf > 0.5:
                        # Find matching track for this detection
                        for track in active_tracks:
                            if track.bbox == det["bbox"] or (
                                track.plate_bbox == det.get("plate_bbox")
                                and track.plate_bbox is not None
                            ):
                                text_aggregator.add_reading(
                                    track.vehicle_id, plate_text, plate_conf,
                                    track.visibility,
                                )
                                break
        else:
            # No detection this frame — tracker predicts using Kalman
            active_tracks = tracker.update([], frame_idx, None)

        # Run EasyOCR on plate regions periodically (skip if Rekognition already read text)
        if plate_ocr and frame_idx % ocr_interval == 0:
            for track in active_tracks:
                if track.frames_since_seen == 0 and track.plate_bbox is not None:
                    text, conf = plate_ocr.read_plate(frame, track.plate_bbox)
                    if text:
                        text_aggregator.add_reading(
                            track.vehicle_id, text, conf, track.visibility
                        )
                    consensus_text, consensus_conf = text_aggregator.get_consensus(
                        track.vehicle_id
                    )
                    if consensus_text:
                        track.update_plate_text(consensus_text, consensus_conf)
        elif text_aggregator:
            # Still update consensus even on non-OCR frames (Rekognition may have added readings)
            for track in active_tracks:
                if track.frames_since_seen == 0:
                    consensus_text, consensus_conf = text_aggregator.get_consensus(
                        track.vehicle_id
                    )
                    if consensus_text:
                        track.update_plate_text(consensus_text, consensus_conf)

        # Draw annotations
        annotated_frame = draw_annotations(frame.copy(), active_tracks)

        # Add stream overlay info
        if is_stream:
            elapsed = _time.time() - start_time
            active_count = sum(
                1 for t in active_tracks if t.frames_since_seen == 0
            )
            overlay = f"LIVE | {elapsed:.0f}s | Vehicles: {active_count} | FPS: {frame_idx / max(elapsed, 0.01):.1f}"
            cv2.putText(
                annotated_frame, overlay, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2,
            )

        # Display progress
        if frame_idx % 30 == 0:
            active_count = sum(
                1 for t in active_tracks if t.frames_since_seen == 0
            )
            if is_stream:
                elapsed = _time.time() - start_time
                print(
                    f"\r[LIVE] Elapsed: {elapsed:.0f}s | Frame: {frame_idx} "
                    f"| Active vehicles: {active_count}",
                    end="",
                )
            else:
                print(
                    f"\rProcessing frame {frame_idx}/{total_frames} "
                    f"| Active vehicles: {active_count}",
                    end="",
                )

        # Write output
        if writer:
            writer.write(annotated_frame)

        # Show live preview (resized to fit screen)
        if show:
            display_frame = _resize_for_display(annotated_frame, display_width)
            cv2.imshow("Opus LaneSight", display_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("\nStopped by user.")
                break

        frame_idx += 1

    print()  # Newline after progress

    # Cleanup
    cap.release()
    if writer:
        writer.release()
        print(f"Output saved to: {output_path}")
    if show:
        cv2.destroyAllWindows()

    # Print results
    all_tracks = tracker.get_all_tracks()
    if all_tracks:
        # Final pass: update all tracks with consensus plate text
        if text_aggregator:
            for track in all_tracks:
                consensus_text, consensus_conf = text_aggregator.get_consensus(
                    track.vehicle_id
                )
                if consensus_text:
                    track.update_plate_text(consensus_text, consensus_conf)

        # Deduplicate tracks with the same plate text
        all_tracks = _deduplicate_by_plate(all_tracks)

        print_results(all_tracks, fps)
    else:
        print("No vehicles detected.")


def main():
    parser = argparse.ArgumentParser(
        description="Opus LaneSight — Analyze video or live stream to detect vehicles, "
        "read plates via OCR, track with DeepSORT, and calculate wait times."
    )

    # Input source (mutually exclusive: file or stream)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--video", help="Path to input video file (MP4, AVI, etc.)"
    )
    input_group.add_argument(
        "--stream",
        help="RTSP/RTMP/HTTP stream URL (e.g., rtsp://user:pass@ip:554/stream)",
    )

    parser.add_argument(
        "--output", default=None,
        help="Path to save annotated output video",
    )
    parser.add_argument(
        "--no-output",
        action="store_true",
        help="Disable saving output video",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.5,
        help="Detection confidence threshold (0-1)",
    )
    parser.add_argument(
        "--show", action="store_true", help="Display video while processing"
    )
    parser.add_argument(
        "--plate-model",
        default=None,
        help="Path to YOLO model for plate detection (optional)",
    )
    parser.add_argument(
        "--ocr-lang",
        nargs="+",
        default=["en"],
        help="OCR language codes (e.g., en ch_sim)",
    )
    parser.add_argument(
        "--ocr-interval",
        type=int,
        default=10,
        help="Run OCR every N frames (lower = more accurate but slower)",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Disable plate OCR (faster processing)",
    )
    parser.add_argument(
        "--display-width",
        type=int,
        default=1280,
        help="Width of the display window in pixels (maintains aspect ratio)",
    )
    parser.add_argument(
        "--detector",
        choices=["yolo", "rekognition"],
        default="yolo",
        help="Detection backend: 'yolo' (local YOLOv8) or 'rekognition' (AWS API)",
    )
    parser.add_argument(
        "--aws-region",
        default="us-east-1",
        help="AWS region for Rekognition API (used with --detector rekognition)",
    )
    parser.add_argument(
        "--detect-interval",
        type=int,
        default=1,
        help="Run detection every N frames (Kalman predicts between). "
        "Higher values reduce API calls for Rekognition or GPU load for YOLO. "
        "Default: 1 (every frame). Recommended for Rekognition: 5-10.",
    )

    args = parser.parse_args()

    # Default output path for file mode
    output = args.output
    if args.no_output:
        output = None
    elif output is None and args.video:
        output = "output.mp4"

    # For stream mode, auto-enable show if no output specified
    if args.stream and not args.output and not args.show:
        args.show = True

    process_video(
        video_path=args.video,
        stream_url=args.stream,
        output_path=output,
        confidence=args.conf,
        show=args.show,
        plate_model_path=args.plate_model,
        ocr_languages=args.ocr_lang,
        ocr_interval=args.ocr_interval,
        no_ocr=args.no_ocr,
        display_width=args.display_width,
        detector_backend=args.detector,
        aws_region=args.aws_region,
        detect_interval=args.detect_interval,
    )


if __name__ == "__main__":
    main()
