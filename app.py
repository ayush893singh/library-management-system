import os
import random
import string
import csv
import io
import pytz
import requests as http_requests
from datetime import datetime, timedelta, date, time
from functools import wraps
import webbrowser
import threading
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session, jsonify, Response)
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection, init_db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'lms_dev_fallback_key_2026')

# ── Constants ──────────────────────────────────────────────────────────────
DAILY_FINE_RATE   = 5.0
STANDARD_LOAN_DAYS = 14
NORMAL_BOOK_FEE   = 69.0
EBOOK_FEE         = 49.0
IST               = pytz.timezone('Asia/Kolkata')
FAST2SMS_KEY      = os.environ.get(
    'FAST2SMS_API_KEY',
    'XJ2PWY8V51l69QIfCOMycsRvdDhmAGEUj7w3BTz4FxKZqop0au28OgaU0IqcJHl1GT5xinf6teLKwYou'
)
PER_PAGE          = 9   # catalog items per page
ADMIN_PER_PAGE    = 10  # admin list items per page


# ── IST Helpers ────────────────────────────────────────────────────────────

def now_ist():
    return datetime.now(IST)

def today_ist():
    return datetime.now(IST).date()


# ── Library Status ─────────────────────────────────────────────────────────

def get_library_status():
    conn = get_db_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    s = {r['key']: r['value'] for r in rows}

    open_h, open_m   = map(int, s.get('open_time',  '08:00').split(':'))
    close_h, close_m = map(int, s.get('close_time', '20:00').split(':'))
    notice = s.get('notice', 'Library: 8 AM–8 PM Mon–Sat. Sunday closed. E-Books 24/7!')

    now     = now_ist()
    weekday = now.weekday()
    cur_t   = now.time()
    open_t  = time(open_h, open_m)
    close_t = time(close_h, close_m)

    if weekday == 6:
        is_open, badge_text, badge_color = False, "CLOSED (Sunday Weekly Off)", "red"
        timing_info = "Opens Monday 8:00 AM"
    elif open_t <= cur_t <= close_t:
        is_open, badge_text, badge_color = True, "OPEN NOW (8 AM – 8 PM)", "emerald"
        timing_info = "Closes today at 8:00 PM"
    else:
        is_open, badge_text, badge_color = False, "CLOSED FOR THE DAY", "rose"
        timing_info = "Opens tomorrow 8:00 AM"

    return dict(is_open=is_open, badge_text=badge_text, badge_color=badge_color,
                timing_info=timing_info, notice=notice,
                working_hours="8:00 AM – 8:00 PM (Mon–Sat)",
                current_date=now.strftime("%A, %d %B %Y"),
                current_time=now.strftime("%I:%M %p"))


@app.context_processor
def inject_globals():
    status = get_library_status()
    user_info = None
    unread_notifs = 0
    if 'user_id' in session:
        user_info = {
            'id': session['user_id'], 'username': session.get('username'),
            'name': session.get('name'),  'role': session.get('role')
        }
        if session.get('role') == 'student':
            conn = get_db_connection()
            unread_notifs = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                (session['user_id'],)
            ).fetchone()
            unread_notifs = list(unread_notifs.values())[0] if unread_notifs else 0
            conn.close()
    return dict(library_status=status, current_user=user_info,
                unread_notifications=unread_notifs)


# ── Loan / Fine Helpers ────────────────────────────────────────────────────

def calculate_due_date(loan_days=STANDARD_LOAN_DAYS, loan_type='normal'):
    due = today_ist() + timedelta(days=loan_days)
    if loan_type == 'normal' and due.weekday() == 6:
        due += timedelta(days=1)
    return due


def get_fine(due_date_str, return_date_str=None):
    due = datetime.strptime(due_date_str, "%Y-%m-%d").date()
    ref = (datetime.strptime(return_date_str, "%Y-%m-%d").date()
           if return_date_str else today_ist())
    if ref > due:
        days_late = (ref - due).days
        return days_late * DAILY_FINE_RATE, days_late
    return 0.0, 0


# ── Notification Helper ────────────────────────────────────────────────────

def create_notification(user_id, message, notif_type='info'):
    try:
        conn = get_db_connection()
        conn.execute("INSERT INTO notifications (user_id,message,notif_type) VALUES (?,?,?)",
                     (user_id, message, notif_type))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Auth Decorators ────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash("Admin access required!", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def staff_required(f):
    """Admin OR Librarian."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') not in ('admin', 'librarian'):
            flash("Staff access required!", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def student_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'student':
            flash("Student access required.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ═══════════════════════════════════════════════════════════════════════════
# AUTHENTICATION
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if 'user_id' in session:
        role = session.get('role')
        if role == 'student':
            return redirect(url_for('student_dashboard'))
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('login'))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            flash("Username aur Password dono chahiye!", "danger")
            return render_template("login.html")

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session.update({
                'user_id': user['id'], 'username': user['username'],
                'name': user['name'],  'role': user['role']
            })
            flash(f"Welcome back, {user['name']}! 👋", "success")
            if user['role'] == 'student':
                return redirect(url_for('student_dashboard'))
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Galat Username ya Password. Dobara try karein.", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        phone    = request.form.get("phone", "").strip()
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not name or not username or not password:
            flash("Name, Student ID, aur Password zaroori hain!", "danger")
            return render_template("login.html", default_section="register")

        conn = get_db_connection()
        existing = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            conn.close()
            flash(f"Student ID '{username}' pehle se maujood hai. Kripya doosra ID chunein.", "danger")
            return render_template("login.html", default_section="register")

        try:
            conn.execute("""INSERT INTO users (username,name,password_hash,role,phone,email)
                            VALUES (?,?,?,'student',?,?)""",
                         (username, name, generate_password_hash(password), phone or None, email or None))
            conn.commit()
            flash(f"Aapka account safaltapoorvak ban gaya! Ab Student ID '{username}' se login karein.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            flash(f"Account banane mein samasya aayi: {e}", "danger")
            return render_template("login.html", default_section="register")
        finally:
            conn.close()

    return render_template("login.html", default_section="register")


@app.route("/logout")
def logout():
    session.clear()
    flash("Aap logout ho gaye hain.", "info")
    return redirect(url_for('login'))


# ── OTP Login (Fast2SMS) ───────────────────────────────────────────────────

@app.route("/send-otp", methods=["POST"])
def send_otp():
    phone = request.form.get("phone", "").strip()
    digits = ''.join(filter(str.isdigit, phone))[-10:]

    if len(digits) < 10:
        flash("Valid 10-digit phone number chahiye!", "danger")
        return redirect(url_for('login'))

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE phone LIKE ?", (f"%{digits}%",)).fetchone()

    if not user:
        conn.close()
        flash("Is phone number par koi account nahi mila. Pehle register karein.", "danger")
        return redirect(url_for('login'))

    otp_code = ''.join(random.choices(string.digits, k=6))

    # Save OTP to DB
    conn.execute("INSERT INTO otp_sessions (phone,otp_code,user_id) VALUES (?,?,?)",
                 (digits, otp_code, user['id']))
    conn.commit()
    conn.close()

    # Try Fast2SMS
    sms_sent = False
    try:
        resp = http_requests.post(
            "https://www.fast2sms.com/dev/bulkV2",
            data=f"variables_values={otp_code}&route=otp&numbers={digits}",
            headers={
                'authorization': FAST2SMS_KEY,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Cache-Control': 'no-cache'
            },
            timeout=8
        )
        result = resp.json()
        sms_sent = result.get('return') is True
    except Exception as e:
        print(f"Fast2SMS error: {e}")

    session['otp_phone']   = digits
    session['demo_otp']    = otp_code
    session['otp_user_id'] = user['id']
    session['sms_sent']    = sms_sent

    if sms_sent:
        flash(f"OTP aapke phone {digits[:2]}XXXXXXXX{digits[-2:]} par bheja gaya! ✅", "success")
    else:
        flash("SMS bhejne mein samasya. Screen par OTP dekh karein (demo mode).", "warning")

    return redirect(url_for('verify_otp'))


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    if 'otp_phone' not in session:
        flash("Pehle phone number daalein.", "warning")
        return redirect(url_for('login'))

    if request.method == "POST":
        entered = request.form.get("otp_code", "").strip()
        if entered == session.get('demo_otp'):
            conn = get_db_connection()
            user = conn.execute("SELECT * FROM users WHERE id=?",
                                (session['otp_user_id'],)).fetchone()
            conn.close()
            if user:
                for k in ('otp_phone', 'demo_otp', 'otp_user_id', 'sms_sent'):
                    session.pop(k, None)
                session.update({'user_id': user['id'], 'username': user['username'],
                                'name': user['name'], 'role': user['role']})
                flash(f"OTP verified! Welcome, {user['name']} ✅", "success")
                if user['role'] == 'student':
                    return redirect(url_for('student_dashboard'))
                return redirect(url_for('admin_dashboard'))
        else:
            flash("Galat OTP! Dobara try karein.", "danger")

    return render_template("verify_otp.html",
                           phone=session.get('otp_phone', ''),
                           sms_sent=session.get('sms_sent', False))


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    if 'otp_phone' not in session:
        return redirect(url_for('login'))
    new_otp = ''.join(random.choices(string.digits, k=6))
    conn = get_db_connection()
    conn.execute("INSERT INTO otp_sessions (phone,otp_code,user_id) VALUES (?,?,?)",
                 (session['otp_phone'], new_otp, session.get('otp_user_id')))
    conn.commit()
    conn.close()

    sms_sent = False
    try:
        resp = http_requests.post(
            "https://www.fast2sms.com/dev/bulkV2",
            data=f"variables_values={new_otp}&route=otp&numbers={session['otp_phone']}",
            headers={'authorization': FAST2SMS_KEY,
                     'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=8)
        sms_sent = resp.json().get('return') is True
    except Exception:
        pass

    session['demo_otp'] = new_otp
    session['sms_sent'] = sms_sent
    flash("Naya OTP generate hua! 🔄", "info")
    return redirect(url_for('verify_otp'))


# ═══════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/student/notifications")
@student_required
def student_notifications():
    user_id = session['user_id']
    conn = get_db_connection()
    notifs = conn.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    return render_template("student_notifications.html", notifications=notifs)


@app.route("/student/notifications/clear", methods=["POST"])
@student_required
def clear_notifications():
    conn = get_db_connection()
    conn.execute("DELETE FROM notifications WHERE user_id=?", (session['user_id'],))
    conn.commit()
    conn.close()
    flash("Sari notifications clear ho gayi!", "info")
    return redirect(url_for('student_notifications'))


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/admin/dashboard")
@staff_required
def admin_dashboard():
    conn = get_db_connection()
    today_str = today_ist().isoformat()

    total_titles    = list(conn.execute("SELECT COUNT(*) FROM books").fetchone().values())[0]
    total_copies    = list(conn.execute("SELECT COALESCE(SUM(total_copies),0) FROM books").fetchone().values())[0]
    avail_copies    = list(conn.execute("SELECT COALESCE(SUM(available_copies),0) FROM books").fetchone().values())[0]
    total_students  = list(conn.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone().values())[0]
    active_loans    = list(conn.execute("SELECT COUNT(*) FROM transactions WHERE status='Issued'").fetchone().values())[0]
    overdue_loans   = list(conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE status='Issued' AND due_date<?", (today_str,)
    ).fetchone().values())[0]
    total_fees      = list(conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments").fetchone().values())[0]
    total_fine_collected = list(conn.execute("""
        SELECT COALESCE(SUM(fine_amount), 0.0) FROM transactions 
        WHERE fine_status = 'paid' OR (status = 'Returned' AND fine_status != 'waived')
    """).fetchone().values())[0]
    pending_pickups_count = list(conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE status='Reserved'"
    ).fetchone().values())[0]

    pending_pickups = conn.execute("""
        SELECT t.id, t.issue_date, t.due_date, t.loan_type, t.fee_paid, t.status,
               b.id AS book_id, b.title AS book_title, b.shelf_location,
               u.id AS student_id, u.name AS student_name, u.username AS student_roll, u.phone AS student_phone
        FROM transactions t
        JOIN books b ON t.book_id=b.id
        JOIN users u ON t.user_id=u.id
        WHERE t.status='Reserved'
        ORDER BY t.id DESC
    """).fetchall()

    recent_loans_raw = conn.execute("""
        SELECT t.id, t.issue_date, t.due_date, t.return_date, t.loan_type,
               t.fee_paid, t.fine_amount, t.fine_status, t.status,
               b.title AS book_title, b.language,
               u.name AS student_name, u.username AS student_id, u.phone AS student_phone
        FROM transactions t
        JOIN books b ON t.book_id=b.id
        JOIN users u ON t.user_id=u.id
        ORDER BY t.id DESC LIMIT 8
    """).fetchall()

    recent_loans = []
    for row in recent_loans_raw:
        item = dict(row)
        if item['status'] == 'Issued':
            fine, days_late = get_fine(item['due_date'])
            item['pending_fine'] = fine if item['fine_status'] != 'waived' else 0.0
            item['days_late']    = days_late
            item['is_overdue']   = days_late > 0 and item['fine_status'] != 'waived'
        else:
            item.update(pending_fine=0.0, days_late=0, is_overdue=False)
        recent_loans.append(item)

    avail_books    = conn.execute("SELECT id,title,available_copies,language FROM books WHERE available_copies>0 ORDER BY title").fetchall()
    students_list  = conn.execute("SELECT id,username,name FROM users WHERE role='student' ORDER BY name").fetchall()
    conn.close()

    return render_template("admin_dashboard.html",
        total_titles=total_titles, total_copies=total_copies,
        available_copies=avail_copies, total_students=total_students,
        active_loans=active_loans, overdue_loans=overdue_loans,
        total_fees_collected=total_fees, total_fine_collected=total_fine_collected,
        pending_pickups_count=pending_pickups_count,
        pending_pickups=pending_pickups, recent_loans=recent_loans,
        available_books=avail_books, students_list=students_list
    )


@app.route("/admin/update-notice", methods=["POST"])
@staff_required
def update_notice():
    notice = request.form.get("notice", "").strip()
    if notice:
        conn = get_db_connection()
        conn.execute("UPDATE settings SET value=? WHERE key='notice'", (notice,))
        conn.commit()
        conn.close()
        flash("Notice board update ho gaya!", "success")
    return redirect(url_for('admin_dashboard'))


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN: BOOKS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/admin/books")
@staff_required
def admin_books():
    q        = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    language = request.args.get("language", "").strip()
    page     = max(1, int(request.args.get("page", 1)))

    conn = get_db_connection()
    sql, params = "SELECT * FROM books WHERE 1=1", []
    if q:
        sql += " AND (title LIKE ? OR author LIKE ? OR isbn LIKE ?)"
        params += [f"%{q}%"] * 3
    if category:
        sql += " AND category=?";  params.append(category)
    if language:
        sql += " AND language=?";  params.append(language)

    count_sql = sql.replace("SELECT *", "SELECT COUNT(*)")
    total = list(conn.execute(count_sql, params).fetchone().values())[0]
    total_pages = max(1, (total + ADMIN_PER_PAGE - 1) // ADMIN_PER_PAGE)
    page = min(page, total_pages)

    sql += f" ORDER BY id DESC LIMIT {ADMIN_PER_PAGE} OFFSET {(page-1)*ADMIN_PER_PAGE}"
    books = conn.execute(sql, params).fetchall()
    categories = [r['category'] for r in conn.execute(
        "SELECT DISTINCT category FROM books WHERE category IS NOT NULL").fetchall()]
    conn.close()

    return render_template("books.html", books=books, query=q,
                           selected_category=category, selected_language=language,
                           categories=categories, page=page, total_pages=total_pages)


@app.route("/admin/books/add", methods=["POST"])
@staff_required
def admin_add_book():
    title    = request.form.get("title", "").strip()
    author   = request.form.get("author", "").strip()
    isbn     = request.form.get("isbn", "").strip()
    category = request.form.get("category", "Motivation").strip()
    language = request.form.get("language", "English").strip()
    shelf    = request.form.get("shelf_location", "Shelf A1").strip()
    content  = request.form.get("content", "").strip()
    cover    = request.form.get("cover_url", "").strip()
    try:
        copies = max(1, int(request.form.get("total_copies", 1)))
    except ValueError:
        copies = 1

    if not title or not author:
        flash("Title aur Author required hain!", "danger")
        return redirect(url_for('admin_books'))

    conn = get_db_connection()
    try:
        conn.execute("""INSERT INTO books
            (title,author,isbn,category,language,shelf_location,total_copies,available_copies,
             normal_price,ebook_price,content,cover_url)
            VALUES (?,?,?,?,?,?,?,?,69.0,49.0,?,?)""",
            (title, author, isbn or None, category, language, shelf, copies, copies, content, cover or None))
        conn.commit()
        flash(f"Book '{title}' catalog mein add ho gayi!", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('admin_books'))


@app.route("/admin/books/edit/<int:book_id>", methods=["POST"])
@staff_required
def admin_edit_book(book_id):
    title    = request.form.get("title", "").strip()
    author   = request.form.get("author", "").strip()
    isbn     = request.form.get("isbn", "").strip()
    category = request.form.get("category", "").strip()
    language = request.form.get("language", "English").strip()
    shelf    = request.form.get("shelf_location", "").strip()
    content  = request.form.get("content", "").strip()
    cover    = request.form.get("cover_url", "").strip()
    try:
        new_total = int(request.form.get("total_copies", 1))
    except ValueError:
        flash("Invalid copies count", "danger")
        return redirect(url_for('admin_books'))

    conn = get_db_connection()
    book = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not book:
        conn.close(); flash("Book nahi mili!", "danger")
        return redirect(url_for('admin_books'))

    issued = book['total_copies'] - book['available_copies']
    if new_total < issued:
        conn.close()
        flash(f"Currently {issued} copies issued hain. Itna kam nahi kar sakte!", "danger")
        return redirect(url_for('admin_books'))

    try:
        conn.execute("""UPDATE books SET title=?,author=?,isbn=?,category=?,language=?,
            shelf_location=?,total_copies=?,available_copies=?,content=?,cover_url=? WHERE id=?""",
            (title, author, isbn or None, category, language, shelf,
             new_total, new_total - issued, content or book['content'], cover or book.get('cover_url'), book_id))
        conn.commit()
        flash("Book details update ho gayi!", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('admin_books'))


@app.route("/admin/books/delete/<int:book_id>", methods=["POST"])
@admin_required
def admin_delete_book(book_id):
    conn = get_db_connection()
    active = list(conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE book_id=? AND status='Issued'", (book_id,)
    ).fetchone().values())[0]
    if active > 0:
        conn.close()
        flash(f"{active} copy abhi issued hai. Delete nahi ho sakti!", "danger")
        return redirect(url_for('admin_books'))
    try:
        conn.execute("DELETE FROM reservations WHERE book_id=?", (book_id,))
        conn.execute("DELETE FROM ratings WHERE book_id=?", (book_id,))
        conn.execute("DELETE FROM transactions WHERE book_id=?", (book_id,))
        conn.execute("DELETE FROM books WHERE id=?", (book_id,))
        conn.commit()
        flash("Book catalog se hata di gayi!", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('admin_books'))


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN: STUDENTS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/admin/students")
@staff_required
def admin_students():
    q    = request.args.get("q", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    conn = get_db_connection()

    sql = """SELECT u.*,
        (SELECT COUNT(*) FROM transactions WHERE user_id=u.id AND status='Issued') AS active_books,
        (SELECT COUNT(*) FROM transactions WHERE user_id=u.id) AS total_borrowed
        FROM users u WHERE u.role='student'"""
    params = []
    if q:
        sql += " AND (u.name LIKE ? OR u.username LIKE ? OR u.phone LIKE ?)"; params += [f"%{q}%"] * 3

    count_sql = f"SELECT COUNT(*) FROM ({sql}) x"
    total = list(conn.execute(count_sql, params).fetchone().values())[0]
    total_pages = max(1, (total + ADMIN_PER_PAGE - 1) // ADMIN_PER_PAGE)
    page = min(page, total_pages)

    sql += f" ORDER BY u.id DESC LIMIT {ADMIN_PER_PAGE} OFFSET {(page-1)*ADMIN_PER_PAGE}"
    students = conn.execute(sql, params).fetchall()
    conn.close()
    return render_template("students.html", students=students, query=q, page=page, total_pages=total_pages)


@app.route("/admin/students/edit/<int:user_id>", methods=["POST"])
@staff_required
def admin_edit_student(user_id):
    name     = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    phone    = request.form.get("phone", "").strip()
    password = request.form.get("password", "").strip()

    if not name or not username:
        flash("Name aur ID required hain!", "danger")
        return redirect(url_for('admin_students'))

    conn = get_db_connection()
    try:
        if password:
            conn.execute("UPDATE users SET name=?,username=?,phone=?,password_hash=? WHERE id=? AND role='student'",
                         (name, username, phone, generate_password_hash(password), user_id))
        else:
            conn.execute("UPDATE users SET name=?,username=?,phone=? WHERE id=? AND role='student'",
                         (name, username, phone, user_id))
        conn.commit()
        flash(f"Student '{name}' update ho gaya!", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('admin_students'))


@app.route("/admin/students/<int:user_id>/history")
@staff_required
def student_history_api(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT id,name,username,phone FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close(); return jsonify({"error": "Not found"}), 404
    loans = conn.execute("""SELECT t.*,b.title AS book_title,b.language FROM transactions t
                            JOIN books b ON t.book_id=b.id WHERE t.user_id=? ORDER BY t.id DESC""",
                         (user_id,)).fetchall()
    conn.close()
    return jsonify({"student": dict(user), "history": [dict(r) for r in loans]})


@app.route("/admin/students/delete/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_student(user_id):
    conn = get_db_connection()
    active = list(conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id=? AND status='Issued'", (user_id,)
    ).fetchone().values())[0]
    if active > 0:
        conn.close(); flash("Student ke paas active books hain. Delete nahi ho sakta!", "danger")
        return redirect(url_for('admin_students'))
    try:
        conn.execute("DELETE FROM payments WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM notifications WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM reservations WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM ratings WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM transactions WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
        flash("Student account delete ho gaya!", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('admin_students'))


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN: TRANSACTIONS / CIRCULATION
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/admin/transactions")
@staff_required
def admin_transactions():
    status_filter = request.args.get("status", "all")
    page          = max(1, int(request.args.get("page", 1)))
    conn          = get_db_connection()
    today_str     = today_ist().isoformat()

    sql = """SELECT t.id, t.issue_date, t.due_date, t.return_date, t.loan_type,
                    t.fee_paid, t.fine_amount, t.fine_status, t.status,
                    b.id AS book_id, b.title AS book_title, b.isbn, b.author, b.shelf_location, b.language,
                    u.id AS student_id, u.name AS student_name, u.username AS student_roll, u.phone AS student_phone
             FROM transactions t
             JOIN books b ON t.book_id=b.id
             JOIN users u ON t.user_id=u.id WHERE 1=1"""
    params = []

    if status_filter == "Issued":
        sql += " AND t.status='Issued'"
    elif status_filter == "Reserved":
        sql += " AND t.status='Reserved'"
    elif status_filter == "Overdue":
        sql += " AND t.status='Issued' AND t.due_date<? AND t.fine_status!='waived'"; params.append(today_str)
    elif status_filter == "Returned":
        sql += " AND t.status='Returned'"

    count_sql = f"SELECT COUNT(*) FROM ({sql}) x"
    total = list(conn.execute(count_sql, params).fetchone().values())[0]
    total_pages = max(1, (total + ADMIN_PER_PAGE - 1) // ADMIN_PER_PAGE)
    page = min(page, total_pages)

    sql += f" ORDER BY t.id DESC LIMIT {ADMIN_PER_PAGE} OFFSET {(page-1)*ADMIN_PER_PAGE}"
    rows = conn.execute(sql, params).fetchall()

    transactions_data = []
    for row in rows:
        item = dict(row)
        if item['status'] == 'Issued':
            fine, days_late = get_fine(item['due_date'])
            item['current_fine'] = fine if item['fine_status'] != 'waived' else 0.0
            item['days_late']    = days_late
            item['is_overdue']   = days_late > 0 and item['fine_status'] != 'waived'
        else:
            item.update(current_fine=item['fine_amount'], days_late=0, is_overdue=False)
        transactions_data.append(item)

    avail_books   = conn.execute("SELECT id,title,available_copies,language FROM books WHERE available_copies>0 ORDER BY title").fetchall()
    students_list = conn.execute("SELECT id,username,name FROM users WHERE role='student' ORDER BY name").fetchall()
    conn.close()

    return render_template("transactions.html",
        transactions=transactions_data, status_filter=status_filter,
        available_books=avail_books, students_list=students_list,
        daily_fine_rate=DAILY_FINE_RATE, page=page, total_pages=total_pages)


@app.route("/admin/issue", methods=["POST"])
@staff_required
def admin_issue_book():
    try:
        book_id   = int(request.form.get("book_id"))
        user_id   = int(request.form.get("user_id"))
        loan_type = request.form.get("loan_type", "normal")
        loan_days = int(request.form.get("loan_days", STANDARD_LOAN_DAYS))
    except (ValueError, TypeError):
        flash("Invalid selection!", "danger")
        return redirect(url_for('admin_transactions'))

    conn = get_db_connection()
    book    = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    student = conn.execute("SELECT * FROM users WHERE id=? AND role='student'", (user_id,)).fetchone()

    if not book or not student:
        conn.close(); flash("Book ya student nahi mila!", "danger")
        return redirect(url_for('admin_transactions'))

    if loan_type == 'normal' and book['available_copies'] <= 0:
        conn.close(); flash(f"'{book['title']}' ke physical copies khatam hain!", "danger")
        return redirect(url_for('admin_transactions'))

    issue_date = today_ist()
    due_date   = calculate_due_date(loan_days, loan_type)
    fee        = EBOOK_FEE if loan_type == 'ebook' else NORMAL_BOOK_FEE

    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO transactions (book_id,user_id,issue_date,due_date,loan_type,fee_paid,status)
                       VALUES (?,?,?,?,?,?,'Issued')""",
                    (book_id, user_id, issue_date.isoformat(), due_date.isoformat(), loan_type, fee))
        trans_id = cur.lastrowid
        cur.execute("""INSERT INTO payments (user_id,transaction_id,amount,payment_type,payment_method)
                       VALUES (?,?,?,'borrow_fee','Library Desk')""",
                    (user_id, trans_id, fee))
        if loan_type == 'normal':
            cur.execute("UPDATE books SET available_copies=available_copies-1 WHERE id=?", (book_id,))
        conn.commit()
        create_notification(user_id, f"📚 '{book['title']}' issue ho gayi. Due date: {due_date.strftime('%d %b %Y')}", "success")
        flash(f"'{book['title']}' issued to {student['name']}! Due: {due_date.strftime('%d %b %Y')}", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('admin_transactions'))


@app.route("/admin/return/<int:trans_id>", methods=["POST"])
@staff_required
def admin_return_book(trans_id):
    conn = get_db_connection()
    trans = conn.execute("""SELECT t.*,b.title AS book_title,u.name AS student_name,u.id AS uid
                            FROM transactions t JOIN books b ON t.book_id=b.id
                            JOIN users u ON t.user_id=u.id
                            WHERE t.id=? AND t.status='Issued'""", (trans_id,)).fetchone()
    if not trans:
        conn.close(); flash("Transaction nahi mila ya already return ho gayi!", "danger")
        return redirect(url_for('admin_transactions'))

    today     = today_ist()
    fine, dl  = get_fine(trans['due_date'], today.isoformat())
    final_fine = 0.0 if trans['fine_status'] == 'waived' else fine
    fine_status = 'waived' if trans['fine_status'] == 'waived' else ('paid' if final_fine > 0 else 'none')

    try:
        conn.execute("""UPDATE transactions SET return_date=?,fine_amount=?,fine_status=?,status='Returned'
                        WHERE id=?""", (today.isoformat(), final_fine, fine_status, trans_id))
        if final_fine > 0:
            conn.execute("""INSERT INTO payments (user_id,transaction_id,amount,payment_type,payment_method)
                            VALUES (?,?,?,'fine_payment','Desk Cash')""",
                         (trans['user_id'], trans_id, final_fine))
        if trans['loan_type'] == 'normal':
            conn.execute("UPDATE books SET available_copies=available_copies+1 WHERE id=?", (trans['book_id'],))

        # Check waiting list
        next_res = conn.execute("""SELECT r.*,u.name AS uname FROM reservations r
                                   JOIN users u ON r.user_id=u.id
                                   WHERE r.book_id=? AND r.status='waiting' ORDER BY r.reserved_at ASC LIMIT 1""",
                                (trans['book_id'],)).fetchone()
        if next_res:
            conn.execute("UPDATE reservations SET status='fulfilled',notified=1 WHERE id=?", (next_res['id'],))
            create_notification(next_res['user_id'],
                                f"🎉 '{trans['book_title']}' ab available hai! Jaldi catalog se issue karein.", "success")

        conn.commit()
        msg = f"'{trans['book_title']}' returned"
        if final_fine > 0:
            msg += f". Fine collected: ₹{final_fine:.2f}"
        flash(msg, "success" if final_fine == 0 else "warning")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('admin_transactions'))


@app.route("/admin/waive-fine/<int:trans_id>", methods=["POST"])
@staff_required
def admin_waive_fine(trans_id):
    conn  = get_db_connection()
    trans = conn.execute("""SELECT t.*,b.title AS book_title,u.name AS student_name
                            FROM transactions t JOIN books b ON t.book_id=b.id
                            JOIN users u ON t.user_id=u.id WHERE t.id=?""", (trans_id,)).fetchone()
    if not trans:
        conn.close(); flash("Transaction nahi mila!", "danger")
        return redirect(url_for('admin_transactions'))

    try:
        new_due = (today_ist() + timedelta(days=7)).isoformat() \
            if datetime.strptime(trans['due_date'], "%Y-%m-%d").date() < today_ist() else trans['due_date']
        conn.execute("UPDATE transactions SET fine_amount=0.0,fine_status='waived',due_date=? WHERE id=?",
                     (new_due, trans_id))
        conn.commit()
        flash(f"Fine maaf! '{trans['book_title']}' ka fine waived.", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('admin_transactions'))


@app.route("/admin/handover/<int:trans_id>", methods=["POST"])
@staff_required
def admin_handover_book(trans_id):
    conn  = get_db_connection()
    trans = conn.execute("""SELECT t.*,b.title AS book_title,u.name AS student_name,u.username AS student_roll
                            FROM transactions t JOIN books b ON t.book_id=b.id
                            JOIN users u ON t.user_id=u.id
                            WHERE t.id=? AND t.status='Reserved'""", (trans_id,)).fetchone()
    if not trans:
        conn.close(); flash("Reservation nahi mila!", "danger")
        return redirect(url_for('admin_transactions'))

    today       = today_ist()
    new_due     = calculate_due_date(STANDARD_LOAN_DAYS, 'normal')
    try:
        conn.execute("UPDATE transactions SET status='Issued',issue_date=?,due_date=? WHERE id=?",
                     (today.isoformat(), new_due.isoformat(), trans_id))
        conn.commit()
        create_notification(trans['user_id'],
            f"✅ '{trans['book_title']}' aapko hand over ho gayi! Due: {new_due.strftime('%d %b %Y')}", "success")
        flash(f"Handover confirmed! '{trans['book_title']}' → {trans['student_name']}. Due: {new_due.strftime('%d %b %Y')}", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('admin_transactions'))


# ── Export CSV ─────────────────────────────────────────────────────────────

@app.route("/admin/export/csv")
@staff_required
def export_csv():
    conn = get_db_connection()
    rows = conn.execute("""SELECT u.name,u.username,b.title,t.loan_type,t.issue_date,
                                  t.due_date,t.return_date,t.fee_paid,t.fine_amount,t.fine_status,t.status
                           FROM transactions t JOIN users u ON t.user_id=u.id JOIN books b ON t.book_id=b.id
                           ORDER BY t.id DESC""").fetchall()
    conn.close()

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['Student Name','Student ID','Book Title','Type','Issue Date','Due Date',
                'Return Date','Fee','Fine','Fine Status','Status'])
    for r in rows:
        w.writerow([r['name'], r['username'], r['title'], r['loan_type'], r['issue_date'],
                    r['due_date'], r.get('return_date') or '', r['fee_paid'],
                    r['fine_amount'], r['fine_status'], r['status']])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment;filename=library_transactions.csv'})


# ═══════════════════════════════════════════════════════════════════════════
# STUDENT PORTAL
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/student/dashboard")
@student_required
def student_dashboard():
    user_id = session['user_id']
    conn    = get_db_connection()
    today   = today_ist()

    active_raw = conn.execute("""SELECT t.id,t.issue_date,t.due_date,t.loan_type,t.fee_paid,
                                        t.fine_status,t.status,
                                        b.id AS book_id,b.title,b.author,b.shelf_location,b.language,b.category
                                 FROM transactions t JOIN books b ON t.book_id=b.id
                                 WHERE t.user_id=? AND t.status IN ('Issued','Reserved')
                                 ORDER BY t.due_date ASC""", (user_id,)).fetchall()

    active_ebooks, reserved_books, active_physical = [], [], []
    total_pending_fine = 0.0
    active_loans = []

    for row in active_raw:
        item  = dict(row)
        due_d = datetime.strptime(item['due_date'], "%Y-%m-%d").date()
        fine, dl = get_fine(item['due_date'])
        is_waived = item['fine_status'] == 'waived'
        is_paid   = item['fine_status'] == 'paid'

        item['days_left']  = (due_d - today).days
        item['is_overdue'] = dl > 0 and not is_waived and not is_paid and item['status'] == 'Issued'
        item['days_late']  = dl
        item['fine']       = 0.0 if (is_waived or is_paid or item['status'] == 'Reserved') else fine
        item['is_expired'] = today > due_d and item['status'] == 'Issued'

        if not is_waived and not is_paid and item['status'] == 'Issued':
            total_pending_fine += fine

        active_loans.append(item)
        if item['status'] == 'Reserved':
            reserved_books.append(item)
        elif item['loan_type'] == 'ebook':
            active_ebooks.append(item)
        else:
            active_physical.append(item)

    history = conn.execute("""SELECT t.id,t.issue_date,t.due_date,t.return_date,t.loan_type,
                                     t.fee_paid,t.fine_amount,t.fine_status,b.title,b.author,b.language
                              FROM transactions t JOIN books b ON t.book_id=b.id
                              WHERE t.user_id=? AND t.status='Returned' ORDER BY t.id DESC LIMIT 5""",
                           (user_id,)).fetchall()

    payments = conn.execute("""SELECT p.*,t.loan_type,b.title AS book_title
                               FROM payments p
                               LEFT JOIN transactions t ON p.transaction_id=t.id
                               LEFT JOIN books b ON t.book_id=b.id
                               WHERE p.user_id=? ORDER BY p.id DESC""", (user_id,)).fetchall()

    my_ratings = conn.execute("""SELECT r.*,b.title FROM ratings r JOIN books b ON r.book_id=b.id
                                 WHERE r.user_id=? ORDER BY r.created_at DESC""", (user_id,)).fetchall()

    my_waitlist = conn.execute("""SELECT res.*,b.title,b.available_copies
                                  FROM reservations res JOIN books b ON res.book_id=b.id
                                  WHERE res.user_id=? AND res.status='waiting'
                                  ORDER BY res.reserved_at ASC""", (user_id,)).fetchall()

    # Books eligible for rating (returned, not yet rated)
    returned_books = conn.execute("""SELECT DISTINCT b.id,b.title FROM transactions t
                                     JOIN books b ON t.book_id=b.id WHERE t.user_id=? AND t.status='Returned'""",
                                  (user_id,)).fetchall()
    rated_ids = {r['book_id'] for r in my_ratings}
    ratable_books = [b for b in returned_books if b['id'] not in rated_ids]

    conn.close()
    return render_template("student_dashboard.html",
        active_loans=active_loans, active_ebooks=active_ebooks,
        reserved_books=reserved_books, active_physical_loans=active_physical,
        history=history, payments=payments,
        total_pending_fine=total_pending_fine,
        my_ratings=my_ratings, my_waitlist=my_waitlist, ratable_books=ratable_books)


@app.route("/student/catalog")
@student_required
def student_catalog():
    q        = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    language = request.args.get("language", "").strip()
    page     = max(1, int(request.args.get("page", 1)))

    conn = get_db_connection()
    sql, params = "SELECT * FROM books WHERE 1=1", []
    if q:
        sql += " AND (title LIKE ? OR author LIKE ? OR isbn LIKE ?)"; params += [f"%{q}%"] * 3
    if category:
        sql += " AND category=?"; params.append(category)
    if language:
        sql += " AND language=?"; params.append(language)

    count_sql = sql.replace("SELECT *", "SELECT COUNT(*)")
    total = list(conn.execute(count_sql, params).fetchone().values())[0]
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)

    sql += f" ORDER BY id DESC LIMIT {PER_PAGE} OFFSET {(page-1)*PER_PAGE}"
    books = conn.execute(sql, params).fetchall()

    categories = [r['category'] for r in conn.execute(
        "SELECT DISTINCT category FROM books WHERE category IS NOT NULL").fetchall()]

    # Avg ratings per book
    ratings_map = {}
    for r in conn.execute("SELECT book_id, AVG(rating) AS avg_r, COUNT(*) AS cnt FROM ratings GROUP BY book_id").fetchall():
        ratings_map[r['book_id']] = {'avg': round(r['avg_r'], 1), 'cnt': r['cnt']}

    # Waitlist counts
    wait_map = {}
    for r in conn.execute("SELECT book_id, COUNT(*) AS cnt FROM reservations WHERE status='waiting' GROUP BY book_id").fetchall():
        wait_map[r['book_id']] = r['cnt']

    # Student's active/reserved book IDs
    user_active_ids = set()
    for r in conn.execute("SELECT book_id FROM transactions WHERE user_id=? AND status IN ('Issued','Reserved')",
                          (session['user_id'],)).fetchall():
        user_active_ids.add(r['book_id'])

    # Student's waitlist book IDs
    user_wait_ids = set()
    for r in conn.execute("SELECT book_id FROM reservations WHERE user_id=? AND status='waiting'",
                          (session['user_id'],)).fetchall():
        user_wait_ids.add(r['book_id'])

    conn.close()
    return render_template("student_catalog.html",
        books=books, query=q, selected_category=category, selected_language=language,
        categories=categories, normal_fee=NORMAL_BOOK_FEE, ebook_fee=EBOOK_FEE,
        page=page, total_pages=total_pages,
        ratings_map=ratings_map, wait_map=wait_map,
        user_active_ids=user_active_ids, user_wait_ids=user_wait_ids)


@app.route("/student/issue", methods=["POST"])
@student_required
def student_issue_book():
    user_id = session['user_id']
    try:
        book_id   = int(request.form.get("book_id"))
        loan_type = request.form.get("loan_type", "ebook")
    except (ValueError, TypeError):
        flash("Invalid selection!", "danger")
        return redirect(url_for('student_catalog'))

    conn = get_db_connection()
    book = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not book:
        conn.close(); flash("Book nahi mili!", "danger")
        return redirect(url_for('student_catalog'))

    # Validate: no duplicate active
    existing = list(conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id=? AND book_id=? AND status IN ('Issued','Reserved')",
        (user_id, book_id)
    ).fetchone().values())[0]
    if existing > 0:
        conn.close(); flash(f"Aapke paas '{book['title']}' already active/reserved hai!", "warning")
        return redirect(url_for('student_dashboard'))

    # Validate stock for normal book
    if loan_type == 'normal' and book['available_copies'] <= 0:
        conn.close(); flash(f"Physical copies khatam hain. E-Book try karein ya Waiting List join karein.", "danger")
        return redirect(url_for('student_catalog'))

    # Validate ebook has content
    if loan_type == 'ebook' and not book.get('content'):
        conn.close(); flash("Is book ka E-Book version available nahi hai.", "warning")
        return redirect(url_for('student_catalog'))

    issue_date = today_ist()
    due_date   = calculate_due_date(STANDARD_LOAN_DAYS, loan_type)
    fee        = EBOOK_FEE if loan_type == 'ebook' else NORMAL_BOOK_FEE
    status     = 'Issued' if loan_type == 'ebook' else 'Reserved'
    utr        = request.form.get("utr_ref", "").strip() or f"UPI-{now_ist().strftime('%M%S%f')[:6]}"

    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO transactions (book_id,user_id,issue_date,due_date,loan_type,fee_paid,status)
                       VALUES (?,?,?,?,?,?,?)""",
                    (book_id, user_id, issue_date.isoformat(), due_date.isoformat(), loan_type, fee, status))
        trans_id = cur.lastrowid
        pay_desc = 'E-Book Purchase' if loan_type == 'ebook' else 'Store Pickup Reservation'
        cur.execute("""INSERT INTO payments (user_id,transaction_id,amount,payment_type,payment_method)
                       VALUES (?,?,?,'borrow_fee',?)""",
                    (user_id, trans_id, fee, f"UPI QR (Ref:{utr}) - {pay_desc}"))
        if loan_type == 'normal':
            cur.execute("UPDATE books SET available_copies=available_copies-1 WHERE id=?", (book_id,))
        conn.commit()

        if loan_type == 'ebook':
            flash(f"✅ E-Book '{book['title']}' issue ho gayi (₹{fee:.0f})! Dashboard se padhein.", "success")
            create_notification(user_id, f"📱 E-Book '{book['title']}' issue! Due: {due_date.strftime('%d %b %Y')}", "success")
        else:
            flash(f"✅ Store Pickup booked (₹{fee:.0f})! '{book['title']}' aapke liye reserve hai. Shelf: {book['shelf_location']}", "success")
            create_notification(user_id, f"📦 Store Pickup booked! '{book['title']}' — {book['shelf_location']} par jakar Student ID dikhayein.", "info")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('student_dashboard'))


@app.route("/student/join-waitlist/<int:book_id>", methods=["POST"])
@student_required
def join_waitlist(book_id):
    user_id = session['user_id']
    conn    = get_db_connection()
    book    = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not book:
        conn.close(); flash("Book nahi mili!", "danger")
        return redirect(url_for('student_catalog'))

    existing = list(conn.execute(
        "SELECT COUNT(*) FROM reservations WHERE book_id=? AND user_id=? AND status='waiting'",
        (book_id, user_id)
    ).fetchone().values())[0]
    if existing > 0:
        conn.close(); flash("Aap already waiting list mein hain!", "warning")
        return redirect(url_for('student_catalog'))

    try:
        conn.execute("INSERT INTO reservations (book_id,user_id) VALUES (?,?)", (book_id, user_id))
        conn.commit()
        flash(f"Waiting list mein add ho gaye! '{book['title']}' available hone par notification milegi. 🔔", "success")
        create_notification(user_id, f"⏳ '{book['title']}' ki waiting list mein hain. Available hone par batayenge.", "info")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('student_catalog'))


@app.route("/student/leave-waitlist/<int:res_id>", methods=["POST"])
@student_required
def leave_waitlist(res_id):
    conn = get_db_connection()
    conn.execute("UPDATE reservations SET status='cancelled' WHERE id=? AND user_id=?",
                 (res_id, session['user_id']))
    conn.commit()
    conn.close()
    flash("Waiting list se hata diya gaya.", "info")
    return redirect(url_for('student_dashboard'))


@app.route("/student/rate/<int:book_id>", methods=["POST"])
@student_required
def rate_book(book_id):
    user_id = session['user_id']
    try:
        rating = int(request.form.get('rating', 0))
    except ValueError:
        rating = 0
    review = request.form.get('review', '').strip()[:500]

    if not (1 <= rating <= 5):
        flash("1 se 5 ke beech rating dein!", "danger")
        return redirect(url_for('student_dashboard'))

    conn = get_db_connection()
    # Verify they actually borrowed this book
    borrowed = list(conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE user_id=? AND book_id=? AND status='Returned'",
        (user_id, book_id)
    ).fetchone().values())[0]
    if not borrowed:
        conn.close(); flash("Sirf returned books ko rate kar sakte hain!", "warning")
        return redirect(url_for('student_dashboard'))

    try:
        conn.execute("""INSERT INTO ratings (book_id,user_id,rating,review) VALUES (?,?,?,?)
                        ON CONFLICT(book_id,user_id) DO UPDATE SET rating=excluded.rating,review=excluded.review""",
                     (book_id, user_id, rating, review))
        conn.commit()
        flash("Rating save ho gayi! ⭐", "success")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('student_dashboard'))


@app.route("/student/read/<int:trans_id>")
@student_required
def student_read_ebook(trans_id):
    user_id = session['user_id']
    conn    = get_db_connection()
    trans   = conn.execute("""SELECT t.*,b.title,b.author,b.category,b.language,b.content
                              FROM transactions t JOIN books b ON t.book_id=b.id
                              WHERE t.id=? AND t.user_id=? AND t.status='Issued'""",
                           (trans_id, user_id)).fetchone()
    conn.close()

    if not trans:
        flash("Loan nahi mila ya already return ho gayi.", "danger")
        return redirect(url_for('student_dashboard'))
    if trans['loan_type'] != 'ebook':
        flash("Online reading sirf E-Books ke liye.", "warning")
        return redirect(url_for('student_dashboard'))

    today    = today_ist()
    due_date = datetime.strptime(trans['due_date'], "%Y-%m-%d").date()
    if today > due_date and trans['fine_status'] not in ('paid', 'waived'):
        fine, dl = get_fine(trans['due_date'])
        return render_template("reader_locked.html", trans=dict(trans), fine=fine, days_late=dl)

    return render_template("reader.html", trans=dict(trans))


@app.route("/student/pay-fine/<int:trans_id>", methods=["POST"])
@student_required
def student_pay_fine(trans_id):
    user_id = session['user_id']
    utr     = request.form.get("utr_ref", "").strip() or f"FINE-{now_ist().strftime('%M%S%f')[:6]}"

    conn  = get_db_connection()
    trans = conn.execute("""SELECT t.*,b.title FROM transactions t JOIN books b ON t.book_id=b.id
                            WHERE t.id=? AND t.user_id=? AND t.status='Issued'""",
                         (trans_id, user_id)).fetchone()
    if not trans:
        conn.close(); flash("Transaction nahi mila!", "danger")
        return redirect(url_for('student_dashboard'))

    fine_amount, _ = get_fine(trans['due_date'])
    current_fine   = fine_amount if fine_amount > 0 else trans['fine_amount']
    if current_fine <= 0:
        conn.close(); flash("Koi pending fine nahi hai!", "info")
        return redirect(url_for('student_dashboard'))

    try:
        conn.execute("""INSERT INTO payments (user_id,transaction_id,amount,payment_type,payment_method)
                        VALUES (?,?,?,'fine_payment',?)""",
                     (user_id, trans_id, current_fine, f"UPI QR (Ref:{utr})"))
        new_due = today_ist() + timedelta(days=7)
        conn.execute("UPDATE transactions SET fine_amount=?,fine_status='paid',due_date=? WHERE id=?",
                     (current_fine, new_due.isoformat(), trans_id))
        conn.commit()
        flash(f"✅ Fine ₹{current_fine:.2f} paid! E-Book unlock ho gayi.", "success")
    except Exception as e:
        flash(f"Payment failed: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('student_dashboard'))


# ═══════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════

with app.app_context():
    try:
        init_db()
    except Exception as e:
        print("DB init:", e)


def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000")


if __name__ == "__main__":
    port     = int(os.environ.get("PORT", 5000))
    is_local = not os.environ.get("RENDER") and not os.environ.get("PORT")
    if is_local and not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.2, open_browser).start()
    app.run(debug=is_local, host="0.0.0.0", port=port)
