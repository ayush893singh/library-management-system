import sqlite3
import os
from datetime import datetime, timedelta, date
from werkzeug.security import generate_password_hash

DB_NAME = os.path.join(os.path.dirname(__file__), "library.db")

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Drop existing tables to ensure clean migration to new schema
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payments'")
    has_payments = cursor.fetchone()
    if not has_payments:
        cursor.execute("DROP TABLE IF EXISTS payments")
        cursor.execute("DROP TABLE IF EXISTS transactions")
        cursor.execute("DROP TABLE IF EXISTS books")
        cursor.execute("DROP TABLE IF EXISTS members")
        cursor.execute("DROP TABLE IF EXISTS users")
        cursor.execute("DROP TABLE IF EXISTS settings")

    # 1. Users Table (Admin & Students)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Books Table (Supports Normal & E-Books, Prices, Language, Content)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            isbn TEXT UNIQUE,
            category TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'English', -- 'Hindi' or 'English'
            shelf_location TEXT DEFAULT 'Shelf A1',
            total_copies INTEGER NOT NULL DEFAULT 1,
            available_copies INTEGER NOT NULL DEFAULT 1,
            normal_price REAL DEFAULT 69.0,
            ebook_price REAL DEFAULT 49.0,
            content TEXT, -- Full readable matter for E-Book
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 3. Transactions Table (Normal vs E-Book, Fee Paid, Fine Status)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            issue_date DATE NOT NULL,
            due_date DATE NOT NULL,
            return_date DATE,
            loan_type TEXT DEFAULT 'normal', -- 'normal' or 'ebook'
            fee_paid REAL DEFAULT 0.0,
            fine_amount REAL DEFAULT 0.0,
            fine_status TEXT DEFAULT 'none', -- 'none', 'pending', 'paid', 'waived'
            status TEXT DEFAULT 'Issued', -- 'Issued', 'Returned'
            FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE RESTRICT,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    # 4. Payments Table (Fee history & fines)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            transaction_id INTEGER,
            amount REAL NOT NULL,
            payment_type TEXT NOT NULL, -- 'borrow_fee' or 'fine_payment'
            payment_method TEXT DEFAULT 'Online (UPI / Card)',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (transaction_id) REFERENCES transactions (id) ON DELETE SET NULL
        )
    """)

    # 5. Settings Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Seed Default Admin (Username: admin, Password: admin123)
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO users (username, name, password_hash, role, phone)
            VALUES (?, ?, ?, 'admin', ?)
        """, ('admin', 'Chief Librarian (Admin)', generate_password_hash('admin123'), '+91 9876543210'))

        # Sample Students
        cursor.execute("""
            INSERT INTO users (username, name, password_hash, role, phone)
            VALUES (?, ?, ?, 'student', ?)
        """, ('STU-1001', 'Rahul Sharma', generate_password_hash('student123'), '+91 9123456780'))

        cursor.execute("""
            INSERT INTO users (username, name, password_hash, role, phone)
            VALUES (?, ?, ?, 'student', ?)
        """, ('STU-1002', 'Priya Patel', generate_password_hash('student123'), '+91 9988776655'))

    # Seed Default Settings
    default_settings = [
        ('open_time', '08:00'),
        ('close_time', '20:00'),
        ('sunday_closed', 'true'),
        ('normal_price', '69.0'),
        ('ebook_price', '49.0'),
        ('notice', 'Library Timings: 8:00 AM - 8:00 PM (Monday to Saturday). Sunday is CLOSED. E-Books available 24/7!')
    ]
    for key, val in default_settings:
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))

    # Seed Rich Hindi & English Books across requested categories
    cursor.execute("SELECT COUNT(*) FROM books")
    if cursor.fetchone()[0] == 0:
        books_data = [
            # 1. Spiritual (Hindi)
            (
                "श्रीमद्भगवद्गीता (यथारूप)", 
                "ए. सी. भक्तिवेदांत स्वामी प्रभुपाद", 
                "978-9383569878", 
                "Spiritual", 
                "Hindi", 
                "Section SPIRIT-1", 
                5, 4, 69.0, 49.0,
                """अध्याय १: कुरुक्षेत्र के युद्धस्थल में सैन्यनिरीक्षण

धृतराष्ट्र उवाच:
धर्मक्षेत्रे कुरुक्षेत्रे समवेता युयुत्सवः।
मामकाः पाण्डवाश्चैव किमकुर्वत सञ्जय॥

भावार्थ: धृतराष्ट्र ने पूछा - हे संजय! धर्मभूमि कुरुक्षेत्र में युद्ध की इच्छा से एकत्रित हुए मेरे तथा पाण्डु के पुत्रों ने क्या किया?

जीवन का सबसे बड़ा दर्शन:
गीता का उपदेश मनुष्य को कर्म करने की प्रेरणा देता है। भगवान श्रीकृष्ण अर्जुन से कहते हैं कि हे पार्थ, फल की चिंता किए बिना केवल अपने स्वधर्म और कर्तव्य का पालन करो। कर्मण्येवाधिकारस्ते मा फलेषु कदाचन। जीवन में जब भी संशय या निराशा आए, आत्मा की अमरता और परमात्मा की सत्ता को स्मरण करो। निष्काम कर्म ही जीवन को मोक्ष की ओर ले जाता है।"""
            ),
            # 2. Spiritual (English)
            (
                "The Power of Now", 
                "Eckhart Tolle", 
                "978-1577314806", 
                "Spiritual", 
                "English", 
                "Section SPIRIT-2", 
                4, 3, 69.0, 49.0,
                """Chapter 1: You Are Not Your Mind

The greatest obstacle to experiencing the reality of your connectedness is the illusion of separation created by your mind. Mind-identification creates a false self, the ego, which is always living in the past or projecting into the future.

The Present Moment:
Realize deeply that the present moment is all you have. Make the NOW the primary focus of your life. Whereas before you dwelled in time and paid brief visits to the Now, have your dwelling place in the Now and pay brief visits to past and future when required to deal with practical aspects of your life. Say "yes" to life — and see how life suddenly starts working for you rather than against you."""
            ),
            # 3. Motivation (Hindi)
            (
                "जीत आपकी (You Can Win)", 
                "शिव खेड़ा", 
                "978-9352668571", 
                "Motivation", 
                "Hindi", 
                "Section MOTIV-1", 
                6, 5, 69.0, 49.0,
                """अध्याय १: नज़रिया ही सब कुछ है (Attitude is Everything)

"जीतने वाले कोई अलग काम नहीं करते, वे हर काम को अलग ढंग से करते हैं।"

सफलता कोई इत्तेफाक नहीं है। यह हमारे नजरिए और लगातार अभ्यास का परिणाम है। एक सकारात्मक नजरिया आपको मुश्किल से मुश्किल हालात में भी आगे बढ़ने का हौसला देता है। 

तीन मुख्य सिद्धांत:
१. ज्ञान (Knowledge): जो आप सीखते हैं।
२. कौशल (Skills): जो आप कर सकते हैं।
३. नजरिया (Attitude): जो आप बनना चाहते हैं।

जब आप अपने काम में ईमानदारी, निष्ठा और समर्पण लाते हैं, तो सफलता खुद आपके कदम चूमती है। कभी हार मत मानो, क्योंकि हर असफलता अगली जीत की नींव होती है।"""
            ),
            # 4. Motivation (English)
            (
                "Atomic Habits", 
                "James Clear", 
                "978-0735211292", 
                "Motivation", 
                "English", 
                "Section MOTIV-2", 
                6, 4, 69.0, 49.0,
                """Chapter 1: The Surprising Power of Atomic Habits

Success is the product of daily habits—not once-in-a-lifetime transformations. If you get 1 percent better each day for one year, you'll end up thirty-seven times better by the time you're done.

The 4 Laws of Behavior Change:
1. Make it Obvious: Design your environment so the cues of good habits are visible.
2. Make it Attractive: Pair an action you want to do with an action you need to do.
3. Make it Easy: Reduce friction. Focus on the two-minute rule to start.
4. Make it Satisfying: Give yourself an immediate reward when you complete your habit.

You do not rise to the level of your goals. You fall to the level of your systems."""
            ),
            # 5. Sports (English)
            (
                "Playing It My Way", 
                "Sachin Tendulkar", 
                "978-1473605206", 
                "Sports", 
                "English", 
                "Section SPORTS-1", 
                4, 3, 69.0, 49.0,
                """Chapter 1: Childhood in Bandra & Shivaji Park

Cricket was not just a game for me; it was oxygen. Under the guidance of my guru, Achrekar Sir, every single day began before sunrise. Sir used to place a one-rupee coin on top of the stumps, and if I didn't get bowled all day, the coin was mine. I still treasure those coins more than any medal.

The 2011 World Cup Dream:
Winning the World Cup at Wankhede Stadium in front of our home crowd was the culmination of a 22-year dream. When Virat and Yusuf lifted me on their shoulders, it wasn't just my journey—it was the collective spirit of a billion Indians."""
            ),
            # 6. Sports (Hindi)
            (
                "मेजर ध्यानचंद: हॉकी के जादूगर", 
                "रोहित भार्गव", 
                "978-8176465431", 
                "Sports", 
                "Hindi", 
                "Section SPORTS-2", 
                4, 4, 69.0, 49.0,
                """अध्याय १: झाँसी से बर्लिन का स्वर्णिम सफर

मेजर ध्यानचंद केवल एक खिलाड़ी नहीं थे, वे भारतीय खेल जगत की अमर गाथा हैं। उनके पास गेंद ऐसी चिपकती थी कि विरोधी देश उनकी हॉकी स्टिक को तोड़कर देखते थे कि कहीं उसमें चुंबक तो नहीं लगा।

१९३६ बर्लिन ओलंपिक का ऐतिहासिक क्षण:
जर्मनी में हिटलर की मौजूदगी में भारतीय हॉकी टीम ने स्वर्ण पदक जीता। मैच के बाद हिटलर ने ध्यानचंद को जर्मन सेना में कर्नल बनने का प्रस्ताव दिया, लेकिन ध्यानचंद ने गर्व से कहा: "मेरा भारत देश बिकाऊ नहीं है, मैं केवल भारत के लिए खेलता हूँ।" यह देशभक्ति और खेल भावना आज भी हर युवा के लिए प्रेरणा है।"""
            ),
            # 7. Technology / Tech (English)
            (
                "Python & AI Development Masterclass", 
                "Dr. Alan Turing & Team", 
                "978-0132350884", 
                "Technology", 
                "English", 
                "Section TECH-1", 
                5, 4, 69.0, 49.0,
                """Chapter 1: Architecture of Modern Intelligent Systems

Python has emerged as the lingua franca of Artificial Intelligence and Data Science. From clean web frameworks like Flask and Django to deep learning libraries like PyTorch and TensorFlow, simplicity meets computational power.

Key Tenets of Clean Code in Python:
- Readability counts: Write code that humans can understand.
- Explicit is better than implicit.
- Modularize your business logic away from database drivers and presentation layers.
- Embrace automated testing, type hinting, and virtual environments for reproducible production builds."""
            ),
            # 8. Technology / Tech (English)
            (
                "Cloud Computing & Web Architecture", 
                "Martin Fowler", 
                "978-0201616224", 
                "Tech", 
                "English", 
                "Section TECH-2", 
                3, 3, 69.0, 49.0,
                """Chapter 1: Designing Resilient Microservices

Distributed systems require thinking about fault tolerance from day zero. When designing client-server applications, decoupling state through stateless APIs, utilizing persistent storage engines like SQLite and PostgreSQL, and caching hot reads ensures high availability.

Security in the Modern Cloud:
Never store plain-text passwords. Always implement salting and hashing algorithms like PBKDF2 or bcrypt, enforce role-based access control (RBAC), and use CSRF protection on critical state-mutating actions."""
            ),
            # 9. Science (Hindi/English)
            (
                "अग्नि की उड़ान (Wings of Fire)", 
                "डॉ. ए. पी. जे. अब्दुल कलाम", 
                "978-8172235000", 
                "Science", 
                "Hindi", 
                "Section SCI-1", 
                5, 4, 69.0, 49.0,
                """अध्याय १: रामेश्वरम की गलियों से अंतरिक्ष तक

"सपने वो नहीं जो हम सोते हुए देखते हैं, सपने वो हैं जो हमें सोने नहीं देते।"

रामेश्वरम में अखबार बांटने वाले एक साधारण बालक से भारत के मिसाइल मैन और राष्ट्रपति बनने का सफर केवल एक व्यक्ति का नहीं, बल्कि हर संघर्षशील भारतीय की उम्मीदों की उड़ान है।

विज्ञान और राष्ट्र निर्माण:
एसएलवी-३ (SLV-3) और अग्नि-पृथ्वी मिसाइलों का सफल प्रक्षेपण साबित करता है कि जब अटूट संकल्प, वैज्ञानिक दृष्टिकोण और राष्ट्रप्रेम एक साथ मिल जाएं, तो कोई भी बाधा देश को महाशक्ति बनने से नहीं रोक सकती। युवाओं, अपने पंखों को पहचानो और आकाश को छूने का साहस करो!"""
            ),
            # 10. Science (English)
            (
                "A Brief History of Time", 
                "Stephen Hawking", 
                "978-0553380163", 
                "Science", 
                "English", 
                "Section SCI-2", 
                4, 3, 69.0, 49.0,
                """Chapter 1: Our Picture of the Universe

A well-known scientist once gave a public lecture on astronomy. At the end, a little old lady at the back said: "What you have told us is rubbish. The world is really a flat plate supported on the back of a giant tortoise." When the scientist asked what supports the tortoise, she replied: "It's turtles all the way down!"

The Nature of Time and Black Holes:
Time is not absolute. Einstein showed that gravity bends space and time. In extreme gravitational collapse, matter forms a singularity where the laws of physics as we know them break down. Yet, through quantum mechanics, black holes emit radiation—now known as Hawking Radiation—and slowly evaporate over cosmic eons."""
            ),
            # 11. Psychology (English)
            (
                "Thinking, Fast and Slow", 
                "Daniel Kahneman", 
                "978-0374533557", 
                "Psychology", 
                "English", 
                "Section PSY-1", 
                4, 3, 69.0, 49.0,
                """Part 1: Two Systems of Thought

System 1 operates automatically and quickly, with little or no effort and no sense of voluntary control (Intuition).
System 2 allocates attention to effortful mental operations, including complex computations, critical thinking, and conscious deliberation.

Cognitive Biases & Decision Making:
We suffer from confirmation bias, the halo effect, and loss aversion (losses loom larger than gains). Recognizing the interplay between System 1's rapid heuristics and System 2's rational oversight is the key to mastering both personal decisions and professional leadership."""
            ),
            # 12. Psychology (Hindi)
            (
                "मन की शक्ति और सफलता (The Power of Subconscious Mind)", 
                "डॉ. जोसेफ मर्फी", 
                "978-9381860083", 
                "Psychology", 
                "Hindi", 
                "Section PSY-2", 
                5, 4, 69.0, 49.0,
                """अध्याय १: आपके भीतर का असीम खज़ाना

आपका अवचेतन मन (Subconscious Mind) एक उपजाऊ बगीचे की तरह है। इसमें आप जैसे बीज (विचार) बोएंगे, वैसी ही फसल (जीवन की परिस्थितियां) काटेंगे।

सकारात्मक आत्म-संवाद की विधि:
१. रात को सोने से पहले अपने मन को शांत करें और सफलता, स्वास्थ्य व शांति की कल्पना करें।
२. डर और शंका के विचारों को तुरंत दृढ़ विश्वास में बदलें।
३. जैसा आप अपने मन की गहराई में विश्वास करते हैं, आपका मस्तिष्क उसी के अनुसार अवसर और ऊर्जा आकर्षित करता है।"""
            )
        ]

        cursor.executemany("""
            INSERT INTO books (title, author, isbn, category, language, shelf_location, total_copies, available_copies, normal_price, ebook_price, content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, books_data)

        # Seed initial loans and payments for Student 1 (STU-1001)
        today = date.today()

        # 1. Active E-Book Loan for Rahul (Atomic Habits) - Can read online!
        e_due = today + timedelta(days=10)
        cursor.execute("""
            INSERT INTO transactions (book_id, user_id, issue_date, due_date, loan_type, fee_paid, status)
            VALUES (4, 2, ?, ?, 'ebook', 49.0, 'Issued')
        """, (today.isoformat(), e_due.isoformat()))
        t1_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO payments (user_id, transaction_id, amount, payment_type, payment_method)
            VALUES (2, ?, 49.0, 'borrow_fee', 'Online UPI')
        """, (t1_id,))

        # 2. Overdue Normal Book Loan (Jeet Aapki) - 6 days late, Fine applicable
        o_issue = today - timedelta(days=20)
        o_due = o_issue + timedelta(days=14)
        if o_due.weekday() == 6:
            o_due += timedelta(days=1)
        cursor.execute("""
            INSERT INTO transactions (book_id, user_id, issue_date, due_date, loan_type, fee_paid, fine_amount, fine_status, status)
            VALUES (3, 2, ?, ?, 'normal', 69.0, 30.0, 'pending', 'Issued')
        """, (o_issue.isoformat(), o_due.isoformat()))
        t2_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO payments (user_id, transaction_id, amount, payment_type, payment_method)
            VALUES (2, ?, 69.0, 'borrow_fee', 'Library Desk Cash')
        """, (t2_id,))

        # 3. An Expired E-Book (Playing It My Way) - Loan expired 3 days ago -> Locked online!
        exp_issue = today - timedelta(days=17)
        exp_due = exp_issue + timedelta(days=14)
        cursor.execute("""
            INSERT INTO transactions (book_id, user_id, issue_date, due_date, loan_type, fee_paid, fine_amount, fine_status, status)
            VALUES (5, 2, ?, ?, 'ebook', 49.0, 15.0, 'pending', 'Issued')
        """, (exp_issue.isoformat(), exp_due.isoformat()))
        t3_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO payments (user_id, transaction_id, amount, payment_type, payment_method)
            VALUES (2, ?, 49.0, 'borrow_fee', 'Online Card')
        """, (t3_id,))

        # 4. Reserved Physical Book for Store Pickup (Wings of Fire)
        res_due = calculate_due_date(STANDARD_LOAN_DAYS) if 'calculate_due_date' in globals() else (today + timedelta(days=14))
        cursor.execute("""
            INSERT INTO transactions (book_id, user_id, issue_date, due_date, loan_type, fee_paid, status)
            VALUES (9, 2, ?, ?, 'normal', 69.0, 'Reserved')
        """, (today.isoformat(), res_due.isoformat()))
        t4_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO payments (user_id, transaction_id, amount, payment_type, payment_method)
            VALUES (2, ?, 69.0, 'borrow_fee', 'UPI QR Code (Ref: RES-92810)')
        """, (t4_id,))
        # Decrement copy count for the reserved copy
        cursor.execute("UPDATE books SET available_copies = available_copies - 1 WHERE id = 9")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database updated and initialized successfully at:", DB_NAME)
