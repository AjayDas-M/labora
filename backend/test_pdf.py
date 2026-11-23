import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'labora.settings'
django.setup()

from labs.records import build_pdf

class FakeCollege:
    college_name = 'Test College'
    college_address = '123 Main Street'
    record_title = 'LABORATORY RECORD'
    record_footer = 'Certified bonafide record'
    logo = None
    record_template = None

ctx = {
    'college': FakeCollege(),
    'logo_path': None,
    'college_name': 'Test College',
    'college_address': '123 Main Street',
    'record_title': 'LABORATORY RECORD',
    'record_footer': 'Certified bonafide record',
    'student': {'name': 'Test Student', 'roll_no': '001', 'batch': 'A', 'department': 'CSE'},
    'student_name': 'Test Student',
    'roll_no': '001',
    'batch': 'A',
    'department': 'CSE',
    'subject': {'name': 'Programming', 'code': 'CS101', 'semester': '3', 'academic_year': '2026-27'},
    'subject_name': 'Programming',
    'subject_code': 'CS101',
    'semester': '3',
    'academic_year': '2026-27',
    'entries': [
        {
            'experiment_no': 1,
            'title': 'Hello World',
            'date': '01-01-2026',
            'aim': 'Print hello world',
            'language': 'Python',
            'code': 'print("Hello World")',
            'stdin': '',
            'output': 'Hello World',
            'result': 'Program executed successfully',
            'approved_by': 'Teacher',
            'approved_on': '02-01-2026',
        }
    ],
    'generated_at': '01-01-2026 10:00',
}

data = build_pdf(ctx)
print(f'PDF generated OK: {len(data)} bytes')
with open('test_record.pdf', 'wb') as f:
    f.write(data)
print('Saved to test_record.pdf')
