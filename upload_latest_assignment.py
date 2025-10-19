#!/usr/bin/env python3
"""
sync_students.py

Sync each student's local folder under OnedriveFolder/<student> with the student's remote
specified in course_info.json using rclone sync -i (interactive).

rclone sync usage: rclone sync <src> <dst>

This script supports two directions:
 - push (default): local -> remote  (rclone sync <local> <remote>)
 - pull            : remote -> local  (rclone sync <remote> <local>)

Expect course_info.json to contain an entry like:
{
  "onedrive_remote": "onedrive:Students/{name}"
}
If no {name} is present the student folder name will be appended.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import shutil

def load_course_info(course_dir: Path) -> dict:
    p = course_dir / 'course_info.json'
    if not p.exists():
        print(f"Warning: course_info.json not found at {p}; no remote template available.")
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"Error reading course_info.json: {e}")
        return {}

def build_remote_path(template: str, student_name: str) -> str:
    """
    Build remote path from template and student name.
    If template contains {name} it will be replaced; otherwise student_name is appended.
    """
    if not template:
        return ''
    if '{name}' in template:
        return template.replace('{name}', student_name)
    if template.endswith(':') or template.endswith('/'):
        return template + student_name
    return template + '/' + student_name

def run_rclone_sync_interactive(src: str, dst: str) -> bool:
    """
    Run `rclone sync -i <src> <dst>` and return True if rclone exits with code 0.
    Prints command and asks for confirmation before running.
    """
    cmd = ['rclone', 'sync', '-i', src, dst]
    print("About to run:")
    print("  " + " ".join(cmd))
    try:
        proc = subprocess.run(cmd)
        if proc.returncode == 0:
            print("rclone sync completed successfully.")
            return True
        else:
            print(f"rclone sync returned exit code {proc.returncode}.")
            return False
    except FileNotFoundError:
        print("Error: rclone not found in PATH. Please install rclone and ensure it's available in PATH.")
        return False
    except Exception as e:
        print(f"Unexpected error running rclone: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Sync each student's OnedriveFolder/<student> with remote (interactive rclone sync -i).")
    parser.add_argument('--course', required=True, help='Path to course folder')
    parser.add_argument('--remote-template', help='Override course_info.json onedrive_remote template (optional)')
    parser.add_argument('--direction', choices=('push','pull'), default='push',
                        help="Direction of sync: 'push' = local -> remote (default); 'pull' = remote -> local")
    args = parser.parse_args()

    course_dir = Path(args.course).expanduser().resolve()
    if not course_dir.exists() or not course_dir.is_dir():
        print("Course directory does not exist or is not a directory:", course_dir)
        sys.exit(2)

    if shutil.which('rclone') is None:
        print("rclone not found in PATH. Please install rclone.")
        sys.exit(3)

    course_info = load_course_info(course_dir)
    remote_template = args.remote_template or course_info.get('onedrive_remote', '').strip()

    if not remote_template:
        print("No remote template provided (course_info.json missing 'onedrive_remote' or --remote-template not given).")
        print("You can provide a template such as 'onedrive:Students/{name}' where {name} is replaced by the student's folder name.")
        have_template = False
    else:
        have_template = True

    onedrive_folder = course_dir / 'OnedriveFolder'
    if not onedrive_folder.exists() or not onedrive_folder.is_dir():
        print("OnedriveFolder not found under course directory:", onedrive_folder)
        sys.exit(0)

    direction = args.direction  # 'push' or 'pull'
    print(f"Sync direction: {direction} (push=local->remote, pull=remote->local)")

    processed = 0
    skipped = 0
    failed = 0

    for student_folder in sorted(onedrive_folder.iterdir()):
        if not student_folder.is_dir():
            continue
        student_name = student_folder.name
        print("\n=== Student:", student_name, "===")

        if have_template:
            remote_path = build_remote_path(remote_template, student_name)
        else:
            remote_path = input(f"Enter rclone remote path for student '{student_name}' (or leave blank to skip): ").strip()
            if not remote_path:
                print("No remote provided for this student; skipping.")
                skipped += 1
                continue

        # Basic sanity check
        if ':' not in remote_path and not remote_path.startswith('/'):
            print("Warning: remote path does not contain a colon (e.g. 'remote:'), is that intentional?")
            q = input("Continue with this remote? (y/N): ").strip().lower()
            if q != 'y':
                print("Skipping this student.")
                skipped += 1
                continue

        # Determine src/dst based on direction
        if direction == 'push':
            src = str(student_folder)        # local -> remote
            dst = remote_path
        else:  # pull
            src = remote_path               # remote -> local
            dst = str(student_folder)

        ok = run_rclone_sync_interactive(src, dst)
        if ok:
            processed += 1
        else:
            # ask whether user skipped or it failed
            resp = input("Was this skipped intentionally (s) or did it fail (f)? [s/f] (default s): ").strip().lower()
            if resp == 'f':
                failed += 1
            else:
                skipped += 1

    print("\nSummary:")
    print(f"  processed (synced): {processed}")
    print(f"  skipped: {skipped}")
    print(f"  failed: {failed}")
    print("Done.")

if __name__ == '__main__':
    main()

