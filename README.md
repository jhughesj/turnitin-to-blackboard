# rbc_to_bb_prompt

A Python utility that converts Turnitin Rubric (`.rbc`) files into prompt text ready to paste into Blackboard Ultra's AI Rubric Generator — making it practical to migrate existing Turnitin rubrics to Blackboard without rebuilding them from scratch.

---

## The problem this solves

Turnitin rubrics can only be exported as `.rbc` files (a JSON-based format). Blackboard Ultra cannot import these directly. The usual workaround — copying and pasting from a Word document table — is slow and error-prone at scale.

Blackboard Ultra now includes an AI Rubric Generator that can create a rubric from a text description. This script converts your `.rbc` file into exactly the kind of structured prompt that generator needs, staying within its ~2,000 character limit automatically.

---

## Features

- Handles all three Turnitin rubric types: full rubrics with scale levels, percentage-band rubrics (e.g. 19 levels from 0%–100%), and grading forms with no scale definitions
- Automatically compresses output to stay under Blackboard's ~2,000 character limit using a 7-step cascade (see below)
- For rubrics with more than 6 levels, samples low/mid/high descriptors — enough for the AI to understand the quality progression without exceeding the limit
- **CLI mode** for batch processing multiple files at once
- **GUI mode** with file picker, output folder selector, progress bar, and colour-coded log
- No third-party packages required (standard Python 3.6+ only; GUI requires tkinter, bundled with the python.org installer)

---

## Requirements

- Python 3.6 or later
- tkinter (included with the standard python.org installer on Windows and macOS)

---

## Installation

**1. Download or clone this repository**

```bash
git clone https://github.com/jhughesj/turnitin-to-blackboard.git
cd rbc_to_bb_prompt
```

Or download `rbc_to_bb_prompt.py` directly.

**2. Check Python is installed**

```bash
python3 --version
```

If Python is not installed, download it from [python.org](https://www.python.org/downloads/).

**3. macOS only — add Python to your PATH if needed**

```bash
echo 'export PATH="/usr/local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
python3 --version
```

---

## Usage

### CLI mode — single file or batch

```bash
python3 rbc_to_bb_prompt.py my_rubric.rbc
python3 rbc_to_bb_prompt.py *.rbc
```

Each `.rbc` file produces a `_BB_prompt.txt` file saved alongside it. The terminal shows the rubric name, type, number of criteria, character count, and whether compression was applied.

### GUI mode

```bash
python3 rbc_to_bb_prompt.py --gui
```

Opens a dark-themed window where you can add files, choose an output folder, and run the conversion with a progress bar and colour-coded log. If no arguments are given, the GUI opens by default.

---

## How to export your Turnitin rubric as an .rbc file

1. In Blackboard Ultra, open your Turnitin assignment
2. Open the rubric in the Turnitin Rubric Manager
3. Select **Export** and save the `.rbc` file to your computer

---

## How to use the output in Blackboard Ultra

1. Run the script against your `.rbc` file
2. Open the generated `_BB_prompt.txt` and copy its contents
3. In Blackboard Ultra, go to your assignment → **Grading & Rubrics**
4. Select **Add Grading Rubric** → **Create New Rubric** → **Generate with AI**
5. Paste the prompt text into the description box
6. Review the generated rubric carefully before saving — always check criteria names, weightings, and descriptors match your original

---

## Auto-compression cascade

The script tries 7 progressively smaller strategies and stops as soon as output is under 1,900 characters:

| Step | Strategy |
|------|----------|
| 1 | Full text — no compression |
| 2 | Trim long descriptors to 50 words |
| 3 | Trim to 30 words |
| 4 | Group criteria with identical descriptors + 50-word trim |
| 5 | Group identical criteria + 25-word trim |
| 6 | Group identical criteria + 15-word trim |
| 7 | Drop all descriptors — criteria names and weightings only |

The log shows ⚡`compressed` next to any file that needed compression, so you know which rubrics the AI had less detail to work from and may need closer review after generation.

---

## Example files

The `examples/` folder contains sample `.rbc` files you can use to test the tool before using your own rubrics. These do not contain real student or staff data.

---

## Development notes

This tool was developed to support a Turnitin-to-Blackboard Ultra migration project, and written with the help of AI coding assistants. It is shared here in the hope it is useful to others facing the same challenge.

---

## Author

Developed by **Jonathan Hughes**, Senior Digital Learning Specialist  
University of Westminster

---

## Licence

This project is licensed under the **MIT License**.

```
MIT License

Copyright (c) 2025 Jonathan Hughes

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Disclaimer

Always review AI-generated rubrics carefully before using them for formal assessment. The author accepts no responsibility for rubrics used without adequate review.
