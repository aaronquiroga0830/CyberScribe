"""
FastAPI streaming server: runs pipeline in background and streams chunks via SSE.
Start with: uvicorn streaming_server:app --host 0.0.0.0 --port 8000
Streamlit calls POST /api/run-pipeline and embeds GET /stream-view for live document updates.
"""
import asyncio
import json
import re
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel

# Run from project root so src and config are importable
import sys
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.mission_service import get_mission, update_mission_last_ingest, update_mission_last_generated
from src.report_service import set_pending
from src.index.build import build_mission_index
from src.retrieve.retriever import get_mission_retriever
from src.agents.base import run_template_rag_agent_stream
from config.settings import get_ollama_base_url_for_report
from src.templates.prompts import (
    RMP_TEMPLATE_QUERY,
    TIMELINE_TEMPLATE_QUERY,
    RMP_GENERATION_PROMPT,
    TIMELINE_GENERATION_PROMPT,
)
from src.db.models import init_db

app = FastAPI(title="Mission RAG Streaming")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REPORT_SPECS = [
    ("rmp", RMP_TEMPLATE_QUERY, RMP_GENERATION_PROMPT),
    ("timeline", TIMELINE_TEMPLATE_QUERY, TIMELINE_GENERATION_PROMPT),
]


def _run_pipeline(mission_id: str, source_path: Path, app_ref: FastAPI) -> None:
    """Run in background thread: ingest, generate RMP + Timeline, push chunks to SSE queues."""
    state = app_ref.state
    loop = state.loop
    buffers = state.stream_buffers
    queues = state.stream_queues
    lock = state.stream_lock

    def push(report_type: str, chunk: str | None, full_content: str | None) -> None:
        key = (mission_id, report_type)
        with lock:
            if full_content is not None:
                buffers[key] = full_content
            qs = list(queues.get(key, []))

        def put():
            for q in qs:
                try:
                    q.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

        if qs:
            loop.call_soon_threadsafe(put)

    try:
        build_mission_index(mission_id=mission_id, source_path=source_path)
        update_mission_last_ingest(mission_id)
        retriever_rmp = get_mission_retriever(mission_id=mission_id, report_type="rmp")
        retriever_timeline = get_mission_retriever(mission_id=mission_id, report_type="timeline")
        shared_q = queue.Queue()

        def run_stream(report_type: str, template_query: str, gen_prompt: str, base_url: str, retriever) -> None:
            try:
                for kind, data in run_template_rag_agent_stream(
                    mission_id, template_query, gen_prompt, retriever=retriever, base_url=base_url
                ):
                    shared_q.put((report_type, kind, data))
            except Exception as e:
                shared_q.put(("error", report_type, str(e)))

        for rt, tq, gp in REPORT_SPECS:
            retriever = retriever_rmp if rt == "rmp" else retriever_timeline
            threading.Thread(
                target=run_stream,
                args=(rt, tq, gp, get_ollama_base_url_for_report(rt), retriever),
                daemon=True,
            ).start()

        full = {"rmp": "", "timeline": ""}
        done = {"rmp": False, "timeline": False}
        error_msg = None
        while not (done["rmp"] and done["timeline"]) and error_msg is None:
            try:
                report_type, kind, data = shared_q.get(timeout=0.05)
            except queue.Empty:
                continue
            if kind == "error":
                error_msg = data
                break
            if kind == "chunk":
                full[report_type] += data
                display = re.sub(r"\n{3,}", "\n\n", full[report_type])
                push(report_type, data, display)
            else:
                set_pending(mission_id, report_type, full[report_type], sources=data)
                done[report_type] = True
                if done["rmp"] and done["timeline"]:
                    update_mission_last_generated(mission_id)
                push(report_type, None, full[report_type])

        for rt in ("rmp", "timeline"):
            push(rt, None, None)
        with lock:
            state.running_mission_id = None
    except Exception as e:
        with lock:
            state.running_mission_id = None
        push("rmp", None, None)
        push("timeline", None, None)


@app.on_event("startup")
def startup():
    init_db()
    app.state.loop = asyncio.get_event_loop()
    app.state.stream_buffers = {}
    app.state.stream_queues = {}
    app.state.stream_lock = threading.Lock()
    app.state.running_mission_id = None


class RunPipelineBody(BaseModel):
    mission_id: str


@app.post("/api/run-pipeline")
def run_pipeline_api(body: RunPipelineBody):
    mission = get_mission(body.mission_id)
    if not mission:
        return {"ok": False, "error": "Mission not found"}
    source_path = Path(mission["source_path"])
    if not source_path.is_dir():
        return {"ok": False, "error": "Source path is not a directory"}
    with app.state.stream_lock:
        app.state.running_mission_id = body.mission_id
    threading.Thread(target=_run_pipeline, args=(body.mission_id, source_path, app), daemon=True).start()
    return {"ok": True, "mission_id": body.mission_id}


async def _sse_stream(mission_id: str, report_type: str, request: Request):
    state = request.app.state
    buffers = state.stream_buffers
    queues = state.stream_queues
    lock = state.stream_lock
    key = (mission_id, report_type)

    q = asyncio.Queue()
    with lock:
        buffers.setdefault(key, "")
        queues.setdefault(key, []).append(q)

    try:
        # Send buffered content first so client catches up
        with lock:
            buf = buffers.get(key, "")
        if buf:
            yield f"data: {json.dumps({'t': 'buf', 'text': buf})}\n\n"

        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'t': 'ping'})}\n\n"
                continue
            if chunk is None:
                yield f"data: {json.dumps({'t': 'done'})}\n\n"
                break
            yield f"data: {json.dumps({'t': 'chunk', 'text': chunk})}\n\n"
    finally:
        with lock:
            if key in queues:
                try:
                    queues[key].remove(q)
                except ValueError:
                    pass


@app.get("/api/stream/{mission_id}/{report_type}")
async def stream_sse(mission_id: str, report_type: str, request: Request):
    if report_type not in ("rmp", "timeline"):
        return {"error": "Invalid report_type"}
    return StreamingResponse(
        _sse_stream(mission_id, report_type, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


STREAM_VIEW_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Live stream</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 8px; background: #0e1117; color: #fafafa; }
    #out { white-space: pre-wrap; word-wrap: break-word; max-height: 320px; overflow-y: auto; padding: 8px; border: 1px solid #333; border-radius: 4px; min-height: 80px; }
    .status { font-size: 0.9em; color: #888; margin-bottom: 6px; }
  </style>
</head>
<body>
  <div class="status" id="status">Connecting…</div>
  <div id="out"></div>
  <script>
    const params = new URLSearchParams(window.location.search);
    const missionId = params.get('mission_id') || '';
    const reportType = params.get('report_type') || 'rmp';
    const base = window.location.origin;
    const url = base + '/api/stream/' + encodeURIComponent(missionId) + '/' + encodeURIComponent(reportType);

    const out = document.getElementById('out');
    const status = document.getElementById('status');

    const es = new EventSource(url);
    let content = '';

    es.onmessage = function(e) {
      try {
        const d = JSON.parse(e.data);
        if (d.t === 'buf') {
          content = d.text || '';
          out.textContent = content || 'Generating…';
        } else if (d.t === 'chunk') {
          content += d.text || '';
          out.textContent = content;
          out.scrollTop = out.scrollHeight;
        } else if (d.t === 'done') {
          status.textContent = 'Done.';
          es.close();
        } else if (d.t === 'ping') {
          // keepalive
        }
      } catch (err) {}
    };

    es.onerror = function() {
      status.textContent = 'Disconnected. Run pipeline to see live stream.';
      if (!content) out.textContent = 'No active stream for this document.';
    };

    es.onopen = function() {
      status.textContent = 'Live stream connected.';
      if (!content) out.textContent = 'Generating…';
    };
  </script>
</body>
</html>
"""


@app.get("/stream-view", response_class=HTMLResponse)
def stream_view(mission_id: str, report_type: str = "rmp"):
    return HTMLResponse(STREAM_VIEW_HTML)


@app.get("/api/status")
def status():
    with app.state.stream_lock:
        mid = getattr(app.state, "running_mission_id", None)
    return {"running_mission_id": mid}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
