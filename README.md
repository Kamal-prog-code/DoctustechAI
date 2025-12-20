# HCC Extraction Pipeline

This project reads clinical progress notes, finds the Assessment/Plan section, and extracts medical conditions with ICD-10 codes. It then checks those codes against `HCC_relevant_codes.csv` and produces:
- One JSON file per note (in `output/`)
- One summary CSV (in `output/summary.csv`)

## What you need (simple checklist)

- Docker installed
- A Google Cloud service account JSON file (for Vertex AI)
- A `.env` file with your settings

## Quick start (Docker, recommended)

1) Copy the example env file and fill it in:
```
cp .env.example .env
```
Open `.env` and replace placeholders like:
- `LANGSMITH_API_KEY`
- `GOOGLE_CLOUD_PROJECT`

2) Put your service account JSON in this folder and name it:
```
service_account.json
```

3) Build and run the pipeline:
```
docker build -t hcc-pipeline . && docker run --rm \
  --env-file .env \
  -v $(pwd)/service_account.json:/app/credentials/service_account.json:ro \
  -v $(pwd)/output:/app/output \
  hcc-pipeline
```

## Where to find results

- Per-note JSON files: `output/`
- Summary CSV: `output/summary.csv`

## Advanced settings (optional)

- `VERTEX_MODEL_NAME` (default `gemini-2.5-flash`) to switch model versions.
- `PIPELINE_MAX_WORKERS` to process notes in parallel (set >1 for faster runs).
- `HCC_ENABLE_FUZZY_MATCH` and `HCC_FUZZY_MATCH_THRESHOLD` to control fuzzy matching.
- `LLM_ENABLE_REPAIR` to auto-repair invalid JSON; `LLM_REPAIR_MAX_CHARS` limits repair prompt size.
- `LLM_USE_RESPONSE_SCHEMA` to request structured JSON output from Vertex.
- `LLM_LOG_VERBOSE` and `SUPPRESS_VERTEXAI_WARNINGS` to control log noise.

## Optional: run without the LLM (rule-based only)

```
docker build -t hcc-pipeline . && docker run --rm \
  --env-file .env \
  -e USE_LLM=false \
  -v $(pwd)/service_account.json:/app/credentials/service_account.json:ro \
  -v $(pwd)/output:/app/output \
  hcc-pipeline
```

## Optional: LangGraph Studio (visual UI)

Start the local dev server:
```
docker run --rm -p 2024:2024 \
  --env-file .env \
  -v $(pwd)/service_account.json:/app/credentials/service_account.json:ro \
  -v $(pwd)/output:/app/output \
  hcc-pipeline langgraph dev --host 0.0.0.0 --port 2024
```

Then open Studio at:
```
URL: https://smith.langchain.com/studio/?baseUrl=http://0.0.0.0:2024
```

## Local (non-Docker) run

If you prefer to run without Docker:
```
poetry install --with dev
poetry run hcc-pipeline
```

You still need the same env vars that are listed in `.env.example`.

## Successful logs looks like

```
karrekamal@Karres-MacBook-Air DoctusTech_AI_engineer_technical-test % docker build -t hcc-pipeline . && docker run --rm --env-file .env -v $(pwd)/service_account.json:/app/credentials/service_account.json:ro -v $(pwd)/output:/app/output hcc-pipeline

[+] Building 3.6s (16/16) FINISHED                       docker:desktop-linux
 => [internal] load build definition from Dockerfile                     0.0s
 => => transferring dockerfile: 633B                                     0.0s
 => [internal] load metadata for docker.io/library/python:3.11-slim      2.1s
 => [internal] load .dockerignore                                        0.0s
 => => transferring context: 2B                                          0.0s
 => [ 1/11] FROM docker.io/library/python:3.11-slim@sha256:158caf0e080e  0.0s
 => => resolve docker.io/library/python:3.11-slim@sha256:158caf0e080e2c  0.0s
 => [internal] load build context                                        0.0s
 => => transferring context: 7.06kB                                      0.0s
 => CACHED [ 2/11] WORKDIR /app                                          0.0s
 => CACHED [ 3/11] RUN pip install --no-cache-dir "poetry==1.8.3"        0.0s
 => CACHED [ 4/11] COPY pyproject.toml poetry.lock* /app/                0.0s
 => CACHED [ 5/11] RUN poetry install --with dev --no-root               0.0s
 => [ 6/11] COPY src /app/src                                            0.0s
 => [ 7/11] COPY progress_notes /app/progress_notes                      0.0s
 => [ 8/11] COPY HCC_relevant_codes.csv /app/HCC_relevant_codes.csv      0.0s
 => [ 9/11] COPY langgraph.json /app/langgraph.json                      0.0s
 => [10/11] COPY README.md /app/README.md                                0.0s
 => [11/11] RUN poetry install --with dev                                1.2s
 => exporting to image                                                   0.2s
 => => exporting layers                                                  0.1s
 => => exporting manifest sha256:94cfc11bcc948a9f47f84149b59861c7cdcc54  0.0s
 => => exporting config sha256:2220f8f35e3fbfb30250ffa4f0886933c7383230  0.0s
 => => exporting attestation manifest sha256:72218fe0d4d21decf439acde00  0.0s
 => => exporting manifest list sha256:573139f10bf2a0623f33d358c65621a94  0.0s
 => => naming to docker.io/library/hcc-pipeline:latest                   0.0s
 => => unpacking to docker.io/library/hcc-pipeline:latest                0.0s

View build details: docker-desktop://dashboard/build/desktop-linux/desktop-linux/tpr265q4l4t1a6rdufet103gn
Skipping virtualenv creation, as specified in config file.
/usr/local/lib/python3.11/site-packages/vertexai/generative_models/_generative_models.py:433: UserWarning: This feature is deprecated as of June 24, 2025 and will be removed on June 24, 2026. For details, see https://cloud.google.com/vertex-ai/generative-ai/docs/deprecations/genai-vertexai-sdk.
  warning_logs.show_deprecation_warning()
2025-12-20 05:51:35,580 INFO hcc_pipeline.cli: Processing pn_1
2025-12-20 05:51:40,654 INFO hcc_pipeline.cli: Processing pn_2
2025-12-20 05:51:44,744 INFO hcc_pipeline.cli: Processing pn_3
2025-12-20 05:51:48,716 INFO hcc_pipeline.cli: Processing pn_4
2025-12-20 05:51:52,435 INFO hcc_pipeline.cli: Processing pn_5
2025-12-20 05:51:56,600 INFO hcc_pipeline.cli: Processing pn_6
2025-12-20 05:51:59,576 INFO hcc_pipeline.cli: Processing pn_7
2025-12-20 05:52:02,529 INFO hcc_pipeline.cli: Processing pn_8
2025-12-20 05:52:06,535 INFO hcc_pipeline.cli: Processing pn_9
2025-12-20 05:52:11,104 INFO hcc_pipeline.cli: Processed 9 notes. Output: output
```
