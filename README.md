# Korean STOCK

한국 주식시장을 위한 멀티 에이전트 리서치 워크벤치입니다. 실제 주문을 내지 않으며, KIS 시세·수급, DART 공시, 미국 및 한국 거시 지표를 근거로 분석 리포트를 만듭니다.

> 투자 조언이나 자동 매매 도구가 아닙니다. 결과는 조사와 검토를 돕는 참고 자료입니다.

## 지금 되는 것

- KIS Open API로 KRX 일봉·기술지표·외국인/기관 수급을 실제 조회
- OpenDART 공시 원문을 수집하고 공시 분석 에이전트에 전달
- FRED의 미국 금리·CPI 등 7개 지표와 한국은행 ECOS 지표를 시점 기준으로 수집
- 시장·공시·거시·수급 분석 에이전트, 상승/하락 토론, 리스크 검토와 최종 리포트
- 실행 근거를 `0_evidence.md`에 별도로 저장
- Kronos 시계열 모델을 별도 GPU API로 연결할 수 있는 인터페이스와 컨테이너 서버 초안

## 빠른 시작

```bash
bash scripts/bootstrap_local_env.sh
~/.virtualenvs/stock-<Mac-name>-py312/bin/python \\
  scripts/korean_stock_research.py 005930 \\
  --date 2026-09-02 --enhanced --verbose
```

실행 전 `.env.example`을 `.env`로 복사해 필요한 API 키를 넣는다. API 연결에 실패하면 샘플 데이터로 대체하지 않고 실행을 중단한다.

필수 키:

```text
KIS_APP_KEY=
KIS_APP_SECRET=
OPENAI_API_KEY=
DART_API_KEY=
FRED_API_KEY=
ECOS_API_KEY=
```

상세 구조와 실행 방법은 [한국 시장 MVP 문서](docs/KOREA_MVP.md), Kronos 배포는 [RunPod 문서](docs/KRONOS_RUNPOD.md)를 참고한다.

## 분석 흐름

```text
KIS / DART / FRED / ECOS
          ↓
시장 · 공시 · 거시 · 수급 근거 분석
          ↓
상승 · 하락 관점 토론 → 리스크 검토 → 최종 리서치 리포트
```

## 라이선스와 출처

이 프로젝트는 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)의 Apache-2.0 라이선스 코드를 기반으로 한국 시장 데이터 소스와 분석 흐름을 확장한 파생 프로젝트다. 원저작권 및 Apache-2.0 라이선스 고지는 [LICENSE](LICENSE)와 [NOTICE](NOTICE)에 유지한다.
