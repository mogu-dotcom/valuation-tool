# -*- coding: utf-8 -*-
"""
밸류에이션 계산기 (PER / PBR / PSR)
- 종목코드를 넣으면 현재가 + 2026/2027 추정치를 자동으로 불러와 편집 가능한 칸에 채움
- 목표 배수(보수/중립/낙관)를 넣으면 목표가와 업사이드(상승여력)를 계산
주식 교육용 — 누구나 쉽고 예쁘게 쓰는 것이 최우선
"""

import streamlit as st
import pandas as pd
import altair as alt
import yfinance as yf

# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------
st.set_page_config(page_title="밸류에이션 계산기", page_icon="📈", layout="centered")

# 한국식 상승/하락 색상 (상승=빨강, 하락=파랑)
UP_COLOR = "#e8392b"     # 빨강 (상승여력 +)
DOWN_COLOR = "#1f6fde"   # 파랑 (상승여력 -)
BRAND = "#6c5ce7"        # 포인트 보라

FIELDS = ["price", "eps_2026", "eps_2027", "bps_2026", "bps_2027",
          "rev_2026", "rev_2027", "shares", "sps_2026", "sps_2027"]
for f in FIELDS:
    st.session_state.setdefault(f, 0.0)
st.session_state.setdefault("currency", "")
st.session_state.setdefault("name", "")
st.session_state.setdefault("loaded", False)
for _k in ("an_mean", "an_low", "an_high"):
    st.session_state.setdefault(_k, 0.0)
st.session_state.setdefault("an_n", 0)


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
                "target_low": info.get("targetLowPrice"),
                "target_high": info.get("targetHighPrice"),
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
    st.session_state["an_low"] = float(data.get("target_low") or 0.0)
    st.session_state["an_high"] = float(data.get("target_high") or 0.0)
    st.session_state["an_n"] = int(data.get("n_analysts") or 0)
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


def fmt_big(v):
    """매출 등 큰 금액을 조/억(원) 또는 B/M($)로 읽기 쉽게."""
    if not v:
        return "-"
    if is_krw():
        if abs(v) >= 1e12:
            return f"{v/1e12:,.1f}조원"
        if abs(v) >= 1e8:
            return f"{v/1e8:,.0f}억원"
        return f"{v:,.0f}원"
    if abs(v) >= 1e9:
        return f"${v/1e9:,.1f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:,.0f}M"
    return f"${v:,.0f}"


def fmt_shares(v):
    if not v:
        return "-"
    if v >= 1e8:
        return f"{v/1e8:,.1f}억 주"
    return f"{v:,.0f} 주"


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
#MainMenu, footer, header [data-testid="stToolbar"] {visibility: hidden;}
.block-container {padding-top: 1.4rem; padding-bottom: 3rem; max-width: 760px;}

/* 히어로 */
.hero {
    background: linear-gradient(135deg, #6c5ce7 0%, #8e7bf0 55%, #a29bfe 100%);
    border-radius: 20px; padding: 26px 28px; margin-bottom: 18px;
    box-shadow: 0 10px 30px rgba(108,92,231,.28);
}
.hero h1 {color:#fff; font-size: 1.7rem; font-weight: 800; margin:0; letter-spacing:-.5px;}
.hero p {color: rgba(255,255,255,.92); margin:.4rem 0 0; font-size:.96rem;}

/* 섹션 라벨 */
.sec {font-weight: 800; font-size: 1.05rem; margin: 6px 0 2px; color:#2d3436;}
.sec .num {display:inline-flex; align-items:center; justify-content:center;
    width:22px; height:22px; border-radius:7px; background:#efeafe; color:#6c5ce7;
    font-size:.8rem; font-weight:800; margin-right:7px;}

/* 결과 헤드라인 */
.headline {
    border-radius: 18px; padding: 22px 24px; margin: 6px 0 14px; color:#fff;
    box-shadow: 0 8px 24px rgba(0,0,0,.10);
}
.headline .cap {font-size:.82rem; opacity:.9; font-weight:600; letter-spacing:.3px;}
.headline .price {font-size: 2.15rem; font-weight: 800; margin:.15rem 0 .1rem; letter-spacing:-1px;}
.headline .up {font-size: 1.05rem; font-weight: 700;}
.headline .from {font-size:.8rem; opacity:.92; margin-top:.5rem;}

/* 시나리오 카드 */
.scn-row {display:flex; gap:10px; margin: 2px 0 8px;}
.scn {flex:1; background:#fff; border:1px solid #eee; border-radius:14px;
    padding:14px 10px; text-align:center; box-shadow:0 2px 10px rgba(0,0,0,.04);}
.scn.mid {border:2px solid #6c5ce7; box-shadow:0 4px 16px rgba(108,92,231,.16);}
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
  <h1>📈 밸류에이션 계산기</h1>
  <p>종목을 고르고 목표 배수만 넣으면 <b>목표주가</b>와 <b>상승여력</b>이 바로 나와요 · PER · PBR · PSR · 한국/미국</p>
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

ref_base = base_by_year["2026"] or base_by_year["2027"]
cur_mult = (price / ref_base) if ref_base else 0.0
sug_mid = round(cur_mult, 1) if cur_mult else 10.0
sug_low = round(sug_mid * 0.8, 1)
sug_high = round(sug_mid * 1.2, 1)

if cur_mult:
    st.caption(f"이 회사가 받을 만한 **{method} 배수**를 정하세요. 한 번 정하면 결과에서 연도(2026/2027)만 "
               f"바꿔가며 비교할 수 있어요.　참고 · 현재 {method} ≈ **{cur_mult:,.1f}배**")
else:
    st.caption(f"이 회사가 받을 만한 **{method} 배수**를 정하세요. 한 번 정하면 결과에서 연도만 바꿔 비교할 수 있어요.")

t1, t2, t3 = st.columns(3)
m_low = t1.number_input("🔵 보수", min_value=0.0, value=sug_low, step=0.1, key=f"mult_low_{method}")
m_mid = t2.number_input("⚪ 중립", min_value=0.0, value=sug_mid, step=0.1, key=f"mult_mid_{method}")
m_high = t3.number_input("🔴 낙관", min_value=0.0, value=sug_high, step=0.1, key=f"mult_high_{method}")

# 애널리스트 컨센서스 기준 배수 (참고) — 목표주가 ÷ 기준값으로 역산
an_mean = st.session_state.get("an_mean", 0.0)
if an_mean and ref_base:
    ref_year = "2026" if base_by_year["2026"] else "2027"
    an_low = st.session_state.get("an_low", 0.0)
    an_high = st.session_state.get("an_high", 0.0)
    an_n = st.session_state.get("an_n", 0)
    mean_mult = an_mean / ref_base
    with st.container(border=True):
        st.markdown("**📋 애널리스트 기준 배수 (참고)**"
                    + (f"　·　분석가 {an_n}명" if an_n else ""))
        ac1, ac2 = st.columns(2)
        ac1.metric(f"현재 {method}", f"{cur_mult:,.1f}배")
        delta = f"현재比 {(mean_mult / cur_mult - 1) * 100:+.0f}%" if cur_mult else None
        ac2.metric(f"애널리스트 평균 목표 {method}", f"{mean_mult:,.1f}배", delta, delta_color="off")
        rng = ""
        if an_low and an_high:
            rng = (f"　개별 애널리스트 최저~최고: **{an_low / ref_base:,.1f} ~ {an_high / ref_base:,.1f}배** "
                   f"(목표가 {fmt_price(an_low)} ~ {fmt_price(an_high)})")
        st.caption(
            f"애널리스트 평균 목표주가 **{fmt_price(an_mean)}**를 {ref_year} {method} 기준값으로 환산했어요.{rng}\n\n"
            f"👉 **평균 {mean_mult:,.1f}배를 기준점**으로 보수/중립/낙관을 정해보세요. "
            "(최저·최고는 가장 비관/낙관적인 애널리스트 **1명** 기준이라 폭이 넓을 수 있어요 · 야후 파이낸스 최신 컨센서스)")

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
                            default="2026", key="year_sel_result") or "2026"
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
    hcolor = UP_COLOR if mid_up >= 0 else DOWN_COLOR
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

    # PER일 때 PEG도 함께 표기 (PEG = PER ÷ 이익성장률)
    if method == "PER":
        e26v, e27v = st.session_state["eps_2026"], st.session_state["eps_2027"]
        g = ((e27v / e26v - 1) * 100) if (e26v and e27v and e26v > 0) else None
        if g and g > 0:
            cur_peg = (price / base) / g
            verdict = ("성장 대비 저평가" if cur_peg < 0.9
                       else "대체로 적정" if cur_peg <= 1.1 else "성장 대비 고평가")
            # ① PEG 숫자를 먼저 크게
            st.markdown("#### 📐 PEG &nbsp;<span style='font-size:.78rem;color:#8a8f99'>"
                        "성장성까지 반영한 밸류에이션</span>", unsafe_allow_html=True)
            pc1, pc2, pc3, pc4 = st.columns(4)
            pc1.metric("현재 PEG", f"{cur_peg:.2f}", verdict, delta_color="off")
            pc2.metric("🔵 보수 목표", f"{m_low/g:.2f}")
            pc3.metric("⚪ 중립 목표", f"{m_mid/g:.2f}")
            pc4.metric("🔴 낙관 목표", f"{m_high/g:.2f}")
            # ② 부가 설명은 아래에
            st.caption(f"**PEG = PER ÷ 연간 EPS 성장률**(여기선 {g:,.1f}%).  "
                       f"숫자가 **1이면 적정**, 1보다 낮으면 성장 대비 **저평가**, 높으면 **고평가**로 봅니다.")
        else:
            st.caption("📐 PEG: 2027 EPS가 2026보다 커야(이익 성장 +) 함께 표시할 수 있어요.")

st.markdown("<br>", unsafe_allow_html=True)
st.caption("⚠️ 교육용 도구입니다. 자동 추정치는 부정확할 수 있으니 투자 판단의 유일한 근거로 쓰지 마세요.")
