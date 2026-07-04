import logging
import os
import json
import time

import anthropic

import config

logger = logging.getLogger(__name__)

SECTIONS = config.SECTIONS
CATCH_ALL_SECTION = SECTIONS[-1]  # unknown sections from the model land here


def score_and_summarise(
    feed_items: list, search_results: list[dict]
) -> tuple[dict[str, list[dict]], dict]:
    """Score candidates via Claude and assign to sections.

    Returns (sections_dict, stats_dict) where stats tracks batch outcomes.
    """
    logger.info("Scoring and summarising items via Claude...")

    candidates = []
    for i, item in enumerate(feed_items):
        candidates.append({
            "id": f"feed_{i}",
            "title": item.title,
            "url": item.url,
            "summary": item.summary[:300],
            "source": item.source,
            "category": item.category,
        })
    for i, item in enumerate(search_results):
        candidates.append({
            "id": f"search_{i}",
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "summary": item.get("summary", ""),
            "source": f"Web search: {item.get('query', '')}",
            "category": "Web Search",
        })

    stats = {"candidates": len(candidates), "strict_batches_ok": 0,
             "strict_batches_failed": 0, "rescue_batches_ok": 0,
             "rescue_batches_failed": 0, "items_scored": 0, "api_error": None}

    if not candidates:
        logger.warning("No candidates to score")
        return {s: [] for s in SECTIONS}, stats

    logger.info(f"  Total candidates for scoring: {len(candidates)}")

    errors: list[str] = []
    sections, ok, failed = _run_scoring_pass(candidates, strict=True, error_sink=errors)
    stats["strict_batches_ok"] = ok
    stats["strict_batches_failed"] = failed

    total_items = sum(len(items) for items in sections.values())
    logger.info(f"  Strict pass: {total_items} items from {ok} ok / {failed} failed batches")

    # Only run rescue if strict returned 0 because the model filtered everything,
    # not because all API calls failed
    if total_items == 0 and len(candidates) > 0 and ok > 0:
        logger.warning("Strict scoring returned 0 items with working API — running rescue pass")
        time.sleep(30)
        sections, ok, failed = _run_scoring_pass(candidates, strict=False, error_sink=errors)
        stats["rescue_batches_ok"] = ok
        stats["rescue_batches_failed"] = failed
        total_items = sum(len(items) for items in sections.values())
        logger.info(f"  Rescue pass: {total_items} items from {ok} ok / {failed} failed batches")
    elif total_items == 0 and ok == 0:
        logger.error("All scoring batches failed — skipping rescue pass (API issue, not scoring issue)")

    stats["items_scored"] = total_items
    if errors:
        stats["api_error"] = errors[0]
    for section, items in sections.items():
        logger.info(f"  {section}: {len(items)} items")

    return sections, stats


def _run_scoring_pass(
    candidates: list[dict], strict: bool, error_sink: list[str] | None = None
) -> tuple[dict[str, list[dict]], int, int]:
    """Run a single scoring pass. Returns (sections, batches_ok, batches_failed)."""
    chunk_size = 40
    all_scored = []
    batches_ok = 0
    batches_failed = 0
    delay = 30

    for i in range(0, len(candidates), chunk_size):
        chunk = candidates[i:i + chunk_size]
        batch_num = i // chunk_size + 1
        logger.info(f"  Scoring batch {batch_num} ({len(chunk)} items, strict={strict})...")
        scored = _score_batch(chunk, strict=strict, error_sink=error_sink)
        if scored is None:
            batches_failed += 1
            delay = min(delay * 2, 120)
        else:
            all_scored.extend(scored)
            batches_ok += 1
        if i + chunk_size < len(candidates):
            logger.info(f"  Waiting {delay}s before next batch...")
            time.sleep(delay)

    sections: dict[str, list[dict]] = {s: [] for s in SECTIONS}
    for item in all_scored:
        section = item.get("section", CATCH_ALL_SECTION)
        if section not in sections:
            logger.warning(f"  Unknown section '{section}' from model — moving to '{CATCH_ALL_SECTION}'")
            section = CATCH_ALL_SECTION
        sections[section].append(item)

    return sections, batches_ok, batches_failed


def _build_scoring_prompt(candidates_text: str, strict: bool = True) -> str:
    """Build the scoring prompt from the user's CONTEXT, with strict or relaxed criteria."""
    extra_rules = getattr(config, "EXTRA_SCORING_RULES", "") or ""
    if extra_rules:
        extra_rules = f"\n{extra_rules.strip()}"

    if strict:
        scoring_criteria = f"""Score each 1-3 based on relevance to the reader described above:
- Score 1: SKIP. Tangentially related, generic hype, dev tips not specific to the reader's domain, or version bumps with no feature change that affects them.
- Score 2: Relevant to one of the reader's priorities but no immediate action needed. Worth a quick read for someone tracking the landscape.
- Score 3: Materially moves one of the reader's stated priorities. Something they should read and potentially act on THIS WEEK.

RULES:
- A good digest has 6-12 total items. Quality over quantity, but an empty digest is worse than a slightly generous one.
- "Why it matters" must be SPECIFIC and tie back to one of the reader's priorities. If you have to stretch, it's Score 1.
- Version bumps of SDKs/libraries are Score 1 UNLESS they introduce something the reader would directly act on (breaking change, security vulnerability, major new capability).
- Max 3 items per section. If more qualify, keep the top ones.
- You MUST include at least a few Score 2 items. An empty output is not acceptable if there are any remotely relevant candidates.{extra_rules}"""
    else:
        scoring_criteria = f"""Score each 1-3 based on relevance to the reader described above:
- Score 1: SKIP. Completely unrelated to the reader's domain.
- Score 2: Related to the reader's domain. Worth a brief mention.
- Score 3: Directly relevant to the reader this week.

RULES:
- Be GENEROUS. The previous scoring pass found nothing relevant, which means the bar was too high.
- Include the 3-6 BEST items from these candidates. There is almost always something worth including.
- Max 3 items per section.{extra_rules}"""

    return f"""{config.CONTEXT}

Below are candidate news items. {scoring_criteria}

For items scoring 2 or 3:
1. Assign to exactly one section: {json.dumps(SECTIONS)}
2. Write a headline in technical founder voice (not journalist clickbait)
3. Write exactly two sentences: what happened, then why it specifically matters to the reader this week.

Return ONLY a valid JSON array. Each element:
{{"id": "...", "score": 2|3, "section": "...", "headline": "...", "body": "...", "url": "...", "source": "..."}}

Omit ALL score 1 items. Do not include them in the output.

CANDIDATES:
{candidates_text}"""


def _classify_api_error(e: Exception) -> str | None:
    """Return a human-readable cause for billing/auth failures, else None."""
    msg = str(e).lower()
    if "credit balance is too low" in msg or "plans & billing" in msg:
        return "Anthropic API rejected the request: credit balance too low. Top up at console.anthropic.com → Plans & Billing."
    if isinstance(e, anthropic.AuthenticationError) or "authentication" in msg or "invalid x-api-key" in msg:
        return "Anthropic API rejected the request: authentication failed (check ANTHROPIC_API_KEY)."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "Anthropic API rejected the request: permission denied (key may lack access to this model)."
    return None


def _score_batch(
    candidates: list[dict], strict: bool = True, error_sink: list[str] | None = None
) -> list[dict] | None:
    """Score a batch via Claude. Returns list on success, None on API/parse failure."""
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=5,
    )

    candidates_text = ""
    for c in candidates:
        candidates_text += (
            f"ID: {c['id']}\n"
            f"Title: {c['title']}\n"
            f"URL: {c['url']}\n"
            f"Summary: {c['summary']}\n"
            f"Source: {c['source']}\n"
            f"Category: {c['category']}\n"
            f"---\n"
        )

    prompt = _build_scoring_prompt(candidates_text, strict=strict)
    logger.info(f"  Prompt length: ~{len(prompt)} chars, strict={strict}")

    try:
        response = client.messages.create(
            model=config.SCORING_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        logger.info(f"  Raw response length: {len(text)} chars")
        if len(text) < 200:
            logger.info(f"  Raw response: {text}")

        text = text.strip()
        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1 or end == 0:
            logger.warning(f"No JSON array found in scoring response. First 500 chars: {text[:500]}")
            return []

        scored = json.loads(text[start:end])
        logger.info(f"  Scored batch: {len(scored)} items passed filter")
        return scored

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed: {e}. First 500 chars of text: {text[:500]}")
        return None
    except Exception as e:
        logger.error(f"Scoring API call failed: {type(e).__name__}: {e}")
        cause = _classify_api_error(e)
        if cause and error_sink is not None and cause not in error_sink:
            error_sink.append(cause)
        return None
