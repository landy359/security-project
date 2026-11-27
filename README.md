# MemWatch v3

정보보호 팀 프로젝트. Linux에서 프로그램을 실행하고 메모리 사용량(RSS)과 파일 기반 실행 코드의 무결성을 감시한다. 웹 대시보드에서 이미지 뷰어 또는 지뢰찾기를 선택하고, 정상 기준을 수집한 뒤 경고와 이벤트를 확인할 수 있다.

## 개발 환경

| 항목 | 팀 개발 환경 |
| --- | --- |
| 운영체제 | Ubuntu 데스크톱 또는 기존 Docker의 `security-desktop` Ubuntu 컨테이너 |
| Python | 3.10 이상, 가상환경 사용 |
| 웹 | Flask 3.1 이상 4 미만, `requirements.txt`로 설치 |
| GUI | Tkinter와 실행 중인 Linux 그래픽 세션(XFCE 등) |
| 저장소 | SQLite. 기준값과 이벤트는 실행 시 지정한 데이터 폴더에 저장 |
| 통합 테스트 | C 컴파일러(`cc`), GUI 세션 또는 Xvfb |

감시 기능은 Linux의 `/proc`를 사용한다. macOS나 Windows에서 작업할 때는 Docker Ubuntu 데스크톱의 터미널에서 아래 Linux 명령을 실행한다.

## 소스 받기

```bash
git clone https://github.com/landy359/security-project.git
cd security-project
```

아래 명령은 **MemWatch v3의 `app.py`와 `requirements.txt`가 있는 폴더**에서 실행한다. 수업 자료가 있는 로컬 프로젝트에서는 `코드 히스토리/MemWatch-v3`가 해당 폴더다. 기존 Docker 환경에서는 v2 폴더를 컨테이너에 연결된 `Codes` 아래에 두면 `/workspace/MemWatch-v3`에서 열 수 있다.

## Ubuntu에서 설치 및 실행

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py --bind 127.0.0.1
```

같은 Ubuntu 환경의 브라우저에서 [대시보드](http://127.0.0.1:5000)를 연다. 종료할 때는 실행 터미널에서 `Ctrl+C`를 누른다. 다른 데이터 폴더가 필요하면 `--data 경로`를 지정한다. 기본값은 소스 폴더 안의 `data/`다.

### 기존 Docker 수업 환경

호스트에서 `docker start security-desktop`으로 기존 컨테이너를 시작한다. [Ubuntu 데스크톱](https://127.0.0.1:3001)의 XFCE 터미널에서 실행한다. 컨테이너에 Tk가 설치되어 있어야 하며, 호스트에서 대시보드에 접속하려면 컨테이너를 만들 때 `127.0.0.1:5000:5000` 포트 매핑을 설정해야 한다.

```bash
cd /workspace/MemWatch-v3
python3 -m venv --system-site-packages /config/memwatch-venv
/config/memwatch-venv/bin/python -m pip install -r requirements.txt
/config/memwatch-venv/bin/python app.py --bind 0.0.0.0 --data /config/memwatch-data-v3
```

이 구성에서는 호스트 브라우저에서 [대시보드](http://127.0.0.1:5000)를 연다. `/config`는 기존 환경에서 가상환경과 감시 데이터를 두는 경로다.

## 처음 감시하기

1. 대시보드에서 이미지 뷰어 또는 지뢰찾기를 선택한다.
2. **작업을 마칠 때까지 측정**을 누르고 평소처럼 앱을 사용한다. 기본 최소 12개 표본이 모이면 **이번 실행 측정 완료**를 누른다. 기본 3회의 독립 실행을 완료한다.
3. 영역별 측정값을 검토하고 **측정값 저장**을 누른다.
4. **감시 시작**을 누르고 그래프, 경고, 이벤트가 갱신되는지 확인한다. 다른 환경이나 앱 버전에서 테스트할 때는 해당 환경에서 기준을 다시 측정한다.

## 동결 후 재개

- **일반 재개**는 해시 불일치로 동결된 대상을 정지 상태에서 검사한다. 기준 해시와 일치하면 재개한다.
- **강제 재개**는 현재 검사 결과를 확인한 뒤 사용자가 선택할 수 있다. 일반 대상은 재개 직후 다시 검사하고, 불일치가 남으면 다시 동결한다. 시연 대상은 최대 10초 안에 게임 창에서 **v1 복원**을 누른 뒤 **지금 검사**로 결과를 확인할 수 있다.
- 코드 무결성 카드에는 파일 기반 실행 코드 검사 범위와 제외된 매핑 수가 표시된다. 감시 중 검사 실패는 제한적으로 재시도하며, 세 번 연속 미확인이면 **검증 불가**를 표시한다.

## 코드와 테스트

| 경로 | 역할 |
| --- | --- |
| `app.py` | Flask 서버와 실행 옵션 |
| `monitor/` | 메모리 수집, 판정, 대상 제어, 기준 및 이벤트 저장 |
| `image_viewer.py`, `minesweeper.py` | 기본 감시 대상 |
| `templates/`, `static/` | 대시보드 화면 |
| `tests/` | 단위 테스트와 Linux 통합 테스트 |

```bash
.venv/bin/python -m unittest tests.test_core -v
.venv/bin/python -m unittest discover -v
```

Docker에서는 두 명령의 Python을 `/config/memwatch-venv/bin/python`으로 바꾼다. Linux 통합 테스트를 실행하려면 필요에 따라 `sudo apt install build-essential`로 컴파일러를 설치한다. GUI 테스트는 `DISPLAY`가 설정된 데스크톱 터미널에서 실행한다. 테스트 출력의 `skipped` 항목은 환경 조건을 확인한다.

## 문제 해결

| 증상 | 확인할 부분 |
| --- | --- |
| `No module named flask` | 실행에 쓰는 Python으로 `-m pip install -r requirements.txt`를 실행한다. |
| Tk를 불러올 수 없거나 창이 안 뜸 | `python3-tk` 설치와 `DISPLAY`를 확인하고 Ubuntu 데스크톱 터미널에서 다시 실행한다. |
| 호스트에서 Docker 대시보드 접속 실패 | 컨테이너 포트 매핑과 `--bind 0.0.0.0`을 확인한다. |
| 코드 검사 미확인 또는 권한 오류 | 대시보드의 검사 상세에서 원인을 확인한다. 감시기가 같은 Linux 환경에서 대상을 직접 실행했는지, 실행 사용자에게 해당 프로세스 읽기 권한이 있는지 확인한다. |

감시 기준과 실행 옵션은 [감시 기능 안내](docs/monitoring.md)를 참고한다.

## 팀 작업 흐름

1. 기본 브랜치의 최신 변경을 받은 뒤, 작업별 브랜치를 만든다. 예를 들어 `git switch -c docs/update-setup`을 실행한다.
2. 수정 후 관련 테스트를 실행하고, 화면을 바꿨다면 대시보드에서도 확인한다.
3. 변경을 커밋하고 `git push -u origin <브랜치명>`으로 올린 뒤 Pull Request를 연다. PR에는 변경 내용, 확인한 환경과 테스트 결과, 팀원이 추가로 설정해야 할 항목을 적는다.
4. 커밋할 파일은 `git status`로 확인한다. `.venv/`, `__pycache__/`, `.ruff_cache/`, `data/`, `tests/build/`, `.DS_Store`는 각자 환경에서 생성되므로 소스 커밋에서 제외한다.
