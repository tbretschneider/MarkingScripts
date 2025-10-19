#!/usr/bin/env python3
"""
course_manager.py
Main CLI to list courses (found one directory up in term folders MT.., HT.., TT..)
and to dispatch to the other scripts.
"""

import json
import subprocess
import sys
from pathlib import Path
import re

BASE = Path(__file__).resolve().parent.parent  # "one directory up" from script folder
TERM_RE = re.compile(r'^(MT|HT|TT)\d{2}$')

def find_term_dirs(base_dir: Path):
    if not base_dir.exists():
        return []
    return [p for p in base_dir.iterdir() if p.is_dir() and TERM_RE.match(p.name)]

def find_courses(term_dir: Path):
    return [p for p in term_dir.iterdir() if p.is_dir()]

def load_course_info(course_dir: Path):
    info_path = course_dir / 'course_info.json'
    if not info_path.exists():
        return None
    try:
        with info_path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def gather_all_courses(base_dir: Path):
    out = []
    for t in find_term_dirs(base_dir):
        for c in find_courses(t):
            info = load_course_info(c)
            if info:
                out.append((t.name, c, info))
    return out

def print_menu(courses):
    print("Available courses:")
    for i, (term, cpath, info) in enumerate(courses, start=1):
        abbrev = info.get('abbreviation', 'UNK')
        full = info.get('full_name', cpath.name)
        print(f"{i}) {abbrev}: {full}  ({term}/{cpath.name})")
    print()
    print("C) Create a new course")
    print("Q) Quit")

def run_script(script_name, course_path=None):
    cmd = [sys.executable, str(Path(__file__).parent / script_name)]
    if course_path:
        cmd += ['--course', str(course_path)]
    subprocess.run(cmd)

def existing_course_menu(selected_course):
    print()
    print(f"Selected course: {selected_course.name}")
    print("Options:")
    print("1) Sync new assignment (download_new_assignment.py)")
    print("2) Mark new assignment (mark.py)")
    print("3) Attach comments to marked PDFs (attach_comments.py)")
    print("4) Upload marked work (upload_latest_assignment.py)")
    print("B) Back")
    choice = input("Choose: ").strip().lower()
    if choice == '1':
        run_script('download_new_assignment.py', selected_course)
    elif choice == '2':
        run_script('mark.py', selected_course)
    elif choice == '3':
        run_script('attach_comments.py', selected_course)
    elif choice == '4':
        run_script('upload_latest_assignment.py', selected_course)
    else:
        return

def main():
    base_dir = BASE
    while True:
        courses = gather_all_courses(base_dir)
        print_menu(courses)
        choice = input("Choose course number, C, or Q: ").strip()
        if choice.lower() == 'q':
            print("Bye.")
            return
        if choice.lower() == 'c':
            run_script('new_course.py')
            # After creation, re-scan
            continue
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(courses):
                _, course_path, _ = courses[idx]
                existing_course_menu(course_path)
            else:
                print("Invalid number.")
        else:
            print("Invalid choice.")

if __name__ == '__main__':
    main()

