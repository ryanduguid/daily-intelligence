# Daily Intelligence — a personal news brief for accountants

**Too much is changing to follow it all: tax rules, e-invoicing mandates, MTD
deadlines, AI tools, regulator guidance.** This is a small open-source worker
that reads the news *for you* and sends you one short email a day with only
the items that matter to **your** practice — and, for each one, *why it
matters to you*.

You describe yourself once, in plain English:

```python
PROFILE = {
    "who": "Sole practitioner in the UK with ~80 small business and landlord clients.",
    "jurisdictions": ["UK", "EU"],
    "topics": ["Making Tax Digital", "VAT & e-invoicing", "AI in accounting practice"],
    "watch_for": "HMRC deadline changes affecting small landlords, and whether any AI tool is actually safe to use on client data",
}
```

Every morning you get an email like:

> **MAKING TAX DIGITAL**
> **HMRC confirms MTD IT software list update** — HMRC added three products to
> the recognised list and tightened the bridging-software criteria. *If your
> landlord clients use spreadsheets, check their bridging tool is still listed
> before the next quarterly update.*

Built by [OpenAccountants](https://www.openaccountants.com), a library of tax
skills with sources and published review status for AI.

## How it works

```
RSS/Atom feeds (your jurisdictions + topics)      Claude web searches (your queries)
                    └──────────────┬──────────────────────┘
                                   ▼
                 Claude scores every candidate against YOUR profile
                 (skip / worth a read / act on this — with "why it matters to you")
                                   ▼
                 One HTML email, sectioned by your topics (via Resend)
                                   ▼
                 SQLite remembers what you've seen (no repeats for 30 days)
```

One run costs a few cents of Claude API usage. Your profile never leaves your
own deployment: `config.py` is gitignored, and the only services called are
Anthropic (scoring/search) and Resend (sending). **No client data is involved
anywhere — this reads public news only.**

## Setup (15 minutes)

Not technical? Paste this README into Claude or ChatGPT and say *"help me set
this up"* — the steps below are exactly what it will walk you through.

### 1. Get your two API keys
- [console.anthropic.com](https://console.anthropic.com) → API key + a few
  dollars of credit (a daily digest costs roughly **$3–10/month** depending on
  how many feeds/searches you configure).
- [resend.com](https://resend.com) → API key, and verify a sending domain or
  address. The free tier is plenty for a personal digest.

### 2. Create your profile
```bash
git clone https://github.com/openaccountants/daily-intelligence.git
cd daily-intelligence
cp config.example.py config.py
# edit config.py — fill in PROFILE, timezone, and send hour
cp .env.example .env   # fill in your keys and email addresses
```

### 3. Test it locally
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
set -a; source .env; set +a
.venv/bin/python main.py --now      # runs once and emails you
```

### 4. Deploy it (Railway)
The worker just needs to stay running; [Railway](https://railway.com) is the
path of least resistance (~$5/month):

1. Push your clone to a **private** GitHub repo (your `config.py` stays out of
   git either way — see the alternative below) and create a Railway service
   from it. The repo includes `.python-version` + `mise.toml` so the build
   works out of the box; the `Procfile` starts `python main.py`.
2. Set the variables from `.env.example` in the Railway service.
3. Add a volume mounted at `/data` and set `SQLITE_PATH=/data/digest.db` so
   the "already sent" memory survives redeploys.
4. **Keeping your profile out of git entirely:** set `DIGEST_CONFIG_B64` to
   `base64 < config.py` — the worker writes `config.py` from it at boot, so
   you can even deploy straight from this public repo with zero changes.

That's it. It sends daily at the hour/timezone in your config; if a run fails,
you get an alert email that says *why* (including "your Anthropic credit ran
out", the most common one).

## Customising

- **Jurisdictions & topics** come from starter packs in [`presets.py`](presets.py)
  (currently UK, US, EU, MT + eight topics). Anything not in a pack still
  works — an unknown topic becomes a section plus a web search automatically.
- **Power users** can override anything the presets produce — `CONTEXT`,
  `SECTIONS`, `SEARCH_QUERIES`, `FEEDS` — at the bottom of `config.py`.
- **Models**: defaults to Claude Sonnet for both search and scoring; switch
  `SCORING_MODEL` to Haiku in `config.py` to cut cost.

## Contributing: add your jurisdiction

The most valuable contribution is a feed pack for your country: a handful of
**live** RSS feeds for your profession's press and your tax authority, plus
one or two search queries. Add them to `presets.py` and open a PR. Please
check feeds actually return recent items before submitting — dead feeds are
silently useless.

## License

[AGPL-3.0](LICENSE) © [OpenAccountants](https://www.openaccountants.com).
Run it, modify it, share it — if you offer a modified version as a service,
share your changes back.
