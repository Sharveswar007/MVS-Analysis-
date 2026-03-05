import pdfplumber
import re
import logging
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def detect_subject_codes(pdf_bytes):
    """
    Scan the entire PDF and return all unique subject codes found.
    Tries pdfplumber native text first; falls back to OCR page-by-page
    when the PDF is a scanned / image-only document.
    Returns a sorted list of unique base subject codes (brackets stripped).
    """
    logger.info("Detecting subject codes from PDF")

    subject_code_pattern = r'\d{2}[A-Z]{3}\d{3}[A-Z](?:\([A-Z]\))?'
    found_codes = set()
    native_text_found = False

    # ---- Step 1: pdfplumber native ----
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text and len(text.strip()) > 20:
                    native_text_found = True
                    matches = re.findall(subject_code_pattern, text)
                    for m in matches:
                        base_code = re.sub(r'\([A-Z]\)$', '', m).strip()
                        found_codes.add(base_code)
    except Exception as e:
        logger.error(f"Error in native detect_subject_codes: {e}")

    if found_codes:
        result = sorted(found_codes)
        logger.info(f"Detected subject codes (native): {result}")
        return result

    # ---- Step 2: OCR fallback (scanned / image PDFs) ----
    if not native_text_found:
        logger.warning("No native text found. Falling back to OCR for subject code detection.")
        try:
            ocr_text = _ocr_pdf_to_text(pdf_bytes)
            if ocr_text:
                ocr_text = _normalize_ocr_text(ocr_text)
                matches = re.findall(subject_code_pattern, ocr_text)
                for m in matches:
                    base_code = re.sub(r'\([A-Z]\)$', '', m).strip()
                    found_codes.add(base_code)
        except Exception as e:
            logger.error(f"OCR fallback in detect_subject_codes failed: {e}")

    result = sorted(found_codes)
    logger.info(f"Detected subject codes (OCR): {result}")
    return result


def extract_attendance_data(pdf_bytes):
    """
    Extract low attendance data from PDF.
    Uses native pdfplumber text extraction with positional subject-percentage matching.
    Falls back to OCR only if native text is insufficient.
    """
    logger.info("Extracting attendance data from PDF")

    try:
        pdf_file = io.BytesIO(pdf_bytes)

        with pdfplumber.open(pdf_file) as pdf:
            # Step 1: Try native text extraction (much more reliable than OCR)
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"

            if len(full_text.strip()) >= 100:
                logger.info(f"Native text extracted: {len(full_text)} chars from {len(pdf.pages)} pages")
                result = _parse_attendance_native(full_text)
                if result:
                    return result
                logger.warning("Native parsing found no results, trying OCR fallback...")

            # Step 2: OCR fallback for scanned/image PDFs
            logger.info("Attempting OCR fallback extraction...")
            return _extract_attendance_ocr(pdf_bytes)

    except Exception as e:
        logger.error(f"Error extracting attendance data: {e}")
        raise


def _normalize_ocr_text(text):
    """Fix common OCR misreads before parsing."""
    text = text.replace('|', ' ')
    # Bullet / dot prefixes before subject codes
    text = re.sub(r'[\u2022\u00b7\*]\s*', '', text)
    # '2I' / 'I' misread as '21' in subject codes
    text = re.sub(r'\b2I([A-Z]{3}\d{3}[A-Z])', r'21\1', text)
    text = re.sub(r'\bI(\d[A-Z]{3}\d{3}[A-Z])', r'2\1', text)
    # Comma-as-decimal: 75,00 → 75.00
    text = re.sub(r'\b(\d{1,3}),(\d{2})\b', r'\1.\2', text)
    return text


# ─────────────────────────── shared compiled patterns ────────────────────────
_SUBJ_RE  = re.compile(r'\d{2}[A-Z]{3}\d{3}[A-Z](?:\([A-Z]\))?')
_REG_RE   = re.compile(r'(?:RA|BA)\d{10,15}')
_PCT_RE   = re.compile(r'\b\d{1,3}\.\d{2}\b')
_PURE_PCT = re.compile(r'^\d{1,3}\.\d{2}$')

_SKIP_WORDS = {
    'LAB', 'SLOTS', 'SLOT', 'NAME', 'S.NO', 'PHOTO', 'ID', 'NOTE', 'NSS',
    'NCC', 'FACULTY', 'ADVISOR', 'CONSOLIDATED', 'ACADEMIC', 'STATUS',
    'KINDLY', 'STUDENT_ACADEMIC_STATUS', 'RANGE', 'FORMAT', 'UPLOADED', 'WRONG',
}

# Slot letter -> sort rank (A=0, B=1, ... Z=25; unslotted codes get rank 100)
_SLOT_RANK = {c: i for i, c in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}


def _sort_by_slot(subjects):
    """
    Sort subject codes by their slot letter so positional pct-matching
    stays correct even when OCR outputs subjects out of A-B-C order.
    Unslotted subjects (lab codes without a letter suffix) come last.
    """
    def _key(code):
        m = re.search(r'\(([A-Z])\)$', code)
        return _SLOT_RANK.get(m.group(1), 100) if m else 100
    return sorted(subjects, key=_key)

# Slot letter → sort rank (A=0, B=1, ... Z=25; unslotted=100)
_SLOT_RANK = {c: i for i, c in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}


def _sort_by_slot(subjects):
    """
    Sort subject codes by their slot letter so positional pct-matching
    is reliable even when OCR doesn't output subjects in A-B-C order.
    Unslotted subjects (lab codes, etc.) are placed after slotted ones.
    """
    def _key(code):
        m = re.search(r'\(([A-Z])\)$', code)
        return _SLOT_RANK.get(m.group(1), 100) if m else 100
    return sorted(subjects, key=_key)


def _is_subj_line(line):
    return bool(_SUBJ_RE.search(line))


def _get_subjects(line):
    return _SUBJ_RE.findall(line)


def _base_code(code):
    return re.sub(r'\([A-Z]\)$', '', code).strip()


def _get_pcts(line):
    return [float(x) for x in _PCT_RE.findall(line)]


def _looks_like_name(line):
    if not line or re.match(r'^[\d\s.%\-()/]+$', line):
        return False
    words = line.split()
    upper = [w for w in words if w.isupper() and len(w) >= 2]
    skip  = any(w.upper() in _SKIP_WORDS for w in words)
    return len(upper) >= 1 and not skip


# ─────────────────────────── student data updater ────────────────────────────
def _add_student(students_data, reg_no, name, subjects, percentages):
    """Match subjects → percentages positionally; record those < 75%."""
    if not subjects:
        logger.warning(f"{reg_no}: no subjects to match")
        return

    low = []
    for idx, subj in enumerate(subjects):
        bc = _base_code(subj)
        if idx < len(percentages):
            pct = percentages[idx]
            if pct < 75.0:
                low.append({'subject_code': bc, 'attendance_percentage': pct})
        else:
            logger.warning(f"{reg_no}: missing pct for {bc} (idx {idx}), "
                           f"only {len(percentages)} for {len(subjects)} subjects")

    if not low:
        return

    if reg_no not in students_data:
        students_data[reg_no] = {'reg_number': reg_no, 'name': name, 'subjects': low}
    else:
        existing = {s['subject_code'] for s in students_data[reg_no]['subjects']}
        for s in low:
            if s['subject_code'] not in existing:
                students_data[reg_no]['subjects'].append(s)
                existing.add(s['subject_code'])

    for s in low:
        logger.info(f"Low attendance: {reg_no} ({name}) – "
                    f"{s['subject_code']}: {s['attendance_percentage']}%")


# ─────────────────────────── data-section splitter ───────────────────────────
def _split_data_section(data_lines):
    """
    Split the post-Slots data lines into per-student (subjects, pcts) blocks.

    Uses the invariant: a new student starts when we encounter a subject line
    AND len(pcts_so_far) >= len(subjects_so_far)  (previous block is complete).

    This correctly handles both formats seen in the OCR output:
      • All subjects then all pcts (most pages in Layout B)
      • sub1, pct1, sub2, subs3-9, pcts2-9   (first student on page 5)
    """
    blocks    = []
    cur_subjs = []
    cur_pcts  = []

    for line in data_lines:
        if _is_subj_line(line):
            # Only start a new block when the previous one is balanced (or empty)
            if cur_subjs and len(cur_pcts) >= len(cur_subjs):
                blocks.append((list(cur_subjs), list(cur_pcts)))
                cur_subjs = []
                cur_pcts  = []
            cur_subjs.extend(_get_subjects(line))
        elif _PCT_RE.search(line):
            cur_pcts.extend(_get_pcts(line))

    if cur_subjs:
        blocks.append((cur_subjs, cur_pcts))

    return blocks


# ─────────────────────────── Layout A parser ─────────────────────────────────
def _parse_layout_a(lines, regs, students_data, last_known_subjs):
    """
    Layout A: each reg-number's block directly contains its subjects + pcts.

    Improvements:
    • Extracts pcts from ALL lines (including lines that also contain subject
      codes), so inline values like '21MAB204T(A) 72.73' are captured.
    • Sorts subjects by slot letter (A->B->...) before positional pct-matching
      so OCR column-read reordering doesn't break the alignment.
    • Carries forward subjects when a block has none (table header not repeated).
    Returns updated last_known_subjs.
    """
    for bi, (li, reg_no) in enumerate(regs):
        bend  = regs[bi + 1][0] if bi + 1 < len(regs) else len(lines)
        block = lines[li + 1 : bend]

        raw_subjs, pcts, name_parts = [], [], []

        for line in block:
            if _is_subj_line(line):
                raw_subjs.extend(_get_subjects(line))
                # Also grab any percentage sitting on the same line
                # e.g. '21MAB204T(A) 72.73' or '21CSE253T(C) 72.73'
                pcts.extend(_get_pcts(line))
            elif _PCT_RE.search(line) and not _looks_like_name(line):
                pcts.extend(_get_pcts(line))
            elif _looks_like_name(line) and len(name_parts) < 2:
                name_parts.append(line)

        # Sort by slot letter so A->B->C... order is always preserved
        subjs = _sort_by_slot(raw_subjs)

        # Carry-forward when no subjects in this block
        if not subjs:
            if last_known_subjs:
                subjs = list(last_known_subjs)
                logger.debug(f"{reg_no}: using carry-forward subjects")
            else:
                logger.warning(f"{reg_no}: no subjects found (Layout A)")
                continue
        else:
            last_known_subjs = list(subjs)

        name = ' '.join(name_parts).strip() or 'Unknown'
        _add_student(students_data, reg_no, name, subjs, pcts)

    return last_known_subjs


# ─────────────────────────── Layout B parser ─────────────────────────────────
def _parse_layout_b(lines, regs, slots_idx, students_data):
    """
    Layout B: all reg numbers (and possibly names) appear BEFORE the Slots
    header; per-student data blocks appear AFTER it in matching order.

    Supports two name sub-layouts:
      B1 (page-5 style): names immediately follow their reg number
      B2 (page-7 style): all names clustered after all reg numbers
    """
    # ── Step 1: extract names ─────────────────────────────────────────
    reg_names      = {}
    name_line_used = set()

    # First pass: names within each reg's block (B1 style)
    for bi, (li, reg_no) in enumerate(regs):
        next_pos = regs[bi + 1][0] if bi + 1 < len(regs) else slots_idx
        parts = []
        for j in range(li + 1, min(next_pos, slots_idx)):
            line = lines[j]
            if _looks_like_name(line) and len(parts) < 2:
                parts.append(line)
                name_line_used.add(j)
        reg_names[reg_no] = ' '.join(parts).strip()

    # Second pass: collect names from after last reg up to slots (B2 style)
    orphans = [
        lines[j]
        for j in range(regs[-1][0] + 1, slots_idx)
        if j not in name_line_used and _looks_like_name(lines[j])
    ]

    # Assign orphan names (in order) to regs that got no name
    nameless = [rno for _, rno in regs if not reg_names.get(rno)]
    oi = 0
    for rno in nameless:
        parts = []
        while oi < len(orphans) and len(parts) < 2:
            # Only take 2 if there are enough orphans left for the remaining nameless regs
            remaining_nameless = len(nameless) - nameless.index(rno) - 1
            remaining_orphans  = len(orphans) - oi - 1
            parts.append(orphans[oi])
            oi += 1
            if remaining_orphans <= remaining_nameless:
                break   # save remaining orphans for remaining regs
        reg_names[rno] = ' '.join(parts).strip() or 'Unknown'

    # ── Step 2: parse data section ────────────────────────────────────
    data_lines = lines[slots_idx + 1:]
    if data_lines and re.search(r'lab\s*slots?', data_lines[0], re.IGNORECASE):
        data_lines = data_lines[1:]

    blocks = _split_data_section(data_lines)

    # ── Step 3: zip regs with blocks ──────────────────────────────────
    n = min(len(regs), len(blocks))
    if n < len(regs):
        logger.warning(f"Layout B: {len(regs)} students but {len(blocks)} blocks → pairing first {n}")

    for i in range(n):
        reg_no = regs[i][1]
        name   = reg_names.get(reg_no) or 'Unknown'
        subjs, pcts = blocks[i]
        _add_student(students_data, reg_no, name, subjs, pcts)

    logger.info(f"Layout B: {len(regs)} regs, {len(blocks)} data blocks, paired {n}.")


# ─────────────────────────── per-page entry point ────────────────────────────
def _parse_page_text(page_text, students_data, last_known_subjs=None):
    """
    Parse one page's text (OCR or native) and add results to students_data.

    Automatically detects Layout A vs Layout B:
      Layout A – subjects appear inside each student's reg-number block
      Layout B – all reg numbers listed before a 'Slots' header;
                 data blocks follow the header in the same order

    Returns updated last_known_subjs for carry-forward into the next page.
    """
    if last_known_subjs is None:
        last_known_subjs = []

    page_text = _normalize_ocr_text(page_text)
    lines = [l.strip() for l in page_text.split('\n') if l.strip()]

    # Locate all reg numbers
    regs = []
    for i, line in enumerate(lines):
        m = _REG_RE.search(line)
        if m:
            regs.append((i, m.group()))

    if not regs:
        return last_known_subjs

    # Locate the first 'Slots' line that appears after the first reg number
    slots_idx = None
    for i, line in enumerate(lines):
        if i > regs[0][0] and re.search(r'\bslots?\b', line, re.IGNORECASE):
            slots_idx = i
            break

    # Layout B detection: Slots appears AFTER the last reg AND no reg block has subjects
    is_layout_b = False
    if slots_idx is not None and slots_idx > regs[-1][0]:
        subj_in_any_block = any(
            _is_subj_line(lines[j])
            for bi, (li, _) in enumerate(regs)
            for j in range(li + 1, (regs[bi + 1][0] if bi + 1 < len(regs) else slots_idx))
        )
        if not subj_in_any_block:
            is_layout_b = True

    if is_layout_b:
        logger.info(f"  → Layout B ({len(regs)} regs, slots @ line {slots_idx})")
        _parse_layout_b(lines, regs, slots_idx, students_data)
    else:
        logger.info(f"  → Layout A ({len(regs)} regs)")
        last_known_subjs = _parse_layout_a(lines, regs, students_data, last_known_subjs)

    return last_known_subjs


# ─────────────────────────── public native entry point ───────────────────────
def _parse_attendance_native(full_text):
    """Entry point for native-text PDFs. Processes full text page-aware."""
    students_data    = {}
    last_known_subjs = _parse_page_text(full_text, students_data)
    result = list(students_data.values())
    logger.info(f"Found {len(result)} students with low attendance")
    return result


def _parse_attendance_native_OLD(full_text):  # kept for reference, not called
    """REPLACED – see _parse_page_text / _parse_layout_a / _parse_layout_b."""
    pass


OCR_API_KEY = "K81654833188957"


def _ocr_page_to_text(page_image_bytes, engine=2):
    """
    Send a single rendered page image to OCR.space and return the text.
    engine=1 (default OCR), engine=2 (OCR+), engine=3 (OCR Pro)
    """
    import requests
    try:
        resp = requests.post(
            'https://api.ocr.space/parse/image',
            files={'file': ('page.png', page_image_bytes, 'image/png')},
            data={
                'apikey': OCR_API_KEY,
                'language': 'eng',
                'isOverlayRequired': False,
                'detectOrientation': True,
                'scale': True,
                'OCREngine': engine,
            },
            timeout=90,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get('IsErroredOnProcessing'):
            logger.error(f"OCR.space error: {result.get('ErrorMessage')}")
            return ""

        pages = result.get('ParsedResults') or []
        return "\n".join(p.get('ParsedText', '') for p in pages)

    except Exception as e:
        logger.error(f"OCR.space page request failed: {e}")
        return ""


def _ocr_pdf_to_text(pdf_bytes):
    """
    Render each page as a PNG image and OCR it one at a time.
    Returns the full concatenated text from all pages.
    """
    from io import BytesIO as _BytesIO

    full_text = ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total = len(pdf.pages)
            for page_num, page in enumerate(pdf.pages, 1):
                logger.info(f"OCR page {page_num}/{total}...")
                try:
                    img = page.to_image(resolution=150)
                    buf = _BytesIO()
                    img.original.save(buf, format='PNG')
                    buf.seek(0)
                    text = _ocr_page_to_text(buf.read())
                    if text:
                        full_text += text + "\n"
                        logger.info(f"  Page {page_num}: got {len(text)} chars")
                    else:
                        logger.warning(f"  Page {page_num}: no text returned")
                except Exception as e:
                    logger.error(f"  Page {page_num} render/OCR error: {e}")
                    continue
    except Exception as e:
        logger.error(f"_ocr_pdf_to_text failed: {e}")

    logger.info(f"OCR complete. Total chars: {len(full_text)}")
    return full_text


def _extract_attendance_ocr(pdf_bytes):
    """
    OCR fallback — renders each page as PNG at 200 dpi, OCRs it with
    Engine 2, then parses with full layout detection.

    Retry logic: if a page yields regs + subjects but ZERO percentages
    (which happens when the PDF renders pct cells too faintly at 150 dpi),
    we retry with Engine 1 at 200 dpi, then Engine 2 at 300 dpi.
    """
    from io import BytesIO as _BytesIO

    students_data    = {}
    last_known_subjs = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total = len(pdf.pages)
            for page_num, page in enumerate(pdf.pages, 1):
                logger.info(f"OCR page {page_num}/{total}...")
                try:
                    img = page.to_image(resolution=200)
                    buf = _BytesIO()
                    img.original.save(buf, format='PNG')
                    img_bytes = buf.getvalue()

                    text = _ocr_page_to_text(img_bytes, engine=2)

                    # ---- Retry when we see regs+subjects but no percentages ----
                    if text:
                        chk = _normalize_ocr_text(text)
                        has_regs  = bool(_REG_RE.search(chk))
                        has_subjs = bool(_SUBJ_RE.search(chk))
                        has_pcts  = bool(_PCT_RE.search(chk))

                        if has_regs and has_subjs and not has_pcts:
                            logger.warning(
                                f"  Page {page_num}: regs+subjs but pcts=0 "
                                f"(Engine2@200dpi) — retrying..."
                            )
                            # Retry 1: Engine 1 @ 200 dpi (same image, different model)
                            text2 = _ocr_page_to_text(img_bytes, engine=1)
                            if _PCT_RE.search(_normalize_ocr_text(text2)):
                                text = text2
                                logger.info(f"  Page {page_num}: Engine1@200dpi recovered pcts")
                            else:
                                # Retry 2: Engine 2 @ 300 dpi (higher resolution)
                                img3 = page.to_image(resolution=300)
                                buf3 = _BytesIO()
                                img3.original.save(buf3, format='PNG')
                                text3 = _ocr_page_to_text(buf3.getvalue(), engine=2)
                                if _PCT_RE.search(_normalize_ocr_text(text3)):
                                    text = text3
                                    logger.info(
                                        f"  Page {page_num}: Engine2@300dpi recovered pcts"
                                    )
                                else:
                                    logger.warning(
                                        f"  Page {page_num}: all retries failed, "
                                        f"proceeding with no pcts"
                                    )

                    if text:
                        logger.info(f"  Page {page_num}: {len(text)} chars")
                        last_known_subjs = _parse_page_text(
                            text, students_data, last_known_subjs
                        )
                    else:
                        logger.warning(f"  Page {page_num}: no text from OCR")
                except Exception as e:
                    logger.error(f"  Page {page_num} error: {e}")
                    continue
    except Exception as e:
        logger.error(f"_extract_attendance_ocr failed: {e}")

    result = list(students_data.values())
    logger.info(f"OCR found {len(result)} students with low attendance")
    return result

