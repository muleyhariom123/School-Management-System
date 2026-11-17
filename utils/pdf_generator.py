import io
import os
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from config import Config

def _get_school_logo(school_settings, max_width=60, max_height=60):
    """Retrieve school logo if present on disk, otherwise default logo."""
    logo_path = None
    if school_settings.get('logo_path'):
        full_p = os.path.join(Config.BASE_DIR, 'static', school_settings['logo_path'])
        if os.path.exists(full_p):
            logo_path = full_p
    if not logo_path:
        default_p = os.path.join(Config.BASE_DIR, 'static', 'images', 'default_logo.png')
        if os.path.exists(default_p):
            logo_path = default_p
    
    if logo_path:
        try:
            return RLImage(logo_path, width=max_width, height=max_height)
        except Exception:
            return None
    return None

def _create_header_elements(school_settings, doc_title):
    """Generate consistent branded header with school logo, school name, and contact details."""
    styles = getSampleStyleSheet()
    
    school_name = school_settings.get('school_name', '[ENTER YOUR SCHOOL NAME]')
    school_addr = school_settings.get('school_address', '')
    school_contact = f"Phone: {school_settings.get('school_phone', 'N/A')} | Email: {school_settings.get('school_email', 'N/A')}"
    
    title_style = ParagraphStyle(
        'SchoolTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=18,
        textColor=colors.HexColor('#1e3a8a'),
        alignment=TA_CENTER
    )
    sub_style = ParagraphStyle(
        'SchoolSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#475569'),
        alignment=TA_CENTER
    )
    doc_title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=colors.HexColor('#0f172a'),
        alignment=TA_CENTER,
        spaceBefore=6,
        spaceAfter=6
    )

    logo = _get_school_logo(school_settings)
    header_data = []
    
    info_flowables = [
        Paragraph(school_name, title_style),
        Paragraph(school_addr, sub_style),
        Paragraph(school_contact, sub_style),
        Spacer(1, 4),
        Paragraph(f"<b>{doc_title.upper()}</b>", doc_title_style)
    ]
    
    if logo:
        # Table with logo on left, school info on right
        header_table = Table([[logo, info_flowables]], colWidths=[70, 430])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ]))
        return [header_table, Spacer(1, 10), HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563eb'), spaceAfter=15)]
    else:
        elements = info_flowables + [Spacer(1, 10), HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563eb'), spaceAfter=15)]
        return elements

def generate_fee_receipt_pdf(payment, school_settings):
    """
    Generate an official, branded PDF fee receipt.
    payment: dict-like with receipt_number, student details, payment amount, date, method, etc.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    bold = ParagraphStyle('Bold', parent=normal, fontName='Helvetica-Bold')
    
    currency = school_settings.get('currency_symbol', '$')
    elements = []
    elements.extend(_create_header_elements(school_settings, f"Official Fee Receipt - #{payment['receipt_number']}"))
    
    # Receipt Meta and Student Details in a 2-column key-value box
    meta_data = [
        [
            Paragraph(f"<b>Receipt No:</b> {payment['receipt_number']}", normal),
            Paragraph(f"<b>Payment Date:</b> {payment['payment_date']}", normal)
        ],
        [
            Paragraph(f"<b>Student Name:</b> {payment.get('student_name', 'N/A')}", normal),
            Paragraph(f"<b>Admission No:</b> {payment.get('admission_number', 'N/A')}", normal)
        ],
        [
            Paragraph(f"<b>Class & Section:</b> {payment.get('class_name', '')} - {payment.get('section_name', '')}", normal),
            Paragraph(f"<b>Academic Year:</b> {payment.get('academic_year', 'Current')}", normal)
        ],
        [
            Paragraph(f"<b>Payment Method:</b> {payment['payment_method']}", normal),
            Paragraph(f"<b>Transaction Ref:</b> {payment.get('transaction_reference') or 'N/A'}", normal)
        ]
    ]
    
    meta_table = Table(meta_data, colWidths=[270, 270])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 15))
    
    # Fee Item Breakdown Table
    fee_cat = payment.get('fee_category', 'School Tuition / Composite Fee')
    amt = float(payment.get('amount_paid', 0.0))
    total_assigned = float(payment.get('assigned_amount') or amt)
    concession = float(payment.get('concession_amount') or 0.0)
    
    breakdown_data = [
        [Paragraph("<b>Description</b>", bold), Paragraph("<b>Category</b>", bold), Paragraph("<b>Amount Paid</b>", bold)],
        [
            Paragraph(f"Payment towards {fee_cat}", normal),
            Paragraph(fee_cat, normal),
            Paragraph(f"<b>{currency}{amt:,.2f}</b>", ParagraphStyle('R', parent=normal, alignment=TA_RIGHT))
        ],
        [
            "",
            Paragraph("<b>Total Received:</b>", bold),
            Paragraph(f"<b>{currency}{amt:,.2f}</b>", ParagraphStyle('RT', parent=bold, alignment=TA_RIGHT, textColor=colors.HexColor('#166534')))
        ]
    ]
    
    breakdown_table = Table(breakdown_data, colWidths=[280, 140, 120])
    breakdown_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e7ff')),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f0fdf4')),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    elements.append(breakdown_table)
    elements.append(Spacer(1, 20))
    
    # Financial Status Box if balance is provided
    if 'outstanding_balance' in payment:
        bal = float(payment['outstanding_balance'])
        bal_color = colors.HexColor('#dc2626') if bal > 0 else colors.HexColor('#16a34a')
        bal_text = f"Remaining Outstanding Balance for this Academic Year: <b>{currency}{bal:,.2f}</b>"
        bal_p = Paragraph(bal_text, ParagraphStyle('Bal', parent=normal, textColor=bal_color, alignment=TA_CENTER))
        bal_table = Table([[bal_p]], colWidths=[540])
        bal_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f1f5f9')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#cbd5e1')),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(bal_table)
        elements.append(Spacer(1, 25))

    # Notes & Signature block
    remarks = payment.get('remarks') or 'None'
    elements.append(Paragraph(f"<b>Remarks / Note:</b> {remarks}", normal))
    elements.append(Spacer(1, 35))
    
    sig_data = [
        [
            Paragraph("____________________________<br/><b>Cashier / Accounts Officer</b>", normal),
            Paragraph("____________________________<br/><b>Authorized Headmaster Stamp</b>", ParagraphStyle('SigR', parent=normal, alignment=TA_RIGHT))
        ]
    ]
    sig_table = Table(sig_data, colWidths=[270, 270])
    elements.append(sig_table)
    
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("<font size='8' color='#94a3b8'>* This is an official computer-generated fee receipt. Valid with authorized stamp.</font>", ParagraphStyle('Foot', parent=normal, alignment=TA_CENTER)))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()

def generate_student_profile_pdf(student, school_settings):
    """Generate printable comprehensive Student Profile & Admission Summary."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    bold = ParagraphStyle('B', parent=normal, fontName='Helvetica-Bold')
    section_head = ParagraphStyle('SecH', parent=normal, fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor('#1e40af'), spaceBefore=10, spaceAfter=4)
    
    elements = []
    elements.extend(_create_header_elements(school_settings, f"Student Record - {student['admission_number']}"))
    
    # Student photo or placeholder
    student_photo = None
    if student.get('photo_path'):
        full_sp = os.path.join(Config.BASE_DIR, 'static', student['photo_path'])
        if os.path.exists(full_sp):
            try:
                student_photo = RLImage(full_sp, width=80, height=95)
            except Exception:
                pass
    
    profile_info = [
        [Paragraph(f"<b>Full Name:</b> {student['full_name']}", normal), Paragraph(f"<b>Admission Number:</b> {student['admission_number']}", normal)],
        [Paragraph(f"<b>Date of Birth:</b> {student.get('dob') or 'N/A'}", normal), Paragraph(f"<b>Gender:</b> {student.get('gender') or 'N/A'}", normal)],
        [Paragraph(f"<b>School Section:</b> {student.get('section_name') or 'N/A'}", normal), Paragraph(f"<b>Class & Section:</b> {student.get('class_name', '')} - {student.get('class_section_name', '')}", normal)],
        [Paragraph(f"<b>Roll Number:</b> {student.get('roll_number') or 'N/A'}", normal), Paragraph(f"<b>Academic Year:</b> {student.get('academic_year_name') or 'N/A'}", normal)],
        [Paragraph(f"<b>Admission Date:</b> {student.get('admission_date') or 'N/A'}", normal), Paragraph(f"<b>Status:</b> <b>{student.get('status', 'Active')}</b>", normal)],
    ]
    
    if student_photo:
        p_table = Table(profile_info, colWidths=[220, 220])
        p_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        comp_table = Table([[student_photo, p_table]], colWidths=[90, 450])
        comp_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(comp_table)
    else:
        p_table = Table(profile_info, colWidths=[270, 270])
        p_table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        elements.append(p_table)
        
    elements.append(Spacer(1, 10))
    elements.append(Paragraph("Guardian & Family Information", section_head))
    
    family_info = [
        [Paragraph(f"<b>Father's Name:</b> {student.get('father_name') or 'N/A'}", normal), Paragraph(f"<b>Mother's Name:</b> {student.get('mother_name') or 'N/A'}", normal)],
        [Paragraph(f"<b>Guardian's Name:</b> {student.get('guardian_name') or 'N/A'}", normal), Paragraph(f"<b>Guardian Phone:</b> {student.get('guardian_phone') or 'N/A'}", normal)],
        [Paragraph(f"<b>Emergency Contact:</b> {student.get('emergency_contact') or 'N/A'}", normal), Paragraph(f"<b>Student Email:</b> {student.get('student_email') or 'N/A'}", normal)],
        [Paragraph(f"<b>Previous School:</b> {student.get('previous_school') or 'None'}", normal), Paragraph(f"<b>Residential Address:</b> {student.get('residential_address') or 'N/A'}", normal)],
    ]
    
    fam_table = Table(family_info, colWidths=[270, 270])
    fam_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(fam_table)
    
    elements.append(Spacer(1, 40))
    sig_data = [
        [
            Paragraph("____________________________<br/><b>Parent / Guardian Signature</b>", normal),
            Paragraph("____________________________<br/><b>Headmaster Seal & Signature</b>", ParagraphStyle('SigR2', parent=normal, alignment=TA_RIGHT))
        ]
    ]
    sig_table = Table(sig_data, colWidths=[270, 270])
    elements.append(sig_table)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()

def generate_tabular_report_pdf(title, headers, rows, school_settings, col_widths=None):
    """Generic tabular report PDF (e.g. for attendance or fee listings)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    elements = []
    elements.extend(_create_header_elements(school_settings, title))
    
    data = []
    # Header row
    data.append([Paragraph(f"<b>{h}</b>", ParagraphStyle('TH', parent=normal, fontName='Helvetica-Bold', textColor=colors.HexColor('#1e3a8a'))) for h in headers])
    
    for r in rows:
        data.append([Paragraph(str(c), normal) for c in r])
        
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e2e8f0')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(t)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()
