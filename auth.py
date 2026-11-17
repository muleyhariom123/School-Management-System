from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import get_db, User, get_school_settings, log_audit
from utils.helpers import save_uploaded_file

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    """Initial Headmaster setup wizard if no administrator exists."""
    db = get_db()
    admin_count = db.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'admin';").fetchone()['cnt']
    if admin_count > 0:
        flash("System already configured. Please log in.", "info")
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        school_name = request.form.get('school_name', '').strip() or '[ENTER YOUR SCHOOL NAME]'
        school_address = request.form.get('school_address', '').strip()
        school_phone = request.form.get('school_phone', '').strip()
        school_email = request.form.get('school_email', '').strip()
        headmaster_name = request.form.get('headmaster_name', '').strip() or 'Headmaster'
        currency_symbol = request.form.get('currency_symbol', '$').strip() or '$'
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        email = request.form.get('email', '').strip()

        if not username or not password:
            flash("Administrator username and password are required.", "danger")
            return render_template('auth/setup.html', settings=get_school_settings())

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return render_template('auth/setup.html', settings=get_school_settings())

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template('auth/setup.html', settings=get_school_settings())

        # Handle logo upload if provided
        logo_path = ''
        if 'logo' in request.files and request.files['logo'].filename:
            saved = save_uploaded_file(request.files['logo'], subfolder='logos')
            if saved:
                logo_path = saved

        # Update school settings
        db.execute("""
            UPDATE school_settings 
            SET school_name = ?, school_address = ?, school_phone = ?, school_email = ?,
                headmaster_name = ?, currency_symbol = ?, logo_path = CASE WHEN ? != '' THEN ? ELSE logo_path END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1;
        """, (school_name, school_address, school_phone, school_email, headmaster_name, currency_symbol, logo_path, logo_path))

        # Create Admin User
        pw_hash = generate_password_hash(password)
        db.execute("""
            INSERT INTO users (username, password_hash, role, full_name, email, is_active)
            VALUES (?, ?, 'admin', ?, ?, 1)
        """, (username, pw_hash, headmaster_name, email))
        db.commit()

        # Log audit
        log_audit(action='INITIAL_SETUP', target_entity='system', target_id='1', details=f"Initial Headmaster account '{username}' configured.")

        flash("Initial setup completed successfully! Please log in with your Headmaster credentials.", "success")
        return redirect(url_for('auth.login'))

    return render_template('auth/setup.html', settings=get_school_settings())

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Unified secure login for Headmaster, Teachers, and Students."""
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        elif current_user.role == 'student':
            return redirect(url_for('student.dashboard'))
        elif current_user.role == 'teacher':
            return redirect(url_for('teacher.dashboard'))

    # Check if first-run setup is required
    db = get_db()
    admin_count = db.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'admin';").fetchone()['cnt']
    if admin_count == 0:
        return redirect(url_for('auth.setup'))

    if request.method == 'POST':
        login_id = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not login_id or not password:
            flash("Please enter both username/ID and password.", "danger")
            return render_template('auth/login.html', settings=get_school_settings())

        # Allow login by username, email, employee_id (teacher), or admission_number (student)
        user_row = db.execute("""
            SELECT u.*, s.id as student_id, t.id as teacher_id
            FROM users u
            LEFT JOIN students s ON s.user_id = u.id
            LEFT JOIN teachers t ON t.user_id = u.id
            WHERE u.username = ? OR u.email = ? OR s.admission_number = ? OR t.employee_id = ?
        """, (login_id, login_id, login_id, login_id)).fetchone()

        if not user_row or not check_password_hash(user_row['password_hash'], password):
            log_audit(action='FAILED_LOGIN', target_entity='users', details=f"Failed login attempt for: {login_id}")
            flash("Invalid credentials. Please verify your login details and try again.", "danger")
            return render_template('auth/login.html', settings=get_school_settings())

        if not user_row['is_active']:
            flash("This account has been deactivated. Please contact the Headmaster.", "danger")
            return render_template('auth/login.html', settings=get_school_settings())

        user = User(
            id=user_row['id'],
            username=user_row['username'],
            role=user_row['role'],
            full_name=user_row['full_name'],
            email=user_row['email'],
            is_active=user_row['is_active'],
            student_id=user_row['student_id'],
            teacher_id=user_row['teacher_id']
        )
        login_user(user)
        log_audit(action='LOGIN', target_entity='users', target_id=str(user.id), details=f"User {user.username} ({user.role}) logged in.", user_id=user.id, username=user.username)

        flash(f"Welcome back, {user.full_name}!", "success")
        if user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        elif user.role == 'student':
            return redirect(url_for('student.dashboard'))
        elif user.role == 'teacher':
            return redirect(url_for('teacher.dashboard'))
        return redirect(url_for('auth.login'))

    return render_template('auth/login.html', settings=get_school_settings())

@auth_bp.route('/logout')
@login_required
def logout():
    """Securely log out current user."""
    log_audit(action='LOGOUT', target_entity='users', target_id=str(current_user.id), details=f"User {current_user.username} logged out.", user_id=current_user.id, username=current_user.username)
    logout_user()
    flash("You have been securely logged out.", "info")
    return redirect(url_for('auth.login'))

@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """Allow current user to update their account password."""
    current_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')

    db = get_db()
    row = db.execute("SELECT password_hash FROM users WHERE id = ?", (current_user.id,)).fetchone()
    if not row or not check_password_hash(row['password_hash'], current_pw):
        flash("Current password is incorrect.", "danger")
        return redirect(request.referrer or url_for('auth.login'))

    if len(new_pw) < 6:
        flash("New password must be at least 6 characters.", "danger")
        return redirect(request.referrer or url_for('auth.login'))

    if new_pw != confirm_pw:
        flash("New passwords do not match.", "danger")
        return redirect(request.referrer or url_for('auth.login'))

    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new_pw), current_user.id))
    db.commit()
    log_audit(action='PASSWORD_CHANGE', target_entity='users', target_id=str(current_user.id), details="Password successfully changed.", user_id=current_user.id, username=current_user.username)
    flash("Password updated successfully.", "success")
    return redirect(request.referrer or url_for('auth.login'))
