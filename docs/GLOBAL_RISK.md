# 무료 글로벌 위험 근거

기존 실험을 몰래 변경하지 않도록 `--global-risk`로 명시적으로 켠다.
새 키는 필요 없다. FRED는 기존 `.env`의 `FRED_API_KEY`를 사용한다.

| 자료 | 무료 출처 | 해석 한계 |
|---|---|---|
| 국제 분쟁 제목·URL·최초 수집시각 | GDELT DOC API | 기사 본문/사건 사실 검증 아님. 영문 키워드·최근순 표본 최대 30건 |
| 일본 익일물 무담보 콜금리 | BOJ FM01/STRDCLUCON | 실제 시장금리. 정책금리 목표·정책 결정 발표와 다름 |
| 달러/엔 | FRED DEXJPUS | 달러당 엔. 상승은 엔화 약세 |
| 브렌트유 | FRED DCOILBRENTEU | 관측 유가. 전쟁과의 인과관계를 입증하지 않음 |

모두 기존 Macro Evidence Analyst → 강세/약세 토론 → 최종 판단으로 전달된다.
판단을 강제로 매수/매도로 바꾸지 않는다. 근거 원문은 snapshot과 증거 파일에 남는다.

## 독립 연결 점검 (LLM/GPU/KIS 계좌 호출 없음)

```bash
.venv/bin/python scripts/check_global_risk.py --date 2026-01-07
```

성공 시 `artifacts/global_risk/2026-01-07/evidence.md` 생성.
전체 연구는 기존 실행 명령에 `--enhanced --global-risk`를 붙인다.

구간별 벤치마크 계획 확인 (실제 API 호출 없음):

```bash
.venv/bin/python scripts/benchmark_korean_stock.py --start 2026-01-01 --end 2026-06-22 --global-risk --strategies buy_hold sma macd rsi kronos agents agents_kronos --plan
.venv/bin/python scripts/benchmark_korean_stock.py --start 2026-07-01 --end 2026-09-03 --global-risk --strategies buy_hold sma macd rsi kronos agents agents_kronos --plan
```

두 번째 종료일은 실행 시 최신 완료 거래일로 교체한다. `--plan` 제거 전
배분 정책 수정과 전체 API 예산을 확정한다. 이 문서의 명령은 실측 완료 주장이 아니다.

## 시점·장애 처리

### 반복 평가용 사전 수집 (명시적 재사용)

```bash
.venv/bin/python scripts/prepare_global_evidence.py --dates 2026-08-19 --output artifacts/frozen_global_evidence
```

성공한 실제 근거만 날짜별 JSON에 저장한다. 이미 존재하면 날짜·검색식·버전·SHA256을 검증하고
재요청하지 않는다. 실패 시 다른 날짜나 빈 자료로 바꾸지 않는다. 당일 미완료 자료는 고정하지 않는다.
현재 구현은 원시 HTTP 응답이 아닌 검증/렌더링된 근거 문자열을 보관한다. 서명이나 완전한 PIT 보장은 아니다.

벤치마크에는 `--global-risk --global-risk-from artifacts/frozen_global_evidence`를 명시한다.
이 모드는 새 글로벌 API 연결을 요구하지 않는 **재현용 입력 모드**다. 파일 누락·손상 시 live로
전환하지 않고 중단한다. 일반 분석의 기본 live 경로는 그대로다.

기존 suite의 실제 KIS 거래일에서 필요한 날짜만 추출해 준비할 수도 있다:

```bash
.venv/bin/python scripts/prepare_global_evidence.py --suite artifacts/benchmarks/regimes_20260904_215552_020361/suite.json --output artifacts/frozen_global_evidence
```

429는 30/60초 간격으로 최대 3번 요청한다. Retry-After가 더 길면 존중하며,
60초 초과 대기 요청은 자동 재요청하지 않고 중단한다. 외부 제한이 영구적으로 해결됐다는 뜻은 아니다.
2026-09-04 재시도에서 8/19 근거 수집 및 저장은 실제 성공했다.

2026-09-04 실제 연결 점검 완료: 분석일 2026-01-07 기준 GDELT 250건 중
마감 이후 46건 제외, 유효 204건 중 최근 30건 표시. BOJ 1/6 콜금리 0.727%,
FRED 달러/엔·브렌트유 응답을 확인했다. 이는 그 시점의 예시 수집 결과이며 현재 값이 아니다.
관련 자동 테스트 21개 통과. 전체 LLM 토론 및 두 구간 성과 재측정은 미실행.

- 뉴스는 한국장 마감 15:30 KST까지. 요청 범위를 넘는 응답도 로컬에서 재검증/제외.
- 최초 수집시각은 원문 발행시각이나 사건 발생시각이 아니다. 오늘 다시 찾은 과거 뉴스 목록의 완전성도 보장하지 않는다.
- 응답 전체가 범위 밖이면 실패. 정상 빈 목록은 NO_MATCHES로 표시하되 위험 부재로 해석하지 않는다.
- 429/일시적 서버 오류는 최대 3번만 요청. 최종 연결 실패·형식 오류는 분석 중단.
- BOJ는 분석일 이전 관측만 사용하나 **최신 수정본**이므로 과거 공개시점 재현을 보장하지 않는다.
- 신규 FRED 시계열은 미국 당일 발표가 한국 마감 이후 들어오는 것을 피하려고 전날 빈티지까지만 사용한다.
- BOJ 정책 목표·발표문·회의 일정은 아직 수집하지 않는다. 시장금리로 대체했다고 주장하지 않는다.
- 근거 수집 성공과 투자 성과 개선은 별개다. 전체 LLM 토론 실측은 별도로 필요하다.

공식 자료:
- https://www.stat-search.boj.or.jp/info/api_manual_en.pdf
- https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
- https://fred.stlouisfed.org/series/DEXJPUS
- https://fred.stlouisfed.org/series/DCOILBRENTEU
