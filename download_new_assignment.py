#!/usr/bin/env python3
"""
Download new assignment via rclone from students' remotes.
Usage: python download_new_assignment.py -c <course_path>
"""
import csv
import json
import subprocess
from pathlib import Path
import re
import sys
import argparse
from datetime import datetime
from typing import List, Dict, Optional

def parse_args():
    parser = argparse.ArgumentParser(
        description="Download and prepare a new assignment for a course."
    )
    parser.add_argument(
        "-c", "--course",
        required=True,
        type=str,
        help="Path to the course directory (e.g. ../MT25/M3)"
    )
    return parser.parse_args()

def sanitize_name(name: str):
    return re.sub(r"[^A-Za-z0-9_\-]", '_', name.replace(' ', '_'))

def list_grades_files(course_dir: Path):
    return sorted(course_dir.glob('grades*.csv'))

def read_students(course_dir: Path):
    st = course_dir / 'studentlist.csv'
    students = []
    if st.exists():
        with st.open() as f:
            reader = csv.DictReader(f)
            for r in reader:
                if r.get('Name'):
                    students.append(r['Name'])
    return students

def rclone_lsd(remote_path: str) -> List[str]:
    # returns list of lines from rclone lsd
    cmd = ['rclone', 'lsd', remote_path]
    print('Running:', ' '.join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print('rclone lsd error:', res.stderr)
        return []
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]

def _parse_iso_modtime(s: str) -> Optional[datetime]:
    # rclone lsjson ModTime is ISO8601 e.g. "2024-10-01T12:34:56Z" or with offset
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        return datetime.fromisoformat(s)
    except Exception:
        return None

def rclone_lsjson(remote_path: str) -> List[Dict]:
    """
    Run `rclone lsjson` on remote_path and return a list of dicts (parsed JSON).
    Each dict typically contains fields like Name, Path, Size, MimeType, ModTime, IsDir, etc.
    """
    cmd = ['rclone', 'lsjson', remote_path]
    print('Running:', ' '.join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print('rclone lsjson error:', res.stderr)
        return []
    try:
        data = json.loads(res.stdout)
        if not isinstance(data, list):
            print('Unexpected lsjson output (not a list).')
            return []
        return data
    except json.JSONDecodeError as e:
        print('Failed to parse lsjson output as JSON:', e)
        return []

def pick_latest_file_from_lsjson(entries: List[Dict]) -> Optional[Dict]:
    """
    From lsjson entries, pick the most recently modified file (not directory).
    Returns the dict entry or None if none found.
    """
    file_entries = [e for e in entries if not e.get('IsDir')]
    if not file_entries:
        return None

    def key_modtime(e):
        mt = e.get('ModTime') or e.get('Time') or ''
        dt = _parse_iso_modtime(mt) if isinstance(mt, str) else None
        return dt or datetime.min

    latest = max(file_entries, key=key_modtime)
    return latest

def rclone_moveto(src, dst):
    cmd = ['rclone', 'moveto', '-i', src, dst]
    res = subprocess.run(cmd)
    return res.returncode == 0

def rclone_sync(src, dst):
    cmd = ['rclone', 'sync', '-i', src, dst]
    res = subprocess.run(cmd)
    return res.returncode == 0

def ensure_student_folders(course_dir: Path, students):
    od = course_dir / 'OnedriveFolder'
    od.mkdir(exist_ok=True)
    for s in students:
        (od / s).mkdir(exist_ok=True)
        (od / s / 'Marked').mkdir(exist_ok=True)

def main():
    args = parse_args()

    # convert to Path and normalise
    course_dir = Path(args.course).expanduser().resolve()

    if not course_dir.exists():
        print(f"Error: course dir missing: {course_dir}", file=sys.stderr)
        sys.exit(2)

    # load course info
    print(f"Using course directory: {course_dir}")
    info_path = course_dir / 'course_info.json'
    if not info_path.exists():
        print(f"Error: missing course_info.json at {info_path}", file=sys.stderr)
        sys.exit(3)

    info = json.loads(info_path.read_text())
    grades = list_grades_files(course_dir)
    if not grades:
        assign_no = 1
        students = read_students(course_dir)
        ensure_student_folders(course_dir, students)
    else:
        last = grades[-1].name
        m = re.search(r'grades(\d+)\.csv', last)
        if m:
            assign_no = int(m.group(1)) + 1
        else:
            assign_no = 1
    print('Assignment number will be', assign_no)
    grades_file = course_dir / f'grades{assign_no}.csv'
    # create header
    header = ['Name','SubmissionTime','Feedback','Overall']
    # dynamic question columns will be appended later
    with grades_file.open('w', newline='') as gf:
        writer = csv.writer(gf)
        writer.writerow(header)

    students = read_students(course_dir)
    remote_template = info.get('onedrive_remote','')

    for s in students:
        remote = remote_template.replace('{name}', s)
        print('\nProcessing student:', s)
        # list remote files as JSON
        entries = rclone_lsjson(remote)
        if not entries:
            print('No files found (or error) for', s)
            continue

        latest_entry = pick_latest_file_from_lsjson(entries)
        if not latest_entry:
            print('No file entries (only directories?) for', s)
            continue

        latest_name = latest_entry.get('Name')
        modtime_raw = latest_entry.get('ModTime') or latest_entry.get('Time') or ''
        modtime = _parse_iso_modtime(modtime_raw)
        print(f"Found latest file: {latest_name} (ModTime: {modtime or 'unknown'})")

        expected_name = f"{sanitize_name(s)}_{info.get('abbreviation')}_{info.get('termyear')}_{assign_no}.pdf"

        #if latest_name != expected_name:
        #    print(f"Student {s}: latest file '{latest_name}' differs from expected '{expected_name}'")
        #    src = f"{remote}/{latest_name}"
        #    dst = f"{remote}/{expected_name}"
        #    moved = rclone_moveto(src, dst)
        #    if moved:
        #        latest_name = expected_name
        #    else:
        #        print('Move failed or was skipped; will attempt to use original filename.')

        # sync remote to local student folder
        local_student_dir = course_dir / 'OnedriveFolder' / s
        local_student_dir.mkdir(parents=True, exist_ok=True)
        src_remote = f"{remote}/"
        dst_local = str(local_student_dir)
        rclone_sync(src_remote,dst_local)
        # Find the latest PDF in the local student folder (by mtime)
        if latest_name != expected_name:
            src_local = local_student_dir / latest_name
            dst_local_path = local_student_dir / expected_name

                # Now rename/move the freshly-synced file to the expected name
            print(f"Renaming local file: {src_local.name} -> {dst_local_path.name}")
            src_local.replace(dst_local_path)  # atomic move/rename

        # record submission time as the ModTime we found (if available) or blank
        submission_time_str = modtime.isoformat() if modtime else ''
        with grades_file.open('a', newline='') as gf:
            writer = csv.writer(gf)
            writer.writerow([s, submission_time_str, '', '', ''])
    print('Done. Grades file:', grades_file)

if __name__ == '__main__':
    main()

