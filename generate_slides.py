"""
Generate Opus LaneSight presentation as a PowerPoint (.pptx) file.
Uses the Opus brand colors and clean layout.
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# Opus brand colors
TEAL_DARK = RGBColor(0x00, 0x48, 0x51)
TEAL = RGBColor(0x00, 0x96, 0x8F)
GREEN = RGBColor(0x93, 0xD5, 0x00)
CYAN = RGBColor(0x41, 0xBB, 0xC9)
BLUE = RGBColor(0x00, 0xA0, 0xE0)
ORANGE = RGBColor(0xFF, 0x82, 0x00)
CHARCOAL = RGBColor(0x13, 0x1E, 0x29)
GRAY = RGBColor(0x54, 0x56, 0x5A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BG_LIGHT = RGBColor(0xF4, 0xF7, 0xF7)


def set_slide_bg(slide, color):
    """Set slide background to a solid color."""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_title_slide(prs, title, subtitle):
    """Add a title slide with gradient-style dark background."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank
    set_slide_bg(slide, TEAL_DARK)

    # Title
    txBox = slide.shapes.add_textbox(Inches(1), Inches(2.5), Inches(8), Inches(1.5))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(44)
    p.font.bold = True
    p.font.color.rgb = WHITE
    p.alignment = PP_ALIGN.LEFT

    # Subtitle
    txBox2 = slide.shapes.add_textbox(Inches(1), Inches(4.2), Inches(8), Inches(1))
    tf2 = txBox2.text_frame
    tf2.word_wrap = True
    p2 = tf2.paragraphs[0]
    p2.text = subtitle
    p2.font.size = Pt(20)
    p2.font.color.rgb = GREEN
    p2.alignment = PP_ALIGN.LEFT

    return slide


def add_content_slide(prs, title, bullets, note=None):
    """Add a content slide with title and bullet points."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank
    set_slide_bg(slide, BG_LIGHT)

    # Title bar
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(10), Inches(1.1))
    shape.fill.solid()
    shape.fill.fore_color.rgb = TEAL_DARK
    shape.line.fill.background()

    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(0.15), Inches(9), Inches(0.9))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = WHITE

    # Bullets
    txBox2 = slide.shapes.add_textbox(Inches(0.7), Inches(1.4), Inches(8.6), Inches(5.5))
    tf2 = txBox2.text_frame
    tf2.word_wrap = True

    for i, bullet in enumerate(bullets):
        if i == 0:
            p = tf2.paragraphs[0]
        else:
            p = tf2.add_paragraph()

        # Handle indented bullets
        if bullet.startswith("  "):
            p.text = bullet.strip()
            p.level = 1
            p.font.size = Pt(16)
            p.font.color.rgb = GRAY
        else:
            p.text = bullet
            p.level = 0
            p.font.size = Pt(18)
            p.font.color.rgb = CHARCOAL

        p.space_after = Pt(8)

    # Optional note at bottom
    if note:
        txBox3 = slide.shapes.add_textbox(Inches(0.7), Inches(6.6), Inches(8.6), Inches(0.6))
        tf3 = txBox3.text_frame
        tf3.word_wrap = True
        p3 = tf3.paragraphs[0]
        p3.text = note
        p3.font.size = Pt(12)
        p3.font.italic = True
        p3.font.color.rgb = TEAL

    return slide


def add_table_slide(prs, title, headers, rows):
    """Add a slide with a table."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, BG_LIGHT)

    # Title bar
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(10), Inches(1.1))
    shape.fill.solid()
    shape.fill.fore_color.rgb = TEAL_DARK
    shape.line.fill.background()

    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(0.15), Inches(9), Inches(0.9))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = WHITE

    # Table
    n_rows = len(rows) + 1
    n_cols = len(headers)
    left = Inches(0.5)
    top = Inches(1.5)
    width = Inches(9)
    height = Inches(0.4 * n_rows)

    table_shape = slide.shapes.add_table(n_rows, n_cols, left, top, width, height)
    table = table_shape.table

    # Header row
    for i, h in enumerate(headers):
        cell = table.cell(0, i)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = TEAL
        for paragraph in cell.text_frame.paragraphs:
            paragraph.font.size = Pt(14)
            paragraph.font.bold = True
            paragraph.font.color.rgb = WHITE

    # Data rows
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            cell = table.cell(r_idx + 1, c_idx)
            cell.text = str(val)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.font.size = Pt(13)
                paragraph.font.color.rgb = CHARCOAL

    return slide


def add_quote_slide(prs, quote, attribution=None):
    """Add a slide with a prominent quote."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_slide_bg(slide, TEAL_DARK)

    txBox = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(3))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = f'"{quote}"'
    p.font.size = Pt(24)
    p.font.italic = True
    p.font.color.rgb = WHITE
    p.alignment = PP_ALIGN.CENTER

    if attribution:
        txBox2 = slide.shapes.add_textbox(Inches(1), Inches(5.2), Inches(8), Inches(0.8))
        tf2 = txBox2.text_frame
        p2 = tf2.paragraphs[0]
        p2.text = attribution
        p2.font.size = Pt(16)
        p2.font.color.rgb = GREEN
        p2.alignment = PP_ALIGN.CENTER

    return slide


def main():
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    # --- Slide 1: Title ---
    add_title_slide(prs, "Opus LaneSight", "AI-Powered Station Wait-Time Intelligence")

    # --- Slide 2: The Problem ---
    add_content_slide(prs, "The Problem", [
        "Specialized LPR camera hardware is expensive to deploy and maintain",
        "Plate-based systems capture identity events, not full station-flow behavior",
        "Station managers lack real-time lane-level queue insight",
        "Public wait estimates don't reflect actual current queue behavior",
        "Privacy expectations favor anonymous tracking",
        "",
        "How can we deliver rich, real-time wait-time intelligence",
        "using standard cameras — without reading license plates?",
    ])

    # --- Slide 3: The Solution ---
    add_content_slide(prs, "The Solution: Opus LaneSight", [
        "Uses existing station HD IP cameras (no new hardware)",
        "Detects and tracks vehicles with anonymous temporary session IDs",
        "Calculates real-time wait estimates from actual queue behavior",
        "Dual detection: Local YOLOv8 (free) or AWS Rekognition (cloud)",
        "Provides operational dashboard for station managers",
        "Publishes motorist-friendly public wait estimates",
        "Privacy-preserving by design: no plate reading, no driver identification",
    ], note="Standard HD IP cameras + AWS AI = anonymous wait-time intelligence")

    # --- Slide 4: Architecture ---
    add_content_slide(prs, "Architecture", [
        "INPUT: Video files (MP4) or Live streams (RTSP/RTMP/HTTP)",
        "",
        "DETECTION: YOLOv8 (local, free, fast) ↔ AWS Rekognition (cloud, scalable)",
        "  Switchable via --detector flag",
        "",
        "TRACKING: DeepSORT with Kalman filter + appearance re-identification",
        "  Handles occlusions, maintains identity across frames",
        "",
        "METRICS: Queue depth, wait time, throughput, bottleneck detection",
        "",
        "OUTPUT: Internal dashboard (operations) + Public wait card (motorists)",
    ])

    # --- Slide 5: AWS Services ---
    add_table_slide(prs, "AWS Services Used", [
        "Service", "Role", "Status"
    ], [
        ["Amazon Rekognition", "Vehicle detection (DetectLabels)", "✓ Implemented"],
        ["Amazon Rekognition", "Plate region localization (DetectText)", "✓ Implemented"],
        ["Amazon Bedrock", "AI-generated station summaries", "Planned"],
        ["Amazon S3", "Video and frame storage", "Planned"],
        ["DynamoDB", "Session and metric persistence", "Planned"],
        ["API Gateway", "Public wait-time REST API", "Planned"],
    ])

    # --- Slide 6: Adaptive Cost Optimization ---
    add_table_slide(prs, "Smart Cost Optimization: Adaptive Detection", [
        "Scene State", "Detection Interval", "Resolution", "Cost Savings"
    ], [
        ["Warmup (first 2.5s)", "Every frame", "1920px", "Full accuracy"],
        ["Stable queue", "Every 10th frame", "960px", "90% savings"],
        ["Empty (no vehicles)", "Every 30th frame", "640px", "97% savings"],
        ["Activity spike", "Every frame (instant)", "1920px", "Instant react"],
    ])

    # --- Slide 7: Tracking Intelligence ---
    add_content_slide(prs, "Tracking Intelligence: Handling Occlusions", [
        "Challenge: Vehicles blocking each other at inspection stations",
        "",
        "Three-layer approach:",
        "  1. Kalman filter prediction — tracks survive 4 seconds during occlusion",
        "  2. Gallery re-identification — appearance + spatial matching revives tracks",
        "  3. Plate-text deduplication — merges any remaining duplicates",
        "",
        "Result: Same vehicle blocked for 3+ seconds",
        "  → Still counted as ONE vehicle with continuous wait time",
        "",
        "Additional techniques:",
        "  • Hungarian algorithm for globally optimal track assignment",
        "  • HSV color histograms on spatial grid for appearance matching",
        "  • OCR-aware text normalization for plate similarity (7↔1, O↔0)",
    ])

    # --- Slide 8: Privacy ---
    add_content_slide(prs, "Privacy by Design", [
        "No plate reading — OCR disabled in production (--no-ocr)",
        "No driver identification — only anonymous integer session IDs",
        "Temporary sessions — IDs expire when vehicle exits camera",
        "Aggregate only — public display shows wait estimate, not individual vehicles",
        "No data retention — session data discarded after vehicle leaves",
    ], note="LaneSight uses temporary anonymous vehicle session IDs. License plates and driver identities are not read or stored.")

    # --- Slide 9: Live Demo ---
    add_content_slide(prs, "Live Demo", [
        "What you'll see:",
        "  1. Video processed through the detection pipeline",
        "  2. Real-time vehicle detection with bounding boxes and IDs",
        "  3. Wait-time calculation (enter time → leave time → duration)",
        "  4. Internal dashboard with queue metrics and status",
        "  5. Public wait-time card (motorist-friendly display)",
        "",
        "Demo commands:",
        "  # Local YOLO (fast, free)",
        "  python main.py --video demo.mp4 --no-ocr --show",
        "",
        "  # AWS Rekognition with adaptive optimization",
        "  python main.py --video demo.mp4 --detector rekognition --auto-adjust --show",
    ])

    # --- Slide 10: Wait-Time Formula ---
    add_content_slide(prs, "Wait-Time Calculation", [
        "Formula:",
        "  Public Wait = Queue Depth × Avg Inspection Time ÷ Active Lanes",
        "",
        "Example:",
        "  9 vehicles × 6.2 min ÷ 3 lanes = 18.6 min → Public: 19 minutes",
        "",
        "Enhanced with:",
        "  • Rolling 15-minute average inspection duration",
        "  • Confidence scoring from detection quality",
        "  • Smoothing to prevent volatile public estimates",
        "  • Automatic fallback when confidence is low",
        "",
        "Key principle: calculation is deterministic, not AI-generated",
    ])

    # --- Slide 11: Business Impact ---
    add_content_slide(prs, "Business Impact", [
        "COST REDUCTION",
        "  • Eliminates specialized LPR cameras ($5K–15K per lane)",
        "  • Uses existing HD IP cameras already at stations",
        "  • Rekognition: ~$0.10/minute with adaptive optimization",
        "",
        "CUSTOMER EXPERIENCE",
        "  • Accurate real-time wait estimates help motorists plan",
        "  • Reduces frustration from unexpected delays",
        "",
        "OPERATIONAL EXCELLENCE",
        "  • Station managers see queue bottlenecks in real time",
        "  • Lane-level metrics identify underperforming lanes",
        "  • Data supports staffing and process improvement",
        "",
        "PROGRAM TRANSPARENCY",
        "  • Measurable service levels across all stations",
    ])

    # --- Slide 12: Guardrails ---
    add_content_slide(prs, "Guardrails and Trust", [
        "AI Guardrails:",
        "  • Wait-time calculation is deterministic (not AI-generated)",
        "  • Bedrock summaries grounded only in measured metrics",
        "  • Confidence scores shown in internal views",
        "  • Low-confidence states suppress public estimates",
        "",
        "Operational Guardrails:",
        "  • Camera issues → 'wait time unavailable' fallback",
        "  • Manual lane-count override available",
        "  • Estimates smoothed over rolling windows (no volatile jumps)",
        "  • Station manager alerted before public-facing changes",
    ])

    # --- Slide 13: Risks ---
    add_table_slide(prs, "Risks and Mitigations", [
        "Risk", "Mitigation"
    ], [
        ["Vehicle occlusion", "Kalman prediction + gallery re-ID + elevated cameras"],
        ["Identity swaps", "Appearance features + motion continuity"],
        ["Poor lighting/weather", "Confidence scores + fallback estimates"],
        ["API cost growth", "Adaptive controller (90-97% reduction during idle)"],
        ["Estimate volatility", "Rolling-window smoothing before publishing"],
        ["Privacy concerns", "No plate reading + anonymous IDs + no retention"],
    ])

    # --- Slide 14: Next 30 Days ---
    add_content_slide(prs, "Next 30 Days", [
        "1. Obtain approved, anonymized inspection-station footage",
        "2. Define lane and zone calibration workflow per station",
        "3. Compare LaneSight estimates against existing wait-time data",
        "4. Measure accuracy across station types, times, and weather",
        "5. Add confidence thresholds and fallback rules",
        "6. Build pilot dashboard for one production station",
        "7. Define integration with existing public wait-time systems",
        "8. Cost comparison: LPR-based vs. IP-camera-based instrumentation",
    ])

    # --- Slide 15: Closing ---
    add_quote_slide(
        prs,
        "Making the world a safer and cleaner place — one queue at a time.",
        "Opus LaneSight • AI-Powered Station Wait-Time Intelligence"
    )

    # Save
    output_path = "Opus_LaneSight_Presentation.pptx"
    prs.save(output_path)
    print(f"Presentation saved to: {output_path}")
    print(f"Slides: {len(prs.slides)}")


if __name__ == "__main__":
    main()
