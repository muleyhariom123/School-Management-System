from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user

def role_required(*roles):
    """Decorator to restrict access to users having one of the specified roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to access this page.", "warning")
                return redirect(url_for('auth.login'))
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    """Decorator to require Headmaster/Admin access."""
    return role_required('admin')(f)

def teacher_required(f):
    """Decorator to require Teacher access."""
    return role_required('teacher')(f)

def student_required(f):
    """Decorator to require Student access."""
    return role_required('student')(f)
