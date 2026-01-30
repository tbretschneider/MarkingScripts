#!/usr/bin/env python3
"""
generate_termly_report.py

Create a LaTeX termly summary file from all gradesN.csv files in a course directory.

- Scans all gradesN.csv files (case-insensitive).
- Detects question columns per file and builds a union of question columns.
- Produces one section per student with:
    * a table of marks (one row per assignment)
    * a collated Feedback section listing feedback per assignment
- Writes: TermlySummary_<CourseAbbr>_<YYYYMMDD>.tex to course/Home/ (or course/).

Usage:
  ./generate_termly_report.py --course /path/to/course_dir
"""
from pathlib import Path
import argparse
import re
import csv
import sys
import json
from datetime import datetime, timezone
import unicodedata

# ---------------- utilities ----------------

def map_overall_to_symbols(overall):
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
    if overall is None:
        return "", False
    if isinstance(overall, int):
        if overall in mapping:
            return mapping[overall], True
        return str(overall), False

    s = (overall or "").strip()
    if s.isdigit():
        num = int(s)
        if num in mapping:
            return mapping[num], True
    return str(overall or ""), False


def latex_escape(s: str) -> str:
    """Escape common LaTeX special chars and normalize unicode to NFKD for safety."""
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    # normalize
    s = unicodedata.normalize("NFKD", s)
    replacements = {
        '\\': r'\textbackslash{}',
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\^{}',
        '<': r'\textless{}',
        '>': r'\textgreater{}',
    }
    out = []
    for ch in s:
        out.append(replacements.get(ch, ch))
    return "".join(out)


def find_all_grades_files(course_dir: Path):
    candidates = []
    for p in course_dir.iterdir():
        if not p.is_file():
            continue
        m = re.match(r'^grades(\d+)\.csv$', p.name, re.IGNORECASE)
        if m:
            candidates.append((int(m.group(1)), p))
    if not candidates:
        raise FileNotFoundError("No gradesN.csv files found in course directory.")
    candidates.sort(key=lambda x: x[0])  # ascending assignment order
    return candidates  # list of (assignment_number:int, Path)


def choose_json_field(d: dict, *candidates):
    for c in candidates:
        if c in d:
            return d[c]
    lower = {k.lower(): k for k in d.keys()}
    for c in candidates:
        lc = c.lower()
        if lc in lower:
            return d[lower[lc]]
    return None


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


def detect_question_columns(fieldnames):
    """
    Detect columns representing questions. Returns list of column names in numeric order
    where possible (Q1, Q2, Question 10, etc.). Columns mentioning 'q'/'question' but
    without a number appear after numbered ones.
    """
    qcols = []
    unordered = []
    for fn in fieldnames:
        low = fn.lower()
        # look for q<number> or question<number>
        m = re.search(r'q\s*[_\-]?\s*(\d+)', low) or re.search(r'question\s*[_\-]?\s*(\d+)', low)
        if not m:
            # fallback: any number in name but ensure q/question present
            m2 = re.search(r'(\d+)', low)
            if m2 and ('q' in low or 'question' in low):
                m = m2
        if m:
            try:
                qnum = int(m.group(1))
                qcols.append((fn, qnum))
                continue
            except Exception:
                pass
        if 'q' in low or 'question' in low:
            unordered.append((fn, None))
    qcols_sorted = sorted(qcols, key=lambda x: x[1])
    qcols_sorted.extend(unordered)
    return [fn for fn, _ in qcols_sorted]


def normalize_name(s: str) -> str:
    """Normalise student name for grouping (lowercase, collapse whitespace)."""
    if s is None:
        return ""
    s = s.strip().lower()
    s = re.sub(r'\s+', ' ', s)
    return s

# ---------------- LaTeX helpers ----------------

def tex_table_header(columns):
    col_defs = " | ".join("l" for _ in columns)
    header = r"\begin{center}" + "\n"
    header += r"\begin{tabular}{ " + col_defs + " }\n"
    header += r"\hline" + "\n"
    header += " & ".join(latex_escape(c) for c in columns) + r" \\" + "\n"
    header += r"\hline" + "\n"
    return header

def tex_table_footer():
    return r"\hline" + "\n" + r"\end{tabular}" + "\n" + r"\end{center}" + "\n"

def safe_overall_cell(raw_val):
    overall_latex, overall_is_raw = map_overall_to_symbols(raw_val)
    if overall_is_raw and overall_latex:
        return "$%s$" % overall_latex
    if raw_val is None:
        return ""
    return latex_escape(raw_val)


# ---------------- main ----------------

def main():
    parser = argparse.ArgumentParser(description="Generate a LaTeX termly summary from all gradesN.csv (variable # of questions supported)")
    parser.add_argument('--course', required=True, help='Path to course folder')
    args = parser.parse_args()

    course_dir = Path(args.course).expanduser().resolve()
    if not course_dir.exists():
        print("Course directory does not exist:", course_dir)
        sys.exit(2)

    # find all grades files
    try:
        grades_candidates = find_all_grades_files(course_dir)  # list of (num, path)
    except FileNotFoundError:
        print("No gradesN.csv files found in course directory. Exiting.")
        sys.exit(1)

    print("Found grade files:", ", ".join(p.name for _, p in grades_candidates))

    # read course_info.json for abbreviation
    course_info = {}
    ci_path = course_dir / 'course_info.json'
    if ci_path.exists():
        try:
            course_info = json.loads(ci_path.read_text(encoding='utf-8'))
        except Exception:
            course_info = {}

    course_abbr = choose_json_field(course_info, 'course_abbr', 'abbr', 'short_name', 'code', 'shortName')
    course_full = choose_json_field(course_info, 'full_name') or course_abbr
    if not course_abbr:
        course_abbr = re.sub(r'[^A-Za-z0-9]+', '', course_dir.name) or "course"

    # We'll collect a global union of question columns across assignments
    global_qcols = []
    assignments = []  # list of dicts: { number:int, path:Path, fieldnames, name_col, id_col, overall_col, feedback_col, qcols, rows }
    for num, path in grades_candidates:
        with path.open('r', newline='', encoding='utf-8') as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            name_col = choose_column(fieldnames, 'Name', 'Student', 'Full Name', 'Student Name')
            id_col = choose_column(fieldnames, 'ID', 'StudentID', 'Student Id', 'Student Number', 'Username')
            overall_col = choose_column(fieldnames, 'Overall', 'Overall grade', 'Grade')
            feedback_col = choose_column(fieldnames, 'Feedback', 'Comments', 'Comment', 'Instructor Comments')
            qcols = detect_question_columns(fieldnames)
            rows = [row for row in reader]
            assignments.append({
                'number': num,
                'path': path,
                'fieldnames': fieldnames,
                'name_col': name_col,
                'id_col': id_col,
                'overall_col': overall_col,
                'feedback_col': feedback_col,
                'qcols': qcols,
                'rows': rows,
            })
            # update global qcols union preserving order (first discovered numeric order; then new ones appended)
            for q in qcols:
                if q not in global_qcols:
                    global_qcols.append(q)

    # Build student index: key -> display name, id, per-assignment data
    # Key priority: ID if present, else normalized name.
    students = {}  # key -> {display_name, id (may be None), assignments: {num:row_dict}}
    for a in assignments:
        num = a['number']
        name_col = a['name_col']
        id_col = a['id_col']
        for row in a['rows']:
            raw_name = (row.get(name_col) or "").strip() if name_col else ""
            raw_id = (row.get(id_col) or "").strip() if id_col else ""
            key = raw_id if raw_id else normalize_name(raw_name)
            if not key:
                # fallback: ensure unique placeholder per file+row index
                key = f"_unknown_{a['path'].name}_{len(students)}"
            if key not in students:
                students[key] = {
                    'display_name': raw_name or raw_id or "(no name)",
                    'id': raw_id or None,
                    'assignments': {},  # num -> {'row':..., 'name_col':..., 'overall_col':..., 'feedback_col':..., 'qcols':...}
                }
            students[key]['assignments'][num] = {
                'row': row,
                'name_col': name_col,
                'overall_col': a['overall_col'],
                'feedback_col': a['feedback_col'],
                'qcols': a['qcols'],
            }

    # Sort students by display name for deterministic output
    sorted_students = sorted(students.items(), key=lambda kv: (kv[1]['display_name'].lower() if kv[1]['display_name'] else ''))

    # Prepare LaTeX template
    today = datetime.now(timezone.utc).date().isoformat()
    out_fn = f"TermlySummary_{course_abbr}_{today}.tex"
    home_dir = course_dir / 'Home'
    out_dir = home_dir if home_dir.exists() and home_dir.is_dir() else course_dir
    out_path = out_dir / out_fn

    template = r"""
\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{geometry}
\usepackage{longtable}
\usepackage{booktabs}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{amsfonts}
\usepackage{array}
\usepackage{microtype}
\geometry{margin=1in}
\begin{document}
\begin{center}
{\LARGE \textbf{__TITLE__}}\\[6pt]
{\large \textit{Termly Report (__DATE__)}}
\end{center}

\tableofcontents
\newpage
__BODY__

\end{document}
""".lstrip()

    body_parts = []
    # For each student: create a section with a table of marks and a feedback subsection
    for key, st in sorted_students:
        student_title = latex_escape(st['display_name'])
        student_id = latex_escape(st['id']) if st['id'] else ""
        header = r"\section*{%s}" % student_title
        if student_id:
            header += f"\\\\\n\\texttt{{{student_id}}}"
        body_parts.append(header + "\n\\addcontentsline{toc}{section}{" + student_title + "}\n")

        # Table columns: Assignment, Overall (if any assignment has overall), then global_qcols (union)
        any_overall = any(( (assign['overall_col'] is not None) for assign in st['assignments'].values() ))
        table_columns = ['PS']
        if any_overall:
            table_columns.append('Overall')
        table_columns.extend(global_qcols)

        table = tex_table_header(table_columns)
        # For consistent ordering, iterate assignments in ascending number order from the found assignments
        assignment_numbers = sorted({a['number'] for a in assignments})
        for num in assignment_numbers:
            cells = []
            cells.append(latex_escape(str(num)))
            if num in st['assignments']:
                ar = st['assignments'][num]
                row = ar['row']
                # Overall
                if any_overall:
                    if ar['overall_col']:
                        raw_val = (row.get(ar['overall_col']) or "").strip()
                        cells.append(safe_overall_cell(raw_val))
                    else:
                        cells.append("")  # no overall column for this assignment
                # question columns
                for q in global_qcols:
                    # Use the column name q if present in that assignment's row; otherwise blank
                    val = ""
                    # prefer exact field if present
                    if q in row:
                        val = (row.get(q) or "").strip()
                    else:
                        # fallback: try case-insensitive match to fieldnames
                        for fn in row.keys():
                            if fn and fn.lower() == q.lower():
                                val = (row.get(fn) or "").strip()
                                break
                    cells.append(safe_overall_cell(val))
            else:
                # Student missing this assignment entirely -> blank cells for the rest
                if any_overall:
                    cells.append("")
                for _ in global_qcols:
                    cells.append("")
            table += " & ".join(cells) + r" \\" + "\n"
        table += tex_table_footer()
        body_parts.append(r"\subsection*{Marks}" + "\n" + table + "\n")

        # Feedback collated
        fb_lines = [r"\subsection*{Feedback}"]
        for num in assignment_numbers:
            if num in st['assignments']:
                ar = st['assignments'][num]
                row = ar['row']
                fb_col = ar['feedback_col']
                fb_raw = (row.get(fb_col) or "").strip() if fb_col else ""
                fb_safe = fb_raw
                if not fb_safe:
                    fb_safe = r"\emph{(no feedback)}"
                fb_lines.append(r"\textbf{Problem Sheet %s} \\ " % latex_escape(str(num)))
                # preserve internal newlines as LaTeX linebreaks
                # split into paragraphs by double newline
                paragraphs = [p.strip() for p in re.split(r'\n\s*\n', fb_safe) if p.strip()]
                for p in paragraphs:
                    # single newlines -> \\ for line breaks
                    p = p.replace('\r\n', '\n').replace('\r', '\n')
                    p = p.replace('\n', r"\\ ")
                    fb_lines.append(p + "\n\n")
            else:
                fb_lines.append(r"\textbf{Problem Sheet %s} \\ " % latex_escape(str(num)) + r"\emph{(no submission)}" + "\n\n")
        body_parts.append("\n".join(fb_lines) + "\n\\bigskip\n\\hrule\n\\bigskip\n")

    full_body = "\n".join(body_parts)
    title = f"{course_full} Termly Feedback Summary"
    full_tex = template.replace("__TITLE__", latex_escape(title)).replace("__DATE__", latex_escape(today))
    full_tex = full_tex.replace("__BODY__", full_body)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_tex, encoding='utf-8')
    print(f"Wrote termly LaTeX summary to: {out_path}")

if __name__ == "__main__":
    main()

