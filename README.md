# CLONE --- Library Management System ---

# Complete Library Management System (LMS)

A complete, full-featured **Library Management System** built with **Python (Flask)**, **SQLite**, and styled using modern **Tailwind CSS** with **Lucide Icons**.

---

##  Key Features

1. **Authentication (No Gmail Needed!)**:
   - **Admin Login:**
     - Username: `admin`
     - Password: `admin123`
     - Full control over catalog, students, circulation desk, notices, and timings.
   - **Student Login:**
     - Student ID: `STU-1001` (or custom roll number)
     - Password: `student123`
     - Self-service registration for new students.

2. **Dedicated Dual Dashboards**:
   - **Admin Command Center:**
     - Live statistics: Total titles, physical copies, shelf available, active loans, overdue count, and fine revenue.
     - Quick circulation checkout form.
     - Dynamic Notice Board editor.
   - **Student Self-Service Portal:**
     - View currently borrowed books.
     - Live countdown of days left before return due date.
     - Penalty/fine calculator and alerts.
     - Past returned loans history.
     - Browse full library catalog with shelf locations.

3. **Smart Library Schedule & Sunday Off System**:
   - **Working Hours:** 8:00 AM – 8:00 PM (Monday to Saturday).
   - **Sunday Closed:** Every Sunday is marked as **CLOSED (Weekly Off)**.
   - **Live Open/Closed Status Badge:** Real-time clock checks whether the library is currently Open or Closed.
   - **Smart Due Date Rollover:** If a 14-day loan return date lands on a Sunday, the system automatically extends the return date to **Monday** with zero penalty!

4. **Book Inventory with Shelf Locations**:
   - Title, Author, ISBN, Category, and **Shelf Location** (e.g., Section CS-1, Section LIT-2).
   - Real-time search and category filtering.
   - Add, edit, and delete books (with active loan protection).

5. **Circulation & Automatic Late Fine**:
   - Issue book (tracks copies automatically).
   - Return book (calculates late fine at ₹5.00/day).

---

##  How to Run

### Method 1: Double-click Launcher (Windows)
Double-click `run.bat` in this folder.

### Method 2: From Terminal / PowerShell
```powershell
cd "C:\Users\Ayush Singh\.gemini\antigravity\scratch\library_management_system"

# Run the web application
python app.py
```
Open your browser and visit: **http://127.0.0.1:5000**

### Method 3: Terminal CLI Mode (No browser needed)
```powershell
cd "C:\Users\Ayush Singh\.gemini\antigravity\scratch\library_management_system"
python cli.py
```
*(Or double-click `run_cli.bat`)*

---

##  Login Credentials

| Role | Login Identifier (No Gmail!) | Password | Capabilities |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin` | `admin123` | Full library control, circulation, students, notices |
| **Student** | `STU-1001` | `student123` | View personal borrowed books, countdowns, fines, catalog |
| **Student 2** | `STU-1002` | `student123` | Test multi-student borrowing |
| **...etc**
