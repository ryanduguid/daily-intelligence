import asyncio
import logging
import os
from datetime import datetime

import anthropic

import config

logger = logging.getLogger(__name__)


def _build_search_prompt(query: str, date_str: str) -> str:
    return (
        f'Search the web for: "{query}" {date_str}\n\n'
        "Return ONLY results from the last 48 hours. For each result, provide:\n"
        "- Title\n"
        "- URL\n"
        "- One sentence summary of what happened\n\n"
        "If there are no relevant recent results, respond with exactly: NO_RESULTS\n"
        "Format each result as:\n"
        "TITLE: ...\n"
        "URL: ...\n"
        "SUMMARY: ...\n"
        "---"
    )


def _parse_search_results(text: str, query: str) -> list[dict]:
    """Parse structured search results from Claude's response."""
    results = []
    current = {}

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("TITLE:"):
            if current.get("title"):
                results.append(current)
            current = {"title": line[6:].strip(), "query": query}
        elif line.startswith("URL:"):
            current["url"] = line[4:].strip()
        elif line.startswith("SUMMARY:"):
            current["summary"] = line[8:].strip()
        elif line == "---":
            if current.get("title"):
                results.append(current)
            current = {}

    if current.get("title"):
        results.append(current)

    return results


def _run_single_search(client: anthropic.Anthropic, query: str, date_str: str) -> list[dict]:
    """Run a single web search via Claude with the web search tool."""
    try:
        response = client.messages.create(
            model=config.SEARCH_MODEL,
            max_tokens=1024,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3,
            }],
            messages=[{
                "role": "user",
                "content": _build_search_prompt(query, date_str),
            }],
        )

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        if "NO_RESULTS" in text:
            return []

        return _parse_search_results(text, query)

    except Exception as e:
        logger.warning(f"Web search failed for '{query}': {e}")
        return []


async def run_web_searches() -> list[dict]:
    """Run web searches sequentially with delays to respect rate limits."""
    logger.info("PASS 2: Running web searches via Claude...")
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=5,
    )

    queries = config.SEARCH_QUERIES
    all_results = []
    for i, query in enumerate(queries):
        logger.info(f"  Search {i+1}/{len(queries)}: {query}")
        results = await asyncio.to_thread(_run_single_search, client, query, date_str)
        all_results.extend(results)
        if i < len(queries) - 1:
            await asyncio.sleep(config.SEARCH_DELAY_SECONDS)

    logger.info(f"PASS 2 complete: {len(all_results)} results from web search")
    return all_results
