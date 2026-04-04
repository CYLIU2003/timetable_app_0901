---
name: debug-timetable-fetch
description: Use when: a schedule does not appear, a route or stop is empty, CSV or Excel timetable loading fails, or backend and frontend schedule output do not match.
---

# debug-timetable-fetch

## Goal
Find why a timetable is not appearing and propose the smallest safe fix.

## Steps
1. Identify whether the affected source is train CSV or bus Excel
2. Trace the path from request -> backend helper -> file path / sheet / column
3. Verify weekday / holiday suffix logic
4. Check file existence, encoding, sheet names, and column names
5. Check whether the frontend is filtering or rendering the returned data incorrectly
6. Produce:
   - verified location
   - root cause
   - minimal patch
   - validation steps

## Required checks
- file path construction
- encoding fallback
- empty or malformed rows
- Excel sheet mismatch
- frontend response expectation

## Output format
1. Verified location
2. Root cause
3. Minimal patch
4. Risks
5. Validation