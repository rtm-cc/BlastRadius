# Blast Radius Digest — Firefox Extension

A modern, high-performance Firefox Extension for [Blast Radius Digest](https://news.rtm.cc) that allows you to monitor daily curated cybersecurity intelligence, threats, vulnerabilities, and breaches directly from Firefox.

---

## Features

### 1. Visual Identity & Design
- **1:1 Visual Parity**: Matches `news.rtm.cc`'s dark and light aesthetic, typography, card borders, and glassmorphic header.
- **Light & Dark Theme**: Supports System (Auto), Dark (`#0a0b0e`), and Light (`#f1f4f9`) themes with a one-click toggle in the header.
- **Deterministic Tag Hues**: Tags and topics share the exact same hue algorithm as the web board.

### 2. Current Day Edition & Archives
- **Today's News by Default**: Automatically isolates stories from the current edition (within the latest 24-hour publication window) so you can quickly scan today's threats without clutter.
- **Forward to Website**: Bottom footer card and top header links allow you to open the full interactive board, past day archives, and timeline clusters on [https://news.rtm.cc](https://news.rtm.cc).

### 3. Topic & Category Navigation
- **Floating Edge Fades & Sleek Chevrons**: Modern feathered gradient edges with floating frosted-glass chevron buttons that smoothly slide categories left and right.
- **Click & Drag to Scroll**: Click and drag with your mouse across the category bar to glide through topics naturally, with instant 1:1 tracking and accidental click suppression.
- **Mouse Wheel Scroll**: Mouse wheel horizontal scrolling over the category bar.
- **Horizontal Pill Bar**: Quick navigation across all security topics:
  - **Active Threats** (`hsl(280, ...)` Purple)
  - **Vulnerabilities & Patches** (`hsl(28, ...)` Orange)
  - **AI Security** (`hsl(160, ...)` Emerald)
  - **Supply Chain** (`hsl(190, ...)` Cyan)
  - **Breaches** (`hsl(0, ...)` Red)
  - **Fraud & Phishing** (`hsl(45, ...)` Amber)
  - **Policy & Enforcement** (`hsl(225, ...)` Blue)
- Story counts are displayed right on each topic pill.

### 4. Space-Efficient Instant Search
- **Collapsible Search Row**: Takes minimal space (~32px) and doesn't push content down when closed.
- **Zero Latency**: Filters across titles, summaries, update notices, tags, and topics in real-time as you type.
- **Keyboard Shortcut**: Press `/` anywhere in the extension to focus search; press `Escape` to clear.
- **Clickable Tag Filtering**: Clicking any tag badge on a story instantly filters the feed by that tag.

### 5. Keyword & Tag Watchlist (Alert Badges)
- **Case-Insensitive (icase) Matching**: All plain keyword and tag searches are fully case-insensitive (e.g. `cve-2026`, `CVE-2026`, and `Cve-2026` all match identically).
- **Regular Expression (Regex) Support**:
  - Add complex patterns using `/pattern/flags` syntax (e.g. `/CVE-\d{4}-\d+/i`, `/\b(ransomware|extortion)\b/i`, `/prompt[\s_-]?injection/i`).
  - Toggle the `.* Regex` mode button in the input row for instant regex validation and formatting.
  - Regex chips display a distinct `.*` indicator badge.
  - Live count indicator on each watchlist chip shows how many stories in today's edition match that specific term or pattern.
- **High-Visibility Alert Badge**: When an edition contains stories matching your watched terms:
  - The browser extension icon badge changes to a **vibrant red** with the match count.
  - Normal status badge uses the brand **indigo** color.
  - Story cards get an alert border and a `⚡ Alert Match` header.
- **Desktop Notifications**: Optional system notification when a watched term is discovered by the background worker.

### 6. Updates & Refresh Pipeline
- **Background Checks**: Powered by Manifest V3 background script and `browser.alarms` every 4 hours (~6 times a day) plus on browser launch.
- **Force Refresh**: Dedicated reload button in the header with a spinning animation that fetches fresh data from `https://news.rtm.cc/feed.xml?_t=...` on demand.
- **Offline / Instant Cache**: Cached locally in `browser.storage.local` for instant sub-second opening.

---

## Installation in Firefox (Temporary Add-on / Developer Mode)

1. Open Firefox.
2. In the URL bar, type:
   ```
   about:debugging#/runtime/this-firefox
   ```
3. Click the **Load Temporary Add-on...** button.
4. Browse to and select `manifest.json` inside the `extensions/firefox` directory.
5. The **Blast Radius Digest** extension will be loaded. Click the puzzle icon or toolbar button to pin it to your Firefox toolbar.

---

## File Structure

```
extensions/firefox/
├── manifest.json       # Manifest V3 configuration with gecko settings
├── background.js       # Background script for alarms, badges, and alerts
├── parser.js           # Zero-dependency, pure JS RSS 2.0 XML parser
├── popup.html          # Extension window layout
├── popup.css           # Styling with full light/dark theme variables
├── popup.js            # Client-side UI logic with cross-browser WebExtension API
├── icons/              # Extension icons (16, 32, 48, 128px)
└── README.md           # Documentation
```
