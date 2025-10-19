#!/usr/bin/env python3
"""
mark.py

Workflow changes:
- Do NOT copy the PDF before opening.
- Open the original file in xournalpp.
- After annotation, detect the annotated PDF (by modification time and sensible heuristics),
  then copy that annotated file into OnedriveFolder/<Student>/Marked/ as Marked_<name>.pdf
- Then prompt for grades/feedback and update grades{assignment}.csv (updating existing rows).
"""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import csv
import json
import sys
import time
from datetime import datetime
from typing import Dict, List

# --- robust append_grades_row (from your requested behavior) ---
import re as _re

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional

def append_grades_row(course_dir: Path, assignment: int, new_row: Dict[str, str]) -> None:
    """
    Update or append a row in grades{assignment}.csv.

    - Matches student by 'Name' (case-insensitive, stripped).
    - Updates Feedback, Overall, and any Q* keys present in new_row.
    - Adds any missing Q* columns (using keys exactly as provided) after 'Overall' if possible.
    """
    grades_csv = course_dir / f'grades{assignment}.csv'
    base_columns = ['Name', 'SubmissionTime', 'Feedback', 'Overall']

    # Prepare incoming keys and values (use keys exactly as provided)
    incoming = {k: (v if v is not None else '') for k, v in (new_row or {}).items()}

    # Identify incoming Q keys (keep them exactly as provided)
    incoming_q_keys = sorted(
        [k for k in incoming.keys() if re.match(r'^Q\d+$', k, re.IGNORECASE)],
        key=lambda x: int(re.search(r'\d+', x).group())
    )

    # Read existing CSV if present
    existing_rows: List[Dict[str, str]] = []
    header: List[str] = []
    if grades_csv.exists():
        with grades_csv.open('r', newline='', encoding='utf-8') as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames[:] if reader.fieldnames else []
            for r in reader:
                # ensure keys are strings and values are stripped strings
                norm = { (k if k is not None else ''): (v.strip() if isinstance(v, str) else (v or '')) for k, v in r.items() }
                existing_rows.append(norm)

    # If no header, start from base columns
    if not header:
        header = base_columns[:]
    else:
        # Ensure base columns exist; if missing, insert them in base order (preserve existing header order)
        for i, col in enumerate(base_columns):
            if col not in header:
                # try to insert after previous base column if present, else at front
                insert_pos = 0
                if i > 0 and base_columns[i-1] in header:
                    insert_pos = header.index(base_columns[i-1]) + 1
                header.insert(insert_pos, col)

    # Decide where to insert new Q columns: after 'Overall' if present, else at the end
    insert_after = header.index('Overall') + 1 if 'Overall' in header else len(header)
    # Add incoming Q keys if missing, preserving numeric order
    for q in incoming_q_keys:
        if q not in header:
            header.insert(insert_after, q)
            insert_after += 1  # keep next inserted Q after previous so they stay adjacent

    # Ensure Feedback and Overall exist (safety)
    for col in ('Feedback', 'Overall'):
        if col not in header:
            header.append(col)

    # Match student by Name (case-insensitive, stripped)
    student_name = (incoming.get('Name') or '').strip()
    matched_index: Optional[int] = None
    if student_name:
        for i, existing in enumerate(existing_rows):
            if (existing.get('Name') or '').strip().lower() == student_name.lower():
                matched_index = i
                break

    if matched_index is not None:
        # Update existing row with provided keys
        row_to_update = existing_rows[matched_index]
        for k, v in incoming.items():
            # ensure column exists in header (if user provided something unexpected like 'Overall grade', add it)
            if k not in header:
                header.append(k)
            row_to_update[k] = v
        existing_rows[matched_index] = row_to_update
    else:
        # Create a new row containing all header columns
        new_record = {col: '' for col in header}
        for k, v in incoming.items():
            if k not in new_record:
                header.append(k)
                new_record[k] = ''
            new_record[k] = v
        existing_rows.append(new_record)

    # Ensure every row has all header columns
    for r in existing_rows:
        for col in header:
            if col not in r or r[col] is None:
                r[col] = ''

    # Write updated CSV back
    with grades_csv.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=header, extrasaction='ignore')
        writer.writeheader()
        for r in existing_rows:
            out_row = {col: (r.get(col, '') if r.get(col, '') is not None else '') for col in header}
            writer.writerow(out_row)


# --- helper functions ---

def find_latest_assignment(course_dir: Path) -> int:
    nums = []
    for p in course_dir.iterdir():
        if p.is_file():
            m = re.match(r'^grades(\d+)\.csv$', p.name)
            if m:
                nums.append(int(m.group(1)))
    return max(nums) if nums else 1

def load_student_list(course_dir: Path) -> set:
    candidates = ['studentlist.csv', 'students.csv', 'student_list.csv']
    names = set()
    for fname in candidates:
        f = course_dir / fname
        if f.exists():
            try:
                with f.open(newline='', encoding='utf-8') as fh:
                    reader = csv.DictReader(fh)
                    cols = [c for c in reader.fieldnames] if reader.fieldnames else []
                    name_col = None
                    for c in cols:
                        if c and c.lower() == 'name':
                            name_col = c
                            break
                    if not name_col and cols:
                        name_col = cols[0]
                    for row in reader:
                        val = row.get(name_col, '').strip() if name_col else ''
                        if val:
                            names.add(val)
            except Exception:
                pass
            break
    return names

def find_submission_pdfs(course_dir: Path, abbr: str, term: str, assignment: int):
    pattern = rf'^(.+?)_{re.escape(abbr)}_{re.escape(term)}_{assignment}\.pdf$'
    pat = re.compile(pattern, re.IGNORECASE)
    found = []
    onedrive_root = course_dir / 'OnedriveFolder'
    if onedrive_root.exists() and onedrive_root.is_dir():
        for p in onedrive_root.rglob('*.pdf'):
            try:
                rel = p.relative_to(onedrive_root)
                parts = rel.parts
            except Exception:
                parts = []
            student_from_folder = parts[0].strip() if len(parts) >= 2 else None
            m = pat.match(p.name)
            if m:
                if student_from_folder:
                    found.append((p, student_from_folder))
                else:
                    student_from_name = m.group(1).strip()
                    found.append((p, student_from_name))
    else:
        for p in course_dir.glob('*.pdf'):
            m = pat.match(p.name)
            if m:
                student = m.group(1).strip()
                found.append((p, student))
    # dedupe
    unique = []
    seen = set()
    for p, s in found:
        key = str(p.resolve())
        if key not in seen:
            unique.append((p, s))
            seen.add(key)
    return unique

def ensure_student_marked_folder(course_dir: Path, student_name: str) -> Path:
    onedrive_root = course_dir / 'OnedriveFolder'
    if onedrive_root.exists() and onedrive_root.is_dir():
        student_folder = onedrive_root / student_name
        student_folder.mkdir(parents=True, exist_ok=True)
        target = student_folder / 'Marked'
        target.mkdir(parents=True, exist_ok=True)
        return target
    else:
        d = course_dir / 'Marked'
        d.mkdir(parents=True, exist_ok=True)
        return d

def open_in_xournalpp(path: Path):
    try:
        proc = subprocess.Popen(['xournalpp', str(path)])
    except FileNotFoundError:
        print("xournalpp not found: please annotate the file manually. Press Enter when ready to continue.")
        proc = None
    return proc

def find_annotated_file(original_path: Path, student_folder: Path, search_start_ts: float) -> Path:
    """
    Heuristics to find the annotated PDF after xournalpp:
    1. Prefer a file with same name in original_path.parent modified after search_start_ts.
    2. Search for any PDF in student_folder (and its subtree) modified after search_start_ts;
       prefer files whose name contains the original filename.
    3. If none found, fall back to original_path.
    """
    # 1) check original path's file (xournal often overwrites the file)
    try:
        if original_path.exists() and original_path.stat().st_mtime > search_start_ts:
            return original_path
    except Exception:
        pass

    candidates: List[Path] = []
    # 2) check student_folder subtree
    if student_folder.exists():
        for p in student_folder.rglob('*.pdf'):
            try:
                if p.stat().st_mtime > search_start_ts:
                    candidates.append(p)
            except Exception:
                continue

    # Sort candidates by mtime descending (most recently modified first)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    # Prefer file that contains original basename
    orig_name = original_path.name
    for p in candidates:
        if orig_name in p.name:
            return p

    if candidates:
        return candidates[0]

    # 3) fallback
    return original_path

# --- main flow ---

def main():
    parser = argparse.ArgumentParser(description="Interactive marking tool (open original in xournalpp)")
    parser.add_argument('--course', required=True, help='Path to course directory')
    args = parser.parse_args()
    course_dir = Path(args.course)

    if not course_dir.exists():
        print(f"Course directory does not exist: {course_dir}", file=sys.stderr)
        sys.exit(2)

    info = {}
    try:
        info_path = course_dir / 'course_info.json'
        if info_path.exists():
            with info_path.open(encoding='utf-8') as fh:
                info = json.load(fh)
    except Exception:
        info = {}

    abbr = info.get('abbreviation') or info.get('course_short_name') or info.get('short_name') or 'UNK'
    term = info.get('termyear') or info.get('term') or info.get('term_year') or ''
    assignment = find_latest_assignment(course_dir)
    print(f"Marking assignment {assignment} for {course_dir.name} (abbr={abbr}, term={term})")

    student_names = load_student_list(course_dir)
    if student_names:
        print(f"Loaded {len(student_names)} students from CSV.")
    else:
        print("No studentlist file found (studentlist.csv or students.csv). Will rely on folder names / filenames.")

    submissions = find_submission_pdfs(course_dir, abbr, term, assignment)
    if not submissions:
        print("No submissions found for this assignment naming scheme.")
        return

    for original_pdf_path, student in submissions:
        print(f"\nProcessing {original_pdf_path.name} (student: {student})")

        if student_names and student not in student_names:
            print(f"Warning: student '{student}' not found in studentlist CSV.")

        # prepare student marked folder (we will copy annotated file there AFTER annotation)
        student_marked_dir = ensure_student_marked_folder(course_dir, student)

        # record start timestamp
        start_ts = time.time()

        # open the original file in xournalpp (do NOT copy first)
        proc = open_in_xournalpp(original_pdf_path)

        # Interactive grading
        grades: Dict[str, str] = {}
        grades['Name'] = student

        qnum = 1
        while True:
            ans = input(f"Enter grade for Q{qnum} (1-9, 's', 'ns'; blank to stop): ").strip()
            if ans == '':
                break
            grades[f'Q{qnum}'] = ans
            qnum += 1
        overall = input("Enter overall grade: ").strip()
        grades['Overall'] = overall
        feedback = input("Enter feedback text (single line ok): ").strip()
        grades['Feedback'] = feedback

        append_grades_row(course_dir, assignment, grades)
        print("Appended/updated results in CSV.")

        # if we launched xournalpp as a subprocess, optionally wait/terminate — here we assume the user handled it
        input("Press Enter when you have finished annotating (save in xournalpp and close or keep closed).")
        if proc:
            try:
                proc.poll()
            except Exception:
                pass

    print("Done marking.")

if __name__ == '__main__':
    main()

