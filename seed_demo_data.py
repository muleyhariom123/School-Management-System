import os
import sqlite3
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash
from config import Config
from models import init_db

def seed_data():
    """Populate realistic fictional sample data for initial demonstration and testing."""
    print("Initializing database...")
    init_db()

    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()

    # 1. Academic Year
    cur.execute("INSERT OR IGNORE INTO academic_years (id, name, start_date, end_date, is_current) VALUES (1, '2026-2027', '2026-06-01', '2027-05-31', 1);")

    # 2. School Sections
    sections_data = [
        (1, 'Primary School', 'Classes 1 to 5 - Foundational Stage', 1),
        (2, 'Middle School', 'Classes 6 to 8 - Preparatory & Middle Stage', 1),
        (3, 'High School', 'Classes 9 to 10 - Secondary Stage', 1),
        (4, 'Senior Secondary', 'Classes 11 to 12 - Higher Secondary Stage', 1),
    ]
    for sid, sname, sdesc, sact in sections_data:
        cur.execute("INSERT OR IGNORE INTO school_sections (id, name, description, is_active) VALUES (?, ?, ?, ?);", (sid, sname, sdesc, sact))

    # 3. Classes and Divisions
    classes_data = [
        # Primary
        (1, 1, 'Class 1', 1),
        (2, 1, 'Class 2', 2),
        (3, 1, 'Class 3', 3),
        (4, 1, 'Class 4', 4),
        (5, 1, 'Class 5', 5),
        # Middle
        (6, 2, 'Class 6', 6),
        (7, 2, 'Class 7', 7),
        (8, 2, 'Class 8', 8),
        # High
        (9, 3, 'Class 9', 9),
        (10, 3, 'Class 10', 10),
    ]
    for cid, sec_id, cname, dorder in classes_data:
        cur.execute("INSERT OR IGNORE INTO classes (id, section_id, name, display_order, is_active) VALUES (?, ?, ?, ?, 1);", (cid, sec_id, cname, dorder))
        # Add sections A and B
        cur.execute("INSERT OR IGNORE INTO class_sections (class_id, section_name, capacity) VALUES (?, 'A', 35);", (cid,))
        cur.execute("INSERT OR IGNORE INTO class_sections (class_id, section_name, capacity) VALUES (?, 'B', 35);", (cid,))

    # 4. Admin User (Headmaster)
    admin_pw = generate_password_hash('Admin@2026')
    cur.execute("""
        INSERT OR IGNORE INTO users (id, username, password_hash, role, full_name, email, phone, is_active)
        VALUES (1, 'admin', ?, 'admin', 'Dr. Arthur Pendelton', 'headmaster@school.edu', '+1 (555) 019-1001', 1);
    """, (admin_pw,))

    # Update School Settings
    cur.execute("""
        UPDATE school_settings
        SET school_name = '[ENTER YOUR SCHOOL NAME]',
            school_address = '100 Academic Way, Knowledge Valley, Suite 400',
            school_phone = '+1 (555) 019-2834',
            school_email = 'admissions@school.edu',
            school_website = 'https://www.school.edu',
            headmaster_name = 'Dr. Arthur Pendelton',
            currency_symbol = '$',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1;
    """)

    # 5. Faculty / Teachers
    teachers_data = [
        (2, 'emp01', 'Prof. Eleanor Vance', 'eleanor.vance@school.edu', '+1 (555) 019-2001', 'M.Sc. Mathematics, B.Ed.', '2023-08-01', 'Mathematics', 10), # Class 10
        (3, 'emp02', 'Mr. David Miller', 'david.miller@school.edu', '+1 (555) 019-2002', 'M.A. English Literature', '2024-01-15', 'English', 6), # Class 6
        (4, 'emp03', 'Mrs. Clara Higgins', 'clara.higgins@school.edu', '+1 (555) 019-2003', 'B.Sc. Elementary Ed', '2022-07-10', 'General Science', 3), # Class 3
    ]
    for uid, empid, tname, temail, tphone, tqual, tjoin, tsubj, tclass in teachers_data:
        pw = generate_password_hash(f"Teach@{empid}")
        cur.execute("""
            INSERT OR IGNORE INTO users (id, username, password_hash, role, full_name, email, phone, is_active)
            VALUES (?, ?, ?, 'teacher', ?, ?, ?, 1);
        """, (uid, empid, pw, tname, temail, tphone))
        
        cur.execute("""
            INSERT OR IGNORE INTO teachers (user_id, employee_id, full_name, email, phone, qualification, joining_date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Active');
        """, (uid, empid, tname, temail, tphone, tqual, tjoin))
        tid = cur.lastrowid or 1
        
        # Get section A id for class
        sec_row = cur.execute("SELECT id FROM class_sections WHERE class_id = ? LIMIT 1;", (tclass,)).fetchone()
        sec_id = sec_row[0] if sec_row else 1
        cur.execute("""
            INSERT OR IGNORE INTO teacher_class_assignments (teacher_id, class_id, class_section_id, subject)
            VALUES (?, ?, ?, ?);
        """, (tid, tclass, sec_id, tsubj))

    # 6. Fee Structures
    # Add standard fees for Class 10, Class 6, Class 3
    fee_structs = [
        # Class 10
        (1, 1, 3, 10, 'Tuition Fee - Term 1', 1200.0, '2026-09-30', 'Standard academic tuition'),
        (2, 1, 3, 10, 'Science & Computer Lab Fee', 250.0, '2026-09-30', 'Practical laboratory fee'),
        (3, 1, 3, 10, 'Board Examination Fee', 150.0, '2026-11-15', 'Annual board examination charges'),
        # Class 6
        (4, 1, 2, 6, 'Tuition Fee - Term 1', 950.0, '2026-09-30', 'Middle school tuition'),
        (5, 1, 2, 6, 'Activity & Sports Fee', 120.0, '2026-09-30', 'Annual sports and clubs'),
        # Class 3
        (6, 1, 1, 3, 'Tuition Fee - Term 1', 800.0, '2026-09-30', 'Primary school tuition'),
        (7, 1, 1, 3, 'Arts & Learning Material', 100.0, '2026-09-30', 'Activity books and supplies'),
    ]
    for fid, ayid, secid, cid, cat, amt, ddate, desc in fee_structs:
        cur.execute("""
            INSERT OR IGNORE INTO fee_structures (id, academic_year_id, school_section_id, class_id, fee_category, amount, due_date, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, (fid, ayid, secid, cid, cat, amt, ddate, desc))

    # 7. Fictional Students
    students_data = [
        # (user_id, adm_no, name, dob, gender, sec_id, class_id, roll, father, mother, guard_phone, email, res_addr)
        (5, 'ADM-2026-0001', 'Liam Johnson', '2010-04-12', 'Male', 3, 10, '101', 'Mark Johnson', 'Sarah Johnson', '+1 (555) 234-5671', 'liam.j@example.com', '45 Elm Street, Springfield'),
        (6, 'ADM-2026-0002', 'Emma Williams', '2010-09-25', 'Female', 3, 10, '102', 'Robert Williams', 'Jessica Williams', '+1 (555) 234-5672', 'emma.w@example.com', '78 Maple Avenue, Springfield'),
        (7, 'ADM-2026-0003', 'Noah Brown', '2014-03-18', 'Male', 2, 6, '601', 'James Brown', 'Emily Brown', '+1 (555) 234-5673', 'noah.b@example.com', '12 Oak Lane, Riverdale'),
        (8, 'ADM-2026-0004', 'Olivia Jones', '2014-11-05', 'Female', 2, 6, '602', 'Michael Jones', 'Rachel Jones', '+1 (555) 234-5674', 'olivia.j@example.com', '89 Pine Road, Riverdale'),
        (9, 'ADM-2026-0005', 'Sophia Davis', '2017-06-20', 'Female', 1, 3, '301', 'William Davis', 'Amanda Davis', '+1 (555) 234-5675', 'sophia.d@example.com', '24 Cedar Drive, Hillcrest'),
        (10, 'ADM-2026-0006', 'Lucas Miller', '2017-08-14', 'Male', 1, 3, '302', 'Daniel Miller', 'Laura Miller', '+1 (555) 234-5676', 'lucas.m@example.com', '33 Willow Way, Hillcrest'),
    ]

    for uid, adm, sname, sdob, sgen, secid, cid, roll, fat, mot, phone, semail, addr in students_data:
        pw = generate_password_hash(f"Stu@{adm}")
        cur.execute("""
            INSERT OR IGNORE INTO users (id, username, password_hash, role, full_name, email, phone, is_active)
            VALUES (?, ?, ?, 'student', ?, ?, ?, 1);
        """, (uid, adm.lower(), pw, sname, semail, phone))

        # Class section
        csec_row = cur.execute("SELECT id FROM class_sections WHERE class_id = ? LIMIT 1;", (cid,)).fetchone()
        csec_id = csec_row[0] if csec_row else 1

        cur.execute("""
            INSERT OR IGNORE INTO students (
                id, user_id, admission_number, full_name, photo_path, dob, gender,
                school_section_id, class_id, class_section_id, roll_number,
                admission_date, academic_year_id, father_name, mother_name,
                guardian_name, guardian_phone, emergency_contact, residential_address,
                previous_school, student_email, status
            ) VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, '2026-06-01', 1, ?, ?, ?, ?, ?, ?, 'Oakridge Academy', ?, 'Active');
        """, (uid - 4, uid, adm, sname, sdob, sgen, secid, cid, csec_id, roll, fat, mot, fat, phone, phone, addr, semail))

    # 8. Assign fees and Record Payments
    # Student 1: Liam Johnson (Class 10) -> Assigned Tuition ($1200), Lab ($250), Exam ($150) = $1600.
    # Paid $1200 via UPI. Remaining = $400.
    cur.execute("""
        INSERT OR IGNORE INTO student_fee_assignments (id, student_id, fee_structure_id, academic_year_id, assigned_amount, concession_amount, status, assigned_date)
        VALUES (1, 1, 1, 1, 1200.0, 0.0, 'Paid', '2026-06-05');
    """)
    cur.execute("""
        INSERT OR IGNORE INTO student_fee_assignments (id, student_id, fee_structure_id, academic_year_id, assigned_amount, concession_amount, status, assigned_date)
        VALUES (2, 1, 2, 1, 250.0, 0.0, 'Pending', '2026-06-05');
    """)
    cur.execute("""
        INSERT OR IGNORE INTO student_fee_assignments (id, student_id, fee_structure_id, academic_year_id, assigned_amount, concession_amount, status, assigned_date)
        VALUES (3, 1, 3, 1, 150.0, 0.0, 'Pending', '2026-06-05');
    """)
    cur.execute("""
        INSERT OR IGNORE INTO payment_transactions (receipt_number, student_id, student_fee_assignment_id, amount_paid, payment_date, payment_method, transaction_reference, remarks, recorded_by_user_id)
        VALUES ('REC-2026-0001', 1, 1, 1200.0, '2026-06-10', 'UPI', 'UPI/983719283712', 'Full Term 1 tuition received via UPI', 1);
    """)

    # Student 2: Emma Williams (Class 10) -> Has $200 merit scholarship concession on Tuition.
    # Tuition $1200 - $200 concession = $1000. Paid $1000 + $250 Lab = $1250 total paid.
    cur.execute("""
        INSERT OR IGNORE INTO student_fee_assignments (id, student_id, fee_structure_id, academic_year_id, assigned_amount, concession_amount, concession_reason, status, assigned_date)
        VALUES (4, 2, 1, 1, 1200.0, 200.0, 'Approved Academic Merit Scholarship', 'Paid', '2026-06-05');
    """)
    cur.execute("""
        INSERT OR IGNORE INTO student_fee_assignments (id, student_id, fee_structure_id, academic_year_id, assigned_amount, concession_amount, status, assigned_date)
        VALUES (5, 2, 2, 1, 250.0, 0.0, 'Paid', '2026-06-05');
    """)
    cur.execute("""
        INSERT OR IGNORE INTO payment_transactions (receipt_number, student_id, student_fee_assignment_id, amount_paid, payment_date, payment_method, transaction_reference, remarks, recorded_by_user_id)
        VALUES ('REC-2026-0002', 2, 4, 1000.0, '2026-06-12', 'Bank Transfer', 'NEFT-AXIS-99214', 'Net tuition after approved merit scholarship', 1);
    """)
    cur.execute("""
        INSERT OR IGNORE INTO payment_transactions (receipt_number, student_id, student_fee_assignment_id, amount_paid, payment_date, payment_method, transaction_reference, remarks, recorded_by_user_id)
        VALUES ('REC-2026-0003', 2, 5, 250.0, '2026-06-12', 'Bank Transfer', 'NEFT-AXIS-99215', 'Lab fee payment', 1);
    """)

    # Student 3: Noah Brown (Class 6) -> Tuition $950, Sports $120. Paid $500 partial cash.
    cur.execute("""
        INSERT OR IGNORE INTO student_fee_assignments (id, student_id, fee_structure_id, academic_year_id, assigned_amount, concession_amount, status, assigned_date)
        VALUES (6, 3, 4, 1, 950.0, 0.0, 'Partial', '2026-06-05');
    """)
    cur.execute("""
        INSERT OR IGNORE INTO student_fee_assignments (id, student_id, fee_structure_id, academic_year_id, assigned_amount, concession_amount, status, assigned_date)
        VALUES (7, 3, 5, 1, 120.0, 0.0, 'Pending', '2026-06-05');
    """)
    cur.execute("""
        INSERT OR IGNORE INTO payment_transactions (receipt_number, student_id, student_fee_assignment_id, amount_paid, payment_date, payment_method, transaction_reference, remarks, recorded_by_user_id)
        VALUES ('REC-2026-0004', 3, 6, 500.0, '2026-06-15', 'Cash', 'CASH-REC-104', 'First installment received in cash', 1);
    """)

    # 9. Attendance Records (for today and previous days)
    today = date.today()
    for day_offset in range(5, -1, -1):
        dt = (today - timedelta(days=day_offset)).isoformat()
        # Mark attendance for all 6 students
        statuses = ['Present', 'Present', 'Present', 'Absent', 'Present', 'Late']
        for idx in range(1, 7):
            st_idx = (idx + day_offset) % len(statuses)
            st_val = statuses[st_idx]
            cur.execute("""
                INSERT OR IGNORE INTO attendance_records (student_id, class_id, class_section_id, date, status, remarks, recorded_by_user_id)
                VALUES (?, 10, 1, ?, ?, '', 1);
            """, (idx, dt, st_val))

    # 10. Notices
    notices_data = [
        ('Welcome to Academic Year 2026-2027', 'We extend a hearty welcome to all students, parents, and faculty. Please review your class syllabus and school guidelines for the upcoming term.', 'all', None, None, '2026-06-01', None, 1),
        ('High School Science Fair & Exhibition', 'High School students (Classes 9-10) are invited to register their science fair team projects by October 25th at the science laboratory.', 'section', 3, None, '2026-10-01', '2026-10-31', 1),
        ('Class 10 Pre-Board Assessment Schedule', 'Detailed schedule for Class 10 assessment examinations has been posted. Students should ensure all project logs are verified.', 'class', None, 10, '2026-10-05', '2026-11-10', 1),
    ]
    for title, content, ttype, tsec, tcls, pdate, edate, author in notices_data:
        cur.execute("""
            INSERT OR IGNORE INTO notices (title, content, target_type, target_section_id, target_class_id, publish_date, expiry_date, is_active, author_user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?);
        """, (title, content, ttype, tsec, tcls, pdate, edate, author))

    # 11. Initial Audit Logs
    cur.execute("""
        INSERT INTO audit_logs (user_id, username, action, target_entity, target_id, details, ip_address)
        VALUES (1, 'admin', 'SYSTEM_SEED', 'system', 'all', 'Seeded realistic initial demo records.', '127.0.0.1');
    """)

    conn.commit()
    conn.close()
    print("Database seeding completed successfully.")
    print("Default Test Accounts Available:")
    print("  [Headmaster / Admin]: Username: 'admin' | Password: 'Admin@2026'")
    print("  [Teacher - Class 10]:  Username: 'emp01' | Password: 'Teach@emp01'")
    print("  [Teacher - Class 6]:   Username: 'emp02' | Password: 'Teach@emp02'")
    print("  [Student - Class 10]:  Username: 'adm-2026-0001' | Password: 'Stu@ADM-2026-0001'")
    print("  [Student - Class 6]:   Username: 'adm-2026-0003' | Password: 'Stu@ADM-2026-0003'")

if __name__ == '__main__':
    seed_data()
