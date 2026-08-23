---
name: SMCP Operator Console
description: Operational evidence, without theater.
colors:
  background: "oklch(1 0 0)"
  surface: "oklch(0.975 0.004 260)"
  surface-strong: "oklch(0.945 0.008 265)"
  ink: "oklch(0.22 0.018 265)"
  muted: "oklch(0.48 0.018 265)"
  border: "oklch(0.89 0.008 265)"
  primary: "oklch(0.42 0.11 270)"
  signal: "oklch(0.63 0.14 235)"
  success: "oklch(0.55 0.12 150)"
  warning: "oklch(0.72 0.14 75)"
  danger: "oklch(0.55 0.18 25)"
---

# Design System: SMCP Operator Console

## 1. Overview

**Creative North Star: "The Accountable Ledger"**

The console behaves like a well-maintained engineering record: the dominant surface is a ledger, every state is named, and detail opens in place without disorienting the operator. It is optimized for a well-lit technical room where an experienced operator scans many jobs and then drills into one chain of evidence.

The system rejects decorative sci-fi, terminal cosplay, neon telemetry, vanity metrics, and interchangeable SaaS card grids. Technical confidence comes from aligned facts, clear state transitions, and inspectable provenance—not from visual theater.

**Key Characteristics:**

- A compact navigation rail and a wide command ledger.
- Progressive disclosure through an integrated evidence drawer.
- Restrained color reserved for actions, selection, focus, and semantic state.
- One humanist system sans, with monospace only for machine identifiers.
- Flat surfaces separated by spacing and crisp rules instead of decorative shadow.

## 2. Colors

True white and cool indigo-tinted neutrals keep the room bright; deep indigo provides the single product voice while semantic colors carry explicit status.

### Primary

- **Control Indigo** (`oklch(0.42 0.11 270)`): Primary actions, current navigation, selected records, and focus. It occupies less than 10% of a screen.

### Secondary

- **Signal Blue** (`oklch(0.63 0.14 235)`): Active/running state and informational links; never decoration.

### Neutral

- **Evidence White** (`oklch(1 0 0)`): Main ledger background.
- **Instrument Surface** (`oklch(0.975 0.004 260)`): Navigation, filters, grouped headers, and the integrated drawer.
- **Graphite Ink** (`oklch(0.22 0.018 265)`): Primary text.
- **Measured Muted** (`oklch(0.48 0.018 265)`): Secondary text that remains AA-readable.
- **Rule** (`oklch(0.89 0.008 265)`): Dividers and control outlines.

### Named Rules

**The Evidence-Only Color Rule.** Color appears only when it communicates action, selection, focus, or state; it never decorates an otherwise neutral surface.

## 3. Typography

**Display Font:** system-ui (with `-apple-system`, `BlinkMacSystemFont`, and `Segoe UI` fallback)
**Body Font:** system-ui (same fallback stack)
**Label/Mono Font:** `ui-monospace` (with `SFMono-Regular`, `Cascadia Code`, and `Roboto Mono` fallback)

**Character:** Familiar system forms keep the interface immediate and stable. Hierarchy comes from weight, spacing, and a fixed product scale; monospace marks machine-authored values only.

### Hierarchy

- **Display** (700, `1.75rem`, 1.15): Page title only.
- **Headline** (700, `1.25rem`, 1.25): Drawer record identity and major empty states.
- **Title** (650, `1rem`, 1.35): Section and grouped-region headings.
- **Body** (400, `1rem`, 1.5): Explanations and forms, capped at 70ch.
- **Compact UI** (400–650, `0.875rem`, 1.4): Table cells, navigation, buttons, and metadata.
- **Caption** (500, `0.75rem`, 1.4): Timestamps and supporting labels.

### Named Rules

**The Machine-Value Rule.** IDs, hashes, byte counts, and timestamps use monospace with tabular numerals; prose and controls never do.

## 4. Elevation

The console is flat by default. Depth comes from tonal layering and full-width dividers. A compact shadow is permitted only for top-layer popovers or dialogs; the ledger and drawer use no shadow.

### Shadow Vocabulary

- **Top layer** (`0 4px 8px oklch(0.22 0.018 265 / 0.12)`): Menus and dialogs only.

### Named Rules

**The Flat Record Rule.** Data surfaces remain flat at rest; selection uses a tonal wash and full perimeter focus treatment, not a floating card.

## 5. Components

### Buttons

- **Shape:** restrained rectangle (`8px` radius), minimum `44px` target.
- **Primary:** Control Indigo with white text and `12px 16px` padding.
- **Hover / Focus:** darker indigo hover; consistent 2px Signal Blue focus ring with 2px offset.
- **Secondary / Ghost:** white or transparent with a Rule outline; destructive actions use explicit danger text and icon.

### Chips

- **Style:** compact 6px radius, semantic pale surface, explicit icon and text.
- **State:** selected views use a bottom rule or surface wash rather than full-pill treatment.

### Cards / Containers

- **Corner Style:** 12px only for isolated empty/error regions; ledger regions remain square and ruled.
- **Background:** Evidence White or Instrument Surface.
- **Shadow Strategy:** none at rest.
- **Border:** full 1px Rule when a boundary is required.
- **Internal Padding:** 12px compact groups, 16–24px major groups.

### Inputs / Fields

- **Style:** white, 8px radius, full Rule outline, visible label.
- **Focus:** 2px Signal Blue ring and offset.
- **Error / Disabled:** explicit icon, message, and state text; color is supplementary.

### Navigation

The desktop rail is persistent and compact. Active location uses an indigo-tinted wash, matching icon, and `aria-current`; mobile uses a labeled top bar and dismissible drawer while preserving the same information architecture.

### Command Ledger

Grouped headers organize Identity, Execution, Evidence, and Output. Rows are links with keyboard-visible selection. One record expands into a full-width drawer containing lifecycle, candidate comparison, and valid next actions.

## 6. Do's and Don'ts

### Do:

- **Do** reserve Control Indigo for primary action, current selection, and focus.
- **Do** pair every status color with an icon and explicit label.
- **Do** align machine values with monospace and tabular numerals.
- **Do** keep 44px targets even when desktop visuals are compact.
- **Do** make unavailable, pending, failed, empty, and partial evidence explicit.

### Don't:

- **Don't** use decorative sci-fi control rooms, neon telemetry, star-field backgrounds, or fictional mission language.
- **Don't** use generic SaaS dashboards made from interchangeable rounded cards, oversized vanity metrics, or decorative gradients.
- **Don't** use terminal cosplay, dense monospace everywhere, or dark mode merely because the product is technical.
- **Don't** claim quality, readiness, or model capability without measured platform evidence.
- **Don't** use colored side-stripe borders, glassmorphism, wide shadows, or pill-shaped controls everywhere.
