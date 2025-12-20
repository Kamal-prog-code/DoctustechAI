import os
from pathlib import Path

import pytest

from hcc_pipeline.config import VertexAIConfig
from hcc_pipeline.evaluation.hcc import HccCodeLookup, HccEvaluator
from hcc_pipeline.extraction.llm import LLMConditionExtractor, VertexGeminiClient
from hcc_pipeline.extraction.rule_based import RuleBasedConditionExtractor
from hcc_pipeline.graph import build_graph
from hcc_pipeline.models import Condition
from hcc_pipeline.utils.conditions import post_process_conditions
from hcc_pipeline.utils.text import extract_assessment_plan, normalize_icd10_code


def _llm_env_ready() -> tuple[bool, str]:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("VERTEX_PROJECT_ID")
    if not project_id:
        return False, "Set GOOGLE_CLOUD_PROJECT or VERTEX_PROJECT_ID to run LLM tests."

    credentials = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials:
        return False, "Set GOOGLE_APPLICATION_CREDENTIALS to run LLM tests."

    if not Path(credentials).exists():
        return False, f"Credentials file not found: {credentials}"

    return True, ""


def _require_llm_env() -> None:
    ready, reason = _llm_env_ready()
    if not ready:
        pytest.skip(reason)


def test_extract_assessment_plan_basic():
    note = (
        "HPI stuff\n"
        "Assessment / Plan\n"
        "1. Diabetes - E11.9\n"
        "2. HTN - I10\n"
        "Return to Office\n"
        "Follow up in 3 months\n"
    )
    assessment = extract_assessment_plan(note)
    assert assessment.startswith("1. Diabetes")
    assert "Return to Office" not in assessment


def test_extract_assessment_plan_missing():
    assert extract_assessment_plan("No assessment here") == ""


def test_normalize_icd10_code():
    assert normalize_icd10_code("I50.22") == "I5022"
    assert normalize_icd10_code(" k21.9 ") == "K219"


def test_rule_based_extraction_with_codes():
    assessment = (
        "1) Substance use disorder moderate - F19.20\n"
        "2) HLD - E78.5\n"
        "3) GERD - K21.9\n"
        "4) CAD - I25.10\n"
        "5) IBD - K51.90\n"
    )
    extractor = RuleBasedConditionExtractor()
    conditions = extractor.extract(assessment)

    assert [c.condition for c in conditions] == [
        "Substance use disorder moderate",
        "HLD",
        "GERD",
        "CAD",
        "IBD",
    ]
    assert [c.icd10_code for c in conditions] == [
        "F19.20",
        "E78.5",
        "K21.9",
        "I25.10",
        "K51.90",
    ]


def test_rule_based_extraction_without_codes():
    assessment = (
        "1) Diabetes - A1c 7.5 in office.\n"
        "2) HTN - stable, continue current meds\n"
        "3) COPD - No issues\n"
    )
    extractor = RuleBasedConditionExtractor()
    conditions = extractor.extract(assessment)

    assert [c.condition for c in conditions] == ["Diabetes", "HTN", "COPD"]
    assert all(c.icd10_code is None for c in conditions)


def test_hcc_evaluation_by_code(tmp_path):
    csv_path = tmp_path / "hcc.csv"
    csv_path.write_text(
        "ICD-10-CM Codes,Description,Tags\nI5022,Chronic systolic heart failure,\n"
    )

    lookup = HccCodeLookup.from_csv(csv_path)
    evaluator = HccEvaluator(lookup)
    conditions = [Condition(condition="CHF", icd10_code="I50.22")]
    evaluator.evaluate(conditions)

    assert conditions[0].hcc_relevant is True
    assert conditions[0].hcc_match is not None
    assert conditions[0].hcc_match.code == "I5022"


def test_hcc_evaluation_by_description(tmp_path):
    csv_path = tmp_path / "hcc.csv"
    csv_path.write_text(
        "ICD-10-CM Codes,Description,Tags\nE1122,Type 2 diabetes mellitus with diabetic chronic kidney disease,\n"
    )

    lookup = HccCodeLookup.from_csv(csv_path)
    evaluator = HccEvaluator(lookup)
    conditions = [
        Condition(
            condition="Type 2 diabetes mellitus with diabetic chronic kidney disease",
            icd10_code=None,
            icd10_description=None,
        )
    ]
    evaluator.evaluate(conditions)

    assert conditions[0].hcc_relevant is True
    assert conditions[0].match_method == "description_exact"


def test_hcc_partial_match_with_abbreviation(tmp_path):
    csv_path = tmp_path / "hcc.csv"
    csv_path.write_text(
        "ICD-10-CM Codes,Description,Tags\nJ449,Chronic obstructive pulmonary disease, unspecified,\n"
    )

    lookup = HccCodeLookup.from_csv(csv_path)
    evaluator = HccEvaluator(lookup)

    conditions, _warnings = post_process_conditions(
        [Condition(condition="COPD", icd10_code=None, icd10_description=None)]
    )
    evaluator.evaluate(conditions)

    assert conditions[0].hcc_relevant is True
    assert conditions[0].match_method == "description_partial"
    assert conditions[0].icd10_description == "Chronic obstructive pulmonary disease, unspecified"


def test_llm_extractor_basic():
    _require_llm_env()
    config = VertexAIConfig.from_env()
    client = VertexGeminiClient(config)
    extractor = LLMConditionExtractor(client, fallback=None)

    assessment = "1) Hypertension - I10\n"
    conditions = extractor.extract(assessment, note_id="llm-basic")

    assert conditions
    assert any(c.icd10_code == "I10" for c in conditions)


def test_llm_graph_end_to_end(tmp_path):
    _require_llm_env()
    csv_path = tmp_path / "hcc.csv"
    csv_path.write_text(
        "ICD-10-CM Codes,Description,Tags\nI5022,Chronic systolic heart failure,\n"
    )

    lookup = HccCodeLookup.from_csv(csv_path)
    evaluator = HccEvaluator(lookup)

    config = VertexAIConfig.from_env()
    client = VertexGeminiClient(config)
    extractor = LLMConditionExtractor(client, fallback=None)

    app = build_graph(extractor, evaluator)
    note_text = (
        "HPI stuff\n"
        "Assessment / Plan\n"
        "1. Chronic systolic heart failure - I50.22\n"
        "Return to Office\n"
    )

    state = {
        "note_id": "pn_llm",
        "note_text": note_text,
        "assessment_plan": "",
        "conditions": [],
        "errors": [],
    }

    result = app.invoke(state)
    conditions = result.get("conditions", [])

    assert conditions
    assert any(c.hcc_relevant for c in conditions)


def test_post_process_conditions_dedupes_and_normalizes():
    conditions = [
        Condition(condition="Hypertension (I10)", icd10_code=None, icd10_description=None),
        Condition(
            condition="Hypertension",
            icd10_code="I10",
            icd10_description="Essential (primary) hypertension",
        ),
        Condition(condition="Hypertension", icd10_code="I10", icd10_description=None),
    ]

    processed, warnings = post_process_conditions(conditions)

    assert len(processed) == 1
    assert not warnings
    assert processed[0].condition == "Hypertension"
    assert processed[0].icd10_code == "I10"
    assert processed[0].icd10_description == "Essential (primary) hypertension"


def test_hcc_fuzzy_match(tmp_path):
    csv_path = tmp_path / "hcc.csv"
    csv_path.write_text(
        "ICD-10-CM Codes,Description,Tags\nN184,Chronic kidney disease, stage 4 (severe),\n"
    )

    lookup = HccCodeLookup.from_csv(csv_path)
    evaluator = HccEvaluator(lookup, enable_fuzzy_match=True, fuzzy_threshold=0.85)

    conditions = [Condition(condition="Chronic kidney disease stage four", icd10_code=None)]
    evaluator.evaluate(conditions)

    assert conditions[0].hcc_relevant is True
    assert conditions[0].match_method == "description_fuzzy"


def test_invalid_icd10_code_is_removed():
    conditions = [Condition(condition="Hypertension", icd10_code="INVALID")]

    processed, warnings = post_process_conditions(conditions)

    assert len(processed) == 1
    assert processed[0].icd10_code is None
    assert any(warning.startswith("invalid_icd10_code:") for warning in warnings)
