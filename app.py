"""
BUKA Platform — Main Flask Application
Auth, dashboard, lead browsing, claiming
"""
import os, sqlite3, hashlib, secrets, re, json
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, g, flash)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

DB_PATH = os.path.join(os.path.dirname(__file__), 'buka.db')

# ── DB helpers ─────────────────────────────────────────────────────────────

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
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        email       TEXT UNIQUE NOT NULL,
        password    TEXT NOT NULL,
        name        TEXT,
        company     TEXT,
        specialty   TEXT,
        city_focus  TEXT,
        plan        TEXT DEFAULT 'free',
        leads_left  INTEGER DEFAULT 5,
        created_at  TEXT DEFAULT (datetime('now')),
        last_login  TEXT
    );

    CREATE TABLE IF NOT EXISTS companies (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        cvr             TEXT UNIQUE,
        name            TEXT NOT NULL,
        industry        TEXT,
        city            TEXT,
        address         TEXT,
        phone           TEXT,
        email           TEXT,
        website         TEXT,
        employees       INTEGER,
        founded         INTEGER,
        description     TEXT,
        score           INTEGER DEFAULT 0,
        email_verified  INTEGER DEFAULT 0,
        scraped_at      TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS claims (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER REFERENCES users(id),
        company_id  INTEGER REFERENCES companies(id),
        claimed_at  TEXT DEFAULT (datetime('now')),
        expires_at  TEXT,
        status      TEXT DEFAULT 'active',
        UNIQUE(user_id, company_id)
    );

    CREATE TABLE IF NOT EXISTS sessions (
        token       TEXT PRIMARY KEY,
        user_id     INTEGER REFERENCES users(id),
        created_at  TEXT DEFAULT (datetime('now')),
        expires_at  TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_companies_industry ON companies(industry);
    CREATE INDEX IF NOT EXISTS idx_companies_city ON companies(city);
    CREATE INDEX IF NOT EXISTS idx_companies_score ON companies(score DESC);
    CREATE INDEX IF NOT EXISTS idx_claims_user ON claims(user_id);
    ''')
    db.commit()
    db.close()

# ── Auth helpers ────────────────────────────────────────────────────────────

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated

def current_user():
    if 'user_id' not in session:
        return None
    db = get_db()
    return db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()

# ── Routes ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    db = get_db()
    stats = {
        'companies': db.execute('SELECT COUNT(*) FROM companies').fetchone()[0],
        'with_email': db.execute('SELECT COUNT(*) FROM companies WHERE email IS NOT NULL AND email != ""').fetchone()[0],
        'industries': db.execute('SELECT COUNT(DISTINCT industry) FROM companies WHERE industry IS NOT NULL').fetchone()[0],
    }
    return render_template('index.html', stats=stats)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email     = request.form.get('email', '').strip().lower()
        password  = request.form.get('password', '').strip()
        name      = request.form.get('name', '').strip()
        company   = request.form.get('company', '').strip()
        specialty = request.form.get('specialty', '').strip()

        if not email or not password or len(password) < 6:
            flash('Email og adgangskode er påkrævet (min. 6 tegn)', 'error')
            return render_template('register.html')

        db = get_db()
        try:
            db.execute(
                'INSERT INTO users (email, password, name, company, specialty, leads_left) VALUES (?,?,?,?,?,5)',
                (email, hash_password(password), name, company, specialty)
            )
            db.commit()
            user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
            session['user_id'] = user['id']
            session['user_email'] = user['email']
            return redirect(url_for('dashboard'))
        except sqlite3.IntegrityError:
            flash('Email er allerede registreret', 'error')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email=? AND password=?',
                          (email, hash_password(password))).fetchone()
        if user:
            session['user_id'] = user['id']
            session['user_email'] = user['email']
            db.execute('UPDATE users SET last_login=? WHERE id=?',
                       (datetime.utcnow().isoformat(), user['id']))
            db.commit()
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Forkert email eller adgangskode', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    db   = get_db()

    # Filters
    industry = request.args.get('industry', '')
    city     = request.args.get('city', '')
    has_email = request.args.get('has_email', '')
    page     = max(1, int(request.args.get('page', 1)))
    per_page = 20

    # Build query
    where, params = ['1=1'], []

    # Exclude already claimed by this user
    where.append('c.id NOT IN (SELECT company_id FROM claims WHERE user_id=? AND status="active")')
    params.append(user['id'])

    if industry:
        where.append('c.industry LIKE ?')
        params.append(f'%{industry}%')
    if city:
        where.append('c.city LIKE ?')
        params.append(f'%{city}%')
    if has_email:
        where.append('c.email IS NOT NULL AND c.email != ""')

    where_str = ' AND '.join(where)

    total = db.execute(
        f'SELECT COUNT(*) FROM companies c WHERE {where_str}', params
    ).fetchone()[0]

    companies = db.execute(
        f'''SELECT c.* FROM companies c
            WHERE {where_str}
            ORDER BY c.score DESC, c.email IS NOT NULL DESC, c.created_at DESC
            LIMIT ? OFFSET ?''',
        params + [per_page, (page-1)*per_page]
    ).fetchall()

    # User's claimed leads
    claimed = db.execute(
        '''SELECT c.*, co.name as company_name, co.email as company_email,
                  co.phone, co.city as company_city, co.industry, co.website
           FROM claims c
           JOIN companies co ON c.company_id = co.id
           WHERE c.user_id=? AND c.status="active"
           ORDER BY c.claimed_at DESC LIMIT 20''',
        (user['id'],)
    ).fetchall()

    industries = db.execute(
        'SELECT industry, COUNT(*) as n FROM companies WHERE industry IS NOT NULL GROUP BY industry ORDER BY n DESC LIMIT 20'
    ).fetchall()

    cities = db.execute(
        'SELECT city, COUNT(*) as n FROM companies WHERE city IS NOT NULL GROUP BY city ORDER BY n DESC LIMIT 20'
    ).fetchall()

    stats = {
        'total_leads': db.execute('SELECT COUNT(*) FROM companies').fetchone()[0],
        'with_email':  db.execute('SELECT COUNT(*) FROM companies WHERE email IS NOT NULL AND email != ""').fetchone()[0],
        'claimed':     db.execute('SELECT COUNT(*) FROM claims WHERE user_id=? AND status="active"', (user['id'],)).fetchone()[0],
    }

    return render_template('dashboard.html',
        user=user, companies=companies, claimed=claimed,
        industries=industries, cities=cities, stats=stats,
        filters={'industry': industry, 'city': city, 'has_email': has_email},
        page=page, total=total, per_page=per_page,
        pages=max(1, (total + per_page - 1) // per_page)
    )

@app.route('/claim/<int:company_id>', methods=['POST'])
@login_required
def claim(company_id):
    user = current_user()
    db   = get_db()

    if user['leads_left'] < 1:
        return jsonify({'error': 'Ingen leads tilbage på din plan. Opgradér for at fortsætte.'}), 403

    company = db.execute('SELECT * FROM companies WHERE id=?', (company_id,)).fetchone()
    if not company:
        return jsonify({'error': 'Virksomhed ikke fundet'}), 404

    # Check not already claimed by this user
    existing = db.execute('SELECT id FROM claims WHERE user_id=? AND company_id=?',
                          (user['id'], company_id)).fetchone()
    if existing:
        return jsonify({'error': 'Du har allerede claimet dette lead'}), 409

    expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
    try:
        db.execute('INSERT INTO claims (user_id, company_id, expires_at) VALUES (?,?,?)',
                   (user['id'], company_id, expires))
        db.execute('UPDATE users SET leads_left = leads_left - 1 WHERE id=?', (user['id'],))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Allerede claimet'}), 409

    return jsonify({'ok': True, 'company': dict(company), 'expires': expires})

@app.route('/api/stats')
def api_stats():
    db = get_db()
    return jsonify({
        'companies': db.execute('SELECT COUNT(*) FROM companies').fetchone()[0],
        'with_email': db.execute('SELECT COUNT(*) FROM companies WHERE email IS NOT NULL AND email != ""').fetchone()[0],
        'industries': db.execute('SELECT industry, COUNT(*) n FROM companies WHERE industry IS NOT NULL GROUP BY industry ORDER BY n DESC LIMIT 10').fetchall(),
    })

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
