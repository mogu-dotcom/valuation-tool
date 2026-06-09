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
          "rev_2026", "rev_2027", "shares"]
for f in FIELDS:
    st.session_state.setdefault(f, 0.0)
st.session_state.setdefault("currency", "")
st.session_state.setdefault("name", "")
st.session_state.setdefault("loaded", False)


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

            data = {
                "resolved": tk,
                "currency": info.get("currency", ""),
                "name": info.get("shortName") or info.get("longName") or tk,
                "price": float(price),
                "shares": info.get("sharesOutstanding"),
                "bps_cur": info.get("bookValue"),
                "eps_2026": None, "eps_2027": None,
                "rev_2026": None, "rev_2027": None,
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
    st.session_state["loaded"] = True


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

POPULAR_KR = [("삼성전자", "005930"), ("SK하이닉스", "000660"),
              ("NAVER", "035420"), ("카카오", "035720")]
POPULAR_US = [("Apple", "AAPL"), ("Tesla", "TSLA"),
              ("NVIDIA", "NVDA"), ("Microsoft", "MSFT")]

st.caption("🇰🇷 인기 한국 종목")
kr_cols = st.columns(4)
for i, (nm, cd) in enumerate(POPULAR_KR):
    if kr_cols[i].button(nm, key=f"kr_{cd}", width='stretch'):
        st.session_state["code_input"] = cd
        do_fetch(cd)

st.caption("🇺🇸 인기 미국 종목")
us_cols = st.columns(4)
for i, (nm, cd) in enumerate(POPULAR_US):
    if us_cols[i].button(nm, key=f"us_{cd}", width='stretch'):
        st.session_state["code_input"] = cd
        do_fetch(cd)

c_in, c_btn = st.columns([3, 1], vertical_alignment="bottom")
code = c_in.text_input("직접 입력 (미국: AAPL · 한국: 005930)", key="code_input",
                       placeholder="종목코드를 입력하세요")
if c_btn.button("🔍 조회", width='stretch', type="primary"):
    do_fetch(code)

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
st.markdown('<div class="sec"><span class="num">2</span>평가 방식 · 기준 연도</div>', unsafe_allow_html=True)

m1, m2 = st.columns([3, 2], vertical_alignment="center")
method = m1.segmented_control("평가 방식", ["PER", "PBR", "PSR"],
                              default="PER", key="method_sel") or "PER"
year = m2.segmented_control("기준 연도", ["2026", "2027"],
                            default="2026", key="year_sel") or "2026"

METHOD_DESC = {
    "PER": ("EPS", "주당순이익", "회사가 버는 **이익** 기준 평가예요. 1주가 1년에 버는 순이익(EPS)을 사용해요."),
    "PBR": ("BPS", "주당순자산", "회사의 **자산** 기준 평가예요. 1주에 담긴 순자산(BPS)을 사용해요."),
    "PSR": ("SPS", "주당매출", "회사의 **매출** 기준 평가예요. 매출을 주식 수로 나눈 주당매출(SPS)을 사용해요."),
}
base_label, base_name, desc = METHOD_DESC[method]
st.caption(f"**{method} · {year}년** 선택됨 — {desc}")

st.divider()

# ---------------------------------------------------------------------------
# 3. 값 확인 · 수정 (선택한 방식에 필요한 칸만)
# ---------------------------------------------------------------------------
st.markdown('<div class="sec"><span class="num">3</span>값 확인 · 수정</div>', unsafe_allow_html=True)
st.caption("자동으로 채워진 값을 그대로 쓰거나, 빈칸·틀린 값은 직접 고치세요. (모든 칸 편집 가능)")

with st.container(border=True):
    st.number_input("💵 현재가", key="price", min_value=0.0, step=1.0, format="%.2f",
                    help="지금 시장에서 거래되는 1주 가격. 상승여력 계산의 기준이에요.")

    if method == "PER":
        a, b = st.columns(2)
        a.number_input("2026 EPS", key="eps_2026", step=0.01, format="%.2f",
                       help="주당순이익 = 순이익 ÷ 주식 수. '1주가 1년에 버는 순이익'.")
        b.number_input("2027 EPS", key="eps_2027", step=0.01, format="%.2f")
        base = st.session_state[f"eps_{year}"]
    elif method == "PBR":
        a, b = st.columns(2)
        a.number_input("2026 BPS", key="bps_2026", step=0.01, format="%.2f",
                       help="주당순자산 = 순자산(자본) ÷ 주식 수. '1주에 담긴 장부상 재산'.")
        b.number_input("2027 BPS", key="bps_2027", step=0.01, format="%.2f")
        st.caption("※ 미래 BPS는 자동 제공이 거의 없어 '현재 BPS'로 채워둡니다. 필요시 수정하세요.")
        base = st.session_state[f"bps_{year}"]
    else:  # PSR
        a, b = st.columns(2)
        a.number_input("2026 매출 (전체)", key="rev_2026", step=1.0, format="%.0f",
                       help="회사 전체 매출액. 발행주식수로 나눠 '주당매출'로 환산해요.")
        b.number_input("2027 매출 (전체)", key="rev_2027", step=1.0, format="%.0f")
        st.number_input("발행주식수", key="shares", min_value=0.0, step=1.0, format="%.0f",
                        help="회사가 발행한 전체 주식 수.")
        shares = st.session_state["shares"]
        rev = st.session_state[f"rev_{year}"]
        base = (rev / shares) if shares else 0.0
        if rev and shares:
            st.caption(f"→ {year} 주당매출(SPS) = {fmt_big(rev)} ÷ {fmt_shares(shares)} "
                       f"= **{fmt_price(base)}**")

price = st.session_state["price"]

st.divider()

# ---------------------------------------------------------------------------
# 4. 목표 배수
# ---------------------------------------------------------------------------
st.markdown('<div class="sec"><span class="num">4</span>목표 배수 입력</div>', unsafe_allow_html=True)

cur_mult = (price / base) if base else 0.0
sug_mid = round(cur_mult, 1) if cur_mult else 10.0
sug_low = round(sug_mid * 0.8, 1)
sug_high = round(sug_mid * 1.2, 1)

if cur_mult:
    st.caption(f"이 회사가 받을 만한 **{method} 배수**를 시나리오별로 정해보세요. "
               f"참고 · 현재 {method} ≈ **{cur_mult:,.1f}배** (현재가 ÷ {year} {base_label})")
else:
    st.caption(f"이 회사가 받을 만한 **{method} 배수**를 시나리오별로 정해보세요.")

t1, t2, t3 = st.columns(3)
m_low = t1.number_input("🔵 보수", min_value=0.0, value=sug_low, step=0.1,
                        key=f"mult_low_{method}_{year}")
m_mid = t2.number_input("⚪ 중립", min_value=0.0, value=sug_mid, step=0.1,
                        key=f"mult_mid_{method}_{year}")
m_high = t3.number_input("🔴 낙관", min_value=0.0, value=sug_high, step=0.1,
                         key=f"mult_high_{method}_{year}")

st.divider()

# ---------------------------------------------------------------------------
# 5. 결과
# ---------------------------------------------------------------------------
st.markdown('<div class="sec"><span class="num">5</span>결과</div>', unsafe_allow_html=True)

if not base or base <= 0:
    need = "매출/발행주식수" if method == "PSR" else base_label
    st.warning(f"**{year} {base_name}({base_label})** 값이 없어요. "
               f"위 3번에서 '{need}' 칸에 값을 입력하면 결과가 나타나요.")
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
      <div class="cap">중립 시나리오 ({mid_mult:.1f}배) 기준 목표주가</div>
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

st.markdown("<br>", unsafe_allow_html=True)
st.caption("⚠️ 교육용 도구입니다. 자동 추정치는 부정확할 수 있으니 투자 판단의 유일한 근거로 쓰지 마세요.")
