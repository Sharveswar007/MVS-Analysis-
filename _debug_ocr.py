import pdfplumber, io, requests
from io import BytesIO

PDF = r'fwdtlpanalysis\O1 Student Attendance Status - As on 25.10.2025.pdf'
API_KEY = 'K81654833188957'

with open(PDF, 'rb') as f:
    data = f.read()

# Only dump pages 5,6,7 (0-indexed: 4,5,6) to understand format
with pdfplumber.open(io.BytesIO(data)) as pdf:
    total = len(pdf.pages)
    print(f"Total pages: {total}")
    for page_num in [5, 6, 7]:   # 1-indexed
        page = pdf.pages[page_num - 1]
        print(f"\n{'='*60}")
        print(f"PAGE {page_num}")
        print('='*60)
        img = page.to_image(resolution=200)
        buf = BytesIO()
        img.original.save(buf, format='PNG')
        buf.seek(0)
        resp = requests.post(
            'https://api.ocr.space/parse/image',
            files={'file': ('page.png', buf.read(), 'image/png')},
            data={'apikey': API_KEY, 'language': 'eng', 'isOverlayRequired': False,
                  'detectOrientation': True, 'scale': True, 'OCREngine': 2},
            timeout=90
        )
        result = resp.json()
        if result.get('ParsedResults'):
            text = result['ParsedResults'][0].get('ParsedText', '')
            print(repr(text[:3000]))
        else:
            print("ERROR:", result)
