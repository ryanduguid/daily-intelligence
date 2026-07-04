"""Daily intelligence digest.

Runs as a long-lived worker (e.g. on Railway). Uses APScheduler to trigger
once a day at the hour/timezone set in config.py, handling DST automatically.

Run immediately (for testing): `python main.py --now` or env RUN_NOW=1.
"""

import base64
import os
import sys

# ── Config bootstrap ────────────────────────────────────────────────────────
# Hosted deploys can inject a private config.py via env var instead of a file:
#   DIGEST_CONFIG_B64 = base64 of your config.py
# Written only if config.py doesn't already exist. Must happen before any
# `import config` below.
if not os.path.exists("config.py") and os.environ.get("DIGEST_CONFIG_B64"):
    with open("config.py", "wb") as f:
        f.write(base64.b64decode(os.environ["DIGEST_CONFIG_B64"]))

if not os.path.exists("config.py"):
    sys.stderr.write(
        "No config.py found. Copy config.example.py to config.py and fill in "
        "your profile (or set DIGEST_CONFIG_B64).\n"
    )
    sys.exit(1)

import asyncio
import logging
import traceback
import uuid
from datetime import datetime

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from feed_fetcher import fetch_all_feeds
from web_searcher import run_web_searches
from scorer import score_and_summarise
from dedup import is_duplicate_batch, mark_sent, purge_old
from email_builder import send_digest, send_error_alert

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("digest")

TZ = pytz.timezone(config.TIMEZONE)


# ── Main digest pipeline ────────────────────────────────────────────────────

async def run_digest():
    """Execute the full digest pipeline."""
    run_id = uuid.uuid4().hex[:8]
    start = datetime.now(TZ)
    logger.info(f"=== Digest run {run_id} started at {start.strftime('%Y-%m-%d %H:%M %Z')} ===")

    # PASS 1: Fetch all RSS/Atom feeds
    feed_items = await fetch_all_feeds()

    # Deduplicate feed items (batch lookup)
    feed_urls = [item.url for item in feed_items]
    seen_urls = is_duplicate_batch(feed_urls)
    unique_feed_items = [item for item in feed_items if item.url not in seen_urls]
    logger.info(f"After dedup: {len(unique_feed_items)}/{len(feed_items)} feed items")

    # PASS 2: Web searches
    search_results = await run_web_searches()

    # Deduplicate search results (batch lookup)
    search_urls = [item.get("url", "") for item in search_results if item.get("url")]
    seen_search_urls = is_duplicate_batch(search_urls)
    unique_search_results = [
        item for item in search_results
        if item.get("url") and item["url"] not in seen_search_urls
    ]
    logger.info(f"After dedup: {len(unique_search_results)}/{len(search_results)} search results")

    # Cooldown after web searches before scoring (rate-limit hygiene)
    cooldown = getattr(config, "SCORING_COOLDOWN_SECONDS", 60)
    logger.info(f"Waiting {cooldown}s cooldown before scoring...")
    await asyncio.sleep(cooldown)

    # Score and summarise
    sections, scorer_stats = score_and_summarise(unique_feed_items, unique_search_results)

    # Collect all URLs that made it into the digest
    sent_urls = []
    for items in sections.values():
        for item in items:
            url = item.get("url", "")
            if url:
                sent_urls.append(url)

    # Log structured run summary
    logger.info(
        f"[{run_id}] feeds={len(unique_feed_items)}, searches={len(unique_search_results)}, "
        f"scored={scorer_stats['items_scored']}, "
        f"strict_ok={scorer_stats['strict_batches_ok']}, "
        f"strict_fail={scorer_stats['strict_batches_failed']}, "
        f"rescue_ok={scorer_stats['rescue_batches_ok']}, "
        f"rescue_fail={scorer_stats['rescue_batches_failed']}"
    )

    if not sent_urls:
        api_error = scorer_stats.get("api_error")
        if api_error:
            cause = f"CAUSE: {api_error}"
        elif scorer_stats["strict_batches_ok"] == 0:
            cause = "CAUSE: every scoring batch failed (API/network issue, not relevance)."
        else:
            cause = "CAUSE: the model scored every candidate as not relevant."
        detail = (
            f"Digest skipped at {datetime.now(TZ).isoformat()} (run {run_id}).\n"
            f"{cause}\n\n"
            f"Stats: {len(unique_feed_items)} feed + "
            f"{len(unique_search_results)} search candidates, "
            f"batches {scorer_stats['strict_batches_ok']} ok / "
            f"{scorer_stats['strict_batches_failed']} failed."
        )
        logger.error(detail)
        send_error_alert(detail)
        return

    send_digest(sections)
    mark_sent(sent_urls)
    purge_old()

    elapsed = (datetime.now(TZ) - start).total_seconds()
    logger.info(f"=== Digest run {run_id} complete in {elapsed:.1f}s, {len(sent_urls)} items sent ===")


def run_digest_sync():
    """Synchronous entry point for the scheduler."""
    try:
        asyncio.run(run_digest())
    except Exception as e:
        error_msg = (
            f"{config.APP_NAME} failed at {datetime.now(TZ).isoformat()}\n\n"
            f"Error: {e}\n\n"
            f"Full traceback:\n{traceback.format_exc()}"
        )
        logger.error(error_msg)
        try:
            send_error_alert(error_msg)
        except Exception as alert_err:
            logger.error(f"Could not send error alert: {alert_err}")


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    # Validate required environment variables
    required_vars = ["ANTHROPIC_API_KEY", "RESEND_API_KEY"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    logger.info(f"{config.APP_NAME} starting...")
    logger.info(f"Current time in {config.TIMEZONE}: {datetime.now(TZ).strftime('%Y-%m-%d %H:%M %Z')}")

    # Check for immediate run flag (useful for testing)
    if "--now" in sys.argv or os.environ.get("RUN_NOW") == "1":
        logger.info("Running digest immediately (--now flag)")
        run_digest_sync()
        return

    # Schedule daily at the configured local time
    scheduler = BlockingScheduler()
    trigger = CronTrigger(
        hour=config.SCHEDULE_HOUR,
        minute=config.SCHEDULE_MINUTE,
        timezone=TZ,
    )
    scheduler.add_job(run_digest_sync, trigger, id="daily_digest", name="Daily Intelligence Digest")

    next_run = trigger.get_next_fire_time(None, datetime.now(TZ))
    logger.info(f"Next digest scheduled for: {next_run}")
    logger.info("Scheduler running.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
