---
name: add-route-or-stop
description: Use when: adding a new station, stop, destination, route, CSV timetable, or Excel timetable mapping to the app.
---

# add-route-or-stop

## Goal
Add a new route or stop safely without breaking existing timetable behavior.

## Steps
1. Identify whether the new source is train CSV or bus Excel
2. Find the existing naming convention for similar routes
3. Add the minimal backend mapping change
4. Add the minimal frontend label / icon support if needed
5. Keep current routes working
6. Provide exact test steps

## Required output
- required file naming pattern
- code locations to edit
- icon or label changes if needed
- endpoint / UI impact
- test scenario

## Important rules
- Do not rename existing routes unless explicitly requested
- Do not assume one schema for all files
- Keep labels natural and consistent with existing Japanese naming