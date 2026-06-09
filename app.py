# -*- coding: utf-8 -*-
"""
밸류에이션 계산기 (PER / PBR / PSR)
- 종목코드를 넣으면 현재가 + 2026/2027 추정치를 자동으로 불러와 편집 가능한 칸에 채움
- 목표 배수(보수/중립/낙관)를 넣으면 목표가와 업사이드를 계산
주식 교육용 MVP — 누구나 쉽게 쓰는 것이 최우선
"""

import streamlit as st
import pandas as pd
import altair as alt
import yfinance as yf

# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------
st.set_page_config(page_title="밸류에이션 계산기", page_icon="📈", layout="centered")

# 입력 칸으로 쓰는 값들의 이름 목록 (세션에 저장해두고 자동조회 시 덮어씀)
FIELDS = [
    "price",
    "eps_2026", "eps_2027",
    "bps_2026", "bps_2027",
    "rev_2026", "rev_2027",
    "shares",
]
for f in FIELDS:
    st.session_state.setdefault(f, 0.0)
st.session_state.setdefault("currency", "")
st.session_state.setdefault("name", "")


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
                continue  # 이 후보로는 못 찾음 -> 다음 후보(.KQ 등)

            data = {
                "resolved": tk,
                "currency": info.get("currency", ""),
                "name": info.get("shortName") or info.get("longName") or tk,
                "price": float(price),
                "shares": info.get("sharesOutstanding"),
                "bps_cur": info.get("bookValue"),  # 현재 BPS
                "eps_2026": None, "eps_2027": None,
                "rev_2026": None, "rev_2027": None,
            }

            # EPS 추정치: 0y = 올해(2026), +1y = 내년(2027)
            try:
                ee = t.earnings_estimate
                if ee is not None and "avg" in ee.columns:
                    if "0y" in ee.index:
                        data["eps_2026"] = float(ee.loc["0y", "avg"])
                    if "+1y" in ee.index:
                        data["eps_2027"] = float(ee.loc["+1y", "avg"])
            except Exception:
                pass

            # 매출 추정치
            try:
                re_ = t.revenue_estimate
                if re_ is not None and "avg" in re_.columns:
                    if "0y" in re_.index:
                        data["rev_2026"] = float(re_.loc["0y", "avg"])
                    if "+1y" in re_.index:
                        data["rev_2027"] = float(re_.loc["+1y", "avg"])
            except Exception:
                pass

            # EPS가 비면 forwardEps/trailingEps로 보완
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
    # 미래 BPS는 거의 제공되지 않아 '현재 BPS'를 두 해 모두에 시작값으로 채움(수정 가능)
    bps_cur = float(data.get("bps_cur") or 0.0)
    st.session_state["bps_2026"] = bps_cur
    st.session_state["bps_2027"] = bps_cur
    st.session_state["rev_2026"] = float(data.get("rev_2026") or 0.0)
    st.session_state["rev_2027"] = float(data.get("rev_2027") or 0.0)
    st.session_state["shares"] = float(data.get("shares") or 0.0)


# ---------------------------------------------------------------------------
# 표시용 도우미
# ---------------------------------------------------------------------------
def cur_symbol():
    return "₩" if st.session_state.get("currency") == "KRW" else "$"


def fmt_price(v):
    if v is None:
        return "-"
    sym = cur_symbol()
    if st.session_state.get("currency") == "KRW":
        return f"{sym}{v:,.0f}"
    return f"{sym}{v:,.2f}"


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
st.title("📈 밸류에이션 계산기")
st.caption("종목을 고르고 목표 배수를 넣으면 **목표가**와 **업사이드(상승여력)**를 바로 계산해 줍니다. "
           "PER · PBR · PSR 세 가지 방식 지원 · 한국/미국 주식")

# --- 1. 종목 입력 + 자동 조회 -------------------------------------------------
st.subheader("1️⃣ 종목 선택")
c_in, c_btn = st.columns([3, 1])
code = c_in.text_input(
    "종목코드",
    placeholder="미국: AAPL  ·  한국: 005930",
    help="미국 주식은 영문 티커(예: AAPL, TSLA), 한국 주식은 6자리 숫자(예: 삼성전자 005930)를 입력하세요.",
)
c_btn.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
if c_btn.button("🔍 자동 조회", width='stretch'):
    if not code.strip():
        st.warning("종목코드를 먼저 입력하세요.")
    else:
        with st.spinner("데이터를 불러오는 중..."):
            data = fetch_data(code)
        if data:
            apply_fetched(data)
            st.success(f"불러왔습니다: **{data['name']}** ({data['resolved']})  ·  현재가 {fmt_price(data['price'])}")
            missing = [k for k in ["eps_2026", "eps_2027", "rev_2026", "rev_2027"] if not data.get(k)]
            if missing:
                st.info("일부 추정치는 자동으로 못 가져왔어요. 아래 칸에서 직접 입력/수정하면 됩니다. (특히 한국 주식·BPS)")
        else:
            st.error("자동 조회에 실패했습니다. 아래 칸에 값을 직접 입력해도 계산은 정상 작동합니다.")

if st.session_state.get("name"):
    st.markdown(f"**선택 종목:** {st.session_state['name']}  ·  통화: {st.session_state.get('currency') or '미상'}")

# --- 2. 평가 방식 / 기준 연도 (먼저 한 번만 선택) ----------------------------
st.subheader("2️⃣ 평가 방식 · 기준 연도")
c_m, c_y = st.columns(2)
method = c_m.radio("평가 방식", ["PER", "PBR", "PSR"], horizontal=True,
                   help="PER=이익(EPS) 기준 · PBR=자산(BPS) 기준 · PSR=매출 기준 평가")
year = c_y.radio("기준 연도", ["2026", "2027"], horizontal=True)

method_desc = {
    "PER": "이익 기준 — 주당순이익(EPS)을 사용합니다.",
    "PBR": "자산 기준 — 주당순자산(BPS)을 사용합니다.",
    "PSR": "매출 기준 — 매출을 발행주식수로 나눈 주당매출(SPS)을 사용합니다.",
}
st.caption(f"선택: **{method} · {year}년** 기준 — {method_desc[method]}")

# --- 3. 값 확인/수정 (선택한 방식에 필요한 칸만 표시) ------------------------
st.subheader("3️⃣ 값 확인 · 수정")
st.caption(f"**{method}** 계산에 필요한 값만 보여드려요. 자동으로 채워진 값을 쓰거나, "
           "빈칸·틀린 값은 직접 고치세요. (모든 칸 편집 가능)")

st.number_input("현재가", key="price", min_value=0.0, step=1.0, format="%.2f",
                help="지금 시장에서 거래되는 1주 가격. 업사이드 계산의 기준이 됩니다.")

if method == "PER":
    cc1, cc2 = st.columns(2)
    cc1.number_input("2026 EPS", key="eps_2026", step=0.01, format="%.2f",
                     help="주당순이익 = 회사 순이익을 전체 주식 수로 나눈 값. '1주가 1년에 버는 순이익'.")
    cc2.number_input("2027 EPS", key="eps_2027", step=0.01, format="%.2f")
    base = st.session_state[f"eps_{year}"]
    base_label, base_name = "EPS", "주당순이익"
elif method == "PBR":
    cc1, cc2 = st.columns(2)
    cc1.number_input("2026 BPS", key="bps_2026", step=0.01, format="%.2f",
                     help="주당순자산 = 회사 순자산(자본)을 주식 수로 나눈 값. '1주에 담긴 회사의 장부상 재산'.")
    cc2.number_input("2027 BPS", key="bps_2027", step=0.01, format="%.2f")
    st.caption("※ 미래 BPS는 자동 제공이 거의 없어 '현재 BPS'를 채워 둡니다. 필요하면 수정하세요.")
    base = st.session_state[f"bps_{year}"]
    base_label, base_name = "BPS", "주당순자산"
else:  # PSR
    cc1, cc2 = st.columns(2)
    cc1.number_input("2026 매출(전체)", key="rev_2026", step=1.0, format="%.0f",
                     help="회사 전체 매출액. PSR 계산 시 발행주식수로 나눠 '주당매출'로 환산합니다.")
    cc2.number_input("2027 매출(전체)", key="rev_2027", step=1.0, format="%.0f")
    st.number_input("발행주식수", key="shares", min_value=0.0, step=1.0, format="%.0f",
                    help="회사가 발행한 전체 주식 수. 매출을 이 값으로 나누면 주당매출(SPS)이 됩니다.")
    shares = st.session_state["shares"]
    rev = st.session_state[f"rev_{year}"]
    base = (rev / shares) if shares else 0.0
    base_label, base_name = "SPS", "주당매출"

price = st.session_state["price"]

# --- 4. 목표 배수 (보수/중립/낙관) -------------------------------------------
st.subheader("4️⃣ 목표 배수 입력")
st.caption(f"{method}을(를) 세 가지 시나리오로 입력하세요. '이 회사가 받을 만한 {method} 배수'를 뜻합니다.")

# 현재 배수 기준으로 보수/중립/낙관 기본값을 제안 (편집 가능)
cur_mult = (price / base) if base else 0.0
sug_mid = round(cur_mult, 1) if cur_mult else 10.0
sug_low = round(sug_mid * 0.8, 1)
sug_high = round(sug_mid * 1.2, 1)

mc1, mc2, mc3 = st.columns(3)
m_low = mc1.number_input("🟦 보수", min_value=0.0, value=sug_low, step=0.1,
                         key=f"mult_low_{method}_{year}")
m_mid = mc2.number_input("⬜ 중립", min_value=0.0, value=sug_mid, step=0.1,
                         key=f"mult_mid_{method}_{year}")
m_high = mc3.number_input("🟥 낙관", min_value=0.0, value=sug_high, step=0.1,
                          key=f"mult_high_{method}_{year}")
if cur_mult:
    st.caption(f"참고 · 현재 {method}(현재가 ÷ {year} {base_label}) ≈ **{cur_mult:,.1f}배**")

# --- 5. 결과 -----------------------------------------------------------------
st.subheader("5️⃣ 결과")

if not base or base <= 0:
    st.warning(f"{method} 계산에 필요한 **{year} {base_name}({base_label})** 값이 없습니다. "
               f"위 '{ '매출/발행주식수' if method=='PSR' else base_label }' 칸에 값을 입력하세요.")
elif not price or price <= 0:
    st.warning("**현재가**가 없어 업사이드를 계산할 수 없습니다. 현재가를 입력하세요.")
else:
    rows = []
    for label, mult in [("보수", m_low), ("중립", m_mid), ("낙관", m_high)]:
        target = mult * base
        upside = (target / price - 1) * 100
        rows.append({"시나리오": label, "목표배수": mult, "목표가": target, "업사이드": upside})
    df = pd.DataFrame(rows)

    # 큰 숫자 카드 (업사이드는 delta로 자동 초록/빨강)
    r1, r2, r3 = st.columns(3)
    for col, row in zip([r1, r2, r3], rows):
        col.metric(
            label=f"{row['시나리오']} ({row['목표배수']:.1f}배)",
            value=fmt_price(row["목표가"]),
            delta=f"{row['업사이드']:+.1f}%",
        )

    # 업사이드 막대그래프 (양수 초록 / 음수 빨강)
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("업사이드:Q", title="업사이드 (%)"),
            y=alt.Y("시나리오:N", sort=["보수", "중립", "낙관"], title=""),
            color=alt.condition(alt.datum.업사이드 > 0, alt.value("#22c55e"), alt.value("#ef4444")),
            tooltip=["시나리오", alt.Tooltip("목표가:Q", format=",.2f"),
                     alt.Tooltip("업사이드:Q", format="+.1f")],
        )
        .properties(height=160)
    )
    st.altair_chart(chart, width='stretch')

    # 요약 표
    show = df.copy()
    show["목표가"] = show["목표가"].map(fmt_price)
    show["목표배수"] = show["목표배수"].map(lambda x: f"{x:.1f}배")
    show["업사이드"] = show["업사이드"].map(lambda x: f"{x:+.1f}%")
    st.dataframe(show.set_index("시나리오"), width='stretch')

    st.caption(f"계산식 · 목표가 = 목표{method} × {year} {base_label}({base:,.2f})  |  "
               f"업사이드 = (목표가 ÷ 현재가 − 1) × 100")

st.divider()
st.caption("⚠️ 교육용 도구입니다. 자동 추정치는 부정확할 수 있으니 투자 판단의 근거로만 쓰지 마세요.")
