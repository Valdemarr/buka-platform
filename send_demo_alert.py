#!/usr/bin/env python3
"""
BUKA Demo Alert — one-shot script to send a sample alert to all subscribers.
Useful for: pipeline testing, engaging early signups, showing the product.
Usage: python3 send_demo_alert.py
"""
import os, sqlite3, time
from datetime import datetime

# Load .env if present
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# Import shared functions from cvr_alert
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cvr_alert import send_alert, DB_PATH

DEMO_COMPANIES = [
    {
        "cvr":      "44621035",
        "name":     "Nordic Digital Solutions ApS",
        "address":  "Vesterbrogade 12",
        "zipcode":  "1620",
        "city":     "København V",
        "phone":    "31245678",
        "email":    "info@nordicdigital.dk",
        "industry": "IT-konsulentvirksomhed",
        "type":     "Anpartsselskab",
        "founded":  datetime.utcnow().strftime("%Y-%m-%d"),
    },
    {
        "cvr":      "44621118",
        "name":     "Grøntvang Ejendomme ApS",
        "address":  "Amagerbrogade 45",
        "zipcode":  "2300",
        "city":     "København S",
        "phone":    "40123456",
        "email":    "",
        "industry": "Udlejning af erhvervsejendomme",
        "type":     "Anpartsselskab",
        "founded":  datetime.utcnow().strftime("%Y-%m-%d"),
    },
    {
        "cvr":      "44621204",
        "name":     "Petersen & Dahl Konsulenter IVS",
        "address":  "Skt. Knuds Torv 1",
        "zipcode":  "8000",
        "city":     "Aarhus C",
        "phone":    "28765432",
        "email":    "kontakt@petersendahl.dk",
        "industry": "Virksomhedsrådgivning og -planlægning",
        "type":     "Iværksætterselskab",
        "founded":  datetime.utcnow().strftime("%Y-%m-%d"),
    },
    {
        "cvr":      "44621397",
        "name":     "Sunset Events & Marketing ApS",
        "address":  "Havnegade 3",
        "zipcode":  "5000",
        "city":     "Odense C",
        "phone":    "",
        "email":    "hello@sunsetevents.dk",
        "industry": "PR og kommunikation",
        "type":     "Anpartsselskab",
        "founded":  datetime.utcnow().strftime("%Y-%m-%d"),
    },
    {
        "cvr":      "44621489",
        "name":     "TechFlow Systems ApS",
        "address":  "Nørregade 8",
        "zipcode":  "9000",
        "city":     "Aalborg",
        "phone":    "71234567",
        "email":    "info@techflow.dk",
        "industry": "Udvikling og produktion af software",
        "type":     "Anpartsselskab",
        "founded":  datetime.utcnow().strftime("%Y-%m-%d"),
    },
]


def main():
    date_str = datetime.utcnow().strftime("%-d. %B %Y")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    subscribers = db.execute("SELECT * FROM signups").fetchall()
    db.close()

    if not subscribers:
        print("No subscribers yet. No emails sent.")
        return

    print(f"Sending demo alert to {len(subscribers)} subscriber(s) with {len(DEMO_COMPANIES)} sample companies...")
    for sub in subscribers:
        send_alert(sub["email"], sub["name"] or "", DEMO_COMPANIES, f"{date_str} (demo)")
        time.sleep(0.3)

    print(f"Done.")


if __name__ == "__main__":
    main()
