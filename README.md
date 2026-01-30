<<<<<<< HEAD
# TLP Result Analysis Tool

A comprehensive FastAPI-based web application for analyzing Test Learning Progress (TLP) results from PDF files and generating detailed Excel reports.

## Features

- **Self Analysis**: Analyze test results for individual teachers
- **Faculty Advisor (FA) Analysis**: Group and analyze results by test components (FT1, FT2, etc.)
- **Overall Analysis**: Generate comprehensive reports for all subjects in a single Excel file
- **PDF Processing**: Supports both native PDF text extraction and OCR fallback
- **Excel Reports**: Automated generation with charts and formatted data
- **Dark Mode**: Toggle between light and dark themes
- **Responsive UI**: Clean, modern interface with tab-based navigation

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: HTML, CSS, JavaScript
- **PDF Processing**: PDFPlumber
- **Excel Generation**: XlsxWriter
- **Data Processing**: Pandas

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Sharveswar007/MVS-Analysis-.git
cd MVS-Analysis-
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file (optional, for OCR API):
```
OCR_API_KEY=your_api_key_here
```

4. Run the application:
```bash
uvicorn main:app --reload
```

5. Open your browser at: `http://localhost:8000`

## Deployment on Render

1. Push your code to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com/)
3. Click "New +" → "Web Service"
4. Connect your GitHub repository
5. Configure:
   - **Name**: tlp-analysis-tool
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add Environment Variable: `OCR_API_KEY` (if needed)
7. Click "Create Web Service"

## Usage

### Self Tab
- Enter teacher name
- Upload PDF file(s)
- Generate individual teacher report

### FA Tab
- Enter Faculty Advisor name
- Add multiple faculty members with their subject codes
- Upload all relevant PDFs
- Generate grouped analysis by test components

### Overall Tab
- Upload all subject PDFs
- Generate single Excel file with multiple sheets (one per subject)

## Team

- **Magi Sharma J** - Full Stack Developer
- **Srivattsa R** - Full Stack Developer
- **Sharveswar M** - Full Stack Developer

## License

MIT License
=======
# MVS-Analysis-
>>>>>>> bf847997231f436185c06d9516304b1ced907494
