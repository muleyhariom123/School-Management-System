import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import current_app
from config import Config
from models import get_db

def allowed_file(filename):
    """Check if uploaded file has an allowed extension."""
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in Config.ALLOWED_EXTENSIONS

def save_uploaded_file(file_storage, subfolder='photos'):
    """
    Securely save an uploaded file and return relative static URL path.
    Example return: 'uploads/photos/abc123_student.jpg'
    """
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        return None

    filename = secure_filename(file_storage.filename)
    unique_prefix = uuid.uuid4().hex[:8]
    unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{unique_prefix}_{filename}"
    
    target_dir = os.path.join(Config.UPLOAD_FOLDER, subfolder)
    os.makedirs(target_dir, exist_ok=True)
    
    dest_path = os.path.join(target_dir, unique_filename)
    file_storage.save(dest_path)
    
    return f"uploads/{subfolder}/{unique_filename}"

def generate_receipt_number():
    """Generate a unique sequential receipt number e.g. REC-2026-0001."""
    db = get_db()
    current_year = datetime.now().year
    row = db.execute("""
        SELECT COUNT(*) as count FROM payment_transactions 
        WHERE strftime('%Y', payment_date) = ?
    """, (str(current_year),)).fetchone()
    seq = (row['count'] if row else 0) + 1
    # Check uniqueness
    while True:
        candidate = f"REC-{current_year}-{seq:04d}"
        exists = db.execute("SELECT id FROM payment_transactions WHERE receipt_number = ?", (candidate,)).fetchone()
        if not exists:
            return candidate
        seq += 1

def generate_admission_number(academic_year_name=None):
    """Generate a unique sequential admission number e.g. ADM-2026-001."""
    db = get_db()
    year = datetime.now().year
    row = db.execute("SELECT COUNT(*) as count FROM students;").fetchone()
    seq = (row['count'] if row else 0) + 1
    while True:
        candidate = f"ADM-{year}-{seq:04d}"
        exists = db.execute("SELECT id FROM students WHERE admission_number = ?", (candidate,)).fetchone()
        if not exists:
            return candidate
        seq += 1

def format_currency(amount, symbol='$'):
    """Format float into nice currency representation."""
    try:
        val = float(amount or 0.0)
        return f"{symbol}{val:,.2f}"
    except (ValueError, TypeError):
        return f"{symbol}0.00"
