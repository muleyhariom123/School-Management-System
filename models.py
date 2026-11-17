import sqlite3
import os
from datetime import datetime
from flask import g, current_app, request
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

def get_db():
    """Get a database connection for current request context."""
    if 'db' not in g:
        db_path = current_app.config.get('DATABASE_PATH', Config.DATABASE_PATH)
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON;")
    return g.db

def close_db(e=None):
    """Close the database connection if open."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db(app=None):
    """Initialize database tables and default configuration."""
    db_path = Config.DATABASE_PATH
    if app:
        db_path = app.config.get('DATABASE_PATH', db_path)

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    cursor = conn.cursor()

    # School settings
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS school_settings (
        id INTEGER PRIMARY KEY,
        school_name TEXT NOT NULL DEFAULT '[ENTER YOUR SCHOOL NAME]',
        school_address TEXT DEFAULT '',
        school_phone TEXT DEFAULT '',
        school_email TEXT DEFAULT '',
        school_website TEXT DEFAULT '',
        headmaster_name TEXT DEFAULT '',
        currency_symbol TEXT DEFAULT '$',
        logo_path TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Academic years
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS academic_years (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        start_date DATE,
        end_date DATE,
        is_current INTEGER DEFAULT 0
    );
    """)

    # School sections (Primary, Middle, High, etc.)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS school_sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1
    );
    """)

    # Classes (linked to section)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section_id INTEGER NOT NULL REFERENCES school_sections(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        display_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        UNIQUE(section_id, name)
    );
    """)

    # Class sections (A, B, C, etc.)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS class_sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
        section_name TEXT NOT NULL,
        capacity INTEGER DEFAULT 40,
        UNIQUE(class_id, section_name)
    );
    """)

    # Users
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin', 'teacher', 'student')),
        full_name TEXT NOT NULL,
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Students
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
        admission_number TEXT NOT NULL UNIQUE,
        full_name TEXT NOT NULL,
        photo_path TEXT DEFAULT '',
        dob DATE,
        gender TEXT,
        school_section_id INTEGER REFERENCES school_sections(id) ON DELETE RESTRICT,
        class_id INTEGER REFERENCES classes(id) ON DELETE RESTRICT,
        class_section_id INTEGER REFERENCES class_sections(id) ON DELETE RESTRICT,
        roll_number TEXT DEFAULT '',
        admission_date DATE,
        academic_year_id INTEGER REFERENCES academic_years(id) ON DELETE RESTRICT,
        father_name TEXT DEFAULT '',
        mother_name TEXT DEFAULT '',
        guardian_name TEXT DEFAULT '',
        guardian_phone TEXT DEFAULT '',
        emergency_contact TEXT DEFAULT '',
        residential_address TEXT DEFAULT '',
        previous_school TEXT DEFAULT '',
        student_email TEXT DEFAULT '',
        status TEXT DEFAULT 'Active' CHECK(status IN ('Active', 'Archived', 'Suspended')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Teachers
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
        employee_id TEXT NOT NULL UNIQUE,
        full_name TEXT NOT NULL,
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        qualification TEXT DEFAULT '',
        photo_path TEXT DEFAULT '',
        joining_date DATE,
        status TEXT DEFAULT 'Active' CHECK(status IN ('Active', 'Archived', 'Inactive'))
    );
    """)

    # Teacher Class Assignments
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teacher_class_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
        class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
        class_section_id INTEGER REFERENCES class_sections(id) ON DELETE CASCADE,
        subject TEXT DEFAULT '',
        UNIQUE(teacher_id, class_id, class_section_id, subject)
    );
    """)

    # Fee structures
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fee_structures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        academic_year_id INTEGER NOT NULL REFERENCES academic_years(id) ON DELETE CASCADE,
        school_section_id INTEGER REFERENCES school_sections(id) ON DELETE SET NULL,
        class_id INTEGER REFERENCES classes(id) ON DELETE CASCADE,
        fee_category TEXT NOT NULL,
        amount REAL NOT NULL CHECK(amount >= 0),
        due_date DATE,
        description TEXT DEFAULT ''
    );
    """)

    # Student fee assignments
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS student_fee_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        fee_structure_id INTEGER NOT NULL REFERENCES fee_structures(id) ON DELETE RESTRICT,
        academic_year_id INTEGER NOT NULL REFERENCES academic_years(id) ON DELETE RESTRICT,
        assigned_amount REAL NOT NULL CHECK(assigned_amount >= 0),
        concession_amount REAL DEFAULT 0.0 CHECK(concession_amount >= 0),
        concession_reason TEXT DEFAULT '',
        status TEXT DEFAULT 'Pending' CHECK(status IN ('Pending', 'Partial', 'Paid')),
        assigned_date DATE,
        UNIQUE(student_id, fee_structure_id)
    );
    """)

    # Payment transactions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payment_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_number TEXT NOT NULL UNIQUE,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        student_fee_assignment_id INTEGER REFERENCES student_fee_assignments(id) ON DELETE SET NULL,
        amount_paid REAL NOT NULL CHECK(amount_paid > 0),
        payment_date DATE NOT NULL,
        payment_method TEXT NOT NULL CHECK(payment_method IN ('Cash', 'UPI', 'Bank Transfer', 'Cheque')),
        transaction_reference TEXT DEFAULT '',
        remarks TEXT DEFAULT '',
        recorded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Attendance records
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
        class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
        class_section_id INTEGER NOT NULL REFERENCES class_sections(id) ON DELETE CASCADE,
        date DATE NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('Present', 'Absent', 'Late', 'Excused')),
        remarks TEXT DEFAULT '',
        recorded_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(student_id, date)
    );
    """)

    # Notices & Announcements
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        target_type TEXT NOT NULL CHECK(target_type IN ('all', 'section', 'class')),
        target_section_id INTEGER REFERENCES school_sections(id) ON DELETE SET NULL,
        target_class_id INTEGER REFERENCES classes(id) ON DELETE SET NULL,
        publish_date DATE NOT NULL,
        expiry_date DATE,
        is_active INTEGER DEFAULT 1,
        author_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Audit logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        username TEXT DEFAULT '',
        action TEXT NOT NULL,
        target_entity TEXT DEFAULT '',
        target_id TEXT DEFAULT '',
        details TEXT DEFAULT '',
        ip_address TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Indexes for fast lookup
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_students_adm ON students(admission_number);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance_records(date, class_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_payments_student ON payment_transactions(student_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fee_assign_student ON student_fee_assignments(student_id);")

    # Insert default school settings row if none exists
    cursor.execute("SELECT id FROM school_settings WHERE id = 1;")
    if not cursor.fetchone():
        cursor.execute("""
        INSERT INTO school_settings (id, school_name, school_address, school_phone, school_email, school_website, headmaster_name, currency_symbol, logo_path)
        VALUES (1, '[ENTER YOUR SCHOOL NAME]', '123 Education Boulevard, Knowledge City', '+1 (555) 019-2834', 'info@school.edu', 'https://school.edu', 'Headmaster Office', '$', '');
        """)

    conn.commit()
    conn.close()


class User(UserMixin):
    """User representation for Flask-Login."""
    def __init__(self, id, username, role, full_name, email='', is_active=1, student_id=None, teacher_id=None, password_hash=None):
        self.id = id
        self.username = username
        self.role = role
        self.full_name = full_name
        self.email = email
        self._is_active = bool(is_active)
        self.student_id = student_id
        self.teacher_id = teacher_id
        self.password_hash = password_hash

    @property
    def is_active(self):
        return self._is_active

    def set_password(self, raw_password):
        """Hash and store a user password."""
        self.password_hash = generate_password_hash(raw_password)
        return self.password_hash

    def check_password(self, raw_password):
        """Verify a raw password against the stored hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)

    @staticmethod
    def _build_from_row(row):
        db = get_db()
        student_id = None
        teacher_id = None
        if row['role'] == 'student':
            s_row = db.execute("SELECT id FROM students WHERE user_id = ?", (row['id'],)).fetchone()
            if s_row:
                student_id = s_row['id']
        elif row['role'] == 'teacher':
            t_row = db.execute("SELECT id FROM teachers WHERE user_id = ?", (row['id'],)).fetchone()
            if t_row:
                teacher_id = t_row['id']

        password_hash = row['password_hash'] if 'password_hash' in row.keys() else None
        return User(
            id=row['id'],
            username=row['username'],
            role=row['role'],
            full_name=row['full_name'],
            email=row['email'],
            is_active=row['is_active'],
            student_id=student_id,
            teacher_id=teacher_id,
            password_hash=password_hash
        )

    @staticmethod
    def get_by_id(user_id):
        db = get_db()
        cursor = db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return User._build_from_row(row)

    @staticmethod
    def get_by_username(username):
        db = get_db()
        cursor = db.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            return None
        return User._build_from_row(row)


def get_school_settings():
    """Retrieve school branding and global configurations."""
    db = get_db()
    row = db.execute("SELECT * FROM school_settings WHERE id = 1;").fetchone()
    if row:
        return dict(row)
    return {
        'school_name': '[ENTER YOUR SCHOOL NAME]',
        'school_address': '',
        'school_phone': '',
        'school_email': '',
        'school_website': '',
        'headmaster_name': '',
        'currency_symbol': '$',
        'logo_path': ''
    }


def log_audit(action, target_entity='', target_id='', details='', user_id=None, username=None, ip=None):
    """Save an immutable audit trail entry."""
    try:
        db = get_db()
        if not ip:
            try:
                ip = request.remote_addr if request else '127.0.0.1'
            except Exception:
                ip = '127.0.0.1'
        db.execute("""
            INSERT INTO audit_logs (user_id, username, action, target_entity, target_id, details, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username or 'System', action, str(target_entity), str(target_id), str(details), ip))
        db.commit()
    except Exception as e:
        print(f"Error logging audit: {e}")


def get_student_financial_summary(student_id):
    """
    Calculate financial totals for a student:
    Outstanding Balance = Total Assigned Fees - Total Payments - Applicable Approved Concessions
    """
    db = get_db()
    # Assigned and concessions
    fee_row = db.execute("""
        SELECT 
            COALESCE(SUM(assigned_amount), 0.0) as total_assigned,
            COALESCE(SUM(concession_amount), 0.0) as total_concession
        FROM student_fee_assignments
        WHERE student_id = ?
    """, (student_id,)).fetchone()
    total_assigned = float(fee_row['total_assigned'] or 0.0)
    total_concession = float(fee_row['total_concession'] or 0.0)

    # Payments recorded
    pay_row = db.execute("""
        SELECT COALESCE(SUM(amount_paid), 0.0) as total_paid
        FROM payment_transactions
        WHERE student_id = ?
    """, (student_id,)).fetchone()
    total_paid = float(pay_row['total_paid'] or 0.0)

    outstanding = max(0.0, total_assigned - total_paid - total_concession)
    return {
        'total_assigned': total_assigned,
        'total_concession': total_concession,
        'total_paid': total_paid,
        'outstanding_balance': outstanding
    }
