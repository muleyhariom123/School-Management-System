import os
import io
import csv
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app, Response
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from models import get_db, get_school_settings, log_audit, get_student_financial_summary
from utils.decorators import admin_required
from utils.helpers import save_uploaded_file, generate_receipt_number, generate_admission_number, format_currency
from utils.pdf_generator import generate_fee_receipt_pdf, generate_student_profile_pdf, generate_tabular_report_pdf

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.before_request
@login_required
@admin_required
def admin_before_request():
    """Ensure all admin routes require admin role."""
    pass

# ==================== 1. DASHBOARD ====================

@admin_bp.route('/dashboard')
def dashboard():
    db = get_db()
    today_str = date.today().isoformat()
    
    # Core Counts
    total_students = db.execute("SELECT COUNT(*) as cnt FROM students WHERE status = 'Active';").fetchone()['cnt']
    total_teachers = db.execute("SELECT COUNT(*) as cnt FROM teachers WHERE status = 'Active';").fetchone()['cnt']
    
    # Financial Totals
    fee_agg = db.execute("""
        SELECT 
            COALESCE(SUM(assigned_amount), 0.0) as total_assigned,
            COALESCE(SUM(concession_amount), 0.0) as total_concession
        FROM student_fee_assignments;
    """).fetchone()
    total_assigned = float(fee_agg['total_assigned'] or 0.0)
    total_concession = float(fee_agg['total_concession'] or 0.0)
    
    pay_agg = db.execute("SELECT COALESCE(SUM(amount_paid), 0.0) as total_paid FROM payment_transactions;").fetchone()
    total_collected = float(pay_agg['total_paid'] or 0.0)
    total_outstanding = max(0.0, total_assigned - total_collected - total_concession)
    
    # Today's Attendance summary
    att_agg = db.execute("""
        SELECT 
            COUNT(*) as total_marked,
            SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present_cnt,
            SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent_cnt,
            SUM(CASE WHEN status = 'Late' THEN 1 ELSE 0 END) as late_cnt,
            SUM(CASE WHEN status = 'Excused' THEN 1 ELSE 0 END) as excused_cnt
        FROM attendance_records
        WHERE date = ?;
    """, (today_str,)).fetchone()
    
    total_marked = att_agg['total_marked'] or 0
    present_cnt = att_agg['present_cnt'] or 0
    absent_cnt = att_agg['absent_cnt'] or 0
    late_cnt = att_agg['late_cnt'] or 0
    excused_cnt = att_agg['excused_cnt'] or 0
    attendance_rate = round((present_cnt / total_marked * 100), 1) if total_marked > 0 else 0
    
    # Students by Section
    section_dist = db.execute("""
        SELECT s.name as section_name, COUNT(st.id) as student_count
        FROM school_sections s
        LEFT JOIN students st ON st.school_section_id = s.id AND st.status = 'Active'
        GROUP BY s.id;
    """).fetchall()
    
    # Recent Admissions
    recent_students = db.execute("""
        SELECT s.*, c.name as class_name, cs.section_name as class_section_name
        FROM students s
        LEFT JOIN classes c ON s.class_id = c.id
        LEFT JOIN class_sections cs ON s.class_section_id = cs.id
        ORDER BY s.id DESC LIMIT 5;
    """).fetchall()
    
    # Recent Payments
    recent_payments = db.execute("""
        SELECT p.*, s.full_name as student_name, s.admission_number
        FROM payment_transactions p
        JOIN students s ON p.student_id = s.id
        ORDER BY p.id DESC LIMIT 5;
    """).fetchall()

    return render_template('admin/dashboard.html',
        settings=get_school_settings(),
        total_students=total_students,
        total_teachers=total_teachers,
        total_assigned=total_assigned,
        total_collected=total_collected,
        total_outstanding=total_outstanding,
        today_marked=total_marked,
        present_cnt=present_cnt,
        absent_cnt=absent_cnt,
        late_cnt=late_cnt,
        excused_cnt=excused_cnt,
        attendance_rate=attendance_rate,
        section_dist=section_dist,
        recent_students=recent_students,
        recent_payments=recent_payments
    )

# ==================== 2. SCHOOL SETTINGS ====================

@admin_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    db = get_db()
    current_settings = get_school_settings()
    
    if request.method == 'POST':
        school_name = request.form.get('school_name', '').strip() or '[ENTER YOUR SCHOOL NAME]'
        school_address = request.form.get('school_address', '').strip()
        school_phone = request.form.get('school_phone', '').strip()
        school_email = request.form.get('school_email', '').strip()
        school_website = request.form.get('school_website', '').strip()
        headmaster_name = request.form.get('headmaster_name', '').strip()
        currency_symbol = request.form.get('currency_symbol', '$').strip() or '$'
        
        logo_path = current_settings.get('logo_path', '')
        if 'logo' in request.files and request.files['logo'].filename:
            saved_logo = save_uploaded_file(request.files['logo'], subfolder='logos')
            if saved_logo:
                logo_path = saved_logo

        db.execute("""
            UPDATE school_settings 
            SET school_name = ?, school_address = ?, school_phone = ?, school_email = ?,
                school_website = ?, headmaster_name = ?, currency_symbol = ?, logo_path = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1;
        """, (school_name, school_address, school_phone, school_email, school_website, headmaster_name, currency_symbol, logo_path))
        db.commit()

        log_audit('UPDATE_SETTINGS', 'school_settings', '1', f"Updated school info: {school_name}", current_user.id, current_user.username)
        flash("School settings successfully updated! New details are now active across all dashboards, portals, and documents.", "success")
        return redirect(url_for('admin.settings'))

    return render_template('admin/settings.html', settings=current_settings)

# ==================== 3. SECTIONS, CLASSES & ACADEMIC YEARS ====================

@admin_bp.route('/sections-classes', methods=['GET'])
def sections_classes():
    db = get_db()
    sections = db.execute("SELECT * FROM school_sections ORDER BY id ASC;").fetchall()
    classes = db.execute("""
        SELECT c.*, s.name as section_name,
               (SELECT COUNT(*) FROM students st WHERE st.class_id = c.id AND st.status = 'Active') as student_count
        FROM classes c
        JOIN school_sections s ON c.section_id = s.id
        ORDER BY c.section_id, c.display_order, c.name ASC;
    """).fetchall()
    
    class_sections = db.execute("""
        SELECT cs.*, c.name as class_name,
               (SELECT COUNT(*) FROM students st WHERE st.class_section_id = cs.id AND st.status = 'Active') as student_count
        FROM class_sections cs
        JOIN classes c ON cs.class_id = c.id
        ORDER BY c.name, cs.section_name ASC;
    """).fetchall()
    
    academic_years = db.execute("SELECT * FROM academic_years ORDER BY id DESC;").fetchall()
    
    return render_template('admin/sections_classes.html',
        settings=get_school_settings(),
        sections=sections,
        classes=classes,
        class_sections=class_sections,
        academic_years=academic_years
    )

@admin_bp.route('/sections/add', methods=['POST'])
def add_section():
    db = get_db()
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    if name:
        try:
            db.execute("INSERT INTO school_sections (name, description, is_active) VALUES (?, ?, 1);", (name, description))
            db.commit()
            log_audit('CREATE_SECTION', 'school_sections', name, f"Created section: {name}", current_user.id, current_user.username)
            flash(f"School section '{name}' added successfully.", "success")
        except Exception as e:
            flash(f"Error adding section: {e}", "danger")
    return redirect(url_for('admin.sections_classes'))

@admin_bp.route('/sections/<int:section_id>/toggle', methods=['POST'])
def toggle_section(section_id):
    db = get_db()
    db.execute("UPDATE school_sections SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?;", (section_id,))
    db.commit()
    flash("Section status updated.", "info")
    return redirect(url_for('admin.sections_classes'))

@admin_bp.route('/classes/add', methods=['POST'])
def add_class():
    db = get_db()
    section_id = request.form.get('section_id')
    name = request.form.get('name', '').strip()
    order = request.form.get('display_order', 0)
    if section_id and name:
        try:
            cur = db.execute("INSERT INTO classes (section_id, name, display_order, is_active) VALUES (?, ?, ?, 1);", (section_id, name, order))
            # Also create default class section 'A'
            class_id = cur.lastrowid
            db.execute("INSERT INTO class_sections (class_id, section_name, capacity) VALUES (?, 'A', 40);", (class_id,))
            db.commit()
            log_audit('CREATE_CLASS', 'classes', str(class_id), f"Created class: {name}", current_user.id, current_user.username)
            flash(f"Class '{name}' created with default Section A.", "success")
        except Exception as e:
            flash(f"Error adding class: {e}", "danger")
    return redirect(url_for('admin.sections_classes'))

@admin_bp.route('/classes/<int:class_id>/toggle', methods=['POST'])
def toggle_class(class_id):
    db = get_db()
    db.execute("UPDATE classes SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?;", (class_id,))
    db.commit()
    flash("Class status updated.", "info")
    return redirect(url_for('admin.sections_classes'))

@admin_bp.route('/class-sections/add', methods=['POST'])
def add_class_section():
    db = get_db()
    class_id = request.form.get('class_id')
    section_name = request.form.get('section_name', '').strip().upper()
    capacity = request.form.get('capacity', 40)
    if class_id and section_name:
        try:
            db.execute("INSERT INTO class_sections (class_id, section_name, capacity) VALUES (?, ?, ?);", (class_id, section_name, capacity))
            db.commit()
            flash(f"Class section '{section_name}' added.", "success")
        except Exception as e:
            flash(f"Section '{section_name}' already exists for this class or error occurred.", "danger")
    return redirect(url_for('admin.sections_classes'))

@admin_bp.route('/academic-years/add', methods=['POST'])
def add_academic_year():
    db = get_db()
    name = request.form.get('name', '').strip()
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    is_current = 1 if request.form.get('is_current') else 0
    if name:
        try:
            if is_current:
                db.execute("UPDATE academic_years SET is_current = 0;")
            db.execute("INSERT INTO academic_years (name, start_date, end_date, is_current) VALUES (?, ?, ?, ?);",
                       (name, start_date, end_date, is_current))
            db.commit()
            flash(f"Academic year '{name}' added.", "success")
        except Exception as e:
            flash(f"Error adding academic year: {e}", "danger")
    return redirect(url_for('admin.sections_classes'))

@admin_bp.route('/api/classes-by-section/<int:section_id>')
def api_classes_by_section(section_id):
    """AJAX helper returning classes belonging to a given section."""
    db = get_db()
    rows = db.execute("SELECT id, name FROM classes WHERE section_id = ? AND is_active = 1 ORDER BY display_order, name ASC;", (section_id,)).fetchall()
    return jsonify([{'id': r['id'], 'name': r['name']} for r in rows])

@admin_bp.route('/api/sections-by-class/<int:class_id>')
def api_sections_by_class(class_id):
    """AJAX helper returning class sections (A, B, C...) for a given class."""
    db = get_db()
    rows = db.execute("SELECT id, section_name FROM class_sections WHERE class_id = ? ORDER BY section_name ASC;", (class_id,)).fetchall()
    return jsonify([{'id': r['id'], 'section_name': r['section_name']} for r in rows])

# ==================== 4. STUDENT MANAGEMENT ====================

@admin_bp.route('/students')
def students():
    db = get_db()
    search = request.args.get('search', '').strip()
    section_id = request.args.get('section_id', '')
    class_id = request.args.get('class_id', '')
    status = request.args.get('status', 'Active')
    
    query = """
        SELECT s.*, sec.name as section_name, c.name as class_name, cs.section_name as class_section_name,
               ay.name as academic_year_name
        FROM students s
        LEFT JOIN school_sections sec ON s.school_section_id = sec.id
        LEFT JOIN classes c ON s.class_id = c.id
        LEFT JOIN class_sections cs ON s.class_section_id = cs.id
        LEFT JOIN academic_years ay ON s.academic_year_id = ay.id
        WHERE 1=1
    """
    params = []
    
    if search:
        query += " AND (s.full_name LIKE ? OR s.admission_number LIKE ? OR s.guardian_phone LIKE ? OR s.guardian_name LIKE ?)"
        like_term = f"%{search}%"
        params.extend([like_term, like_term, like_term, like_term])
    
    if section_id:
        query += " AND s.school_section_id = ?"
        params.append(section_id)
        
    if class_id:
        query += " AND s.class_id = ?"
        params.append(class_id)
        
    if status and status != 'All':
        query += " AND s.status = ?"
        params.append(status)
        
    query += " ORDER BY s.id DESC"
    
    students_list = db.execute(query, params).fetchall()
    all_sections = db.execute("SELECT * FROM school_sections WHERE is_active = 1;").fetchall()
    all_classes = db.execute("SELECT * FROM classes WHERE is_active = 1 ORDER BY display_order, name;").fetchall()

    return render_template('admin/students_list.html',
        settings=get_school_settings(),
        students=students_list,
        sections=all_sections,
        classes=all_classes,
        search=search,
        selected_section=section_id,
        selected_class=class_id,
        selected_status=status
    )

@admin_bp.route('/students/new', methods=['GET', 'POST'])
def student_create():
    db = get_db()
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        admission_number = request.form.get('admission_number', '').strip() or generate_admission_number()
        dob = request.form.get('dob')
        gender = request.form.get('gender')
        school_section_id = request.form.get('school_section_id')
        class_id = request.form.get('class_id')
        class_section_id = request.form.get('class_section_id')
        roll_number = request.form.get('roll_number', '').strip()
        admission_date = request.form.get('admission_date') or date.today().isoformat()
        academic_year_id = request.form.get('academic_year_id')
        
        father_name = request.form.get('father_name', '').strip()
        mother_name = request.form.get('mother_name', '').strip()
        guardian_name = request.form.get('guardian_name', '').strip() or father_name or mother_name
        guardian_phone = request.form.get('guardian_phone', '').strip()
        emergency_contact = request.form.get('emergency_contact', '').strip()
        residential_address = request.form.get('residential_address', '').strip()
        previous_school = request.form.get('previous_school', '').strip()
        student_email = request.form.get('student_email', '').strip()
        
        username = request.form.get('username', '').strip() or admission_number.lower()
        password = request.form.get('password', '').strip() or f"Stu@{admission_number}"
        
        # Validation
        if not full_name or not admission_number or not class_id or not academic_year_id:
            flash("Full Name, Admission Number, Class, and Academic Year are mandatory.", "danger")
            return redirect(url_for('admin.student_create'))

        # Check duplicate admission number
        exists_adm = db.execute("SELECT id FROM students WHERE admission_number = ?;", (admission_number,)).fetchone()
        if exists_adm:
            flash(f"Admission Number '{admission_number}' already exists! Please use a unique number.", "danger")
            return redirect(url_for('admin.student_create'))

        # Check username uniqueness
        exists_user = db.execute("SELECT id FROM users WHERE username = ?;", (username,)).fetchone()
        if exists_user:
            username = f"{username}_{generate_admission_number()[-4:]}"

        photo_path = ''
        if 'photo' in request.files and request.files['photo'].filename:
            saved = save_uploaded_file(request.files['photo'], subfolder='photos')
            if saved:
                photo_path = saved

        # Create user account for student
        pw_hash = generate_password_hash(password)
        cur = db.execute("""
            INSERT INTO users (username, password_hash, role, full_name, email, phone, is_active)
            VALUES (?, ?, 'student', ?, ?, ?, 1);
        """, (username, pw_hash, full_name, student_email, guardian_phone))
        user_id = cur.lastrowid

        # Insert student record
        cur_s = db.execute("""
            INSERT INTO students (
                user_id, admission_number, full_name, photo_path, dob, gender,
                school_section_id, class_id, class_section_id, roll_number,
                admission_date, academic_year_id, father_name, mother_name,
                guardian_name, guardian_phone, emergency_contact, residential_address,
                previous_school, student_email, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active');
        """, (
            user_id, admission_number, full_name, photo_path, dob, gender,
            school_section_id, class_id, class_section_id, roll_number,
            admission_date, academic_year_id, father_name, mother_name,
            guardian_name, guardian_phone, emergency_contact, residential_address,
            previous_school, student_email
        ))
        student_id = cur_s.lastrowid
        
        # Auto-assign standard fee structures configured for this class and academic year
        fee_structs = db.execute("""
            SELECT * FROM fee_structures 
            WHERE class_id = ? AND academic_year_id = ?;
        """, (class_id, academic_year_id)).fetchall()
        for fs in fee_structs:
            db.execute("""
                INSERT OR IGNORE INTO student_fee_assignments 
                (student_id, fee_structure_id, academic_year_id, assigned_amount, concession_amount, status, assigned_date)
                VALUES (?, ?, ?, ?, 0.0, 'Pending', ?);
            """, (student_id, fs['id'], academic_year_id, fs['amount'], admission_date))

        db.commit()
        log_audit('ADMIT_STUDENT', 'students', str(student_id), f"Admitted student {full_name} ({admission_number})", current_user.id, current_user.username)
        
        flash(f"Student '{full_name}' admitted successfully! Credentials: Username '{username}', Password '{password}'", "success")
        return redirect(url_for('admin.student_view', student_id=student_id))

    sections = db.execute("SELECT * FROM school_sections WHERE is_active = 1 ORDER BY id ASC;").fetchall()
    classes = db.execute("SELECT * FROM classes WHERE is_active = 1 ORDER BY section_id, display_order, name;").fetchall()
    class_sections = db.execute("SELECT * FROM class_sections ORDER BY section_name;").fetchall()
    academic_years = db.execute("SELECT * FROM academic_years ORDER BY is_current DESC, id DESC;").fetchall()
    suggested_adm = generate_admission_number()

    return render_template('admin/student_form.html',
        settings=get_school_settings(),
        student=None,
        sections=sections,
        classes=classes,
        class_sections=class_sections,
        academic_years=academic_years,
        suggested_adm=suggested_adm
    )

@admin_bp.route('/students/<int:student_id>')
def student_view(student_id):
    db = get_db()
    student = db.execute("""
        SELECT s.*, sec.name as section_name, c.name as class_name, cs.section_name as class_section_name,
               ay.name as academic_year_name, u.username as account_username
        FROM students s
        LEFT JOIN school_sections sec ON s.school_section_id = sec.id
        LEFT JOIN classes c ON s.class_id = c.id
        LEFT JOIN class_sections cs ON s.class_section_id = cs.id
        LEFT JOIN academic_years ay ON s.academic_year_id = ay.id
        LEFT JOIN users u ON s.user_id = u.id
        WHERE s.id = ?;
    """, (student_id,)).fetchone()
    
    if not student:
        flash("Student record not found.", "danger")
        return redirect(url_for('admin.students'))

    # Fee Assignments
    fees = db.execute("""
        SELECT sfa.*, fs.fee_category, fs.due_date,
               (SELECT COALESCE(SUM(amount_paid), 0.0) FROM payment_transactions WHERE student_fee_assignment_id = sfa.id) as paid_for_item
        FROM student_fee_assignments sfa
        JOIN fee_structures fs ON sfa.fee_structure_id = fs.id
        WHERE sfa.student_id = ?
        ORDER BY sfa.id ASC;
    """, (student_id,)).fetchall()

    # Payments History
    payments = db.execute("""
        SELECT p.*, u.full_name as recorded_by_name
        FROM payment_transactions p
        LEFT JOIN users u ON p.recorded_by_user_id = u.id
        WHERE p.student_id = ?
        ORDER BY p.id DESC;
    """, (student_id,)).fetchall()

    # Financial Totals
    fin_summary = get_student_financial_summary(student_id)

    # Attendance history
    attendance = db.execute("""
        SELECT * FROM attendance_records
        WHERE student_id = ?
        ORDER BY date DESC LIMIT 30;
    """, (student_id,)).fetchall()
    
    att_stats = db.execute("""
        SELECT 
            COUNT(*) as total_days,
            SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present_days,
            SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent_days
        FROM attendance_records
        WHERE student_id = ?;
    """, (student_id,)).fetchone()
    
    total_att_days = att_stats['total_days'] or 0
    present_att_days = att_stats['present_days'] or 0
    att_rate = round((present_att_days / total_att_days * 100), 1) if total_att_days > 0 else 0

    return render_template('admin/student_view.html',
        settings=get_school_settings(),
        student=student,
        fees=fees,
        payments=payments,
        financial=fin_summary,
        attendance=attendance,
        att_rate=att_rate,
        total_att_days=total_att_days,
        present_att_days=present_att_days
    )

@admin_bp.route('/students/<int:student_id>/edit', methods=['GET', 'POST'])
def student_edit(student_id):
    db = get_db()
    student = db.execute("SELECT * FROM students WHERE id = ?;", (student_id,)).fetchone()
    if not student:
        flash("Student not found.", "danger")
        return redirect(url_for('admin.students'))

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        dob = request.form.get('dob')
        gender = request.form.get('gender')
        school_section_id = request.form.get('school_section_id')
        class_id = request.form.get('class_id')
        class_section_id = request.form.get('class_section_id')
        roll_number = request.form.get('roll_number', '').strip()
        academic_year_id = request.form.get('academic_year_id')
        status = request.form.get('status', 'Active')
        
        father_name = request.form.get('father_name', '').strip()
        mother_name = request.form.get('mother_name', '').strip()
        guardian_name = request.form.get('guardian_name', '').strip()
        guardian_phone = request.form.get('guardian_phone', '').strip()
        emergency_contact = request.form.get('emergency_contact', '').strip()
        residential_address = request.form.get('residential_address', '').strip()
        previous_school = request.form.get('previous_school', '').strip()
        student_email = request.form.get('student_email', '').strip()

        photo_path = student['photo_path']
        if 'photo' in request.files and request.files['photo'].filename:
            saved = save_uploaded_file(request.files['photo'], subfolder='photos')
            if saved:
                photo_path = saved

        db.execute("""
            UPDATE students SET
                full_name = ?, photo_path = ?, dob = ?, gender = ?,
                school_section_id = ?, class_id = ?, class_section_id = ?, roll_number = ?,
                academic_year_id = ?, status = ?, father_name = ?, mother_name = ?,
                guardian_name = ?, guardian_phone = ?, emergency_contact = ?,
                residential_address = ?, previous_school = ?, student_email = ?
            WHERE id = ?;
        """, (
            full_name, photo_path, dob, gender,
            school_section_id, class_id, class_section_id, roll_number,
            academic_year_id, status, father_name, mother_name,
            guardian_name, guardian_phone, emergency_contact,
            residential_address, previous_school, student_email, student_id
        ))

        # Also update user full_name and email
        if student['user_id']:
            db.execute("UPDATE users SET full_name = ?, email = ? WHERE id = ?;", (full_name, student_email, student['user_id']))

        db.commit()
        log_audit('UPDATE_STUDENT', 'students', str(student_id), f"Updated details for student {full_name}", current_user.id, current_user.username)
        flash("Student record updated successfully.", "success")
        return redirect(url_for('admin.student_view', student_id=student_id))

    sections = db.execute("SELECT * FROM school_sections WHERE is_active = 1 ORDER BY id ASC;").fetchall()
    classes = db.execute("SELECT * FROM classes WHERE is_active = 1 ORDER BY section_id, display_order, name;").fetchall()
    class_sections = db.execute("SELECT * FROM class_sections ORDER BY section_name;").fetchall()
    academic_years = db.execute("SELECT * FROM academic_years ORDER BY is_current DESC, id DESC;").fetchall()

    return render_template('admin/student_form.html',
        settings=get_school_settings(),
        student=student,
        sections=sections,
        classes=classes,
        class_sections=class_sections,
        academic_years=academic_years
    )

@admin_bp.route('/students/<int:student_id>/archive', methods=['POST'])
def student_archive(student_id):
    db = get_db()
    db.execute("UPDATE students SET status = 'Archived' WHERE id = ?;", (student_id,))
    # Deactivate login
    student = db.execute("SELECT user_id, full_name FROM students WHERE id = ?;", (student_id,)).fetchone()
    if student and student['user_id']:
        db.execute("UPDATE users SET is_active = 0 WHERE id = ?;", (student['user_id'],))
    db.commit()
    log_audit('ARCHIVE_STUDENT', 'students', str(student_id), f"Archived student {student['full_name'] if student else student_id}", current_user.id, current_user.username)
    flash("Student archived successfully. Historical financial and academic records remain preserved.", "info")
    return redirect(url_for('admin.students'))

@admin_bp.route('/students/<int:student_id>/pdf')
def student_pdf(student_id):
    db = get_db()
    student = db.execute("""
        SELECT s.*, sec.name as section_name, c.name as class_name, cs.section_name as class_section_name,
               ay.name as academic_year_name
        FROM students s
        LEFT JOIN school_sections sec ON s.school_section_id = sec.id
        LEFT JOIN classes c ON s.class_id = c.id
        LEFT JOIN class_sections cs ON s.class_section_id = cs.id
        LEFT JOIN academic_years ay ON s.academic_year_id = ay.id
        WHERE s.id = ?;
    """, (student_id,)).fetchone()
    if not student:
        flash("Student not found.", "danger")
        return redirect(url_for('admin.students'))
    
    pdf_bytes = generate_student_profile_pdf(dict(student), get_school_settings())
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'inline; filename="Student_{student["admission_number"]}.pdf"'}
    )

# ==================== 5. TEACHER MANAGEMENT ====================

@admin_bp.route('/teachers')
def teachers():
    db = get_db()
    teachers_list = db.execute("""
        SELECT t.*, u.username,
               (SELECT COUNT(DISTINCT class_id) FROM teacher_class_assignments WHERE teacher_id = t.id) as assigned_classes_count
        FROM teachers t
        LEFT JOIN users u ON t.user_id = u.id
        ORDER BY t.id DESC;
    """).fetchall()
    return render_template('admin/teachers_list.html', settings=get_school_settings(), teachers=teachers_list)

@admin_bp.route('/teachers/new', methods=['GET', 'POST'])
def teacher_create():
    db = get_db()
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        employee_id = request.form.get('employee_id', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        qualification = request.form.get('qualification', '').strip()
        joining_date = request.form.get('joining_date') or date.today().isoformat()
        
        username = request.form.get('username', '').strip() or employee_id.lower()
        password = request.form.get('password', '').strip() or f"Teach@{employee_id}"

        if not full_name or not employee_id:
            flash("Teacher name and employee ID are mandatory.", "danger")
            return redirect(url_for('admin.teacher_create'))

        # Check uniqueness
        if db.execute("SELECT id FROM teachers WHERE employee_id = ?;", (employee_id,)).fetchone():
            flash("Employee ID already exists.", "danger")
            return redirect(url_for('admin.teacher_create'))

        photo_path = ''
        if 'photo' in request.files and request.files['photo'].filename:
            saved = save_uploaded_file(request.files['photo'], subfolder='photos')
            if saved:
                photo_path = saved

        # Create user account
        pw_hash = generate_password_hash(password)
        cur_u = db.execute("""
            INSERT INTO users (username, password_hash, role, full_name, email, phone, is_active)
            VALUES (?, ?, 'teacher', ?, ?, ?, 1);
        """, (username, pw_hash, full_name, email, phone))
        user_id = cur_u.lastrowid

        # Insert teacher
        cur_t = db.execute("""
            INSERT INTO teachers (user_id, employee_id, full_name, email, phone, qualification, photo_path, joining_date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Active');
        """, (user_id, employee_id, full_name, email, phone, qualification, photo_path, joining_date))
        teacher_id = cur_t.lastrowid

        # Handle class assignments
        class_ids = request.form.getlist('class_ids')
        subject = request.form.get('subject', 'General')
        for cid in class_ids:
            # find first section of class
            c_sec = db.execute("SELECT id FROM class_sections WHERE class_id = ? LIMIT 1;", (cid,)).fetchone()
            sec_id = c_sec['id'] if c_sec else 1
            db.execute("""
                INSERT OR IGNORE INTO teacher_class_assignments (teacher_id, class_id, class_section_id, subject)
                VALUES (?, ?, ?, ?);
            """, (teacher_id, cid, sec_id, subject))

        db.commit()
        log_audit('CREATE_TEACHER', 'teachers', str(teacher_id), f"Created teacher {full_name} ({employee_id})", current_user.id, current_user.username)
        flash(f"Teacher '{full_name}' created successfully. Login username: '{username}', password: '{password}'.", "success")
        return redirect(url_for('admin.teachers'))

    all_classes = db.execute("SELECT * FROM classes WHERE is_active = 1 ORDER BY section_id, display_order, name;").fetchall()
    return render_template('admin/teacher_form.html', settings=get_school_settings(), teacher=None, classes=all_classes)

# ==================== 6. FEE MANAGEMENT ====================

@admin_bp.route('/fee-structures', methods=['GET', 'POST'])
def fee_structures():
    db = get_db()
    if request.method == 'POST':
        academic_year_id = request.form.get('academic_year_id')
        class_id = request.form.get('class_id')
        fee_category = request.form.get('fee_category', '').strip()
        amount = request.form.get('amount', 0)
        due_date = request.form.get('due_date')
        description = request.form.get('description', '').strip()

        if academic_year_id and class_id and fee_category and float(amount) > 0:
            # Find section_id
            c_row = db.execute("SELECT section_id FROM classes WHERE id = ?;", (class_id,)).fetchone()
            sec_id = c_row['section_id'] if c_row else None

            cur = db.execute("""
                INSERT INTO fee_structures (academic_year_id, school_section_id, class_id, fee_category, amount, due_date, description)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (academic_year_id, sec_id, class_id, fee_category, float(amount), due_date, description))
            new_fs_id = cur.lastrowid
            
            # Optionally assign to all active students in that class for that academic year
            if request.form.get('auto_assign_students'):
                stus = db.execute("SELECT id FROM students WHERE class_id = ? AND status = 'Active';", (class_id,)).fetchall()
                today_d = date.today().isoformat()
                for st in stus:
                    db.execute("""
                        INSERT OR IGNORE INTO student_fee_assignments 
                        (student_id, fee_structure_id, academic_year_id, assigned_amount, concession_amount, status, assigned_date)
                        VALUES (?, ?, ?, ?, 0.0, 'Pending', ?);
                    """, (st['id'], new_fs_id, academic_year_id, float(amount), today_d))

            db.commit()
            log_audit('CREATE_FEE_STRUCTURE', 'fee_structures', str(new_fs_id), f"Created {fee_category} of {amount} for Class ID {class_id}", current_user.id, current_user.username)
            flash("Fee structure created and assigned successfully.", "success")
        else:
            flash("Please fill in all mandatory fee fields with a valid amount.", "danger")
        return redirect(url_for('admin.fee_structures'))

    structures = db.execute("""
        SELECT fs.*, ay.name as academic_year_name, c.name as class_name, sec.name as section_name,
               (SELECT COUNT(*) FROM student_fee_assignments WHERE fee_structure_id = fs.id) as assigned_student_count
        FROM fee_structures fs
        JOIN academic_years ay ON fs.academic_year_id = ay.id
        JOIN classes c ON fs.class_id = c.id
        LEFT JOIN school_sections sec ON fs.school_section_id = sec.id
        ORDER BY ay.id DESC, c.display_order ASC;
    """).fetchall()

    academic_years = db.execute("SELECT * FROM academic_years ORDER BY is_current DESC;").fetchall()
    classes = db.execute("SELECT * FROM classes WHERE is_active = 1 ORDER BY section_id, display_order, name;").fetchall()

    return render_template('admin/fee_structures.html',
        settings=get_school_settings(),
        structures=structures,
        academic_years=academic_years,
        classes=classes
    )

@admin_bp.route('/payments', methods=['GET', 'POST'])
def payments():
    db = get_db()
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        fee_assignment_id = request.form.get('student_fee_assignment_id') or None
        amount_paid = request.form.get('amount_paid')
        payment_date = request.form.get('payment_date') or date.today().isoformat()
        payment_method = request.form.get('payment_method')
        transaction_ref = request.form.get('transaction_reference', '').strip()
        remarks = request.form.get('remarks', '').strip()

        if not student_id or not amount_paid or float(amount_paid) <= 0 or not payment_method:
            flash("Student, valid payment amount, and payment method are required.", "danger")
            return redirect(url_for('admin.payments'))

        receipt_no = generate_receipt_number()
        amount_flt = float(amount_paid)

        # Record payment transaction
        cur = db.execute("""
            INSERT INTO payment_transactions (
                receipt_number, student_id, student_fee_assignment_id,
                amount_paid, payment_date, payment_method,
                transaction_reference, remarks, recorded_by_user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            receipt_no, student_id, fee_assignment_id,
            amount_flt, payment_date, payment_method,
            transaction_ref, remarks, current_user.id
        ))
        payment_id = cur.lastrowid

        # Update assignment status if specific assignment was targeted
        if fee_assignment_id:
            fa = db.execute("SELECT assigned_amount, concession_amount FROM student_fee_assignments WHERE id = ?;", (fee_assignment_id,)).fetchone()
            if fa:
                paid_so_far = db.execute("SELECT COALESCE(SUM(amount_paid), 0.0) as s FROM payment_transactions WHERE student_fee_assignment_id = ?;", (fee_assignment_id,)).fetchone()['s']
                effective_due = fa['assigned_amount'] - fa['concession_amount']
                if paid_so_far >= effective_due:
                    new_status = 'Paid'
                elif paid_so_far > 0:
                    new_status = 'Partial'
                else:
                    new_status = 'Pending'
                db.execute("UPDATE student_fee_assignments SET status = ? WHERE id = ?;", (new_status, fee_assignment_id))

        db.commit()
        log_audit('RECORD_PAYMENT', 'payment_transactions', str(payment_id), f"Recorded payment {receipt_no} of {amount_flt} for Student ID {student_id}", current_user.id, current_user.username)
        flash(f"Payment recorded successfully! Receipt #{receipt_no} generated.", "success")
        return redirect(url_for('admin.payment_receipt', payment_id=payment_id))

    # Payment listings and search
    search = request.args.get('search', '').strip()
    payment_method = request.args.get('payment_method', '')
    
    query = """
        SELECT p.*, s.full_name as student_name, s.admission_number, c.name as class_name,
               fs.fee_category, u.full_name as recorded_by_name
        FROM payment_transactions p
        JOIN students s ON p.student_id = s.id
        LEFT JOIN classes c ON s.class_id = c.id
        LEFT JOIN student_fee_assignments sfa ON p.student_fee_assignment_id = sfa.id
        LEFT JOIN fee_structures fs ON sfa.fee_structure_id = fs.id
        LEFT JOIN users u ON p.recorded_by_user_id = u.id
        WHERE 1=1
    """
    params = []
    if search:
        query += " AND (p.receipt_number LIKE ? OR s.full_name LIKE ? OR s.admission_number LIKE ?)"
        lk = f"%{search}%"
        params.extend([lk, lk, lk])
    if payment_method:
        query += " AND p.payment_method = ?"
        params.append(payment_method)
        
    query += " ORDER BY p.id DESC LIMIT 100;"
    payments_list = db.execute(query, params).fetchall()

    # Students for dropdown
    all_students = db.execute("SELECT id, full_name, admission_number FROM students WHERE status = 'Active' ORDER BY full_name ASC;").fetchall()

    return render_template('admin/fee_payments.html',
        settings=get_school_settings(),
        payments=payments_list,
        students=all_students,
        search=search,
        selected_method=payment_method
    )

@admin_bp.route('/api/student-fees/<int:student_id>')
def api_student_fees(student_id):
    """Fetch assigned fee items and current balances for payment modal."""
    db = get_db()
    items = db.execute("""
        SELECT sfa.id, sfa.assigned_amount, sfa.concession_amount, sfa.status,
               fs.fee_category,
               (SELECT COALESCE(SUM(amount_paid), 0.0) FROM payment_transactions WHERE student_fee_assignment_id = sfa.id) as total_paid
        FROM student_fee_assignments sfa
        JOIN fee_structures fs ON sfa.fee_structure_id = fs.id
        WHERE sfa.student_id = ?
        ORDER BY sfa.id ASC;
    """, (student_id,)).fetchall()
    
    summary = get_student_financial_summary(student_id)
    
    data = []
    for it in items:
        effective_due = it['assigned_amount'] - it['concession_amount']
        rem = max(0.0, effective_due - it['total_paid'])
        data.append({
            'assignment_id': it['id'],
            'fee_category': it['fee_category'],
            'assigned': it['assigned_amount'],
            'concession': it['concession_amount'],
            'paid': it['total_paid'],
            'remaining': rem,
            'status': it['status']
        })
    return jsonify({'items': data, 'summary': summary})

@admin_bp.route('/payments/<int:payment_id>/receipt')
def payment_receipt(payment_id):
    """View receipt or generate PDF."""
    db = get_db()
    row = db.execute("""
        SELECT p.*, s.full_name as student_name, s.admission_number, s.photo_path,
               c.name as class_name, cs.section_name, ay.name as academic_year,
               fs.fee_category, sfa.assigned_amount, sfa.concession_amount,
               u.full_name as cashier_name
        FROM payment_transactions p
        JOIN students s ON p.student_id = s.id
        LEFT JOIN classes c ON s.class_id = c.id
        LEFT JOIN class_sections cs ON s.class_section_id = cs.id
        LEFT JOIN academic_years ay ON s.academic_year_id = ay.id
        LEFT JOIN student_fee_assignments sfa ON p.student_fee_assignment_id = sfa.id
        LEFT JOIN fee_structures fs ON sfa.fee_structure_id = fs.id
        LEFT JOIN users u ON p.recorded_by_user_id = u.id
        WHERE p.id = ?;
    """, (payment_id,)).fetchone()
    
    if not row:
        flash("Receipt record not found.", "danger")
        return redirect(url_for('admin.payments'))

    fin = get_student_financial_summary(row['student_id'])
    receipt_data = dict(row)
    receipt_data['outstanding_balance'] = fin['outstanding_balance']

    # If PDF requested
    if request.args.get('format') == 'pdf':
        pdf_bytes = generate_fee_receipt_pdf(receipt_data, get_school_settings())
        return Response(
            pdf_bytes,
            mimetype='application/pdf',
            headers={'Content-Disposition': f'inline; filename="Receipt_{row["receipt_number"]}.pdf"'}
        )

    return render_template('admin/receipt_view.html', settings=get_school_settings(), payment=receipt_data)

@admin_bp.route('/fee-concessions/apply', methods=['POST'])
def apply_concession():
    """Apply approved discount or concession with an authorized reason."""
    db = get_db()
    assignment_id = request.form.get('student_fee_assignment_id')
    amount = request.form.get('concession_amount', 0)
    reason = request.form.get('concession_reason', '').strip()

    if assignment_id and float(amount) >= 0 and reason:
        db.execute("""
            UPDATE student_fee_assignments 
            SET concession_amount = ?, concession_reason = ?
            WHERE id = ?;
        """, (float(amount), reason, assignment_id))
        db.commit()
        log_audit('APPLY_CONCESSION', 'student_fee_assignments', str(assignment_id), f"Applied discount of {amount}. Reason: {reason}", current_user.id, current_user.username)
        flash("Fee concession applied successfully.", "success")
    else:
        flash("Please specify valid concession amount and authorized reason.", "danger")
    return redirect(request.referrer or url_for('admin.payments'))

@admin_bp.route('/reports/fees')
def fee_reports():
    """Comprehensive financial reports and summaries."""
    db = get_db()
    # Class-wise financial summary
    class_reports = db.execute("""
        SELECT c.id, c.name as class_name, sec.name as section_name,
               COUNT(DISTINCT s.id) as total_students,
               COALESCE(SUM(sfa.assigned_amount), 0.0) as total_assigned,
               COALESCE(SUM(sfa.concession_amount), 0.0) as total_concession,
               (
                   SELECT COALESCE(SUM(pt.amount_paid), 0.0)
                   FROM payment_transactions pt
                   JOIN students st ON pt.student_id = st.id
                   WHERE st.class_id = c.id
               ) as total_collected
        FROM classes c
        JOIN school_sections sec ON c.section_id = sec.id
        LEFT JOIN students s ON s.class_id = c.id AND s.status = 'Active'
        LEFT JOIN student_fee_assignments sfa ON sfa.student_id = s.id
        GROUP BY c.id
        ORDER BY sec.id, c.display_order ASC;
    """).fetchall()

    # Calculate overall totals
    all_assigned = sum(r['total_assigned'] for r in class_reports)
    all_collected = sum(r['total_collected'] for r in class_reports)
    all_concession = sum(r['total_concession'] for r in class_reports)
    all_outstanding = max(0.0, all_assigned - all_collected - all_concession)

    # Outstanding dues student list
    outstanding_students = []
    active_students = db.execute("""
        SELECT s.id, s.full_name, s.admission_number, c.name as class_name, s.guardian_phone
        FROM students s
        LEFT JOIN classes c ON s.class_id = c.id
        WHERE s.status = 'Active';
    """).fetchall()
    for st in active_students:
        fin = get_student_financial_summary(st['id'])
        if fin['outstanding_balance'] > 0:
            outstanding_students.append({
                'id': st['id'],
                'full_name': st['full_name'],
                'admission_number': st['admission_number'],
                'class_name': st['class_name'],
                'guardian_phone': st['guardian_phone'],
                'assigned': fin['total_assigned'],
                'paid': fin['total_paid'],
                'concession': fin['total_concession'],
                'outstanding': fin['outstanding_balance']
            })

    # Sort outstanding by amount descending
    outstanding_students.sort(key=lambda x: x['outstanding'], reverse=True)

    # Check export format
    export = request.args.get('export')
    if export == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Student Name', 'Admission No', 'Class', 'Guardian Phone', 'Total Assigned', 'Concession', 'Total Paid', 'Outstanding Balance'])
        for s in outstanding_students:
            writer.writerow([s['full_name'], s['admission_number'], s['class_name'], s['guardian_phone'], s['assigned'], s['concession'], s['paid'], s['outstanding']])
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=outstanding_fees_report.csv"})

    return render_template('admin/fee_reports.html',
        settings=get_school_settings(),
        class_reports=class_reports,
        outstanding_students=outstanding_students,
        all_assigned=all_assigned,
        all_collected=all_collected,
        all_concession=all_concession,
        all_outstanding=all_outstanding
    )

# ==================== 7. ATTENDANCE MANAGEMENT ====================

@admin_bp.route('/attendance', methods=['GET', 'POST'])
def attendance():
    db = get_db()
    selected_date = request.args.get('date', date.today().isoformat())
    selected_class_id = request.args.get('class_id')
    selected_section_id = request.args.get('class_section_id')
    
    classes = db.execute("SELECT * FROM classes WHERE is_active = 1 ORDER BY section_id, display_order, name;").fetchall()
    
    if not selected_class_id and classes:
        selected_class_id = str(classes[0]['id'])
        
    class_sections = []
    if selected_class_id:
        class_sections = db.execute("SELECT * FROM class_sections WHERE class_id = ? ORDER BY section_name ASC;", (selected_class_id,)).fetchall()
        if not selected_section_id and class_sections:
            selected_section_id = str(class_sections[0]['id'])

    if request.method == 'POST':
        # Process attendance submission
        post_date = request.form.get('date', selected_date)
        post_class_id = request.form.get('class_id')
        post_section_id = request.form.get('class_section_id')
        
        student_ids = request.form.getlist('student_ids')
        for sid in student_ids:
            st_status = request.form.get(f'status_{sid}', 'Present')
            remarks = request.form.get(f'remarks_{sid}', '').strip()
            
            # Insert or replace attendance record to strictly prevent duplicates
            db.execute("""
                INSERT INTO attendance_records (student_id, class_id, class_section_id, date, status, remarks, recorded_by_user_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(student_id, date) DO UPDATE SET
                    status = excluded.status,
                    remarks = excluded.remarks,
                    recorded_by_user_id = excluded.recorded_by_user_id,
                    updated_at = CURRENT_TIMESTAMP;
            """, (sid, post_class_id, post_section_id, post_date, st_status, remarks, current_user.id))
            
        db.commit()
        log_audit('MARK_ATTENDANCE', 'attendance_records', f"{post_class_id}_{post_date}", f"Marked attendance for {len(student_ids)} students on {post_date}", current_user.id, current_user.username)
        flash(f"Attendance recorded successfully for {post_date}.", "success")
        return redirect(url_for('admin.attendance', date=post_date, class_id=post_class_id, class_section_id=post_section_id))

    # Fetch students roster and their marked attendance status for this date
    roster = []
    if selected_class_id:
        roster_query = """
            SELECT s.id, s.full_name, s.admission_number, s.roll_number, s.photo_path,
                   att.status as attendance_status, att.remarks as attendance_remarks
            FROM students s
            LEFT JOIN attendance_records att ON att.student_id = s.id AND att.date = ?
            WHERE s.class_id = ? AND s.status = 'Active'
        """
        params = [selected_date, selected_class_id]
        if selected_section_id:
            roster_query += " AND s.class_section_id = ?"
            params.append(selected_section_id)
        roster_query += " ORDER BY s.roll_number, s.full_name ASC;"
        roster = db.execute(roster_query, params).fetchall()

    return render_template('admin/attendance.html',
        settings=get_school_settings(),
        selected_date=selected_date,
        selected_class_id=int(selected_class_id) if selected_class_id else None,
        selected_section_id=int(selected_section_id) if selected_section_id else None,
        classes=classes,
        class_sections=class_sections,
        roster=roster
    )

# ==================== 8. NOTICES & ANNOUNCEMENTS ====================

@admin_bp.route('/notices', methods=['GET', 'POST'])
def notices():
    db = get_db()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        target_type = request.form.get('target_type', 'all')
        target_section_id = request.form.get('target_section_id') or None
        target_class_id = request.form.get('target_class_id') or None
        publish_date = request.form.get('publish_date') or date.today().isoformat()
        expiry_date = request.form.get('expiry_date') or None

        if title and content:
            cur = db.execute("""
                INSERT INTO notices (title, content, target_type, target_section_id, target_class_id, publish_date, expiry_date, is_active, author_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?);
            """, (title, content, target_type, target_section_id, target_class_id, publish_date, expiry_date, current_user.id))
            db.commit()
            log_audit('CREATE_NOTICE', 'notices', str(cur.lastrowid), f"Created notice: {title}", current_user.id, current_user.username)
            flash("Notice published successfully.", "success")
        else:
            flash("Title and content are required.", "danger")
        return redirect(url_for('admin.notices'))

    notices_list = db.execute("""
        SELECT n.*, sec.name as section_name, c.name as class_name, u.full_name as author_name
        FROM notices n
        LEFT JOIN school_sections sec ON n.target_section_id = sec.id
        LEFT JOIN classes c ON n.target_class_id = c.id
        LEFT JOIN users u ON n.author_user_id = u.id
        ORDER BY n.id DESC;
    """).fetchall()

    sections = db.execute("SELECT * FROM school_sections WHERE is_active = 1;").fetchall()
    classes = db.execute("SELECT * FROM classes WHERE is_active = 1;").fetchall()

    return render_template('admin/notices.html',
        settings=get_school_settings(),
        notices=notices_list,
        sections=sections,
        classes=classes
    )

@admin_bp.route('/notices/<int:notice_id>/toggle', methods=['POST'])
def toggle_notice(notice_id):
    db = get_db()
    db.execute("UPDATE notices SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?;", (notice_id,))
    db.commit()
    flash("Notice status updated.", "info")
    return redirect(url_for('admin.notices'))

# ==================== 9. AUDIT LOGS ====================

@admin_bp.route('/audit-logs')
def audit_logs():
    db = get_db()
    logs = db.execute("""
        SELECT a.*, u.full_name as user_full_name
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.id DESC LIMIT 200;
    """).fetchall()
    return render_template('admin/audit_logs.html', settings=get_school_settings(), logs=logs)
