REPAIR_PROMPT_TEMPLATE = """You repair malformed JSON into valid JSON.
Return ONLY a JSON object matching this schema:
{{
  "conditions": [
    {{
      "condition": "string",
      "icd10_code": "string or null",
      "icd10_description": "string or null",
      "clinical_status": "string or null",
      "severity": "string or null",
      "confidence": "high|medium|low"
    }}
  ]
}}

If you cannot repair, return {{"conditions": []}}.

Raw response:
\"\"\"{raw}\"\"\"
"""
