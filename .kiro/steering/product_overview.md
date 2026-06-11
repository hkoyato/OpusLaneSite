---
inclusion: always
---
# Opus LaneSight — Product Steering Document

## 1. Product summary

**Opus LaneSight** is an AI-powered station wait-time intelligence prototype for Opus vehicle inspection programs. It uses standard high-definition IP camera footage to anonymously detect, track, and time vehicles as they move through inspection station queues, lanes, bays, and exit zones. The system calculates real-time lane-level operational metrics and publishes an estimated public wait time that can be consumed by an Opus-operated website or station display.

The project is intended for the Opus + AWS AI Hackathon as a two-day working prototype that demonstrates a thin, credible, end-to-end slice: video/frame input, vehicle detection, lane/zone assignment, time-in-zone calculation, station metrics, public wait-time output, and AI-generated operations summary.

## 2. One-line pitch

Opus LaneSight uses standard HD IP cameras and AWS AI to produce anonymous, lane-level wait-time intelligence for inspection stations, reducing dependency on specialized license plate reader hardware while improving operational visibility and motorist transparency.

## 3. Problem statement

Opus currently provides wait-time visibility for inspection stations, but existing approaches may depend on specialized license plate reader camera infrastructure. LPR-based wait-time calculation can be effective, but it has several limitations:

- Specialized camera hardware can be expensive to deploy and maintain.
- Plate-based systems primarily capture identity events, not full station-flow behavior.
- Station managers need lane-level insight into queue depth, bottlenecks, inspection duration, and throughput.
- Public wait-time estimates are more useful when they reflect current queue behavior, active lanes, and recent completion rates.
- Privacy expectations favor aggregate, anonymous tracking when plate identification is not required.

## 4. Target users

### Primary users

- **Station operations managers** who need real-time visibility into queue length, lane bottlenecks, and throughput.
- **Program operations teams** who manage inspection performance across multiple stations.
- **Motorists** who need accurate public wait-time estimates before choosing a station or arrival time.

### Secondary users

- **Government agency stakeholders** who need transparent program performance data.
- **Call center / customer support teams** who benefit from accurate station wait-time information.
- **Engineering and product teams** evaluating lower-cost alternatives or complements to LPR-based wait-time systems.

## 5. Product goals

1. Detect vehicles from standard HD IP camera footage or demo video.
2. Assign detected vehicles to station-defined lanes and zones.
3. Track anonymous vehicle session IDs while vehicles remain inside the station flow.
4. Calculate time spent in queue, inspection bay, and total station cycle.
5. Generate real-time station metrics and public wait-time estimates.
6. Provide a simple internal dashboard for station operations.
7. Provide a public-facing wait-time card/API output.
8. Use AWS AI services in a way that is demoable within the hackathon timeframe.
9. Align with Opus brand principles, including clarity, trust, operational excellence, and the mission of making the world a safer and cleaner place.

## 6. Non-goals for the hackathon prototype

The prototype should not attempt to solve every production requirement. The following are out of scope for the two-day build:

- Production-grade multi-camera re-identification.
- Real-time integration with live station cameras.
- Reading, storing, or processing license plate numbers.
- Using real customer data or production station footage without approval.
- Full station-management integration.
- Final accuracy certification.
- Long-term historical reporting across all Opus programs.
- Edge-device deployment.

## 7. Core use cases

### Use case 1: Internal station monitoring

A station manager opens the LaneSight dashboard and sees current queue length, active lanes, average wait time, inspection duration, throughput, and the slowest lane.

**Success condition:** The manager can quickly identify whether the station is operating normally or whether a lane/bay is causing delays.

### Use case 2: Public wait-time calculation

The system publishes an estimated wait time for a station based on current queue depth, active lanes, and recent vehicle completion rate.

**Success condition:** A public website or card can display a clear wait-time estimate, queue status, open lanes, and last-updated timestamp.

### Use case 3: Vehicle time-in-zone tracking

The system tracks an anonymous vehicle session as it moves from entrance to queue, bay, and exit.

**Success condition:** The system can calculate queue time, inspection time, and total station time for each completed anonymous session.

### Use case 4: AI station summary

An operations user clicks “Generate station summary.” Bedrock produces a grounded summary using calculated metrics only.

**Success condition:** The summary explains station status, bottlenecks, and recommended actions without inventing data.

## 8. Hackathon MVP scope

### What exists today

The current codebase provides:

- **Video input:** CLI accepts any MP4 video file via `--video` flag.
- **Vehicle detection:** YOLOv8 nano model detects cars, trucks, buses, motorcycles per frame.
- **Plate localization:** Multi-method plate region detection (YOLO model or contour/morphology/color fallback).
- **Tracking:** DeepSORT-style tracker with Kalman filter + appearance re-ID maintains anonymous integer IDs across frames.
- **OCR:** EasyOCR reads plate text with multi-frame voting consensus (can be disabled with `--no-ocr`).
- **Wait-time output:** Console table with per-vehicle enter/leave timestamps and wait duration + statistics.
- **Annotated video:** Output MP4 with bounding boxes, vehicle IDs, and plate text overlays.

### What still needs to be built for the MVP

- **Lane and zone assignment:** Polygon-based zone definitions and assigning vehicles to lanes/zones based on bounding box center position.
- **Zone-level timing:** Track time spent in queue zone, inspection bay zone, and exit zone separately.
- **Station metrics aggregation:** Vehicles in queue, active lanes, throughput, average inspection time, bottleneck detection.
- **Public wait-time calculation:** Formula-based estimate from queue depth, active lanes, and recent completion rate.
- **Internal dashboard UI:** Web-based operational dashboard (React or similar).
- **Public wait-time card/page:** Motorist-facing wait-time display.
- **Bedrock integration:** AI-generated station summary from calculated metrics.
- **AWS deployment:** S3, Lambda, DynamoDB, API Gateway integration (or keep local for demo).

### Input

- A short demo video clip, simulated camera stream, or extracted frames.
- Manually defined lane and zone polygons (to be implemented).
- Synthetic station metadata such as station name, number of lanes, and operating status.

### Processing

- Detect vehicles in frames. ✓ (YOLOv8)
- Assign bounding boxes to lane/zone polygons. ✗ (not yet implemented)
- Maintain temporary vehicle session IDs. ✓ (DeepSORT tracker)
- Calculate elapsed time in each zone. ✗ (only total frame-based wait time exists)
- Mark a vehicle complete when it reaches an exit/completion zone. ✗ (not yet implemented)
- Store session and metric snapshots. ✗ (not yet implemented)

### Output

- Internal dashboard. ✗ (not yet implemented)
- Public wait-time card. ✗ (not yet implemented)
- JSON wait-time API response. ✗ (not yet implemented)
- AI-generated station summary. ✗ (not yet implemented)
- Console wait-time table. ✓
- Annotated output video. ✓

## 9. Demo story arc

1. Open with the Opus problem: wait-time tracking is valuable, but specialized hardware can be costly and does not always provide rich lane-level flow data.
2. Show the LaneSight architecture: video input, AWS AI detection, lane assignment, time tracking, dashboard, public API, and Bedrock summary.
3. Run the demo: upload/process video or simulate frames.
4. Show vehicle detections with lane labels and elapsed time.
5. Show the internal dashboard updating.
6. Show the public wait-time card/API.
7. Generate a Bedrock station summary.
8. Close with business impact and next 30-day path to pilot.

## 10. Architecture

### Current implementation (local prototype)

The codebase currently runs as a local, offline CLI pipeline with no cloud dependencies:

```text
Demo video file (MP4)
        ↓
OpenCV frame extraction (main.py)
        ↓
YOLOv8 vehicle detection + plate localization (detector.py, plate_detector.py)
        ↓
DeepSORT tracking: Kalman filter + appearance re-ID (tracker.py, appearance.py)
        ↓
EasyOCR plate text reading with multi-frame voting (ocr.py)
        ↓
Console output: per-vehicle wait-time table + statistics
        ↓
Annotated output video (MP4 with bounding boxes, IDs, plate text)
```

### Module responsibilities (current)

| Module | Responsibility |
|---|---|
| `main.py` | CLI entry point, video I/O loop, orchestrates detection → tracking → OCR → output. |
| `detector.py` | YOLOv8 vehicle detection (car, motorcycle, bus, truck). Delegates plate localization. |
| `plate_detector.py` | Contour/morphology/color-based license plate region detection (fallback when no YOLO plate model). |
| `tracker.py` | DeepSORT-style multi-object tracker: Kalman filter prediction + Hungarian assignment + IoU/appearance cost. |
| `appearance.py` | HSV color histogram feature extractor (spatial grid) for vehicle re-identification. |
| `ocr.py` | EasyOCR with multiple preprocessing pipelines and multi-frame voting for plate text consensus. |

### Key dependencies (current)

| Package | Role |
|---|---|
| `ultralytics` | YOLOv8 model inference for vehicle and optional plate detection. |
| `opencv-python` | Video capture, frame processing, image preprocessing, annotation, video writing. |
| `easyocr` | License plate OCR with GPU support. |
| `scipy` | Hungarian algorithm (`linear_sum_assignment`) for optimal track assignment. |
| `numpy` | Numerical operations throughout. |
| `filterpy` | Listed in requirements but Kalman filter is implemented inline in `tracker.py`. |

### Target hackathon architecture (planned, not yet implemented)

```text
Demo video or IP camera footage
        ↓
Amazon S3
        ↓
Frame extraction / processing job
        ↓
Amazon Rekognition vehicle detection (or keep YOLOv8 locally)
        ↓
AWS Lambda lane and zone assignment
        ↓
DynamoDB vehicle sessions and station metrics
        ↓
API Gateway wait-time API
        ↓
Internal dashboard + public wait-time card
        ↓
Amazon Bedrock station summary and recommendations
```

### Target service responsibilities (planned)

| Service | Responsibility |
|---|---|
| Amazon S3 | Store demo video, extracted frames, and optional output artifacts. |
| Amazon Rekognition | Detect vehicles in frames or images (alternative to local YOLOv8). |
| AWS Lambda | Process detections, assign zones, calculate metrics, generate API responses. |
| DynamoDB | Store anonymous vehicle sessions, zone events, and station metric snapshots. |
| API Gateway | Expose public wait-time and internal metrics endpoints. |
| Amazon Bedrock | Generate grounded operational summaries and recommended actions. |
| CloudWatch | Log processing steps and errors. |

## 11. Data model

### Vehicle session

```json
{
  "session_id": "veh_0007",
  "station_id": "demo_station_01",
  "current_lane_id": "lane_2",
  "current_zone_id": "queue_zone_2",
  "first_seen_at": "2026-06-12T13:31:04-08:00",
  "last_seen_at": "2026-06-12T13:42:19-08:00",
  "entered_queue_at": "2026-06-12T13:31:04-08:00",
  "entered_bay_at": "2026-06-12T13:43:00-08:00",
  "completed_at": null,
  "queue_duration_seconds": 675,
  "inspection_duration_seconds": null,
  "total_duration_seconds": null,
  "confidence_score": 0.87,
  "status": "waiting"
}
```

### Zone event

```json
{
  "event_id": "event_00041",
  "session_id": "veh_0007",
  "station_id": "demo_station_01",
  "zone_id": "queue_zone_2",
  "entered_at": "2026-06-12T13:31:04-08:00",
  "exited_at": null,
  "duration_seconds": 675,
  "confidence_score": 0.87
}
```

### Station metric snapshot

```json
{
  "station_id": "demo_station_01",
  "timestamp": "2026-06-12T13:45:00-08:00",
  "vehicles_in_queue": 9,
  "vehicles_in_bay": 3,
  "active_lanes": 3,
  "average_queue_wait_minutes": 14.2,
  "average_inspection_minutes": 6.4,
  "estimated_public_wait_minutes": 18,
  "throughput_per_hour": 28,
  "slowest_lane_id": "lane_2",
  "confidence_score": 0.82
}
```

## 12. Wait-time calculation approach

For the MVP, use a transparent formula that judges can understand:

```text
Estimated public wait = current queue depth × recent average inspection duration ÷ active lanes
```

Enhanced version:

```text
Estimated public wait = weighted blend of:
- Current queue depth
- Active lane count
- Average inspection duration over the last 15 minutes
- Average completion rate over the last 30 minutes
- Current lane-level bottleneck factor
- Confidence score from detections and tracking
```

Example:

```text
9 vehicles in queue × 6.2 minutes average inspection time ÷ 3 active lanes = 18.6 minutes
Rounded public estimate: 19 minutes
```

## 13. AI and ML approach

### Computer vision (current implementation)

- Detect vehicles using **YOLOv8** (`yolov8n.pt` nano model) locally. COCO class IDs 2, 3, 5, 7 (car, motorcycle, bus, truck).
- License plate localization via dedicated YOLO plate model (if provided) or multi-method contour/morphology/color-based `PlateDetector`.
- Amazon Rekognition remains an option for the cloud path but is not currently integrated.

### Tracking (current implementation)

- **DeepSORT-style tracker** in `tracker.py`:
  - Kalman filter with 7-dimensional state `[cx, cy, area, aspect_ratio, vx, vy, va]` for motion prediction.
  - Hungarian algorithm (`scipy.optimize.linear_sum_assignment`) for optimal detection-to-track assignment.
  - Combined IoU + appearance cost matrix (configurable weight, default 0.3 appearance).
  - Tracks survive up to `max_lost` frames (default 2× FPS) without matches.
  - Minimum `min_hits` detections required before a track is confirmed.
- **Appearance re-identification** in `appearance.py`:
  - HSV color histogram features extracted on a 4×4 spatial grid per vehicle crop.
  - Cosine similarity against stored feature history (up to 30 features per track).
- Anonymous integer vehicle IDs (incremental, session-scoped).

### OCR (current implementation — NOTE: conflicts with privacy non-goal)

- **EasyOCR** reads license plate text with multi-frame voting (`PlateTextAggregator`).
- Multiple preprocessing pipelines (CLAHE, adaptive threshold, Otsu, inverted, sharpened, color) — picks highest-confidence result.
- Character allowlist restricted to `A-Z0-9-`.
- **Important:** The product overview states plate reading is a non-goal. The OCR module exists in the codebase but should be disabled (`--no-ocr`) or removed for the hackathon demo to align with the privacy-preserving positioning.

### Generative AI (planned, not yet implemented)

Use Bedrock to convert calculated metrics into a concise operational summary.

Example prompt input:

```json
{
  "station_name": "Demo Inspection Station",
  "vehicles_in_queue": 9,
  "active_lanes": 3,
  "estimated_public_wait_minutes": 18,
  "average_inspection_minutes": 6.2,
  "slowest_lane": "Lane 2",
  "confidence_score": 0.82
}
```

Example output:

```text
Demo Inspection Station is currently experiencing moderate demand. The public wait estimate is 18 minutes based on 9 vehicles in queue, 3 active lanes, and a recent average inspection duration of 6.2 minutes. Lane 2 is moving slower than the other lanes and should be reviewed by the station manager if the trend continues.
```

## 14. Guardrails and trust

LaneSight should be positioned as privacy-preserving and operationally trustworthy.

### Privacy guardrails

- Do not read or store license plate numbers in the demo or production system.
- **NOTE:** The current codebase includes an OCR module (`ocr.py`) that reads plate text. For the hackathon demo, run with `--no-ocr` or remove OCR output from the UI to align with the privacy-preserving positioning. The OCR capability may be retained internally for development/testing but must not be surfaced in the demo or public-facing outputs.
- Do not identify vehicle owners or motorists.
- Use anonymous temporary session IDs only.
- Expire session IDs after the vehicle exits the station.
- Publish only aggregate metrics to public-facing pages.

### AI guardrails

- Ground Bedrock summaries only in calculated station metrics.
- Do not allow the model to invent data.
- Include confidence scores in internal views.
- Suppress or flag low-confidence metrics.
- Provide a deterministic wait-time calculation separate from the LLM.

### Operational guardrails

- If camera confidence is low, show “wait time unavailable” or fall back to a conservative estimate.
- If active lanes cannot be determined, require manual station override.
- If queue depth is inconsistent, show an internal warning before publishing public changes.

## 15. Business impact

### Hardware cost

LaneSight can reduce dependency on specialized LPR camera infrastructure for wait-time estimation by using standard HD IP cameras where appropriate.

### Customer experience

More accurate and timely public wait estimates can help motorists choose when and where to visit, reducing frustration and surprise delays.

### Operational visibility

Lane-level metrics help station managers identify slow lanes, stalled vehicles, uneven utilization, and bottlenecks.

### Program performance

Aggregate station-flow data can support reporting, staffing decisions, process improvement, and public confidence in inspection programs.

### Privacy posture

Anonymous session tracking supports wait-time calculation without requiring plate recognition.

## 16. Success metrics

### Hackathon success metrics

- Working demo processes a video or frame sequence.
- Vehicles are detected and displayed with anonymous IDs.
- Vehicles are assigned to lanes/zones.
- Time-in-zone is calculated.
- Dashboard displays station metrics.
- Public wait-time card/API works.
- Bedrock generates a grounded operations summary.

### Production evaluation metrics

- Vehicle detection precision and recall.
- Zone assignment accuracy.
- Session tracking continuity.
- Wait-time estimate error versus ground truth.
- Lane-level bottleneck detection accuracy.
- Cost per station compared with LPR-based wait-time instrumentation.
- Public wait-time freshness and availability.

## 17. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Occlusion from vehicles blocking one another | Use elevated camera angles, lane polygons, and aggregate queue metrics. |
| Similar vehicles causing identity swaps | Scope identity to lane/zone session, use motion continuity and timestamps. |
| Poor lighting or weather | Use confidence scores and fallbacks; evaluate camera placement and IR capability. |
| Multi-camera handoff complexity | Start with single-camera lane tracking; add camera handoff later. |
| Public estimate volatility | Smooth estimates over short rolling windows. |
| AI hallucination | Keep wait-time calculation deterministic; use Bedrock only to summarize known metrics. |
| Privacy concerns | Avoid plate recognition and store only anonymous temporary IDs. |

## 18. Next 30 days if selected

1. Obtain approved, anonymized inspection-station footage.
2. Define station-specific lane and zone calibration workflow.
3. Compare LaneSight estimates against existing wait-time calculations.
4. Measure accuracy by station, time of day, lane, and weather condition.
5. Add confidence thresholds and fallback rules.
6. Build a pilot dashboard for one station.
7. Define integration path with existing public wait-time website and internal operations tools.
8. Produce a cost comparison between LPR-based and IP-camera-based wait-time instrumentation.

## 19. Submission-ready description

Opus LaneSight is an AI-powered wait-time intelligence prototype for vehicle inspection stations. It uses standard HD IP camera footage and AWS AI services to anonymously detect vehicles, assign them to lanes and zones, track time spent in queue and inspection areas, and publish real-time wait-time estimates for operations teams and public-facing websites. The prototype reduces dependency on specialized license plate reader hardware, improves station-flow visibility, and supports Opus’s mission of making the world a safer and cleaner place through more efficient inspection programs and better customer transparency.
