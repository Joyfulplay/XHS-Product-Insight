# 项目结构草案

```text
XHS-Product-Insight/
├── README.md
├── PROJECT_STRUCTURE.md
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   └── product_insight_agent.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   └── logger.py
│   │   ├── data/
│   │   │   ├── crawlers/
│   │   │   │   ├── __init__.py
│   │   │   │   └── xhs_client.py
│   │   │   └── raw/
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── base.py
│   │   ├── preprocess/
│   │   │   ├── __init__.py
│   │   │   ├── cleaner.py
│   │   │   └── image_processor.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   └── request_models.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── llm_service.py
│   │   │   ├── persistence_service.py
│   │   │   └── pipeline_service.py
│   │   ├── storage/
│   │   │   ├── db/
│   │   │   └── objects/
│   │   └── main.py
│   ├── tests/
│   │   ├── test_agents.py
│   │   └── test_preprocess.py
│   └── requirements.txt
├── frontend/
│   └── README.md
└── LICENSE
```

## 说明

- `backend/app/data/crawlers/`：数据获取模块，负责抓取小红书内容与相关原始信息。
- `backend/app/preprocess/`：数据预处理模块，包括文本清洗、图片处理、去重和标准化。
- `backend/app/agents/`：AI Agent 相关逻辑，例如产品分析、结论生成等。
- `backend/app/services/`：连接 LLM、数据存储、业务编排的服务层。
- `backend/app/storage/`：用于永久化存储，例如数据库、对象存储、缓存文件。
- `frontend/`：独立前端目录，后续可以放 Vue / React / Next.js 等项目。
