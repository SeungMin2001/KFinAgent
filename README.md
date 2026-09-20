# KFinAgent

[🇰🇷 한국어](README.md) | [🇺🇸 English](README.en.md)

한국 주식 리서치와 분석을 위한 멀티 에이전트 기반 프로젝트입니다. 데이터 수집, 기술적 분석, 뉴스 분석, 리스크 검토, 리포팅 흐름을 하나의 연구 파이프라인으로 구성합니다.

## 주요 구성

- `tradingagents/`: 분석 에이전트와 LLM 클라이언트
- `services/kronos_api/`: Kronos 연동 API 서비스
- `scripts/`: 벤치마크, 리서치, 리포트·감사 보조 스크립트
- `assets/`: 에이전트 역할과 CLI 예시 이미지

## 실행

의존성을 설치한 뒤 환경 변수를 설정하고 실행하세요.

```bash
pip install -r requirements.txt
python main.py
```

외부 데이터 제공자와 LLM 제공자의 키·설정은 저장소의 구성 파일 및 환경 변수 안내를 따릅니다. 투자 판단은 사용자의 책임이며, 이 프로젝트의 출력은 투자 조언이 아닙니다.

