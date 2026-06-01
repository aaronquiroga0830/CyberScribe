"""
Report-specific agents: RMP and Mission Timeline.
Each uses the template-as-query pattern and can be run in parallel.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from config.settings import OUTPUT_DIR
from src.agents.base import run_template_rag_agent
from src.templates.prompts import (
    RMP_TEMPLATE_QUERY,
    TIMELINE_TEMPLATE_QUERY,
    RMP_GENERATION_PROMPT,
    TIMELINE_GENERATION_PROMPT,
)


def run_rmp_agent(mission_id: str, retriever_k: int = 8) -> str:
    """Generate Risk Mitigation Plan from mission docs. Returns content only (CLI path; sources not written to file)."""
    content, _ = run_template_rag_agent(
        mission_id=mission_id,
        template_query=RMP_TEMPLATE_QUERY,
        generation_prompt_template=RMP_GENERATION_PROMPT,
        retriever_k=retriever_k,
    )
    return content


def run_timeline_agent(mission_id: str, retriever_k: int = 8) -> str:
    """Generate mission timeline from crew logs and findings. Returns content only (CLI path)."""
    content, _ = run_template_rag_agent(
        mission_id=mission_id,
        template_query=TIMELINE_TEMPLATE_QUERY,
        generation_prompt_template=TIMELINE_GENERATION_PROMPT,
        retriever_k=retriever_k,
    )
    return content


def run_all_report_agents(
    mission_id: str,
    retriever_k: int = 8,
    output_dir: Path | None = None,
    run_parallel: bool = True,
) -> dict[str, str]:
    """
    Run RMP and Timeline agents. If run_parallel=True, run in parallel threads.
    Saves outputs to output_dir/mission_id/ and returns {report_type: content}.
    """
    output_dir = output_dir or OUTPUT_DIR
    mission_out = output_dir / mission_id
    mission_out.mkdir(parents=True, exist_ok=True)

    def run_rmp() -> tuple[str, str]:
        content = run_rmp_agent(mission_id, retriever_k=retriever_k)
        (mission_out / "rmp_draft.txt").write_text(content, encoding="utf-8")
        return "rmp", content

    def run_timeline() -> tuple[str, str]:
        content = run_timeline_agent(mission_id, retriever_k=retriever_k)
        (mission_out / "timeline_draft.txt").write_text(content, encoding="utf-8")
        return "timeline", content

    results: dict[str, str] = {}
    if run_parallel:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run_rmp), executor.submit(run_timeline)]
            for f in as_completed(futures):
                name, content = f.result()
                results[name] = content
    else:
        results["rmp"], results["timeline"] = run_rmp()[1], run_timeline()[1]

    return results
