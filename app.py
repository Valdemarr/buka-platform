"""
BUKA Platform — CVR New Registration Alert Service
"""
import os, sqlite3, secrets, re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, g

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

DB_PATH = os.path.join(os.path.dirname(__file__), 'buka.db')

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
    db.executescript('''
    CREATE TABLE IF NOT EXISTS signups (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        email       TEXT UNIQUE NOT NULL,
        name        TEXT,
        category    TEXT NOT NULL,
        created_at  TEXT DEFAULT (datetime('now'))
    );
    ''')
    db.commit()
    db.close()

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

    # Basic email validation
    if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return redirect(url_for('index'))

    db = get_db()
    try:
        db.execute(
            'INSERT INTO signups (email, name, category) VALUES (?,?,?)',
            (email, name, category)
        )
        db.commit()
    except sqlite3.IntegrityError:
        pass  # duplicate email — still show success

    return render_template('index.html', success=True)

@app.route('/admin/signups')
def admin_signups():
    secret = request.args.get('key', '')
    if secret != os.environ.get('ADMIN_KEY', 'buka2026'):
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
