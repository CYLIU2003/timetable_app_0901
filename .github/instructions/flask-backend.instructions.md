---
applyTo: "timetable_app.py"
---

This file is the monolithic Flask backend and should be edited carefully.

## Rules
- Prefer local, surgical fixes over broad restructuring
- Preserve route names, API endpoints, and response JSON shape unless explicitly requested
- Do not remove logging or debug output that helps identify CSV/Excel mismatches
- Preserve fallback logic for transport status acquisition
- Keep Japanese labels and operator names intact
- Do not silently alter time-window behavior for schedule display

## Before editing
- Identify the exact route or helper function involved
- Check whether the issue is caused by:
  - file path mismatch
  - CSV encoding
  - Excel sheet or column mismatch
  - API fetch failure
  - scraping fallback failure
  - frontend expectation mismatch

## Required answer style
Always explain:
- which endpoint or helper is affected
- what data source it depends on
- whether the issue is verified from code or inferred