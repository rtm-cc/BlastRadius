// The board. Reads its settings from the inline #boot JSON, loads one
// days/<day>.json at a time, and search.json only once someone searches.
//
// Feed text is attacker-influenced, so every value reaches the DOM through
// textContent and every href goes through safeUrl(). Never innerHTML.
(function () {
  "use strict";

  var boot = JSON.parse(document.getElementById("boot").textContent);
  var board = document.getElementById("board");
  var statusLine = document.getElementById("status");
  var dayInput = document.getElementById("day");
  var dayLabel = document.getElementById("day-label");
  var prevButton = document.getElementById("prev");
  var nextButton = document.getElementById("next");
  var latestButton = document.getElementById("latest");
  var searchForm = document.getElementById("search-form");
  var searchInput = document.getElementById("q");

  var days = boot.days;
  var topics = {};
  boot.topics.forEach(function (t) { topics[t.id] = t; });
  var dayCache = {};
  var searchIndex = null;
  var SEARCH_LIMIT = 300;

  // --- small helpers ------------------------------------------------------

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function safeUrl(url) {
    return typeof url === "string" && /^https?:\/\//i.test(url) ? url : "";
  }

  function link(url, className, text) {
    var href = safeUrl(url);
    var node = el(href ? "a" : "span", className, text);
    if (href) {
      node.href = href;
      node.target = "_blank";
      node.rel = "noopener noreferrer";
    }
    return node;
  }

  function svg(path, className) {
    var ns = "http://www.w3.org/2000/svg";
    var icon = document.createElementNS(ns, "svg");
    icon.setAttribute("viewBox", "0 0 16 16");
    icon.setAttribute("aria-hidden", "true");
    if (className) icon.setAttribute("class", className);
    var p = document.createElementNS(ns, "path");
    p.setAttribute("d", path);
    icon.appendChild(p);
    return icon;
  }

  // A stable hue from any text, so a tag keeps its colour on every day.
  function hue(key) {
    var hash = 0;
    for (var i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) | 0;
    hash = ((hash >>> 16) ^ hash) * 0x45d9f3b;
    hash = ((hash >>> 16) ^ hash) * 0x45d9f3b;
    hash = (hash >>> 16) ^ hash;
    return Math.abs(hash) % 360;
  }

  function topicHue(id) {
    var topic = topics[id];
    return topic && typeof topic.color === "number" ? topic.color : hue(id);
  }

  function topicName(id) {
    return topics[id] ? topics[id].name : id;
  }

  function fold(text) {
    return String(text || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  // --- dates ----------------------------------------------------------------

  var WEEKDAY = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });

  function formatDay(day) {
    var parts = day.split("-");
    var ordered = boot.dateFormat === "mdy" ? [parts[1], parts[2], parts[0]]
      : boot.dateFormat === "ymd" ? parts
      : [parts[2], parts[1], parts[0]];
    var sep = boot.dateFormat === "ymd" ? "-" : "/";
    return WEEKDAY.format(new Date(day + "T12:00:00Z")) + ", " + ordered.join(sep);
  }

  var TIME = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: boot.timezone });
  var DAY_IN_ZONE = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: boot.timezone });
  var SHORT_DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: boot.timezone });

  // The time, with the date added when it is not the board's own day - a
  // story published on Sunday evening often lands on Monday's board.
  function formatPublished(iso, boardDay) {
    if (!iso) return "";
    var when = new Date(iso);
    if (isNaN(when)) return "";
    var time = TIME.format(when);
    return DAY_IN_ZONE.format(when) === boardDay ? time : SHORT_DATE.format(when) + ", " + time;
  }

  // --- routing --------------------------------------------------------------

  function params() {
    return new URLSearchParams(location.search);
  }

  function go(next, replace) {
    // A tag or a timeline day clicked inside the story sheet navigates
    // away from the story it shows.
    closeSheet();
    var query = new URLSearchParams();
    var currentTheme = params().get("theme");
    if (currentTheme && !next.hasOwnProperty("theme")) {
      query.set("theme", currentTheme);
    }
    Object.keys(next).forEach(function (key) {
      if (next[key]) query.set(key, next[key]);
    });
    var url = location.pathname + (query.toString() ? "?" + query : "");
    if (replace) history.replaceState(null, "", url);
    else history.pushState(null, "", url);
    route();
  }

  function currentDay() {
    var wanted = params().get("date");
    if (wanted && days.indexOf(wanted) !== -1) return wanted;
    if (wanted) {
      // The nearest board on or before the requested day.
      for (var i = days.length - 1; i >= 0; i--) if (days[i] <= wanted) return days[i];
      return days[0];
    }
    return days[days.length - 1];
  }

  function route() {
    var p = params();
    var urlTheme = p.get("theme");
    if (urlTheme === "light" || urlTheme === "dark") {
      setTheme(urlTheme, false);
    }
    if (p.get("q") || p.get("tag")) {
      searchInput.value = p.get("q") || "";
      renderSearch(p.get("q") || "", p.get("tag") || "");
    } else {
      searchInput.value = "";
      renderBoard(currentDay(), p.get("topic") || "");
    }
  }

  // --- the board -----------------------------------------------------------

  function loadDay(day) {
    if (!dayCache[day]) {
      dayCache[day] = fetch("days/" + day + ".json").then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
      dayCache[day].catch(function () { delete dayCache[day]; });
    }
    return dayCache[day];
  }

  function updateDayNav(day, searching) {
    var index = days.indexOf(day);
    dayLabel.textContent = searching ? "All days" : day ? formatDay(day) : "No boards yet";
    dayInput.value = day || "";
    if (days.length) {
      dayInput.min = days[0];
      dayInput.max = days[days.length - 1];
    }
    prevButton.disabled = searching || index <= 0;
    nextButton.disabled = searching || index === -1 || index >= days.length - 1;
    latestButton.hidden = !searching && index === days.length - 1;
  }

  function renderBoard(day, focus) {
    updateDayNav(day, false);
    document.title = boot.title + (day ? " · " + formatDay(day) : "");
    if (!day) {
      board.replaceChildren(el("p", "empty", "No boards yet. The first scheduled run will publish one."));
      statusLine.textContent = "";
      return;
    }
    var requested = params().get("date");
    statusLine.textContent = requested && requested !== day
      ? "No board for " + formatDay(requested) + " - showing " + formatDay(day) + "."
      : "";

    loadDay(day).then(function (data) {
      if (currentDay() !== day || params().get("q") || params().get("tag")) return;
      var byTopic = {};
      data.stories.forEach(function (s) { (byTopic[s.topic] = byTopic[s.topic] || []).push(s); });
      Object.keys(byTopic).forEach(function (t) { byTopic[t].sort(function (a, b) { return a.rank - b.rank; }); });

      var columns = focus && topics[focus] ? [[focus]] : boot.columns;
      var row = el("div", focus ? "columns focused" : "columns");
      columns.forEach(function (column) {
        // A retired topic only gets a column on days it published.
        var shown = column.filter(function (id) {
          return (topics[id] && topics[id].enabled) || byTopic[id];
        });
        if (!shown.length) return;
        var col = el("div", shown.length === 2 ? "column stacked" : "column");
        shown.forEach(function (id) { col.appendChild(panel(id, byTopic[id] || [], day, focus)); });
        row.appendChild(col);
      });
      board.replaceChildren(row);
    }).catch(function (err) {
      board.replaceChildren(el("p", "empty", "Could not load the board for " + formatDay(day) + " (" + err.message + ")."));
    });
  }

  function panel(topicId, stories, day, focus) {
    var section = el("section", "panel");
    section.style.setProperty("--topic-h", topicHue(topicId));
    var head = el("header", "panel-head");
    var title = el("h2", "panel-title");
    title.appendChild(el("span", "dot"));
    title.appendChild(el("span", "panel-name", topicName(topicId)));
    title.appendChild(el("span", "panel-count", stories.length ? String(stories.length) : ""));
    head.appendChild(title);

    var toggle = el("a", "icon-btn");
    if (focus) {
      toggle.href = "?date=" + encodeURIComponent(day);
      toggle.setAttribute("aria-label", "Back to all topics");
      toggle.title = "All topics";
      toggle.appendChild(svg("M10 3 5 8l5 5"));
    } else {
      toggle.href = "?date=" + encodeURIComponent(day) + "&topic=" + encodeURIComponent(topicId);
      toggle.setAttribute("aria-label", "Show only " + topicName(topicId));
      toggle.title = "Focus this topic";
      toggle.appendChild(svg("M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"));
    }
    toggle.addEventListener("click", function (event) {
      event.preventDefault();
      go({ date: day, topic: focus ? "" : topicId });
    });
    head.appendChild(toggle);
    section.appendChild(head);

    // Focused, the topic is a grid of equal tiles whose details open in a
    // sheet; on the board, each card unfolds its details in place.
    var body = el("div", focus ? "panel-body grid" : "panel-body");
    if (stories.length) {
      stories.forEach(function (story, i) { body.appendChild(focus ? tile(story, i, day) : card(story, i, day)); });
    } else {
      var empty = el("div", "panel-empty");
      empty.appendChild(el("p", "panel-empty-title", "Nothing published"));
      empty.appendChild(el("p", null, "No story for this topic cleared the bar that day, or its run failed."));
      body.appendChild(empty);
    }
    section.appendChild(body);
    return section;
  }

  function thumb(story) {
    var box = el("div", "thumb");
    box.style.setProperty("--ph", hue(story.title));
    var image = safeUrl(story.image);
    if (image) {
      var img = el("img");
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      img.referrerPolicy = "no-referrer";
      img.draggable = false;
      img.addEventListener("error", function () { img.remove(); });
      img.src = image;
      box.appendChild(img);
    }
    box.appendChild(el("span", "rank", String(story.rank)));
    if (story.isUpdate) box.appendChild(el("span", "badge-update", "Update"));
    return box;
  }

  function tagChip(label) {
    var chip = el("a", boot.coloredTags ? "chip chip-colored" : "chip", label);
    chip.href = "?tag=" + encodeURIComponent(label);
    chip.title = "Every story tagged " + label;
    if (boot.coloredTags) chip.style.setProperty("--tag-h", hue(label));
    chip.addEventListener("click", function (event) {
      event.preventDefault();
      go({ tag: label });
    });
    return chip;
  }

  function details(className, summaryText) {
    var node = el("details", className);
    var summary = el("summary", null);
    summary.appendChild(svg("M6 4l4 4-4 4V4z", "caret"));
    summary.appendChild(el("span", null, summaryText));
    node.appendChild(summary);
    return node;
  }

  function sourceCount(story) {
    var seen = {};
    story.coverage.forEach(function (c) { seen[c.source] = true; });
    return Object.keys(seen).length;
  }

  function coverageList(story) {
    var list = el("ul", "fold-body coverage-list");
    story.coverage.forEach(function (c) {
      var item = el("li");
      item.appendChild(link(c.url, null, c.source + ": " + c.title));
      list.appendChild(item);
    });
    return list;
  }

  function card(story, index, day) {
    var article = el("article", "card");
    article.style.animationDelay = Math.min(index, 8) * 40 + "ms";

    var main = link(story.url, "card-main");
    main.appendChild(thumb(story));
    var text = el("div", "card-text");
    text.appendChild(el("p", "card-title", story.title));
    text.appendChild(el("p", "card-summary", story.summary));
    var meta = el("p", "card-meta");
    meta.appendChild(el("span", "card-sources", story.sources.join(", ")));
    var when = formatPublished(story.published, day);
    if (when) {
      meta.appendChild(el("span", "sep", "·"));
      meta.appendChild(el("span", null, when));
    }
    text.appendChild(meta);
    main.appendChild(text);
    article.appendChild(main);

    var extra = el("div", "card-extra");
    if (story.labels.length) {
      var chips = el("div", "chips");
      story.labels.forEach(function (label) { chips.appendChild(tagChip(label)); });
      extra.appendChild(chips);
    }

    if (story.rationale) {
      var why = details("fold", "Rationale");
      var whyBody = el("div", "fold-body");
      whyBody.appendChild(el("p", null, story.rationale));
      if (story.whatChanged) whyBody.appendChild(el("p", null, "What changed: " + story.whatChanged));
      why.appendChild(whyBody);
      extra.appendChild(why);
    }

    var count = sourceCount(story);
    if (story.coverage.length > 1) {
      var coverage = details("fold coverage", "Full coverage · " + count + " source" + (count === 1 ? "" : "s"));
      coverage.appendChild(coverageList(story));
      extra.appendChild(coverage);
    }

    if (story.timeline.length > 1) extra.appendChild(timeline(story));
    article.appendChild(extra);
    return article;
  }

  // A focused topic's card: always the same shape - image, three lines of
  // title, four of summary, source and time pinned to the bottom - so a
  // row lines up whatever the story. The first is the featured lead. A
  // click opens the full story in a sheet; a modified or middle click
  // still opens the article itself.
  function tile(story, index, day) {
    var article = el("article", index === 0 ? "card tile featured" : "card tile");
    article.style.animationDelay = Math.min(index, 12) * 30 + "ms";

    var main = link(story.url, "card-main");
    main.setAttribute("aria-haspopup", "dialog");
    main.appendChild(thumb(story));
    var text = el("div", "card-text");
    text.appendChild(el("p", "card-title", story.title));
    text.appendChild(el("p", "card-summary", story.summary));
    var meta = el("p", "card-meta");
    meta.appendChild(el("span", "card-sources", story.sources[0] || ""));
    var count = sourceCount(story);
    if (count > 1) meta.appendChild(el("span", "more-sources", "+" + (count - 1)));
    var when = formatPublished(story.published, day);
    if (when) {
      meta.appendChild(el("span", "sep", "·"));
      meta.appendChild(el("span", null, when));
    }
    text.appendChild(meta);
    main.appendChild(text);
    main.addEventListener("click", function (event) {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      openStory(story, day);
    });
    article.appendChild(main);
    return article;
  }

  // --- the story sheet --------------------------------------------------------

  var sheet = null;

  function storySheet() {
    if (!sheet) {
      sheet = el("dialog", "story-sheet");
      // The dialog has no padding, so a click whose target is the dialog
      // itself landed on the backdrop.
      sheet.addEventListener("click", function (event) {
        if (event.target === sheet) sheet.close();
      });
      sheet.addEventListener("close", function () { sheet.replaceChildren(); });
      document.body.appendChild(sheet);
    }
    return sheet;
  }

  function closeSheet() {
    if (sheet && sheet.open) sheet.close();
  }

  function sheetSection(title, content) {
    var section = el("section", "sheet-section");
    section.appendChild(el("h3", null, title));
    section.appendChild(content);
    return section;
  }

  function openStory(story, day) {
    var dialog = storySheet();
    dialog.setAttribute("aria-label", story.title);
    dialog.style.setProperty("--topic-h", topicHue(story.topic));

    var inner = el("div", "sheet-inner");
    var close = el("button", "sheet-close");
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.appendChild(svg("M4 4l8 8M12 4l-8 8"));
    close.addEventListener("click", closeSheet);
    inner.appendChild(close);

    var picture = thumb(story);
    picture.querySelectorAll(".rank, .badge-update").forEach(function (badge) { badge.remove(); });
    inner.appendChild(picture);

    var body = el("div", "sheet-body");
    var kicker = el("p", "sheet-kicker");
    kicker.appendChild(el("span", "sheet-topic", topicName(story.topic) + " · #" + story.rank));
    if (story.isUpdate) kicker.appendChild(el("span", "pill pill-update", "Update"));
    body.appendChild(kicker);
    body.appendChild(el("h2", "sheet-title", story.title));
    var meta = el("p", "card-meta");
    meta.appendChild(el("span", null, story.sources.join(", ")));
    var when = formatPublished(story.published, day);
    if (when) {
      meta.appendChild(el("span", "sep", "·"));
      meta.appendChild(el("span", null, when));
    }
    body.appendChild(meta);
    body.appendChild(el("p", "sheet-summary", story.summary));
    body.appendChild(link(story.url, "sheet-read", "Read the article ↗"));

    if (story.whatChanged) body.appendChild(sheetSection("What changed", el("p", null, story.whatChanged)));
    if (story.rationale) body.appendChild(sheetSection("Why it is here", el("p", null, story.rationale)));
    if (story.coverage.length > 1) {
      var count = sourceCount(story);
      body.appendChild(sheetSection("Full coverage · " + count + " source" + (count === 1 ? "" : "s"), coverageList(story)));
    }
    if (story.timeline.length > 1) {
      var developments = timeline(story);
      developments.open = true;
      body.appendChild(developments);
    }
    if (story.labels.length) {
      var chips = el("div", "chips");
      story.labels.forEach(function (label) { chips.appendChild(tagChip(label)); });
      body.appendChild(chips);
    }

    inner.appendChild(body);
    dialog.replaceChildren(inner);
    dialog.showModal();
    inner.scrollTop = 0;
    close.focus();
  }

  function timeline(story) {
    var node = details("fold developments", "Developments");
    node.querySelector("summary").appendChild(el("span", "pill", story.timeline.length + " events"));
    var list = el("ol", "fold-body timeline");
    story.timeline.forEach(function (event, i) {
      var item = el("li", event.id === story.id ? "current" : null);
      var head = el("div", "event-head");
      var day = el("a", "event-day", formatDay(event.day));
      day.href = "?date=" + encodeURIComponent(event.day);
      day.addEventListener("click", function (e) {
        e.preventDefault();
        go({ date: event.day });
      });
      head.appendChild(day);
      head.appendChild(el("span", "pill", i === 0 ? "First tracked" : event.isUpdate ? "Update" : "Development"));
      if (event.id === story.id) head.appendChild(el("span", "this-card", "This card"));
      item.appendChild(head);
      item.appendChild(link(event.url, "event-title", event.title));
      item.appendChild(el("p", null, event.text));
      list.appendChild(item);
    });
    node.appendChild(list);
    return node;
  }

  // --- search ---------------------------------------------------------------

  function loadSearch() {
    if (!searchIndex) {
      searchIndex = fetch("search.json").then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (rows) {
        rows.forEach(function (row) {
          row.haystack = fold([row.title, row.summary, row.labels.join(" "), row.sources.join(" "), topicName(row.topic)].join(" "));
        });
        return rows;
      });
      searchIndex.catch(function () { searchIndex = null; });
    }
    return searchIndex;
  }

  function renderSearch(query, tag) {
    updateDayNav(currentDay(), true);
    document.title = boot.title + " · " + (tag ? "#" + tag : query);
    statusLine.textContent = "Searching…";
    loadSearch().then(function (rows) {
      var p = params();
      if ((p.get("q") || "") !== query || (p.get("tag") || "") !== tag) return;
      var terms = fold(query).split(/\s+/).filter(Boolean);
      var wantedTag = tag.toLowerCase();
      var hits = rows.filter(function (row) {
        if (wantedTag && !row.labels.some(function (l) { return l.toLowerCase() === wantedTag; })) return false;
        return terms.every(function (t) { return row.haystack.indexOf(t) !== -1; });
      });
      statusLine.textContent = hits.length + " stor" + (hits.length === 1 ? "y" : "ies") +
        (tag ? " tagged " + tag : "") + (query ? " matching “" + query + "”" : "") +
        (hits.length > SEARCH_LIMIT ? ", showing the newest " + SEARCH_LIMIT : "") + ".";

      var list = el("div", "results");
      var lastDay = null;
      var group = null;
      hits.slice(0, SEARCH_LIMIT).forEach(function (row) {
        if (row.day !== lastDay) {
          lastDay = row.day;
          var heading = el("h2", "results-day");
          var open = el("a", null, formatDay(row.day));
          open.href = "?date=" + encodeURIComponent(row.day);
          open.title = "Open this day's board";
          open.addEventListener("click", function (e) {
            e.preventDefault();
            go({ date: row.day });
          });
          heading.appendChild(open);
          list.appendChild(heading);
          group = el("div", "results-group");
          list.appendChild(group);
        }
        group.appendChild(result(row));
      });
      var clear = el("button", "text-btn", "Back to the board");
      clear.type = "button";
      clear.addEventListener("click", function () { go({}); });
      var wrap = el("div", "search-view");
      wrap.appendChild(clear);
      wrap.appendChild(list);
      board.replaceChildren(wrap);
    }).catch(function (err) {
      statusLine.textContent = "Search is unavailable (" + err.message + ").";
    });
  }

  function result(row) {
    var item = el("article", "result");
    item.style.setProperty("--topic-h", topicHue(row.topic));
    item.appendChild(el("span", "result-topic", topicName(row.topic)));
    item.appendChild(link(row.url, "result-title", row.title));
    item.appendChild(el("p", "result-summary", row.summary));
    var meta = el("div", "chips");
    meta.appendChild(el("span", "result-sources", row.sources.join(", ")));
    row.labels.forEach(function (label) { meta.appendChild(tagChip(label)); });
    item.appendChild(meta);
    return item;
  }

  // --- controls -------------------------------------------------------------

  function step(delta) {
    var index = days.indexOf(currentDay()) + delta;
    if (index >= 0 && index < days.length) go({ date: days[index], topic: params().get("topic") });
  }

  prevButton.addEventListener("click", function () { step(-1); });
  nextButton.addEventListener("click", function () { step(1); });
  latestButton.addEventListener("click", function () { go({ topic: params().get("topic") }); });
  dayInput.addEventListener("change", function () {
    if (dayInput.value) go({ date: dayInput.value, topic: params().get("topic") });
  });
  dayLabel.parentElement.addEventListener("click", function () {
    try { dayInput.showPicker(); } catch (_) { dayInput.focus(); }
  });
  searchForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var query = searchInput.value.trim();
    go(query ? { q: query } : {});
  });
  searchInput.addEventListener("search", function () {
    if (!searchInput.value && params().get("q")) go({});
  });
  document.getElementById("home").addEventListener("click", function (event) {
    event.preventDefault();
    go({});
  });
  document.addEventListener("keydown", function (event) {
    // The open sheet owns the keyboard; Escape closes it natively.
    if (sheet && sheet.open) return;
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    var searching = params().get("q") || params().get("tag");
    if (event.key === "/" && !typing) {
      event.preventDefault();
      searchInput.focus();
    } else if (event.key === "Escape" && searching) {
      searchInput.blur();
      go({});
    } else if (!typing && !searching && event.key === "ArrowLeft") {
      step(-1);
    } else if (!typing && !searching && event.key === "ArrowRight") {
      step(1);
    }
  });

  // --- theme ---------------------------------------------------------------

  var themeToggle = document.getElementById("theme-toggle");

  function resolvedTheme() {
    var urlTheme = params().get("theme");
    if (urlTheme === "light" || urlTheme === "dark") return urlTheme;
    var explicit = document.documentElement.getAttribute("data-theme");
    if (explicit === "light" || explicit === "dark") return explicit;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function updateThemeUI(theme) {
    if (!themeToggle) return;
    var nextTheme = theme === "dark" ? "light" : "dark";
    themeToggle.setAttribute("aria-label", "Switch to " + nextTheme + " theme");
    themeToggle.setAttribute("title", "Switch to " + nextTheme + " theme");
    var metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) metaTheme.setAttribute("content", theme === "dark" ? "#0a0b0e" : "#f7f7fa");
  }

  function setTheme(theme, updateUrl) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("theme", theme); } catch (_) {}
    updateThemeUI(theme);
    if (updateUrl) {
      var p = params();
      p.set("theme", theme);
      var newUrl = location.pathname + "?" + p.toString();
      history.replaceState(null, "", newUrl);
    }
  }

  if (themeToggle) {
    updateThemeUI(resolvedTheme());
    themeToggle.addEventListener("click", function () {
      var next = resolvedTheme() === "dark" ? "light" : "dark";
      setTheme(next, true);
    });
    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
        if (!localStorage.getItem("theme") && !params().get("theme")) {
          updateThemeUI(resolvedTheme());
        }
      });
    }
  }

  window.addEventListener("popstate", route);

  route();
})();
