from flask import Flask, request, jsonify, session, render_template
import hashlib, os

app = Flask(__name__)
app.secret_key = 'outingplanning_secret_2025'

# ── DB ABSTRACTION ────────────────────────────────────────
# Local = SQLite, Render = PostgreSQL (set DATABASE_URL env var)
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras

    def get_db():
        conn = psycopg2.connect(DATABASE_URL)
        return conn

    def q(sql):
        # convert SQLite ? placeholders to PostgreSQL %s
        return sql.replace('?', '%s')

    def fetchall(cursor):
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def fetchone(cursor):
        if cursor.description is None:
            return None
        cols = [d[0] for d in cursor.description]
        row = cursor.fetchone()
        return dict(zip(cols, row)) if row else None

    def lastrowid(cursor):
        cursor.execute('SELECT lastval()')
        return cursor.fetchone()[0]

else:
    import sqlite3
    SQLITE_DB = os.path.join(os.path.dirname(__file__), 'outingplanning.db')

    def get_db():
        conn = sqlite3.connect(SQLITE_DB)
        conn.row_factory = sqlite3.Row
        return conn

    def q(sql):
        return sql  # SQLite uses ? already

    def fetchall(cursor):
        return [dict(r) for r in cursor.fetchall()]

    def fetchone(cursor):
        row = cursor.fetchone()
        return dict(row) if row else None

    def lastrowid(cursor):
        return cursor.lastrowid

# ── PAGE ROUTES ───────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/dashboard')
def dashboard_page():
    return render_template('dashboard.html')

# ── DB SETUP ──────────────────────────────────────────────
TEAM_NAME = 'Swimming Outing'

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    conn = get_db()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute('''CREATE TABLE IF NOT EXISTS teams (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            event_date TEXT,
            event_location TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS attendees (
            id SERIAL PRIMARY KEY,
            team_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'Guest',
            status TEXT DEFAULT 'going')''')
        cur.execute('''CREATE TABLE IF NOT EXISTS foods (
            id SERIAL PRIMARY KEY,
            team_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            assigned_to TEXT DEFAULT 'TBD',
            category TEXT DEFAULT 'Main Dish')''')
        cur.execute('''CREATE TABLE IF NOT EXISTS polls (
            id SERIAL PRIMARY KEY,
            team_id INTEGER NOT NULL,
            question TEXT NOT NULL)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS poll_options (
            id SERIAL PRIMARY KEY,
            poll_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            votes INTEGER DEFAULT 0)''')
    else:
        cur.executescript('''
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                event_date TEXT,
                event_location TEXT);
            CREATE TABLE IF NOT EXISTS attendees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'Guest',
                status TEXT DEFAULT 'going');
            CREATE TABLE IF NOT EXISTS foods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                assigned_to TEXT DEFAULT 'TBD',
                category TEXT DEFAULT 'Main Dish');
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                question TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS poll_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                votes INTEGER DEFAULT 0);
        ''')
    cur.execute(q('INSERT INTO teams (name, password_hash) VALUES (?,?) ON CONFLICT (name) DO NOTHING'
                  if DATABASE_URL else
                  'INSERT OR IGNORE INTO teams (name, password_hash) VALUES (?,?)'),
                (TEAM_NAME, hash_pw('swim2025')))
    conn.commit()
    conn.close()

# ── AUTH ──────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    team = data.get('team', '').strip()
    pw   = data.get('password', '')
    if not team or not pw:
        return jsonify({'error': 'All fields required'}), 400
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(q('INSERT INTO teams (name, password_hash) VALUES (?,?)'), (team, hash_pw(pw)))
        conn.commit()
        return jsonify({'message': 'Team registered'})
    except Exception:
        conn.rollback()
        return jsonify({'error': 'Team name already exists'}), 409
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    pw     = data.get('password', '')
    user   = data.get('user', '').strip()
    status = data.get('status', 'going')
    if status not in ('going', 'maybe'):
        status = 'going'
    if not pw or not user:
        return jsonify({'error': 'All fields required'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q('SELECT * FROM teams WHERE password_hash=?'), (hash_pw(pw),))
    row = fetchone(cur)
    if not row:
        conn.close()
        return jsonify({'error': 'Incorrect password'}), 401
    session['team_id']   = row['id']
    session['team_name'] = row['name']
    session['user_name'] = user
    # auto-add or update attendee status
    cur.execute(q('SELECT id FROM attendees WHERE team_id=? AND LOWER(name)=LOWER(?)'), (row['id'], user))
    existing = fetchone(cur)
    if existing:
        cur.execute(q('UPDATE attendees SET status=? WHERE id=?'), (status, existing['id']))
    else:
        cur.execute(q('INSERT INTO attendees (team_id,name,role,status) VALUES (?,?,?,?)'),
                    (row['id'], user, 'Member', status))
    conn.commit()
    conn.close()
    return jsonify({'team': row['name'], 'user': user})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'})

@app.route('/api/me')
def me():
    if 'team_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'team': session['team_name'], 'user': session['user_name']})

# ── EVENT ─────────────────────────────────────────────────
@app.route('/api/event', methods=['GET','PUT'])
def event():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    tid = session['team_id']
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'PUT':
        d = request.json
        cur.execute(q('UPDATE teams SET event_date=?, event_location=? WHERE id=?'),
                    (d.get('date'), d.get('location'), tid))
        conn.commit()
    cur.execute(q('SELECT event_date, event_location FROM teams WHERE id=?'), (tid,))
    row = fetchone(cur)
    conn.close()
    return jsonify({'date': row['event_date'], 'location': row['event_location']})

# ── ATTENDEES ─────────────────────────────────────────────
@app.route('/api/attendees', methods=['GET','POST'])
def attendees():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    tid = session['team_id']
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'POST':
        d = request.json
        cur.execute(q('INSERT INTO attendees (team_id,name,role,status) VALUES (?,?,?,?)'),
                    (tid, d['name'], d.get('role','Guest'), d.get('status','going')))
        conn.commit()
    cur.execute(q('SELECT * FROM attendees WHERE team_id=?'), (tid,))
    rows = fetchall(cur)
    conn.close()
    return jsonify(rows)

@app.route('/api/attendees/<int:aid>', methods=['DELETE'])
def delete_attendee(aid):
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q('DELETE FROM attendees WHERE id=? AND team_id=?'), (aid, session['team_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Deleted'})

# ── FOOD ──────────────────────────────────────────────────
@app.route('/api/foods', methods=['GET','POST'])
def foods():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    tid = session['team_id']
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'POST':
        d = request.json
        cur.execute(q('INSERT INTO foods (team_id,name,assigned_to,category) VALUES (?,?,?,?)'),
                    (tid, d['name'], d.get('assigned_to','TBD'), d.get('category','Main Dish')))
        conn.commit()
    cur.execute(q('SELECT * FROM foods WHERE team_id=?'), (tid,))
    rows = fetchall(cur)
    conn.close()
    return jsonify(rows)

@app.route('/api/foods/<int:fid>', methods=['DELETE'])
def delete_food(fid):
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q('DELETE FROM foods WHERE id=? AND team_id=?'), (fid, session['team_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Deleted'})

# ── POLLS ─────────────────────────────────────────────────
@app.route('/api/polls', methods=['GET','POST'])
def polls():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    tid = session['team_id']
    conn = get_db()
    cur = conn.cursor()
    if request.method == 'POST':
        d = request.json
        cur.execute(q('INSERT INTO polls (team_id,question) VALUES (?,?)'), (tid, d['question']))
        pid = lastrowid(cur)
        for opt in d.get('options', []):
            cur.execute(q('INSERT INTO poll_options (poll_id,label) VALUES (?,?)'), (pid, opt))
        conn.commit()
    cur.execute(q('SELECT * FROM polls WHERE team_id=?'), (tid,))
    poll_rows = fetchall(cur)
    result = []
    for p in poll_rows:
        cur.execute(q('SELECT * FROM poll_options WHERE poll_id=?'), (p['id'],))
        opts = fetchall(cur)
        result.append({'id': p['id'], 'question': p['question'], 'options': opts})
    conn.close()
    return jsonify(result)

@app.route('/api/polls/<int:pid>', methods=['DELETE'])
def delete_poll(pid):
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q('DELETE FROM poll_options WHERE poll_id=?'), (pid,))
    cur.execute(q('DELETE FROM polls WHERE id=? AND team_id=?'), (pid, session['team_id']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Deleted'})

@app.route('/api/polls/<int:pid>/options', methods=['POST'])
def add_poll_option(pid):
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    label = request.json.get('label', '').strip()
    if not label:
        return jsonify({'error': 'Label required'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q('SELECT id FROM polls WHERE id=? AND team_id=?'), (pid, session['team_id']))
    if not fetchone(cur):
        conn.close()
        return jsonify({'error': 'Poll not found'}), 404
    cur.execute(q('INSERT INTO poll_options (poll_id, label) VALUES (?,?)'), (pid, label))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Option added'})

@app.route('/api/polls/<int:pid>/vote/<int:oid>', methods=['POST'])
def vote(pid, oid):
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q('UPDATE poll_options SET votes=votes+1 WHERE id=? AND poll_id=?'), (oid, pid))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Voted'})

# ── STATS ─────────────────────────────────────────────────
@app.route('/api/stats')
def stats():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    tid = session['team_id']
    conn = get_db()
    cur = conn.cursor()
    cur.execute(q('SELECT COUNT(*) FROM attendees WHERE team_id=?'), (tid,))
    total = cur.fetchone()[0]
    cur.execute(q("SELECT COUNT(*) FROM attendees WHERE team_id=? AND status='going'"), (tid,))
    confirmed = cur.fetchone()[0]
    cur.execute(q('SELECT COUNT(*) FROM foods WHERE team_id=?'), (tid,))
    food_count = cur.fetchone()[0]
    cur.execute(q('SELECT COUNT(*) FROM polls WHERE team_id=?'), (tid,))
    poll_count = cur.fetchone()[0]
    conn.close()
    return jsonify({'attendees': total, 'confirmed': confirmed, 'foods': food_count, 'polls': poll_count})

init_db()

if __name__ == '__main__':
    print('OutingPlanning server running at http://localhost:5000')
    app.run(debug=True, port=5000)
