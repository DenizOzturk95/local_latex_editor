import os
import sys
import tempfile
import subprocess
import threading
import requests
import fitz  # PyMuPDF
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import re
from datetime import datetime


class LiveTeXEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Live LaTeX Editor + Preview")
        self.geometry("1200x800")

        # Path where the .tex is stored locally, and build/backup folders:
        self.current_tex_path = None
        self.build_dir = None
        self.backup_dir = None

        # For scheduling live‐compile after typing:
        self._compile_after_id = None
        # For scheduling periodic backups:
        self._backup_after_id = None
        self.backup_interval_ms = 10 * 60 * 1000  # 10 minutes

        # Keep reference to the PhotoImage so it doesn't get GC’d:
        self._img_ref = None

        # Build the UI:
        self._build_ui()

        # Start the backup schedule (even before any file is open):
        self._schedule_backup()

    def _build_ui(self):
        # === TOP TOOLBAR ===
        toolbar = ttk.Frame(self, relief=tk.RIDGE, padding=(4, 2))
        toolbar.pack(fill=tk.X, side=tk.TOP)

        btn_open = ttk.Button(toolbar, text="Open URL…", command=self._on_open_url)
        btn_open.pack(side=tk.LEFT, padx=4)

        btn_save = ttk.Button(toolbar, text="Save Now", command=self._save_now)
        btn_save.pack(side=tk.LEFT, padx=4)

        btn_compile = ttk.Button(toolbar, text="Compile Now", command=self._compile_now)
        btn_compile.pack(side=tk.LEFT, padx=4)

        # === MAIN PANED WINDOW ===
        # Three panes: Outline | Editor | PDF Preview
        main_pane = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        # 1) LEFT PANE: File Outline (Treeview)
        left_frame = ttk.Frame(main_pane, width=200)
        left_frame.pack_propagate(False)
        outline_label = ttk.Label(left_frame, text="File Outline", anchor="center")
        outline_label.pack(fill=tk.X)
        self.outline_tree = ttk.Treeview(left_frame, show="tree")
        vsb_outline = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.outline_tree.yview)
        self.outline_tree.configure(yscrollcommand=vsb_outline.set)
        vsb_outline.pack(side=tk.RIGHT, fill=tk.Y)
        self.outline_tree.pack(fill=tk.BOTH, expand=True)
        self.outline_tree.bind("<<TreeviewSelect>>", self._on_outline_click)

        main_pane.add(left_frame, weight=1)

        # 2) CENTER PANE: LaTeX Source Editor
        center_frame = ttk.Frame(main_pane)
        self.tex_text = tk.Text(center_frame, wrap="none", undo=True)
        # scrollbars for editor
        vsb_tex = ttk.Scrollbar(center_frame, orient=tk.VERTICAL, command=self.tex_text.yview)
        hsb_tex = ttk.Scrollbar(center_frame, orient=tk.HORIZONTAL, command=self.tex_text.xview)
        self.tex_text.configure(yscrollcommand=vsb_tex.set, xscrollcommand=hsb_tex.set)
        vsb_tex.pack(side=tk.RIGHT, fill=tk.Y)
        hsb_tex.pack(side=tk.BOTTOM, fill=tk.X)
        self.tex_text.pack(fill=tk.BOTH, expand=True)
        # Bind key events to schedule a live compile + outline rebuild
        self.tex_text.bind("<KeyRelease>", self._on_text_modified)

        main_pane.add(center_frame, weight=4)

        # 3) RIGHT PANE: PDF Preview Canvas
        right_frame = ttk.Frame(main_pane)
        self.pdf_canvas = tk.Canvas(right_frame, bg="lightgray")
        vsb_pdf = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=self.pdf_canvas.yview)
        hsb_pdf = ttk.Scrollbar(right_frame, orient=tk.HORIZONTAL, command=self.pdf_canvas.xview)
        self.pdf_canvas.configure(yscrollcommand=vsb_pdf.set, xscrollcommand=hsb_pdf.set)
        vsb_pdf.pack(side=tk.RIGHT, fill=tk.Y)
        hsb_pdf.pack(side=tk.BOTTOM, fill=tk.X)
        self.pdf_canvas.pack(fill=tk.BOTH, expand=True)
        main_pane.add(right_frame, weight=5)

    # -------------------------
    # === BUTTON COMMANDS ===
    # -------------------------
    def _on_open_url(self):
        """Ask for a URL to a raw .tex file, fetch it, store as main.tex, and load into the editor."""
        url = simpledialog.askstring("Open LaTeX URL", "Enter URL of the raw .tex file:")
        if not url:
            return

        try:
            resp = requests.get(url)
            resp.raise_for_status()
            tex_source = resp.text
        except Exception as e:
            messagebox.showerror("Fetch Error", f"Could not fetch URL:\n{e}")
            return

        # Derive a local filename (e.g. from URL basename, or fallback to main.tex):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        base = os.path.basename(parsed.path)
        if base.lower().endswith(".tex"):
            local_name = base
        else:
            local_name = "main.tex"

        # Save into the current working directory:
        cwd = os.getcwd()
        self.current_tex_path = os.path.join(cwd, local_name)
        try:
            with open(self.current_tex_path, "w", encoding="utf-8") as f:
                f.write(tex_source)
        except Exception as e:
            messagebox.showerror("File Write Error", f"Could not write {self.current_tex_path}:\n{e}")
            return

        # Ensure build/ and backups/ folders exist:
        self.build_dir = os.path.join(cwd, "build")
        self.backup_dir = os.path.join(cwd, "backups")
        os.makedirs(self.build_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)

        # Load the text into the editor, reset modification flag:
        self.tex_text.delete("1.0", tk.END)
        self.tex_text.insert("1.0", tex_source)
        self.tex_text.edit_modified(False)

        # Build the initial outline and compile:
        self._update_outline()
        self._compile_now()

    def _save_now(self):
        """Write the current editor contents immediately to self.current_tex_path."""
        if not self.current_tex_path:
            messagebox.showinfo("No File", "No .tex file is currently open.")
            return
        try:
            content = self.tex_text.get("1.0", tk.END)
            with open(self.current_tex_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.tex_text.edit_modified(False)
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save to {self.current_tex_path}:\n{e}")
            return
        messagebox.showinfo("Saved", f"Saved to {self.current_tex_path}")

    def _compile_now(self):
        """Force an immediate compile and re-render of the first PDF page."""
        if not self.current_tex_path:
            messagebox.showinfo("No File", "No .tex file is currently open.")
            return

        # Always save before compiling:
        try:
            with open(self.current_tex_path, "w", encoding="utf-8") as f:
                f.write(self.tex_text.get("1.0", tk.END))
            self.tex_text.edit_modified(False)
        except Exception as e:
            messagebox.showerror("Save‐Before‐Compile Error", f"Could not save .tex:\n{e}")
            return

        # Copy the .tex into build/temp.tex, then run pdflatex there:
        temp_tex = os.path.join(self.build_dir, "temp.tex")
        try:
            with open(self.current_tex_path, "r", encoding="utf-8") as src, \
                 open(temp_tex, "w", encoding="utf-8") as dst:
                dst.write(src.read())
        except Exception as e:
            messagebox.showerror("Build Copy Error", f"Could not copy .tex into build/:\n{e}")
            return

        # Run pdflatex (nonstopmode):
        try:
            proc = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "temp.tex"],
                cwd=self.build_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20
            )
        except Exception as e:
            messagebox.showerror("LaTeX Compile Error", f"Failed to run pdflatex:\n{e}")
            return

        if proc.returncode != 0:
            # Read the .log to show the user:
            logtxt = ""
            log_path = os.path.join(self.build_dir, "temp.log")
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as lf:
                    logtxt = lf.read()
            messagebox.showerror(
                "LaTeX Compilation Failed",
                f"pdflatex exited with code {proc.returncode}.\n\nLog output:\n\n{logtxt}"
            )
            return

        # If compilation succeeded, render the first page to a Tkinter image:
        pdf_path = os.path.join(self.build_dir, "temp.pdf")
        if not os.path.exists(pdf_path):
            messagebox.showerror("PDF Missing", "Compiled PDF not found in build/")
            return

        try:
            doc = fitz.open(pdf_path)
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=150)
            img_data = pix.tobytes("png")
            pil_img = Image.open(fitz.open("png", img_data))
            # Convert to a PhotoImage:
            tk_img = ImageTk.PhotoImage(pil_img)
        except Exception as e:
            messagebox.showerror("Render Error", f"Failed to render PDF:\n{e}")
            return

        # Display it on the canvas:
        self.pdf_canvas.delete("all")
        self.pdf_canvas.configure(scrollregion=(0, 0, pil_img.width, pil_img.height))
        self.pdf_canvas.create_image(0, 0, anchor="nw", image=tk_img)
        self._img_ref = tk_img  # keep a reference so it doesn't get garbage‐collected

    # -------------------------
    # === AUTO‐SAVE & LIVE COMPILE ===
    # -------------------------
    def _on_text_modified(self, event=None):
        """
        Called on every KeyRelease. Schedule a live compile + outline update
        2 seconds after the last keypress.
        """
        if self._compile_after_id:
            self.after_cancel(self._compile_after_id)
        self._compile_after_id = self.after(2000, self._live_update)

    def _live_update(self):
        """Actually do a compile + outline refresh after typing stops."""
        self._compile_after_id = None
        self._update_outline()
        self._compile_now()

    # -------------------------
    # === OUTLINE PARSING ===
    # -------------------------
    def _update_outline(self):
        """
        Parse the editor’s text for \section, \subsection, etc., and rebuild the Treeview.
        Clicking on an item will scroll the editor to that line.
        """
        text = self.tex_text.get("1.0", tk.END)
        lines = text.splitlines()

        # Clear the tree:
        for iid in self.outline_tree.get_children():
            self.outline_tree.delete(iid)

        # Regexes for section levels:
        pattern = re.compile(r"^(?P<indent>\\(sub){0,2}section)\*?\{(?P<title>.*?)\}")

        parent_stack = { 0: "" }  # depth → parent IID
        last_iid = None

        for lineno, line in enumerate(lines, start=1):
            m = pattern.match(line)
            if not m:
                continue

            fullcmd = m.group("indent")  # “\section” or “\subsection” or “\subsubsection”
            title = m.group("title")
            if fullcmd.startswith(r"\subsubsection"):
                depth = 3
            elif fullcmd.startswith(r"\subsection"):
                depth = 2
            else:
                depth = 1

            iid = f"outline_{lineno}"
            display_text = f"{title}"
            # Determine parent based on depth:
            parent = parent_stack.get(depth - 1, "")
            self.outline_tree.insert(parent, "end", iid, text=display_text)
            parent_stack[depth] = iid
            last_iid = iid

            # Store the lineno in the item’s “values” so we can jump later:
            self.outline_tree.set(iid, "lineno", str(lineno))

    def _on_outline_click(self, event=None):
        """When the user clicks a node in the outline, scroll the editor to that line."""
        sel = self.outline_tree.selection()
        if not sel:
            return
        iid = sel[0]
        lineno = self.outline_tree.set(iid, "lineno")
        if lineno:
            try:
                # Scroll the text widget so that line is visible:
                target_index = f"{lineno}.0"
                self.tex_text.see(target_index)
                # Also move the insert cursor there:
                self.tex_text.mark_set("insert", target_index)
                self.tex_text.focus()
            except Exception:
                pass

    # -------------------------
    # === PERIODIC BACKUP ===
    # -------------------------
    def _schedule_backup(self):
        """Schedule the next backup in self.backup_interval_ms."""
        if self._backup_after_id:
            self.after_cancel(self._backup_after_id)
        self._backup_after_id = self.after(self.backup_interval_ms, self._do_backup)

    def _do_backup(self):
        """
        Write the current .tex buffer to backups/backup_YYYYMMDD_HHMMSS.tex
        (if a file is open). Then reschedule the next backup.
        """
        if self.current_tex_path:
            try:
                content = self.tex_text.get("1.0", tk.END)
                now = datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = f"backup_{now}.tex"
                fullpath = os.path.join(self.backup_dir, fname)
                with open(fullpath, "w", encoding="utf-8") as f:
                    f.write(content)
                # print(f"[Backup saved to {fullpath}]")  # (optional console log)
            except Exception as e:
                print(f"Backup error: {e}", file=sys.stderr)

        # Schedule next backup in 10 minutes:
        self._schedule_backup()


if __name__ == "__main__":
    # Verify that pdflatex is on PATH; if not, exit with an error message.
    try:
        subprocess.run(["pdflatex", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    except Exception:
        print("Error: pdflatex not found on PATH. Install TeX Live or MiKTeX, and ensure 'pdflatex' is callable.")
        sys.exit(1)

    app = LiveTeXEditor()
    app.mainloop()
