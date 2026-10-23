# Contributing

Thanks for helping. Circuit Breaker is a small project, so the process is light: open an issue or a pull request, keep changes focused, and make sure the tests pass.

## Set up

Requirements: Python 3.10+ (CI uses 3.13) and Node 18+ (CI uses 22).

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
cd web; npm install; npm run build; cd ..
copy .env.example .env
.\.venv\Scripts\python -m backend
```

**macOS and Linux (bash)**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
(cd web && npm install && npm run build)
cp .env.example .env
.venv/bin/python -m backend
```

The server listens on http://127.0.0.1:8000. Every variable in `.env` is optional. With no model provider, investigations use labelled templates.

For frontend work, run `npm run dev` in `web/` (port 5173). It proxies `/api` and `/ws` to the backend on port 8000.

## Run the checks

```bash
python -m pytest -q tests               # unit and API tests
(cd web && npx eslint src --max-warnings=0 && npm run build)
python scripts/demo_check.py            # every endpoint, against a running server
python scripts/failure_drills.py        # invalid key, no internet, slow model, closed WebSocket
python scripts/tour_check.py            # the demo tour, headless, in Safe mode
```

The last two need Playwright's Chromium: `python -m playwright install chromium`.

CI runs pytest, the lint and the frontend build, and builds the Docker image, on every push and pull request.

## Ground rules

- **Data stays synthetic.** Do not add real customer data, real VPAs or real phone numbers, including in tests and screenshots.
- **Never present template text as model output.** Every model-written explanation must keep its provenance label.
- **Numbers in the UI come from computation.** Do not hardcode metrics or results.
- **Changing results.** If you change the generator, the scorer or the policy thresholds, rerun the README results and say so in the pull request.
- **Secrets.** Never commit `.env` or API keys.
- **Translations.** Tamil and Hindi copy changes are welcome. A native speaker's review is especially useful (see `docs/translations.md`).
