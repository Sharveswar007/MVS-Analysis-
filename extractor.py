
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
    """Normalize teacher name for comparison - removes special characters."""
    if not name:
        return ""
    # Remove dots, spaces, parentheses, brackets, dashes, commas and lowercase
    return re.sub(r'[.\s()\[\]\-,/]', '', name).lower().strip()

def matches_query(query, text):
    """
    Flexible matching for faculty search. Supports:
    - Name only (e.g., "Dr.Smith")
    - Faculty ID only (e.g., "EMP123")
    - Both name and ID (e.g., "Dr.Smith EMP123")
    """
    if not query or not text:
        return False
    
    norm_text = normalize_name(text)
    norm_query = normalize_name(query)
    
    # Direct substring match (covers single name or single ID)
    if norm_query in norm_text:
        return True
    
    # Split query into tokens and check if ALL tokens match individually
    parts = query.strip().split()
    if len(parts) > 1:
        if all(normalize_name(part) in norm_text for part in parts):
            return True
    
    return False

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

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _check_consistency(metrics):
    """
    Checks mathematical consistency of a metrics list.
    Pass% (index 3) should match (passed / appeared) * 100.
    Returns 1.0 (consistent), 0.5 (close), or 0.0 (inconsistent).
    """
    if len(metrics) < 4:
        return 0.0
    try:
        strength = float(metrics[0])
        absent   = float(metrics[1])
        fail     = float(metrics[2])
        pass_pct = float(metrics[3])
    except (ValueError, TypeError):
        return 0.0

    if strength <= 0:
        return 0.0
    appeared = strength - absent
    if appeared <= 0:
        return 0.0

    passed = appeared - fail
    calc_pct = (passed / appeared) * 100
    diff = abs(calc_pct - pass_pct)

    if diff <= 2:
        return 1.0
    elif diff <= 5:
        return 0.5
    return 0.0


def _build_results_list(all_matches, course, subject_code, test_name, method, raw_text):
    """Turns a list of match dicts into the standard results_list format."""
    results_list = []
    for match_data in all_matches:
        results_list.append({
            "course": course,
            "subject_code": subject_code,
            "dataset": test_name,
            "data": match_data,
            "method": method,
            "raw_text": raw_text,
        })
    return results_list


def _extract_with_pdfplumber(file_bytes, teacher_name_query):
    """
    Runs pdfplumber-based extraction only.
    Returns a results_list (may be empty).
    """
    logger.info(f"[pdfplumber] Extracting for: {teacher_name_query}")
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                logger.warning("[pdfplumber] Empty PDF.")
                return []

            full_text = ""
            all_tables = []

            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
                tables = page.extract_tables()
                all_tables.extend(tables)

            if len(full_text.strip()) < 50:
                logger.warning("[pdfplumber] Low text density – likely a scanned PDF.")
                return []  # Caller will still run OCR

            # --- Metadata ---
            course = "Unknown Course"
            subject_code = "Unknown Code"
            test_name = "Unknown Test"

            course_match = re.search(r"Course\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
            if course_match:
                course = course_match.group(1).strip()
                subject_code = course.split("-")[0].strip() if "-" in course else course.split()[0].strip()

            test_match = re.search(r"Test Name\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
            if test_match:
                test_name = test_match.group(1).strip()

            logger.info(f"[pdfplumber] Metadata – Course: {course}, Code: {subject_code}, Test: {test_name}")

            # --- Matches ---
            all_matches = []

            for table in all_tables:
                for row in table:
                    clean_row = [str(cell) if cell is not None else "" for cell in row]

                    merged_cell_match = False
                    for cell in clean_row:
                        if "\n" in cell and matches_query(teacher_name_query, cell):
                            cell_matches = parse_all_text_lines(cell, teacher_name_query)
                            if cell_matches:
                                all_matches.extend(cell_matches)
                                merged_cell_match = True
                            if merged_cell_match:
                                break

                    if merged_cell_match:
                        continue

                    if any("Faculty Name" in cell for cell in clean_row):
                        continue

                    found_name = None
                    for cell in clean_row:
                        if matches_query(teacher_name_query, cell):
                            found_name = cell
                            break

                    if found_name:
                        match = parse_table_row(clean_row, found_name)
                        if match:
                            all_matches.append(match)

            if not all_matches:
                logger.warning("[pdfplumber] Table extraction: no match. Trying line-by-line...")
                all_matches = parse_all_text_lines(full_text, teacher_name_query)

            if not all_matches:
                logger.warning(f"[pdfplumber] No data found for '{teacher_name_query}'.")
                return []

            return _build_results_list(all_matches, course, subject_code, test_name,
                                       "pdfplumber_native", full_text)

    except Exception as e:
        logger.error(f"[pdfplumber] Extraction failed: {e}")
        return []


def _extract_with_ocr(file_bytes, teacher_name_query, api_key):
    """
    Runs OCR-based extraction only.
    Returns a results_list (may be empty).
    """
    if not api_key:
        logger.warning("[OCR] No API key – skipping OCR extraction.")
        return []

    logger.info(f"[OCR] Extracting for: {teacher_name_query}")
    full_text = fetch_ocr_text(file_bytes, api_key)

    if not full_text:
        return []

    all_matches = parse_all_text_lines(full_text, teacher_name_query)

    if not all_matches:
        logger.warning(f"[OCR] No data found for '{teacher_name_query}'.")
        return []

    course = "Unknown (OCR)"
    test_name = "Unknown (OCR)"
    course_match = re.search(r"Course\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
    if course_match:
        course = course_match.group(1).strip()
    test_match = re.search(r"Test Name\s*[:|-]\s*(.*)", full_text, re.IGNORECASE)
    if test_match:
        test_name = test_match.group(1).strip()

    subject_code = course.split("-")[0].strip() if "-" in course else course.split()[0].strip()

    return _build_results_list(all_matches, course, subject_code, test_name,
                               "ocr_api", full_text)


def cross_verify_results(plumber_results, ocr_results, teacher_name_query):
    """
    Cross-verifies pdfplumber and OCR results.
    
    Strategy:
    - If both found data, compare key metrics (strength, absent, fail) per entry.
      * diff <= 3  → confirmed match → use pdfplumber (higher structural fidelity)
      * diff <= 15 → minor mismatch  → prefer pdfplumber but flag as partial
      * diff > 15  → major mismatch  → pick whichever is mathematically consistent
    - If only one found data, use that result (flagged as unverified/single-source).
    - If neither found data, return empty list.
    """
    if not plumber_results and not ocr_results:
        logger.warning(f"[CrossVerify] Both methods found no data for '{teacher_name_query}'.")
        return []

    if not plumber_results:
        logger.warning(f"[CrossVerify] pdfplumber: no data. Using OCR results only.")
        for r in ocr_results:
            r["method"] = "ocr_only"
            r["verified"] = False
        return ocr_results

    if not ocr_results:
        logger.info(f"[CrossVerify] OCR: no data. Using pdfplumber results (unverified).")
        for r in plumber_results:
            r["verified"] = False
        return plumber_results

    logger.info(
        f"[CrossVerify] pdfplumber={len(plumber_results)} entries, OCR={len(ocr_results)} entries."
    )

    verified = []

    for p_item in plumber_results:
        p_metrics = p_item.get("data", {}).get("metrics", [])
        if len(p_metrics) < 3:
            verified.append({**p_item, "verified": False, "method": "pdfplumber_unverified"})
            continue

        best_ocr = None
        best_diff = float("inf")

        for o_item in ocr_results:
            o_metrics = o_item.get("data", {}).get("metrics", [])
            if len(o_metrics) < 3:
                continue
            diff = sum(abs(float(p_metrics[i]) - float(o_metrics[i])) for i in range(3))
            if diff < best_diff:
                best_diff = diff
                best_ocr = o_item

        if best_ocr is None:
            # No comparable OCR entry found
            verified.append({**p_item, "verified": False, "method": "pdfplumber_no_ocr_match"})
            continue

        if best_diff <= 3:
            logger.info(f"[CrossVerify] CONFIRMED (diff={best_diff:.1f}): metrics match. Using pdfplumber.")
            verified.append({**p_item, "verified": True, "method": "pdfplumber_verified"})

        elif best_diff <= 15:
            logger.warning(f"[CrossVerify] MINOR MISMATCH (diff={best_diff:.1f}): preferring pdfplumber.")
            verified.append({**p_item, "verified": "partial", "method": "pdfplumber_preferred"})

        else:
            logger.warning(f"[CrossVerify] MAJOR MISMATCH (diff={best_diff:.1f}): checking consistency.")
            p_score = _check_consistency(p_metrics)
            o_metrics = best_ocr.get("data", {}).get("metrics", [])
            o_score = _check_consistency(o_metrics)
            logger.info(f"[CrossVerify] Consistency scores – pdfplumber={p_score}, OCR={o_score}")

            if p_score >= o_score:
                logger.info("[CrossVerify] Using pdfplumber (equal or better consistency).")
                verified.append({**p_item, "verified": False, "method": "pdfplumber_inconsistent"})
            else:
                logger.info("[CrossVerify] Using OCR (better consistency).")
                verified.append({**best_ocr, "verified": False, "method": "ocr_preferred"})

    # If OCR found more entries than pdfplumber, append the extras
    if len(ocr_results) > len(plumber_results):
        logger.info(
            f"[CrossVerify] OCR found {len(ocr_results) - len(plumber_results)} extra entries not in pdfplumber."
        )
        # Naive heuristic: extra entries are OCR results beyond the matched count
        for o_item in ocr_results[len(plumber_results):]:
            verified.append({**o_item, "verified": False, "method": "ocr_extra"})

    if not verified:
        logger.warning("[CrossVerify] Verification produced no results. Returning OCR results as fallback.")
        for r in ocr_results:
            r["method"] = "ocr_fallback"
        return ocr_results

    return verified


def extract_pdf_data(file_bytes, teacher_name_query, ocr_api_key=None):
    """
    Extracts data from a PDF (bytes) for a specific teacher.
    Always runs BOTH pdfplumber and OCR (when an API key is present),
    cross-verifies the two result sets, then returns the most reliable data.
    """
    logger.info(f"Starting dual extraction for teacher: {teacher_name_query}")

    # --- Step 1: pdfplumber ---
    plumber_results = _extract_with_pdfplumber(file_bytes, teacher_name_query)

    # --- Step 2: OCR ---
    ocr_results = _extract_with_ocr(file_bytes, teacher_name_query, ocr_api_key)

    # --- Step 3: Cross-verify & return ---
    return cross_verify_results(plumber_results, ocr_results, teacher_name_query)

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
    all_matches = parse_all_text_lines(full_text, teacher_name_query)
    
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

def parse_all_text_lines(text, teacher_query):
    """
    Finds ALL occurrences of the teacher in the text lines.
    Supports searching by name, faculty ID, or both.
    Returns a list of match dicts.
    """
    matches = []
    lines = text.splitlines()
    for line in lines:
        if matches_query(teacher_query, line):
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

def _overall_parse_ocr_lines(ocr_text):
    """Helper: parse numeric data rows from OCR text for overall extraction."""
    matches = []
    for line in ocr_text.splitlines():
        if "Total" in line or "Range" in line or "Faculty" in line:
            continue
        numbers = re.findall(r"[-+]?\d*\.\d+|\d+", line)
        valid_nums = []
        for n in numbers:
            try:
                valid_nums.append(float(n))
            except (ValueError, TypeError):
                pass
        if len(valid_nums) >= 10:
            matches.append({
                "raw_row": line,
                "metrics": valid_nums[-10:],
                "faculty_name": "",
            })
    return matches


def extract_overall_data(file_bytes, ocr_api_key=None):
    """
    Extracts ALL rows from a PDF and aggregates them into a single result.
    Used for Overall Result Analysis.

    Always runs BOTH pdfplumber and OCR (if API key is available).
    Cross-verifies by comparing row counts and total student numbers;
    chooses whichever source is more complete / internally consistent,
    then falls back to merging both if they complement each other.
    """
    logger.info("Starting dual overall extraction (all rows \u2192 aggregate).")

    # ------------------------------------------------------------------ #
    # STEP 1 \u2013 pdfplumber
    # ------------------------------------------------------------------ #
    plumber_matches = []
    plumber_text    = ""
    course          = "Unknown Course"
    subject_code    = "Unknown Code"
    test_name       = "Unknown Test"

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if not pdf.pages:
                raise Exception("Empty PDF")

            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    plumber_text += text + "\n"

                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        clean_row = [str(cell) if cell is not None else "" for cell in row]
                        if any(x in str(clean_row) for x in ["Faculty Name", "Test Component", "S.No"]):
                            continue
                        match = parse_table_row(clean_row)
                        if match:
                            plumber_matches.append(match)

        if plumber_text:
            cm = re.search(r"Course\s*[:|-]\s*(.*)", plumber_text, re.IGNORECASE)
            if cm:
                course = cm.group(1).strip()
                subject_code = course.split("-")[0].strip() if "-" in course else course.split()[0].strip()
            tm = re.search(r"Test Name\s*[:|-]\s*(.*)", plumber_text, re.IGNORECASE)
            if tm:
                test_name = tm.group(1).strip()

        logger.info(f"[pdfplumber overall] Found {len(plumber_matches)} data rows.")

    except Exception as e:
        logger.error(f"[pdfplumber overall] Extraction error: {e}")

    # ------------------------------------------------------------------ #
    # STEP 2 \u2013 OCR
    # ------------------------------------------------------------------ #
    ocr_matches = []
    ocr_text    = ""

    if ocr_api_key:
        ocr_text = fetch_ocr_text(file_bytes, ocr_api_key)
        if ocr_text:
            ocr_matches = _overall_parse_ocr_lines(ocr_text)
            logger.info(f"[OCR overall] Found {len(ocr_matches)} data rows.")

            # Fill in metadata from OCR if pdfplumber couldn\u2019t parse it
            if course == "Unknown Course":
                cm = re.search(r"Course\s*[:|-]\s*(.*)", ocr_text, re.IGNORECASE)
                if cm:
                    course = cm.group(1).strip()
                    subject_code = course.split("-")[0].strip() if "-" in course else course.split()[0].strip()
            if test_name == "Unknown Test":
                tm = re.search(r"Test Name\s*[:|-]\s*(.*)", ocr_text, re.IGNORECASE)
                if tm:
                    test_name = tm.group(1).strip()

    # ------------------------------------------------------------------ #
    # STEP 3 \u2013 Cross-verify & decide which set to aggregate
    # ------------------------------------------------------------------ #
    def _total_strength(matches):
        total = 0.0
        for m in matches:
            try:
                total += float(m["metrics"][0])
            except (IndexError, ValueError, TypeError):
                pass
        return total

    p_count  = len(plumber_matches)
    o_count  = len(ocr_matches)
    p_total  = _total_strength(plumber_matches)
    o_total  = _total_strength(ocr_matches)

    logger.info(
        f"[CrossVerify overall] pdfplumber: {p_count} rows / {p_total:.0f} students | "
        f"OCR: {o_count} rows / {o_total:.0f} students"
    )

    selected_matches = []
    method_used      = "none"

    if p_count > 0 and o_count > 0:
        # Both have data \u2013 pick the more complete one
        if p_count >= o_count and abs(p_total - o_total) / max(p_total, o_total, 1) < 0.05:
            # Very close \u2013 pdfplumber regarded as more accurate
            logger.info("[CrossVerify overall] Both agree. Using pdfplumber.")
            selected_matches = plumber_matches
            method_used      = "pdfplumber_verified"
        elif o_count > p_count:
            logger.warning(
                f"[CrossVerify overall] OCR found MORE rows ({o_count} > {p_count}). Using OCR."
            )
            selected_matches = ocr_matches
            method_used      = "ocr_preferred"
        else:
            # Similar row count but different totals \u2013 check internal consistency
            p_score = sum(_check_consistency(m["metrics"]) for m in plumber_matches)
            o_score = sum(_check_consistency(m["metrics"]) for m in ocr_matches)
            logger.info(f"[CrossVerify overall] Consistency scores \u2013 pdfplumber={p_score:.1f}, OCR={o_score:.1f}")
            if p_score >= o_score:
                selected_matches = plumber_matches
                method_used      = "pdfplumber_preferred"
            else:
                selected_matches = ocr_matches
                method_used      = "ocr_preferred"

    elif p_count > 0:
        logger.info("[CrossVerify overall] Only pdfplumber found data.")
        selected_matches = plumber_matches
        method_used      = "pdfplumber_only"

    elif o_count > 0:
        logger.warning("[CrossVerify overall] Only OCR found data.")
        selected_matches = ocr_matches
        method_used      = "ocr_only"

    else:
        logger.warning("[CrossVerify overall] No data found by either method.")
        return None

    # ------------------------------------------------------------------ #
    # STEP 4 \u2013 Aggregate & return
    # ------------------------------------------------------------------ #
    aggregated = aggregate_metrics(selected_matches)

    return {
        "course":        course,
        "subject_code":  subject_code,
        "dataset":       test_name,
        "data":          aggregated,
        "method":        method_used,
        "raw_text_len":  len(plumber_text or ocr_text),
    }

