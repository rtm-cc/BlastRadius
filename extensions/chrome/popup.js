/**
 * Blast Radius Chrome Extension Popup Logic
 * Handles feed display, instant search, topic filtering,
 * watchlist management, themes, and refresh operations.
 */

import {
  parseFeed,
  filterCurrentDayStories,
  evaluateWatchlist,
  validateWatchlistTerm,
  testTermMatch,
} from './parser.js';

// Configuration
const FEED_URL = 'https://news.rtm.cc/feed.xml';
const SITE_URL = 'https://news.rtm.cc';

// Topic Definitions and Hues (from config/topics.yaml)
const TOPIC_CONFIG = {
  breaches: { name: 'Breaches', color: 0 },
  vulnerabilities: { name: 'Vulnerabilities & Patches', color: 28 },
  threats: { name: 'Active Threats', color: 280 },
  supply_chain: { name: 'Supply Chain', color: 190 },
  ai_security: { name: 'AI Security', color: 160 },
  fraud_phishing: { name: 'Fraud & Phishing', color: 45 },
  policy: { name: 'Policy & Enforcement', color: 225 },
};

// State
let allDayStories = [];
let filteredStories = [];
let activeTopic = 'all';
let searchQuery = '';
let userWatchlist = [];
let desktopNotificationsEnabled = false;
let currentDayStr = '';
let isRegexInputMode = false;

// DOM Elements
const storiesList = document.getElementById('stories-list');
const emptyState = document.getElementById('empty-state');
const loadingSpinner = document.getElementById('loading-spinner');
const errorBanner = document.getElementById('error-banner');
const errorMessage = document.getElementById('error-message');

const topicsBar = document.getElementById('topics-bar');
const topicsFadeLeft = document.getElementById('topics-fade-left');
const topicsFadeRight = document.getElementById('topics-fade-right');
const btnScrollTopicsLeft = document.getElementById('btn-scroll-topics-left');
const btnScrollTopicsRight = document.getElementById('btn-scroll-topics-right');

const btnToggleSearch = document.getElementById('btn-toggle-search');
const searchContainer = document.getElementById('search-container');
const searchInput = document.getElementById('search-input');
const btnClearSearch = document.getElementById('btn-clear-search');
const searchStats = document.getElementById('search-stats');

const btnRefresh = document.getElementById('btn-refresh');
const btnTheme = document.getElementById('btn-theme');
const btnRetry = document.getElementById('btn-retry');

const btnWatchlist = document.getElementById('btn-watchlist');
const watchlistModal = document.getElementById('watchlist-modal');
const btnCloseWatchlist = document.getElementById('btn-close-watchlist');
const btnDoneWatchlist = document.getElementById('btn-done-watchlist');
const watchlistForm = document.getElementById('watchlist-form');
const watchlistInput = document.getElementById('watchlist-input');
const btnToggleRegexMode = document.getElementById('btn-toggle-regex-mode');
const watchlistErrorMsg = document.getElementById('watchlist-error-msg');
const watchlistTagsContainer = document.getElementById('watchlist-tags');
const watchlistCountSpan = document.getElementById('watchlist-count');
const chkDesktopNotifications = document.getElementById('chk-desktop-notifications');
const btnClearAlertBadge = document.getElementById('btn-clear-alert-badge');
const watchlistBadgeDot = document.getElementById('watchlist-badge-dot');

const alertBanner = document.getElementById('alert-banner');
const alertBannerText = document.getElementById('alert-banner-text');
const btnViewAlertMatches = document.getElementById('btn-view-alert-matches');
const btnDismissAlertBanner = document.getElementById('btn-dismiss-alert-banner');

const footerEditionDate = document.getElementById('footer-edition-date');
const footerStoryCount = document.getElementById('footer-story-count');

// --- Helper Functions --------------------------------------------------------

function safeUrl(url) {
  return typeof url === 'string' && /^https?:\/\//i.test(url) ? url : '';
}

/**
 * Deterministic hue hash matching BlastRadius public/app.js
 */
function tagHue(key) {
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) | 0;
  hash = ((hash >>> 16) ^ hash) * 0x45d9f3b;
  hash = ((hash >>> 16) ^ hash) * 0x45d9f3b;
  hash = (hash >>> 16) ^ hash;
  return Math.abs(hash) % 360;
}

function getTopicHue(topicNameOrId) {
  const norm = String(topicNameOrId || '').toLowerCase().replace(/[\s&]+/g, '_');
  for (const [id, conf] of Object.entries(TOPIC_CONFIG)) {
    if (id === norm || conf.name.toLowerCase() === String(topicNameOrId).toLowerCase()) {
      return conf.color;
    }
  }
  return tagHue(topicNameOrId);
}

function formatRelativeTime(timestamp) {
  if (!timestamp) return '';
  const diffSec = Math.floor((Date.now() - timestamp) / 1000);
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  const d = new Date(timestamp);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatEditionDay(dayStr) {
  if (!dayStr) return "Today's Edition";
  try {
    const parts = dayStr.split('-');
    if (parts.length === 3) {
      const d = new Date(`${dayStr}T12:00:00Z`);
      return d.toLocaleDateString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
      });
    }
  } catch (_) {}
  return dayStr;
}

// --- Theme Management --------------------------------------------------------

async function initTheme() {
  const { theme } = await chrome.storage.local.get('theme');
  if (theme === 'light' || theme === 'dark') {
    document.documentElement.setAttribute('data-theme', theme);
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
}

async function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  let next;
  if (!current) {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    next = prefersDark ? 'light' : 'dark';
  } else if (current === 'dark') {
    next = 'light';
  } else {
    next = 'dark';
  }

  document.documentElement.setAttribute('data-theme', next);
  await chrome.storage.local.set({ theme: next });
}

// --- Search Functionality ----------------------------------------------------

function toggleSearchRow(forceOpen) {
  const isHidden = searchContainer.classList.contains('hidden');
  const shouldOpen = forceOpen !== undefined ? forceOpen : isHidden;

  if (shouldOpen) {
    searchContainer.classList.remove('hidden');
    searchInput.focus();
  } else {
    searchContainer.classList.add('hidden');
    searchInput.value = '';
    searchQuery = '';
    applyFilters();
  }
}

function handleSearchInput() {
  searchQuery = searchInput.value.trim().toLowerCase();
  applyFilters();
}

// --- Feed Data Loading & Refresh ---------------------------------------------

async function loadFeed(forceRefresh = false) {
  showLoading(true);
  hideError();

  try {
    if (!forceRefresh) {
      // 1. Try local cache first for instant sub-second render
      const { feed_cache } = await chrome.storage.local.get('feed_cache');
      if (feed_cache && feed_cache.stories && feed_cache.stories.length > 0) {
        populateDataFromCache(feed_cache);
        showLoading(false);

        // If cache is reasonably fresh (< 1 hour), don't refetch
        const age = Date.now() - (feed_cache.timestamp || 0);
        if (age < 60 * 60 * 1000) {
          return;
        }
      }
    }

    // 2. Fetch fresh feed
    setRefreshButtonState(true);
    const url = `${FEED_URL}?_t=${Date.now()}`;
    const response = await fetch(url, {
      cache: forceRefresh ? 'no-cache' : 'default',
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const xmlText = await response.text();
    const parsed = parseFeed(xmlText);
    const dayFiltered = filterCurrentDayStories(parsed.items);

    // Save to cache
    const evalRes = evaluateWatchlist(dayFiltered.stories, userWatchlist);
    const cacheData = {
      title: parsed.title,
      lastBuildDate: parsed.lastBuildDate,
      currentDay: dayFiltered.currentDay,
      stories: dayFiltered.stories,
      totalCount: dayFiltered.totalCount,
      olderCount: dayFiltered.olderCount,
      timestamp: Date.now(),
      evalResult: {
        matchCount: evalRes.matchCount,
        matchesByStoryId: evalRes.matchesByStoryId,
      },
    };

    await chrome.storage.local.set({
      feed_cache: cacheData,
      last_updated: Date.now(),
    });

    populateDataFromCache(cacheData);
    showLoading(false);
  } catch (err) {
    console.error('Error fetching feed:', err);
    showLoading(false);
    // If we have cached stories already showing, don't break with full error screen
    if (allDayStories.length === 0) {
      showError(`Unable to load feed (${err.message}). Please check your connection.`);
    }
  } finally {
    setRefreshButtonState(false);
  }
}

function populateDataFromCache(cache) {
  allDayStories = cache.stories || [];
  currentDayStr = cache.currentDay || '';

  footerEditionDate.textContent = formatEditionDay(currentDayStr);
  footerStoryCount.textContent = `${allDayStories.length} stories`;

  renderTopicsBar();
  applyFilters();
  evaluateAlertsBanner();
}

function setRefreshButtonState(isRefreshing) {
  if (isRefreshing) {
    btnRefresh.classList.add('refreshing');
    btnRefresh.disabled = true;
  } else {
    btnRefresh.classList.remove('refreshing');
    btnRefresh.disabled = false;
  }
}

function showLoading(show) {
  if (show && allDayStories.length === 0) {
    loadingSpinner.classList.remove('hidden');
    storiesList.classList.add('hidden');
    emptyState.classList.add('hidden');
  } else {
    loadingSpinner.classList.add('hidden');
    storiesList.classList.remove('hidden');
  }
}

function showError(msg) {
  errorMessage.textContent = msg;
  errorBanner.classList.remove('hidden');
}

function hideError() {
  errorBanner.classList.add('hidden');
}

// --- Topic Navigation Pills & Scroll Controls --------------------------------

const CANONICAL_TOPIC_NAMES = [
  'Active Threats',
  'Vulnerabilities & Patches',
  'AI Security',
  'Supply Chain',
  'Breaches',
  'Fraud & Phishing',
  'Policy & Enforcement',
];

function updateTopicScrollButtons() {
  if (!topicsBar || !topicsFadeLeft || !topicsFadeRight) return;
  const scrollLeft = topicsBar.scrollLeft;
  const maxScrollLeft = topicsBar.scrollWidth - topicsBar.clientWidth;

  // Show/hide left fade overlay & floating chevron
  if (scrollLeft > 6) {
    topicsFadeLeft.classList.remove('is-hidden');
  } else {
    topicsFadeLeft.classList.add('is-hidden');
  }

  // Show/hide right fade overlay & floating chevron
  if (maxScrollLeft - scrollLeft > 6) {
    topicsFadeRight.classList.remove('is-hidden');
  } else {
    topicsFadeRight.classList.add('is-hidden');
  }
}

function renderTopicsBar() {
  topicsBar.innerHTML = '';

  // Calculate story counts per topic
  const countsByTopic = {};
  for (const s of allDayStories) {
    const key = (s.topic || 'General').trim();
    countsByTopic[key] = (countsByTopic[key] || 0) + 1;
  }

  // 1. "All" Pill
  const allPill = document.createElement('button');
  allPill.type = 'button';
  allPill.className = `topic-pill ${activeTopic === 'all' ? 'active' : ''}`;
  allPill.innerHTML = `All <span class="count">${allDayStories.length}</span>`;
  allPill.addEventListener('click', () => {
    activeTopic = 'all';
    updateActiveTopicPills();
    applyFilters();
    allPill.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    setTimeout(updateTopicScrollButtons, 200);
  });
  topicsBar.appendChild(allPill);

  // 2. Ordered topics matching board canonical sequence
  const topicsPresent = Object.keys(countsByTopic);
  topicsPresent.sort((a, b) => {
    const idxA = CANONICAL_TOPIC_NAMES.findIndex(
      (n) => n.toLowerCase() === a.toLowerCase()
    );
    const idxB = CANONICAL_TOPIC_NAMES.findIndex(
      (n) => n.toLowerCase() === b.toLowerCase()
    );
    if (idxA !== -1 && idxB !== -1) return idxA - idxB;
    if (idxA !== -1) return -1;
    if (idxB !== -1) return 1;
    return a.localeCompare(b);
  });

  for (const topicName of topicsPresent) {
    const hue = getTopicHue(topicName);
    const pill = document.createElement('button');
    pill.type = 'button';
    pill.className = `topic-pill ${activeTopic === topicName ? 'active' : ''}`;
    pill.style.setProperty('--pill-hue', String(hue));
    pill.dataset.topic = topicName;

    const dot = document.createElement('span');
    dot.className = 'topic-dot';

    const text = document.createTextNode(` ${topicName} `);
    const count = document.createElement('span');
    count.className = 'count';
    count.textContent = countsByTopic[topicName];

    pill.appendChild(dot);
    pill.appendChild(text);
    pill.appendChild(count);

    pill.addEventListener('click', () => {
      activeTopic = topicName;
      updateActiveTopicPills();
      applyFilters();
      pill.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
      setTimeout(updateTopicScrollButtons, 200);
    });

    topicsBar.appendChild(pill);
  }

  // Check scroll buttons visibility
  setTimeout(updateTopicScrollButtons, 50);
}

function updateActiveTopicPills() {
  const pills = topicsBar.querySelectorAll('.topic-pill');
  pills.forEach((p) => {
    if (activeTopic === 'all' && !p.dataset.topic) {
      p.classList.add('active');
    } else if (p.dataset.topic === activeTopic) {
      p.classList.add('active');
    } else {
      p.classList.remove('active');
    }
  });
}

// --- Filtering & Card Rendering ----------------------------------------------

function applyFilters() {
  filteredStories = allDayStories.filter((story) => {
    // Topic filter
    if (activeTopic !== 'all' && story.topic !== activeTopic) {
      return false;
    }

    // Search query filter
    if (searchQuery) {
      const matchInTitle = story.title.toLowerCase().includes(searchQuery);
      const matchInSummary = story.summary.toLowerCase().includes(searchQuery);
      const matchInUpdate = (story.update || '').toLowerCase().includes(searchQuery);
      const matchInTopic = (story.topic || '').toLowerCase().includes(searchQuery);
      const matchInLabels = (story.labels || []).some((l) =>
        l.toLowerCase().includes(searchQuery)
      );
      if (!matchInTitle && !matchInSummary && !matchInUpdate && !matchInTopic && !matchInLabels) {
        return false;
      }
    }

    return true;
  });

  // Update search stats indicator
  if (searchQuery) {
    searchStats.classList.remove('hidden');
    searchStats.textContent = `Showing ${filteredStories.length} of ${allDayStories.length} stories`;
  } else {
    searchStats.classList.add('hidden');
  }

  renderStoryCards();
}

function renderStoryCards() {
  storiesList.innerHTML = '';

  if (filteredStories.length === 0) {
    emptyState.classList.remove('hidden');
    return;
  }
  emptyState.classList.add('hidden');

  const evalRes = evaluateWatchlist(filteredStories, userWatchlist);

  filteredStories.forEach((story) => {
    const matches = evalRes.matchesByStoryId[story.id] || [];
    const isWatchedMatch = matches.length > 0;

    const card = document.createElement('article');
    card.className = `story-card ${isWatchedMatch ? 'is-watched-match' : ''}`;
    card.dataset.id = story.id;

    // 1. Watched Badge if matched
    if (isWatchedMatch) {
      const badge = document.createElement('div');
      badge.className = 'watched-badge';
      badge.textContent = `⚡ Alert Match: "${matches.join(', ')}"`;
      card.appendChild(badge);
    }

    // 2. Meta Top (Topic + Time)
    const metaTop = document.createElement('div');
    metaTop.className = 'story-meta-top';

    const topicSpan = document.createElement('span');
    topicSpan.className = 'story-topic';
    const topicHue = getTopicHue(story.topic);
    topicSpan.style.setProperty('--topic-hue', String(topicHue));

    const topicDot = document.createElement('span');
    topicDot.className = 'story-topic-dot';
    topicSpan.appendChild(topicDot);
    topicSpan.appendChild(document.createTextNode(story.topic || 'General'));

    const timeSpan = document.createElement('span');
    timeSpan.className = 'story-time';
    timeSpan.textContent = formatRelativeTime(story.timestamp);

    metaTop.appendChild(topicSpan);
    metaTop.appendChild(timeSpan);
    card.appendChild(metaTop);

    // 3. Story Title Link
    const titleLink = document.createElement('a');
    titleLink.className = 'story-title-link';
    titleLink.href = safeUrl(story.link) || `${SITE_URL}/#${story.id}`;
    titleLink.target = '_blank';
    titleLink.rel = 'noopener noreferrer';
    titleLink.textContent = story.title;
    card.appendChild(titleLink);

    // 4. Story Summary
    if (story.summary) {
      const summaryP = document.createElement('p');
      summaryP.className = 'story-summary';
      summaryP.textContent = story.summary;
      card.appendChild(summaryP);
    }

    // 5. Update Note (if present)
    if (story.update) {
      const updateBox = document.createElement('div');
      updateBox.className = 'story-update';
      const strong = document.createElement('strong');
      strong.textContent = 'Update: ';
      updateBox.appendChild(strong);
      updateBox.appendChild(document.createTextNode(story.update));
      card.appendChild(updateBox);
    }

    // 6. Labels / Tags Row
    if (story.labels && story.labels.length > 0) {
      const tagsContainer = document.createElement('div');
      tagsContainer.className = 'story-tags';

      story.labels.forEach((label) => {
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.style.setProperty('--tag-h', String(tagHue(label)));
        tag.textContent = label;
        // Clicking tag filters search instantly
        tag.style.cursor = 'pointer';
        tag.title = `Filter by "${label}"`;
        tag.addEventListener('click', (e) => {
          e.stopPropagation();
          toggleSearchRow(true);
          searchInput.value = label;
          handleSearchInput();
        });
        tagsContainer.appendChild(tag);
      });

      card.appendChild(tagsContainer);
    }

    // 7. Footer Meta (Sources & Link)
    const footerMeta = document.createElement('div');
    footerMeta.className = 'story-footer-meta';

    const sourcesSpan = document.createElement('span');
    sourcesSpan.className = 'story-sources';
    if (story.sources && story.sources.length > 0) {
      sourcesSpan.textContent = `Sources: ${story.sources.join(', ')}`;
    } else {
      sourcesSpan.textContent = 'Blast Radius';
    }

    const openLink = document.createElement('a');
    openLink.className = 'story-external-link';
    openLink.href = safeUrl(story.link) || `${SITE_URL}/#${story.id}`;
    openLink.target = '_blank';
    openLink.rel = 'noopener noreferrer';
    openLink.innerHTML = `Read ↗`;

    footerMeta.appendChild(sourcesSpan);
    footerMeta.appendChild(openLink);
    card.appendChild(footerMeta);

    storiesList.appendChild(card);
  });
}

// --- Watchlist & Notification Area --------------------------------------------

async function loadWatchlistSettings() {
  const { watchlist = [], desktop_notifications = false } = await chrome.storage.local.get([
    'watchlist',
    'desktop_notifications',
  ]);
  userWatchlist = watchlist;
  desktopNotificationsEnabled = desktop_notifications;

  chkDesktopNotifications.checked = desktopNotificationsEnabled;
  renderWatchlistTags();
  evaluateAlertsBanner();
}

function renderWatchlistTags() {
  watchlistTagsContainer.innerHTML = '';
  watchlistCountSpan.textContent = String(userWatchlist.length);

  if (userWatchlist.length === 0) {
    const emptyNotice = document.createElement('span');
    emptyNotice.style.fontSize = '11.5px';
    emptyNotice.style.color = 'var(--muted)';
    emptyNotice.textContent = 'No watched terms yet. Add one above!';
    watchlistTagsContainer.appendChild(emptyNotice);
    return;
  }

  userWatchlist.forEach((term, index) => {
    const isRegex = /^\/.+\/[a-z]*$/i.test(term);

    // Count how many stories in today's edition match this specific term
    let matchCount = 0;
    for (const story of allDayStories) {
      const rawHaystack = [
        story.title,
        story.summary,
        story.update,
        story.topic,
        ...(story.labels || []),
      ]
        .filter(Boolean)
        .join(' ');
      if (testTermMatch(term, rawHaystack, rawHaystack.toLowerCase())) {
        matchCount++;
      }
    }

    const chip = document.createElement('span');
    chip.className = `watchlist-chip ${isRegex ? 'is-regex' : ''}`;

    if (isRegex) {
      const regexBadge = document.createElement('span');
      regexBadge.className = 'chip-regex-badge';
      regexBadge.textContent = '.*';
      regexBadge.title = 'Regular Expression';
      chip.appendChild(regexBadge);
    }

    const text = document.createElement('span');
    text.textContent = term;
    chip.appendChild(text);

    // Match count pill for today's edition
    const countBadge = document.createElement('span');
    countBadge.className = `chip-match-count ${matchCount > 0 ? 'has-matches' : ''}`;
    countBadge.textContent = String(matchCount);
    countBadge.title = `${matchCount} matching ${
      matchCount === 1 ? 'story' : 'stories'
    } in current edition`;
    chip.appendChild(countBadge);

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'watchlist-chip-remove';
    removeBtn.setAttribute('aria-label', `Remove ${term}`);
    removeBtn.textContent = '✕';
    removeBtn.addEventListener('click', () => removeWatchlistTerm(index));
    chip.appendChild(removeBtn);

    watchlistTagsContainer.appendChild(chip);
  });
}

async function addWatchlistTerm(term) {
  const validation = validateWatchlistTerm(term, isRegexInputMode);

  if (!validation.valid) {
    watchlistErrorMsg.textContent = validation.error;
    watchlistErrorMsg.classList.remove('hidden');
    return false;
  }

  watchlistErrorMsg.classList.add('hidden');
  const formatted = validation.formatted;

  if (userWatchlist.some((t) => t.toLowerCase() === formatted.toLowerCase())) {
    watchlistErrorMsg.textContent = `"${formatted}" is already in your watchlist.`;
    watchlistErrorMsg.classList.remove('hidden');
    return false;
  }

  userWatchlist.push(formatted);
  await chrome.storage.local.set({ watchlist: userWatchlist });
  renderWatchlistTags();
  evaluateAlertsBanner();
  applyFilters();

  // Notify background worker to re-evaluate badge
  chrome.runtime.sendMessage({ action: 'CHECK_WATCHLIST', watchlist: userWatchlist });
  return true;
}

async function removeWatchlistTerm(index) {
  userWatchlist.splice(index, 1);
  await chrome.storage.local.set({ watchlist: userWatchlist });
  renderWatchlistTags();
  evaluateAlertsBanner();
  applyFilters();

  // Notify background worker
  chrome.runtime.sendMessage({ action: 'CHECK_WATCHLIST', watchlist: userWatchlist });
}

function evaluateAlertsBanner() {
  const evalRes = evaluateWatchlist(allDayStories, userWatchlist);
  if (evalRes.matchCount > 0) {
    watchlistBadgeDot.classList.remove('hidden');
    alertBanner.classList.remove('hidden');
    const terms = Array.from(
      new Set(evalRes.matchedStories.flatMap((m) => m.matches))
    );
    alertBannerText.textContent = `${evalRes.matchCount} matched ${
      evalRes.matchCount === 1 ? 'story' : 'stories'
    } for: "${terms.join(', ')}"`;
  } else {
    watchlistBadgeDot.classList.add('hidden');
    alertBanner.classList.add('hidden');
  }
}

// --- Event Handlers & Initialization -----------------------------------------

function attachEventListeners() {
  // Theme Toggle
  btnTheme.addEventListener('click', toggleTheme);

  // Refresh Button
  btnRefresh.addEventListener('click', () => loadFeed(true));

  // Retry Button
  btnRetry.addEventListener('click', () => loadFeed(true));

  // Topics Horizontal Scroll Navigation (Buttons, Wheel & Scroll)
  btnScrollTopicsLeft.addEventListener('click', () => {
    topicsBar.scrollBy({ left: -140, behavior: 'smooth' });
    setTimeout(updateTopicScrollButtons, 250);
  });

  btnScrollTopicsRight.addEventListener('click', () => {
    topicsBar.scrollBy({ left: 140, behavior: 'smooth' });
    setTimeout(updateTopicScrollButtons, 250);
  });

  topicsBar.addEventListener('scroll', updateTopicScrollButtons, { passive: true });

  // Topics Click & Drag to Scroll
  let isDown = false;
  let startX = 0;
  let initialScrollLeft = 0;
  let hasDragged = false;

  topicsBar.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    isDown = true;
    hasDragged = false;
    startX = e.pageX - topicsBar.offsetLeft;
    initialScrollLeft = topicsBar.scrollLeft;
    topicsBar.classList.add('is-dragging');
  });

  window.addEventListener('mousemove', (e) => {
    if (!isDown) return;
    const x = e.pageX - topicsBar.offsetLeft;
    const walk = x - startX;
    if (Math.abs(walk) > 4) {
      hasDragged = true;
    }
    if (hasDragged) {
      e.preventDefault();
      topicsBar.scrollLeft = initialScrollLeft - walk;
      updateTopicScrollButtons();
    }
  });

  window.addEventListener('mouseup', () => {
    if (!isDown) return;
    isDown = false;
    topicsBar.classList.remove('is-dragging');
    setTimeout(() => {
      hasDragged = false;
    }, 60);
  });

  // Intercept click on capture phase so dragging doesn't trigger pill selection
  topicsBar.addEventListener(
    'click',
    (e) => {
      if (hasDragged) {
        e.stopPropagation();
        e.preventDefault();
      }
    },
    true
  );

  topicsBar.addEventListener(
    'wheel',
    (e) => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
        e.preventDefault();
        topicsBar.scrollLeft += e.deltaY;
        updateTopicScrollButtons();
      }
    },
    { passive: false }
  );

  window.addEventListener('resize', updateTopicScrollButtons);

  // Search Toggle
  btnToggleSearch.addEventListener('click', () => toggleSearchRow());
  searchInput.addEventListener('input', handleSearchInput);
  btnClearSearch.addEventListener('click', () => {
    searchInput.value = '';
    searchQuery = '';
    applyFilters();
    searchInput.focus();
  });

  // Watchlist Modal Handlers
  btnWatchlist.addEventListener('click', () => {
    watchlistModal.classList.remove('hidden');
    watchlistErrorMsg.classList.add('hidden');
    watchlistInput.focus();
  });

  btnCloseWatchlist.addEventListener('click', () => {
    watchlistModal.classList.add('hidden');
  });

  btnDoneWatchlist.addEventListener('click', () => {
    watchlistModal.classList.add('hidden');
  });

  // Toggle regex mode button
  btnToggleRegexMode.addEventListener('click', () => {
    isRegexInputMode = !isRegexInputMode;
    if (isRegexInputMode) {
      btnToggleRegexMode.classList.add('active');
      watchlistInput.placeholder = 'e.g. /CVE-\\d+/i or CVE-\\d+';
    } else {
      btnToggleRegexMode.classList.remove('active');
      watchlistInput.placeholder = 'e.g. ransomware, CVE-2026, CrowdStrike';
    }
    watchlistErrorMsg.classList.add('hidden');
    watchlistInput.focus();
  });

  watchlistInput.addEventListener('input', () => {
    watchlistErrorMsg.classList.add('hidden');
    // If user starts typing /..., automatically highlight regex mode
    if (watchlistInput.value.trim().startsWith('/')) {
      btnToggleRegexMode.classList.add('active');
    } else if (!isRegexInputMode) {
      btnToggleRegexMode.classList.remove('active');
    }
  });

  watchlistForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const ok = await addWatchlistTerm(watchlistInput.value);
    if (ok) {
      watchlistInput.value = '';
      if (!isRegexInputMode) {
        btnToggleRegexMode.classList.remove('active');
      }
    }
  });

  chkDesktopNotifications.addEventListener('change', async (e) => {
    desktopNotificationsEnabled = e.target.checked;
    await chrome.storage.local.set({
      desktop_notifications: desktopNotificationsEnabled,
    });
  });

  btnClearAlertBadge.addEventListener('click', async () => {
    chrome.runtime.sendMessage({ action: 'CLEAR_ALERT_BADGE' });
    watchlistBadgeDot.classList.add('hidden');
    alertBanner.classList.add('hidden');
  });

  // Alert Banner Actions
  btnViewAlertMatches.addEventListener('click', () => {
    // Filter view to only matched stories
    const evalRes = evaluateWatchlist(allDayStories, userWatchlist);
    const matchedIds = new Set(evalRes.matchedStories.map((m) => m.story.id));
    filteredStories = allDayStories.filter((s) => matchedIds.has(s.id));
    renderStoryCards();
  });

  btnDismissAlertBanner.addEventListener('click', () => {
    alertBanner.classList.add('hidden');
  });

  // Keyboard Shortcuts
  window.addEventListener('keydown', (e) => {
    // '/' opens search
    if (e.key === '/' && document.activeElement !== searchInput && !watchlistModal.classList.contains('hidden') === false) {
      e.preventDefault();
      toggleSearchRow(true);
    }
    // 'Escape' closes modal or clears search
    if (e.key === 'Escape') {
      if (!watchlistModal.classList.contains('hidden')) {
        watchlistModal.classList.add('hidden');
      } else if (!searchContainer.classList.contains('hidden')) {
        toggleSearchRow(false);
      }
    }
  });
}

// Startup
async function init() {
  await initTheme();
  await loadWatchlistSettings();
  attachEventListeners();
  await loadFeed();
}

document.addEventListener('DOMContentLoaded', init);
