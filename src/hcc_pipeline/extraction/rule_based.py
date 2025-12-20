from __future__ import annotations

import re
from typing import List

from hcc_pipeline.models import Condition
from hcc_pipeline.utils.conditions import extract_icd10_codes, find_description_for_code


BLOCK_START_RE = re.compile(r"^\s*\d+[\).]\s*")
STATUS_RE = re.compile(r"\b(stable|improving|worsening|unchanged|acute|chronic)\b", re.IGNORECASE)
SEVERITY_RE = re.compile(r"\b(mild|moderate|severe|end[- ]?stage)\b", re.IGNORECASE)


class RuleBasedConditionExtractor:
    def extract(self, assessment_text: str, note_id: str | None = None) -> List[Condition]:
        if not assessment_text.strip():
            return []

        lines = [line.rstrip() for line in assessment_text.splitlines()]
        blocks: list[list[str]] = []
        current: list[str] = []

        for line in lines:
            if BLOCK_START_RE.match(line):
                if current:
                    blocks.append(current)
                current = [line]
            elif current:
                current.append(line)

        if current:
            blocks.append(current)

        if not blocks:
            blocks = [lines]

        conditions: list[Condition] = []
        for block in blocks:
            block_text = " ".join(part.strip() for part in block if part.strip())
            if not block_text:
                continue

            first_line = block[0]
            first_line = BLOCK_START_RE.sub("", first_line).strip()
            condition_name = first_line

            for delim in [" - ", "-", ":"]:
                if delim in condition_name:
                    condition_name = condition_name.split(delim, 1)[0]
                    break

            condition_name = condition_name.strip(" -:")
            if not condition_name:
                continue

            status_match = STATUS_RE.search(block_text)
            clinical_status = status_match.group(1).lower() if status_match else None

            severity_match = SEVERITY_RE.search(block_text)
            severity = None
            if severity_match:
                severity_value = severity_match.group(1).lower()
                severity = "severe" if "end" in severity_value else severity_value

            codes = extract_icd10_codes(block_text)
            if not codes:
                conditions.append(
                    Condition(
                        condition=condition_name,
                        icd10_code=None,
                        icd10_description=None,
                        clinical_status=clinical_status,
                        severity=severity,
                    )
                )
                continue

            for code in codes:
                icd10_description = None
                for line in block:
                    icd10_description = find_description_for_code(line, code)
                    if icd10_description:
                        break
                if not icd10_description:
                    icd10_description = find_description_for_code(block_text, code)

                conditions.append(
                    Condition(
                        condition=condition_name,
                        icd10_code=code,
                        icd10_description=icd10_description,
                        clinical_status=clinical_status,
                        severity=severity,
                    )
                )

        return conditions
