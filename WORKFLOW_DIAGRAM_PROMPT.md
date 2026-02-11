# Simple Workflow Diagram for TLP Result Finder

Create a clean, simple workflow diagram showing the TLP Result Finder application flow.

---

## MAIN FLOW

**START** → User opens web application

↓

**WEB UI** → User sees 4 analysis options

↓

**USER SELECTS MODE** → Choose one of 4 paths

---

## 4 ANALYSIS PATHS

### Path 1: Self Analysis
- Upload TLP PDFs + enter teacher name
- Extract teacher's data from PDFs
- Generate teacher-specific Excel report
- Download Excel file

### Path 2: FA Analysis  
- Upload multiple TLP PDFs
- Extract all teachers' data
- Group by test components (FT1, FT2, etc.)
- Generate consolidated Excel report
- Download Excel file

### Path 3: Overall Analysis
- Upload PDFs from different subjects
- Extract data for each subject
- Generate multi-sheet Excel (one sheet per subject)
- Download Excel file

### Path 4: Attendance Analysis
- Upload attendance PDF
- Find students with attendance < 75%
- Generate Excel list of low-attendance students
- Download Excel file

---

## PROCESSING FLOW (Common for all paths)

1. **Receive Files** → FastAPI receives uploaded PDFs

2. **Extract Text** → Try reading PDF text
   - If readable → Use pdfplumber
   - If scanned → Use OCR.Space API

3. **Parse Data** → Extract student records and metrics

4. **Generate Excel** → Create formatted workbook with charts

5. **Send Response** → Download Excel file to user

---

## KEY COMPONENTS

**Frontend:**
- Web UI (HTML page with 4 tabs)

**Backend:**
- FastAPI server (main.py)
- PDF processor (extractor.py)
- Attendance processor (attendance_extractor.py)

**External:**
- OCR.Space API (for scanned PDFs)

**Output:**
- Formatted Excel files with tables and charts

---

## VISUAL SUGGESTIONS

**Colors:**
- Blue: User interface
- Green: API layer  
- Orange: PDF processing
- Yellow: Data processing
- Purple: Excel generation
- Pink: File download

**Shapes:**
- Ovals: Start/End
- Rectangles: Processes
- Diamonds: Decisions (Which mode? Text or OCR?)
- Dashed box: External API (OCR.Space)

**Layout:**
- Show 4 paths branching from mode selection
- All paths converge at Excel generation
- Keep it simple and easy to read