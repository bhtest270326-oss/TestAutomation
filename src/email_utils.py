"""email_utils.py — Shared branded HTML email template for all customer communications.

Colour scheme matches the Perth Swedish & European Auto Centre banner:
  Primary red  : #C41230
  White        : #FFFFFF
  Body text    : #1e293b
  Light bg     : #f4f4f4
"""

import os
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

# Public base URL of the Railway deployment — set APP_BASE_URL in Railway env vars
_APP_BASE_URL = os.environ.get('APP_BASE_URL', '').rstrip('/')

# Brand colours
RED    = '#C41230'
WHITE  = '#FFFFFF'
DARK   = '#1e293b'
LIGHT_BG = '#f4f4f4'
MUTED  = '#64748b'


def get_banner_url() -> str:
    """Return the publicly accessible URL for the banner image, or empty string."""
    if _APP_BASE_URL:
        return f"{_APP_BASE_URL}/static/Banner.jpg"
    return ''


def build_email_html(content_html: str) -> str:
    """Wrap *content_html* in the standard branded email shell.

    The shell includes:
    - Banner image (or red header fallback if APP_BASE_URL is not set)
    - White content card
    - Red footer
    """
    banner_url = get_banner_url()

    if banner_url:
        banner_block = (
            f'<img src="{banner_url}" alt="Perth Swedish &amp; European Auto Centre" '
            f'width="600" style="display:block;width:100%;max-width:600px;border:0;">'
        )
    else:
        # Fallback: styled red header bar matching the banner
        banner_block = (
            f'<div style="background:{RED};padding:20px 32px;">'
            f'<p style="margin:0;color:{WHITE};font-size:20px;font-weight:700;'
            f'letter-spacing:-0.3px;">Perth Swedish &amp; European Auto Centre</p>'
            f'</div>'
        )

    return (
        '<!DOCTYPE html>'
        '<html lang="en">'
        '<head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '</head>'
        f'<body style="margin:0;padding:0;background:{LIGHT_BG};'
        f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Arial,sans-serif;">'
        '<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{LIGHT_BG};">'
        '<tr><td align="center" style="padding:24px 16px;">'
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;background:#ffffff;border-radius:8px;'
        'overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">'
        # Banner row
        '<tr><td style="line-height:0;font-size:0;padding:0;">'
        + banner_block +
        '</td></tr>'
        # Content row
        '<tr><td style="padding:32px 32px 28px;color:#1e293b;">'
        + content_html +
        '</td></tr>'
        # Footer row
        '<tr><td style="background:#1a1a2a;padding:18px 32px;text-align:center;">'
        f'<p style="margin:0;color:{WHITE};font-size:13px;font-weight:600;">'
        'Perth Swedish &amp; European Auto Centre</p>'
        f'<p style="margin:6px 0 0;color:rgba(255,255,255,0.55);font-size:12px;">'
        'Payment by EFTPOS on the day &nbsp;|&nbsp; Reply to this email with any questions</p>'
        '</td></tr>'
        '</table>'
        '</td></tr>'
        '</table>'
        '</body></html>'
    )


def _p(text: str, style: str = '') -> str:
    """Convenience: paragraph tag."""
    base = f'color:{DARK};font-size:15px;line-height:1.65;margin:0 0 14px;'
    return f'<p style="{base}{style}">{text}</p>'


def _h2(text: str) -> str:
    return (
        f'<h2 style="color:{RED};font-size:18px;font-weight:700;'
        f'margin:0 0 16px;padding-bottom:10px;border-bottom:2px solid {RED};">'
        f'{text}</h2>'
    )


def _info_row(label: str, value: str) -> str:
    return (
        '<tr>'
        f'<td style="padding:8px 12px;font-size:14px;color:{MUTED};'
        f'font-weight:600;white-space:nowrap;width:130px;">{label}</td>'
        f'<td style="padding:8px 12px;font-size:14px;color:{DARK};">{value}</td>'
        '</tr>'
    )


def _info_table(rows: list[tuple[str, str]]) -> str:
    """Render a two-column label/value table with a left red accent border."""
    inner = ''.join(_info_row(label, value) for label, value in rows if value)
    return (
        '<table cellpadding="0" cellspacing="0" width="100%" '
        f'style="border-left:4px solid {RED};border-collapse:collapse;'
        f'margin:0 0 20px;background:#f8fafc;border-radius:0 4px 4px 0;">'
        f'<tbody>{inner}</tbody>'
        '</table>'
    )


def _ul(items: list[str]) -> str:
    lis = ''.join(
        f'<li style="margin-bottom:6px;color:{DARK};font-size:15px;">{i}</li>'
        for i in items
    )
    return f'<ul style="margin:8px 0 20px;padding-left:20px;">{lis}</ul>'


def send_customer_email(
    service,
    to_email: str,
    subject: str,
    content_html: str,
    thread_id: str = None,
    message_id_header: str = None,
) -> None:
    """Send a branded HTML email to a customer via the Gmail API.

    Args:
        service:            Gmail API service object.
        to_email:           Recipient address.
        subject:            Email subject line.
        content_html:       Inner HTML body (will be wrapped in the brand template).
        thread_id:          Gmail thread ID to reply into (optional).
        message_id_header:  Message-ID value for In-Reply-To threading (optional).
    """
    html = build_email_html(content_html)

    msg = MIMEMultipart('alternative')
    msg['to'] = to_email
    msg['subject'] = subject
    if message_id_header:
        msg['In-Reply-To'] = message_id_header
        msg['References'] = message_id_header
    msg.attach(MIMEText(html, 'html'))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    send_body = {'raw': raw}
    if thread_id:
        send_body['threadId'] = thread_id

    service.users().messages().send(userId='me', body=send_body).execute()
