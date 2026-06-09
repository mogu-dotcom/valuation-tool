# 📈 밸류에이션 계산기

PER · PBR · PSR 방식으로 **목표가**와 **업사이드(상승여력)**를 쉽게 계산하는 주식 교육용 웹 도구입니다.
한국·미국 주식을 지원하며, 종목코드를 입력하면 현재가와 2026/2027 추정치를 자동으로 불러옵니다.
(자동으로 못 가져온 값은 직접 입력/수정할 수 있습니다.)

## 로컬에서 실행하기

```bash
# 1) 가상환경 만들기 (최초 1회)
py -m venv venv

# 2) 패키지 설치 (최초 1회)
venv\Scripts\python.exe -m pip install -r requirements.txt

# 3) 실행
venv\Scripts\streamlit.exe run app.py
```

브라우저에서 자동으로 `http://localhost:8501` 이 열립니다.

## 웹에 무료 배포하기 (Streamlit Community Cloud)

1. 이 폴더를 GitHub 저장소(public)에 올립니다.
2. https://share.streamlit.io 에 GitHub 계정으로 로그인합니다.
3. **New app** → 저장소·브랜치·`app.py` 선택 → **Deploy**.
4. 몇 분 뒤 `https://<이름>.streamlit.app` 주소가 생성됩니다. 학생들은 이 링크만 클릭하면 됩니다.

> 클라우드에서 Python 버전을 고를 수 있습니다(3.12 권장). `requirements.txt`가 자동으로 설치됩니다.

## 사용법

1. **종목 선택** — 미국은 티커(`AAPL`), 한국은 6자리 코드(`005930`) 입력 후 *자동 조회*.
2. **값 확인·수정** — 자동으로 채워진 현재가·EPS·BPS·매출을 확인하고 필요하면 수정.
3. **평가 방식·연도** — PER/PBR/PSR 중 선택, 기준 연도(2026/2027) 선택.
4. **목표 배수** — 보수/중립/낙관 세 가지 배수 입력(현재 배수 기준으로 자동 제안됨).
5. **결과** — 시나리오별 목표가와 업사이드를 카드·막대그래프로 확인.
