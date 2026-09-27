import os
from datetime import datetime, timedelta, date, time
from functools import wraps
import webbrowser
import threading
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection, init_db

app = Flask(__name__)
app.secret_key = "lms_complete_secure_session_key_2026_v2"

DAILY_FINE_RATE = 5.0
STANDARD_LOAN_DAYS = 14
NORMAL_BOOK_FEE = 69.0
EBOOK_FEE = 49.0

# ----------------- TIMINGS & SCHEDULE HELPER -----------------

def get_library_status():
    """Calculates live library open/closed status based on Sunday off and working hours."""
    conn = get_db_connection()
    settings_rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()

    settings_dict = {row['key']: row['value'] for row in settings_rows}
    open_time_str = settings_dict.get('open_time', '08:00')
    close_time_str = settings_dict.get('close_time', '20:00')
    notice = settings_dict.get('notice', 'Library Timings: 8:00 AM - 8:00 PM (Mon-Sat). Sunday is CLOSED. E-Books available 24/7!')

    now = datetime.now()
    weekday = now.weekday()  # 0=Monday, 6=Sunday

    open_h, open_m = map(int, open_time_str.split(':'))
    close_h, close_m = map(int, close_time_str.split(':'))

    open_t = time(open_h, open_m)
    close_t = time(close_h, close_m)
    cur_t = now.time()

    if weekday == 6:  # Sunday
        is_open = False
        badge_text = "CLOSED TODAY (Sunday Weekly Off)"
        badge_color = "red"
        timing_info = "Opens Monday at 8:00 AM"
    else:
        if open_t <= cur_t <= close_t:
            is_open = True
            badge_text = "OPEN NOW (8:00 AM - 8:00 PM)"
            badge_color = "emerald"
            timing_info = "Closes today at 8:00 PM"
        else:
            is_open = False
            badge_text = "CLOSED FOR THE DAY"
            badge_color = "rose"
            timing_info = "Opens tomorrow at 8:00 AM"

    return {
        "is_open": is_open,
        "badge_text": badge_text,
        "badge_color": badge_color,
        "timing_info": timing_info,
        "notice": notice,
        "working_hours": "8:00 AM - 8:00 PM (Mon to Sat)",
        "current_date": now.strftime("%A, %d %B %Y"),
        "current_time": now.strftime("%I:%M %p")
    }

@app.context_processor
def inject_library_info():
    status = get_library_status()
    user_info = None
    if 'user_id' in session:
        user_info = {
            'id': session.get('user_id'),
            'username': session.get('username'),
            'name': session.get('name'),
            'role': session.get('role')
        }
    return dict(library_status=status, current_user=user_info)

# ----------------- LOAN & FINE HELPERS -----------------

def calculate_due_date(loan_days=STANDARD_LOAN_DAYS, loan_type='normal'):
    """Calculates due date. If normal physical book due date lands on Sunday, auto-extend to Monday."""
    due = date.today() + timedelta(days=loan_days)
    if loan_type == 'normal' and due.weekday() == 6:
        due += timedelta(days=1)
    return due

def get_fine(due_date_str, return_date_str=None):
    """Calculates late fine (₹5/day)."""
    due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
    ref_date = datetime.strptime(return_date_str, "%Y-%m-%d").date() if return_date_str else date.today()
    if ref_date > due_date:
        days_late = (ref_date - due_date).days
        return days_late * DAILY_FINE_RATE, days_late
    return 0.0, 0

# ----------------- AUTH DECORATORS -----------------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash("Admin access required! Please log in as Admin.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'student':
            flash("Student access required.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ----------------- AUTHENTICATION -----------------

@app.route("/")
def index():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Please enter both Username and Password!", "danger")
            return render_template("login.html")

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['name'] = user['name']
            session['role'] = user['role']
            flash(f"Welcome back, {user['name']}!", "success")

            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('student_dashboard'))
        else:
            flash("Invalid Username or Password. Please try again.", "danger")

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()

        if not name or not username or not password:
            flash("Name, Student ID/Username, and Password are required!", "danger")
            return render_template("register.html")

        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO users (username, name, password_hash, role, phone)
                VALUES (?, ?, ?, 'student', ?)
            """, (username, name, generate_password_hash(password), phone))
            conn.commit()
            flash(f"Account created successfully for {name}! Please log in with ID: {username}", "success")
            return redirect(url_for('login'))
        except Exception as e:
            flash(f"Student ID '{username}' already exists. Please choose a different ID.", "danger")
        finally:
            conn.close()

    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('login'))

# ----------------- ADMIN DASHBOARD & CONTROLS -----------------

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    conn = get_db_connection()
    today_str = date.today().isoformat()

    total_titles = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    total_copies = conn.execute("SELECT COALESCE(SUM(total_copies), 0) FROM books").fetchone()[0]
    available_copies = conn.execute("SELECT COALESCE(SUM(available_copies), 0) FROM books").fetchone()[0]
    total_students = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'student'").fetchone()[0]
    active_loans = conn.execute("SELECT COUNT(*) FROM transactions WHERE status = 'Issued'").fetchone()[0]

    overdue_loans = conn.execute("""
        SELECT COUNT(*) FROM transactions 
        WHERE status = 'Issued' AND due_date < ?
    """, (today_str,)).fetchone()[0]

    total_fine_collected = conn.execute("""
        SELECT COALESCE(SUM(fine_amount), 0.0) FROM transactions WHERE fine_status = 'paid' OR (status = 'Returned' AND fine_status != 'waived')
    """).fetchone()[0]

    total_fees_collected = conn.execute("""
        SELECT COALESCE(SUM(amount), 0.0) FROM payments
    """).fetchone()[0]

    pending_pickups_raw = conn.execute("""
        SELECT t.id, t.issue_date, t.due_date, t.loan_type, t.fee_paid, t.status,
               b.id AS book_id, b.title AS book_title, b.isbn, b.language, b.shelf_location,
               u.id AS student_id, u.name AS student_name, u.username AS student_roll, u.phone AS student_phone
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        JOIN users u ON t.user_id = u.id
        WHERE t.status = 'Reserved'
        ORDER BY t.id DESC
    """).fetchall()
    pending_pickups = [dict(r) for r in pending_pickups_raw]

    recent_loans_raw = conn.execute("""
        SELECT t.id, t.issue_date, t.due_date, t.return_date, t.loan_type, t.fee_paid, t.fine_amount, t.fine_status, t.status,
               b.title AS book_title, b.isbn, b.language,
               u.name AS student_name, u.username AS student_id, u.phone AS student_phone
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        JOIN users u ON t.user_id = u.id
        ORDER BY t.id DESC LIMIT 6
    """).fetchall()

    recent_loans = []
    for row in recent_loans_raw:
        item = dict(row)
        if item['status'] == 'Issued':
            fine, days_late = get_fine(item['due_date'])
            item['pending_fine'] = fine if item['fine_status'] != 'waived' else 0.0
            item['days_late'] = days_late
            item['is_overdue'] = days_late > 0 and item['fine_status'] != 'waived'
        else:
            item['pending_fine'] = 0.0
            item['days_late'] = 0
            item['is_overdue'] = False
        recent_loans.append(item)

    available_books = conn.execute("SELECT id, title, available_copies, language FROM books WHERE available_copies > 0 ORDER BY title ASC").fetchall()
    students_list = conn.execute("SELECT id, username, name FROM users WHERE role = 'student' ORDER BY name ASC").fetchall()
    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_titles=total_titles,
        total_copies=total_copies,
        available_copies=available_copies,
        total_students=total_students,
        active_loans=active_loans,
        overdue_loans=overdue_loans,
        total_fine_collected=total_fine_collected,
        total_fees_collected=total_fees_collected,
        pending_pickups=pending_pickups,
        recent_loans=recent_loans,
        available_books=available_books,
        students_list=students_list
    )

@app.route("/admin/update-notice", methods=["POST"])
@admin_required
def update_notice():
    notice = request.form.get("notice", "").strip()
    if notice:
        conn = get_db_connection()
        conn.execute("UPDATE settings SET value = ? WHERE key = 'notice'", (notice,))
        conn.commit()
        conn.close()
        flash("Library Notice Board updated successfully!", "success")
    return redirect(url_for('admin_dashboard'))

# ----------------- ADMIN: BOOKS MANAGEMENT -----------------

@app.route("/admin/books")
@admin_required
def admin_books():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    language = request.args.get("language", "").strip()
    
    conn = get_db_connection()
    sql = "SELECT * FROM books WHERE 1=1"
    params = []

    if query:
        sql += " AND (title LIKE ? OR author LIKE ? OR isbn LIKE ?)"
        term = f"%{query}%"
        params.extend([term, term, term])
    
    if category:
        sql += " AND category = ?"
        params.append(category)

    if language:
        sql += " AND language = ?"
        params.append(language)

    sql += " ORDER BY id DESC"
    book_rows = conn.execute(sql, params).fetchall()
    categories = [row[0] for row in conn.execute("SELECT DISTINCT category FROM books WHERE category IS NOT NULL").fetchall()]
    conn.close()

    return render_template("books.html", books=book_rows, query=query, selected_category=category, selected_language=language, categories=categories)

@app.route("/admin/books/add", methods=["POST"])
@admin_required
def admin_add_book():
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    isbn = request.form.get("isbn", "").strip()
    category = request.form.get("category", "").strip()
    language = request.form.get("language", "English").strip()
    shelf = request.form.get("shelf_location", "Shelf A1").strip()
    content = request.form.get("content", "").strip()
    try:
        copies = int(request.form.get("total_copies", 1))
        if copies < 1:
            copies = 1
    except ValueError:
        copies = 1

    if not title or not author:
        flash("Title and Author are required!", "danger")
        return redirect(url_for('admin_books'))

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO books (title, author, isbn, category, language, shelf_location, total_copies, available_copies, normal_price, ebook_price, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 69.0, 49.0, ?)
        """, (title, author, isbn or None, category or 'Motivation', language, shelf, copies, copies, content))
        conn.commit()
        flash(f"Book '{title}' ({language}) added to catalog!", "success")
    except Exception as e:
        flash(f"Error adding book: ISBN may already exist. ({str(e)})", "danger")
    finally:
        conn.close()

    return redirect(url_for('admin_books'))

@app.route("/admin/books/edit/<int:book_id>", methods=["POST"])
@admin_required
def admin_edit_book(book_id):
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    isbn = request.form.get("isbn", "").strip()
    category = request.form.get("category", "").strip()
    language = request.form.get("language", "English").strip()
    shelf = request.form.get("shelf_location", "").strip()
    content = request.form.get("content", "").strip()
    try:
        new_total_copies = int(request.form.get("total_copies", 1))
    except ValueError:
        flash("Invalid number of copies", "danger")
        return redirect(url_for('admin_books'))

    conn = get_db_connection()
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        conn.close()
        flash("Book not found!", "danger")
        return redirect(url_for('admin_books'))

    issued_copies = book["total_copies"] - book["available_copies"]
    if new_total_copies < issued_copies:
        conn.close()
        flash(f"Cannot reduce total copies below currently issued copies ({issued_copies})!", "danger")
        return redirect(url_for('admin_books'))

    new_available_copies = new_total_copies - issued_copies

    try:
        conn.execute("""
            UPDATE books
            SET title = ?, author = ?, isbn = ?, category = ?, language = ?, shelf_location = ?, total_copies = ?, available_copies = ?, content = ?
            WHERE id = ?
        """, (title, author, isbn or None, category, language, shelf, new_total_copies, new_available_copies, content or book['content'], book_id))
        conn.commit()
        flash("Book details updated successfully!", "success")
    except Exception as e:
        flash(f"Error updating book: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('admin_books'))

@app.route("/admin/books/delete/<int:book_id>", methods=["POST"])
@admin_required
def admin_delete_book(book_id):
    conn = get_db_connection()
    active_loans = conn.execute("SELECT COUNT(*) FROM transactions WHERE book_id = ? AND status = 'Issued'", (book_id,)).fetchone()[0]

    if active_loans > 0:
        conn.close()
        flash(f"Cannot delete book: {active_loans} copy is currently borrowed by students!", "danger")
        return redirect(url_for('admin_books'))

    try:
        conn.execute("DELETE FROM transactions WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.commit()
        flash("Book removed from library catalog!", "success")
    except Exception as e:
        flash(f"Could not delete book: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('admin_books'))

# ----------------- ADMIN: STUDENTS MANAGEMENT & EDIT -----------------

@app.route("/admin/students")
@admin_required
def admin_students():
    query = request.args.get("q", "").strip()
    conn = get_db_connection()

    sql = """
        SELECT u.*, 
               (SELECT COUNT(*) FROM transactions WHERE user_id = u.id AND status = 'Issued') AS active_books,
               (SELECT COUNT(*) FROM transactions WHERE user_id = u.id) AS total_borrowed
        FROM users u
        WHERE u.role = 'student'
    """
    params = []
    if query:
        sql += " AND (u.name LIKE ? OR u.username LIKE ? OR u.phone LIKE ?)"
        term = f"%{query}%"
        params.extend([term, term, term])

    sql += " ORDER BY u.id DESC"
    students_rows = conn.execute(sql, params).fetchall()
    conn.close()

    return render_template("students.html", students=students_rows, query=query)

@app.route("/admin/students/edit/<int:user_id>", methods=["POST"])
@admin_required
def admin_edit_student(user_id):
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    phone = request.form.get("phone", "").strip()
    new_password = request.form.get("password", "").strip()

    if not name or not username:
        flash("Name and Student ID are required!", "danger")
        return redirect(url_for('admin_students'))

    conn = get_db_connection()
    try:
        if new_password:
            conn.execute("""
                UPDATE users
                SET name = ?, username = ?, phone = ?, password_hash = ?
                WHERE id = ? AND role = 'student'
            """, (name, username, phone, generate_password_hash(new_password), user_id))
        else:
            conn.execute("""
                UPDATE users
                SET name = ?, username = ?, phone = ?
                WHERE id = ? AND role = 'student'
            """, (name, username, phone, user_id))
        conn.commit()
        flash(f"Student '{name}' details updated successfully!", "success")
    except Exception as e:
        flash(f"Error updating student: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('admin_students'))

@app.route("/admin/students/<int:user_id>/history")
@admin_required
def student_history_api(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT id, name, username, phone FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "Student not found"}), 404

    loans = conn.execute("""
        SELECT t.*, b.title AS book_title, b.isbn, b.language
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        WHERE t.user_id = ?
        ORDER BY t.id DESC
    """, (user_id,)).fetchall()
    conn.close()

    history_list = [dict(row) for row in loans]
    return jsonify({"student": dict(user), "history": history_list})

@app.route("/admin/students/delete/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_student(user_id):
    conn = get_db_connection()
    active_loans = conn.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ? AND status = 'Issued'", (user_id,)).fetchone()[0]

    if active_loans > 0:
        conn.close()
        flash("Cannot delete student: They have active borrowed books!", "danger")
        return redirect(url_for('admin_students'))

    try:
        conn.execute("DELETE FROM payments WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        flash("Student account deleted successfully!", "success")
    except Exception as e:
        flash(f"Error deleting student: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('admin_students'))

# ----------------- ADMIN: CIRCULATION & FINE WAIVER -----------------

@app.route("/admin/transactions")
@admin_required
def admin_transactions():
    status_filter = request.args.get("status", "all")
    conn = get_db_connection()
    today_str = date.today().isoformat()

    sql = """
        SELECT t.id, t.issue_date, t.due_date, t.return_date, t.loan_type, t.fee_paid, t.fine_amount, t.fine_status, t.status,
               b.id AS book_id, b.title AS book_title, b.isbn, b.author, b.shelf_location, b.language,
               u.id AS student_id, u.name AS student_name, u.username AS student_roll, u.phone AS student_phone
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        JOIN users u ON t.user_id = u.id
        WHERE 1=1
    """
    params = []

    if status_filter == "Issued":
        sql += " AND t.status = 'Issued'"
    elif status_filter == "Reserved":
        sql += " AND t.status = 'Reserved'"
    elif status_filter == "Overdue":
        sql += " AND t.status = 'Issued' AND t.due_date < ? AND t.fine_status != 'waived'"
        params.append(today_str)
    elif status_filter == "Returned":
        sql += " AND t.status = 'Returned'"

    sql += " ORDER BY t.id DESC"
    rows = conn.execute(sql, params).fetchall()

    transactions_data = []
    for row in rows:
        item = dict(row)
        if item['status'] == 'Issued':
            fine, days_late = get_fine(item['due_date'])
            item['current_fine'] = fine if item['fine_status'] != 'waived' else 0.0
            item['days_late'] = days_late
            item['is_overdue'] = days_late > 0 and item['fine_status'] != 'waived'
        else:
            item['current_fine'] = item['fine_amount']
            item['days_late'] = 0
            item['is_overdue'] = False
        transactions_data.append(item)

    available_books = conn.execute("SELECT id, title, available_copies, language FROM books WHERE available_copies > 0 ORDER BY title ASC").fetchall()
    students_list = conn.execute("SELECT id, username, name FROM users WHERE role = 'student' ORDER BY name ASC").fetchall()
    conn.close()

    return render_template(
        "transactions.html",
        transactions=transactions_data,
        status_filter=status_filter,
        available_books=available_books,
        students_list=students_list,
        daily_fine_rate=DAILY_FINE_RATE
    )

@app.route("/admin/issue", methods=["POST"])
@admin_required
def admin_issue_book():
    try:
        book_id = int(request.form.get("book_id"))
        user_id = int(request.form.get("user_id"))
        loan_type = request.form.get("loan_type", "normal")
        loan_days = int(request.form.get("loan_days", STANDARD_LOAN_DAYS))
    except (ValueError, TypeError):
        flash("Invalid book or student selection!", "danger")
        return redirect(request.referrer or url_for('admin_transactions'))

    conn = get_db_connection()
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    student = conn.execute("SELECT * FROM users WHERE id = ? AND role = 'student'", (user_id,)).fetchone()

    if not book or not student:
        conn.close()
        flash("Selected book or student does not exist!", "danger")
        return redirect(request.referrer or url_for('admin_transactions'))

    if loan_type == 'normal' and book["available_copies"] <= 0:
        conn.close()
        flash(f"'{book['title']}' has 0 physical copies left in stock! You can issue as E-Book instead.", "danger")
        return redirect(request.referrer or url_for('admin_transactions'))

    issue_date = date.today()
    due_date = calculate_due_date(loan_days, loan_type)
    fee = EBOOK_FEE if loan_type == 'ebook' else NORMAL_BOOK_FEE

    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO transactions (book_id, user_id, issue_date, due_date, loan_type, fee_paid, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Issued')
        """, (book_id, user_id, issue_date.isoformat(), due_date.isoformat(), loan_type, fee))
        trans_id = cursor.lastrowid

        # Record payment
        cursor.execute("""
            INSERT INTO payments (user_id, transaction_id, amount, payment_type, payment_method)
            VALUES (?, ?, ?, 'borrow_fee', 'Library Desk')
        """, (user_id, trans_id, fee))

        # Decrement physical stock only if normal book
        if loan_type == 'normal':
            cursor.execute("UPDATE books SET available_copies = available_copies - 1 WHERE id = ?", (book_id,))

        conn.commit()
        type_badge = "📱 E-Book (₹49)" if loan_type == 'ebook' else "📖 Normal Book (₹69)"
        flash(f"'{book['title']}' successfully issued as {type_badge} to {student['name']}! Due date: {due_date.strftime('%d %b %Y')}", "success")
    except Exception as e:
        flash(f"Failed to issue book: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(request.referrer or url_for('admin_transactions'))

@app.route("/admin/return/<int:trans_id>", methods=["POST"])
@admin_required
def admin_return_book(trans_id):
    conn = get_db_connection()
    trans = conn.execute("""
        SELECT t.*, b.title AS book_title, u.name AS student_name
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        JOIN users u ON t.user_id = u.id
        WHERE t.id = ? AND t.status = 'Issued'
    """, (trans_id,)).fetchone()

    if not trans:
        conn.close()
        flash("Transaction not found or already closed!", "danger")
        return redirect(request.referrer or url_for('admin_transactions'))

    today = date.today()
    fine_amount, days_late = get_fine(trans["due_date"], today.isoformat())

    try:
        # If fine was already waived, keep fine as 0
        final_fine = 0.0 if trans['fine_status'] == 'waived' else fine_amount
        fine_status = 'waived' if trans['fine_status'] == 'waived' else ('paid' if final_fine > 0 else 'none')

        conn.execute("""
            UPDATE transactions
            SET return_date = ?, fine_amount = ?, fine_status = ?, status = 'Returned'
            WHERE id = ?
        """, (today.isoformat(), final_fine, fine_status, trans_id))

        if final_fine > 0:
            conn.execute("""
                INSERT INTO payments (user_id, transaction_id, amount, payment_type, payment_method)
                VALUES (?, ?, ?, 'fine_payment', 'Desk Cash')
            """, (trans['user_id'], trans_id, final_fine))

        # Increment copy count if physical book
        if trans['loan_type'] == 'normal':
            conn.execute("UPDATE books SET available_copies = available_copies + 1 WHERE id = ?", (trans["book_id"],))

        conn.commit()

        if final_fine > 0:
            flash(f"Book returned! Late by {days_late} days. Fine collected: ₹{final_fine:.2f}", "warning")
        elif trans['fine_status'] == 'waived':
            flash(f"'{trans['book_title']}' returned with fine WAIVED (₹0 collected)!", "info")
        else:
            flash(f"'{trans['book_title']}' returned on time with ₹0.00 fine!", "success")
    except Exception as e:
        flash(f"Error returning book: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(request.referrer or url_for('admin_transactions'))

@app.route("/admin/waive-fine/<int:trans_id>", methods=["POST"])
@admin_required
def admin_waive_fine(trans_id):
    """Admin can waive/forgive late fine without collecting money (Fine Maaf Karna)."""
    conn = get_db_connection()
    trans = conn.execute("""
        SELECT t.*, b.title AS book_title, u.name AS student_name
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        JOIN users u ON t.user_id = u.id
        WHERE t.id = ?
    """, (trans_id,)).fetchone()

    if not trans:
        conn.close()
        flash("Transaction not found!", "danger")
        return redirect(request.referrer or url_for('admin_transactions'))

    try:
        new_due = (date.today() + timedelta(days=7)).isoformat() if datetime.strptime(trans['due_date'], "%Y-%m-%d").date() < date.today() else trans['due_date']
        conn.execute("""
            UPDATE transactions
            SET fine_amount = 0.0, fine_status = 'waived', due_date = ?
            WHERE id = ?
        """, (new_due, trans_id))
        conn.commit()
        flash(f"Success: Fine for '{trans['book_title']}' borrowed by {trans['student_name']} has been WAIVED (माफ़ कर दिया गया)!", "success")
    except Exception as e:
        flash(f"Error waiving fine: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(request.referrer or url_for('admin_transactions'))

# ----------------- STUDENT PORTAL, ISSUE & E-READER -----------------

@app.route("/student/dashboard")
@student_required
def student_dashboard():
    user_id = session.get('user_id')
    conn = get_db_connection()
    today = date.today()

    active_loans_raw = conn.execute("""
        SELECT t.id, t.issue_date, t.due_date, t.loan_type, t.fee_paid, t.fine_status, t.status,
               b.id AS book_id, b.title, b.author, b.isbn, b.shelf_location, b.language, b.category
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        WHERE t.user_id = ? AND t.status IN ('Issued', 'Reserved')
        ORDER BY t.due_date ASC
    """, (user_id,)).fetchall()

    active_loans = []
    active_ebooks = []
    reserved_books = []
    active_physical_loans = []
    total_pending_fine = 0.0

    for row in active_loans_raw:
        item = dict(row)
        due_d = datetime.strptime(item['due_date'], "%Y-%m-%d").date()
        days_left = (due_d - today).days
        fine, days_late = get_fine(item['due_date'])
        
        is_waived = item['fine_status'] == 'waived'
        is_paid = item['fine_status'] == 'paid'

        item['days_left'] = days_left
        item['is_overdue'] = days_late > 0 and not is_waived and not is_paid and item['status'] == 'Issued'
        item['days_late'] = days_late
        item['fine'] = 0.0 if (is_waived or is_paid or item['status'] == 'Reserved') else fine
        item['is_expired'] = today > due_d and item['status'] == 'Issued'
        
        if not is_waived and not is_paid and item['status'] == 'Issued':
            total_pending_fine += fine

        active_loans.append(item)
        if item['status'] == 'Reserved':
            reserved_books.append(item)
        elif item['loan_type'] == 'ebook':
            active_ebooks.append(item)
        else:
            active_physical_loans.append(item)

    # Student's past returned history
    history_raw = conn.execute("""
        SELECT t.id, t.issue_date, t.due_date, t.return_date, t.loan_type, t.fee_paid, t.fine_amount, t.fine_status,
               b.title, b.author, b.language
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        WHERE t.user_id = ? AND t.status = 'Returned'
        ORDER BY t.id DESC LIMIT 5
    """, (user_id,)).fetchall()
    history = [dict(r) for r in history_raw]

    # Student's fee & payment ledger history
    payments_raw = conn.execute("""
        SELECT p.*, t.loan_type, b.title as book_title
        FROM payments p
        LEFT JOIN transactions t ON p.transaction_id = t.id
        LEFT JOIN books b ON t.book_id = b.id
        WHERE p.user_id = ?
        ORDER BY p.id DESC
    """, (user_id,)).fetchall()
    payments = [dict(p) for p in payments_raw]

    conn.close()

    return render_template(
        "student_dashboard.html",
        active_loans=active_loans,
        active_ebooks=active_ebooks,
        reserved_books=reserved_books,
        active_physical_loans=active_physical_loans,
        history=history,
        payments=payments,
        total_pending_fine=total_pending_fine
    )

@app.route("/student/catalog")
@student_required
def student_catalog():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    language = request.args.get("language", "").strip()
    
    conn = get_db_connection()
    sql = "SELECT * FROM books WHERE 1=1"
    params = []

    if query:
        sql += " AND (title LIKE ? OR author LIKE ? OR isbn LIKE ?)"
        term = f"%{query}%"
        params.extend([term, term, term])
    
    if category:
        sql += " AND category = ?"
        params.append(category)

    if language:
        sql += " AND language = ?"
        params.append(language)

    sql += " ORDER BY id DESC"
    book_rows = conn.execute(sql, params).fetchall()
    categories = [row[0] for row in conn.execute("SELECT DISTINCT category FROM books WHERE category IS NOT NULL").fetchall()]
    conn.close()

    return render_template(
        "student_catalog.html",
        books=book_rows,
        query=query,
        selected_category=category,
        selected_language=language,
        categories=categories,
        normal_fee=NORMAL_BOOK_FEE,
        ebook_fee=EBOOK_FEE
    )

@app.route("/student/issue", methods=["POST"])
@student_required
def student_issue_book():
    """Allows student to issue E-Book (instant online) or reserve physical book for store pickup."""
    user_id = session.get('user_id')
    try:
        book_id = int(request.form.get("book_id"))
        loan_type = request.form.get("loan_type", "ebook")  # 'normal' or 'ebook'
    except (ValueError, TypeError):
        flash("Invalid book selection!", "danger")
        return redirect(url_for('student_catalog'))

    conn = get_db_connection()
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        conn.close()
        flash("Book not found!", "danger")
        return redirect(url_for('student_catalog'))

    # Check if student already has this book active or reserved
    existing = conn.execute("""
        SELECT COUNT(*) FROM transactions WHERE user_id = ? AND book_id = ? AND status IN ('Issued', 'Reserved')
    """, (user_id, book_id)).fetchone()[0]

    if existing > 0:
        conn.close()
        flash(f"You already have an active loan or pending store reservation for '{book['title']}'!", "warning")
        return redirect(url_for('student_dashboard'))

    # Check stock for normal physical book
    if loan_type == 'normal' and book["available_copies"] <= 0:
        conn.close()
        flash(f"Sorry, physical copies of '{book['title']}' are out of stock! You can get the E-Book version to read online right away.", "danger")
        return redirect(url_for('student_catalog'))

    issue_date = date.today()
    due_date = calculate_due_date(STANDARD_LOAN_DAYS, loan_type)
    fee = EBOOK_FEE if loan_type == 'ebook' else NORMAL_BOOK_FEE
    status = 'Issued' if loan_type == 'ebook' else 'Reserved'
    
    utr_ref = request.form.get("utr_ref", "").strip() or f"UPI-{datetime.now().strftime('%M%S%f')[:6]}"
    payment_method = f"UPI QR Code (Ref: {utr_ref})"

    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO transactions (book_id, user_id, issue_date, due_date, loan_type, fee_paid, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (book_id, user_id, issue_date.isoformat(), due_date.isoformat(), loan_type, fee, status))
        trans_id = cursor.lastrowid

        # Record payment transaction with UPI reference
        payment_desc = 'E-Book Purchase Fee' if loan_type == 'ebook' else 'Store Pickup Reservation Fee'
        cursor.execute("""
            INSERT INTO payments (user_id, transaction_id, amount, payment_type, payment_method)
            VALUES (?, ?, ?, 'borrow_fee', ?)
        """, (user_id, trans_id, fee, f"{payment_method} - {payment_desc}"))

        # Decrement stock if normal book (holding copy for store pickup)
        if loan_type == 'normal':
            cursor.execute("UPDATE books SET available_copies = available_copies - 1 WHERE id = ?", (book_id,))

        conn.commit()

        if loan_type == 'ebook':
            flash(f"✅ Payment Done (₹{fee:.0f})! E-Book '{book['title']}' is now available on your dashboard. Start reading online right now!", "success")
        else:
            flash(f"✅ Booked for Store Pickup (₹{fee:.0f})! '{book['title']}' has been reserved for you. Please show your Student ID ({session.get('username')}) at the library desk ({book['shelf_location']}) to collect your physical book.", "success")
    except Exception as e:
        flash(f"Failed to process book request: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('student_dashboard'))

@app.route("/admin/handover/<int:trans_id>", methods=["POST"])
@admin_required
def admin_handover_book(trans_id):
    """Admin confirms physical book handover when student visits store to collect."""
    conn = get_db_connection()
    trans = conn.execute("""
        SELECT t.*, b.title AS book_title, u.name AS student_name, u.username AS student_roll
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        JOIN users u ON t.user_id = u.id
        WHERE t.id = ? AND t.status = 'Reserved'
    """, (trans_id,)).fetchone()

    if not trans:
        conn.close()
        flash("Reservation not found or already handed over!", "danger")
        return redirect(url_for('admin_transactions'))

    today = date.today()
    new_due_date = calculate_due_date(STANDARD_LOAN_DAYS, 'normal')

    try:
        conn.execute("""
            UPDATE transactions
            SET status = 'Issued', issue_date = ?, due_date = ?
            WHERE id = ?
        """, (today.isoformat(), new_due_date.isoformat(), trans_id))
        conn.commit()
        flash(f"✅ Handover Confirmed! Physical copy of '{trans['book_title']}' handed over to {trans['student_name']} ({trans['student_roll']}). Official loan due on {new_due_date.strftime('%d %b %Y')}.", "success")
    except Exception as e:
        flash(f"Error confirming handover: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('admin_transactions'))

@app.route("/student/read/<int:trans_id>")
@student_required
def student_read_ebook(trans_id):
    """Online E-Book Reader with Auto-Lock upon expiry."""
    user_id = session.get('user_id')
    conn = get_db_connection()
    trans = conn.execute("""
        SELECT t.*, b.title, b.author, b.category, b.language, b.content
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        WHERE t.id = ? AND t.user_id = ? AND t.status = 'Issued'
    """, (trans_id, user_id)).fetchone()
    conn.close()

    if not trans:
        flash("Loan not found or already returned.", "danger")
        return redirect(url_for('student_dashboard'))

    if trans['loan_type'] != 'ebook':
        flash("Online reading is only available for E-Books.", "warning")
        return redirect(url_for('student_dashboard'))

    # CHECK AUTO-LOCK EXPIRY: If today > due_date and fine is not paid or waived, lock reading access!
    today = date.today()
    due_date = datetime.strptime(trans['due_date'], "%Y-%m-%d").date()
    if today > due_date and trans['fine_status'] not in ('paid', 'waived'):
        fine, days_late = get_fine(trans['due_date'])
        return render_template("reader_locked.html", trans=dict(trans), fine=fine, days_late=days_late)

    return render_template("reader.html", trans=dict(trans))

@app.route("/student/pay-fine/<int:trans_id>", methods=["POST"])
@student_required
def student_pay_fine(trans_id):
    """Allows student to pay fine online with UPI QR Code."""
    user_id = session.get('user_id')
    utr_ref = request.form.get("utr_ref", "").strip() or f"FINE-{datetime.now().strftime('%M%S%f')[:6]}"
    payment_method = f"UPI QR Code (Ref: {utr_ref})"

    conn = get_db_connection()
    trans = conn.execute("""
        SELECT t.*, b.title FROM transactions t
        JOIN books b ON t.book_id = b.id
        WHERE t.id = ? AND t.user_id = ? AND t.status = 'Issued'
    """, (trans_id, user_id)).fetchone()

    if not trans:
        conn.close()
        flash("Transaction not found!", "danger")
        return redirect(url_for('student_dashboard'))

    fine_amount, days_late = get_fine(trans['due_date'])
    if fine_amount <= 0 and trans['fine_status'] != 'pending':
        conn.close()
        flash("No pending fine on this book!", "info")
        return redirect(url_for('student_dashboard'))

    current_fine = fine_amount if fine_amount > 0 else trans['fine_amount']

    try:
        # Record payment
        conn.execute("""
            INSERT INTO payments (user_id, transaction_id, amount, payment_type, payment_method)
            VALUES (?, ?, ?, 'fine_payment', ?)
        """, (user_id, trans_id, current_fine, payment_method))

        # Mark fine as paid in transaction and extend due date by 7 days to grant active access
        new_due = date.today() + timedelta(days=7)
        conn.execute("""
            UPDATE transactions
            SET fine_amount = ?, fine_status = 'paid', due_date = ?
            WHERE id = ?
        """, (current_fine, new_due.isoformat(), trans_id))

        conn.commit()
        flash(f"✅ Payment Done! Fine of ₹{current_fine:.2f} for '{trans['title']}' paid successfully via UPI. E-Book has been unlocked!", "success")
    except Exception as e:
        flash(f"Payment failed: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for('student_dashboard'))

# ----------------- LAUNCH APP -----------------

# Initialize database schema if not already present
with app.app_context():
    try:
        init_db()
    except Exception as e:
        print("Database init:", e)

def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    is_local = os.environ.get("RENDER") is None and os.environ.get("PORT") is None
    print("=" * 65)
    print("  COMPLETE HYBRID LIBRARY MANAGEMENT SYSTEM (LMS)")
    print("  E-Book Price: Rs 49 | Normal Book Price: Rs 69")
    print("  Admin Login: Username = admin | Password = admin123")
    print("  Student Login: Username = STU-1001 | Password = student123")
    print(f"  Running on: http://0.0.0.0:{port} (Local: http://127.0.0.1:{port})")
    print("=" * 65)
    if is_local and not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.2, open_browser).start()
    app.run(debug=is_local, host="0.0.0.0", port=port)
