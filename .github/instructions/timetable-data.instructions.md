---
applyTo: "timetable_data/**/*"
---

Treat timetable data files as operational data, not code.

## Rules
- Do not rename files, sheet names, or columns unless explicitly requested
- If suggesting a rename or normalization, explain which code references must also change
- Preserve the distinction between train CSV files and bus Excel files
- Be careful with weekday / holiday naming assumptions
- Surface mismatches clearly instead of hiding them

## If asked to support a new route or stop
- First identify the current naming convention
- Then state the minimal required data-file change
- Then state the matching code-side change