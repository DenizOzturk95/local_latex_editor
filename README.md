# local_latex_editor
Sharelatex is no good, Overleaf barely works. Meet local latex editor. The same thing but runs on your device. 

![image](https://github.com/user-attachments/assets/60cb2215-f9a6-4af0-99fa-7d5d3d739dc5)

---

## Table of Contents

1. [Prerequisites](#prerequisites)  
2. [Installation](#installation)  
3. [Running the Editor](#running-the-editor)  
4. [Usage Guide](#usage-guide)  
   - [Opening a `.tex` from a URL](#opening-a-tex-from-a-url)  
   - [Editing & Live-Compile](#editing--live-compile)  
   - [Manual Save / Compile](#manual-save--compile)  
   - [File Outline](#file-outline)  
   - [Backup Files](#backup-files)  
5. [Folder Structure](#folder-structure)  
6. [Troubleshooting](#troubleshooting)  

---

## Prerequisites

1. **Python 3.7 or newer**  
2. **pdflatex** on your `PATH` (part of a TeX distribution such as TeX Live or MiKTeX)  
   - Verify by running in a terminal:
     ```bash
     pdflatex --version
     ```
     It should print a version string; if not, install a TeX distribution and ensure `pdflatex` is in your system’s PATH.

3. **Python Packages**  
   Install the following with `pip`:
   ```bash
   pip install requests PyMuPDF Pillow
   ```
   - `requests`   (fetch remote `.tex` files)  
   - `PyMuPDF` (imported as `fitz`)  (render PDF → image)  
   - `Pillow`   (convert images for Tkinter)

---

## Installation

1. **Download or clone this repository** (or simply copy the script file).  
2. Locate the file named:
   ```
   live_tex_editor.py
   ```
3. (Optional) If you prefer a dedicated folder, create one and place `live_tex_editor.py` inside:
   ```bash
   mkdir LiveTeXEditor
   cd LiveTeXEditor
   # Copy live_tex_editor.py here
   ```

---

## Running the Editor

1. Open a terminal (or Command Prompt).  
2. Navigate to the directory containing `live_tex_editor.py`. For example:
   ```bash
   cd path/to/LiveTeXEditor
   ```
3. Run the script with Python:
   ```bash
   python live_tex_editor.py
   ```
4. A window titled “Live LaTeX Editor + Preview” will appear.  

---

## Usage Guide

### Opening a `.tex` from a URL

1. In the toolbar at the top, click **Open URL…**.  
2. A small dialog appears. Paste the **raw** URL of your `.tex` file. For example:
   ```
   https://raw.githubusercontent.com/username/repo/master/main.tex
   ```
3. Click **OK**.  
   - The editor will fetch the `.tex` → save as `main.tex` (or the basename from the URL) in your working directory.  
   - Two subfolders are automatically created if they don’t exist:
     - `build/`  ← where temporary `.tex` is compiled  
     - `backups/`  ← where timestamped backups will be stored every 10 minutes  
   - The left pane (“File Outline”) is populated from all `\section{…}`, `\subsection{…}`, etc.  
   - The center pane displays the raw source.  
   - The right pane immediately shows a rendered preview of page 1 of the compiled PDF.

---

### Editing & Live-Compile

- As you type or modify the `.tex` in the center editor:
  1. After you **stop typing for 2 seconds**, the script auto-saves your edits to `main.tex`.  
  2. It then runs:
     ```bash
     pdflatex -interaction=nonstopmode temp.tex
     ```
     inside the `build/` folder.  
  3. If there are no errors, the first page of `build/temp.pdf` is rendered on the right pane (“PDF Preview”).  
  4. The left “File Outline” is rebuilt (in case you added or changed any `\section{…}`).  
- If `pdflatex` fails (compile errors), a popup shows the `.log` output.

---

### Manual Save / Compile

- **Save Now** (button in toolbar):
  - Immediately writes whatever is in the editor to `main.tex` (in your working directory).  
  - You’ll see a confirmation dialog “Saved to main.tex.”  
- **Compile Now** (button in toolbar):
  - Immediately saves the current editor buffer to `main.tex`, then copies it into `build/temp.tex`, runs `pdflatex`, and re-renders the preview.  
  - If errors occur, a popup with the log is shown.  

---

### File Outline

- The **left pane** is a clickable Treeview showing all sectioning commands:
  - `\section{…}` → top-level nodes  
  - `\subsection{…}` → nested underneath  
  - `\subsubsection{…}` → three levels deep  
- Clicking any node will:
  1. Scroll the center editor to that line number.  
  2. Move the insertion cursor to the start of that section.  
  3. Give focus so you can begin editing right away.

---

### Backup Files

- Every **10 minutes** (regardless of activity), the script runs a backup routine:  
  1. Reads the current editor buffer (whatever is in the center pane).  
  2. Writes it to the folder `backups/` with a timestamp, e.g.:
     ```
     backups/backup_20250602_153045.tex
     ```
  3. Schedules the next backup 10 minutes later.  
- You can always retrieve an older state by opening one of these timestamped `.tex` files.

---

## Folder Structure

After you run the editor and open a `.tex`, you’ll see something like:

```
LiveTeXEditor/
├── live_tex_editor.py        ← (this script)
├── main.tex                  ← (fetched/edited .tex)
├── build/                    ← (auto-created on first compile)
│   ├── temp.aux
│   ├── temp.log
│   ├── temp.pdf
│   └── temp.tex
└── backups/                  ← (auto-created on first backup)
    ├── backup_20250602_153045.tex
    ├── backup_20250602_154045.tex
    └── …
```

- **main.tex** – always points to the current “live” .tex file you’re editing.  
- **build/** – used internally for each compile. You normally don’t edit anything here.  
- **backups/** – contains timestamped snapshots. Feel free to delete old ones periodically.

---

## Troubleshooting

- **`pdflatex` Errors / Not Found**  
  - If `python live_tex_editor.py` prints an error like  
    ```
    Error: pdflatex not found on PATH.
    ```
    install a TeX distribution (TeX Live or MiKTeX) and ensure `pdflatex` is available in your shell/command prompt.
  - If the preview window shows a popup with LaTeX log errors, inspect the typeset errors, fix in the editor, and re-compile.

- **Blank or Out-of-Date Preview**  
  - Make sure you’ve waited at least 2 seconds after your last keystroke (auto-compile delay).  
  - Or click **Compile Now** to force an immediate update.  

- **Outline Not Updating**  
  - The outline refreshes whenever you compile (auto or manual).  
  - If you add new `\section{…}` lines but don’t wait 2 seconds, click **Compile Now** to rebuild the outline.

- **Editor Feels Slow on Very Large `.tex` Files**  
  - The script reparses the entire buffer to build an outline on every compile. If your file is very large (hundreds of sections), you may notice a slight lag.  
  - As a workaround, you can disable outline updates by commenting out the call to `self._update_outline()` in `_live_update()` and after `_on_open_url()`, then manually rebuild the outline by clicking **Compile Now** only when needed.

---

## Summary

This README covers:

- How to install dependencies (`pip install …` + ensure `pdflatex` exists)  
- How to run the script (`python live_tex_editor.py`)  
- A step-by-step usage guide: open a remote `.tex`, edit, see live PDF preview, use the outline, manual save/compile, and timed backups.  

Enjoy a lightweight, Tkinter-based LaTeX editing environment with live preview and automatic backups. Happy TeXing!
