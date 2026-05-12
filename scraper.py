import os
import re
import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup
import anthropic

BOARD_PAGE_URL = "https://community.atlassian.com/forums/Jira-questions/qa-p/jira-questions/page/{page}"
COMMUNITY_ROOT = "https://community.atlassian.com"

RESULTS_FILE  = os.path.join(os.path.dirname(__file__), "results.json")
HISTORY_FILE  = os.path.join(os.path.dirname(__file__), "history.json")
CACHE_FILE    = os.path.join(os.path.dirname(__file__), "post_cache.json")
SUMMARY_FILE  = os.path.join(os.path.dirname(__file__), "exec_summary.json")

DAYS_WINDOW = 90
MAX_PAGES   = 200    # safety cap — well beyond 90 days
PAGE_SLEEP  = 0.4   # seconds between listing page fetches

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


# ─── Date helpers ──────────────────────────────────────────────────────────────

def parse_relative_time(text: str) -> datetime | None:
    """
    Convert tile detail text to a UTC datetime.
    Handles: '38m ago', '2 hours ago', 'yesterday', 'Monday', 'April 16, 2026'.
    """
    now = datetime.now(timezone.utc)

    relative_patterns = [
        (r"(\d+)\s*m(?:in(?:utes?)?)?\s+ago",  lambda n: now - timedelta(minutes=n)),
        (r"(\d+)\s+minutes?\s+ago",             lambda n: now - timedelta(minutes=n)),
        (r"(\d+)\s*h(?:ours?)?\s+ago",          lambda n: now - timedelta(hours=n)),
        (r"(\d+)\s+hours?\s+ago",               lambda n: now - timedelta(hours=n)),
        (r"(\d+)\s*d(?:ays?)?\s+ago",           lambda n: now - timedelta(days=n)),
        (r"(\d+)\s+days?\s+ago",                lambda n: now - timedelta(days=n)),
        (r"(\d+)\s*w(?:eeks?)?\s+ago",          lambda n: now - timedelta(weeks=n)),
        (r"(\d+)\s+weeks?\s+ago",               lambda n: now - timedelta(weeks=n)),
        (r"(\d+)\s*mo(?:nths?)?\s+ago",         lambda n: now - timedelta(days=n * 30)),
        (r"(\d+)\s+months?\s+ago",              lambda n: now - timedelta(days=n * 30)),
        (r"(\d+)\s*y(?:ears?)?\s+ago",          lambda n: now - timedelta(days=n * 365)),
        (r"(\d+)\s+years?\s+ago",               lambda n: now - timedelta(days=n * 365)),
    ]
    for pattern, calc in relative_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return calc(int(m.group(1)))

    if re.search(r"\byesterday\b", text, re.IGNORECASE):
        return now - timedelta(days=1)

    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, day in enumerate(weekdays):
        if re.search(rf"\b{day}\b", text, re.IGNORECASE):
            diff = (now.weekday() - i) % 7 or 7
            return now - timedelta(days=diff)

    # Absolute date: "April 16, 2026" or "Apr 16, 2026"
    m = re.search(
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
        r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(\d{1,2}),?\s+(\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

    return None


# ─── Scraping ──────────────────────────────────────────────────────────────────

def scrape_page(page_num: int) -> list[dict]:
    """Return post dicts from a single board listing page (no extra HTTP fetches)."""
    url = BOARD_PAGE_URL.format(page=page_num)
    response = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")

    posts = []
    for tag in soup.find_all("h3"):
        parent_classes = " ".join(tag.parent.get("class", []))
        if "atl-post-list__tile__heading-wrapper" not in parent_classes:
            continue
        tile = tag.parent.parent
        title = tag.get_text(strip=True)
        if not title:
            continue
        link = tag.find("a", href=True)
        post_url = COMMUNITY_ROOT + link["href"] if link else None
        details = tile.find("div", class_="atl-post-list__tile__details-wrapper")
        details_text = details.get_text(separator=" ", strip=True) if details else ""
        estimated_date = parse_relative_time(details_text)
        posts.append({"title": title, "url": post_url, "post_date": estimated_date})
    return posts


def scrape_all_posts_in_window(
    days: int = DAYS_WINDOW,
    page_callback=None,
) -> list[dict]:
    """
    Paginate through the board, collecting posts until a page's oldest post
    falls beyond `days` days.  Returns all posts within the window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    collected: list[dict] = []

    for page_num in range(1, MAX_PAGES + 1):
        if page_callback:
            page_callback(page_num, len(collected))

        posts = scrape_page(page_num)
        if not posts:
            break

        within = [p for p in posts if p["post_date"] is None or p["post_date"] >= cutoff]
        collected.extend(within)

        oldest = min(
            (p["post_date"] for p in posts if p["post_date"] is not None),
            default=None,
        )
        if oldest is not None and oldest < cutoff:
            break

        time.sleep(PAGE_SLEEP)

    # Serialise datetimes to ISO strings
    for p in collected:
        if isinstance(p["post_date"], datetime):
            p["post_date"] = p["post_date"].isoformat()

    return collected


# ─── Analysis cache ────────────────────────────────────────────────────────────

def load_cache() -> dict[str, dict]:
    """Return {url: analysis_dict} from the persistent cache."""
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE) as f:
        return json.load(f)


def save_cache(cache: dict[str, dict]) -> None:
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


# ─── Claude analysis ───────────────────────────────────────────────────────────

def analyse_title(client: anthropic.Anthropic, title: str) -> dict:
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": (
                    "Analyse this Jira community post title and respond with a JSON object only "
                    "(no markdown, no extra text) with exactly these keys: "
                    '"theme", "sentiment", "severity" (one of: low, medium, high), "summary" (one line).\n\n'
                    f"Title: {title}"
                ),
            }
        ],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


# ─── Main entry point ──────────────────────────────────────────────────────────

def run_scraper(progress_callback=None) -> list[dict]:
    """
    Full pipeline:
      1. Paginate board listing and collect posts within DAYS_WINDOW.
      2. Load analysis cache; only call Claude for posts not yet cached.
      3. Save updated results and append a history entry.
    """
    # Step 1 — scrape listing pages
    def on_page(page_num, count_so_far):
        if progress_callback:
            progress_callback(
                stage="scraping",
                page=page_num,
                posts_found=count_so_far,
                total_posts=None,
                current_title=None,
            )

    posts = scrape_all_posts_in_window(DAYS_WINDOW, page_callback=on_page)

    # Step 2 — load cache; treat Error entries as uncached so they get re-analysed
    cache = load_cache()
    needs_analysis = [
        p for p in posts
        if p.get("url") not in cache
        or cache.get(p.get("url"), {}).get("theme") == "Error"
    ]
    cached_count = len(posts) - len(needs_analysis)

    # Step 3 — Claude analysis for uncached posts
    client = anthropic.Anthropic(api_key=os.environ["JIRA_CUSTOMER_FEEDBACK_OPERATIONS"])
    total_new = len(needs_analysis)

    for i, post in enumerate(needs_analysis):
        if progress_callback:
            progress_callback(
                stage="analysis",
                page=None,
                posts_found=i,
                total_posts=total_new,
                current_title=post["title"],
            )
        try:
            analysis = analyse_title(client, post["title"])
        except Exception as e:
            analysis = {
                "theme": "Error",
                "sentiment": "unknown",
                "severity": "low",
                "summary": f"Analysis failed: {e}",
            }
        analysis["title"] = post["title"]
        analysis["url"] = post.get("url")
        if post.get("url"):
            cache[post["url"]] = analysis
        time.sleep(0.3)

    save_cache(cache)

    # Step 4 — assemble final results (merge cached + newly analysed)
    results: list[dict] = []
    for post in posts:
        url = post.get("url")
        entry = dict(cache.get(url, {})) if url else {}
        entry["title"] = post["title"]
        entry["url"] = url
        entry["post_date"] = post.get("post_date")
        if "theme" not in entry:
            entry.update({"theme": "Unknown", "sentiment": "unknown", "severity": "low", "summary": ""})
        results.append(entry)

    save_results(results)
    append_history(results)

    # Step 5 — generate executive summary from the newly assembled results
    if progress_callback:
        progress_callback(
            stage="summary", page=None, posts_found=None,
            total_posts=None, current_title=None,
        )
    try:
        generate_executive_summary(results, client)
    except Exception:
        pass   # don't let summary errors block the rest

    return results


# ─── Executive Summary ─────────────────────────────────────────────────────────

def _build_summary_prompt(results: list[dict]) -> str:
    good = [r for r in results if r.get("theme") not in ("Error", "Unknown", None)]
    if not good:
        good = results   # fall back to everything

    dates = [r["post_date"] for r in results if r.get("post_date")]
    date_range = (
        f"{min(dates)[:10]} to {max(dates)[:10]}" if dates else "unknown range"
    )

    theme_counts = Counter(r["theme"] for r in good).most_common(12)
    sentiment_counts = Counter(r.get("sentiment", "unknown") for r in good)
    severity_counts  = Counter(r.get("severity",  "unknown") for r in good)
    total_good = len(good)

    high_titles = [
        r["title"] for r in good if r.get("severity") == "high"
    ][:10]
    neg_titles = [
        r["title"] for r in good if r.get("sentiment") == "negative"
    ][:8]

    theme_lines = "\n".join(f"  • {t}: {c} posts" for t, c in theme_counts)
    sent_lines  = "\n".join(
        f"  • {k}: {v} ({v*100//total_good if total_good else 0}%)"
        for k, v in sentiment_counts.most_common()
    )
    sev_lines   = "\n".join(
        f"  • {k}: {v} ({v*100//total_good if total_good else 0}%)"
        for k, v in severity_counts.most_common()
    )
    high_lines  = "\n".join(f"  - {t}" for t in high_titles) or "  (none)"
    neg_lines   = "\n".join(f"  - {t}" for t in neg_titles)  or "  (none)"

    return f"""You are a product analyst reviewing Jira community support posts.

DATA SNAPSHOT
  Period : {date_range}
  Posts analysed: {total_good} (out of {len(results)} total in the 90-day window)

TOP THEMES
{theme_lines}

SENTIMENT
{sent_lines}

SEVERITY
{sev_lines}

SAMPLE HIGH-SEVERITY POST TITLES
{high_lines}

SAMPLE NEGATIVE-SENTIMENT POST TITLES
{neg_lines}

Write a concise executive summary in Markdown (~220 words) using exactly these sections:
### Situation Overview
### Top Issue Themes
### Key Concerns
### Recommended Focus Areas

Be specific, reference actual theme names and counts, and keep a professional tone."""


def generate_executive_summary(
    results: list[dict],
    client: anthropic.Anthropic | None = None,
) -> dict:
    """
    Call Claude to produce an executive summary of the current results.
    Saves and returns {"generated_at": ..., "markdown": ..., "post_count": ...}.
    """
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["JIRA_CUSTOMER_FEEDBACK_OPERATIONS"])

    prompt = _build_summary_prompt(results)
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    markdown = message.content[0].text.strip()

    good_count = len([r for r in results if r.get("theme") not in ("Error", "Unknown", None)])
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "post_count": good_count,
        "total_count": len(results),
        "markdown": markdown,
    }
    save_summary(summary)
    return summary


def load_summary() -> dict | None:
    if not os.path.exists(SUMMARY_FILE):
        return None
    with open(SUMMARY_FILE) as f:
        return json.load(f)


def save_summary(summary: dict) -> None:
    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2)


# ─── Persistence ───────────────────────────────────────────────────────────────

def save_results(results: list[dict]) -> None:
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


def append_history(results: list[dict]) -> None:
    history = load_history()
    sentiment_counts = dict(Counter(r.get("sentiment", "unknown") for r in results))
    severity_counts  = dict(Counter(r.get("severity",  "unknown") for r in results))
    theme_counts     = Counter(r.get("theme", "unknown") for r in results)

    dates = [r["post_date"] for r in results if r.get("post_date")]
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "post_count": len(results),
        "days_window": DAYS_WINDOW,
        "date_range": {
            "from": min(dates) if dates else None,
            "to":   max(dates) if dates else None,
        },
        "sentiment_counts": sentiment_counts,
        "severity_counts":  severity_counts,
        "top_themes":       theme_counts.most_common(10),
        "results":          results,
    }
    history.append(entry)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def load_results() -> list[dict]:
    if not os.path.exists(RESULTS_FILE):
        return []
    with open(RESULTS_FILE) as f:
        return json.load(f)


def load_history() -> list[dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE) as f:
        return json.load(f)


def get_date_range(results: list[dict]) -> tuple[str | None, str | None]:
    """Return (earliest, latest) ISO date strings from a results list."""
    dates = [r["post_date"] for r in results if r.get("post_date")]
    if not dates:
        return None, None
    return min(dates), max(dates)
