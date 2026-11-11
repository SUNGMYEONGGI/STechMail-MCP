<p align="center">
  <img src="assets/logo.png" alt="SeoulTech Mail MCP 로고" width="128" height="128">
</p>

<h1 align="center">SeoulTech Mail MCP</h1>

<p align="center">
  서울과학기술대학교 웹메일 받은편지함을 AI 앱에서 읽기 전용으로 조회하는 MCP 서버
</p>

<p align="center">
  <a href="https://github.com/SUNGMYEONGGI/STechMail-MCP/releases/latest"><img alt="release" src="https://img.shields.io/github/v/release/SUNGMYEONGGI/STechMail-MCP"></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="read-only" src="https://img.shields.io/badge/mail-read--only-2FD39A">
  <a href="LICENSE"><img alt="license" src="https://img.shields.io/github/license/SUNGMYEONGGI/STechMail-MCP"></a>
</p>

메일 발송·삭제·읽음 처리 기능은 없음.

| 도구 | 하는 일 |
| --- | --- |
| `check_mail_connection` | 메일 계정 연결 확인 |
| `list_inbox_messages` | 날짜별 발신자·제목·읽음 상태 조회 |
| `read_inbox_message` | 메일 본문 조회 |
| `get_daily_mail_digest` | 날짜별 메일 미리보기·건수 조회 |

로컬 개인용(stdio)과 여러 사용자용 OAuth 원격 서버(`--http`) 두 가지로 실행 가능함.

날짜는 한국 시간 기준임. 조회 결과를 보고 ChatGPT나 Codex가 요약해 줌. 첨부파일 내용은 조회하지 않음.

## 설치

Python 3.10 이상, Google Chrome, 서울과기대 웹메일 계정 필요함. macOS에서 메일 조회 확인함. Linux는 설치와 MCP 초기화까지 확인했으며, 웹메일 로그인은 아직 확인 전임. Windows는 추후 지원 예정.

```bash
git clone https://github.com/SUNGMYEONGGI/STechMail-MCP.git seoultech-mcp
cd seoultech-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/seoultech-mail configure
.venv/bin/seoultech-mail check
```

`configure`에서 본인 학교 메일 주소와 비밀번호 입력하면 됨. 계정 정보는 `~/.config/seoultech-mcp/credentials.json`에 권한 `600`으로 저장됨. 비밀번호를 바꿨다면 `configure` 다시 실행.

## Codex에서 사용

Codex CLI 설치 후 프로젝트 폴더에서 한 번만 등록하면 됨.

```bash
codex mcp add seoultech-mail -- "$(pwd)/.venv/bin/seoultech-mail-mcp"
codex mcp get seoultech-mail
```

Codex 다시 열고 새 채팅에서 “서울과기대 메일에서 어제 받은 메일 정리해줘”처럼 요청하면 됨. 로컬 Codex 연결에는 터널 필요 없음. 등록 해제는 `codex mcp remove seoultech-mail`.

## ChatGPT 플러그인에서 사용

### 처음 한 번: 터널 설정

1. [OpenAI 공식 릴리스](https://github.com/openai/tunnel-client/releases/latest)에서 OS·CPU에 맞는 `tunnel-client` 내려받고 압축 풀기. 실행 파일이 있는 폴더에서 아래 명령 실행.

   ```bash
   mkdir -p "$HOME/.local/bin"
   install -m 755 ./tunnel-client "$HOME/.local/bin/tunnel-client"
   export PATH="$HOME/.local/bin:$PATH"
   ```

   새 터미널에서도 쓰려면 마지막 `export` 줄을 `~/.zshrc` 또는 `~/.bashrc`에 추가하면 됨.

2. [OpenAI Platform 터널 설정](https://platform.openai.com/settings/organization/tunnels)에서 본인 **Personal 조직**의 터널 만들기. 사용할 ChatGPT 워크스페이스 연결하고 같은 조직의 API 키 준비. 터널을 만들 때는 `Tunnels Read·Manage`, 사용할 때는 `Read·Use` 권한 필요함.

3. 프로젝트 폴더에서 `tunnel_YOUR_ID`를 본인 터널 ID로 바꿔 실행. 기존 프로필이 있으면 이 단계 건너뛰면 됨.

   ```bash
   tunnel-client init \
     --sample sample_mcp_stdio_local \
     --profile seoultech-mail \
     --tunnel-id 'tunnel_YOUR_ID' \
     --mcp-command "$(pwd)/.venv/bin/seoultech-mail-mcp" \
     --health-listen-addr 127.0.0.1:8080
   ```

   프로필 저장 위치: `~/.config/tunnel-client/seoultech-mail.yaml`.

### 사용할 때: 터널 켜기

새 터미널에서 첫 줄 입력 후 OpenAI API 키를 붙여 넣고 Enter. 키 입력 중에는 화면에 표시되지 않음.

```bash
read -rs CONTROL_PLANE_API_KEY && export CONTROL_PLANE_API_KEY
tunnel-client run --profile seoultech-mail
```

같은 터미널에 키가 남아 있으면 `run`만 실행하면 됨. `run`이 켜진 동안 ChatGPT에서 사용 가능함.

### 플러그인 등록

ChatGPT 개발자 모드 켠 뒤 [플러그인](https://chatgpt.com/plugins)에서 새 플러그인 만들기. 터널을 실행한 상태에서 아래처럼 입력하면 됨.

| 항목 | 입력값 |
| --- | --- |
| 이름 | `SeoulTech Mail` |
| 설명 | `서울과학기술대학교 받은편지함 조회 및 메일 요약` |
| 아이콘 | [`assets/logo.png`](assets/logo.png) |
| 연결 | `터널` → 본인 터널 ID |
| 인증 | `인증 없음` |

등록 후 “채팅에서 사용해 보기”에서 메일 조회 요청하면 됨. 플러그인 등록은 한 번만 하면 됨.

터널 방식은 이 컴퓨터에 저장된 **하나의 메일 계정**으로 동작함. 여러 사람이 각자 계정으로 쓰려면 아래 [OAuth 원격 서버](#oauth-원격-서버-v020)를 사용.

## OAuth 원격 서버 (v0.2.0)

서버 하나에 여러 사용자가 각자 학교 계정으로 연결하는 방식임. Claude 커스텀 커넥터나 ChatGPT 플러그인에서 서버 주소를 등록하면, 연결할 때 로그인 페이지가 열리고 학교 웹메일 아이디·비밀번호를 입력하면 됨. 서버는 실제 웹메일 로그인으로 계정을 확인한 뒤 OAuth 토큰을 발급함.

```bash
.venv/bin/seoultech-mail-mcp --generate-key   # 출력값을 SEOULTECH_AUTH_KEY로 보관
export SEOULTECH_PUBLIC_URL="https://mail-mcp.example.com"
export SEOULTECH_AUTH_KEY="위에서 만든 키"
export SEOULTECH_AUTH_DB="$HOME/.local/share/seoultech-mcp/auth.db"   # 기본값
.venv/bin/seoultech-mail-mcp --http --host 127.0.0.1 --port 8000
```

| 환경 변수 | 설명 |
| --- | --- |
| `SEOULTECH_PUBLIC_URL` | 외부에서 접속하는 HTTPS 주소. OAuth issuer와 리소스 주소(`/mcp`)로 사용됨 |
| `SEOULTECH_AUTH_KEY` | 비밀번호 암호화 키(Fernet). 바꾸면 모든 사용자가 다시 로그인해야 함 |
| `SEOULTECH_AUTH_DB` | 클라이언트·토큰·암호화된 비밀번호 저장 SQLite 파일 (권한 600) |
| `SEOULTECH_HOST`, `SEOULTECH_PORT` | `--host`, `--port` 기본값 |
| `SEOULTECH_SESSION_TTL` | 웹메일 로그인 세션 재사용 시간(초, 기본 1200). 세션은 메모리에만 보관하고 서버 재시작 시 사라짐 |
| `SEOULTECH_MAX_BROWSERS` | 동시에 실행할 수 있는 로그인용 Chrome 수 (기본 2) |

- 서버 앞에 HTTPS 리버스 프록시(Caddy, nginx, Cloudflare Tunnel 등)를 두고 `127.0.0.1:8000`으로 전달. `SEOULTECH_PUBLIC_URL`은 `https`만 허용함(로컬 테스트용 `localhost` 제외).
- 서버에 Google Chrome 필요함 (웹메일 로그인).
- 연결 주소: `https://mail-mcp.example.com/mcp`. 인증은 `OAuth`, 동적 클라이언트 등록 지원하므로 클라이언트 ID 입력 필요 없음.
- 엔드포인트: `/.well-known/oauth-authorization-server`, `/register`, `/authorize`, `/login`, `/token`, `/revoke`, `/account/delete`, `/mcp`.
- 토큰 수명: access 1시간, refresh 30일(사용할 때마다 교체). 로그인 요청은 10분 안에 끝내야 하고 요청 하나당 실패는 5회까지 허용함.
- 로그인 실패 제한: 15분 동안 같은 IP에서 10회, 같은 계정으로 5회 실패하면 해당 시간이 지날 때까지 로그인 차단(HTTP 429). 새 로그인 요청을 만들어도 초기화되지 않음. 계정 단위 횟수는 로그인 성공 시 초기화됨.
- 리버스 프록시가 다른 호스트에 있으면 `FORWARDED_ALLOW_IPS`에 프록시 IP를 지정해야 실제 접속 IP로 제한이 걸림(기본값은 같은 서버의 `127.0.0.1`). 신뢰할 수 없는 IP를 넣으면 `X-Forwarded-For` 위조로 IP 제한을 우회할 수 있음.

**저장 정보 삭제:**
- 비밀번호는 그 계정에 유효한 연결(refresh 토큰 또는 교환 전 인가 코드)이 남아 있는 동안만 보관함. 클라이언트가 토큰을 폐기(`/revoke`)하거나 refresh 토큰이 만료되면 비밀번호도 삭제됨. 정리는 서버 시작 시, 새 로그인 요청 시, 토큰 폐기 시 실행됨.
- 사용자가 직접 `https://서버주소/account/delete`에서 학교 계정으로 본인 확인 후 비밀번호와 모든 연결을 즉시 삭제할 수 있음. 로그인 페이지에도 링크가 있음. 실패 제한은 로그인과 같이 적용됨.

**보안 주의:** 메일 조회 때마다 웹메일에 로그인해야 하므로 사용자 비밀번호를 서버에 암호화해 저장함. 토큰은 해시로만 저장함. 서버 운영자는 `SEOULTECH_AUTH_KEY`와 DB 파일에 접근할 수 있으면 비밀번호를 복호화할 수 있으므로, 신뢰할 수 있는 사람만 운영하고 키와 DB를 분리 보관할 것. 학교 계정 정책도 확인할 것.

## 터널 끄기·재시작·점검

- **끄기:** `run` 실행 중인 터미널에서 `Ctrl+C`. 플러그인 등록과 터널 ID는 그대로 남음.
- **다시 켜기:** 같은 터미널에서 `tunnel-client run --profile seoultech-mail`. 새 터미널이면 API 키 입력부터 다시.
- **상태 확인:** 실행 중 다른 터미널에서 아래 명령 사용. `"result": "ok"`면 OpenAI 서버와 연결된 상태임. 시작 직후에는 잠시 뒤 다시 확인.

  ```bash
  tunnel-client health --port 8080 --require-control-plane-poll --json
  ```

- **설정 점검:** 처음 설정하거나 오류가 날 때만 API 키가 설정된 터미널에서 실행하면 됨.

  ```bash
  tunnel-client doctor --profile seoultech-mail --explain
  ```

플러그인 생성이 실패하거나 터널에서 `404`가 뜬다면 Platform·프로필·플러그인에 입력한 터널 ID부터 비교. 프로필을 수정했다면 `Ctrl+C`로 끄고 다시 실행해야 반영됨.

## 메일 정리 파일

프로젝트 폴더에서 실행. `ai-digest`는 Codex CLI 설치·로그인 필요함.

```bash
.venv/bin/seoultech-mail digest --date yesterday
.venv/bin/seoultech-mail ai-digest --date yesterday
```

저장 폴더는 각각 `~/seoultech-mail-digests/`, `~/seoultech-mail-summaries/`. 날짜는 `today`, `yesterday`, `YYYY-MM-DD` 중 선택 가능함.

계정 파일·API 키·메일 정리 파일은 GitHub에 올리지 말 것. 메일 조회 결과는 사용하는 AI 클라이언트에 전달됨. 학교 웹메일의 내부 API가 바뀌면 서버 수정이 필요할 수 있음.

참고: [Codex MCP 설정](https://developers.openai.com/codex/mcp) · [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
