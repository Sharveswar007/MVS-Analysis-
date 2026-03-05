import attendance_extractor, logging
logging.basicConfig(level=logging.INFO)

with open(r'fwdtlpanalysis\O1 Student Attendance Status - As on 25.10.2025.pdf', 'rb') as f:
    data = f.read()

result = attendance_extractor.extract_attendance_data(data)
print(f'\nTotal students with low attendance: {len(result)}')
for s in result[:10]:
    print(f'  {s["reg_number"]} | {s["name"]}')
    for sub in s['subjects']:
        print(f'    {sub["subject_code"]}: {sub["attendance_percentage"]}%')
