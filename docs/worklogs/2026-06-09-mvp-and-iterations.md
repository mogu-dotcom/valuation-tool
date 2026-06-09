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
