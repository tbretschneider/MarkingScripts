#!/usr/bin/env python3
"""
new_course.py
Create a new course folder inside the chosen term folder (like MT25).
Creates:
 - a directory <term>/<course_name>/
 - course_info.json with keys full_name, abbreviation, onedrive_remote
 - OnedriveFolder/  (empty, for rclone sync target structure)
 - studentlist.csv with header Name,Email (empty rows)
"""

import argparse
from pathlib import Path
import json
import csv
import re
import sys

TERM_RE = re.compile(r'^(MT|HT|TT)\d{2}$')

def choose_term(base_dir: Path):
    terms = [d for d in base_dir.iterdir() if d.is_dir() and TERM_RE.match(d.name)]
    print("Available terms:")
    for i, t in enumerate(terms, 1):
        print(f"{i}) {t.name}")
    print("Or type a new term code (like MT25):")
    choice = input("Choose term number or new term code: ").strip()
    if choice.isdigit():
        idx = int(choice)-1
        if 0 <= idx < len(terms):
            return terms[idx], choice
    if TERM_RE.match(choice):
        term_dir = base_dir / choice
        term_dir.mkdir(parents=True, exist_ok=True)
        return term_dir, choice
    print("Invalid term code.")
    sys.exit(1)

def sanitize_folder_name(name: str):
    # make a safe folder name
    return re.sub(r'[\/\\\*\:\?"<>\|]', '_', name).strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--course', help='(optional) path to existing course (not used here)')
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent
    print("Creating a new course.")
    term_dir, term_choice = choose_term(base_dir)

    course_folder_name = input("Course folder name (short, used for filesystem): ").strip()
    if not course_folder_name:
        print("Course folder name required.")
        sys.exit(1)
    course_folder_name = sanitize_folder_name(course_folder_name)
    course_dir = term_dir / course_folder_name
    if course_dir.exists():
        print(f"Course directory {course_dir} already exists. Aborting.")
        sys.exit(1)
    full_name = input("Course full name (displayed name): ").strip()
    abbreviation = input("Course abbreviation (short label, e.g. M3): ").strip()
    onedrive_remote = input("Remote location template (use {name} token for student folder), e.g. 'remote:Courses/{name}': ").strip()
    if '{name}' not in onedrive_remote:
        print("Note: you did not include '{name}' token in the remote path. That's okay but recommended.")

    # create structure
    course_dir.mkdir(parents=True, exist_ok=True)
    (course_dir / 'OnedriveFolder').mkdir(exist_ok=True)
    # studentlist.csv
    student_csv = course_dir / 'studentlist.csv'
    with student_csv.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Name', 'Email'])

    # course_info.json
    info = {
        'termyear': term_choice,
        'full_name': full_name or course_folder_name,
        'abbreviation': abbreviation or course_folder_name,
        'onedrive_remote': onedrive_remote
    }
    with (course_dir / 'course_info.json').open('w', encoding='utf-8') as f:
        json.dump(info, f, indent=2)

    print(f"Created course at {course_dir}")
    print("Structure:")
    print(" - OnedriveFolder/")
    print(" - studentlist.csv")
    print(" - course_info.json")
    print("Done. Exiting.")

if __name__ == '__main__':
    main()

