import os
import unittest
from datetime import date, timedelta
from app import app
from database import init_db, get_db_connection

class TestLMS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_01_admin_login_without_gmail(self):
        # Admin logs in using Username 'admin' (not gmail)
        res = self.app.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Admin Command Center', res.data)

    def test_02_student_login(self):
        # Student logs in with Roll No 'STU-1001'
        res = self.app.post('/login', data={'username': 'STU-1001', 'password': 'student123'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Student Portal', res.data)
        self.assertIn(b'Rahul Sharma', res.data)

    def test_03_student_issue_ebook_online(self):
        with self.app.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'STU-1001'
            sess['name'] = 'Rahul Sharma'
            sess['role'] = 'student'

        # Student issues E-Book (Book ID 1, Gita)
        res = self.app.post('/student/issue', data={'book_id': 1, 'loan_type': 'ebook', 'utr_ref': 'UPI-TEST-101'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'E-Book', res.data)

        # Check DB
        conn = get_db_connection()
        trans = conn.execute("SELECT * FROM transactions WHERE user_id = 2 AND book_id = 1 AND loan_type = 'ebook'").fetchone()
        self.assertIsNotNone(trans)
        self.assertEqual(trans['status'], 'Issued')
        self.assertEqual(trans['fee_paid'], 49.0)

        # Student reads online
        res_read = self.app.get(f'/student/read/{trans["id"]}')
        self.assertEqual(res_read.status_code, 200)
        self.assertIn(b'Distraction-Free Reading Mode', res_read.data)
        conn.close()

    def test_04_student_reserve_physical_book_for_store_pickup(self):
        with self.app.session_transaction() as sess:
            sess['user_id'] = 2
            sess['username'] = 'STU-1001'
            sess['name'] = 'Rahul Sharma'
            sess['role'] = 'student'

        # Student books Physical Book (Book ID 2, The Power of Now) for store pickup
        res = self.app.post('/student/issue', data={'book_id': 2, 'loan_type': 'normal', 'utr_ref': 'UPI-TEST-102'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Booked for Store Pickup', res.data)

        # Check DB
        conn = get_db_connection()
        trans = conn.execute("SELECT * FROM transactions WHERE user_id = 2 AND book_id = 2 AND loan_type = 'normal'").fetchone()
        self.assertIsNotNone(trans)
        self.assertEqual(trans['status'], 'Reserved')
        self.assertEqual(trans['fee_paid'], 69.0)

        # Check student dashboard has the reservation and instructions
        res_dash = self.app.get('/student/dashboard')
        self.assertIn(b'Booked for Store Pickup', res_dash.data)
        self.assertIn(b'Store par jaake le lunga', res_dash.data)
        # Verify student CANNOT return online (no return button)
        self.assertNotIn(b'action="/student/return', res_dash.data)
        conn.close()

    def test_05_admin_confirm_handover_and_return(self):
        with self.app.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['name'] = 'Chief Librarian'
            sess['role'] = 'admin'

        conn = get_db_connection()
        trans = conn.execute("SELECT * FROM transactions WHERE user_id = 2 AND book_id = 2 AND status = 'Reserved'").fetchone()
        self.assertIsNotNone(trans)
        trans_id = trans['id']

        # Admin confirms store pickup handover
        res_handover = self.app.post(f'/admin/handover/{trans_id}', follow_redirects=True)
        self.assertEqual(res_handover.status_code, 200)
        self.assertIn(b'Handover Confirmed', res_handover.data)

        # Verify status is now 'Issued'
        trans_after = conn.execute("SELECT * FROM transactions WHERE id = ?", (trans_id,)).fetchone()
        self.assertEqual(trans_after['status'], 'Issued')

        # Admin confirms return at desk
        res_return = self.app.post(f'/admin/return/{trans_id}', follow_redirects=True)
        self.assertEqual(res_return.status_code, 200)
        self.assertIn(b'returned', res_return.data)

        # Verify status is now 'Returned'
        trans_returned = conn.execute("SELECT * FROM transactions WHERE id = ?", (trans_id,)).fetchone()
        self.assertEqual(trans_returned['status'], 'Returned')
        conn.close()

    def test_06_admin_waive_fine(self):
        with self.app.session_transaction() as sess:
            sess['user_id'] = 1
            sess['username'] = 'admin'
            sess['name'] = 'Chief Librarian'
            sess['role'] = 'admin'

        conn = get_db_connection()
        # Find transaction 2 (overdue loan)
        trans = conn.execute("SELECT * FROM transactions WHERE id = 2").fetchone()
        if trans:
            res_waive = self.app.post(f'/admin/waive-fine/{trans["id"]}', follow_redirects=True)
            self.assertEqual(res_waive.status_code, 200)
            self.assertIn(b'WAIVED', res_waive.data)
        conn.close()

if __name__ == '__main__':
    unittest.main()
