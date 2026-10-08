import sys
from datetime import datetime, timedelta, date
from werkzeug.security import generate_password_hash
from database import get_db_connection, init_db

DAILY_FINE_RATE = 5.0
STANDARD_LOAN_DAYS = 14

def print_header(title):
    print("\n" + "=" * 65)
    print(f"  {title.upper()}")
    print("=" * 65)

def get_fine(due_date_str, return_date_str=None):
    due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
    ref_date = datetime.strptime(return_date_str, "%Y-%m-%d").date() if return_date_str else date.today()
    if ref_date > due_date:
        days_late = (ref_date - due_date).days
        return days_late * DAILY_FINE_RATE, days_late
    return 0.0, 0

def calculate_due_date(loan_days=STANDARD_LOAN_DAYS):
    due = date.today() + timedelta(days=loan_days)
    if due.weekday() == 6:  # Sunday
        due += timedelta(days=1)  # Rollover to Monday!
    return due

def view_all_books():
    print_header("Book Catalog")
    conn = get_db_connection()
    books = conn.execute("SELECT id, title, author, category, shelf_location, available_copies, total_copies FROM books ORDER BY id ASC").fetchall()
    conn.close()

    if not books:
        print("No books found in the library.")
        return

    print(f"{'ID':<4} | {'Title':<24} | {'Author':<18} | {'Shelf':<12} | {'Copies'}")
    print("-" * 75)
    for b in books:
        title = (b['title'][:21] + '..') if len(b['title']) > 24 else b['title']
        author = (b['author'][:15] + '..') if len(b['author']) > 18 else b['author']
        copies_str = f"{b['available_copies']} / {b['total_copies']}"
        print(f"{b['id']:<4} | {title:<24} | {author:<18} | {b['shelf_location']:<12} | {copies_str}")

def add_new_book():
    print_header("Add New Book")
    title = input("Enter Book Title: ").strip()
    if not title:
        print("[-] Book title cannot be empty!")
        return

    author = input("Enter Author Name: ").strip()
    if not author:
        print("[-] Author cannot be empty!")
        return

    isbn = input("Enter ISBN (optional): ").strip()
    category = input("Enter Category (e.g. Technology, Fiction): ").strip()
    shelf = input("Enter Shelf Location [Default: Shelf A1]: ").strip() or "Shelf A1"
    copies_input = input("Enter Total Copies [Default: 1]: ").strip()

    try:
        copies = int(copies_input) if copies_input else 1
        if copies < 1:
            copies = 1
    except ValueError:
        copies = 1

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO books (title, author, isbn, category, shelf_location, total_copies, available_copies)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (title, author, isbn or None, category or 'General', shelf, copies, copies))
        conn.commit()
        print(f"\n[+] Successfully added '{title}' ({copies} copies, {shelf}) to the library!")
    except Exception as e:
        print(f"\n[-] Error adding book: {e}")
    finally:
        conn.close()

def search_books():
    print_header("Search Books")
    query = input("Enter search keyword (Title / Author / ISBN): ").strip()
    if not query:
        print("[-] Empty search query.")
        return

    conn = get_db_connection()
    term = f"%{query}%"
    books = conn.execute("""
        SELECT id, title, author, category, shelf_location, available_copies, total_copies 
        FROM books 
        WHERE title LIKE ? OR author LIKE ? OR isbn LIKE ?
    """, (term, term, term)).fetchall()
    conn.close()

    if not books:
        print(f"No books matching '{query}' found.")
        return

    print(f"\n{'ID':<4} | {'Title':<24} | {'Author':<18} | {'Shelf':<12} | {'Available'}")
    print("-" * 75)
    for b in books:
        title = (b['title'][:21] + '..') if len(b['title']) > 24 else b['title']
        author = (b['author'][:15] + '..') if len(b['author']) > 18 else b['author']
        print(f"{b['id']:<4} | {title:<24} | {author:<18} | {b['shelf_location']:<12} | {b['available_copies']} left")

def view_all_students():
    print_header("Registered Students")
    conn = get_db_connection()
    students = conn.execute("""
        SELECT u.id, u.username, u.name, u.phone,
               (SELECT COUNT(*) FROM transactions WHERE user_id = u.id AND status = 'Issued') as active_books
        FROM users u
        WHERE u.role = 'student'
        ORDER BY u.id ASC
    """).fetchall()
    conn.close()

    if not students:
        print("No students registered.")
        return

    print(f"{'ID':<4} | {'Student ID / Roll':<18} | {'Name':<20} | {'Active Loans'}")
    print("-" * 65)
    for s in students:
        name = (s['name'][:18] + '..') if len(s['name']) > 20 else s['name']
        print(f"{s['id']:<4} | {s['username']:<18} | {name:<20} | {s['active_books']} books")

def add_new_student():
    print_header("Register New Student")
    name = input("Enter Student Full Name: ").strip()
    if not name:
        print("[-] Name cannot be empty!")
        return

    username = input("Enter Student ID / Roll No (Username): ").strip()
    if not username:
        print("[-] Student ID cannot be empty!")
        return

    phone = input("Enter Phone Number: ").strip()
    password = input("Enter Login Password [Default: student123]: ").strip() or "student123"

    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO users (username, name, password_hash, role, phone)
            VALUES (?, ?, ?, 'student', ?)
        """, (username, name, generate_password_hash(password), phone))
        conn.commit()
        print(f"\n[+] Student '{name}' (ID: {username}) registered successfully!")
    except Exception as e:
        print(f"\n[-] Error: Student ID '{username}' already exists. ({e})")
    finally:
        conn.close()

def issue_book():
    print_header("Issue Book to Student")
    conn = get_db_connection()
    available_books = conn.execute("SELECT id, title, available_copies FROM books WHERE available_copies > 0").fetchall()
    students = conn.execute("SELECT id, username, name FROM users WHERE role = 'student'").fetchall()

    if not available_books:
        print("[-] No books currently available for checkout.")
        conn.close()
        return

    print("Available Books:")
    for b in available_books:
        print(f"  [{b['id']}] {b['title']} ({b['available_copies']} left)")

    try:
        book_id = int(input("\nEnter Book ID to issue: "))
    except ValueError:
        print("[-] Invalid Book ID.")
        conn.close()
        return

    print("\nStudents:")
    for s in students:
        print(f"  [{s['id']}] {s['name']} (ID: {s['username']})")

    try:
        user_id = int(input("\nEnter Student ID number: "))
    except ValueError:
        print("[-] Invalid Student number.")
        conn.close()
        return

    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    student = conn.execute("SELECT * FROM users WHERE id = ? AND role = 'student'", (user_id,)).fetchone()

    if not book or not student:
        print("[-] Invalid Book or Student.")
        conn.close()
        return

    print("\nSelect Book Format:")
    print("  [1] E-Book (Digital Copy - Fee: Rs 49)")
    print("  [2] Normal Book (Physical Copy - Fee: Rs 69)")
    fmt_choice = input("Enter choice [Default 1]: ").strip()
    loan_type = 'normal' if fmt_choice == '2' else 'ebook'
    fee = 69.0 if loan_type == 'normal' else 49.0

    if loan_type == 'normal' and book['available_copies'] <= 0:
        print("[-] Book has 0 physical copies left. Please issue as E-Book.")
        conn.close()
        return

    issue_date = date.today()
    due_date = calculate_due_date(STANDARD_LOAN_DAYS)

    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO transactions (book_id, user_id, issue_date, due_date, loan_type, fee_paid, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Issued')
        """, (book_id, user_id, issue_date.isoformat(), due_date.isoformat(), loan_type, fee))
        trans_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO payments (user_id, transaction_id, amount, payment_type, payment_method)
            VALUES (?, ?, ?, 'borrow_fee', 'CLI Desk')
        """, (user_id, trans_id, fee))

        if loan_type == 'normal':
            cursor.execute("UPDATE books SET available_copies = available_copies - 1 WHERE id = ?", (book_id,))
        conn.commit()

        fmt_name = "E-Book (Rs 49)" if loan_type == 'ebook' else "Physical Book (Rs 69)"
        print(f"\n[+] Success! '{book['title']}' issued as {fmt_name} to {student['name']}.")
        print(f"    Due Date: {due_date.strftime('%d %b %Y')} (Sunday rollover protected)")
    except Exception as e:
        print(f"[-] Failed to issue book: {e}")
    finally:
        conn.close()

def return_book():
    print_header("Return Book")
    conn = get_db_connection()
    issued_loans = conn.execute("""
        SELECT t.id, t.due_date, b.title as book_title, b.id as book_id, u.name as student_name
        FROM transactions t
        JOIN books b ON t.book_id = b.id
        JOIN users u ON t.user_id = u.id
        WHERE t.status = 'Issued'
    """).fetchall()

    if not issued_loans:
        print("No books are currently issued.")
        conn.close()
        return

    print("Currently Issued Books:")
    for loan in issued_loans:
        fine, days_late = get_fine(loan['due_date'])
        late_info = f" -> ⚠️ {days_late} days OVERDUE (Fine: ₹{fine:.2f})" if days_late > 0 else f" (Due: {loan['due_date']})"
        print(f"  [Tx #{loan['id']}] '{loan['book_title']}' borrowed by {loan['student_name']}{late_info}")

    try:
        tx_id = int(input("\nEnter Transaction ID (#) to return: "))
    except ValueError:
        print("[-] Invalid Transaction ID.")
        conn.close()
        return

    loan = conn.execute("SELECT * FROM transactions WHERE id = ? AND status = 'Issued'", (tx_id,)).fetchone()
    if not loan:
        print("[-] Transaction not found or already returned.")
        conn.close()
        return

    today = date.today()
    fine, days_late = get_fine(loan['due_date'], today.isoformat())

    try:
        conn.execute("""
            UPDATE transactions
            SET return_date = ?, fine_amount = ?, status = 'Returned'
            WHERE id = ?
        """, (today.isoformat(), fine, tx_id))
        conn.execute("UPDATE books SET available_copies = available_copies + 1 WHERE id = ?", (loan['book_id'],))
        conn.commit()

        print("\n[+] Book returned successfully!")
        if fine > 0:
            print(f"    ⚠️ Return was {days_late} days late. Fine collected: ₹{fine:.2f}")
        else:
            print("    ✅ Returned on time. Fine: ₹0.00")
    except Exception as e:
        print(f"[-] Error returning book: {e}")
    finally:
        conn.close()

def main():
    init_db()
    try:
        while True:
            now = datetime.now()
            schedule_note = "🔴 CLOSED (Sunday Off)" if now.weekday() == 6 else "🟢 OPEN (8 AM - 8 PM)"
            print("\n" + "=" * 55)
            print(f"     LIBRARY MANAGEMENT SYSTEM (CLI) &bull; {schedule_note}")
            print("=" * 55)
            print("  [1] View All Books")
            print("  [2] Add New Book")
            print("  [3] Search Books")
            print("  [4] View All Students")
            print("  [5] Register New Student")
            print("  [6] Issue Book (with Sunday Rollover)")
            print("  [7] Return Book (Fine Calculation)")
            print("  [8] Exit")
            print("=" * 55)

            choice = input("Enter your choice (1-8): ").strip()

            if choice == '1':
                view_all_books()
            elif choice == '2':
                add_new_book()
            elif choice == '3':
                search_books()
            elif choice == '4':
                view_all_students()
            elif choice == '5':
                add_new_student()
            elif choice == '6':
                issue_book()
            elif choice == '7':
                return_book()
            elif choice == '8':
                print("\nExiting Library Management System. Good bye!\n")
                break
            else:
                print("\n[-] Invalid choice. Please enter a number from 1 to 8.")

            input("\nPress Enter to return to main menu...")
    except (KeyboardInterrupt, EOFError):
        print("\n\nSession ended. Good bye!\n")
        sys.exit(0)

if __name__ == "__main__":
    main()
