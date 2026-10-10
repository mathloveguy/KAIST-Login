# KAIST Login

KAIST KLMS와 Dooray를 위한 로컬 Python 로그인 도구입니다. Windows/macOS에서 같은 코어를 사용하며, 각 운영체제용 설치·실행 스크립트를 제공합니다. Codex, Claude Desktop, Claude Code는 동일한 MCP 도구를, Python 자동화는 `Broker`를 호출합니다.

**현재 상태: 초기 구현입니다. 공개 로그인 화면을 조사했고 macOS의 모의 계정·합성 메일·브라우저·MCP 테스트를 통과했습니다. 실제 계정 로그인, 실제 인증메일 형식, Windows 실행은 사용자의 기기에서 추가 검증해야 합니다.**

## 동작 구조

```text
사용자 → 로컬 설정 창 → OS 보안 저장소 (KAIST 비밀번호)
사용자 → 로컬 Gmail 연결 창 → OS 보안 저장소 (Google 앱 비밀번호)
Codex/Claude/Python → 로그인 브로커 → KAIST SSO → KLMS / Dooray
                     ↘ Gmail에서 새 인증번호만 추출 → SSO에 입력
Codex/Claude/Python ← 로그인 상태 / 요청한 서비스 페이지 텍스트
```

- macOS Keychain / Windows Credential Manager를 직접 사용합니다. 평문 keyring으로 대체하지 않습니다.
- 비밀번호를 명령행 인자, 환경변수, `.env`, 소스코드에 저장하지 않습니다.
- Google 앱 비밀번호도 OS 보안 저장소에 보관합니다. 로그인 쿠키·localStorage·IndexedDB 및 선택적으로 사용하는 OAuth 토큰은 암호화 파일에 저장합니다.
- 런타임 데이터는 macOS `~/Library/Application Support/KAISTLogin`, Windows `%LOCALAPPDATA%\KAISTLogin`에 저장합니다. 이 Google Drive 프로젝트 폴더에는 저장하지 않습니다.
- 인증 도메인은 `sso.kaist.ac.kr`, 서비스는 `klms.kaist.ac.kr`, `kaist.gov-dooray.com`으로 제한합니다.
- 로그, 브라우저 trace, 화면 캡처, 쿠키 반환, 임의 JS 실행 도구를 제공하지 않습니다.
- 비밀번호 제출은 한 번만 합니다. 실패하면 사용자가 로컬에서 확인하기 전까지 자동 재시도를 막습니다.
- CAPTCHA, 앱 승인, 학교 정책으로 요구되는 추가 절차는 브라우저에서 사용자가 처리합니다.

## 설치

Python 3.11 이상이 필요합니다. GUI에는 Tkinter가 필요하며 python.org의 Windows/macOS 설치 프로그램을 사용할 수 있습니다. 관리자 권한은 필요 없습니다. 설치 스크립트는 PyPI의 의존성과 Playwright Chromium을 다운로드합니다.

### macOS

프로젝트 폴더에서:

```sh
zsh scripts/setup-mac.command
```

계정 입력창에 KAIST 포털 아이디·비밀번호·외부 Gmail 주소를 입력합니다. 이후 명령은 아래처럼 실행합니다.

```sh
zsh scripts/run-mac.command status
zsh scripts/run-mac.command gmail-connect
zsh scripts/run-mac.command calibrate klms
zsh scripts/run-mac.command calibrate dooray
zsh scripts/run-mac.command login klms
zsh scripts/run-mac.command read klms
```

### Windows (일반 PowerShell, WSL 제외)

```powershell
.\scripts\setup-windows.ps1
.\scripts\run-windows.ps1 status
.\scripts\run-windows.ps1 gmail-connect
.\scripts\run-windows.ps1 calibrate klms
.\scripts\run-windows.ps1 calibrate dooray
.\scripts\run-windows.ps1 login dooray
```

조직 정책이 PowerShell 스크립트를 차단하면 정책을 끄지 말고 아래 Python 명령을 직접 실행할 수 있습니다.

```powershell
py -3 -m venv "$env:LOCALAPPDATA\KAISTLogin\runtime"
$KaistPython = "$env:LOCALAPPDATA\KAISTLogin\runtime\Scripts\python.exe"
& $KaistPython -m pip install .
& $KaistPython -m playwright install chromium
& $KaistPython -m kaist_login setup
```

Mac과 Windows에는 각각 계정을 등록하고 Gmail 연결을 진행합니다. OS 보안 저장소와 암호화 파일은 다른 기기로 복사해서 재사용하지 않습니다. 설치 스크립트를 다시 실행하면 프로젝트의 최신 코드를 설치합니다.

## Gmail 인증번호 자동 입력 준비

기본 연결은 **Gmail IMAP + Google 앱 비밀번호**입니다. Google Cloud 프로젝트, OAuth 클라이언트 JSON, 테스트 앱의 매주 재승인이 필요하지 않습니다. 일반 Google 계정 비밀번호는 입력하지 않습니다. Codex/Claude의 기존 Gmail 커넥터와는 별도의 로컬 연결입니다.

1. Google 계정에서 **2단계 인증**을 켭니다.
2. [Google 앱 비밀번호](https://myaccount.google.com/apppasswords)에서 `KAIST Login`용 앱 비밀번호를 만듭니다.
3. `gmail-connect`를 실행합니다. 외부 Gmail 주소와 **발급받은 16자리 앱 비밀번호**를 로컬 창에 입력합니다. 공백을 포함해 붙여넣어도 됩니다.
4. 프로그램이 TLS로 `imap.gmail.com:993`에 연결을 확인한 뒤 OS 보안 저장소에 앱 비밀번호를 보관합니다. 인증번호·메일 본문·앱 비밀번호는 LLM에 전달하지 않습니다.
5. 아래 `calibrate`로 실제 MFA 화면과 인증메일의 발신 주소·제목을 등록합니다. 기존에 등록했다면 같은 Gmail 주소에서는 규칙을 유지합니다.

앱 비밀번호는 보통 한 번 등록하며 OAuth 테스트 앱의 7일 만료 제한을 받지 않습니다. Google 계정 비밀번호 변경 또는 앱 비밀번호 취소 시에는 새로 발급해 연결해야 합니다. 조직 계정, 고급 보호 계정, 보안 키만 사용하는 2단계 인증에서는 앱 비밀번호 메뉴가 없을 수 있습니다. [Google 공식 안내](https://support.google.com/accounts/answer/185833)

개인 Gmail은 IMAP이 기본 활성화되어 있습니다. 이 구현은 **INBOX의 최근 인증메일**을 조회하므로 Gmail 필터가 인증메일을 받은편지함에서 자동 보관한다면 해당 필터를 조정하세요. 조회는 읽기 전용 `SELECT`와 `BODY.PEEK[]`를 사용해 읽음 표시를 변경하지 않습니다. 앱 비밀번호 자체는 인증메일에만 한정된 권한이 아니므로 보안 저장소에만 보관합니다. [Gmail 클라이언트 안내](https://support.google.com/mail/answer/7126229)

### 인증메일 자동 삭제 옵션

**기본값은 꺼짐**이며 이전 버전에서 옵션이 없던 설정도 메일을 보존합니다. Gmail 연결 창의 체크박스 또는 `mail-options` 설정 창에서 변경할 수 있습니다.

```sh
# 옵션 설정 창 열기
zsh scripts/run-mac.command mail-options
# 켜기 / 끄기
zsh scripts/run-mac.command mail-options --delete-otp-email
zsh scripts/run-mac.command mail-options --no-delete-otp-email
```

Windows는 `.\scripts\run-windows.ps1 mail-options`와 같은 인자를 사용합니다. 옵션을 켜도 로그인 성공을 확인한 뒤 실제 사용한 메일 한 통만 휴지통에 옮깁니다. IMAP에서는 Gmail의 `\Trash` 라벨을 사용하며 `\Deleted`, `CLOSE`, `EXPUNGE` 명령은 사용하지 않습니다. 메일 UID의 세대와 Gmail 고유 메시지 ID를 다시 확인해 다른 메일에 삭제가 적용되지 않게 합니다.

로그인 실패, 잘못된 인증번호, 후보 중복, 시간 초과 시에는 메일을 보존합니다. 세션 재사용이나 수동 인증은 자동으로 사용한 메일이 없으므로 삭제 대상이 없습니다. 과거 인증메일은 일괄 삭제하지 않습니다.

| `otp_cleanup` | 의미 |
|---|---|
| `kept` | 자동 인증에 사용한 메일을 삭제 옵션에 따라 보존 |
| `trashed` | 사용한 메일을 휴지통으로 이동 |
| `not_used` | 자동 OTP 미사용 |
| `failed` | 로그인은 성공했으나 선택한 메일의 정리 실패. 로그인 재시도 불필요 |

### 기존 OAuth 연결 (선택 사항)

기존 OAuth 연결도 유지할 수 있습니다. 필요한 의존성을 `pip install '.[oauth]'`로 설치하고 `gmail-connect --method oauth`를 실행하면 JSON 선택과 Google 승인 흐름을 사용합니다. 새 설치의 기본 의존성에는 Google API 패키지를 포함하지 않습니다.

OAuth에서 삭제 꺼짐이면 `gmail.readonly`, 켜짐이면 `gmail.modify`를 요청합니다. 기존 읽기 전용 연결에서 삭제를 켜면 `gmail-connect --method oauth --delete-otp-email`로 추가 권한을 승인해야 합니다. OAuth 테스트 앱의 7일 refresh token 만료 문제는 이 선택 방식에 남아 있으므로 재승인을 피하려면 기본 IMAP 방식으로 전환하세요. IMAP으로 전환하면 로컬 OAuth 토큰을 제거하며, 이전 Google 앱의 권한은 Google 계정에서 별도로 취소할 수 있습니다.

인증번호 선택 조건:

- 정확한 발신 주소, 등록한 수신 주소, 제목의 고정 문구가 일치
- 이번 로그인/발송 요청 이후 수신, 최대 5분 이내
- Gmail의 `Authentication-Results`에서 발신 도메인과 정렬된 DKIM 성공 확인
- `인증번호`, `인증코드`, `verification code`, `OTP` 등의 문구 바로 뒤(숫자 없는 12자 이내, 예: `인증번호는 [123456]`)에 있는 6자리 숫자. 본문 charset(EUC-KR/CP949 포함)을 반영해 해독
- 후보 메일이나 코드가 여러 개면 자동 입력 중단

현재는 6자리 코드만 지원합니다. 전달 메일, 다른 본문 형식, DKIM 결과가 다른 경우에는 자동 입력을 중단합니다. 실제 발신자나 메일 템플릿을 추측해서 하드코딩하지 않았습니다.

## 최초 화면 등록 (`calibrate`)

실제 비밀번호를 알지 못하는 개발 단계에서는 2차 인증 화면을 확인할 수 없습니다. 따라서 사용자의 화면에서 요소를 선택하는 로컬 등록 창을 제공합니다.

1. `calibrate klms` 또는 `calibrate dooray`를 실행합니다. 전용 브라우저와 설정 창이 열립니다.
2. **저장된 계정으로 1차 로그인**을 누릅니다. 필요하면 브라우저에서 직접 로그인합니다.
3. 이메일 인증 화면에서 **현재 화면 조사**를 누릅니다.
4. 인증번호 입력란, 인증 확인 버튼을 선택합니다. 같은 화면에 이메일 방식 선택·발송 버튼이 있으면 선택하고, 자동 발송되면 비워 둡니다.
5. 실제 인증메일의 발신 이메일 주소와 제목의 고정 문구를 입력하고 **인증 화면 규칙 저장**을 누릅니다. 인증번호를 이 창에 입력할 필요는 없습니다.
6. 최초 로그인은 브라우저에서 직접 완료합니다. 로그인된 서비스 화면에서 다시 **현재 화면 조사**를 누르고, 로그인 후에만 보이는 고유한 메뉴/링크를 선택한 뒤 **로그인 성공 화면 등록**을 누릅니다.
7. 다른 서비스도 같은 방식으로 성공 화면을 등록합니다. 두 서비스는 SSO 비밀번호와 MFA 규칙을 공유합니다.

성공 표시는 “페이지가 바뀜”만으로 판정하지 않습니다. KLMS 로그아웃 링크, Dooray 로그아웃 버튼/링크 또는 사용자가 등록한 고유 메뉴가 실제로 나타나야 합니다. 공개 로그인 화면에도 나오는 메뉴는 성공 기준으로 선택하지 마세요.

**현재 MFA 등록기는 같은 URL 경로의 화면에서 선택·발송·입력·확인을 처리하는 흐름을 지원합니다. 다른 페이지나 iframe으로 이동하는 인증 흐름은 아직 어댑터 수정이 필요합니다.** 학교가 UI를 변경해도 임의의 입력창에 코드를 넣지 않고 중단합니다. 등록 시 요소 ID가 없으면 DOM 위치를 사용하므로 화면 변경에 취약할 수 있습니다.

## Codex 연결

`mcp-config`가 현재 설치된 Python의 절대 경로를 포함한 설정 예제를 출력합니다.

```sh
zsh scripts/run-mac.command mcp-config
```

Windows는 `run-windows.ps1 mcp-config`를 사용합니다. 출력된 `[mcp_servers.kaist_login]` 블록을 기존 Codex 설정과 병합합니다. 같은 이름의 블록이 있다면 중복 추가하지 말고 갱신하세요. 이 프로젝트는 사용자 Codex 설정을 자동으로 덮어쓰지 않습니다.

```toml
[mcp_servers.kaist_login]
command = "/absolute/path/to/runtime/bin/python"
args = ["-m", "kaist_login", "serve"]
tool_timeout_sec = 240
```

`skills/kaist-login` 폴더는 사용자의 Codex skills 디렉터리에 복사해 재사용할 수 있습니다. 이 저장소에는 배포용 스킬을 포함하며 전역 자동 설치는 하지 않았습니다.

제공 도구:

| 도구 | 반환 |
|---|---|
| `kaist_status()` | 아이디, Gmail 주소, 저장/연결 여부 |
| `kaist_login(site)` | 로그인 성공 상태 또는 제한된 오류 코드 |
| `kaist_read_page(site, url?, max_chars?)` | 요청한 서비스 페이지의 텍스트 |

**로그인 세션은 이 프로그램 소유입니다.** Codex 내장 브라우저나 다른 브라우저 플러그인에 자동으로 로그인되지 않습니다. 이후 조회는 `kaist_read_page`나 Python `Broker`로 이어가세요. 서비스 페이지 열람 자체로 메일/알림이 읽음 처리될 수 있습니다. 텍스트 조회는 파일 첨부 다운로드, 모든 SPA 메뉴 조작, 임의 업무 자동화까지 구현한 것은 아닙니다.

## Claude Desktop / Claude Code 연결

별도 서버나 비밀번호 사본이 필요하지 않습니다. 같은 기기·OS 사용자라면 Codex와 같은 보안 저장소와 암호화 세션을 사용합니다. 동시 로그인 호출은 `broker_busy`로 중단합니다.

### Claude Desktop

```sh
zsh scripts/run-mac.command mcp-config --client claude-desktop
```

Windows에서는 `.\scripts\run-windows.ps1 mcp-config --client claude-desktop`를 실행합니다. 출력된 JSON의 `mcpServers.kaist_login` 항목을 Claude Desktop의 **Settings → Developer → Edit Config**에서 기존 설정에 병합하고 앱을 재시작합니다. 다른 서버 설정을 덮어쓰지 마세요.

일반적인 설정 파일 위치는 macOS `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows `%APPDATA%\Claude\claude_desktop_config.json`입니다. 웹 브라우저의 claude.ai는 이 로컬 stdio 프로세스에 직접 연결할 수 없습니다.

### Claude Code

macOS:

```sh
claude mcp add --transport stdio --scope user kaist_login -- "$HOME/Library/Application Support/KAISTLogin/runtime/bin/python" -m kaist_login serve
```

Windows PowerShell:

```powershell
claude mcp add --transport stdio --scope user kaist_login -- "$env:LOCALAPPDATA\KAISTLogin\runtime\Scripts\python.exe" -m kaist_login serve
```

또는 `mcp-config --client claude-code`로 생성한 JSON을 프로젝트 `.mcp.json`의 기존 `mcpServers`에 병합할 수 있습니다. `/mcp`에서 연결 상태와 세 도구를 확인합니다. 클라이언트의 도구 시간 제한이 로그인 대기 시간보다 짧다면, 먼저 로컬 `login` 명령으로 로그인한 뒤 조회하세요.

Claude에서도 비밀번호나 인증번호를 채팅에 넣지 않습니다. “KLMS에서 내 강좌 정보를 확인해 줘”처럼 요청하고, 이후 조회는 브로커의 `kaist_read_page`로 이어갑니다. Claude의 다른 브라우저 도구에는 세션이 전달되지 않습니다. Claude 앱 자체에서의 실계정 통합 테스트는 아직 하지 않았으며, 생성 설정 파싱과 표준 MCP 핸드셰이크를 테스트합니다.

## Python 호출

```python
import asyncio
from kaist_login.browser import Broker

async def main():
    result = await Broker().read("klms")
    print(result["text"])

asyncio.run(main())
```

`examples/read_klms.py`에는 오류 처리도 포함되어 있습니다. 비밀번호·쿠키·Page 객체를 호출자에게 넘기지 않습니다. 새 업무 기능은 브로커 내부에 명시적인 작업으로 추가하는 방향을 권장합니다.

## 오류와 복구

| 코드 | 조치 |
|---|---|
| `setup_required` | `setup`으로 로컬 계정 등록 |
| `operation_failed` | 네트워크, Tkinter, Chromium 설치, 키체인 권한을 점검. 원시 예외는 비밀값 유출 방지를 위해 출력하지 않음 |
| `gmail_imap_setup_required` | `gmail-connect`로 앱 비밀번호 등록 |
| `gmail_imap_auth_or_command_failed` | 앱 비밀번호, 2단계 인증, 계정의 IMAP 지원 확인 후 다시 연결 |
| `gmail_imap_connection_failed` | 네트워크 확인 |
| `gmail_not_connected` / `gmail_reconnect_required` | 기존 OAuth 연결을 기본 IMAP으로 전환하거나 `--method oauth`로 재승인 |
| `oauth_dependencies_required` | OAuth 사용 시에만 `.[oauth]` 의존성 설치 |
| `login_requires_local_reset` | 비밀번호/계정 상태 확인 후 `reset-login`; 무한 재시도 금지 |
| `login_cooldown` | 마지막 시도 이후 60초 대기 |
| `mfa_layout_changed` | `calibrate`로 화면 요소 재등록 |
| `ambiguous_otp` / `otp_timeout` | 인증메일과 형식 확인, 브라우저에서 직접 인증 |
| `needs_user_login_or_success_marker` | 사용자 인증 또는 성공 화면 등록 필요 |
| `broker_busy` | 기존 로그인/등록 창 종료 후 실행 |
| `encrypted_state_unavailable` | 다른 기기의 키/파일을 복사했는지 확인. `forget` 후 다시 연결 |

`forget`은 로컬 확인창을 거쳐 KAIST 비밀번호·Google 앱 비밀번호·토큰·세션을 삭제합니다. Google 계정에서 앱 비밀번호·접근 권한을 취소하거나 KAIST 서버의 기존 세션을 폐기하는 기능은 별도입니다.

## 보안 경계

이 구현의 보장은 **정상적인 CLI/MCP 출력에 비밀번호·OTP·토큰을 노출하지 않는 것**입니다. 같은 OS 사용자로 임의 코드를 실행하는 LLM, 악성 프로세스, 수정된 패키지로부터 비밀번호를 완전히 격리하지는 못합니다. 특히 macOS에서 동일 Python 실행 파일의 다른 스크립트가 키체인 항목에 접근할 수 있습니다.

**셸 실행 권한이 있는 에이전트(Claude Code, Codex 등)도 여기에 해당합니다.** 런타임 Python으로 `keyring`을 직접 호출하거나 암호화 키를 꺼내 `gmail.sealed`(메일함 전체 읽기·수정 권한)를 복호화할 수 있습니다. 브로커는 정상 경로에서 비밀값을 내보내지 않을 뿐, 에이전트의 셸 권한을 막지는 않습니다. 에이전트 권한 설정에서 런타임 데이터 폴더와 `keyring` 호출을 차단하는 것을 권장합니다.

더 강한 격리가 필요하면 로그인 브로커를 별도 OS 사용자/기기에서 실행하고, 에이전트에는 제한된 RPC만 허용하는 배포가 필요합니다. 이는 이번 로컬 버전의 범위에 포함되지 않습니다. TLS 검증을 끄거나 인증 자체를 우회하는 기능은 없습니다. 세션 재사용 가능 기간은 학교 정책에 따릅니다. `sessionStorage`는 저장하지 않습니다.

Gmail을 연결하면 프로그램에 메일 접근 권한이 생기고, `read`로 조회한 KLMS/Dooray 본문은 요청한 LLM에 전달됩니다. 외부로 보내지 않을 정보는 조회 요청에서 제외하세요.

## 개발·검증

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

Windows는 `.venv\Scripts\python.exe`를 사용합니다. 테스트는 메모리 keyring, 가짜 로그인 페이지, 합성 메일과 모의 IMAP 응답을 사용합니다. 실제 저장된 비밀번호나 Gmail을 읽지 않습니다.

## 조사 근거 (2026-10-10)

- [KLMS 로그인](https://klms.kaist.ac.kr/login/ssologin.php): 브라우저에서 `sso.kaist.ac.kr`로 이동하는 로그인 링크를 확인했습니다. `#loginTab02`, `#login_id`, `#login_pwd`, `loginProc()` 버튼을 관찰했습니다.
- [KAIST Dooray](https://kaist.gov-dooray.com/): `교직원 / 재학생 / 졸업생` 버튼이 같은 KAIST SSO로 이동함을 확인했습니다. 업무계정/손님은 이 버전의 지원 대상이 아닙니다.
- [KAIST 공식 메일 안내](https://ict.kaist.ac.kr/mail): 내부 구성원은 포털 통합계정으로 메일서비스를 이용합니다.
- [keyring 문서](https://keyring.readthedocs.io/en/latest/): native backend 및 macOS 접근 제어의 한계.
- [Google Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app), [Gmail OAuth 범위](https://developers.google.com/workspace/gmail/api/auth/scopes).
- [Playwright 인증 상태](https://playwright.dev/python/docs/auth), [Codex MCP 설정](https://developers.openai.com/codex/mcp).

- [Claude Code MCP](https://code.claude.com/docs/en/mcp), [Claude Desktop 로컬 MCP](https://modelcontextprotocol.io/docs/develop/connect-local-servers), [Gmail 휴지통 API 및 권한](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/trash).

- [Gmail IMAP 확장과 라벨 처리](https://developers.google.com/workspace/gmail/imap/imap-extensions).
