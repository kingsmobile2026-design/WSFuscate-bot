# WSFuscate Discord 봇

## 기능
- `/obf` 슬래시 명령어에서 파일 첨부
- `.lua`, `.luau`, `.txt` 입력
- 동봉된 `WSFuscate.html` 엔진으로 Chromium에서 난독화
- 결과를 `obfuscate.txt`로 **명령 실행자에게만(ephemeral)** 전달
- 채널에 원본 파일/원본 코드/결과 파일을 별도 메시지로 게시하지 않음

## 설치
Python 3.10 이상 권장.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

## 봇 설정
1. Discord Developer Portal에서 Application과 Bot을 생성합니다.
2. OAuth2 URL Generator에서 `bot` 및 `applications.commands` 권한으로 서버에 초대합니다.
3. 봇 토큰을 환경 변수 `BOT_TOKEN`으로 설정합니다. 기존 배포 환경과의 호환을 위해 `DISCORD_BOT_TOKEN`도 사용할 수 있으며, 두 값이 모두 있으면 `BOT_TOKEN`을 우선 사용합니다.

Windows PowerShell:
```powershell
$env:BOT_TOKEN="여기에_봇_토큰"
python bot.py
```

Linux/macOS:
```bash
export BOT_TOKEN="여기에_봇_토큰"
python bot.py
```

봇이 접속하면 `/obf` 명령어가 동기화됩니다. 디스코드에서 `/obf`를 선택하고 파일 입력란에 파일을 첨부한 뒤 전송하면 됩니다.

## Render 배포

이 프로젝트에는 Render Blueprint 파일(`render.yaml`)이 포함되어 있습니다. 다음 순서로 배포합니다.

1. ZIP을 풀고 파일 전체(`bot.py`, `WSFuscate.html`, `requirements.txt`, `render.yaml`, `.python-version`)를 GitHub 저장소 루트에 업로드합니다.
2. Render 대시보드에서 **New + → Blueprint**를 선택하고 해당 GitHub 저장소를 연결합니다.
3. Blueprint 설정 중 `BOT_TOKEN` 값을 입력합니다. 기존 서비스에 Blueprint를 나중에 추가하는 경우에는 Render 서비스의 **Environment** 화면에서 `BOT_TOKEN`을 직접 추가합니다.
4. 생성된 `wsfuscate-discord-bot` Background Worker의 배포 로그에서 Discord 로그인 및 slash command 동기화 성공 여부를 확인합니다.

Render는 `render.yaml`의 빌드 명령으로 Python 패키지와 Chromium 및 OS 의존성을 설치하고, 시작 명령으로 `python bot.py`를 실행합니다. Discord 봇은 외부 HTTP 요청을 받지 않으므로 **Web Service가 아니라 Background Worker**로 배포합니다. Render Background Worker는 선택한 인스턴스 플랜에 따라 과금될 수 있습니다. <https://render.com/docs/blueprint-spec>

## 설정 환경 변수(선택)
- `BOT_TOKEN`: Discord 봇 토큰(Render에서 사용하는 기본 변수명)
- `DISCORD_BOT_TOKEN`: 기존 변수명 호환용 (`BOT_TOKEN`이 없을 때 사용)
- `MAX_INPUT_BYTES`: 원본 최대 크기(기본 8 MiB)
- `MAX_OUTPUT_BYTES`: 결과 최대 크기(기본 25 MiB)
- `BUILD_TIMEOUT_MS`: 난독화 제한 시간(기본 180000ms)

## 개인정보/보안 동작
- 명령어 응답을 처음부터 ephemeral로 defer하고 결과도 ephemeral follow-up으로 전송합니다.
- 원본 첨부를 봇 프로세스 메모리에서 읽어 별도 격리된 Chromium 페이지에 전달합니다.
- 원본을 채널 메시지, 로그, 결과 파일에 넣지 않습니다.
- 요청마다 Chromium 브라우저를 새로 만들고 종료합니다. 동시 빌드는 2개로 제한합니다.
- 원본을 디스크 임시 파일로 저장하지 않습니다.

**중요한 한계:** Discord에 업로드한 첨부는 Discord 플랫폼의 첨부 전송/저장 시스템을 거칩니다. 봇만 파일을 읽게 하려면 반드시 명령어의 파일 첨부 입력으로 업로드해야 하며, 일반 채널 메시지에 먼저 파일을 올린 뒤 봇을 호출하면 안 됩니다. 서버 관리자, 호스팅 사업자, 봇 운영자는 봇 프로세스/호스트에 접근할 수 있습니다. 이 방식은 다른 일반 서버 멤버에게 원본을 공개하지 않도록 설계한 것이지, Discord 또는 봇 호스트 운영자로부터 암호학적으로 비밀을 보장하는 방식은 아닙니다.

봇 호스트의 로그/백업/크래시 덤프 정책도 별도로 보호하세요. 실제 배포 전에 개인 테스트 서버에서 ephemeral 첨부 응답이 정상적으로 보이는지 확인하세요.
