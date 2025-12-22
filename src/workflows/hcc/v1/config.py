from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from framework.utils.env import parse_bool_env


@dataclass(frozen=True)
class PipelineConfig:
    notes_dir: Path
    hcc_csv_path: Path
    output_dir: Path
    max_workers: int
    enable_fuzzy_match: bool
    fuzzy_match_threshold: float

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        notes_dir = Path(os.getenv("PROGRESS_NOTES_DIR", "progress_notes"))
        hcc_csv_path = Path(os.getenv("HCC_CODES_CSV", "HCC_relevant_codes.csv"))
        output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
        max_workers = int(os.getenv("PIPELINE_MAX_WORKERS", "1"))
        enable_fuzzy_match = parse_bool_env(os.getenv("HCC_ENABLE_FUZZY_MATCH", "true"))
        fuzzy_match_threshold = float(os.getenv("HCC_FUZZY_MATCH_THRESHOLD", "0.92"))
        return cls(
            notes_dir=notes_dir,
            hcc_csv_path=hcc_csv_path,
            output_dir=output_dir,
            max_workers=max_workers,
            enable_fuzzy_match=enable_fuzzy_match,
            fuzzy_match_threshold=fuzzy_match_threshold,
        )
