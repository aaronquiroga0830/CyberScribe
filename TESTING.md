# Testing CyberScribe

See [README.md](README.md) for installation, configuration, and startup. Run all commands from the repository root using the project Python environment.

## Automated checks

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m pip check
npm ci
npm run typecheck
npm run build
```

Tests cover evidence attribution, grounded suggestions, DOCX ingestion/export, and isolated API startup/authentication. The API smoke test runs in a separate process with temporary data/output folders; it does not change your mission database or require Ollama. The web smoke check uses the Vite build when present, so build the front end before running all checks in CI.

## Manual end-to-end check

1. Start Ollama with the model named in `.env`, build the interface, and start FastAPI as described in the README.
2. Sign in, or create the initial admin on a fresh installation.
3. Create a disposable mission with separate source and output folders. Add a short crew-log text file, a text PDF, or a DOCX containing paragraphs and a table.
4. Open each report type (RMP, Timeline, AAR, SITREP) and request an update.
5. Verify that suggestions remain pending until accepted, that reject leaves the draft intact, and that accepted edits can be saved and exported.
6. Select text in the editor and request inline assistance. Verify the evidence display, accept/reject controls, and continued typing after a suggestion.
7. Exercise comments and review transitions with the appropriate mission roles; finalize a report and verify content locks and DOCX/PDF exports.

The optional CLI/scheduler follows a separate RMP/Timeline generation path. Test it separately if you use it; it is not required to start the web application.
