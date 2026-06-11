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
from tracker import VehicleTracker
from ocr import PlateOCR
from appearance import AppearanceExtractor


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
    output_path,
    confidence,
    show,
    plate_model_path,
    ocr_languages,
    ocr_interval,
    no_ocr,
):
    """Main processing pipeline."""
    # Initialize video capture
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video file '{video_path}'")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Video: {video_path}")
    print(f"Resolution: {width}x{height}, FPS: {fps:.1f}, Frames: {total_frames}")
    print(f"OCR: {'disabled' if no_ocr else f'enabled (languages={ocr_languages}, interval={ocr_interval} frames)'}")
    print()

    # Initialize components
    detector = VehicleDetector(
        vehicle_model_path="yolov8n.pt",
        plate_model_path=plate_model_path,
        confidence=confidence,
    )

    tracker = VehicleTracker(
        iou_threshold=0.3,
        max_lost=int(fps * 2),
        min_hits=3,
        appearance_weight=0.3,
    )

    appearance_extractor = AppearanceExtractor(feature_dim=128)

    plate_ocr = None
    if not no_ocr:
        print("Initializing OCR engine...")
        plate_ocr = PlateOCR(languages=ocr_languages, gpu=True)
        print("OCR ready.")

    # Initialize video writer
    writer = None
    if output_path:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Detect vehicles and plates
        detections = detector.detect(frame)

        # Extract appearance features for all detections
        features = None
        if detections:
            bboxes = [d["bbox"] for d in detections]
            features = appearance_extractor.extract_batch(frame, bboxes)

        # Update tracker with detections and features
        active_tracks = tracker.update(detections, frame_idx, features)

        # Run OCR on plate regions periodically
        if plate_ocr and frame_idx % ocr_interval == 0:
            for track in active_tracks:
                if track.frames_since_seen == 0 and track.plate_bbox is not None:
                    text, conf = plate_ocr.read_plate(frame, track.plate_bbox)
                    if text:
                        track.update_plate_text(text, conf)

        # Draw annotations
        annotated_frame = draw_annotations(frame.copy(), active_tracks)

        # Display progress
        if frame_idx % 30 == 0:
            active_count = sum(
                1 for t in active_tracks if t.frames_since_seen == 0
            )
            print(
                f"\rProcessing frame {frame_idx}/{total_frames} "
                f"| Active vehicles: {active_count}",
                end="",
            )

        # Write output
        if writer:
            writer.write(annotated_frame)

        # Show live preview
        if show:
            cv2.imshow("Vehicle Wait Time Analyzer", annotated_frame)
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
        print_results(all_tracks, fps)
    else:
        print("No vehicles detected in the video.")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze video to detect vehicles, read plates via OCR, "
        "track with DeepSORT, and calculate wait times."
    )
    parser.add_argument(
        "--video", required=True, help="Path to input video file"
    )
    parser.add_argument(
        "--output", default="output.mp4", help="Path to save annotated video"
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

    args = parser.parse_args()

    process_video(
        video_path=args.video,
        output_path=args.output,
        confidence=args.conf,
        show=args.show,
        plate_model_path=args.plate_model,
        ocr_languages=args.ocr_lang,
        ocr_interval=args.ocr_interval,
        no_ocr=args.no_ocr,
    )


if __name__ == "__main__":
    main()
