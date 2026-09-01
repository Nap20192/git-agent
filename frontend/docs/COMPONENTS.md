# git-agent frontend — Component Catalog

Shared UI lives in `src/components/`. Primitives are exported (with their prop types) from
`src/components/primitives/index.ts`:

```tsx
import {
  Panel, PanelHeader, Badge, Button, TextInput, StatusDot, Sparkline, Meter,
  StatusBadge, Tabs, CodeBlock, KeyValueList, EntityList, Drawer,
} from "@/components/primitives";
```

Colors are never passed as raw values — components take a `tone` prop resolved through the tone
system (see [Tone system](#tone-system)).

## Primitives

### Panel

Bordered surface card — the base container for every boxed section.

| Prop | Type | Default | Description |
|---|---|---|---|
| `variant` | `"panel" \| "panel2"` | `"panel"` | Background surface. `panel` is the default card, `panel2` is inset. |
| `soft` | `boolean` | `false` | Softer border for secondary cards. |
| `className` | `string` | — | Extra class(es). |
| `style` | `CSSProperties` | — | Inline style overrides. |
| `children` | `ReactNode` | required | Panel content. |

### PanelHeader

Standard panel header: leading glyph + spaced-out title + optional right-aligned slot.

| Prop | Type | Default | Description |
|---|---|---|---|
| `icon` | `ReactNode` | — | Leading glyph (e.g. `"◈"`, `"$_"`). |
| `iconTone` | `Tone` | `"amber"` | Tone for the glyph. |
| `title` | `ReactNode` | required | Header title. |
| `right` | `ReactNode` | — | Right-aligned content (counts, links, actions). |
| `className` | `string` | — | Extra class(es). |

### Badge

Small status pill.

| Prop | Type | Default | Description |
|---|---|---|---|
| `tone` | `Tone` | `"muted"` | Text (and border) color role. |
| `outline` | `boolean` | `true` | Outlined pill (border + tone text) vs plain tone text. |
| `uppercase` | `boolean` | `false` | Uppercase the label. |
| `children` | `ReactNode` | required | Label. |

### Button

The one button. Extends `ButtonHTMLAttributes<HTMLButtonElement>`, so `onClick`, `disabled`, `type`
pass through.

| Prop | Type | Default | Description |
|---|---|---|---|
| `variant` | `"primary" \| "outline" \| "ghost"` | `"outline"` | `primary` = amber fill, `outline` = bordered, `ghost` = subtle. |
| ...rest | `ButtonHTMLAttributes` | — | Forwarded to the native `<button>`. |

### TextInput

Terminal-style prompt input with a leading glyph. Extends `InputHTMLAttributes<HTMLInputElement>`.

| Prop | Type | Default | Description |
|---|---|---|---|
| `glyph` | `ReactNode` | `"❯"` | Leading glyph inside the field. |
| `active` | `boolean` | `false` | Highlight the border (e.g. valid input ready to submit). |
| `trailing` | `ReactNode` | — | Trailing slot (submit affordance, status). |
| ...rest | `InputHTMLAttributes` | — | Forwarded to the native `<input>`. |

### StatusDot

A small colored status dot with optional pulse + glow.

| Prop | Type | Default | Description |
|---|---|---|---|
| `tone` | `Tone` | `"low"` | Dot color role. |
| `pulse` | `boolean` | `false` | Pulse animation for live/running state. |
| `glow` | `boolean` | `true` | Soft glow halo. |
| `size` | `number` | `7` | Diameter in px. |

### Sparkline

Tiny inline trend line. Points are computed by `sparkPoints()` from `src/lib/format.ts`.

| Prop | Type | Default | Description |
|---|---|---|---|
| `values` | `number[]` | required | Data points, left to right. |
| `tone` | `Tone` | `"muted"` | Stroke color role. |
| `width` | `number` | `64` | Width in px. |
| `height` | `number` | `22` | Height in px. |

### Meter

Thin horizontal fill bar. `pct` is clamped to 0–100.

| Prop | Type | Default | Description |
|---|---|---|---|
| `pct` | `number` | required | Fill percentage, 0–100. |
| `tone` | `Tone` | `"amber"` | Fill color role. |
| `width` | `number` | `46` | Width in px. |
| `height` | `number` | `5` | Height in px. |
| `bordered` | `boolean` | `true` | 1px soft border around the track. |

### StatusBadge

Run-status pill: icon + label in the status tone. Pre-wired to `src/lib/status.ts` (replaces the
deleted `SeverityTag`).

| Prop | Type | Default | Description |
|---|---|---|---|
| `status` | `RunStatus` | required | One of `pending \| running \| succeeded \| failed \| interrupted` (from `@/api`). |
| `withIcon` | `boolean` | `true` | Prefix the label with `runIcon(status)`. |

### Tabs

Terminal-style tab strip: chips with an active underline.

| Prop | Type | Default | Description |
|---|---|---|---|
| `items` | `TabItem[]` | required | `{ id, label, badge?, disabled? }` per tab. |
| `value` | `string` | required | Active tab id. |
| `onChange` | `(id: string) => void` | required | Fires on tab click. |

### CodeBlock

Monospace block with an accent left-border and an optional copy button.

| Prop | Type | Default | Description |
|---|---|---|---|
| `children` | `string` | required | The code/text body. |
| `accent` | `Tone` | `border-soft` | Left-border accent tone. |
| `copyable` | `boolean` | `true` | Show the copy button. |
| `label` | `string` | — | Optional caption above the block. |

### KeyValueList

Two-column key/value rows, values optionally toned.

| Prop | Type | Default | Description |
|---|---|---|---|
| `rows` | `KeyValueRow[]` | required | `{ key, value, tone? }` per row. |

### EntityList

Generic list-page table: typed columns, row click, selection, empty state. Backs the list screens.

| Prop | Type | Default | Description |
|---|---|---|---|
| `columns` | `Column<T>[]` | required | `{ id, header, width, render, align? }` per column. |
| `rows` | `T[]` | required | Row data. |
| `keyOf` | `(row: T) => string` | required | Stable row key. |
| `onRowClick` | `(row: T) => void` | — | Row click handler (rows become clickable). |
| `selectedKey` | `string \| null` | — | Highlight the matching row. |
| `empty` | `ReactNode` | — | Empty-state content. |

### Drawer

Right-side slide-over panel; closes on Escape / backdrop.

| Prop | Type | Default | Description |
|---|---|---|---|
| `open` | `boolean` | required | Visibility. |
| `title` | `ReactNode` | required | Header title. |
| `onClose` | `() => void` | required | Close handler. |
| `width` | `number` | `420` | Panel width in px. |
| `children` | `ReactNode` | required | Panel body. |

## Layout components (`src/components/layout/`)

- **AppShell** — app frame rendered by the router: fixed `TopBar`, `StatusBar`, and the active screen
  between them via `<Outlet/>`. No props.
- **TopBar** — brand mark (→ `/runs`), numbered screen tabs from `src/app/screens.ts`, a "new run"
  action (→ `/runs?new=1`), and a clock. Route-driven, no props, no global run state.
- **StatusBar** — bottom line: mode chip, fake shell path `~/git-agent/<screen>` from the current
  route, and a `scan → parse → report` readout. Route-driven, no props.

## Run feature components (`src/features/runs/`)

- **GraphCanvas** (`GraphCanvasProps`: `nodes`, `edges`, `selectedId`, `onSelect`, `eventCounts?`) —
  interactive SVG graph. Pan by dragging empty space; nodes drag + select. Layout is client-owned:
  seeded from `GraphNode.x/y` percent hints, persisted to `localStorage` by node-id set. Colors/icons
  from `nodeTone`/`nodeIcon`.
- **NodeInspector** (`NodeInspectorProps`: `runId`, `node`, `events`, `onClose`) — tabbed panel
  (`overview | system prompt | tools | skills | events`) over `useNodeSpec`. Honest for procedural
  nodes (no LLM prompt; tools = sandbox commands), full for agent nodes.
- **EventStream** (`EventStreamProps`: `logs`, `nodes`, `selectedNodeId`, `live`) — full-width log
  bound to the graph by node id, with per-node filter chips and live follow.

## Tone system (`src/lib/tone.ts`)

A `Tone` is a named color role mapping 1:1 to a CSS variable in `src/styles/tokens.css`. Components
take `tone` props instead of raw colors.

```ts
export type Tone =
  | "text" | "muted" | "dim" | "comment"       // text hierarchy
  | "amber" | "burnt" | "blue"                  // accents
  | "crit" | "high" | "med" | "low" | "info";   // status scale

toneVar("amber"); // => "var(--amber)"
```

## Status system (`src/lib/status.ts`)

Replaces the deleted severity system. Maps domain status onto tone / label / glyph:

| Export | Type | Purpose |
|---|---|---|
| `runTone(s)` | `(RunStatus) => Tone` | `running→amber`, `succeeded→low`, `failed→crit`, `interrupted→high`, `pending→muted`. |
| `runLabel(s)` | `(RunStatus) => string` | The status word. |
| `runIcon(s)` | `(RunStatus) => string` | Glyph (`○ ◉ ● ✕ ■`). |
| `nodeTone(s)` | `(NodeStatus) => Tone` | `running→amber`, `completed→low`, `error→crit`, `pending→dim`. |
| `nodeIcon(s)` | `(NodeStatus) => string` | Node glyph (`○ ◉ ● ⊘`). |
| `RUN_STATUS_ORDER` | `RunStatus[]` | Canonical sort/filter order. |

`StatusBadge` is the ready-made component for run status; use `runTone`/`nodeTone` directly for custom
rendering (filters, graph nodes, bars).

## Feature components (`src/features/`)

One folder per area; screen-specific components live next to the screen that owns them and are not
shared. Named exports everywhere; co-located `*.module.css`. Features compose primitives + hooks
(`@/hooks`); they never import another feature.

| Folder | Screen(s) | Notable sub-components |
|---|---|---|
| `features/runs/` | `RunsScreen`, `RunDetailScreen`, `ReportScreen` | `GraphCanvas`, `NodeInspector`, `EventStream` |
| `features/connections/` | `ConnectionsScreen` | — |
| `features/sandboxes/` | `SandboxesScreen` | — |
| `features/skills/` | `SkillsScreen` | — |
| `features/overview/` | `OverviewScreen` | — |

If a component is needed by a second screen, promote it to `src/components/primitives/` (with a `tone`
prop instead of hardcoded colors).
