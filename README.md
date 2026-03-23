# US Tech Layoff Intelligence Platform

## Question this project answers
*Which tech sectors are genuinely recovering from 2022–2025 layoffs, and which are still contracting — and what does that mean for job seekers right now?*

## Architecture
```
Layoffs.fyi + BLS JOLTS API
        ↓
   Python ingestion scripts
        ↓
   AWS S3 (raw data lake)
        ↓
   AWS Glue ETL job (clean + Parquet)
        ↓
   AWS Athena (SQL analysis layer)
        ↓
   AWS Lambda + EventBridge (weekly automation)
        ↓
   OpenAI API (AI-generated analyst memo)
        ↓
   Power BI Dashboard (published to Power BI Service)
```

## Tech stack
- **Cloud:** AWS (S3, Glue, Athena, Lambda, EventBridge, CloudWatch)
- **Language:** Python 3.12
- **BI tool:** Power BI Desktop + Power BI Service
- **AI layer:** OpenAI GPT-4o-mini
- **Data sources:** Layoffs.fyi, BLS JOLTS API

## Project structure
```
layoff-intelligence/
├── ingestion/          # Python scripts to fetch raw data
├── glue/               # AWS Glue ETL job
├── athena/queries/     # SQL analysis queries
├── lambda/             # Lambda handler (pipeline orchestrator)
├── ai/                 # OpenAI memo generator
├── powerbi/            # Power BI connection notes
└── docs/               # Architecture diagram + notes
```

## Setup
See docs/architecture.md for full setup instructions.

## Key findings
*(Updated weekly by automated pipeline)*

