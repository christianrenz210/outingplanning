from flask import Flask, request, jsonify, session, render_template
import sqlite3, hashlib, os

app = Flask(__name__)
app.secret_key = 'outingplanning_secret_2025'

# ── DB PATH ───────────────────────────────────────────────
if os.environ.get('RENDER'):
    DB = '/tmp/outingplanning.db'
else:
    DB = os.path.join(os.path.dirname(__file__), 'outingplanning.db')

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
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

TEAM_NAME = 'Swimming Outing'

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def init_db():
    with get_db() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                event_date TEXT,
                event_location TEXT
            );
            CREATE TABLE IF NOT EXISTS attendees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                role TEXT DEFAULT 'Guest',
                status TEXT DEFAULT 'going',
                FOREIGN KEY (team_id) REFERENCES teams(id)
            );
            CREATE TABLE IF NOT EXISTS foods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                assigned_to TEXT DEFAULT 'TBD',
                category TEXT DEFAULT 'Main Dish',
                FOREIGN KEY (team_id) REFERENCES teams(id)
            );
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                FOREIGN KEY (team_id) REFERENCES teams(id)
            );
            CREATE TABLE IF NOT EXISTS poll_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                votes INTEGER DEFAULT 0,
                FOREIGN KEY (poll_id) REFERENCES polls(id)
            );
        ''')
        db.execute(
            'INSERT OR IGNORE INTO teams (name, password_hash) VALUES (?, ?)',
            (TEAM_NAME, hash_pw('swim2025'))
        )

# ── AUTH ──────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    team = data.get('team', '').strip()
    pw   = data.get('password', '')
    if not team or not pw:
        return jsonify({'error': 'All fields required'}), 400
    try:
        with get_db() as db:
            db.execute('INSERT INTO teams (name, password_hash) VALUES (?,?)', (team, hash_pw(pw)))
        return jsonify({'message': 'Team registered'})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Team name already exists'}), 409

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    pw   = data.get('password', '')
    user = data.get('user', '').strip()
    if not pw or not user:
        return jsonify({'error': 'All fields required'}), 400
    with get_db() as db:
        row = db.execute('SELECT * FROM teams WHERE password_hash=?', (hash_pw(pw),)).fetchone()
    if not row:
        return jsonify({'error': 'Incorrect password'}), 401
    session['team_id']   = row['id']
    session['team_name'] = row['name']
    session['user_name'] = user
    return jsonify({'team': row['name'], 'user': user})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'})

@app.route('/api/me')
def me():
    if 'team_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'team': session['team_name'], 'user': session['user_name'], 'team_id': session['team_id']})

# ── EVENT ─────────────────────────────────────────────────
@app.route('/api/event', methods=['GET','PUT'])
def event():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    tid = session['team_id']
    with get_db() as db:
        if request.method == 'PUT':
            d = request.json
            db.execute('UPDATE teams SET event_date=?, event_location=? WHERE id=?',
                       (d.get('date'), d.get('location'), tid))
        row = db.execute('SELECT event_date, event_location FROM teams WHERE id=?', (tid,)).fetchone()
    return jsonify({'date': row['event_date'], 'location': row['event_location']})

# ── ATTENDEES ─────────────────────────────────────────────
@app.route('/api/attendees', methods=['GET','POST'])
def attendees():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    tid = session['team_id']
    with get_db() as db:
        if request.method == 'POST':
            d = request.json
            db.execute('INSERT INTO attendees (team_id,name,role,status) VALUES (?,?,?,?)',
                       (tid, d['name'], d.get('role','Guest'), d.get('status','going')))
        rows = db.execute('SELECT * FROM attendees WHERE team_id=?', (tid,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/attendees/<int:aid>', methods=['DELETE'])
def delete_attendee(aid):
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as db:
        db.execute('DELETE FROM attendees WHERE id=? AND team_id=?', (aid, session['team_id']))
    return jsonify({'message': 'Deleted'})

# ── FOOD ──────────────────────────────────────────────────
@app.route('/api/foods', methods=['GET','POST'])
def foods():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    tid = session['team_id']
    with get_db() as db:
        if request.method == 'POST':
            d = request.json
            db.execute('INSERT INTO foods (team_id,name,assigned_to,category) VALUES (?,?,?,?)',
                       (tid, d['name'], d.get('assigned_to','TBD'), d.get('category','Main Dish')))
        rows = db.execute('SELECT * FROM foods WHERE team_id=?', (tid,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/foods/<int:fid>', methods=['DELETE'])
def delete_food(fid):
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as db:
        db.execute('DELETE FROM foods WHERE id=? AND team_id=?', (fid, session['team_id']))
    return jsonify({'message': 'Deleted'})

# ── POLLS ─────────────────────────────────────────────────
@app.route('/api/polls', methods=['GET','POST'])
def polls():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    tid = session['team_id']
    with get_db() as db:
        if request.method == 'POST':
            d = request.json
            cur = db.execute('INSERT INTO polls (team_id,question) VALUES (?,?)', (tid, d['question']))
            pid = cur.lastrowid
            for opt in d.get('options', []):
                db.execute('INSERT INTO poll_options (poll_id,label) VALUES (?,?)', (pid, opt))
        rows = db.execute('SELECT * FROM polls WHERE team_id=?', (tid,)).fetchall()
        result = []
        for p in rows:
            opts = db.execute('SELECT * FROM poll_options WHERE poll_id=?', (p['id'],)).fetchall()
            result.append({'id': p['id'], 'question': p['question'], 'options': [dict(o) for o in opts]})
    return jsonify(result)

@app.route('/api/polls/<int:pid>', methods=['DELETE'])
def delete_poll(pid):
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as db:
        db.execute('DELETE FROM poll_options WHERE poll_id=?', (pid,))
        db.execute('DELETE FROM polls WHERE id=? AND team_id=?', (pid, session['team_id']))
    return jsonify({'message': 'Deleted'})

@app.route('/api/polls/<int:pid>/options', methods=['POST'])
def add_poll_option(pid):
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    label = data.get('label', '').strip()
    if not label:
        return jsonify({'error': 'Label required'}), 400
    with get_db() as db:
        poll = db.execute('SELECT * FROM polls WHERE id=? AND team_id=?', (pid, session['team_id'])).fetchone()
        if not poll:
            return jsonify({'error': 'Poll not found'}), 404
        db.execute('INSERT INTO poll_options (poll_id, label) VALUES (?,?)', (pid, label))
    return jsonify({'message': 'Option added'})

@app.route('/api/polls/<int:pid>/vote/<int:oid>', methods=['POST'])
def vote(pid, oid):
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    with get_db() as db:
        db.execute('UPDATE poll_options SET votes=votes+1 WHERE id=? AND poll_id=?', (oid, pid))
    return jsonify({'message': 'Voted'})

# ── STATS ─────────────────────────────────────────────────
@app.route('/api/stats')
def stats():
    if 'team_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    tid = session['team_id']
    with get_db() as db:
        total     = db.execute('SELECT COUNT(*) FROM attendees WHERE team_id=?', (tid,)).fetchone()[0]
        confirmed = db.execute("SELECT COUNT(*) FROM attendees WHERE team_id=? AND status='going'", (tid,)).fetchone()[0]
        food_count = db.execute('SELECT COUNT(*) FROM foods WHERE team_id=?', (tid,)).fetchone()[0]
        poll_count = db.execute('SELECT COUNT(*) FROM polls WHERE team_id=?', (tid,)).fetchone()[0]
    return jsonify({'attendees': total, 'confirmed': confirmed, 'foods': food_count, 'polls': poll_count})

init_db()

if __name__ == '__main__':
    print('OutingPlanning server running at http://localhost:5000')
    app.run(debug=True, port=5000)
