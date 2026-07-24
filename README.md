# XHS-Product-Insight

XHS-Product-Insight is a browser-extension-based product insight project. It identifies products from Taobao or Tmall pages, collects related Xiaohongshu notes and comments, and transforms unstructured user content into clear product insights through data cleaning, statistical analysis, and LLM-based information extraction.

> Taobao and Tmall are used only for product identification.  
> All review analysis data comes from Xiaohongshu notes and comments.

## Project Overview

Online product content often contains duplicated information, irrelevant discussion, promotional language, and scattered opinions. This project aims to organize Xiaohongshu content into structured and understandable insights that support users' purchase decisions.

The overall workflow is:

```text
Taobao/Tmall product page
        ↓
Product information extraction
        ↓
Xiaohongshu keyword generation
        ↓
Xiaohongshu notes and comments collection
        ↓
Data desensitization and cleaning
        ↓
LLM-based information extraction
        ↓
Structured data and statistical analysis
        ↓
Visualization and product insights
```

The final analysis is designed to include:

- collection statistics;
- product attributes;
- usage scenarios;
- target user groups;
- frequently mentioned advantages and disadvantages;
- high-frequency keywords;
- sentiment and risk distribution;
- representative Xiaohongshu content;
- personalized purchase recommendations.

## Data Source Scope

### Taobao and Tmall

Taobao and Tmall pages provide basic product information such as:

- product title;
- brand and model, when available;
- product ID;
- product URL;
- platform source.

Taobao and Tmall reviews are not used in the review-analysis results.

### Xiaohongshu

Xiaohongshu is the only source of review-analysis data. The planned collection data includes:

- note titles and text;
- tags and publication time;
- anonymized author identifiers;
- engagement statistics;
- comments;
- collection metadata.

## System Components

| Component | Responsibility |
|---|---|
| Browser extension | Recognize products, accept user settings, start tasks, show progress, and display results |
| Local crawler connector | Handle Xiaohongshu login, collect notes and comments, manage asynchronous tasks, and return desensitized structured data |
| Analysis backend | Clean data, calculate statistics, optionally invoke the LLM, apply preference-based scoring, and generate product insights |

The current integration uses the collection API as the end-to-end contract. After a collection job succeeds, `/api/v1/xhs/collections/{job_id}/result` returns the collected Xiaohongshu content together with normalized analysis fields for the browser extension. A separate `/analysis` job API has not been added.

## Browser Extension

The extension is currently designed for Taobao and Tmall product pages. Its responsibilities include:

- detecting the current product page;
- extracting available product information;
- generating a default Xiaohongshu search query;
- allowing the user to edit the query;
- configuring collection limits;
- checking the local service status;
- starting login and collection tasks;
- polling asynchronous task progress;
- previewing structured collection data;
- displaying Xiaohongshu-only analysis results;
- applying user preference weights to scoring and ranking.

The extension remains lightweight: it does not perform the crawler's login process, store authentication credentials, or run the complete LLM analysis pipeline itself.

## Data Flow

1. The user opens a supported Taobao or Tmall product page.
2. The extension extracts the product information and generates a Xiaohongshu search query.
3. The user may edit the query and collection limits.
4. The extension starts a login or collection task through the local connector.
5. The connector collects Xiaohongshu notes and comments and removes sensitive information.
6. The extension polls the task and then retrieves the collection result.
7. The backend cleans the data, performs statistical analysis, optionally extracts insights with an LLM, and stores the result.
8. The extension displays the final results and representative Xiaohongshu content.

## Local Crawler Connector

During development, the local service is expected to use:

```text
http://127.0.0.1:8000
```

Login and collection may take time, so both operations should run as asynchronous jobs. The connector should return a `job_id`, and the extension should poll for status instead of keeping one HTTP request open.

The current interface contract is:

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/xhs/auth/login` | Start a Xiaohongshu login task |
| `GET` | `/api/v1/xhs/auth/login/{job_id}` | Query the login task |
| `GET` | `/api/v1/xhs/auth/status` | Query the current login status |
| `POST` | `/api/v1/xhs/collections` | Start a collection task |
| `GET` | `/api/v1/xhs/collections/{job_id}` | Query collection progress |
| `GET` | `/api/v1/xhs/collections/{job_id}/result` | Retrieve the desensitized collection result and analysis fields |

### Run the Local Backend

The local FastAPI service provides the extension-facing API, Xiaohongshu collection connector, persistence, and analysis pipeline.

For Windows users, the easiest way is to double-click:

```text
Start-XHS-Backend.bat
```

This launcher opens WSL, prepares the Python virtual environment, installs backend dependencies, and starts FastAPI at `http://127.0.0.1:8000`. Keep the launcher window open while using the browser extension.

For development or debugging, the equivalent WSL command is:

```bash
cd ~/XHS-Product-Insight
source venv/bin/activate
export PYTHONPATH=$(pwd)/backend:$PYTHONPATH
uvicorn main:app --reload --app-dir backend --host 127.0.0.1 --port 8000
```

It keeps task state in memory, so restarting the service clears prior job IDs. The login-status endpoint confirms that the required local cookie fields are present; an expired server-side session is reported by a later collection task as `AUTH_REQUIRED`.

The collection endpoint receives a product keyword or page-derived source:

```json
{
  "source": "Sony WH-1000XM5"
}
```

User preference weights belong to the frontend scoring layer and are not required by the collection endpoint.

## Structured Raw Data

The connector and analysis pipeline return desensitized structured data rather than cookies, headers, or an unprocessed command-line dump. A high-level example of the collection portion is:

```json
{
  "schema_version": "1.1",
  "collected_at": "2026-07-22T00:00:00Z",
  "input": {
    "source": "keyword",
    "query": "product keyword"
  },
  "collection": {
    "note_count": 10,
    "comment_count": 120
  },
  "notes": [
    {
      "title": "Example note title",
      "text": "Example note content",
      "tags": ["product", "review"],
      "publish_time": "2026-07-20T00:00:00Z",
      "author_id_hash": "anonymized-author-id",
      "engagement": {
        "likes": 0,
        "collects": 0,
        "comments": 0,
        "shares": 0
      },
      "comments": []
    }
  ],
  "errors": []
}
```

The exact schema should be versioned and shared by the connector, analysis backend, and extension.
Here, `input.source` is `keyword` for a direct product-name search and `taobao_or_tmall` for a product-link search.

## Data Security

Sensitive authentication data must be removed before crawler results reach the extension or analysis backend.

The system must not expose, store, or log:

- cookies or request headers;
- `a1`;
- `web_session`;
- `webId`;
- `xsec_token`;
- `xsec_source`;
- QR-code authentication credentials;
- authenticated URLs containing sensitive query parameters.

Only publicly available content should be collected. Data acquisition and processing must comply with applicable laws, privacy requirements, research-ethics requirements, platform rules, and reasonable rate limits.

## Mock and Real Modes

The extension supports both Mock mode and Real mode.

### Mock Mode

Mock mode simulates service connection, login, asynchronous collection, progress updates, structured data, and analysis results. Mock content must be clearly identified and must follow the Xiaohongshu-only review scope.

### Real Mode

Real mode connects to the local service. A real request failure should be shown clearly to the user and must not be silently replaced by a successful Mock result.

The repository currently tracks `extension/.env.local` with:

```env
VITE_USE_MOCK=false
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

## Project Structure

The confirmed project structure includes:

```text
XHS-Product-Insight/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── data/crawlers/
│   │   ├── LLM/
│   │   ├── preprocess/
│   │   ├── schemas/
│   │   └── services/
│   ├── main.py
│   └── tests/
├── extension/
│   ├── mocks/
│   ├── scripts/
│   ├── src/
│   ├── manifest.json
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── requirements.txt
└── README.md
```

## Run the Browser Extension

### Prerequisites

- Node.js 18 or later;
- npm;
- Google Chrome or Microsoft Edge.

Enter the extension directory and install dependencies:

```bash
cd extension
npm install
```

Run type checking:

```bash
npm run typecheck
```

Build the extension:

```bash
npm run build
```

After the build succeeds:

1. Open `chrome://extensions` or `edge://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Choose the generated `extension/dist` directory.
5. Open a supported Taobao or Tmall product page.
6. Refresh the page and open the extension side panel.

After changing extension code, rebuild the project and reload the unpacked extension.

## Current Status

### Available

- browser extension foundation;
- Taobao and Tmall page support;
- product information extraction;
- Mock service and analysis flows;
- editable Xiaohongshu search query;
- user preference settings, scoring, and ranking;
- Xiaohongshu-only result presentation;
- TypeScript type checking and production build scripts;
- local asynchronous Xiaohongshu login and collection connector;
- connector-side result-schema normalization and sensitive-field removal;
- FastAPI collection/result endpoints used by the extension;
- backend persistence for collection results;
- statistical analysis and optional OpenAI-based insight generation.

### In Progress

- unified task states and error codes;
- frontend result-field polishing for real collection results;
- end-to-end stability testing against Xiaohongshu rate limits and safety checks.

### Planned

- spam and promotional-content detection;
- multimodal analysis where applicable;
- personalized purchase recommendations;
- broader end-to-end testing.

## Known Limitations

- The project is not yet production-ready.
- Mock mode is still available for frontend-only demos, but real mode calls the local FastAPI service.
- Product extraction may be affected by changes to Taobao or Tmall page structures.
- Collection depends on a running local connector and a valid Xiaohongshu login state.
- Xiaohongshu may require safety verification or rate-limit requests; the crawler stops instead of trying to bypass these checks.
- LLM-generated conclusions may require human validation and should not be treated as guaranteed facts.

## Disclaimer

This project is intended for educational and research purposes. It must not be used to bypass access controls, collect private content, expose authentication credentials, or perform unauthorized large-scale data acquisition.

## License

A license has not yet been specified.
