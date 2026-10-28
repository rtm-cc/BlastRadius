# Finding targeted Google News topic feeds

Google News has two different kinds of result that can share the same visible
name:

- A **search** is keyword matching. Its URL contains `/search?q=...` and can
  include loosely related or low-quality results.
- A **topic** is a Google-defined entity or subject. Its URL contains
  `/topics/CAAq...`; the opaque `CAAq...` value is Google's selector for that
  curated topic feed.

The topic ID is not something that can be derived from a word. Google creates
and exposes it in the Google News web interface, so use the interface to
discover it.

## Example: Nvidia

1. Open Google News and search for `Nvidia`:

   ```text
   https://news.google.com/search?q=Nvidia&hl=en-US&gl=US&ceid=US:en
   ```

2. In the search page, use the **Topics** result/chip on the right side and
   open the topic named **Nvidia**. Do not copy the `/search` URL.

3. The address bar now contains Google’s topic selector, for example:

   ```text
   https://news.google.com/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGx5YUY4U0FtVnVLQUFQAQ?hl=en-US&gl=US&ceid=US:en
   ```

4. Copy the opaque part after `/topics/` into a `google_news` entry in
   `config/sources/<topic>.yaml`, and carry `hl`/`gl` over as `language`/`country`
   if they are not `en-US`/`US`:

   ```yaml
   - id: gnews_nvidia
     type: google_news
     name: Google News - Nvidia
     google_topic: CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGx5YUY4U0FtVnVLQUFQAQ
     max_age_hours: 24
     max_items: 25
   ```

   The run fetches this equivalent RSS feed:

   ```text
   https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGx5YUY4U0FtVnVLQUFQAQ?hl=en-US&gl=US&ceid=US:en
   ```

   `python -m top10 check-feed '<that rss url>'` shows what it returns.

That topic feed is generally much more targeted than the keyword search feed,
even though both are labelled “Nvidia.”

## Go narrower when Google offers a tab

After opening a topic, click any specific subtopic/tab that Google provides.
If its URL contains both of these segments:

```text
/topics/<TOPIC_ID>/sections/<SECTION_ID>
```

put `TOPIC_ID` in `google_topic` and `SECTION_ID` in `google_section`.
`SECTION_ID` is another opaque selector. Leaving it out widens the source back
to the topic’s default feed.

## Practical workflow

Search in Google News only to discover an entity/topic. Then open Google’s
**Topics** result, optionally choose a focused tab, and copy its ids into
`config/sources/<topic>.yaml`. If Google offers no topic result, it has not exposed a reusable
topic feed for that query; use `query:` instead of `google_topic:`, or a more
specific query.
