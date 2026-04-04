これが AI に編集を任せるための中核指示書です。

# AGENTS.md

## Purpose
This repository is a Flask-based timetable and transit information web app.
Your role is to safely debug, extend, and maintain the app without breaking existing CSV/Excel timetable support, frontend expectations, or transport-status fallback behavior.

## Core mindset
- Preserve working behavior
- Prefer minimal safe patches
- Respect real timetable data and naming
- Keep frontend-backend contracts stable
- Explain assumptions instead of hiding them

## Absolute guardrails
- Never remove external API fallback behavior unless explicitly instructed
- Never hardcode timetable content that should come from `timetable_data/`
- Never silently change endpoint names or JSON response shape
- Never rename route labels, file names, sheet names, or Excel columns without explicitly stating the impact
- Never replace Japanese labels or route names with generic placeholders
- Never do a full architecture rewrite for a local bug fix
- Never assume all timetable files share one perfectly clean schema

## Standard procedure
For any non-trivial task, do the following:

1. Classify the issue
- backend logic
- frontend rendering
- timetable file mapping
- external API / scraping
- UI text / settings
- icon or static asset handling

2. Locate the exact implementation
- identify the endpoint, helper, or rendering function
- identify the data source it depends on
- identify any frontend-backend dependency

3. Separate verified facts from inferences
- verified: confirmed from file paths, function names, API routes, data loading logic, DOM ids
- inferred: likely intent, expected timetable schema, desired UX

4. Minimize the patch
- prefer a local fix
- avoid broad refactors unless explicitly requested
- preserve current route configuration and UI behavior

5. Validate explicitly
- show how to run the app
- show which route / stop / endpoint to test
- show what output should change

## Required response format for bug fixing
1. Verified location
2. Root cause
3. Minimal patch
4. Risks / side effects
5. Validation steps
6. Remaining uncertainty

## Repository-specific guidance

### Backend changes
Always check:
- endpoint path
- helper function used
- file path assumptions
- encoding assumptions
- timetable file type (CSV or Excel)
- response shape consumed by frontend

### Frontend changes
Always check:
- DOM id and class usage in HTML and JS
- whether backend still returns the expected fields
- whether route toggles and count inputs still behave correctly
- whether icon lookup can fail safely

### Timetable data changes
Always check:
- file naming convention
- weekday / holiday suffix logic
- Excel sheet names
- column names
- encoding
- whether the route definition references the file correctly

### External API / status logic
Always check:
- primary API
- fallback source
- timeout / failure handling
- whether the frontend can still render partial results

## Preferred change style
- Small diffs
- Natural Japanese for user-facing text
- Clear comments only where necessary
- No large rewrites without instruction
- Preserve operability first, cleanup second

## If asked to add a new feature
Implement in this order:
1. preserve current behavior
2. add minimal backend support
3. add minimal frontend support
4. test with one route / stop first
5. then generalize

## If asked to add a new route, stop, or timetable source
Always provide:
1. required data file naming
2. required code reference update
3. expected API output
4. UI impact
5. test steps
6. skill 1: debug-timetable-fetch

時刻表が出ない、駅だけ空白、バスだけ壊れる、みたいな時に使う skill です。

.github/skills/debug-timetable-fetch/SKILL.md

7. skill 2: add-route-or-stop

新しい駅・方面・バス停・路線を増やすとき用です。

.github/skills/add-route-or-stop/SKILL.md

8. skill 3: safe-ui-edit

見た目調整や表示項目追加を AI にやらせるとき用です。

.github/skills/safe-ui-edit/SKILL.md

9. AI に投げるときの実用プロンプト

これを使うと、かなり自走しやすくなります。

バグ修正
/debug-timetable-fetch
○○路線の発車案内が表示されません。
推測ではなく、実際の backend helper と timetable_data 側の参照を追って、
1. verified location
2. root cause
3. minimal patch
4. validation steps
の順で出してください。
路線追加
/add-route-or-stop
新しく ○○駅 / ○○方面 を追加したいです。
既存命名規則を確認し、
必要な timetable_data のファイル名、
必要な backend 修正箇所、
必要なら frontend のラベルやアイコン修正箇所を、
最小変更で提案してください。
見た目調整
/safe-ui-edit
設定画面の見た目を整理したいです。
既存機能を消さずに、
DOM id と app.js の依存関係を壊さない最小変更案を出してください。
10. さらに AI に任せやすくする追加ルール

この repo では特に次を守らせると事故が減ります。

- まず backend か frontend か data-file mapping かを分類する
- timetable_data を見ずに時刻表バグの結論を出さない
- Excel のシート名と列名は勝手に正規化しない
- API が壊れても既存フォールバックを安易に削除しない
- UI テキストは自然な日本語を保つ
- 大改修は別提案に分け、今回の修正とは分離する
11. この repo 向けの運用方針

この repo は Flask 単一ファイル寄りなので、最初から「分割リファクタしてください」と AI に言うと壊れやすいです。
順番としては、

まず instructions と AGENTS.md を置く
次に skill を置く
そのあと AI に「最小変更で」修正させる
動作確認が取れてから段階的分割を考える

が安全です。