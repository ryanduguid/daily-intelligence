import logging
import os
from datetime import datetime

import pytz
import resend

import config

logger = logging.getLogger(__name__)

# Render sections in the same order config defines them (single source of truth).
SECTIONS_ORDER = config.SECTIONS

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<style>
  :root {{
    color-scheme: light dark;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    font-size: 15px;
    line-height: 1.5;
    color: #e0e0e0;
    background-color: #1a1a1a;
    margin: 0;
    padding: 0;
  }}
  @media (prefers-color-scheme: light) {{
    body {{
      color: #1a1a1a;
      background-color: #ffffff;
    }}
    .container {{
      background-color: #ffffff;
    }}
    h1 {{
      color: #1a1a1a;
      border-bottom-color: #e0e0e0;
    }}
    h2 {{
      color: #333333;
      border-left-color: #2563eb;
    }}
    .item {{
      border-bottom-color: #f0f0f0;
    }}
    .item-headline {{
      color: #1a1a1a;
    }}
    .item-body {{
      color: #444444;
    }}
    .item-source a {{
      color: #2563eb;
    }}
    .empty-section {{
      color: #888888;
    }}
  }}
  .container {{
    max-width: 640px;
    margin: 0 auto;
    padding: 20px;
    background-color: #1a1a1a;
  }}
  h1 {{
    font-size: 18px;
    font-weight: 600;
    color: #ffffff;
    border-bottom: 1px solid #333;
    padding-bottom: 8px;
    margin-bottom: 24px;
  }}
  h2 {{
    font-size: 14px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #a0a0a0;
    margin-top: 28px;
    margin-bottom: 12px;
    padding-left: 10px;
    border-left: 3px solid #3b82f6;
  }}
  .item {{
    margin-bottom: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid #2a2a2a;
  }}
  .item:last-child {{
    border-bottom: none;
  }}
  .item-headline {{
    font-weight: 600;
    color: #f0f0f0;
    margin-bottom: 4px;
  }}
  .item-body {{
    color: #b0b0b0;
    margin-bottom: 4px;
  }}
  .item-source {{
    font-size: 12px;
  }}
  .item-source a {{
    color: #3b82f6;
    text-decoration: none;
  }}
  .empty-section {{
    color: #666;
    font-style: italic;
    font-size: 13px;
  }}
</style>
</head>
<body>
<div class="container">
  <h1>{subject}</h1>
  {sections_html}
</div>
</body>
</html>"""


def build_email_html(sections: dict[str, list[dict]], subject: str) -> str:
    """Build the HTML email body from scored sections."""
    sections_html = ""

    for section_name in SECTIONS_ORDER:
        items = sections.get(section_name, [])
        # Sort by score descending
        items.sort(key=lambda x: x.get("score", 0), reverse=True)

        sections_html += f'<h2>{section_name}</h2>\n'

        if not items:
            sections_html += '<p class="empty-section">Nothing material today.</p>\n'
            continue

        for item in items:
            headline = item.get("headline", item.get("title", ""))
            body = item.get("body", "")
            url = item.get("url", "#")
            source = item.get("source", "")

            sections_html += (
                '<div class="item">\n'
                f'  <div class="item-headline"><strong>{_escape(headline)}</strong></div>\n'
                f'  <div class="item-body">{_escape(body)}</div>\n'
                f'  <div class="item-source"><a href="{_escape(url)}">{_escape(source)}</a></div>\n'
                '</div>\n'
            )

    return HTML_TEMPLATE.format(subject=_escape(subject), sections_html=sections_html)


def _escape(text: str) -> str:
    """Basic HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def send_digest(sections: dict[str, list[dict]]) -> None:
    """Build and send the digest email via Resend."""
    resend.api_key = os.environ["RESEND_API_KEY"]

    tz = pytz.timezone(config.TIMEZONE)
    now = datetime.now(tz)
    subject = f"{config.APP_NAME}. {now.strftime('%A %d %B %Y')}"

    html = build_email_html(sections, subject)

    params = {
        "from": config.FROM_EMAIL,
        "to": config.RECIPIENTS,
        "subject": subject,
        "html": html,
    }

    try:
        response = resend.Emails.send(params)
        logger.info(f"Email sent via Resend: {response}")
    except Exception as e:
        logger.error(f"Failed to send digest email: {e}")
        raise


def send_error_alert(error_msg: str) -> None:
    """Send a plain text failure alert to the alert recipients."""
    try:
        resend.api_key = os.environ["RESEND_API_KEY"]

        tz = pytz.timezone(config.TIMEZONE)
        now = datetime.now(tz)

        params = {
            "from": config.FROM_EMAIL,
            "to": config.ALERT_RECIPIENTS,
            "subject": f"{config.APP_NAME} FAILED - {now.strftime('%Y-%m-%d %H:%M')}",
            "text": error_msg,
        }

        resend.Emails.send(params)
        logger.info(f"Error alert sent to {', '.join(config.ALERT_RECIPIENTS)}")
    except Exception as e:
        logger.error(f"Failed to send error alert: {e}")
