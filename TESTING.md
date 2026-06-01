# How to run and test the MVP

Run everything from the **project folder** (`agentic_rag_mvp`).

## 1. One-time setup

```powershell
cd C:\Users\aaron\agentic_rag_mvp
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy env (optional; defaults work if Ollama is on localhost):

```powershell
copy .env.example .env
```

Edit `.env` if needed (e.g. `OLLAMA_MODEL=llama3.2`).

## 2. Start Ollama (local LLM)

In a separate terminal (or in background):

```powershell
ollama serve
ollama pull llama3.2
```

Leave Ollama running. Use whatever model you already have (e.g. `llama3.2`, `mistral`); set `OLLAMA_MODEL` in `.env` to match.

## 3. Run the UI

From the project folder with venv activated:

```powershell
cd C:\Users\aaron\agentic_rag_mvp
.venv\Scripts\activate
uvicorn server:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** in your browser.

## 4. Test in the UI

1. **Create a mission**
   - Click **+ New mission**.
   - Mission name: `Test Mission`.
   - Document pick-up: `C:\Users\aaron\agentic_rag_mvp\data\missions\sample_mission`
   - Drop-off: `C:\Users\aaron\agentic_rag_mvp\output\test_mission` (or any folder you want).
   - Click **Create mission**.

2. **Run the pipeline once**
   - Open the mission, then click **Open RMP & Timeline**.
   - Click **Run pipeline now**. Both RMP and Timeline streams appear in real time.

3. **Review documents**
   - When streams finish, **Pending draft** sections appear. Use **Accept** or **Reject**.
   - Edit **Current version** and click **Save edits to drop-off** if needed.
   - Check the drop-off folder for `Risk_Mitigation_Plan.txt` and `Mission_Timeline.txt` after Accept or Save.

## 5. Optional: background scheduler

To test the daily job (runs at 02:00 by default, or trigger manually in UI):

```powershell
python run_scheduler.py
```

Keep it running in a second terminal. For a one-off test, “Run pipeline now” in the UI is enough.

## 6. Optional: CLI

```powershell
# Build index and generate (mission id = slug of name, e.g. test_mission)
python run.py build test_mission --source "C:\Users\aaron\agentic_rag_mvp\data\missions\sample_mission"
python run.py run test_mission
# Or both:
python run.py all test_mission --source "C:\Users\aaron\agentic_rag_mvp\data\missions\sample_mission"
```

## Troubleshooting

- **Import errors**: Run all commands from `C:\Users\aaron\agentic_rag_mvp` with venv activated.
- **Ollama connection**: Ensure `ollama serve` is running and `.env` has `OLLAMA_BASE_URL=http://localhost:11434`.
- **No documents found**: Pick-up path must be a folder containing at least one `.txt` or `.pdf` file.
- **First run slow**: Sentence-transformers and FAISS load on first use; later runs are faster.
