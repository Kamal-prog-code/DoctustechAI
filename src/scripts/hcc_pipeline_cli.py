from __future__ import annotations

import argparse
import csv
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from framework.llm.client import VertexGeminiClient
from framework.llm.config import VertexAIConfig
from workflows.hcc.v1.config import PipelineConfig
from workflows.hcc.v1.nodes.extract_conditions_llm import LLMConditionExtractor
from workflows.hcc.v1.nodes.extract_conditions_rule_based import RuleBasedConditionExtractor
from workflows.hcc.v1.nodes.hcc_evaluation import HccCodeLookup, HccEvaluator
from workflows.hcc.v1.orchestrator import build_graph
from workflows.hcc.v1.schemas.llm import RESPONSE_SCHEMA
from framework.io.notes import iter_note_files, load_note_text
from framework.logging_utils import configure_logging
from workflows.hcc.v1.schemas.domain import NoteResult


logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the HCC extraction pipeline.")
    parser.add_argument("--notes-dir", default=None, help="Directory with progress notes.")
    parser.add_argument("--hcc-csv", default=None, help="Path to HCC reference CSV.")
    parser.add_argument("--output-dir", default=None, help="Output directory.")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM extraction.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of notes.")
    parser.add_argument("--max-workers", type=int, default=None, help="Parallel workers.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    args = parser.parse_args()

    configure_logging(args.log_level)

    pipeline_config = PipelineConfig.from_env()
    notes_dir = Path(args.notes_dir) if args.notes_dir else pipeline_config.notes_dir
    hcc_csv = Path(args.hcc_csv) if args.hcc_csv else pipeline_config.hcc_csv_path
    output_dir = Path(args.output_dir) if args.output_dir else pipeline_config.output_dir

    output_dir.mkdir(parents=True, exist_ok=True)

    lookup = HccCodeLookup.from_csv(hcc_csv)
    evaluator_settings = {
        "enable_fuzzy_match": pipeline_config.enable_fuzzy_match,
        "fuzzy_threshold": pipeline_config.fuzzy_match_threshold,
    }

    use_llm = not args.no_llm
    thread_local = threading.local()

    def build_app() -> Any:
        evaluator = HccEvaluator(lookup, **evaluator_settings)
        if use_llm:
            logger.info("Using LLM-based condition extraction")
            vertex_config = VertexAIConfig.from_env()
            client = VertexGeminiClient(vertex_config, response_schema=RESPONSE_SCHEMA)
            extractor = LLMConditionExtractor(
                client, fallback=RuleBasedConditionExtractor()
            )
        else:
            logger.info("Using rule-based condition extraction")
            extractor = RuleBasedConditionExtractor()
        return build_graph(extractor, evaluator)

    def get_app() -> Any:
        app = getattr(thread_local, "app", None)
        if app is None:
            app = build_app()
            thread_local.app = app
        return app

    note_paths = iter_note_files(notes_dir)
    if args.limit is not None:
        note_paths = note_paths[: args.limit]

    def process_note(note_path: Path) -> NoteResult:
        note_id = note_path.name
        logger.info("Processing %s", note_id)
        try:
            note_text = load_note_text(note_path)
            state = {
                "note_id": note_id,
                "note_text": note_text,
                "assessment_plan": "",
                "conditions": [],
                "errors": [],
            }
            result_state = get_app().invoke(state)
            note_result = NoteResult(
                note_id=note_id,
                source_file=str(note_path),
                assessment_plan=result_state.get("assessment_plan", ""),
                conditions=result_state.get("conditions", []),
                errors=result_state.get("errors", []),
            )
        except Exception as exc:
            logger.exception("Failed processing %s: %s", note_id, exc)
            note_result = NoteResult(
                note_id=note_id,
                source_file=str(note_path),
                assessment_plan="",
                conditions=[],
                errors=["note_processing_failed"],
            )

        _write_note_result(output_dir / f"{note_id}.json", note_result)
        return note_result

    max_workers = args.max_workers if args.max_workers is not None else pipeline_config.max_workers
    if max_workers < 1:
        max_workers = 1

    results: list[NoteResult] = []
    if max_workers == 1:
        for note_path in note_paths:
            results.append(process_note(note_path))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_note, note_path): note_path for note_path in note_paths}
            for future in as_completed(futures):
                results.append(future.result())

    results.sort(key=lambda result: result.note_id)

    _write_summary_csv(output_dir / "summary.csv", results)

    logger.info("Processed %d notes. Output: %s", len(results), output_dir)
    return 0


def _write_note_result(path: Path, result: NoteResult) -> None:
    payload = result.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_summary_csv(path: Path, results: list[NoteResult]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "note_id",
                "condition",
                "icd10_code",
                "icd10_description",
                "clinical_status",
                "severity",
                "confidence",
                "hcc_relevant",
                "hcc_code",
                "hcc_description",
                "match_method",
            ]
        )
        for result in results:
            for condition in result.conditions:
                hcc_match = condition.hcc_match
                writer.writerow(
                    [
                        result.note_id,
                        condition.condition,
                        condition.icd10_code or "",
                        condition.icd10_description or "",
                        condition.clinical_status or "",
                        condition.severity or "",
                        condition.confidence or "",
                        condition.hcc_relevant,
                        hcc_match.code if hcc_match else "",
                        hcc_match.description if hcc_match else "",
                        condition.match_method or "",
                    ]
                )


if __name__ == "__main__":
    raise SystemExit(main())
