import attendance_extractor, logging, sys
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

with open(r'fwdtlpanalysis\O1 Student Attendance Status - As on 25.10.2025.pdf', 'rb') as f:
    data = f.read()

print("=== Testing _ocr_pdf_to_text ===")
text = attendance_extractor._ocr_pdf_to_text(data)
print(f"OCR returned {len(text)} chars")
print("FIRST 2000 CHARS:")
print(text[:2000])

print("\n=== Testing _parse_attendance_native ===")
students = attendance_extractor._parse_attendance_native(text)
print(f"\nStudents with low attendance: {len(students)}")
for s in students[:10]:
    print(f"  {s['reg_number']} | {s['name']}")
    for sub in s['subjects']:
        print(f"    {sub['subject_code']}: {sub['attendance_percentage']}%")
