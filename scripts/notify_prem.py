"""Send Prem a short checkpoint email during unattended Health-Loop runs.

Plain SMTP (smtp.gmail.com:587, STARTTLS) — deliberately not Mail.app or
AppleScript, whose GUI dialogs can block an unattended run. Credentials come
exclusively from the environment (GMAIL_SENDER / GMAIL_APP_PASSWORD) and are
never written to disk or logged. Used only at the checkpoint moments defined
in docs/platform improvements/CONTEXT.md §2f.1 — never for routine progress.

Usage:
    python scripts/notify_prem.py "Subject line" "Body text"
    echo "body" | python scripts/notify_prem.py "Subject line" -
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage

RECIPIENT = "pendelanagapremsai@gmail.com"


def send(subject: str, body: str) -> None:
    sender = os.environ.get("GMAIL_SENDER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender or not password:
        raise SystemExit(
            "GMAIL_SENDER / GMAIL_APP_PASSWORD not set in the environment")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.send_message(msg)
    print(f"sent: {subject!r} -> {RECIPIENT}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    subject_arg, body_arg = sys.argv[1], sys.argv[2]
    if body_arg == "-":
        body_arg = sys.stdin.read()
    send(subject_arg, body_arg)
