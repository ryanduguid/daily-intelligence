"""Your digest configuration — copy this file to `config.py` and fill in YOUR profile.

    cp config.example.py config.py

`config.py` is the only file you edit, and it is gitignored so your interests
stay private. Describe yourself in PROFILE below in plain English — no prompt
engineering needed. (Tip: paste this file into Claude or ChatGPT and say
"fill this in for me, I'm a <your practice>" — it works great.)
"""

import os

from presets import assemble, TOPIC_PACKS, JURISDICTION_FEEDS

# ── 1. WHO YOU ARE ───────────────────────────────────────────────────────
PROFILE = {
    # Your practice, in a sentence or two. Be concrete — it sharpens scoring.
    "who": (
        "Sole practitioner accountant in the UK with ~80 small business and "
        "landlord clients. Interested in practical tools, deadlines, and "
        "anything that changes what I must tell clients."
    ),

    # Where you practise. Available presets: see JURISDICTION_FEEDS in presets.py
    # (currently UK, US, EU, MT — contribute yours!). Unknown codes are ignored.
    "jurisdictions": ["UK", "EU"],

    # What you care about. Each topic becomes a section of your daily email.
    # Available presets: see TOPIC_PACKS in presets.py. You can also invent
    # your own topic — it still becomes a section + a web search.
    "topics": [
        "Making Tax Digital",
        "VAT & e-invoicing",
        "AI in accounting practice",
        "Practice management & tech",
    ],

    # Free text: anything specific you want watched, in your own words.
    "watch_for": (
        "HMRC deadline changes affecting small landlords, and whether any AI "
        "tool is actually safe to use on client data"
    ),
}

# Assemble the engine inputs from your profile.
CONTEXT, SECTIONS, SEARCH_QUERIES, FEEDS, FALLBACK_PAGES = assemble(PROFILE)

# ── 2. EMAIL DELIVERY (via Resend) ───────────────────────────────────────
# Prefer env vars so addresses aren't written into files.
APP_NAME = "Your Daily Brief"        # email subject prefix — make it yours
FROM_EMAIL = os.environ.get("FROM_EMAIL", "digest@example.com")
RECIPIENTS = [
    e.strip() for e in os.environ.get("DIGEST_RECIPIENTS", "you@example.com").split(",") if e.strip()
]
ALERT_RECIPIENTS = [
    e.strip() for e in os.environ.get("ALERT_RECIPIENTS", ",".join(RECIPIENTS)).split(",") if e.strip()
]

# ── 3. SCHEDULE ──────────────────────────────────────────────────────────
TIMEZONE = "Europe/London"           # IANA timezone
SCHEDULE_HOUR = 7                    # local hour for the daily send (24h)
SCHEDULE_MINUTE = 0

# ── 4. MODELS ────────────────────────────────────────────────────────────
SEARCH_MODEL = "claude-sonnet-4-6"   # runs the web searches
SCORING_MODEL = "claude-sonnet-4-6"  # scores & summarises candidates

# ── 5. POWER-USER OVERRIDES (all optional) ───────────────────────────────
# Everything assemble() produced can be overridden or extended right here.

# Extra scoring rules appended to the prompt, e.g.:
# EXTRA_SCORING_RULES = "Over-report anything about MTD — include even indirect signals."
EXTRA_SCORING_RULES = ""

# Add your own feeds to a section:
# FEEDS["Making Tax Digital"] = FEEDS.get("Making Tax Digital", []) + [
#     "https://example.com/feed.xml",
# ]

# Or replace the assembled values wholesale:
# CONTEXT = "..."; SECTIONS = [...]; SEARCH_QUERIES = [...]; FEEDS = {...}

# Pages with no feed at all, scraped for headlines: [(url, section), ...]
EXTRA_SCRAPE_URLS = []

# ── 6. TUNING ────────────────────────────────────────────────────────────
FEED_LOOKBACK_HOURS = 72        # ignore feed items older than this
SEARCH_DELAY_SECONDS = 60       # pause between web searches (rate limits)
SCORING_COOLDOWN_SECONDS = 60   # pause after searches, before scoring
