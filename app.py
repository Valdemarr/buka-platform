"""
BUKA Platform — CVR New Registration Alert Service
"""
import os, sqlite3, secrets, re, hashlib, hmac, requests as _req

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
        "created_at TEXT DEFAULT (datetime('now')));"
        "CREATE TABLE IF NOT EXISTS cvr_seen ("
        "id INTEGER PRIMARY KEY, "
        "last_cvr INTEGER NOT NULL);"
    )
    db.commit()
    db.close()

def make_unsub_token(email):
    return hmac.new(UNSUB_SECRET.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:32]

@app.route('/')
def index():
    return render_template('index.html', success=False)

@app.route('/signup', methods=['POST'])
def signup():
    email    = request.form.get('email', '').strip().lower()
    name     = request.form.get('name', '').strip()
    category = request.form.get('category', '').strip()
    if not email or not category:
        return redirect(url_for('index'))
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return redirect(url_for('index'))
    db = get_db()
    try:
        db.execute('INSERT INTO signups (email, name, category) VALUES (?,?,?)',
                   (email, name, category))
        db.commit()
        _tg_notify(f"Ny BUKA tilmelding!\nNavn: {name or '(ikke angivet)'}\nEmail: {email}\nKategori: {category}")
    except sqlite3.IntegrityError:
        pass
    return render_template('index.html', success=True)

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
    rows = db.execute('SELECT * FROM signups ORDER BY created_at DESC').fetchall()
    out = '<table border=1><tr><th>ID</th><th>Email</th><th>Name</th><th>Category</th><th>Signed up</th></tr>'
    for r in rows:
        out += f'<tr><td>{r["id"]}</td><td>{r["email"]}</td><td>{r["name"]}</td><td>{r["category"]}</td><td>{r["created_at"]}</td></tr>'
    out += '</table>'
    return out

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
