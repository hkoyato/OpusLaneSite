---
inclusion: always
---
# Opus LaneSight — UI Guidelines

## 1. Purpose

These guidelines define the visual and interaction direction for the Opus LaneSight hackathon prototype. The goal is to make the product feel like a credible Opus-aligned application while keeping the design simple enough to implement in a two-day sprint.

The interface should communicate operational clarity, trust, safety, environmental responsibility, and technical competence. It should look modern, calm, and functional rather than flashy or consumer-generic.

## 2. Brand foundation

Opus LaneSight should visually support the Opus mission:

> Making the world a safer and cleaner place.

The interface should reinforce three ideas:

1. **Cleaner and safer inspection programs** — the product helps inspection stations operate more efficiently.
2. **Operational excellence** — station managers get clear, actionable visibility into queue flow.
3. **Public confidence** — motorists receive accurate, transparent wait-time estimates.

## 3. Product naming and brand hierarchy

Use the product name as:

```text
Opus LaneSight
```

Use the descriptor as:

```text
AI-powered station wait-time intelligence
```

Do not create a new standalone logo for LaneSight. Treat LaneSight as a product name under the Opus masterbrand.

### Correct usage

```text
[Official Opus logo]

Opus LaneSight
AI-powered station wait-time intelligence
```

### Avoid

```text
[Modified Opus logo attached to LaneSight]
[Opus globe used alone as a product icon]
[Stretched or recolored Opus logo]
[All-caps product lockup]
```

## 4. Logo usage

Use official Opus logo artwork only. Do not recreate, modify, stretch, recolor, add effects to, or separate the Opus wordmark and globe.

Guidelines:

- Prefer the horizontal Opus logo when space allows.
- Use the stacked version only when space restrictions require it.
- Maintain clear space around the logo approximately equal to the width of the “S” in OPUS.
- Do not use the globe alone as an icon.
- Do not combine the Opus logo and “LaneSight” into a new custom logo.
- Do not apply shadows, glows, bevels, gradients, outlines, or animation effects to the official logo.

## 5. Color palette

Use the Opus color palette consistently. Keep the interface primarily teal, green, blue, white, and neutral gray. Use orange only for important warnings or highlights.

### Core design tokens

```css
:root {
  --opus-teal-dark: #004851;
  --opus-green: #93D500;
  --opus-teal: #00968F;
  --opus-cyan: #41BBC9;
  --opus-blue: #00A0E0;
  --opus-navy: #004A98;
  --opus-orange: #FF8200;
  --opus-charcoal: #131E29;
  --opus-gray: #54565A;
  --opus-bg: #F4F7F7;
  --opus-white: #FFFFFF;
}
```

### Recommended usage

| UI element | Recommended color |
|---|---|
| Primary header / navigation | `#004851` |
| Primary CTA button | `#00968F` |
| Success / normal status | `#93D500` |
| Informational metrics | `#00A0E0` or `#41BBC9` |
| Secondary charts | `#004A98` |
| Warning / attention state | `#FF8200` |
| Main text | `#131E29` |
| Secondary text | `#54565A` |
| Page background | `#F4F7F7` or `#FFFFFF` |

### Status color system

| Status | Label | Color |
|---|---|---|
| Good | Normal wait | `#93D500` |
| Moderate | Moderate wait | `#00A0E0` |
| Attention | Queue building | `#FF8200` |
| Unknown | Data unavailable | `#54565A` |

### Color rules

- Do use teal and green as the dominant brand colors.
- Do use blue/cyan for informational data visualizations.
- Do use orange sparingly for warnings, alerts, or key callouts.
- Do not use red as a dominant color unless absolutely necessary for a critical error state.
- Do not use random bright colors outside the Opus palette.
- Do not use low-contrast text on gradients or imagery.

## 6. Gradients

Use linear gradients to create motion and positivity. Avoid radial gradients and dark, swampy visual treatments.

Recommended gradient:

```css
background: linear-gradient(135deg, #004851 0%, #00968F 58%, #93D500 100%);
```

Use gradients for:

- Title slide hero area.
- Dashboard header.
- Public wait-time hero card.
- Empty states or product intro screens.

Avoid gradients for:

- Body text backgrounds.
- Dense data tables.
- Small metric cards where legibility matters.

## 7. Typography

The Opus brand type system uses Brokman for headlines and Roboto for body copy. For the hackathon prototype, use Roboto throughout unless Brokman is officially available.

### Font stack

```css
font-family: "Roboto", Arial, Helvetica, sans-serif;
```

### Type hierarchy

| Role | Size | Weight | Notes |
|---|---:|---:|---|
| Page title | 36-44px | 700 | Use sentence case, not all caps. |
| Section title | 24-28px | 700 | Deep teal or charcoal. |
| Card title | 16-18px | 600 | Clear, concise labels. |
| Body text | 14-16px | 400 | Use charcoal or gray. |
| Metric value | 32-48px | 700 | Large and readable. |
| Caption / timestamp | 12-13px | 400 | Gray text. |

### Typography rules

- Use sentence case for headings.
- Avoid all-caps headlines.
- Keep labels short and functional.
- Use large metric values for dashboard readability.
- Do not use decorative or novelty fonts.
- Maintain strong contrast for accessibility.

## 8. Imagery and visual style

Use imagery that reflects safe, clean, modern vehicle inspection and positive environmental impact.

### Preferred imagery

- Clean inspection lanes.
- Vehicles in orderly queues.
- Modern station interiors.
- Roads, nature, and clean air themes.
- Operators or inspectors using professional equipment.
- Camera/AI overlays on neutral vehicle footage.

### Avoid imagery

- Heavy smoke, pollution, or dirty exhaust imagery.
- Dystopian surveillance visuals.
- Aggressive law-enforcement imagery.
- Dark, cluttered, low-quality station photos.
- Images that show readable license plates unless approved and anonymized.

## 9. Layout principles

The interface should be clean, modular, and information-dense without feeling crowded.

### Recommended structure

```text
Top navigation / product header
        ↓
Station status summary
        ↓
Primary metrics cards
        ↓
Live lane view + operations summary
        ↓
Lane metrics table / charts
```

### Spacing

Use an 8px spacing system:

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 24px;
--space-6: 32px;
--space-7: 48px;
```

### Card style

```css
.card {
  background: #FFFFFF;
  border: 1px solid rgba(19, 30, 41, 0.08);
  border-radius: 14px;
  box-shadow: 0 8px 24px rgba(19, 30, 41, 0.08);
  padding: 20px;
}
```

## 10. Internal dashboard requirements

The internal dashboard should answer four questions immediately:

1. What is the current public wait estimate?
2. How many vehicles are in queue?
3. Which lanes are active or slow?
4. What action, if any, should the station manager take?

### Required dashboard components

#### Header

- Opus logo.
- Product name: Opus LaneSight.
- Station name.
- Last updated timestamp.
- Data confidence status.

#### Metric cards

Minimum cards:

- Estimated public wait.
- Vehicles in queue.
- Active lanes.
- Average inspection time.
- Throughput per hour.
- Slowest lane / bottleneck.

#### Live lane view

Show video or frame preview with overlays:

- Vehicle bounding boxes.
- Anonymous vehicle IDs.
- Lane names.
- Zone names.
- Time-in-zone labels.
- Confidence indicator.

Example overlay label:

```text
Vehicle 07 · Lane 2 · Queue 06:42
```

#### Lane metrics table

| Lane | Vehicles | Avg queue | Avg inspection | Status |
|---|---:|---:|---:|---|
| Lane 1 | 3 | 11 min | 6.1 min | Normal |
| Lane 2 | 5 | 18 min | 7.8 min | Queue building |
| Lane 3 | 1 | 8 min | 5.9 min | Normal |

#### AI station summary

Include a Bedrock-generated summary card, but make it clear it is generated from measured metrics.

Example:

```text
Station status: Moderate wait. Lane 2 is moving slower than the other lanes, with an average queue time of 18 minutes. Current public wait estimate is 19 minutes based on 9 vehicles in queue, 3 active lanes, and a recent average inspection duration of 6.2 minutes.
```

## 11. Public wait-time card requirements

The public card should be simpler than the internal dashboard. Do not expose internal operational details unless they are useful to motorists.

### Required fields

- Station name.
- Estimated wait time.
- Queue status.
- Open lanes.
- Last updated timestamp.
- Optional confidence/freshness indicator.

### Example copy

```text
Demo Inspection Station

Current estimated wait
18 minutes

Queue status: Moderate
Open lanes: 3 of 4
Last updated: 1:42 PM

Powered by Opus LaneSight
```

### Public card tone

- Calm.
- Clear.
- Non-technical.
- No internal model jargon.
- No unnecessary precision.

Use “18 minutes,” not “18.42 minutes.”

## 12. Data visualization guidance

### Recommended charts

- Bar chart for wait time by lane.
- Line chart for wait estimate over time.
- Simple throughput trend.
- Zone dwell-time comparison.

### Chart rules

- Use Opus teal, green, blue, and cyan.
- Use orange only for attention states.
- Label charts directly.
- Avoid 3D charts.
- Avoid rainbow palettes.
- Avoid cluttered legends.
- Always include units such as minutes or vehicles/hour.

## 13. Interaction states

### Loading state

Use calm operational language:

```text
Processing station footage…
Detecting vehicles and assigning lanes.
```

### Empty state

```text
No vehicles currently detected.
Wait-time estimate will update when station activity resumes.
```

### Low-confidence state

```text
Low detection confidence.
Public wait-time estimate is temporarily withheld. Review camera angle or lighting.
```

### Error state

```text
Unable to process the latest frame.
The previous valid wait-time estimate is still displayed internally for reference.
```

## 14. Accessibility

- Maintain readable contrast between text and background.
- Do not rely only on color to communicate status; pair color with labels.
- Use large metric values for at-a-glance readability.
- Provide descriptive labels for icons.
- Use sentence case and clear wording.
- Make dashboard tables readable at presentation-screen size.

## 15. Voice and tone

The product voice should be:

- Clear.
- Calm.
- Operational.
- Trustworthy.
- Confident but not exaggerated.

### Preferred wording

- “Estimated public wait.”
- “Vehicles in queue.”
- “Active lanes.”
- “Lane 2 is moving slower than average.”
- “Low confidence — review before publishing.”

### Avoid wording

- “Surveillance mode active.”
- “Tracking motorists.”
- “AI knows exactly where every vehicle is.”
- “Guaranteed wait time.”
- “Instantly replaces LPR.”

## 16. Privacy and trust UI patterns

Include privacy-preserving language in the prototype and deck.

Recommended trust note:

```text
LaneSight uses temporary anonymous vehicle session IDs for wait-time calculation. License plates and driver identities are not read or stored in this prototype.
```

Show this in:

- About modal.
- Trust/guardrails slide.
- Internal dashboard footer.
- README.

## 17. Prototype screens

### Screen 1: Landing / station selector

Purpose: Let the user select a demo station or upload a video.

Key elements:

- Opus logo.
- Opus LaneSight title.
- Short product descriptor.
- “Start demo” button.
- “Upload footage” button, if implemented.

### Screen 2: Processing view

Purpose: Show that AI is detecting vehicles.

Key elements:

- Frame preview.
- Processing progress.
- Vehicle count detected.
- Current frame/time.

### Screen 3: Internal dashboard

Purpose: Main demo screen for judges.

Key elements:

- Metric cards.
- Lane overlay view.
- Lane table.
- Bedrock summary.
- Public wait-time preview.

### Screen 4: Public wait-time page

Purpose: Show what motorists would see.

Key elements:

- Station name.
- Large wait-time number.
- Queue status.
- Last updated.
- Powered by Opus LaneSight.

## 18. Demo presentation guidance

For a 5-minute demo, spend most of the time on the working prototype.

Suggested timing:

| Time | Segment |
|---:|---|
| 0:00-0:30 | Problem and why Opus cares. |
| 0:30-1:00 | Solution and AWS architecture. |
| 1:00-3:30 | Live demo. |
| 3:30-4:15 | Business impact. |
| 4:15-4:45 | Guardrails and trust. |
| 4:45-5:00 | Next steps. |

## 19. Implementation-ready React style suggestions

### Page shell

```jsx
<div className="app-shell">
  <header className="topbar">
    <img src="/opus-logo.svg" alt="Opus" className="logo" />
    <div>
      <h1>Opus LaneSight</h1>
      <p>AI-powered station wait-time intelligence</p>
    </div>
  </header>
  <main>{children}</main>
</div>
```

### CSS starter

```css
body {
  margin: 0;
  font-family: "Roboto", Arial, Helvetica, sans-serif;
  color: #131E29;
  background: #F4F7F7;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 20px 32px;
  background: linear-gradient(135deg, #004851 0%, #00968F 58%, #93D500 100%);
  color: #FFFFFF;
}

.logo {
  height: 36px;
  width: auto;
}

.metric-card {
  background: #FFFFFF;
  border: 1px solid rgba(19, 30, 41, 0.08);
  border-radius: 14px;
  box-shadow: 0 8px 24px rgba(19, 30, 41, 0.08);
  padding: 20px;
}

.metric-label {
  color: #54565A;
  font-size: 14px;
}

.metric-value {
  color: #004851;
  font-size: 42px;
  font-weight: 700;
  line-height: 1;
}

.status-normal {
  color: #004851;
  border-left: 5px solid #93D500;
}

.status-moderate {
  color: #004851;
  border-left: 5px solid #00A0E0;
}

.status-attention {
  color: #004851;
  border-left: 5px solid #FF8200;
}
```

## 20. Final design checklist

Before demo submission, verify:

- The official Opus logo is used correctly and not modified.
- The product name appears as “Opus LaneSight.”
- The UI uses Opus teal/green/blue palette.
- Orange is used only for alerts or emphasis.
- Headings are sentence case, not all caps.
- Public wait-time copy is simple and motorist-friendly.
- Internal dashboard shows actionable operational metrics.
- Privacy note says plates and driver identities are not read or stored.
- AI summary is grounded in calculated metrics.
- The deck follows a clean Opus-style visual system.
