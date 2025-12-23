from __future__ import annotations

import csv
import difflib
from pathlib import Path
from typing import Dict, Optional

from workflows.hcc.v1.schemas.domain import Condition, HccMatch
from workflows.hcc.v1.nodes.text_utils import normalize_description, normalize_icd10_code


_DESCRIPTION_STOP_TOKENS = {
    "unspecified",
    "other",
    "with",
    "without",
    "due",
    "to",
    "of",
    "and",
    "the",
    "in",
    "on",
    "for",
}


def _meaningful_tokens(text: str) -> set[str]:
    tokens = [token for token in text.split() if token]
    filtered = [
        token
        for token in tokens
        if token not in _DESCRIPTION_STOP_TOKENS and len(token) > 2
    ]
    if filtered:
        return set(filtered)
    return {token for token in tokens if token not in _DESCRIPTION_STOP_TOKENS}


def _description_match_score(
    description: str,
    candidate_description: str,
    min_overlap: float,
    min_similarity: float,
) -> float | None:
    if not description or not candidate_description:
        return None

    desc_tokens = _meaningful_tokens(description)
    cand_tokens = _meaningful_tokens(candidate_description)
    if not desc_tokens or not cand_tokens:
        return None

    overlap = desc_tokens & cand_tokens
    if not overlap:
        return None

    overlap_ratio = len(overlap) / min(len(desc_tokens), len(cand_tokens))
    similarity = difflib.SequenceMatcher(None, description, candidate_description).ratio()
    if overlap_ratio < min_overlap and similarity < min_similarity:
        return None

    return overlap_ratio * 0.7 + similarity * 0.3


class HccCodeLookup:
    def __init__(self, code_map: Dict[str, HccMatch], desc_map: Dict[str, HccMatch]):
        self._code_map = code_map
        self._desc_map = desc_map
        self._desc_keys = list(desc_map.keys())
        self._desc_keys_by_initial: dict[str, list[str]] = {}
        for key in self._desc_keys:
            initial = key[:1]
            self._desc_keys_by_initial.setdefault(initial, []).append(key)
        self._code_prefix_map: dict[str, list[HccMatch]] = {}
        for code, match in code_map.items():
            for prefix_len in (3, 4):
                if len(code) >= prefix_len:
                    prefix = code[:prefix_len]
                    self._code_prefix_map.setdefault(prefix, []).append(match)

    @classmethod
    def from_csv(cls, csv_path: Path) -> "HccCodeLookup":
        if not csv_path.exists():
            raise FileNotFoundError(f"HCC code CSV not found: {csv_path}")

        code_map: Dict[str, HccMatch] = {}
        desc_map: Dict[str, HccMatch] = {}

        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                code = normalize_icd10_code(row.get("ICD-10-CM Codes"))
                description = (row.get("Description") or "").strip()
                tags = (row.get("Tags") or "").strip() or None
                if not code:
                    continue

                match = HccMatch(code=code, description=description, tags=tags)
                code_map[code] = match

                desc_key = normalize_description(description)
                if desc_key and desc_key not in desc_map:
                    desc_map[desc_key] = match

        return cls(code_map=code_map, desc_map=desc_map)

    def match_by_code(self, code: str | None) -> Optional[HccMatch]:
        key = normalize_icd10_code(code)
        if not key:
            return None
        return self._code_map.get(key)

    def match_by_description(self, description: str | None) -> Optional[HccMatch]:
        key = normalize_description(description)
        if not key:
            return None
        return self._desc_map.get(key)

    def match_by_description_partial(self, description: str | None) -> Optional[HccMatch]:
        key = normalize_description(description)
        if not key:
            return None
        if len(key.split()) < 2:
            return None

        candidates: dict[str, HccMatch] = {}
        for desc_key, match in self._desc_map.items():
            if key in desc_key or desc_key in key:
                candidates[match.code] = match

        if len(candidates) == 1:
            return next(iter(candidates.values()))
        return None

    def match_by_description_fuzzy(
        self, description: str | None, cutoff: float
    ) -> Optional[HccMatch]:
        key = normalize_description(description)
        if not key:
            return None
        if len(key) < 6 or len(key.split()) < 2:
            return None

        candidates = self._desc_keys_by_initial.get(key[:1], self._desc_keys)
        matches = difflib.get_close_matches(key, candidates, n=2, cutoff=cutoff)
        if not matches:
            return None
        if len(matches) == 1:
            return self._desc_map.get(matches[0])

        ratio1 = difflib.SequenceMatcher(None, key, matches[0]).ratio()
        ratio2 = difflib.SequenceMatcher(None, key, matches[1]).ratio()
        if ratio1 - ratio2 >= 0.05:
            return self._desc_map.get(matches[0])
        return None

    def match_by_code_prefix_and_description(
        self,
        code: str | None,
        description: str | None,
        min_overlap: float,
        min_similarity: float,
    ) -> Optional[HccMatch]:
        code_key = normalize_icd10_code(code)
        desc_key = normalize_description(description)
        if not code_key or not desc_key or len(code_key) < 3:
            return None

        prefixes = []
        if len(code_key) >= 4:
            prefixes.append(code_key[:4])
        prefixes.append(code_key[:3])

        best_match: Optional[HccMatch] = None
        best_score = 0.0
        seen_codes: set[str] = set()

        for prefix in prefixes:
            for match in self._code_prefix_map.get(prefix, []):
                if match.code in seen_codes:
                    continue
                seen_codes.add(match.code)
                candidate_key = normalize_description(match.description)
                score = _description_match_score(
                    desc_key, candidate_key, min_overlap, min_similarity
                )
                if score is None:
                    continue
                if score > best_score:
                    best_score = score
                    best_match = match

        return best_match


class HccEvaluator:
    def __init__(
        self,
        lookup: HccCodeLookup,
        enable_fuzzy_match: bool = True,
        fuzzy_threshold: float = 0.92,
    ) -> None:
        self._lookup = lookup
        self._enable_fuzzy_match = enable_fuzzy_match
        self._fuzzy_threshold = fuzzy_threshold
        self._prefix_overlap_threshold = 0.5
        self._prefix_similarity_threshold = 0.35

    def evaluate(self, conditions: list[Condition]) -> list[Condition]:
        for condition in conditions:
            code_match = self._lookup.match_by_code(condition.icd10_code)
            if code_match:
                condition.hcc_relevant = True
                condition.hcc_match = code_match
                condition.match_method = "code"
                if not condition.icd10_description:
                    condition.icd10_description = code_match.description
                continue

            desc_match = self._lookup.match_by_description(
                condition.icd10_description or condition.condition
            )
            if desc_match:
                condition.hcc_relevant = True
                condition.hcc_match = desc_match
                condition.match_method = "description_exact"
            else:
                desc_match = self._lookup.match_by_description_partial(
                    condition.icd10_description or condition.condition
                )
                if desc_match:
                    condition.hcc_relevant = True
                    condition.hcc_match = desc_match
                    condition.match_method = "description_partial"
                elif self._enable_fuzzy_match:
                    desc_match = self._lookup.match_by_description_fuzzy(
                        condition.icd10_description or condition.condition,
                        cutoff=self._fuzzy_threshold,
                    )
                    if desc_match:
                        condition.hcc_relevant = True
                        condition.hcc_match = desc_match
                        condition.match_method = "description_fuzzy"
                    else:
                        prefix_match = self._lookup.match_by_code_prefix_and_description(
                            condition.icd10_code,
                            condition.icd10_description or condition.condition,
                            min_overlap=self._prefix_overlap_threshold,
                            min_similarity=self._prefix_similarity_threshold,
                        )
                        if prefix_match:
                            condition.hcc_relevant = True
                            condition.hcc_match = prefix_match
                            condition.match_method = "code_prefix_fuzzy"
                        else:
                            condition.hcc_relevant = False
                            condition.match_method = None
                else:
                    condition.hcc_relevant = False
                    condition.match_method = None

            if condition.hcc_match and not condition.icd10_description:
                condition.icd10_description = condition.hcc_match.description

        return conditions
