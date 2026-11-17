import os
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, abort
from flask_login import login_required, current_user
from models import get_db, get_school_settings, get_student_financial_summary, log_audit
from utils.decorators import student_required
from utils.pdf_generator import generate_fee_receipt_pdf

student_bp = Blueprint('student', __name__, url_prefix='/student')

@student_bp.before_request
@login_required
@student_required
def student_before_request():
    """Ensure all student routes require active student role."""
    if not current_user.student_id:
        abort(403)

def _get_current_student_data():
    """Retrieve full student record belonging strictly to current logged in student."""
    db = get_db()
    student = db.execute("""
        SELECT s.*, sec.name as section_name, c.name as class_name, cs.section_name as class_section_name,
               ay.name as academic_year_name, u.username
        FROM students s
        LEFT JOIN school_sections sec ON s.school_section_id = sec.id
        LEFT JOIN classes c ON s.class_id = c.id
        LEFT JOIN class_sections cs ON s.class_section_id = cs.id
        LEFT JOIN academic_years ay ON s.academic_year_id = ay.id
        LEFT JOIN users u ON s.user_id = u.id
        WHERE s.id = ?;
    """, (current_user.student_id,)).fetchone()
    return student

# ==================== 1. STUDENT DASHBOARD ====================

@student_bp.route('/dashboard')
def dashboard():
    student = _get_current_student_data()
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('auth.logout'))

    db = get_db()
    # Financial summary
    fin = get_student_financial_summary(student['id'])

    # Attendance statistics
    att_stats = db.execute("""
        SELECT 
            COUNT(*) as total_days,
            SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present_days,
            SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent_days,
            SUM(CASE WHEN status = 'Late' THEN 1 ELSE 0 END) as late_days,
            SUM(CASE WHEN status = 'Excused' THEN 1 ELSE 0 END) as excused_days
        FROM attendance_records
        WHERE student_id = ?;
    """, (student['id'],)).fetchone()
    
    total_days = att_stats['total_days'] or 0
    present_days = att_stats['present_days'] or 0
    att_percent = round((present_days / total_days * 100), 1) if total_days > 0 else 0

    # Recent payments (last 3)
    recent_payments = db.execute("""
        SELECT * FROM payment_transactions
        WHERE student_id = ?
        ORDER BY payment_date DESC, id DESC LIMIT 3;
    """, (student['id'],)).fetchall()

    # Relevant notices
    notices = db.execute("""
        SELECT * FROM notices
        WHERE is_active = 1
          AND (expiry_date IS NULL OR expiry_date >= ?)
          AND (
              target_type = 'all' 
              OR (target_type = 'section' AND target_section_id = ?)
              OR (target_type = 'class' AND target_class_id = ?)
          )
        ORDER BY publish_date DESC LIMIT 5;
    """, (date.today().isoformat(), student['school_section_id'], student['class_id'])).fetchall()

    return render_template('student/dashboard.html',
        settings=get_school_settings(),
        student=student,
        financial=fin,
        attendance={
            'total_days': total_days,
            'present_days': present_days,
            'absent_days': att_stats['absent_days'] or 0,
            'rate': att_percent
        },
        recent_payments=recent_payments,
        notices=notices
    )

# ==================== 2. FEES & RECEIPTS ====================

@student_bp.route('/fees')
def fees():
    student = _get_current_student_data()
    db = get_db()
    fin = get_student_financial_summary(student['id'])

    # Fee Assignments
    assigned_fees = db.execute("""
        SELECT sfa.*, fs.fee_category, fs.due_date, fs.description,
               (SELECT COALESCE(SUM(amount_paid), 0.0) FROM payment_transactions WHERE student_fee_assignment_id = sfa.id) as item_paid
        FROM student_fee_assignments sfa
        JOIN fee_structures fs ON sfa.fee_structure_id = fs.id
        WHERE sfa.student_id = ?
        ORDER BY sfa.id ASC;
    """, (student['id'],)).fetchall()

    # Complete Payment History
    payments = db.execute("""
        SELECT p.*, fs.fee_category
        FROM payment_transactions p
        LEFT JOIN student_fee_assignments sfa ON p.student_fee_assignment_id = sfa.id
        LEFT JOIN fee_structures fs ON sfa.fee_structure_id = fs.id
        WHERE p.student_id = ?
        ORDER BY p.payment_date DESC, p.id DESC;
    """, (student['id'],)).fetchall()

    return render_template('student/fees.html',
        settings=get_school_settings(),
        student=student,
        financial=fin,
        assigned_fees=assigned_fees,
        payments=payments
    )

@student_bp.route('/receipts/<int:payment_id>/download')
def download_receipt(payment_id):
    """Securely download PDF fee receipt belonging strictly to this student."""
    db = get_db()
    payment = db.execute("""
        SELECT p.*, s.full_name as student_name, s.admission_number,
               c.name as class_name, cs.section_name, ay.name as academic_year,
               fs.fee_category, sfa.assigned_amount, sfa.concession_amount
        FROM payment_transactions p
        JOIN students s ON p.student_id = s.id
        LEFT JOIN classes c ON s.class_id = c.id
        LEFT JOIN class_sections cs ON s.class_section_id = cs.id
        LEFT JOIN academic_years ay ON s.academic_year_id = ay.id
        LEFT JOIN student_fee_assignments sfa ON p.student_fee_assignment_id = sfa.id
        LEFT JOIN fee_structures fs ON sfa.fee_structure_id = fs.id
        WHERE p.id = ? AND p.student_id = ?;
    """, (payment_id, current_user.student_id)).fetchone()

    if not payment:
        abort(403)

    fin = get_student_financial_summary(current_user.student_id)
    receipt_data = dict(payment)
    receipt_data['outstanding_balance'] = fin['outstanding_balance']

    pdf_bytes = generate_fee_receipt_pdf(receipt_data, get_school_settings())
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="Receipt_{payment["receipt_number"]}.pdf"'}
    )

# ==================== 3. ATTENDANCE ====================

@student_bp.route('/attendance')
def attendance():
    student = _get_current_student_data()
    db = get_db()

    records = db.execute("""
        SELECT * FROM attendance_records
        WHERE student_id = ?
        ORDER BY date DESC LIMIT 60;
    """, (student['id'],)).fetchall()

    att_stats = db.execute("""
        SELECT 
            COUNT(*) as total_days,
            SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present_days,
            SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent_days,
            SUM(CASE WHEN status = 'Late' THEN 1 ELSE 0 END) as late_days,
            SUM(CASE WHEN status = 'Excused' THEN 1 ELSE 0 END) as excused_days
        FROM attendance_records
        WHERE student_id = ?;
    """, (student['id'],)).fetchone()

    total_days = att_stats['total_days'] or 0
    present_days = att_stats['present_days'] or 0
    rate = round((present_days / total_days * 100), 1) if total_days > 0 else 0

    return render_template('student/attendance.html',
        settings=get_school_settings(),
        student=student,
        records=records,
        stats={
            'total': total_days,
            'present': present_days,
            'absent': att_stats['absent_days'] or 0,
            'late': att_stats['late_days'] or 0,
            'excused': att_stats['excused_days'] or 0,
            'rate': rate
        }
    )

# ==================== 4. NOTICES ====================

@student_bp.route('/notices')
def notices():
    student = _get_current_student_data()
    db = get_db()

    notices_list = db.execute("""
        SELECT n.*, u.full_name as author_name
        FROM notices n
        LEFT JOIN users u ON n.author_user_id = u.id
        WHERE n.is_active = 1
          AND (n.expiry_date IS NULL OR n.expiry_date >= ?)
          AND (
              n.target_type = 'all' 
              OR (n.target_type = 'section' AND n.target_section_id = ?)
              OR (n.target_type = 'class' AND n.target_class_id = ?)
          )
        ORDER BY n.publish_date DESC;
    """, (date.today().isoformat(), student['school_section_id'], student['class_id'])).fetchall()

    return render_template('student/notices.html',
        settings=get_school_settings(),
        student=student,
        notices=notices_list
    )

# ==================== 5. PROFILE & ALLOWED EDITS ====================

@student_bp.route('/profile', methods=['GET', 'POST'])
def profile():
    student = _get_current_student_data()
    db = get_db()

    if request.method == 'POST':
        # Student is ONLY allowed to update permitted personal contact fields
        # Strictly disallowed from modifying admission number, name, class, fees, roll number, status!
        student_email = request.form.get('student_email', '').strip()
        emergency_contact = request.form.get('emergency_contact', '').strip()
        residential_address = request.form.get('residential_address', '').strip()

        db.execute("""
            UPDATE students 
            SET student_email = ?, emergency_contact = ?, residential_address = ?
            WHERE id = ?;
        """, (student_email, emergency_contact, residential_address, student['id']))
        
        if student['user_id']:
            db.execute("UPDATE users SET email = ? WHERE id = ?;", (student_email, student['user_id']))
            
        db.commit()
        log_audit('UPDATE_STUDENT_SELF_PROFILE', 'students', str(student['id']), "Student updated allowed personal contact info", current_user.id, current_user.username)
        flash("Personal contact information updated successfully.", "success")
        return redirect(url_for('student.profile'))

    return render_template('student/profile.html',
        settings=get_school_settings(),
        student=student
    )
