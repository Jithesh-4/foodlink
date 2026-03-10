

from flask import Flask, render_template, request, redirect, session, jsonify, Response
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
import json, queue, threading
from datetime import datetime, timedelta
from ai_utils import translate_text
import ollama
app = Flask(__name__)
app.secret_key = 'foodlink_secret_2024'




#  SSE REAL-TIME SYSTEM

_listeners_lock = threading.Lock()
_listeners = []


def broadcast_event(event_type, data):
    msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with _listeners_lock:
        dead = []
        for q in _listeners:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _listeners.remove(q)


def sse_stream():
    my_queue = queue.Queue(maxsize=50)
    with _listeners_lock:
        _listeners.append(my_queue)
    yield "event: connected\ndata: {\"msg\": \"connected\"}\n\n"
    try:
        while True:
            try:
                msg = my_queue.get(timeout=25)
                yield msg
            except queue.Empty:
                yield ": ping\n\n"
    except GeneratorExit:
        pass
    finally:
        with _listeners_lock:
            if my_queue in _listeners:
                _listeners.remove(my_queue)



#  DATABASE

def get_db():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='12345678',
        database='foodlink_db'
    )




#  mysql-connector returns TIME columns as timedelta objects.

def fmt_time(val):
    """Convert timedelta or None → '11:30 AM' string."""
    if val is None:
        return ''
    if isinstance(val, timedelta):
        total_seconds = int(val.total_seconds())
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds % 3600) // 60
        period = 'AM' if hours < 12 else 'PM'
        h = hours % 12 or 12
        return f"{h}:{minutes:02d} {period}"
    return str(val)


def fix_listing(row):
    """Convert a listing dict's time fields to strings."""
    if row:
        row['available_from'] = fmt_time(row.get('available_from'))
        row['available_to']   = fmt_time(row.get('available_to'))
    return row


#  SSE STREAM ENDPOINT

@app.route('/stream')
def stream():
    return Response(
        sse_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


#  LANDING PAGE
@app.route('/')
def index():
    return render_template('index.html')


#  SEEKER ROUTES
@app.route('/seeker/login', methods=['GET', 'POST'])
def seeker_login():
    if request.method == 'POST':
        phone = request.form['phone']
        city  = request.form.get('city', '')
        lang  = request.form.get('language', 'en')
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM seekers WHERE phone=%s", (phone,))
        user = cursor.fetchone()
        if not user:
            cursor.execute(
                "INSERT INTO seekers (phone, city, language) VALUES (%s,%s,%s)",
                (phone, city, lang)
            )
            db.commit()
        session['seeker_phone'] = phone
        session['seeker_city']  = city
        db.close()
        return redirect('/seeker/dashboard')
    return render_template('seeker/login.html')

@app.route('/ai/translate', methods=['POST'])
def ai_translate():
    data = request.json
    text = data.get("text")
    lang = data.get("lang")

    translated = translate_text(text, lang)

    return jsonify({"translated": translated})

@app.route('/ai/interpret', methods=['POST'])
def ai_interpret():

    data = request.json
    query = data.get("query")

    prompt = f"""
    Convert the following voice sentence into simple food search keywords.

    Examples:
    "I want free food" -> free meal
    "cheap food nearby" -> discount
    "government ration shop" -> ration

    Sentence: {query}

    Return only 2 or 3 keywords.
    """

    response = ollama.chat(
        model='gemma:2b',
        messages=[{"role": "user", "content": prompt}]
    )

    keywords = response['message']['content']

    return jsonify({"keywords": keywords})


@app.route('/seeker/dashboard')
def seeker_dashboard():
    if 'seeker_phone' not in session:
        return redirect('/seeker/login')
    db = get_db()
    cursor = db.cursor(dictionary=True)

   
    cursor.execute("""
        SELECT f.*, n.name AS ngo_name
        FROM food_listings f
        JOIN ngos n ON f.ngo_id = n.id
        WHERE f.is_active = 1
        ORDER BY f.id DESC
    """)
    rows = cursor.fetchall()
    db.close()

    
    listings = [fix_listing(row) for row in rows]

    return render_template('seeker/dashboard.html', listings=listings)


@app.route('/api/listings')
def api_listings():
    """JSON endpoint — called by seeker JS as fallback."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT f.id, f.title, f.food_type, f.quantity,
               f.available_from, f.available_to,
               f.address, f.date, n.name AS ngo_name
        FROM food_listings f
        JOIN ngos n ON f.ngo_id = n.id
        WHERE f.is_active = 1
        ORDER BY f.id DESC
    """)
    rows = cursor.fetchall()
    db.close()
    result = []
    for row in rows:
        row['available_from'] = fmt_time(row.get('available_from'))
        row['available_to']   = fmt_time(row.get('available_to'))
        if row.get('date'):
            row['date'] = str(row['date'])
        result.append(row)
    return jsonify(result)


#  NGO ROUTES
@app.route('/ngo/login', methods=['GET', 'POST'])
def ngo_login():
    if request.method == 'POST':
        email    = request.form['email']
        password = request.form['password']
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM ngos WHERE email=%s", (email,))
        ngo = cursor.fetchone()
        db.close()
        if ngo and check_password_hash(ngo['password'], password):
            session['ngo_id']       = ngo['id']
            session['ngo_name']     = ngo['name']
            session['ngo_verified'] = bool(ngo['is_verified'])
            return redirect('/ngo/dashboard')
        return render_template('ngo/login.html', error='Invalid email or password')
    return render_template('ngo/login.html')


@app.route('/ngo/register', methods=['GET', 'POST'])
def ngo_register():
    if request.method == 'POST':
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO ngos (name, email, password, phone, city, address)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            request.form['name'],
            request.form['email'],
            generate_password_hash(request.form['password']),
            request.form['phone'],
            request.form.get('city', ''),
            request.form.get('address', '')
        ))
        db.commit()
        db.close()
        return redirect('/ngo/login')
    return render_template('ngo/login.html')


@app.route('/ngo/dashboard')
def ngo_dashboard():
    if 'ngo_id' not in session:
        return redirect('/ngo/login')
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM food_listings WHERE ngo_id=%s ORDER BY id DESC",
        (session['ngo_id'],)
    )
    rows = cursor.fetchall()
    db.close()

    # Fix timedelta TIME fields
    listings = [fix_listing(row) for row in rows]
    return render_template('ngo/dashboard.html', listings=listings)


@app.route('/ngo/post-food', methods=['POST'])
def post_food():
    if 'ngo_id' not in session:
        return redirect('/ngo/login')

   

    title       = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    food_type   = request.form.get('food_type', 'free_meal')
    quantity    = request.form.get('quantity', '').strip()
    from_time   = request.form.get('available_from', '')
    to_time     = request.form.get('available_to', '')
    date_val    = request.form.get('date', '')
    address     = request.form.get('address', '').strip()

    if not title or not address:
        return redirect('/ngo/dashboard')

    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO food_listings
          (ngo_id, title, description, food_type, quantity,
           available_from, available_to, date, address, is_active)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, 1)
    """, (
        session['ngo_id'], title, description, food_type,
        quantity, from_time, to_time, date_val, address
    ))
    db.commit()
    new_id = cursor.lastrowid
    db.close()

    # ── Broadcast to ALL open dashboards instantly 
    broadcast_event('new_food', {
        'id':        new_id,
        'title':     title,
        'food_type': food_type,
        'quantity':  quantity,
        'from_time': from_time,
        'to_time':   to_time,
        'address':   address,
        'ngo_name':  session.get('ngo_name', 'NGO'),
        'date':      date_val,
    })

    return redirect('/ngo/dashboard')


@app.route('/ngo/toggle/<int:listing_id>')
def toggle_listing(listing_id):
    if 'ngo_id' not in session:
        return redirect('/ngo/login')
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(
        "SELECT is_active FROM food_listings WHERE id=%s AND ngo_id=%s",
        (listing_id, session['ngo_id'])
    )
    row = cursor.fetchone()
    if row:
        new_status = 0 if row['is_active'] else 1
        cursor.execute(
            "UPDATE food_listings SET is_active=%s WHERE id=%s",
            (new_status, listing_id)
        )
        db.commit()
        broadcast_event('listing_toggled', {
            'id':       listing_id,
            'is_active': bool(new_status),
            'ngo_name': session.get('ngo_name', '')
        })
    db.close()
    return redirect('/ngo/dashboard')


#  ADMIN ROUTES

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'admin123':
            session['admin'] = True
            return redirect('/admin/dashboard')
        return render_template('admin/login.html', error='Wrong credentials')
    return render_template('admin/login.html')


@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'):
        return redirect('/admin/login')
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM ngos WHERE is_verified=0 ORDER BY id DESC")
    pending = cursor.fetchall()

    cursor.execute("SELECT * FROM ngos WHERE is_verified=1 ORDER BY name")
    verified = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) as count FROM food_listings WHERE is_active=1")
    today_count = cursor.fetchone()

    cursor.execute("""
        SELECT f.*, n.name AS ngo_name
        FROM food_listings f JOIN ngos n ON f.ngo_id = n.id
        WHERE f.is_active = 1
        ORDER BY f.id DESC LIMIT 20
    """)
    rows = cursor.fetchall()
    db.close()

    recent_listings = [fix_listing(row) for row in rows]

    return render_template('admin/dashboard.html',
        pending=pending,
        verified=verified,
        today_count=today_count,
        recent_listings=recent_listings
    )


@app.route('/admin/verify-ngo/<int:ngo_id>')
def verify_ngo(ngo_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT name FROM ngos WHERE id=%s", (ngo_id,))
    ngo = cursor.fetchone()
    cursor.execute("UPDATE ngos SET is_verified=1 WHERE id=%s", (ngo_id,))
    db.commit()
    db.close()
    broadcast_event('ngo_verified', {
        'ngo_id':   ngo_id,
        'ngo_name': ngo['name'] if ngo else ''
    })
    return redirect('/admin/dashboard')


@app.route('/admin/reject-ngo/<int:ngo_id>')
def reject_ngo(ngo_id):
    if not session.get('admin'):
        return redirect('/admin/login')
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM ngos WHERE id=%s AND is_verified=0", (ngo_id,))
    db.commit()
    db.close()
    broadcast_event('ngo_rejected', {'ngo_id': ngo_id})
    return redirect('/admin/dashboard')


@app.route('/admin/stats')
def admin_stats():
    if not session.get('admin'):
        return jsonify({}), 403
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as c FROM ngos WHERE is_verified=0")
    pending = cursor.fetchone()['c']
    cursor.execute("SELECT COUNT(*) as c FROM ngos WHERE is_verified=1")
    verified = cursor.fetchone()['c']
    cursor.execute("SELECT COUNT(*) as c FROM food_listings WHERE is_active=1")
    today = cursor.fetchone()['c']
    cursor.execute("SELECT COUNT(*) as c FROM seekers")
    users = cursor.fetchone()['c']
    db.close()
    return jsonify({'pending': pending, 'verified': verified, 'today': today, 'users': users})


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


if __name__ == '__main__':
    app.run(debug=True, threaded=True)