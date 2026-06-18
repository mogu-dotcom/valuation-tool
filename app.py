# -*- coding: utf-8 -*-
"""
밸류에이션 계산기 (PER / PBR / PSR)
- 종목코드를 넣으면 현재가 + 2026/2027 추정치를 자동으로 불러와 편집 가능한 칸에 채움
- 목표 배수(보수/중립/낙관)를 넣으면 목표가와 업사이드(상승여력)를 계산
주식 교육용 — 누구나 쉽고 예쁘게 쓰는 것이 최우선
"""

import re
import streamlit as st
import pandas as pd
import altair as alt
import requests
import yfinance as yf

# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------
st.set_page_config(page_title="밸류에이션 계산기", page_icon="📈", layout="centered")

# 한국식 상승/하락 색상 (상승=빨강, 하락=파랑)
UP_COLOR = "#e8392b"     # 빨강 (상승여력 +)
DOWN_COLOR = "#1f6fde"   # 파랑 (상승여력 -)

FIELDS = ["price", "eps_2026", "eps_2027", "bps_2026", "bps_2027",
          "rev_2026", "rev_2027", "shares", "sps_2026", "sps_2027"]
for f in FIELDS:
    st.session_state.setdefault(f, 0.0)
st.session_state.setdefault("currency", "")
st.session_state.setdefault("name", "")
st.session_state.setdefault("loaded", False)
for _k in ("an_mean", "an_median"):
    st.session_state.setdefault(_k, 0.0)
st.session_state.setdefault("an_n", 0)
st.session_state.setdefault("naver_code", "")
st.session_state.setdefault("us_symbol", "")


# ---------------------------------------------------------------------------
# 데이터 조회 (yfinance)
# ---------------------------------------------------------------------------
def resolve_tickers(code: str):
    """입력값을 야후 파이낸스용 종목코드 후보로 변환.
    - 한국: 6자리 숫자 -> .KS(코스피) 먼저, 실패 시 .KQ(코스닥)
    - 미국: 그대로 사용
    """
    code = code.strip().upper()
    if code.isdigit() and len(code) == 6:
        return [f"{code}.KS", f"{code}.KQ"]
    return [code]


@st.cache_data(ttl=600, show_spinner=False)
def fetch_data(code: str):
    """종목코드로 현재가 + 추정치를 가져온다. 못 가져오면 해당 값은 None."""
    for tk in resolve_tickers(code):
        try:
            t = yf.Ticker(tk)
            info = t.info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if not price:
                try:
                    price = t.fast_info.get("last_price")
                except Exception:
                    price = None
            if not price:
                continue

            # BPS 보강: ① bookValue ② 현재가÷PBR ③ 재무제표 자본총계÷발행주식수
            bps_cur = info.get("bookValue")
            if not bps_cur and info.get("priceToBook"):
                try:
                    bps_cur = float(price) / float(info["priceToBook"])
                except Exception:
                    bps_cur = None
            if not bps_cur:
                try:
                    bs = t.balance_sheet
                    sh0 = info.get("sharesOutstanding")
                    for row in ("Common Stock Equity", "Stockholders Equity",
                                "Total Equity Gross Minority Interest"):
                        if bs is not None and row in bs.index:
                            vals = bs.loc[row].dropna()
                            if len(vals) and sh0:
                                bps_cur = float(vals.iloc[0]) / float(sh0)
                                break
                except Exception:
                    pass

            data = {
                "resolved": tk,
                "currency": info.get("currency", ""),
                "name": info.get("shortName") or info.get("longName") or tk,
                "price": float(price),
                "shares": info.get("sharesOutstanding"),
                "bps_cur": bps_cur,
                "eps_2026": None, "eps_2027": None,
                "rev_2026": None, "rev_2027": None,
                "target_mean": info.get("targetMeanPrice"),
                "target_median": info.get("targetMedianPrice"),
                "n_analysts": info.get("numberOfAnalystOpinions"),
            }
            try:
                ee = t.earnings_estimate
                if ee is not None and "avg" in ee.columns:
                    if "0y" in ee.index:
                        data["eps_2026"] = float(ee.loc["0y", "avg"])
                    if "+1y" in ee.index:
                        data["eps_2027"] = float(ee.loc["+1y", "avg"])
            except Exception:
                pass
            try:
                re_ = t.revenue_estimate
                if re_ is not None and "avg" in re_.columns:
                    if "0y" in re_.index:
                        data["rev_2026"] = float(re_.loc["0y", "avg"])
                    if "+1y" in re_.index:
                        data["rev_2027"] = float(re_.loc["+1y", "avg"])
            except Exception:
                pass
            if not data["eps_2026"]:
                data["eps_2026"] = info.get("forwardEps") or info.get("trailingEps")
            return data
        except Exception:
            continue
    return None


_WNS = "https://whynotsellreport.com"
_WNS_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


@st.cache_data(ttl=86400, show_spinner=False)
def _wns_stock_id(code6: str):
    """whynotsellreport stocklist에서 6자리 코드 → 내부 종목 id 매핑."""
    if not code6:
        return None
    try:
        r = requests.get(f"{_WNS}/api/stocklist", headers=_WNS_HEADERS, timeout=8)
        for s in r.json():
            if s.get("code") == code6:
                return s.get("id")
    except Exception:
        return None
    return None


def _to_num(v):
    """문자열/숫자/None을 안전하게 float로. 실패 시 0.0."""
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return 0.0


@st.cache_data(ttl=1800, show_spinner="최근 애널리스트 리포트 불러오는 중...")
def recent_targets(code6: str, want: int = 5):
    """whynotsellreport.com API에서 최근 애널리스트 리포트 목표가를 수집.
    같은 애널리스트(보통 증권사당 1명 담당)는 가장 최근 1건만. 한국 종목만.
    네트워크/형식 문제 등 어떤 오류에도 절대 예외를 던지지 않고 []를 반환한다."""
    try:
        sid = _wns_stock_id(code6)
        if not sid:
            return []
        r = requests.get(f"{_WNS}/api/reports/sid/{sid}", headers=_WNS_HEADERS, timeout=8)
        data = r.json()
        if not isinstance(data, list):
            return []
        rows = [x for x in data
                if isinstance(x, dict) and _to_num(x.get("price")) > 0 and x.get("date")]
        rows.sort(key=lambda x: str(x.get("date", "")), reverse=True)  # 최신순
        out, seen = [], set()
        for x in rows:
            analyst = str(x.get("analyst_name") or "").strip()
            if not analyst or analyst.lower() == "tbd" or analyst in seen:
                continue
            seen.add(analyst)
            out.append({"date": str(x["date"])[:10], "broker": analyst,
                        "target": int(_to_num(x["price"]))})
            if len(out) >= want:
                break
        return out
    except Exception:
        return []


def _drop_outliers(recs, band: float = 0.35):
    """목표가가 중앙값에서 ±band 밖이면 '특히 다른 값'으로 보고 제외. 4건 이상일 때만 적용.
    반환: (남긴 목록, 제외된 목록)"""
    if len(recs) < 4:
        return recs, []
    ts = sorted(r["target"] for r in recs)
    n = len(ts)
    med = ts[n // 2] if n % 2 else (ts[n // 2 - 1] + ts[n // 2]) / 2
    if med <= 0:
        return recs, []
    lo, hi = med * (1 - band), med * (1 + band)
    kept = [r for r in recs if lo <= r["target"] <= hi]
    dropped = [r for r in recs if not (lo <= r["target"] <= hi)]
    return (kept or recs), dropped


@st.cache_data(ttl=1800, show_spinner="최근 애널리스트 목표가 불러오는 중...")
def us_recent_targets(symbol: str, months: int = 2, want: int = 12):
    """야후 upgrades_downgrades에서 미국 종목의 최근 N개월 증권사별 목표가 수집.
    같은 증권사는 가장 최근 1건. 어떤 오류에도 [] 반환."""
    try:
        ud = yf.Ticker(symbol).upgrades_downgrades
        if ud is None or len(ud) == 0 or "currentPriceTarget" not in ud.columns:
            return []
        ud = ud.copy()
        try:
            if getattr(ud.index, "tz", None) is not None:
                ud.index = ud.index.tz_localize(None)
        except Exception:
            pass
        cutoff = pd.Timestamp.now() - pd.DateOffset(months=months)
        ud = ud[ud.index >= cutoff].sort_index(ascending=False)
        out, seen = [], set()
        for dt, row in ud.iterrows():
            firm = str(row.get("Firm") or "").strip()
            tgt = _to_num(row.get("currentPriceTarget"))
            if not firm or firm in seen or tgt <= 0:
                continue
            seen.add(firm)
            out.append({"date": str(pd.Timestamp(dt).date()), "broker": firm, "target": tgt})
            if len(out) >= want:
                break
        return out
    except Exception:
        return []


def apply_fetched(data: dict):
    """조회 결과를 입력 칸(세션)에 채워 넣는다. None은 0으로."""
    st.session_state["currency"] = data.get("currency", "")
    st.session_state["name"] = data.get("name", "")
    st.session_state["price"] = float(data.get("price") or 0.0)
    st.session_state["eps_2026"] = float(data.get("eps_2026") or 0.0)
    st.session_state["eps_2027"] = float(data.get("eps_2027") or 0.0)
    bps_cur = float(data.get("bps_cur") or 0.0)
    st.session_state["bps_2026"] = bps_cur
    st.session_state["bps_2027"] = bps_cur
    st.session_state["rev_2026"] = float(data.get("rev_2026") or 0.0)
    st.session_state["rev_2027"] = float(data.get("rev_2027") or 0.0)
    st.session_state["shares"] = float(data.get("shares") or 0.0)
    # 주당매출(SPS) = 전체 매출 ÷ 발행주식수
    sh = st.session_state["shares"]
    st.session_state["sps_2026"] = (st.session_state["rev_2026"] / sh) if sh else 0.0
    st.session_state["sps_2027"] = (st.session_state["rev_2027"] / sh) if sh else 0.0
    # 애널리스트 목표주가 컨센서스
    st.session_state["an_mean"] = float(data.get("target_mean") or 0.0)
    st.session_state["an_median"] = float(data.get("target_median") or 0.0)
    st.session_state["an_n"] = int(data.get("n_analysts") or 0)
    _rc = re.match(r"(\d{6})\.K[SQ]$", data.get("resolved", ""))
    st.session_state["naver_code"] = _rc.group(1) if _rc else ""
    st.session_state["us_symbol"] = "" if _rc else data.get("resolved", "")
    st.session_state["loaded"] = True
    # 입력 위젯이 새로 불러온 값을 다시 읽도록 위젯 상태 초기화
    for wk in ("w_price", "w_eps_2026", "w_eps_2027", "w_bps_2026", "w_bps_2027",
               "w_sps_2026", "w_sps_2027"):
        st.session_state.pop(wk, None)


def do_fetch(code: str):
    if not code or not code.strip():
        st.session_state["_fetch_msg"] = ("warn", "종목코드를 먼저 입력하세요.")
        return
    with st.spinner("데이터를 불러오는 중..."):
        data = fetch_data(code)
    if data:
        apply_fetched(data)
        miss = [k for k in ["eps_2026", "eps_2027", "rev_2026", "rev_2027"] if not data.get(k)]
        st.session_state["_fetch_msg"] = (
            "ok",
            f"**{data['name']}** ({data['resolved']}) 불러옴 · 현재가 {fmt_price(data['price'])}"
            + ("  ·  일부 추정치는 자동 조회가 안 돼 직접 입력이 필요해요." if miss else ""),
        )
    else:
        st.session_state["_fetch_msg"] = (
            "err", "자동 조회에 실패했어요. 아래 칸에 값을 직접 입력해도 계산은 됩니다.")


# ---------------------------------------------------------------------------
# 표시용 도우미
# ---------------------------------------------------------------------------
def is_krw():
    return st.session_state.get("currency") == "KRW"


def cur_symbol():
    return "₩" if is_krw() else "$"


def fmt_price(v):
    if v is None:
        return "-"
    sym = cur_symbol()
    return f"{sym}{v:,.0f}" if is_krw() else f"{sym}{v:,.2f}"


def fmt_num(v):
    """천단위 콤마 표기. 원화는 정수, 달러는 소수 2자리."""
    if not v:
        return "-"
    return f"{v:,.0f}" if is_krw() else f"{v:,.2f}"


def _fmt_input(v, dec):
    return f"{v:,.{dec}f}"


def _parse_num(s):
    if s is None:
        return None
    s = str(s).replace(",", "").replace(" ", "").strip()
    if s == "":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def _commit_field(field, wk, dec):
    """입력 확정 시: 콤마 제거→숫자 파싱→영구 저장→콤마 포함 형식으로 다시 표시."""
    p = _parse_num(st.session_state.get(wk, ""))
    if p is None:  # 숫자가 아니면 마지막 정상값으로 복원
        p = float(st.session_state.get(field, 0.0) or 0.0)
    st.session_state[field] = p
    st.session_state[wk] = _fmt_input(p, dec)


def num_field(container, label, field, decimals=None, help=None):
    """천단위 콤마가 칸 '안'에 표시되는 숫자 입력칸 (텍스트 입력 기반).
    - 값을 영구 키(field)에 보관 → 평가 방식 전환으로 칸이 사라졌다 와도 유지
    - decimals=None이면 원화 0자리 / 달러 2자리 자동"""
    wk = "w_" + field
    dec = decimals if decimals is not None else (0 if is_krw() else 2)
    if wk not in st.session_state:
        st.session_state[wk] = _fmt_input(float(st.session_state.get(field, 0.0) or 0.0), dec)
    container.text_input(label, key=wk, help=help,
                         on_change=_commit_field, args=(field, wk, dec))
    p = _parse_num(st.session_state[wk])
    if p is not None:
        st.session_state[field] = p


# ---------------------------------------------------------------------------
# 스타일 (CSS)
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');

html, body, [class*="css"], .stApp, button, input, textarea, select {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
/* 라이트모드 고정 — 다크모드 사용자도 동일하게 밝게 보이도록 강제 */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], .block-container {
    background-color: #ffffff !important;
}
.stApp { color:#2d3436 !important; }
#MainMenu, footer {visibility: hidden;}
/* 상단 흰색 헤더 바 + 데코 라인 완전히 제거 (공간까지) */
header[data-testid="stHeader"], [data-testid="stDecoration"] {display: none !important; height: 0 !important;}
.block-container {padding-top: 1.1rem; padding-bottom: 3rem; max-width: 760px;}

/* 설명·주석 — 차분하고 읽기 쉽게 (전역 통일) */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
.stCaption, .stCaption p {
    color:#767e89 !important; line-height:1.62 !important; font-size:.82rem !important;
}
/* 구분선 — 얇고 은은하게 */
hr {margin:1.1rem 0 !important; border:none !important; border-top:1px solid #eef0f4 !important;}

/* 히어로 — 모던/심플 (밝은 카드 + 그라데이션 아이콘 마크) */
.hero {
    display:flex; align-items:center; gap:16px;
    padding: 22px 24px; margin: 2px 0 18px;
    background: linear-gradient(180deg,#fbfaff 0%, #ffffff 70%);
    border: 1px solid #ece9f8; border-radius: 20px;
    box-shadow: 0 1px 2px rgba(30,25,60,.03);
}
.hero-mark {
    flex:0 0 auto; width:52px; height:52px; border-radius:16px;
    display:flex; align-items:center; justify-content:center; font-size:1.5rem;
    background: linear-gradient(135deg,#6c5ce7,#a18cf5);
    box-shadow: 0 8px 18px rgba(108,92,231,.32);
}
.hero-body {min-width:0;}
.hero-kicker {font-size:.66rem; font-weight:800; letter-spacing:.14em;
    text-transform:uppercase; color:#9a8ee8; margin-bottom:3px;}
.hero h1 {font-size:1.55rem; font-weight:800; letter-spacing:-.6px; margin:0;
    color:#20242e; line-height:1.12;}
.hero h1 .grad {background:linear-gradient(118deg,#6c5ce7,#9d6bf2);
    -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;}
.hero p {margin:6px 0 0; font-size:.85rem; color:#8b919c;}
.hero-tags {display:flex; flex-wrap:wrap; gap:5px; margin-top:10px;}
.hero-tags span {font-size:.7rem; font-weight:700; color:#6f6889;
    background:#f4f2fc; border:1px solid #ece9f8; border-radius:7px; padding:2px 8px;}

/* 섹션 라벨 */
.sec {font-weight: 800; font-size: 1.04rem; margin: 8px 0 4px; color:#2d3436;}
.sec .num {display:inline-flex; align-items:center; justify-content:center;
    width:22px; height:22px; border-radius:7px; background:#efeafe; color:#6c5ce7;
    font-size:.8rem; font-weight:800; margin-right:8px;}

/* 노트(콜아웃) — 안내문을 깔끔한 박스로 */
.note {background:#f8f9fc; border-left:3px solid #d6dbf0; border-radius:8px;
    padding:9px 13px; font-size:.8rem; color:#616873; line-height:1.6; margin:2px 0 6px;}
.note b {color:#474c54;}

/* 입력 카드 모서리 정리 */
[data-testid="stVerticalBlockBorderWrapper"] {border-radius:14px !important;}

/* 메트릭 — 은은한 카드로 통일 */
[data-testid="stMetric"] {background:#fafbfd; border:1px solid #eef0f5;
    border-radius:12px; padding:10px 13px 8px;}
[data-testid="stMetricLabel"] p {font-size:.76rem !important; color:#767e89 !important;}
[data-testid="stMetricValue"] {font-size:1.22rem !important; font-weight:800;}

/* 마크다운 표(애널 기준 배수) — 깔끔하게 */
.stMarkdown table {border-collapse:collapse; width:100%; font-size:.85rem; margin:6px 0 2px;}
.stMarkdown thead th {background:#f6f7fb; color:#57606f; font-weight:700;
    padding:8px 11px; border-bottom:1px solid #e9ebf0;}
.stMarkdown tbody td {padding:8px 11px; border-bottom:1px solid #f1f2f6; color:#3a3f47;}
.stMarkdown th:first-child, .stMarkdown td:first-child {text-align:left;}
.stMarkdown th:not(:first-child), .stMarkdown td:not(:first-child) {text-align:right;}

/* 결과 헤드라인 */
.headline {border-radius: 16px; padding: 22px 24px; margin: 6px 0 14px; color:#fff;
    box-shadow: 0 6px 16px rgba(0,0,0,.08);}
.headline .cap {font-size:.82rem; opacity:.92; font-weight:600; letter-spacing:.3px;}
.headline .price {font-size: 2.1rem; font-weight: 800; margin:.15rem 0 .1rem; letter-spacing:-1px;}
.headline .up {font-size: 1.02rem; font-weight: 700;}
.headline .from {font-size:.8rem; opacity:.92; margin-top:.5rem;}

/* 시나리오 카드 */
.scn-row {display:flex; gap:10px; margin: 2px 0 8px;}
.scn {flex:1; background:#fff; border:1px solid #eef0f4; border-radius:14px;
    padding:14px 10px; text-align:center; box-shadow:0 1px 6px rgba(0,0,0,.03);}
.scn.mid {border:1.5px solid #6c5ce7; box-shadow:0 3px 12px rgba(108,92,231,.13);}
.scn .lab {font-size:.82rem; font-weight:700; color:#636e72;}
.scn .mlt {font-size:.74rem; color:#b2bec3; margin:.1rem 0 .4rem;}
.scn .pr {font-size:1.08rem; font-weight:800; color:#2d3436;}
.scn .up {font-size:.92rem; font-weight:800; margin-top:.2rem;}

/* 배지 */
.badge {display:inline-block; background:#f1f2f6; color:#57606f; border-radius:999px;
    padding:3px 11px; font-size:.8rem; font-weight:600; margin-right:6px;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 히어로 헤더
# ---------------------------------------------------------------------------
st.markdown("""
<div class="hero">
  <div class="hero-mark">📈</div>
  <div class="hero-body">
    <div class="hero-kicker">STOCK VALUATION</div>
    <h1>밸류에이션 <span class="grad">계산기</span></h1>
    <p>종목과 목표 배수만 넣으면 목표주가·상승여력을 즉시 계산해요</p>
    <div class="hero-tags"><span>PER</span><span>PBR</span><span>PSR</span><span>PEG</span><span>🇰🇷 한국</span><span>🇺🇸 미국</span></div>
  </div>
</div>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 1. 종목 선택
# ---------------------------------------------------------------------------
st.markdown('<div class="sec"><span class="num">1</span>종목 선택</div>', unsafe_allow_html=True)

POPULAR = [("삼성전자", "005930"), ("SK하이닉스", "000660"), ("NAVER", "035420"),
           ("카카오", "035720"), ("Apple", "AAPL"), ("Tesla", "TSLA"),
           ("NVIDIA", "NVDA"), ("Microsoft", "MSFT")]
POP_MAP = {nm: cd for nm, cd in POPULAR}


def _on_pick():
    nm = st.session_state.get("pop_pick")
    if nm:
        st.session_state["code_input"] = POP_MAP[nm]
        st.session_state["_pending_fetch"] = POP_MAP[nm]


# 메인: 검색창 (맨 위)
c_in, c_btn = st.columns([3, 1], vertical_alignment="bottom")
code = c_in.text_input("종목 검색", key="code_input",
                       placeholder="미국: AAPL   ·   한국: 005930")
search_clicked = c_btn.button("🔍 조회", width='stretch', type="primary")

# 인기 종목 태그 (검색창 아래, 간단한 pill)
st.pills("인기 종목 (눌러서 바로 조회)", list(POP_MAP.keys()),
         selection_mode="single", key="pop_pick", on_change=_on_pick)

# 조회 실행
if search_clicked:
    do_fetch(code)
elif st.session_state.pop("_pending_fetch", None):
    do_fetch(st.session_state["code_input"])

msg = st.session_state.pop("_fetch_msg", None)
if msg:
    kind, text = msg
    {"ok": st.success, "warn": st.warning, "err": st.error}[kind](text)

if st.session_state.get("loaded"):
    st.markdown(
        f'<span class="badge">📌 {st.session_state["name"]}</span>'
        f'<span class="badge">💱 {st.session_state.get("currency") or "—"}</span>'
        f'<span class="badge">💵 현재가 {fmt_price(st.session_state["price"])}</span>',
        unsafe_allow_html=True)

st.divider()

# ---------------------------------------------------------------------------
# 2. 평가 방식 · 기준 연도
# ---------------------------------------------------------------------------
st.markdown('<div class="sec"><span class="num">2</span>평가 방식</div>', unsafe_allow_html=True)

method = st.segmented_control("평가 방식", ["PER", "PBR", "PSR"],
                              default="PER", key="method_sel") or "PER"

METHOD_DESC = {
    "PER": ("EPS", "주당순이익", "회사가 버는 **이익** 기준 평가예요. 1주가 1년에 버는 순이익(EPS)을 사용해요."),
    "PBR": ("BPS", "주당순자산", "회사의 **자산** 기준 평가예요. 1주에 담긴 순자산(BPS)을 사용해요."),
    "PSR": ("SPS", "주당매출", "회사의 **매출** 기준 평가예요. 매출을 주식 수로 나눈 주당매출(SPS)을 사용해요."),
}
base_label, base_name, desc = METHOD_DESC[method]
st.caption(f"**{method}** 선택됨 — {desc}")

st.divider()

# ---------------------------------------------------------------------------
# 3. 값 확인 · 수정 (선택한 방식에 필요한 칸만)
# ---------------------------------------------------------------------------
st.markdown('<div class="sec"><span class="num">3</span>값 확인 · 수정</div>', unsafe_allow_html=True)
st.caption("자동으로 채워진 값을 그대로 쓰거나, 빈칸·틀린 값은 직접 고치세요. 칸 아래에 콤마(,) 표기를 함께 보여드려요.")

with st.container(border=True):
    num_field(st, "💵 현재가", "price",
              help="지금 시장에서 거래되는 1주 가격. 상승여력 계산의 기준이에요.")

    if method == "PER":
        a, b = st.columns(2)
        num_field(a, "2026 EPS", "eps_2026",
                  help="주당순이익 = 순이익 ÷ 주식 수. '1주가 1년에 버는 순이익'.")
        num_field(b, "2027 EPS", "eps_2027")
    elif method == "PBR":
        a, b = st.columns(2)
        num_field(a, "2026 BPS", "bps_2026",
                  help="주당순자산 = 순자산(자본) ÷ 주식 수. '1주에 담긴 장부상 재산'.")
        num_field(b, "2027 BPS", "bps_2027")
        st.caption("※ BPS는 미래 추정이 거의 없어 '현재 BPS'(현재가÷PBR)를 채워둡니다. 비어 있으면 직접 입력하세요.")
    else:  # PSR
        a, b = st.columns(2)
        num_field(a, "2026 주당매출 (SPS)", "sps_2026",
                  help="주당매출 = 전체 매출 ÷ 발행주식수. '1주가 1년에 올리는 매출'.")
        num_field(b, "2027 주당매출 (SPS)", "sps_2027")
        st.caption("※ 주당매출(SPS) = 전체 매출 ÷ 발행주식수. 자동 조회 값에서 계산해 채웁니다.")


def _base_for(yr):
    if method == "PER":
        return st.session_state[f"eps_{yr}"]
    if method == "PBR":
        return st.session_state[f"bps_{yr}"]
    return st.session_state[f"sps_{yr}"]


base_by_year = {"2026": _base_for("2026"), "2027": _base_for("2027")}
price = st.session_state["price"]

st.divider()

# ---------------------------------------------------------------------------
# 4. 목표 배수
# ---------------------------------------------------------------------------
st.markdown('<div class="sec"><span class="num">4</span>목표 배수 입력</div>', unsafe_allow_html=True)

# 기준 연도는 보수적으로 2027(다음 해, EPS가 더 큼 → 배수가 낮게 잡힘) 우선
ref_base = base_by_year["2027"] or base_by_year["2026"]
ref_year = "2027" if base_by_year["2027"] else "2026"
cur_mult = (price / ref_base) if ref_base else 0.0

# --- 애널리스트 기준 목표가를 먼저 계산 (디폴트 배수 + 아래 패널에서 공용) ---
an_mean = st.session_state.get("an_mean", 0.0)
an_median = st.session_state.get("an_median", 0.0) or an_mean
naver_code = st.session_state.get("naver_code", "")
us_symbol = st.session_state.get("us_symbol", "")
try:
    if naver_code:
        recent, src_label, unit = recent_targets(naver_code), "whynotsellreport.com", "명"
    elif us_symbol:
        recent, src_label, unit = us_recent_targets(us_symbol), "Yahoo Finance · 최근 2개월", "곳"
    else:
        recent, src_label, unit = [], "", ""
except Exception:
    recent, src_label, unit = [], "", ""
recent, dropped = _drop_outliers(recent)   # 중앙값에서 ±35% 밖 극단값 제외
try:
    if recent:
        bench_target = sum(x.get("target", 0) for x in recent) / len(recent)
    elif an_median:
        bench_target = an_median
    else:
        bench_target = 0.0
except Exception:
    bench_target = 0.0
bench_mult = (bench_target / ref_base) if (bench_target and ref_base) else 0.0

# 디폴트 목표 배수: 애널리스트 평균 목표 배수를 '중립'으로, 보수/낙관은 ±20%
basis = bench_mult or cur_mult or 10.0
sug_mid = round(basis, 1)
sug_low = round(sug_mid * 0.8, 1)
sug_high = round(sug_mid * 1.2, 1)

if bench_mult:
    st.caption(f"**중립** 기본값을 **애널리스트 평균 목표 {method} {bench_mult:,.1f}배**(**{ref_year} EPS 기준 · 보수적**)로 채웠어요. "
               f"보수/낙관은 ±20%. 자유롭게 바꾸세요.　참고 · 현재 {method} ≈ {cur_mult:,.1f}배")
elif cur_mult:
    st.caption(f"이 회사가 받을 만한 **{method} 배수**를 정하세요.　참고 · 현재 {method} ≈ **{cur_mult:,.1f}배**")
else:
    st.caption(f"이 회사가 받을 만한 **{method} 배수**를 정하세요.")

t1, t2, t3 = st.columns(3)
# 키에 기본값 포함 → 새 종목(=새 애널 평균)이면 자동 리셋, 같으면 사용자 수정값 유지
m_low = t1.number_input("🔵 보수", min_value=0.0, value=sug_low, step=0.1, key=f"mult_low_{method}_{sug_low}")
m_mid = t2.number_input("⚪ 중립", min_value=0.0, value=sug_mid, step=0.1, key=f"mult_mid_{method}_{sug_mid}")
m_high = t3.number_input("🔴 낙관", min_value=0.0, value=sug_high, step=0.1, key=f"mult_high_{method}_{sug_high}")


# 기준 배수 표(참고): 목표가를 2026·2027 EPS 양쪽으로 환산 (리포트가 어느 해 기준인지 알 수 없으므로)
def _bench_table(target_price, src_label):
    md = f"| EPS 기준 | 현재 {method} | {src_label} |\n|:--|--:|--:|\n"
    any_row = False
    for yr in ("2026", "2027"):
        b = base_by_year[yr]
        if b and price:
            md += f"| **{yr}** | {price / b:,.1f}배 | **{target_price / b:,.1f}배** |\n"
            any_row = True
    if any_row:
        st.markdown(md)


if bench_target and ref_base:
    with st.container(border=True):
        if recent:
            st.markdown(f"**📋 최근 애널리스트 기준 배수**　·　{len(recent)}{unit}")
            _bench_table(bench_target, f"리포트평균 {method}")
            lines = "　".join(f"· {x['date']} {x['broker']} {fmt_price(x['target'])}" for x in recent)
            drop_note = ""
            if dropped:
                drop_note = "　❌제외(극단값): " + ", ".join(
                    f"{x['broker']} {fmt_price(x['target'])}" for x in dropped)
            st.caption(
                f"{lines}{drop_note}\n\n"
                f"평균 목표주가 **{fmt_price(bench_target)}** (서로 다른 {len(recent)}{unit}, 같은 곳은 최근 1건"
                f"{', 극단값 제외' if dropped else ''}).  "
                "같은 목표가라도 **어느 해 EPS로 나누냐**에 따라 배수가 달라요 — 보통 **다음 해(2027) 실적** "
                "기준이 **더 보수적**이에요. "
                f"(출처: {src_label})")
        else:
            an_n = st.session_state.get("an_n", 0)
            st.markdown("**📋 애널리스트 기준 배수 (참고)**"
                        + (f"　·　분석가 {an_n}명" if an_n else ""))
            _bench_table(bench_target, f"애널 중앙값 {method}")
            st.caption(
                f"목표주가 **중앙값 {fmt_price(bench_target)}** 기준. 같은 목표가라도 어느 해 EPS로 나누냐에 따라 배수가 달라요"
                "(애널리스트는 보통 다음 해 실적 기준 → **2027 기준이 현실적**). "
                "한국 종목은 최근 리포트(whynotsellreport.com)를 우선 쓰고, 못 불러오면 이 컨센서스로 대체돼요.")

st.divider()

# ---------------------------------------------------------------------------
# 5. 결과
# ---------------------------------------------------------------------------
st.markdown('<div class="sec"><span class="num">5</span>결과</div>', unsafe_allow_html=True)


def _mid_upside(yr):
    b = base_by_year[yr]
    if not b or not price:
        return None
    return (m_mid * b / price - 1) * 100


def _chip(yr, up):
    if up is None:
        return f'<span class="badge">📅 {yr} 자료없음</span>'
    col = UP_COLOR if up >= 0 else DOWN_COLOR
    ar = "▲" if up >= 0 else "▼"
    return f'<span class="badge">📅 {yr} 중립 <b style="color:{col}">{ar}{up:+.1f}%</b></span>'


# 올해/내년 상승여력 한눈 비교 (중립 기준)
st.markdown("**📊 올해 vs 내년 상승여력** (중립 시나리오 기준)", unsafe_allow_html=True)
st.markdown(_chip("2026", _mid_upside("2026")) + "　" + _chip("2027", _mid_upside("2027")),
            unsafe_allow_html=True)

# 연도를 태그로 선택 → 아래에 자세히 표시
year = st.segmented_control("기준 연도 (눌러서 자세히 보기)", ["2026", "2027"],
                            default="2027", key="year_sel_result") or "2027"
base = base_by_year[year]

if not base or base <= 0:
    st.warning(f"**{year} {base_name}({base_label})** 값이 없어요. "
               f"위 3번에서 '{base_name}' 칸에 값을 입력하면 결과가 나타나요.")
elif not price or price <= 0:
    st.warning("**현재가**가 없어 상승여력을 계산할 수 없어요. 위에서 현재가를 입력하세요.")
else:
    scns = []
    for label, mult in [("보수", m_low), ("중립", m_mid), ("낙관", m_high)]:
        target = mult * base
        upside = (target / price - 1) * 100
        scns.append((label, mult, target, upside))

    # 헤드라인 (중립 시나리오)
    _, mid_mult, mid_target, mid_up = scns[1]
    arrow = "▲" if mid_up >= 0 else "▼"
    grad = (f"linear-gradient(135deg,{UP_COLOR} 0%, #ff6b5e 100%)" if mid_up >= 0
            else f"linear-gradient(135deg,{DOWN_COLOR} 0%, #5b9bf0 100%)")
    st.markdown(f"""
    <div class="headline" style="background:{grad}">
      <div class="cap">{year}년 기준 · 중립 시나리오 ({mid_mult:.1f}배) 목표주가</div>
      <div class="price">{fmt_price(mid_target)}</div>
      <div class="up">{arrow} 상승여력 {mid_up:+.1f}%</div>
      <div class="from">현재가 {fmt_price(price)} → 목표가 {fmt_price(mid_target)}</div>
    </div>
    """, unsafe_allow_html=True)

    # 3개 시나리오 카드
    cards = ""
    for idx, (label, mult, target, upside) in enumerate(scns):
        c = UP_COLOR if upside >= 0 else DOWN_COLOR
        ar = "▲" if upside >= 0 else "▼"
        mid_cls = " mid" if idx == 1 else ""
        cards += (f'<div class="scn{mid_cls}"><div class="lab">{label}</div>'
                  f'<div class="mlt">{mult:.1f}배</div>'
                  f'<div class="pr">{fmt_price(target)}</div>'
                  f'<div class="up" style="color:{c}">{ar} {upside:+.1f}%</div></div>')
    st.markdown(f'<div class="scn-row">{cards}</div>', unsafe_allow_html=True)

    # 막대 차트 (상승=빨강 / 하락=파랑)
    df = pd.DataFrame({
        "시나리오": [s[0] for s in scns],
        "상승여력": [s[3] for s in scns],
        "목표가": [s[2] for s in scns],
    })
    bars = alt.Chart(df).mark_bar(cornerRadius=6, height=26).encode(
        x=alt.X("상승여력:Q", title="상승여력 (%)"),
        y=alt.Y("시나리오:N", sort=["보수", "중립", "낙관"], title=None),
        color=alt.condition(alt.datum.상승여력 >= 0,
                            alt.value(UP_COLOR), alt.value(DOWN_COLOR)),
        tooltip=[alt.Tooltip("시나리오:N"),
                 alt.Tooltip("상승여력:Q", format="+.1f"),
                 alt.Tooltip("목표가:Q", format=",.0f")],
    )
    labels = alt.Chart(df).mark_text(align="left", dx=6, fontWeight="bold").encode(
        x="상승여력:Q",
        y=alt.Y("시나리오:N", sort=["보수", "중립", "낙관"]),
        text=alt.Text("상승여력:Q", format="+.1f"),
        color=alt.condition(alt.datum.상승여력 >= 0,
                            alt.value(UP_COLOR), alt.value(DOWN_COLOR)),
    )
    st.altair_chart((bars + labels).properties(height=150), width='stretch')

    st.caption(f"계산식 · 목표가 = 목표{method} × {year} {base_label}({fmt_price(base)})  ·  "
               f"상승여력 = (목표가 ÷ 현재가 − 1) × 100  ·  🔴 빨강=상승 🔵 파랑=하락")

    # PER일 때 PEG도 함께 표기 (PEG = PER ÷ 이익성장률). 성장률은 수정 가능.
    if method == "PER":
        e26v, e27v = st.session_state["eps_2026"], st.session_state["eps_2027"]
        g_auto = ((e27v / e26v - 1) * 100) if (e26v and e27v and e26v > 0) else None
        st.markdown("#### 📐 PEG &nbsp;<span style='font-size:.78rem;color:#8a8f99'>"
                    "성장성까지 반영한 밸류에이션</span>", unsafe_allow_html=True)
        if g_auto is None:
            st.caption("📐 PEG: 2026·2027 EPS가 모두 있어야 계산할 수 있어요.")
        else:
            gc1, gc2 = st.columns([1, 2], vertical_alignment="center")
            # 키에 자동값을 포함 → EPS(=자동값)가 바뀌면 새 자동값으로 리셋, 같으면 사용자 수정값 유지
            g = gc1.number_input(
                "연간 EPS 성장률 (%)", value=round(g_auto, 1), step=0.5,
                key=f"peg_g_{round(g_auto, 2)}",
                help="PEG = PER ÷ 이 성장률. 기본값은 2026→2027 컨센서스 EPS 증가율(자동)이며 직접 수정할 수 있어요. "
                     "반도체 등 경기민감 업종은 한 해 성장률이 크게 튀어 PEG가 과도하게 낮게 보일 수 있으니, "
                     "정상화된 장기 성장률로 바꿔 보는 걸 권장해요.")
            gc2.caption(f"기본값 **{g_auto:,.1f}%** = (2027 EPS {fmt_num(e27v)} ÷ 2026 EPS {fmt_num(e26v)} − 1).  "
                        "이건 **한 해 컨센서스 성장률**이라, 경기민감주는 직접 보정하는 게 좋아요.")
            if g and g > 0:
                cur_peg = (price / base) / g
                verdict = ("성장 대비 저평가" if cur_peg < 0.9
                           else "대체로 적정" if cur_peg <= 1.1 else "성장 대비 고평가")
                pc1, pc2, pc3, pc4 = st.columns(4)
                pc1.metric("현재 PEG", f"{cur_peg:.2f}", verdict, delta_color="off")
                pc2.metric("🔵 보수 목표", f"{m_low / g:.2f}")
                pc3.metric("⚪ 중립 목표", f"{m_mid / g:.2f}")
                pc4.metric("🔴 낙관 목표", f"{m_high / g:.2f}")
                st.caption(f"**PEG = PER({price / base:,.1f}) ÷ 성장률({g:,.1f}%) = {cur_peg:.2f}**.  "
                           "1이면 적정, 1보다 낮으면 성장 대비 **저평가**, 높으면 **고평가**.")
            else:
                st.caption("성장률을 **0보다 큰 값**으로 입력해야 PEG를 계산할 수 있어요.")

st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
st.markdown(
    "<div class='note'>⚠️ <b>교육용 도구</b>입니다. 자동 추정치는 부정확할 수 있으니 "
    "투자 판단의 유일한 근거로 쓰지 마세요.</div>", unsafe_allow_html=True)
