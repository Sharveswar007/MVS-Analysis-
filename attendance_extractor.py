import pdfplumber
import pandas as pd
import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_attendance_data(pdf_bytes):
    """Extract low attendance data from image-based PDF using OCR"""
    logger.info(f"Extracting attendance data from PDF")
    
    try:
        import requests
        from io import BytesIO
        import io
        
        OCR_API_KEY = "K81654833188957"
        
        pdf_file = io.BytesIO(pdf_bytes)
        
        with pdfplumber.open(pdf_file) as pdf:
            students_data = {}
            
            for page_num, page in enumerate(pdf.pages, 1):
                logger.info(f"Processing page {page_num} with OCR")
                
                # Convert page to image for OCR
                try:
                    img = page.to_image(resolution=150)
                    img_buffer = BytesIO()
                    img.original.save(img_buffer, format='PNG')
                    img_buffer.seek(0)
                    
                    # Send to OCR API
                    response = requests.post(
                        'https://api.ocr.space/parse/image',
                        files={'file': ('page.png', img_buffer, 'image/png')},
                        data={
                            'apikey': OCR_API_KEY,
                            'language': 'eng',
                            'isOverlayRequired': False,
                            'detectOrientation': True,
                            'scale': True,
                            'OCREngine': 2
                        },
                        timeout=60
                    )
                    
                    result = response.json()
                    
                    if not result.get('ParsedResults'):
                        logger.error(f"OCR failed for page {page_num}")
                        continue
                    
                    text = result['ParsedResults'][0].get('ParsedText', '')
                    
                    if not text:
                        logger.warning(f"No text extracted from page {page_num}")
                        continue
                    
                    logger.info(f"OCR extracted {len(text)} characters from page {page_num}")
                    
                    # Parse the text for attendance data
                    lines = text.split('\n')
                    
                    # Patterns
                    reg_pattern = r'RA\d{13}'
                    subject_pattern = r'\d{2}[A-Z]{3}\d{3}[A-Z]\([A-Z]\)'
                    percentage_pattern = r'\b(\d+\.\d{2})\b'
                    
                    current_reg_no = None
                    current_name = None
                    
                    for i, line in enumerate(lines):
                        # Check for registration number
                        reg_match = re.search(reg_pattern, line)
                        if reg_match:
                            current_reg_no = reg_match.group()
                            # Try to extract name - usually after reg number
                            name_match = re.search(rf'{current_reg_no}\s*\|?\s*([A-Z][A-Z\s]+?)(?:\d{{2}}[A-Z]{{3}}|\||$)', line)
                            if name_match:
                                current_name = name_match.group(1).strip()
                            else:
                                current_name = "Unknown"
                            
                            logger.info(f"Found student: {current_reg_no} - {current_name}")
                        
                        # Look for percentages in this line and next few lines
                        if current_reg_no:
                            # Check current line and next 2 lines for percentages
                            search_lines = [line]
                            if i + 1 < len(lines):
                                search_lines.append(lines[i + 1])
                            if i + 2 < len(lines):
                                search_lines.append(lines[i + 2])
                            
                            combined_text = ' '.join(search_lines)
                            
                            # Find subject codes in this context
                            subject_matches = re.findall(subject_pattern, combined_text)
                            # Find percentages
                            percentage_matches = re.findall(percentage_pattern, combined_text)
                            
                            # Match percentages with subject codes
                            for subject_code in subject_matches:
                                # Find percentage near this subject code
                                # Look for percentages after the subject code in the combined text
                                subject_pos = combined_text.find(subject_code)
                                if subject_pos != -1:
                                    # Search for percentage within next 50 characters
                                    after_subject = combined_text[subject_pos:subject_pos + 50]
                                    percent_match = re.search(percentage_pattern, after_subject)
                                    
                                    if percent_match:
                                        percentage = float(percent_match.group(1))
                                        
                                        # Only include if attendance < 75%
                                        if percentage < 75:
                                            if current_reg_no not in students_data:
                                                students_data[current_reg_no] = {
                                                    'reg_number': current_reg_no,
                                                    'name': current_name,
                                                    'subjects': []
                                                }
                                            
                                            # Check if this subject is already added
                                            existing = [s for s in students_data[current_reg_no]['subjects'] 
                                                      if s['subject_code'] == subject_code]
                                            
                                            if not existing:
                                                students_data[current_reg_no]['subjects'].append({
                                                    'subject_code': subject_code,
                                                    'attendance_percentage': percentage
                                                })
                                                
                                                logger.info(f"Low attendance: {current_reg_no} - {subject_code}: {percentage}%")
                
                except Exception as e:
                    logger.error(f"Error processing page {page_num}: {e}")
                    continue
            
            result = list(students_data.values())
            logger.info(f"Found {len(result)} students with low attendance")
            
            return result
            
    except Exception as e:
        logger.error(f"Error extracting attendance data: {e}")
        raise
