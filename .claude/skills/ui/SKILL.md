---
# Design System Skill

## When to Use
Use this skill when building UIs — warm, paper-like surfaces,
understated typography, soft borders, and a calm, distraction-free interaction pattern. Ideal for
AI chat interfaces, productivity dashboards, settings panels, and content-focused apps.

---

## Design Tokens

### Colors (CSS Custom Properties)

All color tokens use HSL values with the pattern `hsl(var(--token-name))`.
The theme is `data-theme="choola" data-mode="light"` on `<html>`.

#### Light Mode — Semantic Tokens
```css
:root {
  /* ── Backgrounds ── */
  --bg-000: 0 0% 100%;            /* #ffffff — pure white (inputs, cards, modals) */
  --bg-100: 48 33.3% 97.1%;       /* #faf9f5 — warm off-white (page bg, sidebar) */
  --bg-200: 53 28.6% 94.5%;       /* #f5f4ed — slightly cooler surface */
  --bg-300: 48 25% 92.2%;         /* #f0eee6 — hover surface, dividers */
  --bg-400: 50 20.7% 88.6%;       /* #e8e6dc — stronger tint, toggle track */
  --bg-500: 50 20.7% 88.6%;       /* #e8e6dc — alias of bg-400 */

  /* ── Text ── */
  --text-000: 60 2.6% 7.6%;       /* #141413 — richest black */
  --text-100: 60 2.6% 7.6%;       /* #141413 — primary body text */
  --text-200: 60 2.5% 23.3%;      /* #3d3d3a — secondary text */
  --text-300: 60 2.5% 23.3%;      /* #3d3d3a — alias */
  --text-400: 51 3.1% 43.7%;      /* #73726c — tertiary/muted */
  --text-500: 51 3.1% 43.7%;      /* #73726c — placeholder, metadata */

  /* ── Borders ── */
  --border-100: 30 3.3% 11.8%;    /* #1f1e1d — strong border */
  --border-200: 30 3.3% 11.8%;    /* #1f1e1d — strong border */
  --border-300: 30 3.3% 11.8%;    /* #1f1e1d — medium border (used at 0.15 opacity) */
  --border-400: 30 3.3% 11.8%;    /* #1f1e1d — dark mode strong */

  /* ── Brand / Accent ── */
  --accent-brand: 15 63.1% 59.6%; /* #d97757 — coral-orange brand color */
  --brand-000: 15 54.2% 51.2%;    /* #c6613f — dark brand */
  --brand-100: 15 54.2% 51.2%;    /* #c6613f — dark brand alias */
  --brand-200: 15 63.1% 59.6%;    /* #d97757 — mid brand (logo asterisk) */
  --brand-900: 0 0% 0%;           /* #000000 — darkest brand */

  /* ── Accent (Blue) ── */
  --accent-000: 210 73.7% 40.2%;  /* #1b67b2 — dark blue */
  --accent-100: 210 70.9% 51.6%;  /* #2c84db — primary interactive blue */
  --accent-200: 210 70.9% 51.6%;  /* #2c84db — focus ring color */
  --accent-900: 211 72% 90%;      /* #d3e5f8 — blue tint bg */

  /* ── Accent Pro (Purple) ── */
  --accent-pro-000: 251 34.2% 33.3%; /* #433872 */
  --accent-pro-100: 251 40% 45.1%;   /* #5645a1 */
  --accent-pro-200: 251 61% 72.2%;   /* #9d8de3 */
  --accent-pro-900: 253 33.3% 91.8%; /* #e6e3f1 */

  /* ── On-color (text over colored backgrounds) ── */
  --oncolor-100: 0 0% 100%;       /* #ffffff */
  --oncolor-200: 60 6.7% 97.1%;   /* #f8f8f7 */
  --oncolor-300: 60 6.7% 97.1%;   /* #f8f8f7 */

  /* ── Semantic States ── */
  --success-000: 125 100% 18%;    /* #005c08 */
  --success-100: 103 72.3% 26.9%; /* #2f7613 */
  --success-200: 103 72.3% 26.9%; /* #2f7613 */
  --success-900: 86 45.1% 90%;    /* #e7f1da */

  --warning-000: 45 91.8% 19%;    /* #5d4704 */
  --warning-100: 39 88.8% 28%;    /* #875a08 */
  --warning-200: 39 88.8% 28%;    /* #875a08 */
  --warning-900: 38 65.9% 92%;    /* #f8eedd */

  --danger-000: /* ~0 58.6% 34.1% */ #8c1e1e;
  --danger-100: /* ~0 56.2% 45.4% */ #b33232;
  --danger-200: /* ~0 56.2% 45.4% */ #b33232;
  --danger-900: /* ~0 50% 95% */     #ffe8e8;

  /* ── Pictogram / Illustration ── */
  --pictogram-100: 50 20.7% 88.6%;  /* #e8e6dc */
  --pictogram-200: 51 16.5% 84.5%;  /* #dedcd1 */
  --pictogram-300: 0 0% 100%;        /* #ffffff */
  --pictogram-400: 48 33.3% 97.1%;   /* #faf9f5 */

  /* ── Always (theme-invariant) ── */
  --always-black: 0 0% 0%;          /* #000000 */
  --always-white: 0 0% 100%;        /* #ffffff */
}
```

#### Dark Mode Overrides (when `data-mode="dark"`)
```css
[data-mode="dark"] {
  --bg-000: 60 2.1% 18.4%;    /* #30302e */
  --bg-100: 60 2.7% 14.5%;    /* #262624 */
  --bg-200: 30 3.3% 11.8%;    /* #1f1e1d */
  --bg-300: 60 2.6% 7.6%;     /* #141413 */
  --bg-400: 0 0% 0%;           /* #000000 */

  --text-000: 48 33.3% 97.1%; /* #faf9f5 */
  --text-100: 48 33.3% 97.1%; /* #faf9f5 */
  --text-200: 50 9% 73.7%;    /* #c2c0b6 */
  --text-300: 50 9% 73.7%;    /* #c2c0b6 */
  --text-400: 48 4.8% 59.2%;  /* #9c9a92 */
  --text-500: 48 4.8% 59.2%;  /* #9c9a92 */

  --border-100: 51 16.5% 84.5%; /* #dedcd1 */
  --border-200: 51 16.5% 84.5%; /* #dedcd1 */
  --border-300: 51 16.5% 84.5%; /* #dedcd1 */

  --accent-pro-000: 251 84.6% 74.5%; /* #9b87f5 */
  --accent-pro-100: 251 40.2% 54.1%; /* #6c5bb9 */
  --accent-pro-200: 251 40% 45.1%;   /* #5645a1 */
  --accent-pro-900: 250 25.3% 19.4%; /* #29253e */
  --accent-900: 210 55.9% 24.6%;     /* #1c3f62 */
  --success-900: 127 100% 13.9%;     /* #004708 */
  --warning-900: 45 94.8% 15.1%;     /* #4b3902 */
}
```

#### Key Resolved Hex Values (for quick reference)

| Token | Light | Dark |
|-------|-------|------|
| `--bg-000` | `#ffffff` | `#30302e` |
| `--bg-100` | `#faf9f5` (warm cream) | `#262624` |
| `--bg-200` | `#f5f4ed` | `#1f1e1d` |
| `--bg-300` | `#f0eee6` | `#141413` |
| `--bg-400` | `#e8e6dc` | `#000000` |
| `--text-100` | `#141413` | `#faf9f5` |
| `--text-200` | `#3d3d3a` | `#c2c0b6` |
| `--text-500` | `#73726c` | `#9c9a92` |
| `--accent-brand` | `#d97757` (coral) | `#d97757` |
| `--accent-100` | `#2c84db` (blue) | `#2c84db` |
| `--border-300` | `rgba(31,30,29,0.15)` | `rgba(222,220,209,0.15)` |

---

### Typography

#### Font Stacks
```css
:root {
  --font-sans-serif:   "Anthropic Sans", system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-ui:           "Anthropic Sans", system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --font-ui-serif:     "Anthropic Serif", Georgia, "Times New Roman", serif;
  --font-serif:        "Anthropic Serif", Georgia, "Times New Roman", serif;
  --font-mono:         "Anthropic Mono", ui-monospace, monospace;
  --font-system:       system-ui, sans-serif;
  --font-dyslexia:     "OpenDyslexic", "Comic Sans MS", ui-serif, serif;
  /* Semantic role assignments */
  --font-choola-response: var(--font-ui-serif); /* AI responses use Serif */
  --font-user-message:    var(--font-sans-serif); /* User input uses Sans */
}

/* Applied to body */
body {
  font-family: var(--font-ui);  /* Anthropic Sans */
}
```

#### Type Scale

| Role | Font Family | Size | Weight | Line Height | Color |
|------|-------------|------|--------|-------------|-------|
| Welcome greeting (hero) | Anthropic Serif | 40px | 330 | 60px (1.5) | `--text-200` (#3d3d3a) |
| H1 — Page title | Anthropic Serif | 24px | 500 | 31.2px (1.3) | `--text-100` (#141413) |
| H2 — Section heading | Anthropic Sans | 16px | 600 | 22.4px (1.4) | `--text-100` (#141413) |
| H2 — Sidebar label | Anthropic Sans | 12px | 400 | 16px (1.33) | `--text-500` (#73726c) |
| Body / Composer input | Anthropic Sans | 16px | 430 | 22.4px (1.4) | `--text-100` (#141413) |
| Body standard | Anthropic Sans | 16px | 400 | 24px (1.5) | `--text-100` (#141413) |
| Card title | Anthropic Sans | 14px | 500 | 19.6px (1.4) | `--text-100` (#141413) |
| Card description | Anthropic Sans | 14px | 430 | 19.6px (1.4) | `--text-300` (#3d3d3a) |
| Label / Nav link | Anthropic Sans | 14px | 430 | 19.6px (1.4) | `--text-200` (#3d3d3a) |
| Button text (primary) | Anthropic Sans | 14px | 500 | 19.6px (1.4) | `#ffffff` |
| Sidebar nav items | Anthropic Sans | 12px | 430 | 16px (1.33) | `--text-200` (#3d3d3a) |
| Metadata / Timestamp | Anthropic Sans | 12px | 430 | 16.8px (1.4) | `--text-500` (#73726c) |
| Badge text | Anthropic Sans | ~10px (0.625rem) | 400 | — | `--text-300` (#3d3d3a) |
| Model selector text | Anthropic Sans | 12px | 430 | 16px | `--text-200` (#3d3d3a) |
| Settings nav items | Anthropic Sans | 14px | 430 | 19.6px | `--text-100` (#141413) |
| Form input text | Anthropic Sans | 14px | 430 | 19.6px | `--text-100` (#141413) |
| Textarea text | Anthropic Sans | 14px | 430 | 19.6px | `--text-100` (#141413) |
| User avatar initials | Anthropic Sans | 16px | 600 | — | `--bg-100` (#faf9f5) |

> **Note:** Weight `430` is a variable font axis value (between Regular 400 and Medium 500). Weight `330` is a light variant used only for the greeting headline.

---

### Spacing & Layout

#### Grid & Breakpoints
```css
/* Tailwind breakpoints observed in stylesheets */
sm:   640px
md:   768px
lg:  1024px
xl:  1280px
2xl: 1536px

/* Custom breakpoints */
350px, 500px, 840px, 1000px, 1200px, 1400px, 1562px
```

#### Layout Structure
```
┌─────────────────────────────────────────────────┐
│ html: data-theme="choola" data-mode="light"     │
│ body: bg-bg-100 (#faf9f5)                        │
│                                                  │
│  ┌─────────────────────────────────────────┐    │
│  │ .grid.w-full (CSS Grid: 1 col)          │    │
│  │  ┌──────────┐ ┌───────────────────────┐ │    │
│  │  │ Sidebar  │ │ Main content          │ │    │
│  │  │ 288px    │ │ flex-1 (868px)        │ │    │
│  │  │ fixed/   │ │ max-w-7xl (1280px)    │ │    │
│  │  │ sticky   │ │ px-4 md:px-8 lg:px-14 │ │    │
│  │  └──────────┘ └───────────────────────┘ │    │
│  └─────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

#### Key Dimensions
```
Sidebar width:           288px
Content max-width:       1280px (max-w-7xl)
Chat input max-width:    672px (max-w-2xl)
Input container padding: 0 32px (lg: 0 56px, xl: 0 80px)
Content top padding:     10vh (mobile), 20vh (md+)
Chat card gap:           32px (gap-8)
Section spacing:         28px (gap-7)
Background tile grid:    32px × 32px
```

#### Spacing Scale (Tailwind-based, observed)
```
0.5 =  2px   (border-width hairlines: border-0.5)
1   =  4px
1.5 =  6px   (badge px)
2   =  8px   (icon gaps, small padding)
2.5 = 10px   (button px in composer)
3   = 12px   (input padding)
3.5 = 14px   (composer inner margin)
4   = 16px   (card padding, nav padding)
5   = 20px   (card left padding)
6   = 24px
7   = 28px   (welcome area gap)
8   = 32px   (content padding, section gap)
9   = 36px   (avatar size h-9 w-9)
```

---

### Shadows & Effects
```css
/* Chat composer input box shadow */
.composer-shadow {
  box-shadow:
    rgba(0, 0, 0, 0.075) 0px 4px 20px 0px,
    rgba(31, 30, 29, 0.3) 0px 0px 0px 0.5px;
}

/* Subtle card shadow on hover */
.card-hover-shadow {
  box-shadow: rgba(0, 0, 0, 0.08) 0px 2px 8px 0px;
}

/* Stop/loading button glow (brand shadow) */
.brand-glow {
  box-shadow:
    rgba(217, 119, 87, 0.24) 0px 40px 80px 0px,
    rgba(217, 119, 87, 0.24) 0px 4px 14px 0px;
}

/* Background dot-grid pattern (subtle grid lines on page bg) */
.page-bg-grid {
  background-color: hsl(var(--bg-100));
  background-image:
    linear-gradient(to right,  hsl(var(--bg-200)) 1px, transparent 1px),
    linear-gradient(to bottom, hsl(var(--bg-200)) 1px, transparent 1px);
  background-size: 32px 32px;
}

/* Focus ring */
:focus-visible {
  outline: 2px solid hsl(var(--accent-100)); /* #2c84db */
  outline-offset: 2px;
}
```

#### Transitions & Animations
```css
/* Standard button transition (cubic ease-out) */
.btn-transition {
  transition: color, background-color, border-color, box-shadow, transform, opacity, filter
    0.3s cubic-bezier(0.165, 0.85, 0.45, 1);
}

/* Fast surface transition (bg/border-color) */
.surface-transition {
  transition: background-color, border-color 0.15s cubic-bezier(0.4, 0, 0.2, 1);
}

/* Sidebar theme transition */
.sidebar-transition {
  transition: background-color, border-color, box-shadow 35ms ease;
}

/* Composer box resize */
.composer-transition {
  transition: all 0.2s ease;
}

/* Primary button hover micro-interaction */
.btn-primary:hover {
  transform: scaleY(1.015) scaleX(1.005);
  transition: transform 0.15s cubic-bezier(0.165, 0.85, 0.45, 1);
}

/* Project card hover */
.card:hover {
  transform: none; /* uses active:scale-[0.98] press effect instead */
}
.card:active {
  transform: scale(0.98);
}
```

#### Border Styles
```css
/* Standard hairline border (default) */
border: 0.8px solid rgba(31, 30, 29, 0.15);      /* inputs, cards */

/* Very subtle hairline */
border: 0.4px solid rgba(31, 30, 29, 0.15);      /* quick action pills */

/* Slightly stronger */
border: 0.4px solid rgba(31, 30, 29, 0.3);       /* sort button, outlined */

/* Emphasized border (loading state) */
border: 0.4px solid rgba(31, 30, 29, 0.4);

/* Right-side rule (sidebar divider) */
border-right: 0.4px solid rgba(31, 30, 29, 0.15);
```

---

## Component Patterns

### 1. Primary Button (dark/filled)
```html
<button class="btn-primary">
  + New project
</button>
```
```css
.btn-primary {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 36px;            /* h-9 */
  padding: 8px 16px;       /* py-2 px-4 */
  border-radius: 8px;      /* rounded-lg */
  border: none;
  color: #ffffff;
  font-family: var(--font-ui);
  font-size: 14px;
  font-weight: 500;
  line-height: 1.4;
  cursor: pointer;
  overflow: hidden;
  gap: 4px;
  min-width: 80px;
  white-space: nowrap;
  isolation: isolate;
  transition: transform 0.15s cubic-bezier(0.165, 0.85, 0.45, 1);
  will-change: transform;
  backface-visibility: hidden;
}
/* Dark fill uses ::before pseudo-element */
.btn-primary::before {
  content: '';
  position: absolute;
  inset: 0;
  background-color: hsl(var(--text-100)); /* #141413 */
  border-radius: inherit;
  z-index: -1;
}
/* Radial gradient highlight on hover */
.btn-primary::after {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(at bottom, hsla(var(--bg-000)/20%), hsla(var(--bg-000)/0%));
  opacity: 0;
  transition: opacity 0.2s, transform 0.2s;
  transform: translateY(8px);
}
.btn-primary:hover {
  transform: scaleY(1.015) scaleX(1.005);
}
.btn-primary:hover::after {
  opacity: 1;
  transform: translateY(0);
}
```

### 2. Ghost / Outlined Button
```html
<button class="btn-ghost">Activity ↓</button>
```
```css
.btn-ghost {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 36px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 0.4px solid rgba(31, 30, 29, 0.3);
  background: transparent;
  color: hsl(var(--text-100));
  font-family: var(--font-ui);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  gap: 4px;
  transition: background-color 0.3s cubic-bezier(0.165, 0.85, 0.45, 1);
}
.btn-ghost:hover {
  background-color: hsl(var(--bg-300));
}
```

### 3. Icon Button (toolbar/nav)
```html
<button class="btn-icon" aria-label="Close sidebar">
  <svg width="20" height="20" viewBox="0 0 20 20">...</svg>
</button>
```
```css
.btn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: hsl(var(--text-100));
  cursor: pointer;
  transition: background-color 0.3s cubic-bezier(0.165, 0.85, 0.45, 1);
}
.btn-icon:hover {
  background-color: hsl(var(--bg-300));
}
```

### 4. Quick Action Pill Button
```html
<button class="btn-pill">
  <svg>...</svg>
  Code
</button>
```
```css
.btn-pill {
  display: inline-flex;
  align-items: center;
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  border: 0.4px solid rgba(31, 30, 29, 0.15);
  background: hsl(var(--bg-100));
  color: hsl(var(--text-200));
  font-family: var(--font-ui);
  font-size: 14px;
  font-weight: 430;
  gap: 6px;
  cursor: pointer;
  transition: background-color 0.3s cubic-bezier(0.165, 0.85, 0.45, 1);
}
.btn-pill:hover {
  background: hsl(var(--bg-300));
  border-color: rgba(31, 30, 29, 0.25);
}
```

### 5. Text Input / Text Field
```html
<input type="text" class="input-text" placeholder="Ivan" value="Ivan" />
```
```css
.input-text {
  display: block;
  width: 100%;
  height: 44px;       /* h-11 */
  padding: 0 12px;    /* px-3 */
  border-radius: 9.6px;  /* rounded-[0.6rem] */
  border: 0.8px solid rgba(31, 30, 29, 0.15);
  background: hsl(var(--bg-000)); /* #ffffff */
  color: hsl(var(--text-100));
  font-family: var(--font-ui);
  font-size: 14px;
  font-weight: 430;
  line-height: 1.4;
  outline: none;
  transition: border-color 0.15s ease;
}
.input-text:hover {
  border-color: rgba(31, 30, 29, 0.3);
}
.input-text:focus {
  outline: 2px solid hsl(var(--accent-100)); /* #2c84db */
  outline-offset: 0;
}
.input-text::placeholder {
  color: hsl(var(--text-500));
}
```

### 6. Textarea
```css
.textarea {
  display: block;
  width: 100%;
  min-height: 84px;
  padding: 12px;
  border-radius: 9.6px;
  border: 0.8px solid rgba(31, 30, 29, 0.15);
  background: hsl(var(--bg-000));
  color: hsl(var(--text-100));
  font-family: var(--font-ui);
  font-size: 14px;
  font-weight: 430;
  line-height: 1.4;
  resize: vertical;
  outline: none;
}
.textarea:focus {
  outline: 2px solid hsl(var(--accent-100));
}
.textarea::placeholder {
  color: hsl(var(--text-500));
}
```

### 7. Search Input
```html
<div class="search-wrapper">
  <svg class="search-icon">...</svg>
  <input type="search" placeholder="Search projects..." />
</div>
```
```css
.search-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 44px;
  padding: 0 12px;
  border-radius: 9.6px;
  border: 0.8px solid rgba(31, 30, 29, 0.15);
  background: hsl(var(--bg-000));
  color: hsl(var(--text-100));
  font-size: 16px;
  font-weight: 430;
  transition: border-color 0.15s ease;
}
.search-wrapper:focus-within {
  outline: 2px solid hsl(var(--accent-100));
  border-color: transparent;
}
.search-wrapper input {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: 16px;
  font-weight: 430;
  color: hsl(var(--text-100));
}
.search-wrapper input::placeholder {
  color: hsl(var(--text-500));
}
```

### 8. Select / Dropdown Trigger
```html
<button class="select-trigger" role="combobox" aria-expanded="false">
  <span>Select your work function</span>
  <svg class="chevron">...</svg>
</button>
```
```css
.select-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  height: 44px;
  padding: 0 10px 0 12px;
  border-radius: 9.6px;
  border: 0.8px solid rgba(31, 30, 29, 0.15);
  background: hsl(var(--bg-000));
  color: hsl(var(--text-100));
  font-family: var(--font-ui);
  font-size: 14px;
  font-weight: 430;
  cursor: pointer;
  gap: 6px;
  white-space: nowrap;
  transition: border-color 0.15s ease;
}
.select-trigger:hover {
  border-color: rgba(31, 30, 29, 0.3);
}
/* Dropdown max height */
.select-dropdown {
  max-height: 480px; /* --dropdown-max-height */
  overflow-y: auto;
  border-radius: 9.6px;
  background: hsl(var(--bg-000));
  border: 0.8px solid rgba(31, 30, 29, 0.15);
  box-shadow: rgba(0,0,0,0.1) 0px 8px 24px;
}
```

### 9. Toggle Switch
```html
<label class="toggle-label">
  <div class="toggle-wrapper group/switch">
    <input type="checkbox" class="peer sr-only" role="switch" />
    <!-- Track -->
    <span class="toggle-track peer-checked:bg-[--accent-100]"></span>
    <!-- Thumb -->
    <span class="toggle-thumb peer-checked:translate-x-4"></span>
  </div>
  Response completions
</label>
```
```css
.toggle-wrapper {
  position: relative;
  width: 36px;
  height: 20px;
  cursor: pointer;
  user-select: none;
}
.toggle-track {
  display: block;
  width: 36px;
  height: 20px;
  border-radius: 9999px;
  background: hsl(var(--bg-500));           /* #e8e6dc — off state */
  box-shadow: inset 0 0 0 0.5px rgba(31, 30, 29, 0.2);
  transition: background-color 0.15s ease;
}
input:checked ~ .toggle-track {
  background: hsl(var(--accent-100));       /* #2c84db — on state */
}
.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 9999px;
  background: #ffffff;
  box-shadow: inset 0 0 0 0.5px rgba(31, 30, 29, 0.15);
  transition: transform 0.15s ease;
}
input:checked ~ .toggle-thumb {
  transform: translateX(16px);
}
```

### 10. Project / Content Card
```html
<a class="project-card" href="/project/...">
  <div class="card-content">
    <div class="card-header">
      <div class="card-title">Carrer path</div>
      <span class="card-badge">Example project</span>
    </div>
    <div class="card-description">I want to create as detailed...</div>
    <div class="card-meta">Updated 8 months ago</div>
  </div>
</a>
```
```css
.project-card {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  padding: 16px 16px 16px 20px; /* py-4 pl-5 pr-4 */
  border-radius: 12px;           /* rounded-xl */
  border: 0.4px solid rgba(31, 30, 29, 0.15);
  background-image: linear-gradient(
    to bottom,
    hsl(var(--bg-100)),
    hsla(var(--bg-100) / 0.3)
  );
  text-decoration: none;
  color: hsl(var(--text-100));
  cursor: pointer;
  overflow: hidden;
  position: relative;
  transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
}
.project-card:hover {
  background-image: linear-gradient(
    to bottom,
    hsl(var(--bg-000)),
    hsla(var(--bg-000) / 0.8)
  );
  border-color: rgba(31, 30, 29, 0.25);
  box-shadow: rgba(0, 0, 0, 0.08) 0px 2px 8px;
}
.project-card:active {
  transform: scale(0.98);
}
.card-title {
  font-size: 14px;
  font-weight: 500;
  line-height: 1.4;
  color: hsl(var(--text-100));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card-description {
  font-size: 14px;
  font-weight: 430;
  line-height: 1.4;
  color: hsl(var(--text-300));
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  flex-grow: 1;
}
.card-meta {
  font-size: 12px;
  font-weight: 430;
  line-height: 1.4;
  color: hsl(var(--text-500));
  margin-top: auto;
  padding-top: 12px;
}
/* Card grid */
.cards-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}
@media (min-width: 768px) {
  .cards-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 24px;
  }
}
```

### 11. Badge / Tag
```html
<span class="badge">Example project</span>
<span class="badge badge-beta">Beta</span>
```
```css
.badge {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 8px;
  border-radius: 8px;
  background: rgba(232, 230, 220, 0.4);  /* bg-500 at 40% */
  color: hsl(var(--text-200));
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 430;
  line-height: 1;
  white-space: nowrap;
  vertical-align: middle;
  flex-shrink: 0;
}
.badge-beta {
  height: 20px;
  padding: 0 6px;
  border-radius: 6px;
  font-size: 10px;   /* 0.625rem */
  background: linear-gradient(
    to bottom left,
    hsla(var(--bg-500) / 0.3),
    hsla(var(--bg-500) / 0.7)
  );
}
```

### 12. Chat Composer Input
```html
<div class="composer">
  <div class="composer-inner">
    <!-- ProseMirror / contenteditable input -->
    <div class="ProseMirror" contenteditable="true" role="textbox">
      <p data-placeholder="How can I help you today?"></p>
    </div>
  </div>
  <div class="composer-toolbar">
    <button class="btn-icon">+</button>  <!-- attachment -->
    <div class="composer-right">
      <button class="model-selector">Opus 4.6 Extended ↓</button>
      <button class="btn-voice">🎤</button>
    </div>
  </div>
</div>
```
```css
.composer {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 672px;
  border-radius: 20px;
  border: 0.8px solid transparent;
  background: hsl(var(--bg-000));  /* #ffffff */
  box-shadow:
    rgba(0, 0, 0, 0.