
import pdfplumber
import pandas as pd
import requests
import os
import re
import logging
import io

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def normalize_name(name):
    """Normalize teacher name for comparison."""
    if not name:
        return ""
    # Remove dots, spaces, and lowercase
    return name.lower().replace(".", "").replace(" ", "").strip()

def clean_faculty_name(raw_text):
    """
    Cleans the faculty name string by removing S.No and trailing metrics.
    Example: "107 Dr.Name(123) 43 0..." -> "Dr.Name(123)"
    """
    if not raw_text:
        return ""
        
    # Step 1: Remove S.No if present (digits at start followed by space)
    text = re.sub(r'^\d+\s+', '', raw_text)
    
    # Step 2: Remove trailing metrics (sequence of numbers at end)
    # Regex for sequence of numbers at end: ((\s+\d+(\.\d+)?)+)$
    match = re.search(r'(.*?)(\s+\d+(\.\d+)?)+\s*$', text)
    if match:
        return match.group(1).strip()
    
    return text.strip()

def extract_pdf_data(file_bytes, teacher_name_query, ocr_api_key=None):
    """
    Extracts data from a PDF (bytes) for a specific teacher.
    Returns a dictionary with metadata and the teacher's data row.
    """
    logger.info(f"Starting extraction for teacher: {teacher_name_query}")
    
    # 1. Try Native Extraction with pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                raise Exception("Empty PDF")
            
            # Use first page for full analysis (assuming valid data is on page 1 for now, or concat all)
            # For this specific format, usually it's a 1-2 page report.
            
            full_text = ""
            all_tables = []
            
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
                
                # Extract tables
                tables = page.extract_tables()
                all_tables.extend(tables)
            
            # Check text density to decide if OCR is needed
            if len(full_text.strip()) < 50:
                logger.warning("Low text density detected. PDF might be scanned. Switching to OCR fallback.")
                return extract_with_ocr_fallback(file_bytes, teacher_name_query, ocr_api_key)
            
            logger.info("Native text found. Proceeding with pdfplumber extraction.")
            logger.debug(f"Extracted Text (First 200 chars): {full_text[:200]}")
            
            # 2. Parse Metadata (Course, Test Name)
            course = "Unknown Course"
            subject_code = "Unknown Code"
            test_name = "Unknown Test"
            
            # Heuristic parsing for key headers using Regex in the raw text
            course_match = re.search(r"Course\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
            if course_match:
                course = course_match.group(1).strip()
                # Try to extract code (e.g., "21CSC209J - ...")
                # Assume code is the first part before a dash or space?
                # Usually: CODE - NAME
                if "-" in course:
                     subject_code = course.split("-")[0].strip()
                else:
                     subject_code = course.split()[0].strip() # Fallback to first word
                
            test_match = re.search(r"Test Name\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
            if test_match:
                test_name = test_match.group(1).strip()
                
            logger.info(f"Identified Metadata - Course: {course}, Code: {subject_code}, Test: {test_name}")
            
            # 3. Find Teacher Data in Tables
            all_matches = []
            
            search_name = normalize_name(teacher_name_query)
            
            for table in all_tables:
                for row in table:
                    # Cleaning
                    clean_row = [str(cell) if cell is not None else "" for cell in row]
                    
                    # Check for giant merged cells (newlines in cell)
                    merged_cell_match = False
                    for cell in clean_row:
                        if "\n" in cell and search_name in normalize_name(cell):
                            logger.info("Found teacher inside a merged/multiline cell. Parsing lines within cell.")
                            # Scan ALL lines in this cell
                            cell_matches = parse_all_text_lines(cell, search_name)
                            if cell_matches:
                                all_matches.extend(cell_matches)
                                merged_cell_match = True
                            if merged_cell_match: break 
                    
                    if merged_cell_match:
                        continue # Move to next row

                    # Standard Row Logic
                    if any("Faculty Name" in cell for cell in clean_row):
                        continue
                        
                    found_name = None
                    for cell in clean_row:
                        if search_name in normalize_name(cell):
                            found_name = cell
                            break
                    
                    if found_name:
                        logger.info(f"Found match in row: {clean_row}")
                        match = parse_table_row(clean_row, found_name)
                        if match:
                            all_matches.append(match)
            
            # If no extraction worked, try raw text lines
            if not all_matches:
                logger.warning("Table extraction yielded no match. Trying line-by-line regex on full text...")
                all_matches = parse_all_text_lines(full_text, search_name)

            results_list = []
            
            if not all_matches:
                 logger.warning(f"No data found for teacher '{teacher_name_query}' in native extraction.")
            else:
                 logger.info(f"Found {len(all_matches)} entries for {teacher_name_query}. Returning as separate datasets.")
                 
                 for idx, match_data in enumerate(all_matches):
                     # Use the test name directly without suffix
                     # Suffix was causing issues when grouping by test type in FA analysis
                     unique_test_name = test_name
                         
                     results_list.append({
                        "course": course,
                        "subject_code": subject_code,
                        "dataset": unique_test_name,
                        "data": match_data,
                        "method": "pdfplumber_native",
                        "raw_text": full_text 
                     })
            
            return results_list

    except Exception as e:
        logger.error(f"Native extraction failed: {e}")
        return extract_with_ocr_fallback(file_bytes, teacher_name_query, ocr_api_key)

def fetch_ocr_text(file_bytes, api_key):
    """
    Sends file to OCR.space API and returns extracted text.
    """
    if not api_key:
        logger.error("OCR API key not provided. Skipping OCR fallback.")
        return ""
        
    try:
        logger.info("Sending request to OCR.space API...")
        # OCR.space API endpoint
        url = 'https://api.ocr.space/parse/image'
        
        # Prepare file
        files = {'file': ('report.pdf', file_bytes, 'application/pdf')}
        data = {
            'apikey': api_key,
            'isTable': True, # Try to preserve table structure
            'OCREngine': 2, # Use engine 2 for better text/numbers
            'scale': True
        }
        
        response = requests.post(url, files=files, data=data, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"OCR API Error: {response.status_code} - {response.text}")
            return ""
            
        result = response.json()
        
        if result.get('IsErroredOnProcessing'):
            logger.error(f"OCR Processing Error: {result.get('ErrorMessage')}")
            return ""
            
        # Concatenate text from all pages
        full_text = ""
        if result.get('ParsedResults'):
            for page_res in result['ParsedResults']:
                full_text += page_res.get('ParsedText', '') + "\n"
                
        logger.info(f"OCR Success. Extracted {len(full_text)} characters.")
        return full_text
        
    except Exception as e:
        logger.error(f"OCR Request Failed: {e}")
        return ""

def extract_with_ocr_fallback(file_bytes, teacher_name_query, api_key):
    """
    Fallback extraction using OCR API when native text is missing/garbled.
    """
    logger.info("Attempting OCR fallback extraction...")
    full_text = fetch_ocr_text(file_bytes, api_key)
    
    if not full_text:
        return []
        
    # Search in OCR text
    search_name = normalize_name(teacher_name_query)
    all_matches = parse_all_text_lines(full_text, search_name)
    
    results = []
    if all_matches:
        # We don't have metadata easily from OCR text usually, unless we parse headers
        # Try to parse course/test from full text same as before
        course = "Unknown (OCR)"
        test_name = "Unknown (OCR)"
        
        course_match = re.search(r"Course\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
        if course_match: course = course_match.group(1).strip()
            
        test_match = re.search(r"Test Name\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
        if test_match: test_name = test_match.group(1).strip()
            
        aggregated = aggregate_metrics(all_matches)
        
        results.append({
            "course": course,
            "subject_code": course.split('-')[0].strip() if '-' in course else course.split()[0],
            "dataset": test_name,
            "data": aggregated, # Return aggregated for single teacher query?
            # Or should we return list? extract_pdf_data returns list.
            # But aggregate_metrics returns dict.
            # extract_pdf_data returns list of dicts with 'data' field being the row/match.
            # Let's return list of matches.
            "data": all_matches[0], # Return first match for now or loop?
            "method": "ocr_api",
            "raw_text": full_text
        })
        # Wait, previous loop in extract_pdf_data returned one entry per match.
        # Let's do that.
        results = []
        for idx, match in enumerate(all_matches):
             results.append({
                "course": course,
                "subject_code": course.split('-')[0].strip() if '-' in course else course.split()[0],
                "dataset": test_name,
                "data": match,
                "method": "ocr_api",
                "raw_text": full_text
            })
            
    return results

def parse_table_row(row_list, faculty_name=None):
    """
    Parses a standard table row.
    """
    numbers = []
    
    for cell in row_list:
        clean = cell.replace("%", "").strip()
        tokens = clean.replace("\n", " ").split()
        for t in tokens:
            try:
                val = float(t)
                numbers.append(val)
            except:
                continue
            
    if len(numbers) < 10:
        return None
        
    data_points = numbers[-10:] 
    
    return {
        "raw_row": row_list,
        "metrics": data_points,
        "faculty_name": clean_faculty_name(faculty_name) if faculty_name else ""
    }

def parse_all_text_lines(text, search_name_norm):
    """
    Finds ALL occurrences of the teacher in the text lines.
    Returns a list of match dicts.
    """
    matches = []
    lines = text.splitlines()
    for line in lines:
        clean_line = normalize_name(line)
        if search_name_norm in clean_line:
            numbers = re.findall(r"[-+]?\d*\.\d+|\d+", line)
            valid_nums = []
            for n in numbers:
                 try: valid_nums.append(float(n))
                 except: pass
            
            if len(valid_nums) >= 10:
                logger.info(f"Line match success: {line.strip()}")
                matches.append({
                    "raw_row": line,
                    "metrics": valid_nums[-10:],
                    "faculty_name": clean_faculty_name(line.strip()) 
                })
    return matches

def aggregate_metrics(matches_list):
    """
    Aggregates a list of match dictionaries into a single result.
    """
    if not matches_list:
        return None
        
    if len(matches_list) == 1:
        return matches_list[0]
        
    total_strength = 0.0
    total_absent = 0.0
    total_fail = 0.0
    total_ranges = [0.0] * 6
    
    for m in matches_list:
        metrics = m['metrics']
        total_strength += metrics[0]
        total_absent += metrics[1]
        total_fail += metrics[2]
        
        for i in range(6):
            if 4+i < len(metrics):
                total_ranges[i] += metrics[4+i]
                
    total_passed = total_strength - total_absent - total_fail
    
    new_pass_pct = 0.0
    if total_strength > 0:
        appeared = total_strength - total_absent
        if appeared > 0:
             new_pass_pct = (total_passed / appeared) * 100
    
    final_metrics = [
        total_strength,
        total_absent,
        total_fail,
        new_pass_pct
    ] + total_ranges
    
    return {
        "raw_row": "AGGREGATED",
        "metrics": final_metrics,
        "match_count": len(matches_list),
        "faculty_name": matches_list[0].get("faculty_name", "")
    }

def extract_overall_data(file_bytes, ocr_api_key=None):
    """
    Extracts ALL data from a PDF (bytes) and aggregates it into a single result.
    Used for Overall Result Analysis.
    """
    logger.info("Starting overall extraction (aggregating all rows).")
    
    full_text = ""
    course = "Unknown Course"
    subject_code = "Unknown Code"
    test_name = "Unknown Test"
    all_matches = []
    
    try:
        # 1. Native Extraction
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                raise Exception("Empty PDF")
            
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
                
                # Table Extraction
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        clean_row = [str(cell) if cell is not None else "" for cell in row]
                        # Skip typical headers
                        if any(x in str(clean_row) for x in ["Faculty Name", "Test Component", "S.No"]):
                            continue
                        
                        match = parse_table_row(clean_row)
                        if match:
                            all_matches.append(match)
                            
        # Metadata parsing from native text
        if full_text:
            course_match = re.search(r"Course\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
            if course_match:
                course = course_match.group(1).strip()
                subject_code = course.split("-")[0].strip() if "-" in course else course.split()[0].strip()
            
            test_match = re.search(r"Test Name\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
            if test_match:
                test_name = test_match.group(1).strip()

        # 2. OCR Fallback if no data found
        if not all_matches:
            logger.warning("No data found via native table extraction. Trying OCR fallback...")
            ocr_text = fetch_ocr_text(file_bytes, ocr_api_key)
            if ocr_text:
                full_text = ocr_text # Use OCR text for line parsing
                
                # Re-parse metadata from OCR text if unknown
                if course == "Unknown Course":
                    course_match = re.search(r"Course\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
                    if course_match:
                         course = course_match.group(1).strip()
                         subject_code = course.split("-")[0].strip() if "-" in course else course.split()[0].strip()
                         
                if test_name == "Unknown Test":
                     test_match = re.search(r"Test Name\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
                     if test_match: test_name = test_match.group(1).strip()

                # Parse lines from OCR text
                lines = full_text.splitlines()
                for line in lines:
                     # Check if line has enough numbers (10+)
                     numbers = re.findall(r"[-+]?\d*\.\d+|\d+", line)
                     
                     # Filter out likely headers (contains "Total", "Range", etc but also verify numbers)
                     if "Total" in line or "Range" in line:
                         continue
                         
                     valid_nums = []
                     for n in numbers:
                         try: valid_nums.append(float(n))
                         except: pass
                         
                     if len(valid_nums) >= 10:
                          all_matches.append({
                                "raw_row": line,
                                "metrics": valid_nums[-10:],
                                "faculty_name": "" 
                          })

    except Exception as e:
        logger.error(f"Overall extraction failed: {e}")
        # Try OCR even on exception?
        if not all_matches:
             ocr_text = fetch_ocr_text(file_bytes, ocr_api_key)
             if ocr_text:
                 # Copy-paste logic or recursing? Be careful.
                 # Let's just do simple line parse here for safety
                 nums_found = 0
                 for line in ocr_text.splitlines():
                     numbers = re.findall(r"[-+]?\d*\.\d+|\d+", line)
                     if len(numbers) >= 10 and "Total" not in line:
                          valid_nums = [float(n) for n in numbers if n.replace('.','',1).isdigit()]
                          if len(valid_nums) >= 10:
                              all_matches.append({"metrics": valid_nums[-10:], "faculty_name": ""})

    if not all_matches:
        logger.warning("No data found in overall extraction (including OCR).")
        return None
        
    # Aggregate everything
    aggregated = aggregate_metrics(all_matches)
    
    return {
        "course": course,
        "subject_code": subject_code,
        "dataset": test_name,
        "data": aggregated,
        "method": "pdfplumber_overall" if not ocr_api_key else "ocr_fallback", 
        "raw_text_len": len(full_text)
    }

