# Blast Radius Digest — Chrome Extension

[![Chrome Web Store](https://img.shields.io/badge/Chrome_Web_Store-Available-4285F4?style=for-the-badge&logo=googlechrome&logoColor=white)](https://chromewebstore.google.com/detail/blast-radius-digest/cjcockadimcmobekplcdofhempfkjipi)

A modern, high-performance Chrome Extension for [Blast Radius Digest](https://news.rtm.cc) that allows you to monitor daily curated cybersecurity intelligence, threats, vulnerabilities, and breaches directly from your browser.

👉 [**Install from the Chrome Web Store**](https://chromewebstore.google.com/detail/blast-radius-digest/cjcockadimcmobekplcdofhempfkjipi)

---

## Features

### 1. Visual Identity & Design
- **1:1 Visual Consistency**: Perfectly matches `news.rtm.cc`'s dark and light aesthetic, typography, card borders, and glassmorphic header.
- **Light & Dark Theme**: Supports System (Auto), Dark (`#0a0b0e`), and Light (`#f1f4f9`) themes with a one-click toggle in the header.
- **Deterministic Tag Hues**: Tags and topics share the exact same hue algorithm as the web board.

### 2. Current Day Edition & Archives
- **Today's News by Default**: Automatically isolates stories from the current edition (within the latest 24-hour publication window) so you can quickly scan today's threats without clutter.
- **Forward to Website**: Bottom footer card and top header links allow you to open the full interactive board, past day archives, and timeline clusters on [https://news.rtm.cc](https://news.rtm.cc).

### 3. Topic & Category Navigation
- **Floating Edge Fades & Sleek Chevrons**: Modern feathered gradient edges with floating frosted-glass chevron buttons that smoothly slide categories left and right.
- **Horizontal Pill Bar**: Quick navigation across all security topics:
  - **Active Threats** (`hsl(280, ...)` Purple)
  - **Vulnerabilities & Patches** (`hsl(28, ...)` Orange)
  - **AI Security** (`hsl(160, ...)` Emerald)
  - **Supply Chain** (`hsl(190, ...)` Cyan)
  - **Breaches** (`hsl(0, ...)` Red)
  - **Fraud & Phishing** (`hsl(45, ...)` Amber)
  - **Policy & Enforcement** (`hsl(225, ...)` Blue)
- **Intuitive Navigation**: Full click-and-drag mouse support, mouse wheel horizontal scrolling, and floating chevron buttons let you glide across all topics effortlessly. Story counts are displayed right on each topic pill.

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
- **Background Checks**: Powered by Manifest V3 service worker and `chrome.alarms` every 4 hours (~6 times a day) plus on browser launch.
- **Force Refresh**: Dedicated reload button in the header with a spinning animation that fetches fresh data from `https://news.rtm.cc/feed.xml?_t=...` on demand.
- **Offline / Instant Cache**: Cached locally in `chrome.storage.local` for instant sub-second opening.

---

## Installation

### Option 1: Chrome Web Store (Recommended)
Install directly with one click from the [**Chrome Web Store**](https://chromewebstore.google.com/detail/blast-radius-digest/cjcockadimcmobekplcdofhempfkjipi).

### Option 2: Developer Mode (Manual / Unpacked)
1. Open Google Chrome (or Brave, Microsoft Edge, Vivaldi, Arc).
2. Navigate to `chrome://extensions`.
3. Toggle on **Developer mode** in the top-right corner.
4. Click **Load unpacked** in the top-left corner.
5. Select the `extensions/chrome` directory from this repository.
6. The **Blast Radius Digest** icon will appear in your extensions toolbar. Click the pin icon to keep it visible!

---

## File Structure

```
extensions/chrome/
├── manifest.json       # Manifest V3 configuration & permissions
├── background.js       # Service worker for periodic alarms, alerts, and badges
├── parser.js           # Zero-dependency, pure JS RSS 2.0 XML parser
├── popup.html          # Extension window markup
├── popup.css           # Styling with full light/dark theme variables
├── popup.js            # Client-side UI logic, instant search, and watchlist
├── icons/              # Extension icons (16, 32, 48, 128px)
└── README.md           # Documentation
```

---

## Firefox Extension

A dedicated Firefox build is available in [`extensions/firefox`](../firefox).
