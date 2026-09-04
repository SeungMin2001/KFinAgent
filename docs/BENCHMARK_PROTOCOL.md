# 한국 주식 평가 프로토콜 v1

실행 전 조건을 고정하고 모든 전략을 같은 거래일·비용·초기자금으로 비교한다.
원본 TradingAgents의 CR/AR/Sharpe/MDD 평가를 참고하되 한국 워크플로의 Kronos 기여도를 별도로 측정한다.
원문: https://arxiv.org/abs/2412.20138

## 비교군

| 전략 | 사전에 고정한 규칙 |
|---|---|
| buy_hold | 첫 시가에 매수 후 보유 |
| sma | SMA20 > SMA60이면 보유 |
| macd | EMA12-EMA26 > EMA9 signal이면 보유 |
| rsi | 단순 14일 RSI<30 진입, >70 청산, 나머지 유지 |
| kronos | 12일 중앙경로 예상수익률이 왕복 가정비용 초과 시 보유 |
| agents | 한국형 전체 에이전트, Kronos 제외 |
| agents_kronos | 동일 한국형 전체 에이전트 + 동일 Kronos 예측 |

Buy/Overweight=100% 매수, Hold=현재 비중 유지, Underweight/Sell=현금화.
Trader의 자유 텍스트 수량을 임의 해석하지 않고 고정 등급 매핑을 비교한다.
REVIEW, API 오류, 누락된 캔들, 공통 거래일 불일치는 실패 처리한다.

## 체결과 공정성

- 최소 60거래일 워밍업. 기본은 12거래일마다 전 전략이 함께 판단한다.
- t 종가까지 정보로 판단, t+1 실제 관측 거래일 시가 체결. 거래량 0이면 다음 거래일까지 보류.
- 종목별 초기 100만원 독립 계정, 종목 간 현금 재배분 없음. 합산 NAV로 평가.
- 실계좌 잔고와 일반 리포트 기억을 읽지 않는다. 전략별 가상 잔고를 Agent에 제공.
- KIS 조정가격에 대한 가상 소수점 수량. 배당 제외 price-return 평가다.
- 편도 10bp는 수수료·슬리피지·세금을 합친 실험 가정이며 실제 세율 주장이 아니다.
- 반드시 10/30/50bp 민감도도 비교해야 한다. 호가제한·거래정지·체결대기열은 정밀 모사하지 않는다.
- 마지막 날은 종가 평가이며 강제 청산하지 않는다. 현금 이자와 Sharpe 무위험수익률은 0.
- 단순/Agent 전략에 같은 cadence를 적용한다. 기술지표 전략의 최적화된 최고 성능을 주장하지 않는다.

## 실행

계획만 확인 (API 호출 없음):

```bash
.venv/bin/python scripts/benchmark_korean_stock.py --plan --strategies buy_hold sma macd rsi kronos agents agents_kronos
```

기본 파일럿은 2026-06-01~2026-08-31, 사용자 지정 삼성전자·SK하이닉스 2종목.
최초 3종목(LS ELECTRIC 포함) 실행은 예비 실행으로만 남기며 최종 비교에서 제외한다.
편의표본으로 파이프라인을 검증하며, 시장 대표성·전략 우월성을 입증하지 않는다.

```bash
.venv/bin/python scripts/benchmark_korean_stock.py
.venv/bin/python scripts/benchmark_korean_stock.py --strategies buy_hold sma macd rsi kronos agents agents_kronos
```

전체 비교는 RunPod 및 KIS/DART/FRED/ECOS/LLM API가 필요하다. 그래프 호출 상한은 기본 120회.
실패 후에는 새 디렉터리에서 재실행한다. 실패한 실행의 부분 성과를 leaderboard로 만들지 않는다.

종목별로 독립 실행한 경우 설정과 날짜가 같은 완료 실행만 합산할 수 있다:

```bash
.venv/bin/python scripts/combine_benchmarks.py <삼성전자_결과폴더> <SK하이닉스_결과폴더>
```

합산은 실제 NAV를 더한 뒤 Sharpe/MDD를 다시 계산한다. 개별 Sharpe를 평균하지 않는다.
`BENCHMARK.html`은 전체 대시보드, `equity.svg`와 `drawdown.svg`는 독립적으로 삽입 가능한 벡터 그림이다.

본 평가 제안: 2025-09-01~2026-08-31, 위 두 종목, 12거래일 판단, 전 전략 동일 비용.
먼저 2026년 8월 단월 파일럿을 끝내 API 흐름을 검증한다. 1년 평가와 최소 3회 반복은 파일럿 실행시간·API 사용량을 확인한 뒤 진행한다.
현재 단월은 파라미터 탐색 없이 정해진 그대로 실행하며 성능 우월성을 판정하는 holdout으로 사용하지 않는다.

## 공개 요건

수익률, 252거래일 기준 연환산 수익률, Sharpe(rf=0), MDD, 거래횟수, 비용, 시장 노출도 및 paired 12일 block-bootstrap 평균 일별 초과 로그수익 신뢰구간을 공개한다.
전체 누적수익과 낙폭 차트, 종목별 equity CSV, 체결 JSON, 원본 캔들 SHA256, 설정과 코드 commit을 함께 보관한다.
Agent 모델 ID·라운드 수, 근거 snapshot·판단·가상계좌도 저장한다. API 키는 저장하지 않는다.

`--bars-from <기존실행폴더>`로 SHA256이 일치하는 실제 KIS 캔들을 명시적으로 재사용할 수 있다.
자동 데이터 대체가 아니며, 원본이 없거나 checksum이 다르면 중단한다. 기준선 비용 민감도는 `--cost-bps 30` 또는 `50`으로 재계산한다.

파일럿 이후에는 파라미터를 고정하고 독립된 1년 이상 기간·업종별 종목군에서 검증한다.
반복 LLM/Kronos 실행 최소 3회, 비용 민감도, 종목별/월별 결과, 미래의 전향적 paper-trading 결과를 추가한 뒤 성능 주장을 한다.
최고 수익률 조합만 README에 싣지 않고 실패한 전략과 기간도 함께 공개한다.

## 아직 해결되지 않은 과거정보 누수

ECOS는 과거 vintage를 보장하지 않는다. DART 정정자료, 헤드라인 과거 보존기간/전체성,
미국 발표시각과 한국 종가의 시간대, LLM 사전학습 지식, Kronos 사전학습 기간도 검증 대상이다.
날짜 필터만 적용했다고 완전한 point-in-time/OOS라 부르지 않는다.
모델 입력은 실제 공개된 시점의 snapshot 보관으로 전향적으로 검증해야 한다.
Kronos 미래 시간축은 현재 평일 기반이므로 KRX 공휴일과 일치하지 않을 수 있다.
따라서 현 버전은 **탐색적 historical replay**이며, 모든 정보에 과거 접근이 가능하다는 가정은 사용하지 않는다.
