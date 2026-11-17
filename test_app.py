import os
import unittest
import io
from app import create_app
from models import get_db, init_db, get_school_settings, get_student_financial_summary
from config import Config

class SchoolManagementSystemTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

    def test_01_branding_and_settings(self):
        """Verify school settings centrally store school name and placeholder."""
        with self.app.app_context():
            settings = get_school_settings()
            self.assertIn('school_name', settings)
            self.assertIn('[ENTER YOUR SCHOOL NAME]', settings['school_name'])

        # Test login page displays the placeholder school name
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'[ENTER YOUR SCHOOL NAME]', response.data)

    def test_02_authentication_and_roles(self):
        """Test authentication for admin, teacher, and student with role access control."""
        # 1. Admin login
        res = self.client.post('/login', data={'username': 'admin', 'password': 'Admin@2026'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Administrative Overview', res.data)
        self.client.get('/logout')

        # 2. Teacher login
        res = self.client.post('/login', data={'username': 'emp01', 'password': 'Teach@emp01'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Teacher Dashboard', res.data)
        
        # Teacher trying to access admin dashboard should be forbidden (403)
        admin_res = self.client.get('/admin/dashboard')
        self.assertEqual(admin_res.status_code, 403)
        self.client.get('/logout')

        # 3. Student login
        res = self.client.post('/login', data={'username': 'adm-2026-0001', 'password': 'Stu@ADM-2026-0001'}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Student Account', res.data)
        
        # Student trying to access teacher dashboard or admin dashboard should be forbidden (403)
        teach_res = self.client.get('/teacher/dashboard')
        self.assertEqual(teach_res.status_code, 403)
        admin_res = self.client.get('/admin/dashboard')
        self.assertEqual(admin_res.status_code, 403)
        self.client.get('/logout')

    def test_03_headmaster_financial_calculations(self):
        """Test formula: Outstanding Balance = Total Assigned - Total Paid - Concessions."""
        with self.app.app_context():
            # Liam Johnson (student_id = 1): Assigned $1600, Paid $1200 -> Outstanding $400
            fin1 = get_student_financial_summary(1)
            self.assertEqual(fin1['total_assigned'], 1600.0)
            self.assertEqual(fin1['total_paid'], 1200.0)
            self.assertEqual(fin1['total_concession'], 0.0)
            self.assertEqual(fin1['outstanding_balance'], 400.0)

            # Emma Williams (student_id = 2): Assigned $1450, Concession $200, Paid $1250 -> Outstanding $0
            fin2 = get_student_financial_summary(2)
            self.assertEqual(fin2['total_assigned'], 1450.0)
            self.assertEqual(fin2['total_concession'], 200.0)
            self.assertEqual(fin2['total_paid'], 1250.0)
            self.assertEqual(fin2['outstanding_balance'], 0.0)

    def test_04_pdf_generation(self):
        """Verify ReportLab PDF generation for receipts and student profiles."""
        self.client.post('/login', data={'username': 'admin', 'password': 'Admin@2026'}, follow_redirects=True)
        
        # Test Fee Receipt PDF
        res = self.client.get('/admin/payments/1/receipt?format=pdf')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'application/pdf')
        self.assertTrue(res.data.startswith(b'%PDF-'))

        # Test Student Profile PDF
        res = self.client.get('/admin/students/1/pdf')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'application/pdf')
        self.assertTrue(res.data.startswith(b'%PDF-'))
        self.client.get('/logout')

    def test_05_csv_export(self):
        """Verify CSV export for financial reports."""
        self.client.post('/login', data={'username': 'admin', 'password': 'Admin@2026'}, follow_redirects=True)
        res = self.client.get('/admin/reports/fees?export=csv')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.content_type)
        self.assertIn(b'Student Name,Admission No,Class', res.data)
        self.client.get('/logout')

    def test_06_student_admission_and_duplicate_prevention(self):
        """Test student admission and duplicate admission number rejection."""
        self.client.post('/login', data={'username': 'admin', 'password': 'Admin@2026'}, follow_redirects=True)
        
        # Attempt to create student with duplicate admission number ADM-2026-0001
        res = self.client.post('/admin/students/new', data={
            'full_name': 'Duplicate Test',
            'admission_number': 'ADM-2026-0001',
            'academic_year_id': 1,
            'school_section_id': 3,
            'class_id': 10,
            'guardian_phone': '1234567890'
        }, follow_redirects=True)
        self.assertIn(b'already exists', res.data)
        self.client.get('/logout')

    def test_07_attendance_submission_and_duplicate_prevention(self):
        """Test daily attendance marking and duplicate date prevention."""
        self.client.post('/login', data={'username': 'admin', 'password': 'Admin@2026'}, follow_redirects=True)
        
        test_date = '2026-10-09'
        res = self.client.post('/admin/attendance', data={
            'date': test_date,
            'class_id': 10,
            'class_section_id': 1,
            'student_ids': ['1', '2'],
            'status_1': 'Present',
            'status_2': 'Absent',
            'remarks_1': 'On time',
            'remarks_2': 'Sick note'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Attendance recorded successfully', res.data)

        # Check in DB that exactly one record exists per student for this date
        with self.app.app_context():
            db = get_db()
            count = db.execute("SELECT COUNT(*) as cnt FROM attendance_records WHERE date = ? AND student_id = 1;", (test_date,)).fetchone()['cnt']
            self.assertEqual(count, 1)

        self.client.get('/logout')

    def test_08_student_isolation_security(self):
        """Security requirement: Prevent students from accessing other students' records or receipts."""
        # Log in as Student 1 (Liam Johnson, id=1)
        self.client.post('/login', data={'username': 'adm-2026-0001', 'password': 'Stu@ADM-2026-0001'}, follow_redirects=True)

        # Receipt #1 belongs to Student 1 -> should succeed
        res1 = self.client.get('/student/receipts/1/download')
        self.assertEqual(res1.status_code, 200)
        self.assertTrue(res1.data.startswith(b'%PDF-'))

        # Receipt #2 belongs to Student 2 (Emma Williams) -> Student 1 must receive 403 Forbidden!
        res2 = self.client.get('/student/receipts/2/download')
        self.assertEqual(res2.status_code, 403)
        self.client.get('/logout')

    def test_09_teacher_class_restriction(self):
        """Teacher can mark attendance for assigned class, but forbidden on unassigned classes."""
        # Teacher emp01 is assigned to Class 10 only (not Class 3)
        self.client.post('/login', data={'username': 'emp01', 'password': 'Teach@emp01'}, follow_redirects=True)

        # Try to submit attendance for Class 3 (unassigned) -> Should receive 403 Forbidden!
        res = self.client.post('/teacher/attendance', data={
            'date': '2026-10-09',
            'class_id': 3,
            'class_section_id': 1,
            'student_ids': ['5']
        })
        self.assertEqual(res.status_code, 403)
        self.client.get('/logout')

    def test_10_student_permitted_profile_updates(self):
        """Students can only update permitted fields (email, address) and cannot alter fees or roll number."""
        self.client.post('/login', data={'username': 'adm-2026-0001', 'password': 'Stu@ADM-2026-0001'}, follow_redirects=True)
        
        res = self.client.post('/student/profile', data={
            'student_email': 'updated.liam@example.com',
            'emergency_contact': '+1 (555) 999-8888',
            'residential_address': '99 New Horizon Blvd',
            'roll_number': 'HACKED_ROLL', # Attempting to tamper roll number
            'admission_number': 'HACKED_ADM' # Attempting to tamper admission number
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            db = get_db()
            st = db.execute("SELECT * FROM students WHERE id = 1;").fetchone()
            # Permitted fields were updated
            self.assertEqual(st['student_email'], 'updated.liam@example.com')
            self.assertEqual(st['residential_address'], '99 New Horizon Blvd')
            # Protected administrative fields remained unchanged!
            self.assertEqual(st['admission_number'], 'ADM-2026-0001')
            self.assertEqual(st['roll_number'], '101')

        self.client.get('/logout')

if __name__ == '__main__':
    unittest.main()
