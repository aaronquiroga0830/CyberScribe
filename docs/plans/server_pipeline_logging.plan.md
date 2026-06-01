---
name: Server pipeline logging
overview: Add logging in the server pipeline and stream flow so we can see what happens when a run starts, when chunks arrive, when each report finishes or errors, and when the pipeline clears state. No behavior change.
todos: []
isProject: false
---

# Server pipeline logging

## Goal

Add logging so that when the app runs (or stalls/crashes), we can see:

- When a pipeline run starts and for which mission/reports
- When the stream for each report produces chunks (without flooding the log)
- When each report's stream finishes normally ("sources" received) or with an error
- When the pipeline loop exits and why (all done vs error)
- When `running_mission_id` is cleared (normal exit vs exception)

End-to-end visibility: add logging in the **agent** (base.py, where the LLM stream runs) and in **report_service** (when pending is written) so we can see exactly where the process is when it stalls.

This will confirm whether the problem is "stream stopped, pipeline never got sources."

---

## 1. Logger setup

**File:** [server.py](C:\Users\aaron\agentic_rag_mvp\server.py)

- Add `import logging` at the top with the other stdlib imports.
- After imports, define a module-level logger, e.g. `logger = logging.getLogger(__name__)`. Rely on the app's existing logging level (or default); no need to change global config unless you want pipeline logs at a different level.

---

## 2. Pipeline start

**File:** [server.py](C:\Users\aaron\agentic_rag_mvp\server.py) – inside `_run_pipeline`, after `run_types` is finalized and before the `with lock:` block.

- Log once: e.g. `logger.info("pipeline start mission_id=%s report_types=%s", mission_id, run_types)`.

---

## 3. Report stream thread start and exit

**File:** [server.py](C:\Users\aaron\agentic_rag_mvp\server.py) – inside the nested `run_stream` function.

- **Start:** At the very beginning of `run_stream` (first line inside the function), log: `logger.info("stream start mission_id=%s report_type=%s", mission_id, report_type)`.
- **Normal exit:** The generator yields `("sources", sources)` then the loop ends. We can't log inside the generator from here, but the consumer will log when it receives sources (see below). Optionally, after the `for kind, data in run_template_rag_agent_stream(...)` loop ends (normally), log: `logger.info("stream finished mission_id=%s report_type=%s", mission_id, report_type)`. That confirms the thread is about to exit after sending sources.
- **Error exit:** In the `except Exception as e:` block, log before putting the error on the queue: `logger.warning("stream error mission_id=%s report_type=%s error=%s", mission_id, report_type, e)` (or `logger.exception(...)` to include traceback).

---

## 4. Consumer loop: chunks, sources, error

**File:** [server.py](C:\Users\aaron\agentic_rag_mvp\server.py) – inside the `while not all(done.values()) and error_msg is None:` loop.

- **Chunk:** To avoid flooding, log chunk activity periodically. For example, maintain a counter per report: `chunk_count[report_type] += 1` when `kind == "chunk"`, and when `chunk_count[report_type] % 100 == 1` (or every 50 chunks), log: `logger.debug("chunks mission_id=%s report_type=%s count=%s", mission_id, report_type, chunk_count[report_type])`. Initialize `chunk_count = {rt: 0 for rt in run_types}` before the loop. Using `logger.debug` keeps normal runs quiet unless the user sets log level to DEBUG.
- **Sources (report completed):** When `kind != "chunk"` (i.e. we got the final "sources" message), log: `logger.info("report done mission_id=%s report_type=%s", mission_id, report_type)`.
- **Error:** When `kind == "error"`, you already set `error_msg = data`. Just before the `break`, log: `logger.warning("pipeline error mission_id=%s report_type=%s error=%s", mission_id, report_type, error_msg)`.

---

## 5. Loop exit and cleanup

**File:** [server.py](C:\Users\aaron\agentic_rag_mvp\server.py) – immediately after the `while` loop, and in the `except` block.

- **After the loop:** Log why we exited:
  `logger.info("pipeline loop exit mission_id=%s all_done=%s error=%s", mission_id, all(done.values()), error_msg)`.
- **Before clearing running_mission_id (normal path):** Right before `state.running_mission_id = None` in the `try` block, log: `logger.info("pipeline cleanup mission_id=%s", mission_id)`.
- **In the except block:** Before clearing `running_mission_id`, log: `logger.exception("pipeline exception mission_id=%s", mission_id)` (or `logger.error(..., exc_info=True)`). Then clear state as now.

---

## 6. Agent stream (base.py)

**File:** [src/agents/base.py](C:\Users\aaron\agentic_rag_mvp\src\agents\base.py)

- Add `import logging` and `logger = logging.getLogger(__name__)` at the top (if not already present).
- In `run_template_rag_agent_stream`, **before** the `for chunk in chain.stream(...)` loop: log once, e.g. `logger.info("agent stream start mission_id=%s", mission_id)`.
- **After** the loop (when it exits normally, right before `yield ("sources", sources)`): log once, e.g. `logger.info("agent stream end mission_id=%s", mission_id)`.
- Optional: wrap the `for chunk in chain.stream(...)` loop (and the yield after it) in try/except; on exception, log `logger.exception("agent stream error mission_id=%s", mission_id)` then re-raise. That way a stall inside Ollama shows as "agent stream start" with no "agent stream end" or "agent stream error"; an exception in the generator shows as "agent stream error".

Interpretation: "agent stream start" but no "agent stream end" for that run → hang is inside the LLM stream (Ollama/connection). "agent stream end" but no "report done" in server → issue between generator and consumer.

---

## 7. Report service (set_pending)

**File:** [src/report_service.py](C:\Users\aaron\agentic_rag_mvp\src\report_service.py)

- Add `import logging` and `logger = logging.getLogger(__name__)` at the top (if not already present).
- At the start of `set_pending` (after the report_type check), log once: e.g. `logger.info("set_pending mission_id=%s report_type=%s len=%s", mission_id, report_type, len(content))`.

Then you can see whether a given report ever reached "saved as pending." If you see "report done" in server but no "set_pending" for that report, something went wrong between the consumer and the DB.

---

## 8. Optional: request entry points

**File:** [server.py](C:\Users\aaron\agentic_rag_mvp\server.py)

- In `request_mission_update` (or wherever the pipeline is triggered), you can log once when an update is requested: e.g. `logger.info("update requested mission_id=%s report_types=%s", mission_id, report_types)`. That ties pipeline runs to API calls in the log.

---

## Summary

| Where | What to log |
|-------|-------------|
| **server.py** | |
| Pipeline start | mission_id, report_types |
| run_stream start | mission_id, report_type |
| run_stream normal exit | mission_id, report_type (after loop) |
| run_stream exception | mission_id, report_type, error |
| Consumer: chunk | debug, every N chunks per report (e.g. 100) |
| Consumer: sources | info, report done for mission_id, report_type |
| Consumer: error | warning, pipeline error + report_type + message |
| After while loop | all_done, error_msg |
| Before running_mission_id = None (normal) | pipeline cleanup mission_id |
| In except | pipeline exception mission_id + traceback |
| **src/agents/base.py** | |
| Before chain.stream loop | agent stream start mission_id |
| After loop (normal exit) | agent stream end mission_id |
| On exception in stream (optional) | agent stream error mission_id + traceback |
| **src/report_service.py** | |
| set_pending entry | mission_id, report_type, len(content) |

Use a logger per module (`logging.getLogger(__name__)`). No change to control flow or timeouts; only logging so the next run (or stall) produces a clear trace.
