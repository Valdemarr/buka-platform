#!/usr/bin/env python3
"""
BUKA CVR Alert — daily job
Fetches new Danish company registrations, emails each subscriber their filtered list.
Run once per day (cron: 0 7 * * 1-5)
"""
import os, sqlite3, requests, json, time, hashlib, hmac
from datetime import datetime, timedelta
from html import escape

# Load .env from script directory if present (server-side config)
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

RESEND_KEY   = os.environ["RESEND_API_KEY_EXTERNAL"]   # re_RrGhfEaE_...
FROM_EMAIL   = "esben@buka.dk"
DB_PATH      = os.path.join(os.path.dirname(__file__), "buka.db")
BUKA_URL     = os.environ.get("BUKA_URL", "https://buka.dk")
UNSUB_SECRET = os.environ.get("UNSUB_SECRET", "buka-unsub-2026")


def make_unsub_token(email):
    return hmac.new(UNSUB_SECRET.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:32]

# Industry codes we care about mapping to subscriber categories
# Keys match the 'category' field in the signups table
CATEGORY_FILTERS = {
    "revisor":     None,   # all industries — new companies all need accountants
    "webbureau":   None,   # all — all new companies may need a website
    "forsikring":  None,
    "bank":        None,
    "it":          None,
    "reklame":     None,
    "telefoni":    None,
    "andet":       None,
}

def get_new_companies(days_back=1):
    """
    Fetch companies registered in the last N days via cvrapi.dk sequential CVR scan.
    Strategy: find the highest known CVR, scan forward until 404s.
    Falls back to date-based cvrapi search if sequential fails.
    """
    companies = []
    cutoff_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    # Try querying recent registrations via cvrapi search
    # cvrapi doesn't support date range natively, so we use a heuristic:
    # scan a window of high CVR numbers (new companies get high sequential numbers)
    db = sqlite3.connect(DB_PATH)
    row = db.execute("SELECT last_cvr FROM cvr_seen WHERE id=1").fetchone()
    last_cvr = row[0] if row else None
    db.close()

    if last_cvr is None:
        last_cvr = 44500000  # approximate current high watermark

    scanned, found, consecutive_misses = 0, 0, 0
    cvr = last_cvr + 1

    while consecutive_misses < 20 and scanned < 200:
        try:
            r = requests.get(
                f"https://cvrapi.dk/api?vat={cvr}&country=dk",
                timeout=5
            )
            if r.status_code == 200:
                data = r.json()
                if "error" not in data:
                    # Parse startdate "DD/MM - YYYY"
                    start_raw = data.get("startdate", "")
                    start_date = parse_cvr_date(start_raw)
                    if start_date and start_date >= cutoff_date:
                        companies.append({
                            "cvr":      str(cvr),
                            "name":     data.get("name", ""),
                            "address":  data.get("address", ""),
                            "zipcode":  data.get("zipcode", ""),
                            "city":     data.get("city", ""),
                            "phone":    data.get("phone", ""),
                            "email":    data.get("email", ""),
                            "industry": data.get("industrydesc", ""),
                            "type":     data.get("companydesc", ""),
                            "founded":  start_date,
                        })
                        found += 1
                    consecutive_misses = 0
                else:
                    consecutive_misses += 1
            else:
                consecutive_misses += 1
        except Exception:
            consecutive_misses += 1

        cvr += 1
        scanned += 1
        time.sleep(0.5)  # be polite

    # Save new high watermark
    if scanned > 0:
        db = sqlite3.connect(DB_PATH)
        db.execute("INSERT OR REPLACE INTO cvr_seen (id, last_cvr) VALUES (1, ?)", (cvr - 1,))
        db.commit()
        db.close()

    return companies


def parse_cvr_date(raw):
    """Convert 'DD/MM - YYYY' to 'YYYY-MM-DD'."""
    try:
        raw = raw.replace(" ", "")
        day, rest = raw.split("/")
        month, year = rest.split("-")
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    except Exception:
        return None


def company_row_html(c):
    name     = escape(c.get("name", ""))
    cvr      = escape(c.get("cvr", ""))
    city     = escape(c.get("city", "") or "")
    industry = escape(c.get("industry", "") or "Ukendt branche")
    phone    = escape(c.get("phone", "") or "")
    email    = escape(c.get("email", "") or "")
    ctype    = escape(c.get("type", "") or "")

    phone_html = f'<a href="tel:{phone}" style="color:#1a56ff;text-decoration:none;">{phone}</a>' if phone else '<span style="color:#9ca3af;">—</span>'
    email_html = f'<a href="mailto:{email}" style="color:#1a56ff;text-decoration:none;">{email}</a>' if email else '<span style="color:#9ca3af;">—</span>'

    return f"""
    <tr>
      <td style="background:#fff;padding:20px 32px;border-top:1px solid #e5e7eb;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td>
              <p style="margin:0 0 2px;font-size:1rem;font-weight:800;color:#0d0d1a;">{name}</p>
              <p style="margin:0 0 8px;font-size:0.78rem;color:#6b7280;">{ctype} &mdash; CVR {cvr} &mdash; {city}</p>
              <p style="margin:0;font-size:0.82rem;color:#374151;background:#f8f9ff;display:inline-block;padding:3px 8px;border-radius:4px;">{industry}</p>
            </td>
          </tr>
          <tr><td style="padding-top:10px;">
            <table cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td style="padding-right:20px;font-size:0.82rem;color:#374151;">📞 {phone_html}</td>
                <td style="font-size:0.82rem;color:#374151;">✉️ {email_html}</td>
              </tr>
            </table>
          </td></tr>
        </table>
      </td>
    </tr>"""


def send_alert(subscriber_email, subscriber_name, companies, date_str):
    if not companies:
        return

    rows_html  = "".join(company_row_html(c) for c in companies)
    count      = len(companies)
    unsub_link = f"{BUKA_URL}/unsubscribe?email={subscriber_email}&token={make_unsub_token(subscriber_email)}"

    with open(os.path.join(os.path.dirname(__file__), "alert_email_template.html")) as f:
        template = f.read()

    html = template \
        .replace("{{DATE}}", date_str) \
        .replace("{{COUNT}}", str(count)) \
        .replace("{{COMPANY_ROWS}}", rows_html) \
        .replace("{{UNSUB_LINK}}", unsub_link)

    subject = f"BUKA: {count} nye virksomheder registreret {date_str}"

    payload = {
        "from":    FROM_EMAIL,
        "to":      [subscriber_email],
        "subject": subject,
        "html":    html,
    }

    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=10,
    )
    if r.status_code not in (200, 201):
        print(f"WARN: failed to send to {subscriber_email}: {r.status_code} {r.text}")
    else:
        print(f"Sent to {subscriber_email}: {count} companies")


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS signups (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        email       TEXT UNIQUE NOT NULL,
        name        TEXT,
        category    TEXT NOT NULL,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS cvr_seen (
        id       INTEGER PRIMARY KEY,
        last_cvr INTEGER NOT NULL
    );
    """)
    db.commit()
    db.close()


def _tg_ops(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat  = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text},
            timeout=5,
        )
    except Exception:
        pass


def main():
    init_db()
    date_str  = (datetime.utcnow() - timedelta(days=1)).strftime("%-d. %B %Y")
    companies = get_new_companies(days_back=1)

    if not companies:
        msg = f"BUKA: Ingen nye virksomheder fundet for {date_str}. Tjek CVR data-kilde."
        print(msg)
        _tg_ops(msg)
        return

    print(f"Found {len(companies)} new companies for {date_str}")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    subscribers = db.execute("SELECT * FROM signups").fetchall()
    db.close()

    for sub in subscribers:
        send_alert(sub["email"], sub["name"] or "", companies, date_str)
        time.sleep(0.3)

    summary = f"BUKA: {len(companies)} nye virksomheder sendt til {len(subscribers)} abonnenter ({date_str})"
    print(summary)
    _tg_ops(summary)


if __name__ == "__main__":
    main()
