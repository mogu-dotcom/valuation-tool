# Worklog — 2026-06-09 — 밸류에이션 계산기 MVP 구축 + 1차 반복 개선

> **이 문서의 목적**: 다음 작업 세션이 코드를 다시 분석하지 않고도 맥락을 이어받기 위한 기록.
> "왜 이렇게 짰는지", "어디를 건드리면 되는지", "함정이 무엇인지"를 중심으로 작성함.
> (첫 워크로그라서 프로젝트 전반을 함께 정리했음. 다음부터는 마지막 워크로그 이후의 변경만 추가하면 됨.)

---

## 0. 한 줄 요약
주식 교육 강사(모구)가 수업에 쓸 **밸류에이션 계산기**를 Streamlit으로 만들어 Railway에 배포함.
PER/PBR/PSR로 목표주가·상승여력을 계산하고, PEG·애널리스트 컨센서스 배수를 참고로 제공. 한국/미국 주식 지원.

---

## 1. 빠른 시작 (다음 세션이 가장 먼저 볼 것)

### 핵심 좌표
| 항목 | 값 |
|---|---|
| 프로젝트 폴더 | `C:\Users\conta\valuation-tool` |
| GitHub | https://github.com/mogu-dotcom/valuation-tool (브랜치 **master**) |
| 공개 URL (운영) | https://valuation-tool-production-248e.up.railway.app |
| Railway 프로젝트 | `valuation-tool` (ID `d5f7c7ba-2482-4962-848f-653cad8e5f91`), env `production` |
| Railway 서비스 | `valuation-tool` (ID `d0322b49-758a-4abf-a1be-d4b342db6432`) |
| 메인 코드 | `app.py` (단일 파일, ~603줄) |
| 계정 | GitHub `mogu-dotcom`, Railway/이메일 `mogu@hs-academy.kr` |

### 설치된 CLI 도구 (winget/직접설치, PATH에 없을 수 있어 절대경로 사용)
- gh CLI: `C:\Program Files\GitHub CLI\gh.exe` (인증됨: mogu-dotcom, scope repo)
- Railway CLI: `C:\Users\conta\railway-cli\railway.exe` (v5.6.2, 로그인됨: mogu@hs-academy.kr)
- Python: 로컬 **3.14** (`venv/`), Railway 빌드는 **3.13** (railpack 기본)

### 자주 쓰는 명령 (Bash 도구 기준, 경로는 git-bash 스타일)
```bash
# 로컬 실행 (미리보기) — http://localhost:8501
/c/Users/conta/valuation-tool/venv/Scripts/streamlit.exe run app.py --server.headless true --server.port 8501

# 문법 체크
py -3.14 -m py_compile app.py

# 로직 검증 (AppTest) — 예시는 6장 참고. 예외/계산값 확인
./venv/Scripts/python.exe <테스트.py>

# 커밋 + 푸시 + 배포 (★ --service 필수! 아래 5장 gotcha 참고)
git add app.py && git commit -m "..." && git push origin master
/c/Users/conta/railway-cli/railway.exe up --ci --service valuation-tool

# 배포 후 헬스 체크
curl -s -o /dev/null -w "%{http_code}\n" https://valuation-tool-production-248e.up.railway.app/healthz
```

> **AppTest 주의**: `at.session_state`는 SafeSessionState 프록시라 `.get()`/`.pop()` **미지원**. 반드시 `at.session_state["key"]` 인덱싱으로 접근. 첫 `.run()` 전에 `at.session_state[...]`로 값 세팅 가능(통화 등은 dec 계산 때문에 먼저 세팅).

---

## 2. 프로젝트 개요 / 의도

- **사용자**: 주식 투자 교육 강사. 코딩 비전문가 → 옵션은 쉬운 말로 설명, 단계는 구체적으로 안내. **한국어 소통**.
  (글로벌 메모리 `user-stock-educator`, `project-valuation-tool` 참고. 글로벌 CLAUDE.md에 "항상 한국어", "기술 선택은 비개발자도 이해하게 설명" 지침 있음.)
- **목표**: 일반 수강생이 PER/PBR/PSR로 목표가·상승여력을 어렵지 않게 계산하는 웹 도구. **쓰기 편함이 최우선**.
- **최초 제약**: "오늘 90분 안에 MVP 배포 + 데모" → MVP를 빠르게 띄우고, 이후 사용자 피드백으로 반복 개선함(이 세션 전체).
- 설계 문서(최초 플랜): `C:\Users\conta\.claude\plans\swift-napping-twilight.md`

---

## 3. 기술 스택 & 아키텍처

- **Streamlit 1.58** (파이썬으로 웹 UI 자동 생성) + **yfinance 1.4.1** (야후 파이낸스 데이터) + pandas/altair.
- **단일 파일 `app.py`** 구조. 위→아래로 선형 실행되는 Streamlit 스크립트.
- 데이터 흐름: 종목코드 입력 → `fetch_data()`(yfinance) → `apply_fetched()`가 `st.session_state`의 **영구 키**에 저장 →
  화면 위젯이 그 값을 읽어 표시/편집 → 계산 → 결과.

### app.py 섹션 맵 (줄번호는 대략, 변경되면 `grep '<div class="sec"'`로 재확인)
| 영역 | 내용 |
|---|---|
| 상단 | import, 상수(UP_COLOR=빨강, DOWN_COLOR=파랑, BRAND), `FIELDS` 영구키 목록, setdefault |
| `resolve_tickers` | 6자리숫자→`.KS`(코스피) 우선 `.KQ`(코스닥) 폴백, 그 외 그대로(미국) |
| `fetch_data` | `@st.cache_data(ttl=600)`. 현재가·EPS·매출 추정·BPS·발행주식수·애널리스트 목표가 수집 |
| `apply_fetched` | 조회 결과를 session_state 영구키로 저장 + SPS 계산 + 위젯키(`w_*`) pop |
| `do_fetch` | 조회 버튼/태그 클릭 시 호출. 결과 메시지(`_fetch_msg`) 세팅 |
| 표시 헬퍼 | `is_krw, cur_symbol, fmt_price, fmt_big(조/억·B/M), fmt_shares, fmt_num(콤마)` |
| 입력 헬퍼 | `_fmt_input, _parse_num, _commit_field, num_field` (★ 콤마 텍스트 입력, 6장 참고) |
| CSS | Pretendard 폰트, 히어로 헤더, 카드/배지 스타일, Streamlit 기본 메뉴·푸터 숨김 |
| 섹션 1 | 종목 선택: **검색창(메인)** + 인기종목 **pill 태그**(한·미 통합) |
| 섹션 2 | 평가 방식 segmented_control (PER/PBR/PSR) — **연도는 여기 없음** |
| 섹션 3 | 값 확인·수정: 선택 방식에 필요한 칸만(EPS / BPS / 주당매출SPS) + 현재가. `_base_for`, `base_by_year` |
| 섹션 4 | 목표 배수(보수/중립/낙관, **연도 무관**) + **📋 애널리스트 기준 배수(참고)** |
| 섹션 5 | 결과: **연도 태그(2026/2027) 여기서 선택**, 올해/내년 비교칩, 헤드라인 목표가 카드, 3시나리오 카드, 막대차트, (PER일 때) **📐 PEG** |

---

## 4. 배포 인프라 (CLI 기반) — 어떻게 세팅했나

- **왜 Railway?** 사용자가 원래 Railway 사용 중. CLI 배포 가능 + 영구 URL(Streamlit Cloud는 CLI 없음, cloudflared는 임시).
- **인증**: gh와 railway 모두 **device-flow/browserless 로그인**으로 처리. 백그라운드로 로그인 명령 실행 → 출력에서 코드 추출 → 사용자가 브라우저로 승인. (비밀번호를 대화에 노출 안 함)
- **빌드 설정**:
  - `Procfile`: `web: streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true --server.enableCORS false --server.enableXsrfProtection false`
  - `.streamlit/config.toml`: headless, CORS/XSRF off, usage stats off
  - railpack(Nixpacks 후속)이 `requirements.txt` 감지 → pip 설치 → Procfile로 실행. Python 3.13 자동.
- **배포 명령**: `railway up --ci --service valuation-tool`
  - `--ci`: 빌드 로그 스트리밍 후 종료(백그라운드 실행에 적합)
  - **★ gotcha**: 이 프로젝트는 서비스가 **링크되어 있지 않음**(`railway status`의 Linked service: None). 그래서 `--service valuation-tool`을 **반드시** 명시해야 함. 빼면 `Multiple services found` 에러.
- **venv는 git/배포에서 제외**(`.gitignore`). 브라우저 업로드 X, `railway up`이 로컬 디렉토리 업로드(.gitignore 존중).

---

## 5. 작업 순서 = 커밋 로그 (오늘 한 일 전체)

시간순. 각 커밋의 "무엇을/왜"를 정리.

1. **7080f4b 13:15 — MVP** (PER/PBR/PSR 목표가·업사이드). Streamlit 단일앱. 종목 자동조회 + 편집 가능 칸 + 보수/중립/낙관 시나리오 + 색상 막대.
2. **b3f1430 13:27 — Railway 배포 설정**. Procfile, streamlit config 추가 → 최초 공개 URL 생성.
3. **db10bae 13:45 — UI/UX 대폭 개선**. Pretendard 폰트, 그라데이션 히어로 헤더, 인기종목 원클릭, **한국식 색상(상승=빨강/하락=파랑)**, 조/억 단위, 결과 카드.
4. **81da817 13:50 — 종목선택 UI**. 검색창을 메인(위)으로, 인기종목을 `st.pills` 태그로 통합(한·미 헤더 제거).
5. **95d9b1a 13:59 — 기준연도 이동**. 연도(2026/2027)를 섹션2→**섹션5(결과)**로 이동. 결과에서 태그로 전환하며 "올해 vs 내년" 비교칩. 목표배수는 연도 무관으로.
6. **639df17 14:04 — 버그 수정(중요)**. 평가방식 전환 시 EPS/BPS/매출 값 소실 → 위젯상태와 영구저장 분리. (6장 참고)
7. **4605c9c 14:14 — 콤마/BPS/PSR**. ① 입력칸 **안에** 천단위 콤마(text_input 방식) ② BPS 3단계 폴백 ③ PSR을 **주당매출(SPS)** 입력으로 변경. (6장 참고)
8. **0f76537 14:36 — PEG 표기**. PER 결과(섹션5)에 PEG를 함께 표시(성장률·현재PEG·시나리오별 목표PEG). 별도 방식 아님.
9. **e686660 14:48 — PEG 레이아웃**. PEG 숫자를 metric으로 먼저, 설명은 아래로.
10. **7907ac3 14:55 — 애널리스트 기준 배수**. 섹션4 아래에 애널리스트 목표주가 컨센서스 ÷ 기준값 = "애널리스트 적용 배수" 역산 표시.

---

## 6. 핵심 기술 결정 & 함정(gotcha) — ★ 다음 세션 필독

### (A) Streamlit 위젯 상태 GC 버그 → 영구키/위젯키 분리
- **증상**: 평가방식을 PER→PBR→PER로 바꾸면 EPS 등 입력값이 0으로 사라짐.
- **원인**: Streamlit은 **그려지지 않은 위젯의 session_state 키를 자동 삭제(GC)**. 방식 전환으로 칸이 사라지면 값 소멸.
- **해결 패턴** (`num_field` 함수): 데이터는 **영구키**(`eps_2026` 등 `FIELDS`)에 보관하고, 위젯은 **별도 위젯키**(`w_eps_2026`)를 사용.
  매 렌더에서 `w_*`가 없으면 영구키 값으로 시드 → 위젯 렌더 → 위젯값을 다시 영구키로 복사.
- **새 종목 조회 시**: `apply_fetched`가 영구키를 갱신하고 `w_*` 위젯키를 **pop**해서 새 값이 다시 시드되게 함.
  → 위젯 입력 칸을 새로 추가하면 `apply_fetched`의 pop 목록과 `FIELDS`에도 반드시 추가할 것.

### (B) number_input은 천단위 콤마 미지원 → text_input 기반 `num_field`
- `format="%,.0f"`는 `ValueError`. number_input 자체가 콤마 불가.
- 그래서 입력칸을 **text_input**으로: 표시값은 `_fmt_input`(콤마 포함 문자열), `on_change=_commit_field`에서 콤마 제거→파싱→영구키 저장→다시 콤마 형식으로 표시. 잘못된 입력은 마지막 정상값으로 복원.
- `decimals=None`이면 통화 인식(원화 0자리/달러 2자리). 발행주식수·매출은 `decimals=0` 명시.
- 단점: +/- 스테퍼 없음(텍스트 입력이라). 대신 콤마가 칸 안에 보임.

### (C) BPS 자동조회 3단계 폴백
- 한국 종목은 yfinance `info.bookValue`/`priceToBook` 둘 다 **None**인 경우가 많음.
- `fetch_data`에서: ① `info["bookValue"]` → ② `현재가 / info["priceToBook"]` → ③ **재무제표 `balance_sheet`의 자본총계 ÷ 발행주식수**.
  - balance_sheet 행 우선순위: `Common Stock Equity` → `Stockholders Equity` → `Total Equity Gross Minority Interest`.
  - 검증: 삼성전자 BPS≈73,591 / SK하이닉스≈169,776 / 애플 7.3 정상.

### (D) PSR = 주당매출(SPS) 입력으로 단순화
- 초기엔 전체매출+발행주식수 입력 → 사용자 요청으로 **주당매출(SPS)** 직접 입력/표시로 변경.
- `apply_fetched`가 SPS = 매출 ÷ 발행주식수로 계산해 `sps_2026/sps_2027`에 채움(편집 가능).

### (E) PEG는 별도 방식이 아니라 PER 결과에 부가 표기
- 사용자 의도: PER로 계산할 때 5번 결과에 PEG를 **함께** 보여주기.
- 구현: 섹션5 결과(method=="PER")에서 성장률 `g = (eps_2027/eps_2026 - 1)*100`을 **즉석 계산**(EPS 편집 시 자동 반영).
  - 현재 PEG = (현재가/EPS) ÷ g. 시나리오별 목표 PEG = 목표PER ÷ g.
  - 표시 순서: **PEG 숫자(metric)를 먼저**, 설명 caption은 아래. g≤0이면 안내문.
  - 별도 `peg_*` 영구필드 없음(즉석 계산).

### (F) 한국식 색상
- 상승=빨강(`UP_COLOR #e8392b`), 하락=파랑(`DOWN_COLOR #1f6fde`). `st.metric` 기본색은 미국식이라 **커스텀 HTML 카드/Altair**로 직접 색 지정.

### (G) 애널리스트 기준 배수 = 목표주가 ÷ 기준값 역산
- yfinance `targetMeanPrice/targetLowPrice/targetHighPrice/numberOfAnalystOpinions` 수집(`an_mean/an_low/an_high/an_n`).
- 섹션4에서 `목표주가 ÷ ref_base`(2026 기준값, 없으면 2027)로 환산 → "애널리스트 적용 PER/PBR/PSR". 방식 바꾸면 자동 환산.

---

## 7. 데이터 소스 레퍼런스 (yfinance) — 무엇이 되고 안 되나

| 항목 | 소스 | 한국 | 미국 | 비고 |
|---|---|---|---|---|
| 현재가 | `info.currentPrice/regularMarketPrice`, fast_info | ✅ | ✅ | 안정적 |
| EPS 2026/2027 | `Ticker.earnings_estimate` `0y`/`+1y` avg | ✅ | ✅ | 오늘=2026이라 0y=2026, +1y=2027 매핑 자연스러움 |
| 매출 2026/2027 | `Ticker.revenue_estimate` `0y`/`+1y` avg | ✅ | ✅ | 전체 매출(원/달러) |
| 발행주식수 | `info.sharesOutstanding` | ✅ | ✅ | SPS 계산용 |
| BPS | `bookValue` → `price/priceToBook` → `balance_sheet 자본총계/주식수` | ⚠️→✅(폴백) | ✅ | 한국은 3단계 폴백 필수 |
| 애널리스트 목표가 | `info.targetMean/Low/HighPrice`, `numberOfAnalystOpinions` | ✅ | ✅ | "딱 2개월" 필터는 없음(최신 컨센서스만) |

- **티커 규칙**: 한국 6자리 → `005930.KS`(코스피) 시도 후 실패 시 `.KQ`(코스닥). 미국은 심볼 그대로.
- **캐시**: `fetch_data`는 `@st.cache_data(ttl=600)`. 클라우드 rate-limit 완화 + 반복 조회 속도.

---

## 8. 알려진 한계 & 다음 작업 후보(TODO)

### 데이터 한계
- **"최근 2개월" 애널리스트 필터 미지원**: 무료 yfinance는 현재 컨센서스만 제공. 정확한 기간 필터가 필요하면
  네이버 금융/FnGuide 스크래핑 또는 유료 API 연동 필요(사용자가 요청 시). 현재 UI엔 "(야후 파이낸스 최신 컨센서스)" 명시.
- **미래 BPS 추정치 없음**: 2026/2027 BPS는 현재 BPS를 양쪽에 채움(편집 가능). 미래 자본 추정은 미제공.
- **yfinance 클라우드 차단 가능성**: 야후가 데이터센터 IP를 간헐적으로 막을 수 있음. 모든 칸이 **편집 가능**해서 데모는 안 깨지지만,
  자동조회가 비는 경우가 늘면 데이터 소스 보강 고려.

### UX/기능 후보 (사용자 미요청, 아이디어)
- 애널리스트 평균 배수를 "중립 배수로 한 번에 적용" 버튼(현재는 보고 수동 입력).
- 종목 검색 자동완성(이름→코드). 현재는 코드 직접 입력 + 인기종목 태그.
- 결과 공유/저장(이미지/링크), 여러 종목 비교.
- 입력값 단위 가독성(매출 칸은 콤마라 매우 김 → 조/억 입력 토글 고려).
- PEG 성장률을 사용자가 직접 조정하는 입력(현재는 2026→2027 자동 계산만).

### 운영
- Railway 사용량(크레딧) 소모 중. 사용자가 끄고 싶으면 대시보드에서 서비스 중지 안내.
- 서비스가 링크 안 됨 → 매 배포 `--service valuation-tool` 필수(또는 `railway service` 링크 1회 설정 고려).

---

## 9. 검증 방법 (이번 세션에서 실제로 쓴 패턴)

- **문법**: `py -3.14 -m py_compile app.py`
- **로직(AppTest)**: 첫 run 전 `at.session_state["currency"/"price"/"eps_*" ...]=...` 세팅 → `at.run()` → `at.exception` 없음 확인,
  `at.metric`/`at.text_input`/`at.markdown` 값으로 계산·표시 검증. 방식 전환은 `at.session_state["method_sel"]="PBR"; at.run()`.
- **수치 검증 예**: price100/eps10/eps12 → PER 중립 목표가 100, 낙관(12배) +20%; PEG=PER10÷성장률20=0.50.
- **배포 후**: `curl .../healthz` 200 확인.

---

## 10. 다음 세션 체크리스트 (이어서 작업할 때)
1. 이 워크로그 + 글로벌 메모리(`project-valuation-tool`, `user-stock-educator`) 읽기.
2. `git -C C:\Users\conta\valuation-tool log --oneline`로 이 문서 이후 변경 확인.
3. 입력칸을 **추가/변경**하면: `FIELDS`, `apply_fetched`의 `w_*` pop 목록, `num_field` 사용 여부를 함께 점검(6-A/B 함정).
4. 배포는 **반드시** `railway up --ci --service valuation-tool`.
5. 한국어로 소통, 기술 선택은 비개발자도 이해하게 설명.

---

## 11. 업데이트 — "애널리스트 기준 배수" 기능 진화 (2026-06-09 오후, 워크로그 이후)

> 섹션 5(결과) 위 **섹션 4 하단**의 "📋 기준 배수" 박스가 핵심. 사용자가 목표 배수를 정할 때
> 애널리스트가 실제로 적용하는 배수를 기준점으로 보여주는 기능. 아래 순서로 4번 반복 개선됨.

### 커밋 (이 문서 이후)
- `6be29ba` 현재 vs 평균 목표 비교 강조, 극단 최저/최고는 캡션으로(개별 1명 명시)
- `a9421f3` 평균 → **중앙값(median)**으로 (극단 소수 의견 자동 제외) + "1개월 날짜필터 불가" 안내
- `c7b221f` **네이버 최근 리포트 목표가 스크래핑** 추가 + 실패 시 야후 중앙값 자동 폴백
- `cc5662a` 목표가를 **2026·2027 EPS 양쪽으로 환산해 표로** 표시(리포트 EPS 기준연도 불명 대응)

### 데이터 소스 조사 결론 (중요 — 다시 조사하지 말 것)
- **yfinance 애널리스트 목표가**: `targetMeanPrice/targetMedianPrice/targetLowPrice/targetHighPrice/numberOfAnalystOpinions`
  제공. 단 **개별 애널리스트별 날짜가 없음** → "최근 1개월"로 못 좁힘. low/high는 **극단 1명**이라 범위가 비현실적으로 넓음 → **중앙값**이 가장 robust.
- **yfinance `recommendations`**: 기간별(0m/-1m/-2m/-3m) 투자의견 **개수**만(목표가 없음). `upgrades_downgrades`는 한국 종목 빈 값.
- **네이버 금융 리서치 목록** `finance.naver.com/research/company_list.naver?searchType=itemCode&itemCode={6자리}`:
  EUC-KR. 행에 종목명/제목/**증권사**/**작성일(YY.MM.DD)**/조회수 + `company_read.naver?nid=` 링크. **목록엔 목표가 없음**(마지막 숫자는 조회수).
- **네이버 리포트 상세** `company_read.naver?nid={nid}`: `목표가` 라벨 뒤 **첫 콤마숫자**가 목표가.
  추출 정규식: `목표가[\s\S]{0,150}?([\d]{1,3}(?:,[0-9]{3})+)`. (※ `<em>`로 감싸이지 않음 — em 패턴은 실패함.)
- **whynotsellreport.com**: 목표가 추적 사이트지만 **Next.js 클라이언트 렌더**(데이터가 HTML에 없음, 종목이 내부 번호 /stock/1,2,3…). API 역추적 필요 + 소규모 사이트라 운영 리스크 큼 → **채택 안 함**.

### 구현 (app.py)
- `recent_targets(code6)` (module top에 `import re, requests` 추가, `requirements.txt`에 `requests` 추가):
  `@st.cache_data(ttl=1800)`. 네이버 목록→최근 nid들→상세에서 목표가 추출, 최대 3개 `{date,broker,target}` 반환.
  **모든 단계 try/except, 실패 시 `[]` 반환**(차단·구조변경에도 안 깨짐). 한국 6자리 코드만.
- `apply_fetched`가 `naver_code`(resolved가 `\d{6}\.K[SQ]`면 6자리, 아니면 "") 저장. `an_mean/an_median/an_low/an_high/an_n`도 저장.
- 섹션 4 패널: `recent = recent_targets(naver_code)` 성공 → **최근 리포트 평균**, 실패/미국 → **야후 중앙값**.
  두 경로 모두 `_bench_table(target, label)`로 **2026·2027 EPS 양쪽 환산 배수를 표**로 표시(현재 배수 동행).

### ★ 핵심 함정/주의 (다음 세션)
- **(H) 네이버 스크래핑은 Railway(클라우드 IP)에서 차단될 수 있음.** 로컬은 됨. 배포 후 실제로 되는지는
  **앱 화면의 박스 제목**으로 확인: "최근 애널리스트 리포트 기준 배수 · 최근 N개"=성공 / "애널리스트 기준 배수 (참고) · 분석가 N명"=폴백.
  (배포 컨테이너 직접 테스트는 `railway ssh`인데 운영 서버라 자동승인 거부됨 — 사용자 승인 필요.) **2026-06-10 현재 운영 환경 성공/폴백 여부 미확인 — 사용자 확인 대기.**
- **(I) 리포트가 몇 년도 EPS로 목표가를 산정했는지 자동으로 알 수 없음**(PDF 본문, 증권사마다 다름).
  애널리스트는 보통 **다음 해(2027) 포워드 EPS** 기준 → 2026 EPS로 나누면 PER 과대. 그래서 **2026·2027 양쪽**을 표로 보여주고 "2027 기준이 현실적"이라 안내. 임의로 한 해만 쓰지 말 것.
- 목표가는 **price/EPS연도** 로 환산하므로, 같은 목표가라도 연도별 배수가 다름(표로 노출).

### 남은 TODO (이 기능 관련)
- 운영(Railway)에서 네이버 차단 시 대안: 프록시 경유, 또는 한국 종목 한정 다른 소스.
- 네이버 목록의 최근 리포트가 **한 증권사로 쏠릴 수 있음**(예: 삼성전자 최근 3개가 전부 미래에셋). 증권사별 dedupe 옵션 고려 가능(현재는 최근순 그대로, 목록에 증권사·날짜 노출해 투명).
- 미국 종목은 여전히 야후 중앙값만(날짜별 목표가 무료 소스 없음).

> ⚠️ **위 11장의 "네이버 스크래핑"은 12장에서 whynotsellreport.com API로 대체됨.** 네이버 코드는 더 이상 사용 안 함.

---

## 12. 업데이트 — 소스 교체(whynotsellreport) · PEG 수정가능 · 목표배수 디폴트 (2026-06-12)

### 커밋 (599db82 워크로그 이후)
- `da0d918` (네이버) 같은 증권사 중복 제거 — **곧 폐기됨**(아래 b78dd39로 대체)
- `b78dd39` 최근 리포트 소스 **네이버 스크래핑 → whynotsellreport.com API**로 교체
- `3501a38` **PEG 성장률 수정 가능**하게(기본=2026→2027 컨센서스 자동)
- `0dbe9d2` **목표배수 기본값 = 애널리스트 평균 목표 PER**(중립=평균, 보수/낙관 ±20%)
- `09f4180` **방어 강화** — recent_targets/평균계산 try-except로 감싸 운영 크래시 수정
- `c309683` 목표배수 기준연도 **2026 → 2027(보수적)**

### ★ whynotsellreport.com API (현재 최근 리포트 소스 — 재조사 불필요)
프론트는 Next.js(클라이언트 렌더, 데이터 HTML에 없음). **데이터는 `/api/*` JSON 엔드포인트**. robots.txt `Allow: /`.
백엔드 흔적: `stocks.allreview.kr`. 발견·사용 엔드포인트:
- **`/api/stocklist`** (335KB) → `[{id, code, name, remark(KOSPI/KOSDAQ), ...}]`. **code(6자리) → id 매핑**에 사용. (삼성전자 005930 → id **911**)
- **`/api/reports/sid/{id}`** (★메인, 종목별 전체 리포트, 삼성 ~2.4MB/5331건) →
  `[{id, stock_code_id, company_id, analyst_id, price(목표가), date("YYYY-MM-DD ..."), judge, title, description, analyst_name, company_name, ...}]`
  - **price=목표가, date=발표일, analyst_name=애널리스트**. ⚠️ **증권사(브로커리지) 이름 필드는 없음**(company_id/company_name은 *피커버 종목*을 가리킴, 증권사 아님). → **애널리스트 이름으로 하우스 구분**(보통 종목당 증권사별 1명이라 사실상 동일).
  - price=0/`"tbd"` analyst = 예고/플레이스홀더 → 필터.
- 기타(미사용): `/api/reports/dates/range/{id}`(날짜 목록), `/api/reports/from/`, `/api/reports/stockchart/sid/`, `/api/stock_info/sid/`, `/api/target_price_change`(전종목 최신 목표가 변경 피드).
- **장점 vs 네이버**: 단일 JSON 호출, 6월 리포트가 훨씬 완전(네이버는 미래에셋만 보였음), HTML 파싱 불필요.

### 구현 (app.py)
- `import re, requests` (모듈 top). `_WNS="https://whynotsellreport.com"`, `_WNS_HEADERS`.
- `_wns_stock_id(code6)` `@cache_data(ttl=86400)`: stocklist에서 code→id.
- `recent_targets(code6, want=5)` `@cache_data(ttl=1800)`: `/api/reports/sid/{id}` → price>0 필터 → 날짜 내림차순 → **애널리스트 중복 제거** → 최대 5명 `{date, broker(=애널), target}`.
  - **★ 전체 본문을 try/except로 감쌈 → 어떤 외부데이터/네트워크 오류에도 [] 반환(절대 예외 안 던짐).** `_to_num()`으로 가격 안전 변환(문자열 콤마 등).
- 세션 키 `naver_code`(이름만 네이버 잔재, 실제는 whynotsellreport용 6자리코드). apply_fetched가 resolved `\d{6}\.K[SQ]`→6자리로 세팅.

### ★ 운영 크래시 버그 & 방어 패턴 (09f4180) — 교훈
- **증상**: 로컬은 정상인데 **Railway에서 삼성전자 조회 시 빨간 에러**(조회 안 됨).
- **원인**: whynotsellreport 데이터 일부 항목의 `price`가 예상과 다른 형식이라 `(x.get("price") or 0) > 0` 에서 **str>int TypeError**. 이 처리부가 try/except 밖이라 전파됨. 로컬은 캐시된 깨끗한 5건만 봐서 재현 안 됨.
- **방어 원칙(앞으로도)**: 외부 데이터를 **처리하는 부분까지 전부** try/except로 감싸고, 숫자는 `_to_num` 같은 안전 변환을 쓸 것. 호출부도 `try: recent=recent_targets(...) except: recent=[]`로 이중 방어.

### 목표 배수 디폴트 (0dbe9d2 → c309683)
- 섹션 4: 기존 현재가 기반 8/10/12 → **애널리스트 평균 목표가 ÷ EPS = 평균 목표 PER**을 **중립 기본값**, 보수/낙관 ±20%.
- **기준연도는 2027(보수적)**: `ref_base = base_by_year["2027"] or ["2026"]`. 2027 EPS가 더 커서 같은 목표가라도 배수가 낮게(=보수적) 잡힘. (삼성 2026기준 10.9배 → 2027기준 **8.6배**)
- **새 종목시 자동 리셋**: 멀티플 number_input 키에 기본값 포함 `key=f"mult_mid_{method}_{sug_mid}"` → 종목(=애널평균) 바뀌면 새 디폴트로 리셋, 사용자가 수정하면 유지. (PEG 성장률 입력도 같은 패턴 `key=f"peg_g_{round(g_auto,2)}"`.)
- 애널 데이터 없으면(미국 등) 야후 중앙값, 그것도 없으면 현재 배수 → 10.0 순으로 폴백.

### PEG 성장률 수정 가능 (3501a38)
- 섹션 5 PER 결과의 PEG: 성장률을 **number_input으로 수정 가능**(기본=2026→2027 컨센서스 g_auto). 출처/한계(경기민감주 단년 성장률은 PEG를 과도하게 낮게 보이게 함) 안내. g≤0이면 PEG 미표시.
- 검증됨: g=26.9%는 버그 아님(yfinance `+1y growth`=0.2694와 동일).

### 다음 세션 메모
- `naver_code` 세션키는 사실 whynotsellreport용(리네이밍 안 함). 헷갈리지 말 것.
- whynotsellreport도 소규모 사이트라 다운/차단 가능 → 그때는 야후 중앙값으로 자동 폴백(앱 안 죽음). 운영에서 어느 쪽인지는 패널 제목으로 구분(11장 (H) 참고, "최근 애널리스트 리포트"=whynotsell 성공 / "애널리스트 기준 배수(참고)"=폴백).

---

## 13. 업데이트 — 미국 애널 목표가(야후) · 2027 통일 · 디자인 마감 (2026-06-12)

### 커밋 (555c8ba 워크로그 이후)
- `7385522` **미국 종목 애널 목표가 = 야후 `upgrades_downgrades`** (최근 2개월, 증권사별, 극단값 제외)
- `b9a52c9` 5번 결과 **기준연도 기본값 2026 → 2027**
- `7d67e50` **UI 마감 정리**(설명/주석 타이포·노트·메트릭·표·여백)

### ★ 미국 애널 목표가 소스 (재조사 불필요)
- **`yf.Ticker(symbol).upgrades_downgrades`** (US 종목은 채워짐, KR은 비어있음). DataFrame:
  - index = 발표일(Timestamp), 컬럼 = `Firm`(증권사), **`currentPriceTarget`(목표가)**, `priorPriceTarget`, `ToGrade`, `priceTargetAction`(Raises/Lowers).
  - → **API 키 없이** 날짜·증권사·목표가를 다 얻음. (앞 11장의 "야후는 날짜별 개별 목표가 없음" 결론을 이걸로 뒤집음 — `upgrades_downgrades`에 있었음!)
- `us_recent_targets(symbol, months=2, want=12)`: tz 제거 → `now - DateOffset(months=2)` 이후 필터 → **증권사별 최근 1건** → `{date, broker, target}`. 전부 try/except로 [] 보장.
- **공통 극단값 제거 `_drop_outliers(recs, band=0.35)`**: 4건↑일 때 **중앙값 ±35% 밖 제외**(KR·US 둘 다 적용). 제외분은 패널 캡션에 "❌제외"로 노출.

### 소스 분기 (섹션 4)
- `naver_code` 있으면 → whynotsellreport(`recent_targets`, unit="명").
- `us_symbol` 있으면 → 야후(`us_recent_targets`, unit="곳", src="Yahoo Finance · 최근 2개월").
- 둘 다 없으면 → 야후 중앙값(an_median) 폴백.
- `apply_fetched`가 resolved로 `naver_code`(KR 6자리) 또는 `us_symbol`(그 외) 세팅. setdefault에 `us_symbol` 추가.

### 보수적 기준 통일 (2027)
- 목표배수 디폴트(섹션4)도, 결과 기본연도(섹션5 `year_sel_result` default)도 **2027**. EPS가 더 커서 배수가 낮게(보수적) 잡힘.

### 디자인 마감 (7d67e50) — CSS 위주, 로직 무변경
- 전역 캡션 톤 통일(`[data-testid="stCaptionContainer"]` 색·줄간격), `.note` 콜아웃 클래스(하단 면책 등),
  `[data-testid="stMetric"]` 은은한 카드, `.stMarkdown table` 표 스타일, hr 얇게, 히어로 톤다운.
- 방향: **심플·정돈 우선(요란함 X)**. 추가 시 이 톤 유지.

### 현재 기능 전체 요약 (스냅샷)
PER/PBR/PSR + (PER에) PEG(성장률 수정가능) · 한국[whynotsellreport]/미국[야후 upgrades_downgrades] 최근 애널 목표가(2개월·극단값제외)
· 목표배수 디폴트=애널 평균(2027 보수적) · 콤마 입력 · 보수/중립/낙관 시나리오 · 2026/2027 비교 · 한국식 색상 · 깔끔 디자인.
