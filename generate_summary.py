#!/usr/bin/env python3
"""
generate_report

Create a LaTeX summary file from the latest gradesN.csv in a course directory.

- Detects a variable number of question columns (Q1, Q2, Question 3, q10, etc.)
  and includes them in the Grades table in numeric order.
- Uses map_overall_to_symbols() to convert Overall grades 1..9 to LaTeX symbols.
- Writes: Summary_<CourseAbbr>_<assignmentnumber>.tex to course/Home/ (or course/).
Usage:
  ./generate_report --course /path/to/course_dir
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
    if overall_is_raw:
        return "$%s$" % overall_latex
    return latex_escape(raw_val)


# ---------------- main ----------------

def main():
    parser = argparse.ArgumentParser(description="Generate a LaTeX summary file from the latest gradesN.csv (variable # of questions supported)")
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
        sys.exit(1)

    m = re.match(r'^grades(\d+)\.csv$', grades_csv.name, re.IGNORECASE)
    assignment_num = m.group(1) if m else "?"
    print(f"Using grades file: {grades_csv.name} (assignment {assignment_num})")

    # read course_info.json for abbreviation
    course_info = {}
    ci_path = course_dir / 'course_info.json'
    if ci_path.exists():
        try:
            course_info = json.loads(ci_path.read_text(encoding='utf-8'))
        except Exception:
            course_info = {}

    course_abbr = choose_json_field(course_info, 'course_abbr', 'abbr', 'short_name', 'code', 'shortName')
    course_full = choose_json_field(course_info, 'full_name')
    if not course_abbr:
        course_abbr = re.sub(r'[^A-Za-z0-9]+', '', course_dir.name) or "course"

    home_dir = course_dir / 'Home'
    out_dir = home_dir if home_dir.exists() and home_dir.is_dir() else course_dir
    out_name = f"Summary_{course_abbr}_{assignment_num}.tex"
    out_path = out_dir / out_name

    # Read CSV
    with grades_csv.open('r', newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        name_col = choose_column(fieldnames, 'Name', 'Student', 'Full Name')
        #submission_col = choose_column(fieldnames, 'SubmissionTime', 'Submission Time', 'Submitted')
        overall_col = choose_column(fieldnames, 'Overall', 'Overall grade', 'Grade')
        feedback_col = choose_column(fieldnames, 'Feedback', 'Comments', 'Comment')

        question_columns = detect_question_columns(fieldnames)

        if name_col is None:
            print("Error: Could not find a Name column in CSV.")
            sys.exit(1)

        rows = [row for row in reader]

    # Build LaTeX using placeholders to avoid %-format issues
    title = f"{course_full} Feedback Summary"
    generated_str = f"{assignment_num}"

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
{\large \textit{Problem Sheet __DATE__}}
\end{center}

\section*{Overall comments}
% intentionally left blank

\section*{Grades}
__TABLE__
\section*{Feedback given to students}
__FEEDBACK__

\end{document}
""".lstrip()

    # Compose table columns: Name, SubmissionTime(optional), Overall(optional), then question columns
    table_columns = [name_col]
    #if submission_col:
    #    table_columns.append(submission_col)
    if overall_col:
        table_columns.append(overall_col)
    # append detected question columns (only if actually present)
    qcols_present = [q for q in question_columns if q in fieldnames and q not in table_columns]
    table_columns.extend(qcols_present)

    table_body = tex_table_header(table_columns)
    for row in rows:
        cells = []
        for col in table_columns:
            if col == overall_col:
                raw_val = (row.get(overall_col) or "").strip()
                cell = safe_overall_cell(raw_val)
            else:
                cell = safe_overall_cell(row.get(col, ""))
            cells.append(cell)
        table_body += " & ".join(cells) + r" \\" + "\n"
    table_body += tex_table_footer()

    # Student feedback
    fb_section_lines = []
    for row in rows:
        name = (row.get(name_col) or "").strip() or "(no name)"
        fb = (row.get(feedback_col) or "").strip() if feedback_col else ""
        name_tex = latex_escape(name)
        if fb:
            fb_escaped = latex_escape(fb)
            fb_escaped = fb_escaped.replace('\r\n', '\n').replace('\r', '\n')
            paragraphs = [p.strip() for p in fb_escaped.split("\n\n") if p.strip() != ""]
            fb_parts = []
            for p in paragraphs:
                lines = p.split("\n")
                if len(lines) > 1:
                    joined = r"\\ " .join(lines)
                else:
                    joined = p
                fb_parts.append(joined)
            fb_tex = ("\n\n\\par\n\n").join(fb_parts)
        else:
            fb_tex = r"\emph{(no feedback)}"
        fb_section_lines.append(r"\textbf{%s}" % name_tex + "\n\n" + fb_tex + "\n\n\\bigskip\n")
    fb_section = "\n".join(fb_section_lines)

    full_tex = template.replace("__TITLE__", latex_escape(title)).replace("__DATE__", latex_escape(generated_str))
    full_tex = full_tex.replace("__TABLE__", table_body)
    full_tex = full_tex.replace("__FEEDBACK__", fb_section)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_tex, encoding='utf-8')
    print(f"Wrote LaTeX summary to: {out_path}")

if __name__ == "__main__":
    main()

