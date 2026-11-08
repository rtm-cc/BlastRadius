/**
 * Blast Radius Background Service Worker / Script (Firefox)
 * Handles periodic updates, badge state, and alert notifications.
 */

import { parseFeed, filterCurrentDayStories, evaluateWatchlist } from './parser.js';

const ext = typeof browser !== 'undefined' ? browser : chrome;

const FEED_URL = 'https://news.rtm.cc/feed.xml';
const ALARM_NAME = 'blastradius-periodic-refresh';
// Refresh every 4 hours (240 minutes, ~6x per day)
const REFRESH_INTERVAL_MINUTES = 240;

const BADGE_COLOR_NORMAL = '#4338ca'; // Indigo
const BADGE_COLOR_ALERT = '#ef4444';  // Alarm Red

// Initialize alarms on installation
ext.runtime.onInstalled.addListener(async () => {
  ext.alarms.create(ALARM_NAME, {
    periodInMinutes: REFRESH_INTERVAL_MINUTES,
    delayInMinutes: 1, // run shortly after install
  });
  await fetchAndUpdateFeed();
});

// Check on browser startup
ext.runtime.onStartup.addListener(async () => {
  const { feed_cache } = await ext.storage.local.get('feed_cache');
  const now = Date.now();
  // If cache is missing or older than 2 hours, fetch immediately
  if (!feed_cache || !feed_cache.timestamp || now - feed_cache.timestamp > 2 * 60 * 60 * 1000) {
    await fetchAndUpdateFeed();
  }
});

// Periodic alarm handler
ext.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === ALARM_NAME) {
    await fetchAndUpdateFeed();
  }
});

// Listen for messages from popup
ext.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'REFRESH_FEED') {
    fetchAndUpdateFeed(true)
      .then((result) => sendResponse({ success: true, ...result }))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true; // Keep message channel open for async response
  }

  if (message.action === 'CLEAR_ALERT_BADGE') {
    clearAlertBadge();
    sendResponse({ success: true });
    return false;
  }

  if (message.action === 'CHECK_WATCHLIST') {
    checkCurrentStoriesAgainstWatchlist(message.watchlist || [])
      .then((res) => sendResponse(res))
      .catch((err) => sendResponse({ error: err.message }));
    return true;
  }
});

/**
 * Fetch the RSS feed, parse stories, check watchlist, and update badge & cache.
 */
export async function fetchAndUpdateFeed(force = false) {
  try {
    const url = `${FEED_URL}?_t=${Date.now()}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 20000);

    const response = await fetch(url, {
      signal: controller.signal,
      cache: force ? 'no-cache' : 'default',
    });
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP error ${response.status}: ${response.statusText}`);
    }

    const xmlText = await response.text();
    const parsed = parseFeed(xmlText);
    const dayFiltered = filterCurrentDayStories(parsed.items);

    // Read user settings and watchlist
    const { watchlist = [], desktop_notifications = false, last_notified_guids = [] } =
      await ext.storage.local.get(['watchlist', 'desktop_notifications', 'last_notified_guids']);

    const evalResult = evaluateWatchlist(dayFiltered.stories, watchlist);

    // Save to storage
    const cacheData = {
      title: parsed.title,
      lastBuildDate: parsed.lastBuildDate,
      currentDay: dayFiltered.currentDay,
      stories: dayFiltered.stories,
      totalCount: dayFiltered.totalCount,
      olderCount: dayFiltered.olderCount,
      timestamp: Date.now(),
      evalResult: {
        matchCount: evalResult.matchCount,
        matchesByStoryId: evalResult.matchesByStoryId,
      },
    };

    await ext.storage.local.set({
      feed_cache: cacheData,
      last_updated: Date.now(),
    });

    // Update Extension Badge
    updateBadge(dayFiltered.stories.length, evalResult.matchCount);

    // Trigger Desktop Notification if matches found and enabled
    if (desktop_notifications && evalResult.matchCount > 0) {
      const newMatches = evalResult.matchedStories.filter(
        (m) => !last_notified_guids.includes(m.story.id)
      );

      if (newMatches.length > 0) {
        const topMatch = newMatches[0];
        const termsStr = topMatch.matches.join(', ');
        const notifyTitle = `⚡ Blast Radius Alert: "${termsStr}"`;
        const notifyBody = topMatch.story.title;

        ext.notifications.create(`br-alert-${topMatch.story.id}`, {
          type: 'basic',
          iconUrl: 'icons/icon128.png',
          title: notifyTitle,
          message: notifyBody,
        });

        // Remember notified GUIDs to avoid duplicates
        const updatedNotified = Array.from(
          new Set([...last_notified_guids, ...newMatches.map((m) => m.story.id)])
        );
        await ext.storage.local.set({ last_notified_guids: updatedNotified });
      }
    }

    return {
      currentDay: dayFiltered.currentDay,
      storyCount: dayFiltered.stories.length,
      matchCount: evalResult.matchCount,
      timestamp: Date.now(),
    };
  } catch (err) {
    console.error('Blast Radius update failed:', err);
    throw err;
  }
}

/**
 * Set badge color and text depending on alert state and unread count.
 */
function updateBadge(storyCount, matchCount) {
  const actionApi = ext.action || ext.browserAction;
  if (!actionApi) return;

  if (matchCount > 0) {
    actionApi.setBadgeBackgroundColor({ color: BADGE_COLOR_ALERT });
    actionApi.setBadgeText({ text: String(matchCount) });
    actionApi.setBadgeTextColor?.({ color: '#ffffff' });
  } else if (storyCount > 0) {
    actionApi.setBadgeBackgroundColor({ color: BADGE_COLOR_NORMAL });
    actionApi.setBadgeText({ text: String(storyCount) });
    actionApi.setBadgeTextColor?.({ color: '#ffffff' });
  } else {
    actionApi.setBadgeText({ text: '' });
  }
}

/**
 * Clear alert badge and restore normal story count badge.
 */
async function clearAlertBadge() {
  const actionApi = ext.action || ext.browserAction;
  if (!actionApi) return;

  const { feed_cache } = await ext.storage.local.get('feed_cache');
  if (feed_cache && feed_cache.stories) {
    actionApi.setBadgeBackgroundColor({ color: BADGE_COLOR_NORMAL });
    actionApi.setBadgeText({ text: String(feed_cache.stories.length) });
  } else {
    actionApi.setBadgeText({ text: '' });
  }
}

/**
 * Quick evaluation of watchlist without refetching.
 */
async function checkCurrentStoriesAgainstWatchlist(watchlist) {
  const { feed_cache } = await ext.storage.local.get('feed_cache');
  if (!feed_cache || !feed_cache.stories) {
    return { matchCount: 0, matchesByStoryId: {} };
  }
  const evalResult = evaluateWatchlist(feed_cache.stories, watchlist);
  updateBadge(feed_cache.stories.length, evalResult.matchCount);
  return evalResult;
}

// When notification is clicked, open the Blast Radius website
ext.notifications.onClicked.addListener(() => {
  ext.tabs.create({ url: 'https://news.rtm.cc' });
});
