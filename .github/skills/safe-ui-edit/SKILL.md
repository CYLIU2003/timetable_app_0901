---
name: safe-ui-edit
description: Use when: modifying the display, settings modal, cards, route selectors, color settings, or other UI behavior without breaking backend contract compatibility.
---

# safe-ui-edit

## Goal
Make frontend/UI changes while preserving backend compatibility and current settings behavior.

## Steps
1. Identify the affected DOM ids, classes, and JS functions
2. Check the backend response fields used by the UI
3. Make the smallest HTML / JS edit possible
4. Preserve existing settings and toggles unless explicitly changing them
5. Provide concrete browser-side validation steps

## Required checks
- DOM element existence
- event binding consistency
- API field usage
- icon fallback behavior
- route toggle and count-setting behavior

## Output format
1. Verified location
2. UI issue or requested change
3. Minimal patch
4. Risks
5. Validation