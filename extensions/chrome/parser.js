/**
 * Blast Radius RSS Feed Parser
 * Pure JavaScript, zero-dependency parser compatible with both
 * Service Worker (background.js) and DOM (popup.js) contexts.
 */

export function unescapeXml(str) {
  if (!str) return '';
  return str
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

export function parseFeed(xmlText) {
  if (!xmlText || typeof xmlText !== 'string') {
    return { title: '', lastBuildDate: '', items: [] };
  }

  // Extract channel level metadata
  const channelTitleMatch = /<channel>[\s\S]*?<title>(.*?)<\/title>/i.exec(xmlText);
  const channelTitle = channelTitleMatch ? unescapeXml(channelTitleMatch[1].trim()) : 'Blast Radius Digest';

  const lastBuildMatch = /<lastBuildDate>(.*?)<\/lastBuildDate>/i.exec(xmlText);
  const lastBuildDate = lastBuildMatch ? lastBuildMatch[1].trim() : '';

  const items = [];
  const itemRegex = /<item>([\s\S]*?)<\/item>/gi;
  let match;

  while ((match = itemRegex.exec(xmlText)) !== null) {
    const itemXml = match[1];

    const getTag = (tag) => {
      const m = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, 'i').exec(itemXml);
      return m ? unescapeXml(m[1].trim()) : '';
    };

    const title = getTag('title');
    const link = getTag('link');
    const guid = getTag('guid') || link;
    const pubDate = getTag('pubDate');
    const timestamp = pubDate ? new Date(pubDate).getTime() : Date.now();
    const isoDate = !isNaN(timestamp) ? new Date(timestamp).toISOString() : new Date().toISOString();

    // Extract categories
    const categories = [];
    const catRegex = /<category[^>]*>([\s\S]*?)<\/category>/gi;
    let cm;
    while ((cm = catRegex.exec(itemXml)) !== null) {
      const cat = unescapeXml(cm[1].trim());
      if (cat) categories.push(cat);
    }

    const topic = categories[0] || 'General';
    const labels = categories.slice(1);

    // Extract enclosure image
    let imageUrl = '';
    const encMatch = /<enclosure[^>]*url=["']([^"']+)["']/i.exec(itemXml);
    if (encMatch) imageUrl = encMatch[1];

    // Extract description content
    const desc = getTag('description');
    if (!imageUrl) {
      const imgMatch = /<img[^>]*src=["']([^"']+)["']/i.exec(desc);
      if (imgMatch) imageUrl = imgMatch[1];
    }

    // Extract summary and update text from <p> tags
    let summary = '';
    let update = '';
    const pRegex = /<p[^>]*>([\s\S]*?)<\/p>/gi;
    let pm;
    while ((pm = pRegex.exec(desc)) !== null) {
      const rawText = pm[1].replace(/<[^>]+>/g, '').trim();
      if (!rawText) continue;
      if (rawText.startsWith('Topic:') || rawText.startsWith('Related Coverage:')) continue;
      if (/^Update:\s*/i.test(rawText)) {
        update = rawText.replace(/^Update:\s*/i, '').trim();
      } else if (!summary) {
        summary = rawText;
      }
    }

    // Extract sources
    let sources = [];
    const srcMatch = /Sources:\s*([^|<]+)/i.exec(desc);
    if (srcMatch) {
      sources = srcMatch[1]
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    } else if (link) {
      try {
        const u = new URL(link);
        sources = [u.hostname.replace(/^www\./, '')];
      } catch (_) {}
    }

    items.push({
      id: guid,
      title,
      link,
      pubDate,
      timestamp,
      date: isoDate,
      topic,
      labels,
      summary,
      update,
      imageUrl,
      sources,
    });
  }

  return {
    title: channelTitle,
    lastBuildDate,
    items,
  };
}

/**
 * Filter stories for current day / latest edition.
 * Looks at the newest story timestamp and returns all stories
 * within a 24-hour window from that newest story.
 */
export function filterCurrentDayStories(items) {
  if (!items || items.length === 0) {
    return {
      currentDay: '',
      stories: [],
      totalCount: 0,
      olderCount: 0,
    };
  }

  // Find max timestamp
  let maxTime = 0;
  for (const item of items) {
    if (item.timestamp && item.timestamp > maxTime) {
      maxTime = item.timestamp;
    }
  }

  // 24 hour threshold from the latest published item
  const cutoff = maxTime - 24 * 60 * 60 * 1000;
  const currentStories = [];
  const olderStories = [];

  for (const item of items) {
    if (item.timestamp >= cutoff) {
      currentStories.push(item);
    } else {
      olderStories.push(item);
    }
  }

  const latestDateObj = new Date(maxTime);
  const currentDay = latestDateObj.toISOString().slice(0, 10);

  return {
    currentDay,
    stories: currentStories,
    totalCount: items.length,
    olderCount: olderStories.length,
  };
}

/**
 * Validate a watchlist candidate term.
 * Supports plain text (icase) or regex (/pattern/flags).
 */
export function validateWatchlistTerm(term, isRegexMode = false) {
  const clean = (term || '').trim();
  if (!clean) return { valid: false, error: 'Term cannot be empty' };

  let candidate = clean;
  if (isRegexMode && !candidate.startsWith('/')) {
    candidate = `/${candidate}/i`;
  }

  const slashMatch = /^\/(.+)\/([a-z]*)$/i.exec(candidate);
  if (slashMatch) {
    try {
      new RegExp(slashMatch[1], slashMatch[2]);
      return { valid: true, formatted: candidate, isRegex: true };
    } catch (e) {
      return {
        valid: false,
        error: `Invalid regex: ${e.message}`,
        formatted: candidate,
        isRegex: true,
      };
    }
  }

  return { valid: true, formatted: clean, isRegex: false };
}

/**
 * Test whether a single term or regex matches haystack text.
 * Plain strings use case-insensitive substring search.
 * Regexes (/pattern/flags) use case-insensitive regex by default.
 */
export function testTermMatch(rawTerm, rawHaystack, lowerHaystack) {
  if (!rawTerm) return false;
  const trimmed = typeof rawTerm === 'string' ? rawTerm.trim() : '';
  if (!trimmed) return false;

  // Regex format: /pattern/flags
  const slashMatch = /^\/(.+)\/([a-z]*)$/i.exec(trimmed);
  if (slashMatch) {
    try {
      const pattern = slashMatch[1];
      let flags = slashMatch[2] || '';
      // Ensure 'i' flag for case-insensitivity unless explicitly specified
      if (!flags.includes('i')) {
        flags += 'i';
      }
      const re = new RegExp(pattern, flags);
      return re.test(rawHaystack);
    } catch (err) {
      console.warn('Invalid regex in watchlist:', trimmed, err);
      return false;
    }
  }

  // Plain string term: case-insensitive (icase) substring match
  return lowerHaystack.includes(trimmed.toLowerCase());
}

/**
 * Check if a story matches any keyword in the watchlist.
 * Supports case-insensitive plain terms and /pattern/flags regexes.
 */
export function matchesWatchlist(story, watchlist) {
  if (!watchlist || watchlist.length === 0) return [];
  const matched = [];

  const rawHaystack = [
    story.title,
    story.summary,
    story.update,
    story.topic,
    ...(story.labels || []),
  ]
    .filter(Boolean)
    .join(' ');

  const lowerHaystack = rawHaystack.toLowerCase();

  for (const item of watchlist) {
    const rawTerm = typeof item === 'string' ? item : (item.term || '');
    if (testTermMatch(rawTerm, rawHaystack, lowerHaystack)) {
      matched.push(rawTerm);
    }
  }

  return matched;
}

/**
 * Evaluate all stories against watchlist.
 */
export function evaluateWatchlist(stories, watchlist) {
  if (!watchlist || watchlist.length === 0) {
    return { matchedStories: [], matchCount: 0, matchesByStoryId: {} };
  }

  const matchesByStoryId = {};
  const matchedStories = [];

  for (const story of stories) {
    const matches = matchesWatchlist(story, watchlist);
    if (matches.length > 0) {
      matchesByStoryId[story.id] = matches;
      matchedStories.push({ story, matches });
    }
  }

  return {
    matchedStories,
    matchCount: matchedStories.length,
    matchesByStoryId,
  };
}
