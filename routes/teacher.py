import os
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from models import get_db, get_school_settings, log_audit
from utils.decorators import teacher_required

teacher_bp = Blueprint('teacher', __name__, url_prefix='/teacher')

@teacher_bp.before_request
@login_required
@teacher_required
def teacher_before_request():
    """Ensure all teacher routes require active teacher role."""
    if not current_user.teacher_id:
        abort(403)

def _get_current_teacher_data():
    """Retrieve teacher record for logged in teacher."""
    db = get_db()
    teacher = db.execute("SELECT * FROM teachers WHERE id = ?;", (current_user.teacher_id,)).fetchone()
    return teacher

# ==================== 1. TEACHER DASHBOARD ====================

@teacher_bp.route('/dashboard')
def dashboard():
    teacher = _get_current_teacher_data()
    db = get_db()
    today_str = date.today().isoformat()

    # Assigned classes
    assigned_classes = db.execute("""
        SELECT tca.*, c.name as class_name, cs.section_name, s.name as school_section_name,
               (SELECT COUNT(*) FROM students st WHERE st.class_id = tca.class_id AND st.status = 'Active') as student_count
        FROM teacher_class_assignments tca
        JOIN classes c ON tca.class_id = c.id
        LEFT JOIN class_sections cs ON tca.class_section_id = cs.id
        LEFT JOIN school_sections s ON c.section_id = s.id
        WHERE tca.teacher_id = ?
        ORDER BY c.display_order ASC;
    """, (teacher['id'],)).fetchall()

    # Total students under teacher's assigned classes
    total_assigned_students = sum(ac['student_count'] for ac in assigned_classes)

    # Today's attendance marking status for these classes
    class_ids = [str(ac['class_id']) for ac in assigned_classes]
    today_marked_count = 0
    if class_ids:
        in_clause = ','.join(class_ids)
        row = db.execute(f"""
            SELECT COUNT(DISTINCT student_id) as cnt
            FROM attendance_records
            WHERE date = ? AND class_id IN ({in_clause});
        """, (today_str,)).fetchone()
        today_marked_count = row['cnt'] or 0

    # Relevant notices
    notices = db.execute("""
        SELECT * FROM notices
        WHERE is_active = 1
        ORDER BY publish_date DESC LIMIT 5;
    """).fetchall()

    return render_template('teacher/dashboard.html',
        settings=get_school_settings(),
        teacher=teacher,
        assigned_classes=assigned_classes,
        total_students=total_assigned_students,
        today_marked=today_marked_count,
        notices=notices
    )

# ==================== 2. ATTENDANCE MARKING ====================

@teacher_bp.route('/attendance', methods=['GET', 'POST'])
def attendance():
    teacher = _get_current_teacher_data()
    db = get_db()
    selected_date = request.args.get('date', date.today().isoformat())
    selected_class_id = request.args.get('class_id')
    selected_section_id = request.args.get('class_section_id')

    # Assigned classes only!
    assigned_classes = db.execute("""
        SELECT DISTINCT c.id, c.name
        FROM teacher_class_assignments tca
        JOIN classes c ON tca.class_id = c.id
        WHERE tca.teacher_id = ?
        ORDER BY c.display_order ASC;
    """, (teacher['id'],)).fetchall()

    if not selected_class_id and assigned_classes:
        selected_class_id = str(assigned_classes[0]['id'])

    # Verify teacher is allowed for this class
    if selected_class_id:
        allowed = db.execute("""
            SELECT id FROM teacher_class_assignments 
            WHERE teacher_id = ? AND class_id = ?;
        """, (teacher['id'], selected_class_id)).fetchone()
        if not allowed:
            abort(403)

    class_sections = []
    if selected_class_id:
        class_sections = db.execute("SELECT * FROM class_sections WHERE class_id = ? ORDER BY section_name ASC;", (selected_class_id,)).fetchall()
        if not selected_section_id and class_sections:
            selected_section_id = str(class_sections[0]['id'])

    if request.method == 'POST':
        post_date = request.form.get('date', selected_date)
        post_class_id = request.form.get('class_id')
        post_section_id = request.form.get('class_section_id')

        # Double check permission
        allowed = db.execute("""
            SELECT id FROM teacher_class_assignments 
            WHERE teacher_id = ? AND class_id = ?;
        """, (teacher['id'], post_class_id)).fetchone()
        if not allowed:
            abort(403)

        student_ids = request.form.getlist('student_ids')
        for sid in student_ids:
            st_status = request.form.get(f'status_{sid}', 'Present')
            remarks = request.form.get(f'remarks_{sid}', '').strip()

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
        log_audit('TEACHER_MARK_ATTENDANCE', 'attendance_records', f"{post_class_id}_{post_date}", f"Teacher {teacher['full_name']} marked attendance on {post_date}", current_user.id, current_user.username)
        flash("Class attendance successfully submitted and updated.", "success")
        return redirect(url_for('teacher.attendance', date=post_date, class_id=post_class_id, class_section_id=post_section_id))

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

    return render_template('teacher/attendance.html',
        settings=get_school_settings(),
        teacher=teacher,
        selected_date=selected_date,
        selected_class_id=int(selected_class_id) if selected_class_id else None,
        selected_section_id=int(selected_section_id) if selected_section_id else None,
        classes=assigned_classes,
        class_sections=class_sections,
        roster=roster
    )

# ==================== 3. STUDENTS LIST (ASSIGNED CLASSES) ====================

@teacher_bp.route('/students')
def students():
    teacher = _get_current_teacher_data()
    db = get_db()

    students_list = db.execute("""
        SELECT s.*, c.name as class_name, cs.section_name as class_section_name
        FROM students s
        JOIN classes c ON s.class_id = c.id
        LEFT JOIN class_sections cs ON s.class_section_id = cs.id
        JOIN teacher_class_assignments tca ON tca.class_id = s.class_id
        WHERE tca.teacher_id = ? AND s.status = 'Active'
        GROUP BY s.id
        ORDER BY c.name, s.roll_number, s.full_name ASC;
    """, (teacher['id'],)).fetchall()

    return render_template('teacher/students.html',
        settings=get_school_settings(),
        teacher=teacher,
        students=students_list
    )
