# KFinAgent

[🇰🇷 한국어](README.md) | [🇺🇸 English](README.en.md)

Multi-agent research and analysis tooling for Korean equities. The project combines data collection, technical and news analysis, risk review, and reporting into a research workflow.

## Main components

- `tradingagents/`: analysis agents and LLM clients
- `services/kronos_api/`: Kronos integration API service
- `scripts/`: benchmark, research, reporting, and audit helpers
- `assets/`: agent-role and CLI example images

## Run

```bash
pip install -r requirements.txt
python main.py
```

Configure external data-provider and LLM credentials through the repository configuration and environment variables. This project is for research and does not constitute investment advice.
