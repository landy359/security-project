# MemWatch v3

정보보호 팀 프로젝트. Linux에서 프로그램을 실행하고 메모리 사용량(RSS)과 파일 기반 실행 코드의 무결성을 감시한다. 웹 대시보드에서 이미지 뷰어 또는 지뢰찾기를 선택하고, 정상 기준을 수집한 뒤 경고와 이벤트를 확인할 수 있다.

## 실행 전 준비

- **Ubuntu 데스크톱 사용자**는 [A. Ubuntu에서 실행](#a-ubuntu에서-실행)을 따라간다.
- **macOS·Windows 사용자**는 Docker Desktop을 설치하고 실행한 다음 [B. Docker Desktop에서 실행](#b-docker-desktop에서-실행)을 따라간다.
- MemWatch는 Linux의 `/proc`로 메모리를 읽는다. Python 3.10 이상, Tkinter, Flask 및 그래픽 데스크톱 세션이 필요하다.

## A. Ubuntu에서 실행

Ubuntu 데스크톱에서 **터미널**을 연다. 모든 명령은 같은 터미널에서 순서대로 실행한다.

### 1. Git과 Python 설치

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-tk
python3 --version
```

### 2. 소스 받기

```bash
git clone https://github.com/landy359/security-project.git
cd security-project
ls app.py requirements.txt
```

`ls` 출력에 두 파일이 보이면 올바른 폴더다. 이미 저장소를 받아 뒀다면 해당 폴더로 이동한다. 이후 Python 명령은 이 폴더에서 실행한다.

### 3. 가상환경 만들고 의존성 설치

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

### 4. 서버 시작

```bash
.venv/bin/python app.py --bind 127.0.0.1
```

터미널에 실행 주소가 나오면 Ubuntu 브라우저에서 [MemWatch 대시보드](http://127.0.0.1:5000)를 열고 [처음 감시하기](#처음-감시하기)로 이동한다. 실행 중에는 터미널을 열어 둔다. 기준값과 이벤트는 기본적으로 저장소 안의 `data/`에 저장된다.

## B. Docker Desktop에서 실행

### 1. Ubuntu 컨테이너 만들기

Docker Desktop이 실행 중인지 확인한다. **Mac 터미널 또는 Windows PowerShell**에서 아래 한 줄을 실행한다. Ubuntu XFCE 화면은 3001번 포트, MemWatch 대시보드는 5000번 포트로 연다. 두 포트는 이 컴퓨터에서만 접근할 수 있게 연결한다.

```bash
docker run -d --name memwatch-webtop --shm-size=1g -p 127.0.0.1:3001:3001 -p 127.0.0.1:5000:5000 -v memwatch-webtop-config:/config lscr.io/linuxserver/webtop:ubuntu-xfce
```

이 명령은 최초 1회만 실행한다. 다음부터는 `docker start memwatch-webtop`을 실행한다. 수업용 `security-desktop` 컨테이너에 이미 두 포트가 연결돼 있다면 해당 컨테이너를 `docker start security-desktop`으로 시작하고 2단계로 이동한다.

### 2. Ubuntu 데스크톱 접속

호스트 브라우저에서 [Ubuntu 데스크톱](https://127.0.0.1:3001)을 열고 화면 안에서 **Terminal**을 실행한다. Webtop은 기본 설정에서 자체 서명 인증서를 사용한다. [LinuxServer Webtop 문서](https://docs.linuxserver.io/images/docker-webtop/#application-setup)

### 3. Ubuntu 터미널에서 설치 및 실행

아래 명령은 **브라우저 안에 열린 Ubuntu 터미널**에 입력한다. 소스는 컨테이너의 영구 저장 공간인 `/config`에 받는다.

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-tk
cd /config
git clone https://github.com/landy359/security-project.git
cd security-project
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py --bind 0.0.0.0 --data /config/memwatch-data-v3
```

설치한 뒤 다시 실행할 때는 Ubuntu 터미널에서 `cd /config/security-project`와 마지막 줄의 서버 명령을 실행한다. 기존 수업 환경에서 공유 폴더에 복제해 둔 경우에는 `app.py`가 있는 실제 경로로 이동해서 같은 명령을 사용한다.

### 4. 대시보드 열기

**호스트 브라우저**에서 [MemWatch 대시보드](http://127.0.0.1:5000)를 열어 Ubuntu 데스크톱과 나란히 배치한다. 앱 창은 Ubuntu 데스크톱에 열리고 감시 결과는 대시보드에 표시된다.

## 처음 감시하기

1. 대시보드에서 이미지 뷰어 또는 지뢰찾기를 선택한다.
2. **작업을 마칠 때까지 측정**을 누르고 평소처럼 앱을 사용한다. 기본 최소 12개 표본이 모이면 **이번 실행 측정 완료**를 누른다. 기본 3회의 독립 실행을 완료한다.
3. 영역별 측정값을 검토하고 **측정값 저장**을 누른다.
4. **감시 시작**을 누르고 그래프, 경고, 이벤트가 갱신되는지 확인한다. 다른 환경이나 앱 버전에서 테스트할 때는 해당 환경에서 기준을 다시 측정한다.

## 동결 후 재개

- **일반 재개**는 해시 불일치로 동결된 대상을 정지 상태에서 검사한다. 기준 해시와 일치하면 재개한다.
- **강제 재개**는 현재 검사 결과를 확인한 뒤 사용자가 선택할 수 있다. 일반 대상은 재개 직후 다시 검사하고, 불일치가 남으면 다시 동결한다. 시연 대상은 최대 10초 안에 게임 창에서 **v1 복원**을 누른 뒤 **지금 검사**로 결과를 확인할 수 있다.
- 코드 무결성 카드에는 파일 기반 실행 코드 검사 범위와 제외된 매핑 수가 표시된다. 감시 중 검사 실패는 제한적으로 재시도하며, 세 번 연속 미확인이면 **검증 불가**를 표시한다.

## 시연 모드

공유 라이브러리 교체로 코드 불일치와 동결을 확인하려면 서버를 실행한 터미널에서 먼저 `Ctrl+C`로 기존 서버를 종료한다. Ubuntu 터미널에서 다음 명령을 실행한다. Docker를 사용 중이면 마지막 줄을 그 아래의 Docker용 명령으로 바꾼다.

```bash
sudo apt install build-essential
.venv/bin/python -m tests.build_demo
.venv/bin/python app.py --demo --target demo --bind 127.0.0.1
```

```bash
.venv/bin/python app.py --demo --target demo --bind 0.0.0.0 --data /config/memwatch-data-v3
```

1. 시연 대상의 정상 기준을 측정하고 저장한다. 기준을 만드는 동안은 모듈 v1 상태에서 게임만 플레이한다.
2. 감시를 시작하고 게임의 **v2로 교체**를 누른다. 오른쪽 대시보드에서 **코드 불일치**, **동결**, Linux 상태 **T**를 확인한다.
3. **일반 재개**를 누르면 코드가 여전히 불일치할 때 재개가 보류된다.
4. **강제 재개**를 승인한 뒤 왼쪽에서 10초 안에 **v1 복원**을 누르고, 대시보드에서 **지금 검사**를 눌러 **일치**를 확인한다.

## 종료

1. 대시보드에서 **대상 종료**를 눌러 감시 중인 앱을 닫는다.
2. 서버를 실행한 Ubuntu 터미널에서 `Ctrl+C`를 누른다.
3. Docker를 사용했다면 호스트 터미널에서 `docker stop memwatch-webtop`을 실행한다. 기존 수업 컨테이너를 사용했다면 `docker stop security-desktop`을 실행한다.

## 코드와 폴더 구조

```text
security-project/
├── app.py                  Flask 서버, 대시보드 API, 실행 옵션
├── requirements.txt        Python 의존성
├── image_viewer.py          기본 감시 대상인 이미지 뷰어
├── minesweeper.py           기본 감시 대상인 지뢰찾기
├── monitor/
│   ├── engine.py           감시 상태, 해시 검사와 동결·재개 처리
│   ├── memory.py           Linux /proc 기반 RSS·실행 코드 읽기
│   ├── policy.py           RSS 기준값 계산과 경고 단계 판정
│   ├── catalog.py          감시 대상 등록과 설정
│   ├── target.py           대상 실행과 프로세스 상태 확인
│   └── storage.py          SQLite 기준값과 이벤트 저장
├── templates/index.html    대시보드 HTML
├── static/                 대시보드 JavaScript와 CSS
├── tests/                  단위·Linux 통합 테스트와 시연 모듈
└── docs/monitoring.md      감시 방식과 상세 실행 옵션
```

## 테스트

Ubuntu 데스크톱 터미널에서 `app.py`가 있는 폴더로 이동한다. 단위 테스트는 첫 줄로 실행할 수 있다. 전체 테스트는 C 컴파일러와 GUI 세션이 있는 환경에서 실행한다.

```bash
.venv/bin/python -m unittest tests.test_core -v
sudo apt install build-essential
.venv/bin/python -m unittest discover -v
```

GUI 테스트가 `skipped`라면 Ubuntu 데스크톱 안의 터미널에서 `echo "$DISPLAY"`로 그래픽 세션 연결을 확인한다.

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
