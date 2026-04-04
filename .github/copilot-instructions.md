# timetable_app_0901 repository-wide Copilot instructions

This repository is a timetable and transit information web application built around a Flask backend and a lightweight frontend.

## Project priorities
- Preserve working behavior over refactoring
- Prefer minimal safe edits
- Keep data-loading behavior explicit
- Keep external API fallback behavior intact
- Do not rewrite the app into another framework unless explicitly requested

## Repository structure
- `timetable_app.py` contains the Flask app, API routes, data loading, and external fetch logic
- `static/app.js` contains frontend rendering and settings UI logic
- `templates/index.html` contains the page structure
- `timetable_data/` contains CSV and Excel timetable files
- `static/img/` contains operator / line / bus icons

## Non-negotiable guardrails
- Never remove or silently weaken fallback behavior for external APIs or scraping
- Never hardcode timetable values that should come from CSV or Excel files
- Never change route labels, sheet names, or column names without stating the exact impact
- Never assume timetable files have a single fixed format; keep CSV/Excel mismatch handling visible
- Never replace working Japanese text, labels, or route names with placeholders
- Never convert the whole codebase into a large refactor when the request is only a bug fix

## Working style
When asked to edit code:
1. Identify whether the issue is backend, frontend, data file mapping, or external API related
2. Show the exact file and function involved
3. Prefer the smallest safe patch
4. Preserve current UI behavior unless the request explicitly changes UX
5. Explain validation steps

## Data and API behavior
- Be careful with CSV encoding differences such as UTF-8 and CP932
- Preserve support for both train CSV and bus Excel timetable sources
- Keep 24-hour display-window assumptions unless explicitly asked to change
- Keep API response shapes stable for the frontend

## Output style
For debugging or edits, structure the response as:
1. Verified location
2. Root cause
3. Minimal patch
4. Risks / side effects
5. Validation steps