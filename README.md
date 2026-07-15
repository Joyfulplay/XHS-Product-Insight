# XHS-Product-Insight

XHS-Product-Insight is a Python backend AI Agent project focused on product insight extraction from Xiaohongshu-style content. The system is designed to combine data acquisition, data preprocessing, multimodal analysis, and persistent storage into a unified backend pipeline.

## Project Overview

This project aims to build a backend service that can:

- collect product-related content from public sources;
- preprocess raw text and images;
- invoke LLM-based analysis for structured insights;
- store processed data and results for downstream use.

The current architecture is organized around a clear backend pipeline:

1. Data acquisition
2. Data preprocessing
3. LLM analysis
4. Persistence

## Core Design Goals

- modular backend design for easier maintenance and extension;
- support for multimodal inputs, especially text plus image content;
- a clean Service + Agent + Schema layering strategy;
- simple deployment entry point via `main.py`.

## Backend Project Structure

```text
backend/
├── app/
│   ├── api/
│   │   └── routes.py
│   ├── agents/
│   │   └── product_insight_agent.py
│   ├── core/
│   │   ├── config.py
│   │   └── logger.py
│   ├── data/
│   │   ├── crawlers/
│   │   │   └── xhs_client.py
│   │   └── raw/
│   ├── models/
│   │   └── base.py
│   ├── preprocess/
│   │   ├── cleaner.py
│   │   └── image_processor.py
│   ├── schemas/
│   │   └── request_models.py
│   ├── services/
│   │   ├── llm_service.py
│   │   ├── persistence_service.py
│   │   └── pipeline_service.py
│   ├── storage/
│   │   ├── db/
│   │   └── objects/
│   └── main.py
└── tests/
    ├── test_agents.py
    └── test_preprocess.py
```

## Module Responsibilities

- `api/`: exposes HTTP routes and API contracts for the backend.
- `agents/`: contains AI Agent logic used for product insight reasoning and synthesis.
- `core/`: runtime configuration, logging, shared settings, and environment handling.
- `data/`: raw data acquisition layer, such as crawlers or data connectors.
- `preprocess/`: text cleaning, image preprocessing, normalization, and multimodal preparation.
- `schemas/`: request and response data models.
- `services/`: business orchestration, LLM invocation, and persistence logic.
- `storage/`: persistent storage directory for database files, object storage, or local artifacts.

## Typical Execution Flow

1. the API receives a request;
2. the crawler or data acquisition component pulls source content;
3. the preprocessing layer cleans text and processes images;
4. the Agent or LLM service generates structured insight results;
5. the persistence service stores final output for future retrieval.

## Current Status

This repository currently provides the initial project layout and sample backend modules to support continued development. The frontend is intentionally not described in detail because the interface form has not yet been finalized.

## Development Notes

- the backend is expected to be implemented using Python;
- a FastAPI-style application entry point is provided through `backend/app/main.py`;
- the current codebase focuses on backend structure and example modules rather than full production deployment.

