"""
BUKA Platform — CVR New Registration Alert Service
"""
import os, sqlite3, secrets, re, hashlib, hmac, requests as _req, json as _json

# Load .env from script directory if present
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from flask import Flask, render_template, request, redirect, url_for, g

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
DB_PATH        = os.path.join(os.path.dirname(__file__), 'buka.db')
UNSUB_SECRET   = os.environ.get('UNSUB_SECRET', 'buka-unsub-2026')
TG_TOKEN       = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TG_CHAT        = os.environ.get('TELEGRAM_CHAT_ID', '')
RESEND_KEY     = os.environ.get('RESEND_API_KEY_EXTERNAL', '')
FROM_EMAIL     = 'esben@buka.dk'


def _tg_notify(text):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        _req.post(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT, 'text': text},
            timeout=4
        )
    except Exception:
        pass

CATEGORY_LABELS = {
    'revisor':    'revisor / bogføring',
    'webbureau':  'webbureau / digitalt bureau',
    'forsikring': 'forsikring',
    'bank':       'bank / finans',
    'it':         'IT / software',
    'reklame':    'reklame / marketing',
    'telefoni':   'telefoni',
    'andet':      'B2B-service',
}

def _send_welcome(email, name, category, city):
    if not RESEND_KEY:
        return
    cat_label = CATEGORY_LABELS.get(category, category)
    first_name = name.split()[0] if name and name.strip() else 'hej'
    unsub_token = hmac.new(UNSUB_SECRET.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:32]
    unsub_url = f'https://buka.dk/unsubscribe?email={email}&token={unsub_token}'
    area = city if city and city != 'Hele Danmark' else 'hele Danmark'

    html = f"""<!DOCTYPE html>
<html lang="da"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f0f4ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f0f4ff;padding:32px 16px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;">
  <tr>
    <td style="background:#1a56ff;border-radius:12px 12px 0 0;padding:24px 32px;">
      <span style="font-size:1.5rem;font-weight:900;color:#fff;letter-spacing:-0.5px;">BUKA</span>
    </td>
  </tr>
  <tr>
    <td style="background:#fff;padding:32px 32px 24px;">
      <h1 style="margin:0 0 16px;font-size:1.4rem;font-weight:900;color:#0d0d1a;">Velkommen, {first_name}!</h1>
      <p style="margin:0 0 16px;font-size:0.95rem;color:#374151;line-height:1.7;">
        Du er nu tilmeldt BUKA. Hver hverdag kl. 7:00 sender vi dig en oversigt over
        nye virksomheder registreret i CVR — filtreret til <strong>{cat_label}</strong> i <strong>{area}</strong>.
      </p>
      <p style="margin:0 0 16px;font-size:0.95rem;color:#374151;line-height:1.7;">
        Disse virksomheder er bogstavelig talt registreret dagen før. De har endnu ikke
        valgt leverandør — du har et vindue på 24–72 timer til at være den første.
      </p>
      <div style="background:#f0f4ff;border-radius:10px;padding:20px 24px;margin:24px 0;">
        <p style="margin:0;font-size:0.9rem;color:#374151;line-height:1.6;">
          <strong>Tip:</strong> Ring helst inden kl. 11. Nye ejere svarer som regel selv.
          Præsenter dig kort — de er i gang med at sætte alt op og er åbne for gode tilbud.
        </p>
      </div>
      <p style="margin:0;font-size:0.85rem;color:#6b7280;">
        Din første alarm lander næste hverdag kl. 7:00.
      </p>
    </td>
  </tr>
  <tr>
    <td style="background:#fff;padding:0 32px 24px;border-radius:0 0 12px 12px;">
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:0 0 16px;">
      <p style="margin:0;font-size:0.75rem;color:#9ca3af;">
        BUKA — <a href="https://buka.dk" style="color:#9ca3af;">buka.dk</a> —
        <a href="{unsub_url}" style="color:#9ca3af;">Afmeld</a>
      </p>
    </td>
  </tr>
</table>
</td></tr></table>
</body></html>"""

    try:
        _req.post(
            'https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {RESEND_KEY}', 'Content-Type': 'application/json'},
            json={'from': FROM_EMAIL, 'to': [email],
                  'subject': 'Velkommen til BUKA — din første alarm ankommer snart', 'html': html},
            timeout=8,
        )
    except Exception:
        pass


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        "CREATE TABLE IF NOT EXISTS signups ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "email TEXT UNIQUE NOT NULL, "
        "name TEXT, "
        "category TEXT NOT NULL, "
        "city TEXT DEFAULT 'Hele Danmark', "
        "created_at TEXT DEFAULT (datetime('now')));"
        "CREATE TABLE IF NOT EXISTS cvr_seen ("
        "id INTEGER PRIMARY KEY, "
        "last_cvr INTEGER NOT NULL);"
    )
    # Migrate existing DB: add city column if missing
    try:
        db.execute("ALTER TABLE signups ADD COLUMN city TEXT DEFAULT 'Hele Danmark'")
        db.commit()
    except Exception:
        pass
    db.commit()
    db.close()

def make_unsub_token(email):
    return hmac.new(UNSUB_SECRET.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:32]

def get_subscriber_count():
    try:
        db = sqlite3.connect(DB_PATH)
        count = db.execute('SELECT COUNT(*) FROM signups').fetchone()[0]
        db.close()
        return count
    except Exception:
        return 0

@app.route('/')
def index():
    count = get_subscriber_count()
    return render_template('index.html', success=False, subscriber_count=count)

@app.route('/signup', methods=['POST'])
def signup():
    email    = request.form.get('email', '').strip().lower()
    name     = request.form.get('name', '').strip()
    category = request.form.get('category', '').strip()
    city     = request.form.get('city', 'Hele Danmark').strip()
    if not email or not category:
        return redirect(url_for('index'))
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return redirect(url_for('index'))
    db = get_db()
    is_new = False
    try:
        db.execute('INSERT INTO signups (email, name, category, city) VALUES (?,?,?,?)',
                   (email, name, category, city))
        db.commit()
        is_new = True
        _tg_notify(
            f"Ny BUKA tilmelding!\n"
            f"Navn: {name or '(ikke angivet)'}\n"
            f"Email: {email}\n"
            f"Kategori: {category}\n"
            f"Område: {city}"
        )
    except sqlite3.IntegrityError:
        pass
    if is_new:
        _send_welcome(email, name, category, city)
    count = get_subscriber_count()
    return render_template('index.html', success=True, subscriber_count=count)

@app.route('/unsubscribe')
def unsubscribe():
    email = request.args.get('email', '').strip().lower()
    token = request.args.get('token', '')
    if not email or not token:
        return 'Ugyldigt afmeldingslink.', 400
    if not hmac.compare_digest(token, make_unsub_token(email)):
        return 'Ugyldigt afmeldingslink.', 400
    db = get_db()
    db.execute('DELETE FROM signups WHERE email=?', (email,))
    db.commit()
    return '''<html><body style="font-family:-apple-system,sans-serif;max-width:560px;
margin:80px auto;text-align:center;color:#374151;">
<h2 style="color:#0d0d1a;">Du er afmeldt</h2>
<p>Din email er fjernet fra BUKA. Du modtager ikke flere alarmer.</p>
<p style="margin-top:32px;"><a href="https://buka.dk"
style="color:#1a56ff;text-decoration:none;">Tilbage til buka.dk</a></p>
</body></html>'''

@app.route('/admin/signups')
def admin_signups():
    if request.args.get('key', '') != os.environ.get('ADMIN_KEY', 'buka2026'):
        return 'Unauthorized', 401
    db = get_db()
    rows    = db.execute('SELECT * FROM signups ORDER BY created_at DESC').fetchall()
    by_cat  = {}
    by_city = {}
    for r in rows:
        cat  = r["category"]
        city = r["city"] if "city" in r.keys() else "Hele Danmark"
        by_cat[cat]   = by_cat.get(cat, 0) + 1
        by_city[city] = by_city.get(city, 0) + 1

    s = '''<html><head><meta charset="UTF-8">
<style>
body{font-family:-apple-system,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#111}
h1{font-size:1.6rem;font-weight:900;margin-bottom:4px}
.stats{display:flex;gap:20px;margin:24px 0;flex-wrap:wrap}
.stat{background:#f0f4ff;border-radius:12px;padding:16px 24px;min-width:140px}
.stat .n{font-size:2rem;font-weight:900;color:#1a56ff}
.stat .l{font-size:.8rem;color:#6b7280;font-weight:600}
table{width:100%;border-collapse:collapse;margin-top:20px;font-size:.9rem}
th{background:#f0f4ff;padding:10px 14px;text-align:left;font-weight:700;font-size:.8rem;text-transform:uppercase}
td{padding:10px 14px;border-bottom:1px solid #e5e7eb}
tr:hover td{background:#fafafa}
.tag{background:#eef2ff;color:#1a56ff;padding:2px 8px;border-radius:4px;font-size:.78rem;font-weight:600}
</style></head><body>'''
    s += f'<h1>BUKA Admin</h1><p style="color:#6b7280;font-size:.85rem">Total: {len(rows)} abonnenter</p>'
    s += '<div class="stats">'
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        s += f'<div class="stat"><div class="n">{n}</div><div class="l">{cat}</div></div>'
    s += '</div>'
    if by_city:
        s += '<p style="font-size:.8rem;color:#6b7280;margin-bottom:4px;font-weight:600">OMRÅDER</p>'
        s += '<div class="stats">'
        for city, n in sorted(by_city.items(), key=lambda x: -x[1]):
            s += f'<div class="stat"><div class="n">{n}</div><div class="l">{city}</div></div>'
        s += '</div>'
    s += '<table><tr><th>#</th><th>Email</th><th>Navn</th><th>Kategori</th><th>Område</th><th>Tilmeldt</th></tr>'
    for r in rows:
        city = r["city"] if "city" in r.keys() else "—"
        s += (f'<tr><td>{r["id"]}</td><td>{r["email"]}</td><td>{r["name"] or "—"}</td>'
              f'<td><span class="tag">{r["category"]}</span></td><td>{city}</td>'
              f'<td>{r["created_at"][:16]}</td></tr>')
    s += '</table></body></html>'
    return s

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
