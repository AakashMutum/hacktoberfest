# Draft "good first issue" tickets

These are ready to paste into GitHub issues. Add the `good first issue` label to each.

---

## 1. Native-speaker review of the Tamil and Hindi customer messages

**What:** The hand-written Tamil and Hindi templates in `backend/policy.py` (`COPY`) have not been reviewed by native speakers.

**Task:** Read each string for tone (calm, plain, respectful), natural banking terms (UPI PIN, cooling-off period, trusted contact) and how rupee amounts read in context. Suggest corrections in a pull request.

**Done when:** The `ta` and `hi` entries are reviewed, and `docs/translations.md` notes who reviewed them and when.

**Skills:** Tamil or Hindi. No coding needed beyond editing strings.

---

## 2. Add a fourth customer language

**What:** Customer messages exist in English, Tamil and Hindi.

**Task:** Add one more language, for example Telugu, Kannada, Malayalam or Bengali:
- add the copy to `COPY` in `backend/policy.py`
- add its Unicode range to `SCRIPT_RANGES` in `backend/investigator.py`
- add it to `LANG_NAMES`
- add the matching Noto font package to `web/src/main.tsx`
- add a toggle button in `web/src/components/Phone.tsx`

**Done when:** `tests/test_policy.py::test_copy_complete_in_every_language` passes for the new language, and the phone view renders it.

**Skills:** Python, a little React, the target language.

---

## 3. Show the investigator's tool calls as a timeline

**What:** In function-calling mode, each investigation records `tool_calls` (name and arguments). The rail only lists the tool names.

**Task:** In `web/src/components/Rail.tsx`, render the calls as a small ordered list with their arguments, so a viewer can see what Gemma checked.

**Done when:** An expanded flagged row shows each tool call, `npx eslint src --max-warnings=0` passes, and the layout works at 390 px.

**Skills:** React, TypeScript, CSS.

---

## 4. Point-in-time graph features

**What:** Graph features (`fan_in`, `passthrough`, `chain_depth`) are computed from a snapshot of all 30 days, which leaks future information into earlier payments. This is listed in the README limitations.

**Task:** Compute these features using only payments before each payment's timestamp, for example in daily windows. Then report how the held-out results change.

**Done when:** The generator produces point-in-time features, the tests pass, and the README results table is updated with the new numbers and a note on what changed.

**Skills:** Python, pandas, networkx.

---

## 5. Export the scoreboard as a CSV

**What:** The scoreboard numbers are computed live in `backend/engine.py` (`SystemStats.snapshot`), but they can't be saved.

**Task:** Add `GET /api/metrics.csv`, returning one row per system (Circuit Breaker, Rules A, Rules B) with the same fields as `/api/metrics`. Add a small "Download CSV" link on the scoreboard.

**Done when:** There is a pytest for the endpoint, and the link downloads a file whose numbers match the screen.

**Skills:** FastAPI, a little React.
