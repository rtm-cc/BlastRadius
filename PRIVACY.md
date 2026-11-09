# Privacy Policy for Blast Radius Digest Extension

**Last Updated:** November 2026  
**Website:** [https://news.rtm.cc](https://news.rtm.cc)  
**Repository:** [https://github.com/rtm-cc/BlastRadius](https://github.com/rtm-cc/BlastRadius)

Blast Radius Digest ("we", "our", or "the extension") is a lightweight, privacy-first browser extension designed to provide curated cybersecurity news and threat intelligence.

Your privacy is a fundamental priority. This Privacy Policy outlines our commitment to zero user tracking and explains how the extension operates.

---

## 1. Information We Collect

**We do not collect, store, transmit, or sell any personal information or user data.**

* **No Personally Identifiable Information (PII):** We do not collect names, email addresses, IP addresses, or device identifiers.
* **No Browsing History or Web Activity:** The extension cannot see or track the websites you visit, your browsing habits, or your tab activity.
* **No Telemetry or Analytics:** We do not use third-party analytics (such as Google Analytics or Mixpanel), trackers, or advertising SDKs.

---

## 2. Local Storage and Preferences

The extension uses the browser's local storage API (`chrome.storage.local` / `browser.storage.local`) strictly to improve your local experience:

* **Theme Preference:** Saves whether you chose Light, Dark, or System theme.
* **Watchlist Keywords / Regex:** Stores the custom alert terms or CVE patterns you add.
* **Cached News Edition:** Stores the latest retrieved RSS headlines locally so the extension opens instantly without reloading.

**All of this data remains solely on your personal computer.** It is never transmitted to us or any third party.

---

## 3. Network Connections and Data Transfer

The extension makes network requests solely to fetch the public, static RSS feed from:

* `https://news.rtm.cc/feed.xml`

This request is a standard HTTP GET request used strictly to retrieve public news items. No user-identifying metadata, query parameters, or analytics are attached to this request.

---

## 4. Permissions Used and Why

* **`storage`**: Allows saving your theme preference and watchlist terms locally on your device.
* **`alarms`**: Enables the browser to periodically check for new daily editions in the background.
* **`notifications`**: Displays desktop notifications only when a story matching your custom watchlist terms appears.
* **Host Permission (`https://news.rtm.cc/*`)**: Permits fetching the public RSS feed (`feed.xml`).

---

## 5. Third-Party Services

When you click on a news article link, the extension opens the original reporting source (e.g., BleepingComputer, CISA, The Hacker News) in a new browser tab. Once you navigate to external websites, their respective privacy policies apply.

---

## 6. Children's Privacy

The extension does not knowingly collect or solicit any information from anyone under the age of 13.

---

## 7. Changes to This Policy

If this Privacy Policy is updated, the revised version will be posted at this URL with an updated "Last Updated" date.

---

## 8. Contact & Open Source

Blast Radius is an open-source project. You can inspect the complete source code or raise questions at:

* **GitHub:** [https://github.com/rtm-cc/BlastRadius](https://github.com/rtm-cc/BlastRadius)
* **Website:** [https://rtm.cc](https://rtm.cc)
