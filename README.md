# SeoulTech Mail MCP

서울과학기술대학교 웹메일 받은편지함 조회용 MCP임. 메일 발송·삭제·읽음 처리 기능은 없음.

| 도구 | 하는 일 |
| --- | --- |
| `check_mail_connection` | 메일 계정 연결 확인 |
| `list_inbox_messages` | 날짜별 발신자·제목·읽음 상태 조회 |
| `read_inbox_message` | 메일 본문 조회 |
| `get_daily_mail_digest` | 날짜별 메일 미리보기·건수 조회 |

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
| 아이콘 | [`assets/mailplug-icon.png`](assets/mailplug-icon.png) |
| 연결 | `터널` → 본인 터널 ID |
| 인증 | `인증 없음` |

등록 후 “채팅에서 사용해 보기”에서 메일 조회 요청하면 됨. 플러그인 등록은 한 번만 하면 됨.

현재 플러그인은 이 컴퓨터에 저장된 **하나의 메일 계정**으로 동작함. 사용자별 OAuth가 없으므로 개인용으로만 사용하고, 다른 사람은 각자 계정과 터널을 설정해야 함.

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
