"""Email the newly published items through Azure Communication Services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape
from typing import Callable

from .config import Settings
from .storage import read_json, write_json

log = logging.getLogger(__name__)

STATUS_LABELS = {
    "ga": "Generally available",
    "preview": "Preview",
    "retirement": "Retirement",
    "announcement": "Announcement",
    "guidance": "Guidance",
}
ACTION_LABELS = {
    "adopt": "Adopt",
    "evaluate": "Evaluate",
    "plan-migration": "Plan migration",
    "be-aware": "Be aware",
}


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


SendEmail = Callable[[Email], None]


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _label(item: dict) -> str:
    status = STATUS_LABELS.get(item["status"], item["status"])
    action = ACTION_LABELS.get(item["recommended_action"], item["recommended_action"])
    return f"{status} · {action}"


def build_email(items: list[dict], settings: Settings) -> Email:
    """One digest for all items. Every field is escaped: the briefs are model output
    written from untrusted feed content."""
    if len(items) == 1:
        subject = f"Azure news: {_one_line(items[0]['headline'])}"
    else:
        subject = f"Azure news: {len(items)} new updates"

    text_parts = []
    html_parts = []
    for item in items:
        headline = _one_line(item["headline"])
        impact = item["architecture_impact"]
        lines = [headline, _label(item), "", item["summary"]]
        if impact:
            lines.append(f"Architecture impact: {impact}")
        lines.append(f"Source ({item['source_name']}): {item['link']}")
        text_parts.append("\n".join(lines))
        html_parts.append(
            '<div style="margin:0 0 28px">'
            f'<h2 style="font-size:17px;margin:0 0 4px">{escape(headline)}</h2>'
            f'<p style="color:#555;font-size:13px;margin:0 0 8px">{escape(_label(item))}</p>'
            f'<p style="margin:0 0 8px">{escape(item["summary"])}</p>'
            + (
                f'<p style="margin:0 0 8px"><strong>Architecture impact:</strong> {escape(impact)}</p>'
                if impact
                else ""
            )
            + f'<p style="margin:0"><a href="{escape(item["link"])}">{escape(item["source_name"])}</a></p>'
            "</div>"
        )

    footer_text = "Summaries are generated and can be wrong; check the source before acting."
    footer_html = escape(footer_text)
    if settings.site_url:
        footer_text += f"\nAll items: {settings.site_url}"
        footer_html += f' <a href="{escape(settings.site_url)}">All items</a>'

    text = "\n\n---\n\n".join(text_parts) + f"\n\n---\n\n{footer_text}\n"
    html = (
        '<div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;'
        'line-height:1.45;color:#1b1b1b;max-width:640px">'
        + "".join(html_parts)
        + f'<p style="color:#555;font-size:13px;border-top:1px solid #ddd;padding-top:12px">{footer_html}</p>'
        "</div>"
    )
    return Email(subject=subject, text=text, html=html)


def acs_sender(settings: Settings) -> SendEmail:
    from azure.communication.email import EmailClient

    client = EmailClient.from_connection_string(settings.acs_connection_string)

    def send(email: Email) -> None:
        message = {
            "senderAddress": settings.notify_from,
            "recipients": {"to": [{"address": address} for address in settings.notify_to]},
            "content": {"subject": email.subject, "plainText": email.text, "html": email.html},
        }
        # Waits until the service has accepted or rejected the message.
        result = client.begin_send(message).result()
        if result.get("status") != "Succeeded":
            raise RuntimeError(f"Email not sent: status {result.get('status')!r}, {result.get('error')}")
        log.info("Email sent, operation %s", result.get("id"))

    return send


def run_notify(settings: Settings, send: SendEmail | None = None) -> int:
    """Email the queued items and empty the queue. Returns the number of items emailed.

    The queue is left as it is when sending fails, so the next run tries again.
    """
    if settings.notify_tier not in ("major", "all"):
        raise ValueError(f"Unknown AZURE_NEWS_NOTIFY_TIER: {settings.notify_tier!r}")
    configured = [
        bool(settings.acs_connection_string),
        bool(settings.notify_from),
        bool(settings.notify_to),
    ]
    if any(configured) and not all(configured):
        raise ValueError(
            "Email notification needs all of AZURE_NEWS_ACS_CONNECTION_STRING, "
            "AZURE_NEWS_NOTIFY_FROM and AZURE_NEWS_NOTIFY_TO"
        )

    pending = set((read_json(settings.notifications_path) or {}).get("pending", []))
    if not pending:
        return 0

    sent = 0
    if not any(configured):
        # Dropped rather than kept, so that turning notification on later does not
        # send everything published in the meantime.
        log.info("Email notification is not configured; %d queued items dropped", len(pending))
    else:
        document = read_json(settings.news_path) or {}
        items = [
            item
            for item in document.get("items", [])
            if item["id"] in pending and (settings.notify_tier == "all" or item["tier"] == "major")
        ]
        if items:
            (send or acs_sender(settings))(build_email(items, settings))
            sent = len(items)

    write_json(settings.notifications_path, {"pending": []})
    return sent
