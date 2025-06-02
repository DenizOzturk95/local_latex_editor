import os
import sys
import shutil
import subprocess
import threading
import fitz  # PyMuPDF
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
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

        # For scheduling live‐compile after typing stops:
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

        btn_new_template = ttk.Button(toolbar, text="New from Template…", command=self._on_new_from_template)
        btn_new_template.pack(side=tk.LEFT, padx=4)

        btn_save = ttk.Button(toolbar, text="Save Now", command=self._save_now)
        btn_save.pack(side=tk.LEFT, padx=4)

        btn_compile = ttk.Button(toolbar, text="Compile Now", command=self._compile_now)
        btn_compile.pack(side=tk.LEFT, padx=4)

        # === MAIN PANED WINDOW ===
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
        vsb_tex = ttk.Scrollbar(center_frame, orient=tk.VERTICAL, command=self.tex_text.yview)
        hsb_tex = ttk.Scrollbar(center_frame, orient=tk.HORIZONTAL, command=self.tex_text.xview)
        self.tex_text.configure(yscrollcommand=vsb_tex.set, xscrollcommand=hsb_tex.set)
        vsb_tex.pack(side=tk.RIGHT, fill=tk.Y)
        hsb_tex.pack(side=tk.BOTTOM, fill=tk.X)
        self.tex_text.pack(fill=tk.BOTH, expand=True)
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
    # === TEMPLATE LOADING ===
    # -------------------------
    def _on_new_from_template(self):
        """
        Prompt user to choose a .tex template from ./templates directory,
        copy it to the working directory (as main.tex or original name),
        then load into the editor, build outline, and compile.
        """
        templates_dir = os.path.join(os.getcwd(), "templates")
        if not os.path.isdir(templates_dir):
            messagebox.showerror("Templates Not Found", f"No 'templates' directory found at:\n{templates_dir}")
            return

        # Ask the user to pick a .tex file from ./templates
        chosen = filedialog.askopenfilename(
            title="Select a template",
            initialdir=templates_dir,
            filetypes=[("LaTeX files", "*.tex")],
        )
        if not chosen:
            return

        template_basename = os.path.basename(chosen)
        # Copy template to working directory, naming it "main.tex" (or preserve basename)
        cwd = os.getcwd()
        dest_name = "main.tex"
        dest_path = os.path.join(cwd, dest_name)

        try:
            shutil.copyfile(chosen, dest_path)
        except Exception as e:
            messagebox.showerror("Copy Error", f"Could not copy template:\n{e}")
            return

        self.current_tex_path = dest_path

        # Ensure build/ and backups/ folders exist:
        self.build_dir = os.path.join(cwd, "build")
        self.backup_dir = os.path.join(cwd, "backups")
        os.makedirs(self.build_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)

        # Load template content into editor
        try:
            with open(self.current_tex_path, "r", encoding="utf-8") as f:
                tex_source = f.read()
        except Exception as e:
            messagebox.showerror("Load Error", f"Could not load {dest_name}:\n{e}")
            return

        self.tex_text.delete("1.0", tk.END)
        self.tex_text.insert("1.0", tex_source)
        self.tex_text.edit_modified(False)

        # Build the outline and compile immediately
        self._update_outline()
        self._compile_now()

    # -------------------------
    # === SAVE & COMPILE ===
    # -------------------------
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
            shutil.copyfile(self.current_tex_path, temp_tex)
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
        except FileNotFoundError:
            messagebox.showerror("LaTeX Compile Error", "pdflatex executable not found on PATH.")
            return
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

            # === FIX: use BytesIO to wrap raw PNG bytes so PIL can open it ===
            from io import BytesIO
            pil_img = Image.open(BytesIO(img_data))

            tk_img = ImageTk.PhotoImage(pil_img)
        except Exception as e:
            messagebox.showerror("Render Error", f"Failed to render PDF:\n{e}")
            return

        # Display it on the canvas:
        self.pdf_canvas.delete("all")
        self.pdf_canvas.configure(scrollregion=(0, 0, pil_img.width, pil_img.height))
        self.pdf_canvas.create_image(0, 0, anchor="nw", image=tk_img)
        self._img_ref = tk_img  # keep a reference so it doesn't get GC’d


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
        Scan the editor’s text for \chapter, \section, \subsection, \subsubsection (allowing leading whitespace),
        and rebuild the Treeview accordingly.  Clicking on an item will jump the editor to that line.
        """
        text = self.tex_text.get("1.0", tk.END)
        lines = text.splitlines()

        # 1) Clear any existing items in the outline tree
        for iid in self.outline_tree.get_children():
            self.outline_tree.delete(iid)

        # 2) Compile a regex that catches chapter/section/subsection/subsubsection
        #    ^\s*        → allow any leading spaces/tabs
        #    \\(chapter|section|subsection|subsubsection)\*?  → the command name (optionally starred)
        #    \{(.*?)\}   → capture the title itself (lazy, so it stops at the first closing brace)
        pattern = re.compile(r"^\s*\\(chapter|section|subsection|subsubsection)\*?\{(.*?)\}")

        # parent_stack[depth] will hold the most‐recent Treeview item at that depth
        # We’ll assign:
        #   depth=1 → \chapter
        #   depth=2 → \section
        #   depth=3 → \subsection
        #   depth=4 → \subsubsection
        parent_stack = {0: ""}

        for lineno, line in enumerate(lines, start=1):
            m = pattern.match(line)
            if not m:
                continue

            cmd_name = m.group(1)   # "chapter" or "section" or "subsection" or "subsubsection"
            title    = m.group(2)   # the text inside the braces, e.g. "Introduction"

            # Determine depth from the command name:
            if cmd_name == "chapter":
                depth = 1
            elif cmd_name == "section":
                depth = 2
            elif cmd_name == "subsection":
                depth = 3
            else:  # "subsubsection"
                depth = 4

            # Build a unique item ID (so multiple sections at the same level don't collide):
            iid = f"outline_{lineno}"  

            # Parent is the most‐recent item with depth − 1.
            parent = parent_stack.get(depth - 1, "")

            # Insert into the tree.  The “text” shown in the tree is the section heading.
            # We also store the line number in the hidden “lineno” column via values=(lineno,).
            self.outline_tree.insert(parent, "end", iid,
                                      text=title,
                                      values=(lineno,))

            # Remember that this item is now the latest for its own depth
            parent_stack[depth] = iid


    def _on_outline_click(self, event=None):
        """When the user clicks a node in the outline, scroll the editor to that line."""
        sel = self.outline_tree.selection()
        if not sel:
            return
        iid = sel[0]
        lineno = self.outline_tree.set(iid, "lineno")
        if lineno:
            try:
                target_index = f"{lineno}.0"
                self.tex_text.see(target_index)
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
