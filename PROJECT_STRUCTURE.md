# 项目结构

```text
XHS-Product-Insight/
├── README.md
├── PROJECT_STRUCTURE.md
├── requirements.txt
├── backend/
│   ├── main.py
│   ├── app/
│   │   ├── api/
│   │   │   ├── routes.py
│   │   │   └── xhs_connector.py
│   │   ├── data/
│   │   │   └── crawlers/
│   │   │       └── xhs_client.py
│   │   ├── LLM/
│   │   │   ├── client.py
│   │   │   └── service.py
│   │   ├── preprocess/
│   │   │   ├── cleaner.py
│   │   │   └── image_processor.py
│   │   ├── schemas/
│   │   │   ├── analysis_result.py
│   │   │   ├── cleaned_note.py
│   │   │   ├── crawler.py
│   │   │   └── llmoutput.py
│   │   └── services/
│   │       ├── analysis_pipeline.py
│   │       └── persistence_service.py
│   ├── run_eda.py
│   └── tests/
└── extension/
    ├── mocks/
    ├── scripts/
    ├── src/
    │   ├── api/
    │   ├── analysis_view_model.ts
    │   ├── collection_flow.ts
    │   ├── config.ts
    │   ├── content.ts
    │   ├── product_page.ts
    │   └── sidepanel.ts
    ├── .env.local
    ├── manifest.json
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    └── vite.content.config.ts
```

## 说明

- `backend/main.py`：FastAPI 入口，挂载本地 API 与跨域配置。
- `backend/app/api/xhs_connector.py`：浏览器插件调用的接口层，提供小红书登录状态、采集任务、进度查询和结果查询。
- `backend/app/data/crawlers/`：小红书本地采集模块，读取本机登录状态并采集公开笔记与评论。
- `backend/app/preprocess/`：数据预处理模块，包括文本清洗、图片处理、去重和标准化。
- `backend/app/schemas/`：Pydantic 数据契约，约束采集结果、清洗后笔记和分析结果结构。
- `backend/app/services/analysis_pipeline.py`：后端分析编排，负责统计分析、可选 OpenAI 洞察生成和结果组装。
- `backend/app/services/persistence_service.py`：结果持久化服务，保存和读取采集分析结果。
- `extension/`：浏览器插件前端，负责识别淘宝/天猫商品页、调用 `/api/v1/xhs/collections`、轮询任务并展示结果。
