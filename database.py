import sqlite3
import os
from datetime import datetime, timedelta, date
from werkzeug.security import generate_password_hash

DB_NAME = os.path.join(os.path.dirname(__file__), "library.db")
DATABASE_URL = os.environ.get('DATABASE_URL')
IS_POSTGRES = bool(DATABASE_URL)

# ─────────────────────────────────────────────
# DB Connection Wrapper (SQLite + PostgreSQL)
# ─────────────────────────────────────────────

class _AdaptedCursor:
    """Wraps psycopg2 or sqlite3 cursor to uniform interface."""
    def __init__(self, cur, db_type):
        self._cur = cur
        self._db_type = db_type
        self._last_id = None

    def _fix(self, sql):
        if self._db_type == 'pg':
            return sql.replace('?', '%s')
        return sql

    def execute(self, sql, params=()):
        fixed = self._fix(sql)
        if self._db_type == 'pg' and sql.strip().upper().startswith('INSERT'):
            # Append RETURNING id if not already there
            if 'RETURNING' not in fixed.upper():
                fixed = fixed.rstrip('; ') + ' RETURNING id'
            self._cur.execute(fixed, params)
            row = self._cur.fetchone()
            if row:
                self._last_id = row['id'] if isinstance(row, dict) else row[0]
        else:
            self._cur.execute(fixed, params)
            self._last_id = getattr(self._cur, 'lastrowid', None)
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        if self._db_type == 'pg':
            return dict(row) if hasattr(row, 'keys') else row
        return dict(row)  # sqlite3.Row -> dict

    def fetchall(self):
        rows = self._cur.fetchall()
        if self._db_type == 'pg':
            return [dict(r) if hasattr(r, 'keys') else r for r in rows]
        return [dict(r) for r in rows]

    @property
    def lastrowid(self):
        if self._db_type == 'pg':
            return self._last_id
        return self._cur.lastrowid

    def __getitem__(self, idx):
        return self._cur[idx]


class DBConnection:
    """Unified connection for SQLite or PostgreSQL."""
    def __init__(self, raw, db_type):
        self._raw = raw
        self._db_type = db_type

    def _fix(self, sql):
        if self._db_type == 'pg':
            return sql.replace('?', '%s')
        return sql

    def execute(self, sql, params=()):
        cur = self._raw.cursor()
        if self._db_type == 'pg':
            from psycopg2.extras import RealDictCursor
        adapted = _AdaptedCursor(cur, self._db_type)
        adapted.execute(sql, params)
        return adapted

    def cursor(self):
        raw_cur = self._raw.cursor()
        return _AdaptedCursor(raw_cur, self._db_type)

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._raw.close()


def get_db_connection():
    if IS_POSTGRES:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            url = DATABASE_URL
            if url.startswith('postgres://'):
                url = url.replace('postgres://', 'postgresql://', 1)
            raw = psycopg2.connect(url, cursor_factory=RealDictCursor)
            return DBConnection(raw, 'pg')
        except Exception as e:
            print(f"PostgreSQL connection failed, falling back to SQLite: {e}")

    # SQLite fallback
    raw = sqlite3.connect(DB_NAME)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return DBConnection(raw, 'sqlite')


# ─────────────────────────────────────────────
# Schema Creation
# ─────────────────────────────────────────────

def _create_tables_sqlite(cursor):
    stmts = [
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            phone TEXT,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            isbn TEXT UNIQUE,
            category TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'English',
            shelf_location TEXT DEFAULT 'Shelf A1',
            total_copies INTEGER NOT NULL DEFAULT 1,
            available_copies INTEGER NOT NULL DEFAULT 1,
            normal_price REAL DEFAULT 69.0,
            ebook_price REAL DEFAULT 49.0,
            content TEXT,
            cover_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            issue_date DATE NOT NULL,
            due_date DATE NOT NULL,
            return_date DATE,
            loan_type TEXT DEFAULT 'normal',
            fee_paid REAL DEFAULT 0.0,
            fine_amount REAL DEFAULT 0.0,
            fine_status TEXT DEFAULT 'none',
            status TEXT DEFAULT 'Issued',
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE RESTRICT,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            transaction_id INTEGER,
            amount REAL NOT NULL,
            payment_type TEXT NOT NULL,
            payment_method TEXT DEFAULT 'Online',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (transaction_id) REFERENCES transactions (id) ON DELETE SET NULL
        )""",
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            notif_type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS otp_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_used INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reserved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'waiting',
            notified INTEGER DEFAULT 0,
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            review TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(book_id, user_id),
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )""",
    ]
    for stmt in stmts:
        cursor._cur.execute(stmt)


def _create_tables_pg(cursor):
    stmts = [
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            phone TEXT,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            isbn TEXT UNIQUE,
            category TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'English',
            shelf_location TEXT DEFAULT 'Shelf A1',
            total_copies INTEGER NOT NULL DEFAULT 1,
            available_copies INTEGER NOT NULL DEFAULT 1,
            normal_price REAL DEFAULT 69.0,
            ebook_price REAL DEFAULT 49.0,
            content TEXT,
            cover_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            issue_date DATE NOT NULL,
            due_date DATE NOT NULL,
            return_date DATE,
            loan_type TEXT DEFAULT 'normal',
            fee_paid REAL DEFAULT 0.0,
            fine_amount REAL DEFAULT 0.0,
            fine_status TEXT DEFAULT 'none',
            status TEXT DEFAULT 'Issued',
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE RESTRICT,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            transaction_id INTEGER,
            amount REAL NOT NULL,
            payment_type TEXT NOT NULL,
            payment_method TEXT DEFAULT 'Online',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (transaction_id) REFERENCES transactions (id) ON DELETE SET NULL
        )""",
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            notif_type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS otp_sessions (
            id SERIAL PRIMARY KEY,
            phone TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_used INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS reservations (
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reserved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'waiting',
            notified INTEGER DEFAULT 0,
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS ratings (
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            review TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(book_id, user_id),
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )""",
    ]
    for stmt in stmts:
        cursor._cur.execute(stmt)


def _seed_users(conn, cursor):
    cursor._cur.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    row = cursor._cur.fetchone()
    count = row[0] if row else 0 
    if count == 0:
        users = [
            ('admin',      'Chief Librarian',  generate_password_hash('admin123'),   'admin',     '+91 9876543210'),
            ('librarian',  'Library Staff',    generate_password_hash('lib123'),     'librarian', '+91 9000000001'),
            ('STU-1001',   'Rahul Sharma',     generate_password_hash('student123'), 'student',   '+91 9123456780'),
            ('STU-1002',   'Priya Patel',      generate_password_hash('student123'), 'student',   '+91 9988776655'),
        ]
        for u in users:
            conn.execute("INSERT OR IGNORE INTO users (username, name, password_hash, role, phone) VALUES (?,?,?,?,?)", u)


def _seed_books(conn, cursor):
    cursor._cur.execute("SELECT COUNT(*) FROM books")
    row = cursor._cur.fetchone()
    count = row[0] if row else 0
    if count == 0:
        books_data = [
            ("श्रीमद्भगवद्गीता (यथारूप)", "ए. सी. भक्तिवेदांत स्वामी प्रभुपाद", "978-9383569878", "Spiritual", "Hindi", "Section SPIRIT-1", 5, 4, 69.0, 49.0,
             "अध्याय १: कुरुक्षेत्र के युद्धस्थल में सैन्यनिरीक्षण\n\nधृतराष्ट्र उवाच:\nधर्मक्षेत्रे कुरुक्षेत्रे समवेता युयुत्सवः।\nमामकाः पाण्डवाश्चैव किमकुर्वत सञ्जय॥\n\nगीता का उपदेश: कर्मण्येवाधिकारस्ते मा फलेषु कदाचन। निष्काम कर्म ही जीवन को मोक्ष की ओर ले जाता है।", None),
            ("The Power of Now", "Eckhart Tolle", "978-1577314806", "Spiritual", "English", "Section SPIRIT-2", 4, 3, 69.0, 49.0,
             "Chapter 1: You Are Not Your Mind\n\nRealize deeply that the present moment is all you have. Make the NOW the primary focus of your life. Say 'yes' to life — and see how life suddenly starts working for you rather than against you.", None),
            ("जीत आपकी (You Can Win)", "शिव खेड़ा", "978-9352668571", "Motivation", "Hindi", "Section MOTIV-1", 6, 5, 69.0, 49.0,
             "अध्याय १: नज़रिया ही सब कुछ है\n\n'जीतने वाले कोई अलग काम नहीं करते, वे हर काम को अलग ढंग से करते हैं।'\n\nतीन मुख्य सिद्धांत: ज्ञान, कौशल, और नजरिया।", None),
            ("Atomic Habits", "James Clear", "978-0735211292", "Motivation", "English", "Section MOTIV-2", 6, 4, 69.0, 49.0,
             "Chapter 1: The Surprising Power of Atomic Habits\n\nIf you get 1 percent better each day for one year, you'll end up thirty-seven times better.\n\nThe 4 Laws: Make it Obvious, Make it Attractive, Make it Easy, Make it Satisfying.", None),
            ("Playing It My Way", "Sachin Tendulkar", "978-1473605206", "Sports", "English", "Section SPORTS-1", 4, 3, 69.0, 49.0,
             "Chapter 1: Childhood in Bandra & Shivaji Park\n\nCricket was not just a game for me; it was oxygen. Under the guidance of Achrekar Sir, every single day began before sunrise.", None),
            ("मेजर ध्यानचंद: हॉकी के जादूगर", "रोहित भार्गव", "978-8176465431", "Sports", "Hindi", "Section SPORTS-2", 4, 4, 69.0, 49.0,
             "अध्याय १: झाँसी से बर्लिन का स्वर्णिम सफर\n\nमेजर ध्यानचंद — भारतीय खेल जगत की अमर गाथा। १९३६ बर्लिन ओलंपिक में स्वर्ण पदक।", None),
            ("Python & AI Development Masterclass", "Dr. Alan Turing & Team", "978-0132350884", "Technology", "English", "Section TECH-1", 5, 4, 69.0, 49.0,
             "Chapter 1: Architecture of Modern Intelligent Systems\n\nPython has emerged as the lingua franca of AI. Key Tenets: Readability counts, Explicit is better than implicit.", None),
            ("Cloud Computing & Web Architecture", "Martin Fowler", "978-0201616224", "Tech", "English", "Section TECH-2", 3, 3, 69.0, 49.0,
             "Chapter 1: Designing Resilient Microservices\n\nNever store plain-text passwords. Always implement salting and hashing algorithms like PBKDF2 or bcrypt.", None),
            ("अग्नि की उड़ान (Wings of Fire)", "डॉ. ए. पी. जे. अब्दुल कलाम", "978-8172235000", "Science", "Hindi", "Section SCI-1", 5, 4, 69.0, 49.0,
             "अध्याय १: रामेश्वरम की गलियों से अंतरिक्ष तक\n\n'सपने वो नहीं जो हम सोते हुए देखते हैं, सपने वो हैं जो हमें सोने नहीं देते।'", None),
            ("A Brief History of Time", "Stephen Hawking", "978-0553380163", "Science", "English", "Section SCI-2", 4, 3, 69.0, 49.0,
             "Chapter 1: Our Picture of the Universe\n\nTime is not absolute. In extreme gravitational collapse, matter forms a singularity. Black holes emit Hawking Radiation.", None),
            ("Thinking, Fast and Slow", "Daniel Kahneman", "978-0374533557", "Psychology", "English", "Section PSY-1", 4, 3, 69.0, 49.0,
             "Part 1: Two Systems\n\nSystem 1: fast, automatic, intuitive.\nSystem 2: slow, deliberate, rational.\n\nCognitive biases: confirmation bias, halo effect, loss aversion.", None),
            ("मन की शक्ति (The Power of Subconscious Mind)", "डॉ. जोसेफ मर्फी", "978-9381860083", "Psychology", "Hindi", "Section PSY-2", 5, 4, 69.0, 49.0,
             "अध्याय १: आपके भीतर का असीम खज़ाना\n\nआपका अवचेतन मन एक उपजाऊ बगीचे की तरह है। सकारात्मक विचार बोएं, सफल जीवन काटें।", None),
        ]
        conn.execute("DELETE FROM books WHERE 1=1")  # clear if partial
        for b in books_data:
            conn.execute("""INSERT INTO books (title,author,isbn,category,language,shelf_location,
                total_copies,available_copies,normal_price,ebook_price,content,cover_url)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", b)


def _seed_settings(conn):
    defaults = [
        ('open_time', '08:00'), ('close_time', '20:00'), ('sunday_closed', 'true'),
        ('normal_price', '69.0'), ('ebook_price', '49.0'),
        ('notice', 'Library Timings: 8:00 AM - 8:00 PM (Mon-Sat). Sunday CLOSED. E-Books 24/7!'),
    ]
    for k, v in defaults:
        try:
            conn.execute("INSERT OR IGNORE INTO settings (key,value) VALUES (?,?)", (k, v))
        except Exception:
            pass


def _migrate_schema(conn):
    """Ensures all new columns exist on legacy tables."""
    try:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE books ADD COLUMN cover_url TEXT")
    except Exception:
        pass


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    if IS_POSTGRES:
        _create_tables_pg(cur)
    else:
        _create_tables_sqlite(cur)

    conn.commit()

    _migrate_schema(conn)
    conn.commit()

    _seed_users(conn, cur)
    _seed_settings(conn)
    _seed_books(conn, cur)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("[OK] Database initialized at:", DB_NAME if not IS_POSTGRES else DATABASE_URL[:40])
