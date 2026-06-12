# Opus LaneSight

Opus LaneSight is a prototype for inspection-station wait-time intelligence. It uses standard camera footage to detect and track vehicles, turns those tracks into station-level wait-time metrics, and can publish the latest station snapshot to a small public wait-time display.

The repository contains four working pieces:

1. **Video analysis pipeline** — Python CLI and PySide6 desktop app for MP4 files or RTSP/RTMP/HTTP streams.
2. **Station metrics layer** — deterministic aggregation from tracked vehicles into queue-depth, throughput, active-lane, and public wait estimates.
3. **Station Stats API** — AWS SAM template for API Gateway, Lambda, and DynamoDB.
4. **Public dashboard** — static HTML/CSS/JavaScript page that reads the API and shows a motorist-friendly wait-time card.

> Project status: hackathon/demo prototype. It is useful for demos, experiments, and pilot planning, but it is not a production-certified traffic-measurement system.

## What LaneSight does today

- Processes video files or live camera streams.
- Detects vehicles with local YOLOv8 or optional Amazon Rekognition.
- Tracks vehicles with a DeepSORT-style tracker using Kalman prediction, Hungarian assignment, and appearance re-identification.
- Calculates how long vehicles remain visible in the observed scene.
- Computes station metrics from tracked results:
  - total vehicles
  - peak concurrent vehicles as the current queue-depth proxy
  - completed vehicles
  - manually configured active lanes
  - average observed cycle duration
  - estimated public wait time
  - throughput per hour
- Runs as either:
  - a command-line analyzer (`main.py`), or
  - a branded desktop app (`python -m gui`).
- Publishes station snapshots to an HTTPS API when configured.
- Serves a static public dashboard that lists available stations and displays the latest public wait estimate.

## What is intentionally not claimed

- Lane and zone polygons are not yet implemented; active lane count is an operator setting, and queue depth is currently derived from peak concurrent tracked vehicles.
- The public wait estimate is a transparent formula, not a machine-learning prediction.
- License-plate OCR exists for development experiments, but the intended public wait-time workflow keeps OCR disabled and does not require plate identity.
- Bedrock summaries, historical reporting, multi-camera re-identification, and production station integrations are future work.

## Architecture

```text
Video file or camera stream
        |
        v
Vehicle detection
  - YOLOv8 locally, or
  - Amazon Rekognition when selected
        |
        v
Vehicle tracking
  - Kalman prediction
  - Hungarian assignment
  - appearance re-identification
        |
        v
Station metrics
  - queue-depth proxy
  - average observed cycle time
  - active lane setting
  - public wait estimate
        |
        +--> Desktop app / CLI results
        |
        v
Station Stats API
  - API Gateway
  - Lambda
  - DynamoDB current station snapshot
        |
        v
Static public dashboard
```

## Repository map

| Path | Purpose |
| --- | --- |
| `main.py` | CLI entry point for video and stream processing. |
| `gui/` | PySide6 desktop application, station settings, metrics, and API publishing. |
| `detector.py` | Local YOLOv8 vehicle detection. |
| `detector_rekognition.py` | Optional Amazon Rekognition detector. |
| `tracker.py` | DeepSORT-style vehicle tracker. |
| `ocr.py`, `plate_detector.py` | Optional plate-region and OCR utilities for development experiments. |
| `station_stats_api/` | Lambda handlers, validation, storage adapters, and API logic. |
| `lanesight_client/` | HTTPS snapshot publisher used by the desktop app. |
| `infra/template.yaml` | AWS SAM template for API Gateway, Lambda, and DynamoDB. |
| `src/` | Static public wait-time dashboard. |
| `tests/` | Python and JavaScript tests. |

## Prerequisites

- Python 3.11+ for the local app and tests.
- Python 3.12-compatible AWS runtime for Lambda deployment.
- Node.js 20+ and npm for dashboard tests.
- AWS CLI and AWS SAM CLI for cloud deployment.
- AWS credentials configured locally when using Rekognition or deploying the API.

## Local setup

```bash
git clone <repo-url>
cd "Opus Lanesight"

python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
npm install
```

The first local YOLO run downloads the default model into `assets/models/` if it is missing.

## Run the desktop app

```bash
python -m gui
```

Typical demo flow:

1. Open **Station** and set the station identifier and display name.
2. Open **Input** and choose a video file or stream URL.
3. Keep OCR disabled for the privacy-preserving wait-time workflow.
4. Choose `yolo` for local processing, or `rekognition` if AWS credentials are configured.
5. Start processing and review the **Results** view.

The app stores local settings at `%LOCALAPPDATA%\OpusLaneSight\settings.json` on Windows.

## Run the CLI analyzer

```bash
# Local YOLO, privacy-preserving demo mode
python main.py --video demo_station.mp4 --no-ocr --show

# Headless file processing with annotated output.mp4
python main.py --video demo_station.mp4 --no-ocr

# Live stream preview
python main.py --stream rtsp://camera.example.com/stream --no-ocr --show

# AWS Rekognition detector
python main.py --video demo_station.mp4 --detector rekognition --aws-region us-west-2 --no-ocr

# Rekognition with adaptive interval/resolution control
python main.py --video demo_station.mp4 --detector rekognition --auto-adjust --no-ocr --show
```

Common options:

| Option | Description | Default |
| --- | --- | --- |
| `--video PATH` | Analyze a video file. | Required unless `--stream` is used. |
| `--stream URL` | Analyze an RTSP/RTMP/HTTP stream. | Required unless `--video` is used. |
| `--output PATH` | Save annotated video. | `output.mp4` for file mode. |
| `--no-output` | Disable annotated output. | `False` |
| `--show` | Display a preview window. | `False` for files; auto-enabled for streams without output. |
| `--detector yolo\|rekognition` | Detection backend. | `yolo` |
| `--aws-region REGION` | Rekognition region. | `us-east-1` |
| `--detect-interval N` | Run detection every N frames. | `1` |
| `--auto-adjust` | Adjust Rekognition interval/resolution based on activity. | `False` |
| `--no-ocr` | Disable plate OCR. Recommended for public wait-time demos. | `False` |
| `--ocr-lang LANG...` | EasyOCR language codes when OCR is enabled. | `en` |

Press `q` in the preview window to stop processing.

## Station wait-time formula

The current public estimate is deterministic:

```text
estimated_public_wait_minutes = queue_depth * average_inspection_minutes / active_lanes
```

Where:

- `queue_depth` is the peak concurrent tracked-vehicle count in the observed window.
- `average_inspection_minutes` is currently the average observed vehicle cycle duration because zone-level queue/bay timing is not implemented yet.
- `active_lanes` is an operator-configured station setting and is floored at 1.

## Station Stats API

The deployed API stores one current snapshot per station.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/stations/{station_id}/snapshot` | Accept a station metric snapshot. |
| `GET` | `/stations` | List stations that have a current snapshot. |
| `GET` | `/stations/{station_id}` | Return the latest snapshot for one station. |

All requests require the `X-Client-Credential` header. The prototype authorizer accepts a comma-separated `STATION_STATS_CLIENT_CREDENTIALS` Lambda environment variable. If that variable is not set, the code falls back to the demo credential in `station_stats_api/lambda_handler.py`; do not rely on that fallback for public deployments.

Snapshot body shape:

```json
{
  "station_id": "demo_station_01",
  "timestamp": "2026-06-12T18:00:00Z",
  "vehicles_in_queue": 4,
  "vehicles_in_bay": 2,
  "active_lanes": 2,
  "average_queue_wait_minutes": 6.2,
  "average_inspection_minutes": 6.2,
  "estimated_public_wait_minutes": 12.4,
  "throughput_per_hour": 19,
  "slowest_lane_id": null,
  "confidence_score": 0.82
}
```

## Deploy the API with AWS SAM

From the repository root:

```bash
sam build --template-file infra/template.yaml

sam deploy --guided \
  --stack-name opus-lanesight-station-stats \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    StageName=prod \
    TableName=StationStatistics \
    StationStatsClientCredentials=<replace-with-demo-or-pilot-credential>
```

After deployment, capture the API URL:

```bash
sam list stack-outputs --stack-name opus-lanesight-station-stats
```

Use the `ApiBaseUrl` output as the dashboard `apiBaseUrl` and desktop app API base URL.

Optional custom domain deployment:

```bash
sam deploy \
  --stack-name opus-lanesight-station-stats \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    StageName=prod \
    TableName=StationStatistics \
    StationStatsClientCredentials=<credential> \
    DomainName=stats.example.com \
    CertificateArn=arn:aws:acm:REGION:ACCOUNT:certificate/CERTIFICATE_ID
```

The custom-domain certificate must be in the same region as the regional API Gateway domain.

## Configure snapshot publishing from the desktop app

The desktop app publishes snapshots only when both API settings are configured. If left blank, processing still works locally and snapshots are not submitted.

Edit `%LOCALAPPDATA%\OpusLaneSight\settings.json` and set:

```json
{
  "api_base_url": "https://your-api-id.execute-api.us-west-2.amazonaws.com/prod",
  "client_credential": "your-demo-or-pilot-credential"
}
```

Restart the app after editing the settings file.

## Deploy the public dashboard

The dashboard is static; there is no build step.

1. Create a deployment config:

   ```bash
   cp src/config.example.js src/config.js
   ```

2. Edit `src/config.js`:

   ```js
   window.OPUS_DEMO_CONFIG = {
     apiBaseUrl: "https://your-api-id.execute-api.us-west-2.amazonaws.com/prod",
     clientCredential: "your-demo-or-pilot-credential"
   };
   ```

3. Run locally:

   ```bash
   python -m http.server 8080 --directory src
   ```

   Open `http://localhost:8080`.

4. Publish to S3 and serve with CloudFront for HTTPS:

   ```bash
   aws s3 mb s3://opus-lanesight-public-dashboard-demo
   aws s3 sync src/ s3://opus-lanesight-public-dashboard-demo/ --delete
   ```

   Configure CloudFront with the S3 bucket as the origin and `index.html` as the default root object.

Security note: `src/config.js` is downloaded by every browser visitor. Any credential placed there is public. For a real public deployment, put a server-side backend or edge function between the browser and the protected Station Stats API instead of exposing a write-capable credential in static JavaScript.

## Tests

```bash
pytest
npm test
```

The Python test suite covers the pipeline helpers, desktop app logic, station metrics, API handlers, and client submission behavior. The JavaScript tests cover the public dashboard state, configuration, API client, presentation, and smoke checks.

## Privacy and data handling

- The intended public wait-time workflow uses temporary anonymous vehicle session IDs.
- OCR is optional and should remain disabled for privacy-preserving demos and pilots.
- The public dashboard displays aggregate wait-time information only.
- The Station Stats API stores the latest station metric snapshot, not video frames or vehicle images.

## Roadmap

- Polygon-based lane and zone calibration.
- Separate queue, bay, and exit timing.
- Better active-lane detection instead of manual lane count.
- Production credential storage through AWS Secrets Manager or SSM Parameter Store.
- CloudFront/API integration that avoids exposing credentials to public browsers.
- Grounded AI operations summaries from measured station metrics.
- Historical reporting and multi-station operations views.
