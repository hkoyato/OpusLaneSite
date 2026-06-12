# Opus LaneSight

## AI-Powered Station Wait-Time Intelligence

---

## The Problem

**Wait-time tracking is valuable, but current approaches have limitations.**

- Specialized LPR camera hardware is expensive to deploy and maintain
- Plate-based systems capture identity events, not full station-flow behavior
- Station managers lack lane-level insight into queue depth and bottlenecks
- Public wait estimates don't always reflect real-time queue behavior
- Privacy expectations favor anonymous tracking when plate ID isn't required

> *How can we deliver rich, real-time wait-time intelligence using standard cameras — without reading license plates?*

---

## The Solution: Opus LaneSight

**Standard HD IP cameras + AWS AI = anonymous wait-time intelligence**

- Uses existing station camera infrastructure (no new hardware)
- Detects and tracks vehicles anonymously with temporary session IDs
- Calculates real-time wait estimates from actual queue behavior
- Provides operational dashboard for station managers
- Publishes motorist-friendly public wait estimates
- Privacy-preserving by design: no plate reading, no driver identification

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    INPUT SOURCES                         │
│   Video File (MP4)  │  RTSP/RTMP Live Stream           │
└──────────┬──────────┴──────────────┬────────────────────┘
           │                         │
           ▼                         ▼
┌─────────────────────────────────────────────────────────┐
│                 DETECTION ENGINE                         │
│  Local YOLOv8 (free, fast)  │  AWS Rekognition (cloud) │
│         ↕ switchable via --detector flag                │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              DeepSORT TRACKING ENGINE                    │
│  • Kalman filter motion prediction                      │
│  • Hungarian algorithm optimal assignment               │
│  • Appearance re-identification (color histograms)      │
│  • Occlusion-aware gallery for re-ID after blocking     │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    METRICS ENGINE                        │
│  • Vehicles in queue          • Average wait time       │
│  • Active lanes               • Throughput/hour         │
│  • Estimated public wait      • Bottleneck detection    │
└──────────────────────────┬──────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
┌──────────────────────┐  ┌──────────────────────────────┐
│  Internal Dashboard  │  │  Public Wait-Time Display    │
│  (Station Manager)   │  │  (Motorists)                 │
└──────────────────────┘  └──────────────────────────────┘
```

---

## Key AWS Services

| Service | Role |
|---------|------|
| **Amazon Rekognition** | Vehicle detection via DetectLabels API |
| **Amazon Rekognition** | Plate region localization via DetectText |
| **Amazon Bedrock** | AI-generated station summaries (planned) |
| **Amazon S3** | Video/frame storage (planned) |
| **DynamoDB** | Session and metric persistence (planned) |
| **API Gateway** | Public wait-time API (planned) |

---

## Smart Cost Optimization: Adaptive Detection

**Problem:** Rekognition charges per API call. At 25 FPS, that's $1.50/minute.

**Solution:** Intelligent adaptive controller that adjusts detection frequency based on scene activity.

| Scene State | Interval | Resolution | API Cost |
|-------------|----------|-----------|----------|
| Warmup (first 2.5s) | Every frame | 1920px | Full accuracy |
| Stable queue (vehicles present) | Every 10th frame | 960px | 90% savings |
| Empty (no vehicles) | Every 30th frame | 640px | 97% savings |
| Activity spike (vehicle enters/leaves) | Every frame | 1920px | Instant react |

**Kalman filter predicts vehicle positions on skipped frames — tracking stays smooth.**

Result: ~$0.10-0.15/minute instead of $1.50/minute in typical station conditions.

---

## Tracking Intelligence

### Occlusion Handling

Vehicles blocking each other is the #1 challenge at inspection stations.

**Three-layer approach:**

1. **Kalman filter prediction** — keeps tracking for 4 seconds during occlusion
2. **Gallery re-identification** — appearance + spatial matching revives tracks after long occlusions
3. **Plate-text deduplication** — merges any remaining duplicates as a safety net

### Result

Same vehicle blocked for 3+ seconds → **still counted as one vehicle** with continuous wait time.

---

## Privacy by Design

| Principle | Implementation |
|-----------|---------------|
| No plate reading | OCR disabled in production (`--no-ocr`) |
| No driver identification | Only anonymous integer session IDs |
| Temporary sessions | IDs expire when vehicle exits camera |
| Aggregate only | Public display shows only wait estimate, not individual vehicles |
| No data retention | Session data not stored after vehicle leaves |

> *"LaneSight uses temporary anonymous vehicle session IDs for wait-time calculation. License plates and driver identities are not read or stored."*

---

## Live Demo

### What you'll see:

1. **Video input** → processed through the detection pipeline
2. **Real-time vehicle detection** with bounding boxes and anonymous IDs
3. **Wait-time calculation** — enter time, leave time, total duration
4. **Internal dashboard** — queue metrics, status, and estimates
5. **Public wait-time card** — clean, motorist-friendly display

### Commands:

```bash
# Local YOLO (fast, free)
python main.py --video demo_station.mp4 --no-ocr --show

# AWS Rekognition with adaptive optimization
python main.py --video demo_station.mp4 --detector rekognition --auto-adjust --no-ocr --show

# Live RTSP camera stream
python main.py --stream rtsp://camera-ip:554/stream --detector rekognition --auto-adjust --no-ocr
```

---

## Wait-Time Formula

```
Estimated Public Wait = Queue Depth × Avg Inspection Time ÷ Active Lanes
```

**Example:**

```
9 vehicles × 6.2 min avg inspection ÷ 3 active lanes = 18.6 min
→ Public estimate: 19 minutes
```

Enhanced with:
- Rolling 15-minute average inspection duration
- Confidence scoring from detection quality
- Smoothing to prevent volatile public estimates

---

## Business Impact

### Cost Reduction
- Eliminates need for specialized LPR cameras ($5K-15K per lane)
- Uses existing HD IP cameras already installed at stations
- Rekognition costs ~$0.10/minute with adaptive optimization

### Customer Experience
- Accurate real-time wait estimates help motorists plan visits
- Reduces frustration from unexpected delays
- Builds public confidence in inspection programs

### Operational Excellence
- Station managers see queue bottlenecks in real time
- Lane-level metrics identify underperforming lanes
- Data supports staffing and process improvement decisions

### Program Transparency
- Aggregate flow data supports reporting requirements
- Measurable service levels across all stations
- Supports Opus mission: *making the world a safer and cleaner place*

---

## Guardrails and Trust

### AI Guardrails
- Wait-time calculation is **deterministic** (not AI-generated)
- Bedrock summaries grounded only in measured metrics
- Confidence scores shown in internal views
- Low-confidence states suppress public estimates

### Operational Guardrails
- Low detection confidence → "wait time unavailable" fallback
- Camera issues flagged to station manager
- Manual lane-count override available
- Estimates smoothed over rolling windows (no volatile jumps)

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Vehicle occlusion | Kalman prediction + gallery re-ID + elevated camera angles |
| Identity swaps | Appearance features + motion continuity + session scoping |
| Poor lighting/weather | Confidence scores + fallback estimates + IR camera support |
| API cost growth | Adaptive controller reduces calls 90-97% during idle |
| Estimate volatility | Rolling-window smoothing before publishing |
| Privacy concerns | No plate reading + anonymous IDs + no retention |

---

## Next 30 Days

1. Obtain approved, anonymized inspection-station footage
2. Define lane and zone calibration workflow per station
3. Compare LaneSight estimates against existing wait-time data
4. Measure accuracy across station types, times, and weather
5. Add confidence thresholds and fallback rules
6. Build pilot dashboard for one production station
7. Define integration with existing public wait-time systems
8. Cost comparison: LPR-based vs. IP-camera-based instrumentation

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Detection | YOLOv8 (local) or Amazon Rekognition (cloud) |
| Tracking | Custom DeepSORT: Kalman + Hungarian + appearance |
| Optimization | Adaptive controller (interval + resolution) |
| OCR | EasyOCR (development only, disabled in production) |
| GUI | PySide6 desktop application |
| Video I/O | OpenCV (file + RTSP/RTMP/HTTP streams) |
| Cloud | boto3, AWS Rekognition, Bedrock (planned) |
| Language | Python 3.11+ |

---

## Summary

**Opus LaneSight** delivers real-time, anonymous, lane-level wait-time intelligence for vehicle inspection stations using standard cameras and AWS AI.

**Key differentiators:**
- No new hardware required — works with existing HD cameras
- Privacy-preserving — no plate reading, no identity tracking
- Dual-mode detection — local (free) or cloud (scalable)
- Smart cost optimization — adaptive detection saves 90%+ API costs
- Occlusion-resilient — handles the real-world challenge of blocked vehicles

> *Making the world a safer and cleaner place — one queue at a time.*

---

## Thank You

**Opus LaneSight**
*AI-powered station wait-time intelligence*

Powered by AWS Rekognition + YOLOv8 + DeepSORT
