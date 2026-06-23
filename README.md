# 눌림목 스캐너 대시보드

골든크로스(일봉 200선 + 4시간봉 200선) 후 **피보나치 0.382~0.618 눌림목** 구간에
들어온 종목을 매일 자동으로 찾아 **웹 대시보드**로 보여준다.
**나스닥100 + 코스피200**을 매 거래일 장 마감 후 클라우드가 알아서 스캔하고,
링크만 열면 차트와 매수/손절/익절 라인을 한눈에 볼 수 있다.

- 🖥️ **네 컴퓨터가 꺼져 있어도 돎** (GitHub 클라우드에서 실행)
- 💸 **무료** · 서버 관리 불필요
- 🔁 매일 두 번 자동 갱신 (한국장·미국장 마감 후)
- ⌨️ **코드/터미널 안 건드려도 됨** (아래 방법 A)

> 조건 충족 종목을 찾아주는 스크리너이며 투자 조언이 아님.
> 진입·손절·익절 판단은 본인 몫. (승률 100% 전략은 없음.)

---

# A. 완전 자동 대시보드 만들기 (터미널 없이)

핵심: 이 폴더를 **GitHub 저장소에 한 번 올리고 → Pages 켜기**. 그러면 끝.
이후엔 매일 알아서 돌고, 너는 주소만 열면 된다.

### 1) GitHub에 올리기 — 터미널 싫으면 **GitHub Desktop** 사용
1. [GitHub Desktop](https://desktop.github.com/) 설치 후 로그인(계정 `antifrg3`).
2. **File → New repository** → 이름 `ma-fib-scanner` → 생성.
3. 만들어진 폴더에 **이 폴더의 파일 전부 복사해 넣기**
   (`ma_fib_scanner.py`, `build_site.py`, `build_universe.py`,
    `requirements.txt`, `tickers_us.txt`, `tickers_kr.txt`, `.github` 폴더 등 전부).
4. GitHub Desktop으로 돌아오면 변경분이 보임 → **Commit** → **Publish/Push**.
   - 공개(Public)로 올리면 Pages가 무료. (비공개는 Pages에 유료 플랜 필요)

> 웹으로만 하고 싶으면: github.com에서 New repository → "uploading an existing file"로
> 드래그해서 올려도 됨. 단 `.github/workflows/dashboard.yml` 경로는 그대로 유지해야 함.

### 2) GitHub Pages 켜기 (한 번만)
저장소 페이지에서 **Settings → Pages → Build and deployment → Source** 를
**"GitHub Actions"** 로 선택. (그게 전부)

### 3) 첫 실행
저장소 **Actions** 탭 → 왼쪽 `dashboard` → **Run workflow** 버튼 클릭.
2~10분 뒤 완료되면 초록 체크 → 같은 화면이나 Settings→Pages에 **주소**가 뜬다:
```
https://antifrg3.github.io/ma-fib-scanner/
```
이 주소를 폰·맥 홈화면에 저장해두면 끝. 이후 매 거래일 자동 갱신된다.

### 자동 갱신 시각
| 갱신 | 시각(한국시간) | 이유 |
|---|---|---|
| 한국 종목 반영 | 평일 **16:00** | 코스피 마감(15:30) 후 |
| 미국 종목 반영 | 평일 **07:00** | 미국장 마감(밤사이) 후, 아침에 확인 |

(매번 미국·한국 둘 다 다시 스캔해서 페이지 전체를 새로 만든다. 시각을 바꾸려면
`.github/workflows/dashboard.yml` 의 `cron:` 줄만 수정 — cron은 UTC 기준.)

---

# B. 종목 범위

기본으로 **나스닥100 + 코스피200 전체**를 본다.
워크플로가 실행될 때마다 `build_universe.py` 가 **공식 구성종목을 자동으로 받아와**
`tickers_us.txt` / `tickers_kr.txt` 를 최신으로 다시 만든다(반기 리밸런싱 자동 반영).

직접 줄이거나 늘리고 싶으면 두 파일을 열어 수정해도 된다
(한국: 코스피 `005930.KS`, 코스닥 `247540.KQ`. 줄 끝 `# 삼성전자` 메모는 화면에 종목명으로 표시).

---

# C. (선택) 내 맥에서 먼저 미리보기

클라우드에 올리기 전에 결과를 보고 싶으면 터미널에서:
```bash
pip install -r requirements.txt pykrx
python3 build_universe.py     # 코스피200+나스닥100 최신 목록 생성
python3 build_site.py         # 스캔 후 site/index.html 생성
open site/index.html          # 브라우저로 열기
```

---

# D. (선택) 이메일로도 받기
대시보드 대신/함께 메일을 원하면, 메일 발송 스크립트도 들어있다.
```bash
export GMAIL_ADDRESS=... GMAIL_APP_PASSWORD=... EMAIL_TO=...
MARKET=us python3 ma_fib_scanner.py   # 미국 메일
MARKET=kr python3 ma_fib_scanner.py   # 한국 메일
```
(Gmail 앱 비밀번호: 구글 계정→보안→2단계 인증 켠 뒤 앱 비밀번호 16자리 발급.)

---

# E. 세부 조정 (`ma_fib_scanner.py` 상단 `Config`)
| 항목 | 의미 | 기본값 |
|---|---|---|
| `gc_lookback_days` | 골든크로스를 "최근"으로 볼 거래일 수 | 120 |
| `pre_cross_lookback` | 피보 저점 탐색 구간 | 60 |
| `zone_min` / `zone_max` | 대시보드에 올릴 되돌림 범위 | 0.30 ~ 0.70 |
| `buy_levels` | 분할매수 라인 | 0.382, 0.5, 0.618 |

---

# 참고 / 주의
- **4시간봉 200선**은 TradingView와 완전히 같진 않다(yfinance 1h→4h 리샘플). 1차 필터로
  쓰고 최종 확인은 증권사/TradingView 권장. 한국 종목은 1h가 부실하면 약 100일 일봉MA로 자동 근사.
- **Yahoo 데이터**: 드물게 클라우드 IP가 일시 차단되면 그날 일부 종목이 비어 보일 수 있다.
  다음 실행에서 회복된다. 자주 문제면 C(맥 로컬)로 돌려도 된다.
- 데이터 출처: Yahoo Finance.
