#!/usr/bin/env python3
"""
editgrades.py
GTK3 GUI to edit CSV grades and feedback.

Run with: python3 editgrades.py /path/to/grades.csv
(or use editgrades.sh wrapper)
"""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import csv
import sys
import shutil
import os
from datetime import datetime

# --- Helper functions ------------------------------------------------------

def timestamped_backup(src_path):
    base = os.path.basename(src_path)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = f"/tmp/{base}.{ts}"
    try:
        shutil.copy2(src_path, dest)
    except Exception as e:
        print(f"Warning: failed to copy backup to {dest}: {e}")
        return None
    return dest

# --- Main GUI --------------------------------------------------------------

class GradeEditor(Gtk.Window):
    def __init__(self, csv_path):
        super().__init__(title=f"Edit grades — {os.path.basename(csv_path)}")
        self.set_default_size(1000, 600)
        self.csv_path = csv_path

        # Load CSV
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            self.headers = reader.fieldnames[:]  # preserve order
            self.rows = [row for row in reader]

        # Ensure typical columns exist for convenience
        # We'll make editable columns for: Name, Overall, Q1..Q6 and keep others like SubmissionTime readonly.
        # But all columns are preserved on save.
        self.build_ui()

    def build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(vbox)

        # Notebook for tabs
        notebook = Gtk.Notebook()
        vbox.pack_start(notebook, True, True, 0)

        # --- Tab 1: Grades table ---
        grades_sw = Gtk.ScrolledWindow()
        grades_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        notebook.append_page(grades_sw, Gtk.Label(label="Grades"))

        # Determine columns for table display (Name + SubmissionTime + Overall + Q1..Q6 if present)
        display_cols = []
        if "Name" in self.headers:
            display_cols.append("Name")
        if "SubmissionTime" in self.headers:
            display_cols.append("SubmissionTime")
        # include Overall and Q1..Q6 if present
        for col in ("Overall", "Q1", "Q2", "Q3", "Q4", "Q5", "Q6"):
            if col in self.headers:
                display_cols.append(col)

        # Build ListStore with as many string columns as display_cols
        self.liststore = Gtk.ListStore(*([str] * len(display_cols)))
        # map row -> iter index for syncing later
        self.row_iters = []

        # Fill liststore
        for row in self.rows:
            values = [row.get(c, "") for c in display_cols]
            it = self.liststore.append(values)
            self.row_iters.append(it)

        tree = Gtk.TreeView(model=self.liststore)
        tree.set_grid_lines(Gtk.TreeViewGridLines.BOTH)
        grades_sw.add(tree)

        # Create columns
        for i, colname in enumerate(display_cols):
            renderer = Gtk.CellRendererText()
            # Make most columns editable (except SubmissionTime)
            if colname != "SubmissionTime":
                renderer.set_property("editable", True)
                renderer.connect("edited", self.on_cell_edited, i)
            column = Gtk.TreeViewColumn(colname, renderer, text=i)
            # allow column sizing
            column.set_resizable(True)
            tree.append_column(column)

        # --- Tab 2: Comments editor ---
        comments_sw = Gtk.ScrolledWindow()
        comments_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        notebook.append_page(comments_sw, Gtk.Label(label="Comments"))

        comments_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        comments_box.set_border_width(8)
        comments_sw.add(comments_box)

        # For each student, create a frame with Name label and large TextView for Feedback
        self.feedback_buffers = []  # parallel to self.rows
        for idx, row in enumerate(self.rows):
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.IN)
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            v.set_border_width(6)
            frame.add(v)

            # Name and small metadata line
            name = row.get("Name", f"Student {idx+1}")
            label = Gtk.Label()
            label.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>")
            label.set_halign(Gtk.Align.START)
            v.pack_start(label, False, False, 0)

            # TextView for Feedback
            textview = Gtk.TextView()
            textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            textbuf = textview.get_buffer()
            feedback_text = row.get("Feedback", "")
            textbuf.set_text(feedback_text)
            # make the textviews reasonably tall
            textview.set_size_request(-1, 160)
            # Put into a scrolled window
            tv_sw = Gtk.ScrolledWindow()
            tv_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            tv_sw.add(textview)
            v.pack_start(tv_sw, True, True, 0)

            comments_box.pack_start(frame, False, False, 0)
            self.feedback_buffers.append(textbuf)

        # make sure comments_box expands vertically
        comments_box.pack_end(Gtk.Label(), True, True, 0)

        # --- Bottom action area ---
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        vbox.pack_start(action_box, False, False, 6)
        action_box.set_spacing(6)
        action_box.set_border_width(6)

        self.save_button = Gtk.Button(label="Save")
        self.save_button.connect("clicked", self.on_save_clicked)
        action_box.pack_end(self.save_button, False, False, 0)

        # status label
        self.status = Gtk.Label(label="")
        self.status.set_halign(Gtk.Align.START)
        action_box.pack_start(self.status, True, True, 0)

        self.connect("destroy", Gtk.main_quit)
        self.show_all()

    def on_cell_edited(self, cellrenderer, path, new_text, column_index):
        # Update the ListStore cell that was edited
        try:
            tree_iter = self.liststore.get_iter(path)
            self.liststore.set_value(tree_iter, column_index, new_text)
        except Exception as e:
            print("Edit error:", e)

    def on_save_clicked(self, widget):
        # Update self.rows from both liststore and feedback buffers, then write CSV
        # First, update the subset columns that are in the liststore
        # Determine which display columns we used originally
        display_cols = []
        if "Name" in self.headers:
            display_cols.append("Name")
        if "SubmissionTime" in self.headers:
            display_cols.append("SubmissionTime")
        for col in ("Overall", "Q1", "Q2", "Q3", "Q4", "Q5", "Q6"):
            if col in self.headers:
                display_cols.append(col)

        # Extract liststore rows
        for row_idx, it in enumerate(self.row_iters):
            vals = [self.liststore.get_value(it, i) for i in range(len(display_cols))]
            # write back to self.rows[row_idx]
            for colname, val in zip(display_cols, vals):
                self.rows[row_idx][colname] = val

        # Extract feedbacks
        for i, buf in enumerate(self.feedback_buffers):
            start_iter = buf.get_start_iter()
            end_iter = buf.get_end_iter()
            text = buf.get_text(start_iter, end_iter, True)
            self.rows[i]["Feedback"] = text

        # Write CSV (preserve header order)
        try:
            tmp_output = self.csv_path + ".tmp"
            with open(tmp_output, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.headers, quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()
                for r in self.rows:
                    # ensure all headers present
                    out = {h: r.get(h, "") for h in self.headers}
                    writer.writerow(out)
            # atomic replace
            os.replace(tmp_output, self.csv_path)
            self.status.set_text("Saved successfully.")
            # flash dialog
            dlg = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Saved",
            )
            dlg.format_secondary_text(f"Changes written to {self.csv_path}")
            dlg.run()
            dlg.destroy()
        except Exception as e:
            self.status.set_text("Save failed.")
            dlg = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Save failed",
            )
            dlg.format_secondary_text(str(e))
            dlg.run()
            dlg.destroy()

# --- Entry point -----------------------------------------------------------

def main():
    if len(sys.argv) != 2:
        print("Usage: editgrades.py path/to/grades.csv")
        sys.exit(1)
    csv_path = sys.argv[1]
    if not os.path.isfile(csv_path):
        print("CSV file not found:", csv_path)
        sys.exit(1)

    backup = timestamped_backup(csv_path)
    if backup:
        print(f"Backup created at: {backup}")
    else:
        print("No backup created (see warning).")

    # Start GTK
    win = GradeEditor(csv_path)
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()

