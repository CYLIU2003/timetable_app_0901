---
applyTo: "static/**/*.js,templates/**/*.html"
---

This frontend is lightweight and tightly coupled to backend response formats.

## Rules
- Preserve existing API response expectations
- Avoid unnecessary rewrites of the rendering structure
- Keep Japanese UI labels natural and user-facing
- Do not remove configuration UI unless explicitly requested
- Preserve route visibility toggles, count settings, and card rendering behavior
- Do not assume icons always exist; keep graceful fallback behavior

## When editing
- Check which DOM ids and class names are used by both HTML and JS
- Verify whether the backend response shape still matches frontend usage
- Prefer minimal edits that do not force large HTML/JS rewrites