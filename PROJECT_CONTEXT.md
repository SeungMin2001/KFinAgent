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
- `--enhanced`에서 한국형 역할이 각자 배정된 검증 snapshot 구간만 구조화함
- 한국 특화 실행은 원본 TradingAgents의 `Market → Sentiment → News → Fundamentals` 분석 순서를 유지한다. 각 역할은 KIS 시장, KIS 수급, DART 공시, DART 기반 재무 근거로 대응하며, 이어서 Macro와 Kronos 근거를 추가한 뒤 원본 Bull/Bear·Manager·Trader·Risk·Portfolio 흐름으로 들어간다.
- 모든 한국형 분석 보고서는 Bull/Bear 및 Research Manager에 직접 전달된다. Market Analyst의 요약만 통과하는 정보 병목은 사용하지 않는다.
- `--enhanced --kronos-mode remote`는 사전 검증에 사용한 동일 KIS 캔들을 중복 조회 없이 Kronos에 보내고, Time-Series Forecast Evidence Analyst를 병렬 추가함
- Kronos 일봉 기본 프로토콜은 논문과 맞춤: 과거 40개 OHLCVA → 미래 12개 일봉, T=0.6, top-p=0.9, 10개 경로
- 네 Evidence Agent는 매매 의견을 내지 않고 수치·기간·출처·결측·한계를 전달함
- Market Agent는 KIS 가격·기술지표와 네 Evidence report를 받아 충돌을 종합함
- 실행 중 진행 단계 출력, `--verbose`일 때 각 Agent 출력 표시
- 완료된 리포트마다 `0_evidence.md` 생성
- 보고서에 검증된 KIS 캔들·거래량·Kronos 중앙 예측 경로/최종 p10-p90 범위를 담은 `visuals/market_overview.svg` 생성
- 차트와 동일한 원천 캔들의 결정론적 요약을 Market Agent에 텍스트로 제공한다. 현재 Agent는 이미지 자체를 읽는 Vision 방식이 아니다.

### 아직 미완성인 것

- 공시 유형별 구조화 API를 추가 활용해 원문 자유 텍스트 추출 결과와 교차검증
- 장기 반복 평가·엄밀한 point-in-time 검증·전향적 검증 (초기 과거 replay 엔진과 단월 파일럿은 완료)
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
- `0_history/prior_reports.md`: 분석일 이전의 같은 종목 리포트에서 읽은 결론 요약과 참조 경로
- `1_analysts/market.md`: 통합 시장 분석
- `1_analysts/disclosure.md`, `macro.md`, `flow.md`: 출처별 객관적 Evidence report
- `1_analysts/kronos.md`: 모델 입력 캔들 요약·예측 범위·불확실성을 분리한 시계열 Evidence report
- `2_research/`: Bull/Bear/Manager 토론
- `3_trading/`, `4_risk/`, `5_portfolio/`: 최종 판단 과정
- `complete_report.md`: 통합 리포트
- `FINAL_BRIEF.md`: 최종 등급·실행안·계좌 제약·핵심 근거·차트를 한눈에 보는 결정 우선 요약

## 환경변수

`.env`에만 보관하며 Git에 올리지 않는다.

```env
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ENV=real
# Read-only domestic-stock balance lookup; never commit these values.
KIS_CANO=
KIS_ACNT_PRDT_CD=
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
- 계좌 인지 실행은 KIS 잔고조회만 사용한다. 계좌번호를 제외한 보유 수량·평단·현금·평가금액 요약은 모든 에이전트에 전달되며, 주문 API는 연결하지 않는다. 보유 0주면 `Hold`를 실제 보유 유지로 해석하지 않고 `Watch / No entry`로 표시한다.
- 매 실행 전 `artifacts/reports/`에서 같은 종목의 **분석일보다 이른** 완료 리포트를 최대 3건 읽고, Research Manager·Trader·Portfolio Manager 결론을 모든 에이전트에 참고문맥으로 전달한다. 과거 리포트는 현재 검증 데이터보다 우선하지 않으며, 이후 날짜 리포트는 참조하지 않는다.
- Enhanced 모드는 KIS `종합 시황/공시(제목)`에서 종목 연관 제목 메타데이터도 수집한다. 기사 본문이 아니므로 이벤트 주제 탐지용이며, 제목만으로 사실·인과·매매방향을 단정하지 않는다.
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

- 2026-09-04: `scripts/benchmark_korean_stock.py`, `tradingagents/benchmark.py`에 과거 순차 평가 구현 완료.
  평가 종목은 사용자 지정 삼성전자(005930), SK하이닉스(000660)로 고정. LS ELECTRIC 포함 초기 실행은 예비이며 최종 비교에서 제외.
  기본 비교군 Buy&Hold/SMA/MACD/RSI + 선택 Kronos/Agents/Agents+Kronos. t종가 판단→다음 실제 거래일 시가, 가상 계좌, 편도 비용 가정, 12거래일 판단.
  `docs/BENCHMARK_PROTOCOL.md` 참조. 과거 ECOS 개정치·LLM 학습지식 등으로 탐색적 replay이며 엄밀한 OOS 성과로 주장하지 않는다.
  계좌 주문 API는 호출하지 않는다. 완료된 종목별 실행은 `scripts/combine_benchmarks.py`로 NAV 합산 가능.
  8월 파일럿 7전략/2종목/Agent 토론 8회 실실행 완료: 합산 Buy&Hold +3.29%, MACD +2.37%, Kronos +0.53%, Agents 및 Agents+Kronos 0%(모든 판단 Hold).
  `docs/BENCHMARK_RESULTS.md`에 결과와 제한 기록. 대시보드는 `artifacts/benchmarks/samsung_hynix_202608_pilot/BENCHMARK.html`.
  1년 기준선·비용 10/30/50bp·매일 판단 기준선 검증도 완료. 1년 Agent 전체 비교·반복은 아직 미실시.
  전액 진입 매핑이 Hold를 강화할 수 있다는 관측이 있어, 공개 성능 주장 전 배분 정책·공개시점 검증 및 API 예산 확정 필요.

1. Kronos 포함/미포함 및 단순 기준선 대비 워크포워드 평가를 만든다.
2. 공시 유형별 구조화 API를 추가 활용해 원문 자유 텍스트 추출 결과와 교차검증한다.
3. GitHub 공개용 사용 예시·아키텍처 다이어그램·CI를 정리한다.

## 주의할 버그/교훈

### 2026-09-05 DART 입력 축소

- 사용자 승인으로 enhanced 기본 DART를 구조화 전체 재무제표(CFS/OFS) + 공시당 최대
  12,000자 원문 발췌로 변경. 원문 ZIP/텍스트와 재무 API 응답은 artifacts/dart_sources에
  SHA256으로 보존. 자동 캐시 fallback 없음.
- 구조화 응답의 접수번호/기업/회계연도/보고서코드 불일치 시 중단. 공식 013은 해당 범위
  자료 없음으로 명시하며 네트워크 오류는 실패. 과거 vintage 보장과는 별개.
- 삼성전자 2026-08-19 실제 DART 확인 성공. 구조화 JSON 반복키 제거 뒤 재무 입력 약 8만 자,
  최근 공시 약 3,800자. 새 LLM 토론/RunPod 실행은 하지 않아 토큰 절감 실측은 아직 없음.
- 계좌/정책별 최종 판단 재사용은 계좌 문맥을 바꾸므로 구현하지 않음.
- DART 네트워크 예외의 인증키 URL 노출을 차단. 이전 출력 키는 재발급 권고.

### 공개용 두 구간 평가 진행 (2026-09-04)

- 후속 안정화: `prepare_global_evidence.py`로 실제 날짜별 글로벌 근거를 수집·고정하고
  `--global-risk-from`으로 명시적 재사용. 체크섬/날짜/버전/검색식 검증, 누락·손상 시 live fallback 없음.
  8/19 snapshot 실제 수집 성공: artifacts/frozen_global_evidence/2026-08-19.json.
- GDELT 429 대기 30/60초 및 Retry-After 존중. 제한이 영구 해결된 것은 아님.
- 추가 버그: 한국형 Market Analyst가 재무 원문까지 통째로 받던 문제를 발견해
  market_only_snapshot=True로 가격 자료만 전달하도록 수정. Fundamentals는 별도 분할 분석 유지.
  수정 전 실행 20260904_220504_453553은 중단/성과 제외. 진행 중 요청의 과금은 확인 불가.

- 실거래 자동매매는 사용자 지시로 범위 제외. 평가/벤치마크 공개자료에 집중.
- `scripts/benchmark_regimes.py`: 기본 dry plan, `--run`은 KIS 실제 기준선 suite 실행.
  A=1/1~6/22, B=7/1~9/3 실측. 비용 10/30/50bp × 초기 보유 0/50% = 12조건 완료.
- BuyHold/현금/SMA/MACD/RSI 5개 기준선. 현금 시작·10bp에서 A BuyHold +270.87%,
  MACD +184.49%; B BuyHold -32.75%, MACD -9.09%, RSI -4.32%, 현금 0%.
- `docs/BENCHMARK_REGIMES.md`, `docs/benchmark_results/regimes.json`, 구간별 SVG에 결과 기록.
  로컬 종합: artifacts/benchmarks/regimes_20260904_215552_020361/SUITE_v2.html.
- 실패 뒤 8/19 글로벌 근거를 실제 snapshot으로 고정해 Agent/Agent+Kronos 각 1회 smoke 완료.
  둘 다 미보유 계좌 Hold→WAIT. 2거래일 수익률 0%, 같은 기간 BuyHold +9.42%이나 성능표본 아님.
  RunPod health와 실제 Kronos 예측 호출 모두 성공.
- provider 보고 토큰: Agent 682,937개, Agent+Kronos 700,640개. DART 원문 분할/합성 비용이 과도해
  본 AI suite는 중단 상태. 후속 benchmark 응답별 기본 출력 상한 4,096 추가(총요금 상한 아님).
  판단당 근거 300,000자 초과 시 LLM 전 중단하며 명시적으로만 상향 가능.
- 전체 토론 cap 기본 0인 suite로 대량 LLM 호출 방지. 그래프 수 cap은 토큰/요금 cap이 아님.
- 후속 AI suite 반복/정책 비교는 근거 공급 복구 및 비용 확인 후 진행. README 복원/실거래 구현 안 함.

### 2026-09-04 무료 글로벌 근거 확장

- 사용자 지정 평가 구간: A=2026-01-01~06-22, B=2026-07-01~최신 완료 거래일. 6/23~6/30 제외.
- `--enhanced --global-risk`: GDELT 국제 분쟁 제목/URL/최초수집시각, BOJ 실제 익일물 콜금리,
  기존 FRED 키로 달러/엔·브렌트유 수집 → Macro Evidence Analyst → 기존 토론.
- `scripts/check_global_risk.py --date YYYY-MM-DD`로 LLM/GPU 없이 독립 연결 점검.
- API 실패는 중단. GDELT 범위 밖 반환은 필터링하며 전체 범위 밖이면 실패.
- BOJ 콜금리는 정책 목표가 아니다. 정책 결정 발표문/회의 일정은 미구현.
  BOJ 최신 수정본과 뉴스 아카이브 한계 때문에 엄밀한 PIT 성과를 주장하면 안 된다.
- 기존 결과 보존을 위해 글로벌 근거는 명시적 플래그로 켠다. 새 전체 구간 성과는 아직 미실행.
- 후속 수정: 벤치마크 기본 step 배분(Buy +50%p/Overweight +25%p/Underweight -25%p/Sell 0),
  `--allocation-policy binary`로 기존 방식 비교, `--initial-exposure 0.5`로 기존 보유 평가 지원.
  Hold는 수량 유지이며 WAIT/HOLD_POSITION 실행 행동을 분리한다. 실제 현재 평가 비중을 Agent에 전달.
- 재무 부족 원인: 최근 공시 45일/3건만으로 정기보고서가 빠질 수 있었음.
  별도 정기공시 검색(550일, 분석일 전날 마감) 후 최신 회계기간 원문을 재무 Agent에 제공하도록 수정.
  긴 재무 원문도 분할/합성하여 무단 생략하지 않음. 삼성전자 2026.06 반기보고서 실수집 검증 완료.
- 수정 후 전체 LLM 판단/성과 재평가는 아직 미실행. Hold가 실제로 줄었다고 주장하면 안 됨.
- 사용 문서: `docs/GLOBAL_RISK.md`.

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
