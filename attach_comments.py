#!/usr/bin/env python3
"""
annotate_cover.py

Create a one-page LaTeX comment page for each student's latest Marked_*.pdf
and append it to the marked PDF using pdflatex + pdftk.

- Title is taken from course_info.json (long title key: long_title / longTitle / title).
- Subtitle is "Problem Sheet {assignment}" where assignment is the latest gradesN.csv number.
- Grade is transformed with map_overall_to_symbols for digits 1-9; otherwise left as original (safely escaped).
- Feedback appears before Grade on the generated page (you asked to swap them).

Requirements:
 - pdflatex in PATH
 - pdftk in PATH

Usage:
  python annotate_cover.py --course /path/to/course
"""
from pathlib import Path
import argparse
import re
import csv
import sys
import tempfile
import shutil
import subprocess
import json
from io import StringIO

# ---------------- utilities ----------------

def map_overall_to_symbols(overall):
    """
    Map numeric overall values 1-9 to LaTeX symbol strings.
    Returns (latex_str, mapped_boolean).
    If mapped_boolean is True, latex_str contains LaTeX commands (e.g. "\\alpha") and
    should NOT be escaped again.
    If mapped_boolean is False, latex_str is the original value as a string (should be escaped).
    """
    mapping = {
        1: r"\alpha +",
        2: r"\alpha",
        3: r"\alpha \beta",
        4: r"\beta\alpha",
        5: r"\beta",
        6: r"\beta\gamma",
        7: r"\gamma\beta",
        8: r"\gamma",
        9: r"\gamma-",
    }

    # if it's an int
    if isinstance(overall, int):
        if overall in mapping:
            return mapping[overall], True
        return str(overall), False

    s = (overall or "").strip()
    if s.isdigit():
        num = int(s)
        if num in mapping:
            return mapping[num], True
    # not a mapped digit
    return str(overall or ""), False


def latex_escape(s: str) -> str:
    return s


def find_latest_grades_file(course_dir: Path) -> Path:
    candidates = []
    for p in course_dir.iterdir():
        if not p.is_file():
            continue
        m = re.match(r'^grades(\d+)\.csv$', p.name, re.IGNORECASE)
        if m:
            candidates.append((int(m.group(1)), p))
    if not candidates:
        raise FileNotFoundError("No gradesN.csv files found in course directory.")
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def choose_json_field(d: dict, *candidates):
    for c in candidates:
        if c in d:
            return d[c]
    # try lower-case keys
    lower = {k.lower(): k for k in d.keys()}
    for c in candidates:
        lc = c.lower()
        if lc in lower:
            return d[lower[lc]]
    return None


def read_course_info(course_dir: Path) -> dict:
    p = course_dir / 'course_info.json'
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}


def choose_column(fieldnames, *possible_names):
    """Return the first matching column name from fieldnames, case-insensitive."""
    if not fieldnames:
        return None
    lowered = {fn.lower(): fn for fn in fieldnames}
    for cand in possible_names:
        cand_low = cand.lower()
        if cand_low in lowered:
            return lowered[cand_low]
    # substring match
    for cand in possible_names:
        cand_low = cand.lower()
        for fn in fieldnames:
            if cand_low in fn.lower():
                return fn
    return None


def read_grades_map(grades_csv_path: Path):
    mapping = {}
    if not grades_csv_path.exists():
        raise FileNotFoundError(f"{grades_csv_path} does not exist")

    with grades_csv_path.open('r', newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        name_col = choose_column(fieldnames, 'Name', 'Student', 'Full Name')
        overall_col = choose_column(fieldnames, 'Overall', 'Overall grade', 'Grade')
        feedback_col = choose_column(fieldnames, 'Feedback', 'Comments', 'Comment')

        if name_col is None:
            raise ValueError("Could not find a Name column in grades CSV.")
        if overall_col is None:
            print("Warning: Could not find an Overall/Grade column in CSV; 'Overall' will be blank.")
        if feedback_col is None:
            print("Warning: Could not find a Feedback/Comments column in CSV; 'Feedback' will be blank.")

        for row in reader:
            raw_name = (row.get(name_col) or '').strip()
            if not raw_name:
                continue
            mapping[raw_name] = {
                'Overall': (row.get(overall_col) or '').strip() if overall_col else '',
                'Feedback': (row.get(feedback_col) or '').strip() if feedback_col else '',
            }
    return mapping


def sanitize_folder_name(name: str) -> str:
    if name is None:
        return ''
    return re.sub(r'[^A-Za-z0-9]', '', name).lower()


def find_student_marked_pdf(onedrive_folder: Path, student_folder_name: str):
    """
    Find newest Marked_*.pdf in OnedriveFolder/<student_folder_name>/Marked
    or fallback by sanitized folder-name matching.
    """
    candidate_dir = onedrive_folder / student_folder_name / 'Marked'
    if candidate_dir.exists() and candidate_dir.is_dir():
        pdfs = sorted(candidate_dir.glob('Marked_*.pdf'), key=lambda p: p.stat().st_mtime)
        if pdfs:
            return pdfs[-1]

    # fallback: sanitized match
    target_key = sanitize_folder_name(student_folder_name)
    if not onedrive_folder.exists():
        return None
    for folder in onedrive_folder.iterdir():
        if not folder.is_dir():
            continue
        if sanitize_folder_name(folder.name) == target_key:
            md = folder / 'Marked'
            if md.exists() and md.is_dir():
                pdfs = sorted(md.glob('Marked_*.pdf'), key=lambda p: p.stat().st_mtime)
                if pdfs:
                    return pdfs[-1]
    return None


def make_latex_document(title: str, subtitle: str, feedback: str, overall_latex: str, overall_is_raw: bool) -> str:
    """
    Build a minimal LaTeX document with:
      - Title (large)
      - Subtitle (Problem Sheet N)
      - Feedback (first)
      - Grade (second) using overall_latex. If overall_is_raw is True the grade string
        is considered LaTeX (already containing backslashes) and is inserted raw; otherwise
        it's escaped.
    """
    # escape title & subtitle and feedback, but do NOT escape overall if it's raw LaTeX
    title_e = latex_escape(title or '')
    subtitle_e = latex_escape(subtitle or '')
    feedback_lines = (feedback or '').splitlines()
    # escape feedback content
    feedback_e = '\\\\\n'.join(latex_escape(line) for line in feedback_lines) if feedback_lines else ''
    if overall_is_raw:
        overall_part = overall_latex
    else:
        overall_part = latex_escape(overall_latex or '')

    doc = r"""\documentclass[12pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{geometry}
\usepackage{microtype}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsfonts}
\geometry{margin=1in}
\pagestyle{empty}
\begin{document}
\centering
{\LARGE \textbf{%s}}

\vspace{0.8em}

{\large \textit{%s}}

\vspace{1.2em}
\raggedright

\textbf{Feedback:}

%s

\vspace{1.0em}

\textbf{Grade:} \ \ $%s$

\end{document}
""" % (title_e, subtitle_e, feedback_e if feedback_e else r"(no feedback)", overall_part if overall_part else r"(no grade)")

    return doc


def run_pdflatex(latex_str: str, out_dir: Path, basename: str = "comment") -> Path:
    tex_path = out_dir / f"{basename}.tex"
    pdf_path = out_dir / f"{basename}.pdf"
    with tex_path.open('w', encoding='utf-8') as fh:
        fh.write(latex_str)

    cmd = ['pdflatex', '-interaction=nonstopmode', '-halt-on-error', tex_path.name]
    proc = subprocess.run(cmd, cwd=str(out_dir), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"pdflatex failed (rc={proc.returncode}). stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    if not pdf_path.exists():
        raise RuntimeError("pdflatex finished but PDF not created.")
    return pdf_path


def pdftk_concat(original_pdf: Path, comment_pdf: Path, out_pdf: Path) -> None:
    cmd = ['pdftk', str(comment_pdf), str(original_pdf), 'cat', 'output', str(out_pdf)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"pdftk failed (rc={proc.returncode}). stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")


# ---------------- main ----------------

def main():
    parser = argparse.ArgumentParser(description="Append a LaTeX-generated comment page to students' marked PDFs using pdflatex + pdftk")
    parser.add_argument('--course', required=True, help='Path to course folder')
    args = parser.parse_args()

    course_dir = Path(args.course).expanduser().resolve()
    if not course_dir.exists():
        print("Course directory does not exist:", course_dir)
        sys.exit(2)

    # find latest grades file and assignment number
    try:
        grades_csv = find_latest_grades_file(course_dir)
    except FileNotFoundError:
        print("No gradesN.csv files found in course directory. Exiting.")
        sys.exit(0)

    # determine assignment number from filename
    m = re.match(r'^grades(\d+)\.csv$', grades_csv.name, re.IGNORECASE)
    assignment_num = m.group(1) if m else "?"
    print("Using grades file:", grades_csv.name, "-> assignment", assignment_num)

    # read course_info.json title
    course_info = read_course_info(course_dir)
    long_title = choose_json_field(course_info, 'full_name', 'longTitle', 'title') or ''
    subtitle = f"Problem Sheet {assignment_num}"

    # read grades mapping
    grades_map = read_grades_map(grades_csv)

    onedrive_folder = course_dir / 'OnedriveFolder'
    if not onedrive_folder.exists():
        print("OnedriveFolder not found under course directory:", onedrive_folder)
        sys.exit(0)

    # check required programs
    for prog in ('pdflatex', 'pdftk'):
        if shutil.which(prog) is None:
            print(f"Required program '{prog}' not found in PATH. Please install it.")
            sys.exit(3)

    processed = 0
    skipped_no_pdf = 0
    skipped_no_grade = 0
    errors = 0

    for student_folder in sorted(onedrive_folder.iterdir()):
        if not student_folder.is_dir():
            continue
        student_name = student_folder.name

        # locate grade record: exact match or sanitized match
        grade_record = grades_map.get(student_name)
        if not grade_record:
            s_key = sanitize_folder_name(student_name)
            for csv_name, rec in grades_map.items():
                if sanitize_folder_name(csv_name) == s_key:
                    grade_record = rec
                    break

        marked_pdf = find_student_marked_pdf(onedrive_folder, student_name)
        if not marked_pdf:
            print(f"[SKIP] No Marked_*.pdf for student folder '{student_name}'")
            skipped_no_pdf += 1
            continue

        if not grade_record:
            print(f"[SKIP] No grade/feedback entry for '{student_name}' (found PDF: {marked_pdf.name})")
            skipped_no_grade += 1
            continue

        overall_raw = grade_record.get('Overall', '')
        feedback_raw = grade_record.get('Feedback', '')

        # map overall to latex symbols if appropriate
        overall_latex, overall_is_raw = map_overall_to_symbols(overall_raw)

        print(f"[OK] {student_name}: generating comment (Grade: {overall_raw}) for '{marked_pdf.name}'")

        try:
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                latex_doc = make_latex_document(long_title, subtitle, feedback_raw, overall_latex, overall_is_raw)
                comment_pdf = run_pdflatex(latex_doc, td_path, basename='comment')
                # concat into a temporary file then replace original
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmpout:
                    tmpout_path = Path(tmpout.name)
                pdftk_concat(marked_pdf, comment_pdf, tmpout_path)
                shutil.move(str(tmpout_path), str(marked_pdf))
            processed += 1
        except Exception as e:
            errors += 1
            print(f"[ERROR] Failed for '{student_name}' ({marked_pdf}): {e}")

    print(f"Done. processed={processed}, skipped_no_pdf={skipped_no_pdf}, skipped_no_grade={skipped_no_grade}, errors={errors}")


if __name__ == '__main__':
    main()

