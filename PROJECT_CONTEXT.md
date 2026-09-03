# Korean Stock Research Agent — Project Context

이 파일은 다른 컴퓨터에서 Codex 작업을 이어갈 때 읽는 단일 인수인계 문서다.
API 키·토큰·개인정보는 절대 기록하지 않는다.

## 목표

한국 주식 리서치 Agent를 만든다. 주문 자동화는 범위 밖이다. 결과는 투자 판단을 보조하는 리서치이며, 매수·매도 명령이 아니다.

핵심 구성은 다음과 같다.

- TradingAgents: 역할 기반 분석·상승/하락 토론·리스크 토론·최종 판단 워크플로
- KIS Open API: 국내주식 일봉·기술지표·투자자별 수급
- OpenDART: 한국 기업 공시
- FRED: 미국 금리·물가·국채·달러·VIX
- 한국은행 ECOS: 한국 금리·국채·물가 보조 지표
- Kronos: RunPod GPU API로 배포한 캔들 시계열 예측 모델

## 현재 구현 상태

### 이미 동작·실검증한 것

- KIS 실전 API로 일봉 OHLCV·기술지표 조회
- KIS 연결 실패 시 분석을 시작하지 않는 엄격한 사전 검증
- OpenDART 최근 공시 조회, 올바른 KRX 종목코드 → DART 고유번호 매핑, 원문 ZIP/XML 전체 본문 추출
- 최근 공시는 기본 3건을 조회하며, 선택된 3건의 원문 visible text를 Disclosure Agent에 전달
- FRED 7개 미국 거시 시계열을 분석일 당시 vintage로 조회
- ECOS StatisticSearch로 한국 기준금리·국고채·CPI·근원 CPI를 분석일 이전 관측치로 조회
- KIS 종목별 투자자 수급: 외국인·기관계·투자신탁·기금
- Kronos API 서버 골격과 모델 지연 로딩, API 키 인증, health endpoint, 모델 없는 계약 테스트
- Kronos 클라이언트의 `disabled`/`local`/`remote` 모드, 원격 HTTPS 강제, API 키·입력 기준일·응답 계약 검증
- `--enhanced` 모드에서 위 근거를 하나의 source-attributed snapshot으로 수집
- `--enhanced`에서 Disclosure/Macro/Flow Evidence Analyst가 병렬로 각자 배정된 snapshot 구간만 구조화함
- `--enhanced --kronos-mode remote`는 사전 검증에 사용한 동일 KIS 캔들을 중복 조회 없이 Kronos에 보내고, Time-Series Forecast Evidence Analyst를 병렬 추가함
- 네 Evidence Agent는 매매 의견을 내지 않고 수치·기간·출처·결측·한계를 전달함
- Market Agent는 KIS 가격·기술지표와 네 Evidence report를 받아 충돌을 종합함
- 실행 중 진행 단계 출력, `--verbose`일 때 각 Agent 출력 표시
- 완료된 리포트마다 `0_evidence.md` 생성
- 보고서에 검증된 KIS 캔들·거래량·RSI·Kronos 중앙 예측 경로/최종 p10-p90 범위를 담은 `visuals/market_overview.svg` 생성
- 차트와 동일한 원천 캔들의 결정론적 요약을 Market Agent에 텍스트로 제공한다. 현재 Agent는 이미지 자체를 읽는 Vision 방식이 아니다.

### 아직 미완성인 것

- 공시 유형별 구조화 API를 추가 활용해 원문 자유 텍스트 추출 결과와 교차검증
- 워크포워드 백테스트와 Kronos 기여도 평가
- GitHub 공개용 정리·CI·배포 자동화

## 실행 방법

프로젝트 루트에서 실행한다.

```bash
bash scripts/bootstrap_local_env.sh
~/.virtualenvs/stock-<Mac-name>-py312/bin/python scripts/korean_stock_research.py 005930 --date 2026-09-02 --enhanced --kronos-mode remote --verbose
```

- `005930`: KRX 6자리 종목코드
- `--enhanced`: DART + FRED + ECOS + KIS 수급을 필수 수집. 한 출처라도 실패하면 분석 시작 안 함.
- `--verbose`: Agent별 분석·토론 출력을 터미널에 표시

출력은 `artifacts/reports/<종목>_<시각>/`에 저장된다.

- `0_evidence.md`: 모든 원천 근거와 Agent 전달 경로
- `1_analysts/market.md`: 통합 시장 분석
- `1_analysts/disclosure.md`, `macro.md`, `flow.md`: 출처별 객관적 Evidence report
- `1_analysts/kronos.md`: 모델 입력 캔들 요약·예측 범위·불확실성을 분리한 시계열 Evidence report
- `2_research/`: Bull/Bear/Manager 토론
- `3_trading/`, `4_risk/`, `5_portfolio/`: 최종 판단 과정
- `complete_report.md`: 통합 리포트

## 환경변수

`.env`에만 보관하며 Git에 올리지 않는다.

```env
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ENV=real
OPENAI_API_KEY=
DART_API_KEY=
ECOS_API_KEY=
FRED_API_KEY=

# RunPod Kronos 배포 후 추가
KRONOS_MODE=disabled
KRONOS_API_URL=
KRONOS_API_KEY=
```

KIS 접근토큰은 분당 1회 발급 제한이 있다. 연속 실행에서 `EGW00133`이 나오면 1분 후 재시도한다.

## 중요한 설계 결정

- Kubernetes는 지금 사용하지 않는다. 1차 배포는 **Docker + RunPod 지속 GPU Pod + FastAPI**다.
- Kronos는 최종 매매 신호가 아니라 확률적 보조 근거다.
- Kronos 선택은 `--kronos`/`--require-kronos` 두 옵션으로 중복시키지 않고 `--kronos-mode {disabled,local,remote}` 하나로 제공한다.
- `local` 또는 `remote`를 사용자가 명시하면 Kronos 실패 시 조용히 제외하지 않고 전체 분석을 중단한다. 기본값은 `disabled`다.
- `local`은 로컬 HTTP API, `remote`는 RunPod 등 HTTPS API다. 두 모드 모두 API 키 인증을 사용한다.
- 매크로는 미국 FRED를 주축으로, 한국 ECOS를 보조로 쓴다.
- 수급은 외국인·기관계뿐 아니라 투자신탁·기금 흐름도 본다.
- 공시·매크로·수급 Agent는 매수·매도·목표가를 제시하지 않고 최소한의 해석만 한다.
- 정량 계산은 Python에서 결정론적으로 수행하고 LLM은 계산된 값을 재계산하지 않는다.
- 공시·매크로·수급·예측이 충돌하면 Market Agent가 충돌과 불확실성을 명시한다.
- API 실패나 데이터 부재를 임의의 샘플·다른 공급자 데이터로 대체하지 않는다.
- 공시 원문은 선택된 3개 문서의 전체 visible text를 수집한다. 긴 문서는 기본 60,000자 단위로 모두 분석한 뒤 구조화 결과를 최종 통합하며 원문을 조용히 자르지 않는다.
- Evidence Agent의 구조화 출력이 실패하면 자유 텍스트로 우회하지 않고 실행을 중단한다.

## 다음 작업 우선순위

1. Kronos 포함/미포함 및 단순 기준선 대비 워크포워드 평가를 만든다.
2. 공시 유형별 구조화 API를 추가 활용해 원문 자유 텍스트 추출 결과와 교차검증한다.
3. GitHub 공개용 사용 예시·아키텍처 다이어그램·CI를 정리한다.

## 주의할 버그/교훈

- DART `corp_code` XML은 정규식 전체 매칭을 쓰면 다른 기업 코드가 잡힐 수 있다. 현재는 XML 항목 단위 파싱으로 수정됨.
- KIS 캔들을 Market Agent가 중복 재조회하면 KIS가 500을 낼 수 있다. 현재 실행 스크립트는 사전 검증 스냅샷을 Agent 상태로 전달해 중복 조회를 피한다.
- KIS 당일 확정 수급은 15:40 이전 `OPSQ2001`이 날 수 있다. 분석일이 오늘인 경우에만 직전 완료 거래일의 실제 KIS 수급을 조회하고 요청일·실제 수급 기준일을 모두 기록한다.
- 날짜는 point-in-time 기준으로 다뤄야 한다. 특히 CPI는 월간 발표값이므로 분석일 당일 데이터처럼 취급하면 안 된다.
- ECOS는 분석일 이후 관측치를 차단하지만 과거 vintage를 제공하지 않으므로 개정치 누수는 완전히 제거할 수 없다. 엄밀한 백테스트에는 자체 일별 snapshot 보관이 필요하다.
- `--enhanced --kronos-mode remote`에서는 Evidence Agent 4개가 병렬 실행되며 전체 역할 Agent 수는 13개다.
- iCloud 안의 `.venv`를 두 기기가 공유하면 절대경로가 깨진다. `bootstrap_local_env.sh`로 기기별 환경을 `~/.virtualenvs/` 아래 생성한다.
- Python 3.12와 `requirements.lock`을 두 기기에서 공통 사용한다.
- 2026-09-03 실제 `005930`, 분석일 `2026-09-02`, `--enhanced` 실행 완료: 12개 Agent, 최종 Hold, 14개 비어 있지 않은 보고서 파일 생성.
- 2026-09-03 RunPod RTX 4090 GPU에서 공개 GHCR 이미지 `ghcr.io/seungmin2001/korean-stock/kronos-api:kronos-v0.1.0` 실행 성공. `/healthz` 확인 후 실제 KIS 244개 일봉을 전송해 `Kronos-base` GPU 예측 JSON 수신·계약 검증 성공.
- Kronos는 OHLCV만 입력받는다. 따라서 공시·매크로·수급이 Kronos 예측의 원인이라고 주장하지 않는다. `kronos.md`에는 모델이 받은 캔들의 관측 요약과 모델 출력·불확실성만 기록하고, 다른 근거와의 대조는 Market Agent가 수행한다.
