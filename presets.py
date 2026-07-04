"""Starter packs: feeds and search queries per jurisdiction and topic.

`assemble(PROFILE)` turns a simple accountant profile into the four things the
engine needs (CONTEXT, SECTIONS, SEARCH_QUERIES, FEEDS) so nobody has to write
prompts by hand. Power users can still override any of the four in config.py
after calling assemble().

Contributions welcome: add your jurisdiction's feeds and queries via PR —
that's how coverage grows. Please only add feeds you've checked are alive
(return items with recent dates).
"""

# ── Jurisdiction packs ───────────────────────────────────────────────────
# Feeds about tax/accounting news in a jurisdiction, keyed by ISO-ish code.

JURISDICTION_FEEDS: dict[str, dict[str, list[str]]] = {
    "UK": {
        "UK profession & tax": [
            "https://www.accountingweb.co.uk/rss.xml",
            "https://www.accountancyage.com/feed",
        ],
    },
    "US": {
        "US profession & tax": [
            "https://www.cpapracticeadvisor.com/rss",
            "https://www.cpajournal.com/feed/",
            "https://www.accountingweb.com/rss.xml",
            "https://taxfoundation.org/feed/",
        ],
    },
    "EU": {
        "EU regulation & tax": [
            "https://www.esma.europa.eu/rss.xml",
            "https://www.eba.europa.eu/rss.xml",
            "https://www.internationalaccountingbulletin.com/feed/",
        ],
    },
    "MT": {
        "Malta regulation": [
            "https://mfsa.mt/feed/",
        ],
    },
    # Always included regardless of jurisdiction choice.
    "GLOBAL": {
        "Global profession": [
            "https://tax.thomsonreuters.com/blog/feed/",
            "https://www.internationalaccountingbulletin.com/feed/",
        ],
    },
}

JURISDICTION_QUERIES: dict[str, list[str]] = {
    "UK": ["HMRC OR Making Tax Digital OR UK tax change announcement"],
    "US": ["IRS guidance OR US tax law change announcement"],
    "EU": ["EU VAT OR ViDA OR e-invoicing directive OR EU tax regulation"],
    "MT": ["Malta tax OR MFSA OR Malta FIAU regulation"],
    "GLOBAL": [],
}

# Fallback HTML pages for feeds that often block or fail.
JURISDICTION_FALLBACKS: dict[str, str] = {
    "https://mfsa.mt/feed/": "https://mfsa.mt/news/",
}

# ── Topic packs ──────────────────────────────────────────────────────────
# Each topic becomes a section of the digest email, and brings its own feeds
# and web-search queries.

TOPIC_PACKS: dict[str, dict] = {
    "AI in accounting practice": {
        "feeds": [
            "https://hnrss.org/newest?q=AI+accounting",
            "https://hnrss.org/newest?q=AI+tax",
            "https://www.reddit.com/r/accounting/top.rss?t=week",
        ],
        "queries": [
            "AI tools for accountants client data OR AI accounting practice adoption",
            "accountant AI confidentiality OR professional body AI guidance",
        ],
    },
    "VAT & e-invoicing": {
        "feeds": [
            "https://hnrss.org/newest?q=e-invoicing+OR+Making+Tax+Digital",
        ],
        "queries": [
            "e-invoicing mandate OR VAT digital reporting change",
        ],
    },
    "Making Tax Digital": {
        "feeds": [],
        "queries": [
            "Making Tax Digital income tax deadline OR HMRC MTD software",
        ],
    },
    "Payroll": {
        "feeds": [],
        "queries": [
            "payroll rules change OR payroll compliance update",
        ],
    },
    "Audit": {
        "feeds": [],
        "queries": [
            "audit standard change OR audit regulator enforcement",
        ],
    },
    "Crypto tax": {
        "feeds": [],
        "queries": [
            "crypto tax rules OR digital asset reporting requirement",
        ],
    },
    "Practice management & tech": {
        "feeds": [
            "https://www.reddit.com/r/accounting/top.rss?t=week",
        ],
        "queries": [
            "accounting practice software launch OR accounting firm technology",
        ],
    },
    "AI & tech news (general)": {
        "feeds": [
            "https://simonwillison.net/atom/everything/",
            "https://www.theregister.com/headlines.atom",
        ],
        "queries": [
            "major AI model release OR AI regulation this week",
        ],
    },
}

CATCH_ALL_SECTION = "Worth knowing"


def assemble(profile: dict) -> tuple[str, list[str], list[str], dict[str, list[str]], dict[str, str]]:
    """Build (CONTEXT, SECTIONS, SEARCH_QUERIES, FEEDS, FALLBACK_PAGES) from a profile.

    profile keys:
      who           str  — who you are / your practice, in a sentence or two
      jurisdictions list — e.g. ["UK", "EU"]; unknown codes are ignored
      topics        list — from TOPIC_PACKS keys; unknown topics still become
                            sections + a search query, just with no preset feeds
      watch_for     str  — free text: anything specific to watch for you
    """
    who = (profile.get("who") or "an accountant").strip()
    jurisdictions = [j.upper() for j in profile.get("jurisdictions", [])]
    topics = list(profile.get("topics", [])) or ["AI in accounting practice"]
    watch_for = (profile.get("watch_for") or "").strip()

    # Sections: one per topic, catch-all last.
    sections = topics + [CATCH_ALL_SECTION]

    # Feeds: jurisdiction packs (+ GLOBAL always) then topic packs, deduped.
    feeds: dict[str, list[str]] = {}
    seen_urls: set[str] = set()

    def _add(group: str, urls: list[str]) -> None:
        fresh = [u for u in urls if u not in seen_urls]
        if not fresh:
            return
        feeds.setdefault(group, []).extend(fresh)
        seen_urls.update(fresh)

    for code in [*jurisdictions, "GLOBAL"]:
        for group, urls in JURISDICTION_FEEDS.get(code, {}).items():
            _add(group, urls)

    for topic in topics:
        pack = TOPIC_PACKS.get(topic)
        if pack:
            _add(topic, pack["feeds"])

    # Queries: jurisdiction + topic presets, plus one derived from watch_for.
    queries: list[str] = []
    for code in [*jurisdictions, "GLOBAL"]:
        queries.extend(JURISDICTION_QUERIES.get(code, []))
    for topic in topics:
        pack = TOPIC_PACKS.get(topic)
        if pack:
            queries.extend(pack["queries"])
        else:
            queries.append(f"{topic} news for accountants")
    if watch_for:
        queries.append(watch_for)
    # de-dup preserving order
    queries = list(dict.fromkeys(queries))

    fallbacks = {k: v for k, v in JURISDICTION_FALLBACKS.items() if k in seen_urls}

    # Context: the brief the model scores every candidate against.
    jur_line = ", ".join(jurisdictions) if jurisdictions else "no specific jurisdiction"
    topics_lines = "\n".join(f"{i+1}. {t}" for i, t in enumerate(topics))
    watch_block = (
        f"\n\nSPECIFICALLY WATCH FOR (the reader asked for this in their own words):\n{watch_for}"
        if watch_for else ""
    )

    context = f"""You are compiling a daily intelligence digest for this reader:

READER: {who}
JURISDICTIONS THEY PRACTISE IN: {jur_line}

THEIR PRIORITY TOPICS (weight every item by how much it moves one of these):
{topics_lines}{watch_block}

Prefer items that change what the reader should DO in their practice (a
deadline, a rule change, a tool decision, a client conversation) over items
that are merely interesting. News from their jurisdictions outranks news from
elsewhere unless the item is globally significant. Be specific about WHY an
item matters to this reader — if you have to stretch, it is not relevant."""

    return context, sections, queries, feeds, fallbacks
