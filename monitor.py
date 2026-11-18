"""Watch Palaxi Cinemas showtimes for chosen dates and email any change.

Settings come from environment variables (GitHub repo Variables/Secrets):
  WATCH_URL           movie page on palaxicinemas.com (required)
  WATCH_LOCATION      cinema location to pick, default "Kozhikode"
  WATCH_DATES         date tabs to check, comma separated, default "Thu 17,Fri 18"
  ALERT_EMAIL         where alerts are sent (required)
  GMAIL_USER          Gmail address that sends the alerts (required)
  GMAIL_APP_PASSWORD  Gmail App Password for GMAIL_USER (required, keep secret)
"""

import difflib
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SNAPSHOT = Path("snapshot.txt")


def env(name, default=None):
    value = os.environ.get(name, "").strip() or default
    if value is None:
        sys.exit(f"Missing setting: {name}")
    return value


def showtimes_text(page):
    """Return the show list currently on screen (text between SHOW TIMES and Non Cancellable)."""
    body = page.inner_text("body")
    if "SHOW TIMES" not in body:
        return ""
    part = body.split("SHOW TIMES", 1)[1].split("Non Cancellable", 1)[0]
    lines = [" ".join(l.split()) for l in part.splitlines()]
    lines = [l for l in lines if l]
    # Drop the date tab labels (e.g. "Thu 17", "Dec") at the top; keep show rows.
    while lines and (lines[0][:3] in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
                     or lines[0] in {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                                     "Aug", "Sep", "Oct", "Nov", "Dec"}):
        lines.pop(0)
    # Group as "time | screen | format" rows.
    rows, row = [], []
    for l in lines:
        if row and (l.endswith("AM") or l.endswith("PM")):
            rows.append(" | ".join(row))
            row = []
        row.append(l)
    if row:
        rows.append(" | ".join(row))
    return "\n".join(rows)


def collect(url, location, dates):
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=60000)

        # Pick the cinema location if the site asks for it.
        loc = page.get_by_text(location, exact=True)
        if loc.count():
            loc.first.click()

        try:
            page.wait_for_selector("button.pgbtn", timeout=30000)
        except PWTimeout:
            browser.close()
            return "No show dates are listed on the page yet.\n"

        for d in dates:
            btn = page.locator(f'button[aria-label="Go to {d}"]')
            out.append(f"== {d} ==")
            if not btn.count():
                out.append("Date not listed yet")
                continue
            btn.first.click()
            page.wait_for_timeout(2500)
            out.append(showtimes_text(page) or "No shows")
        browser.close()
    return "\n".join(out) + "\n"


def send_email(subject, body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env("GMAIL_USER")
    msg["To"] = env("ALERT_EMAIL")
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(env("GMAIL_USER"), env("GMAIL_APP_PASSWORD"))
        smtp.send_message(msg)


def main():
    url = env("WATCH_URL")
    location = env("WATCH_LOCATION", "Kozhikode")
    dates = [d.strip() for d in env("WATCH_DATES", "Thu 17,Fri 18").split(",") if d.strip()]
    new_text = collect(url, location, dates)
    print(new_text)

    if os.environ.get("DRY_RUN"):
        return

    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(new_text, encoding="utf-8")
        send_email("Showtime monitor started",
                   f"Now watching:\n{url}\n\nCurrent shows:\n\n{new_text}")
        return

    old_text = SNAPSHOT.read_text(encoding="utf-8")
    if old_text == new_text:
        print("No change.")
        return

    diff = "\n".join(difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(),
        fromfile="before", tofile="now", lineterm="", n=50))
    send_email(
        "Showtimes changed!",
        f"A change was detected on:\n{url}\n\n"
        f"CURRENT SHOWS:\n{new_text}\n"
        "WHAT CHANGED ('-' removed, '+' added):\n" + diff,
    )
    SNAPSHOT.write_text(new_text, encoding="utf-8")
    print("Change detected: email sent.")


if __name__ == "__main__":
    main()
