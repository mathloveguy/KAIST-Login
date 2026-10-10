$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path $PSScriptRoot -Parent
$RuntimeDir = Join-Path $env:LOCALAPPDATA 'KAISTLogin\runtime'
py -3 -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ is required'"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ 설치가 필요합니다.' }
py -3 -m venv $RuntimeDir
if ($LASTEXITCODE -ne 0) { throw '가상환경 생성 실패' }
$Python = Join-Path $RuntimeDir 'Scripts\python.exe'
& $Python -m pip install $ProjectDir
if ($LASTEXITCODE -ne 0) { throw '패키지 설치 실패' }
& $Python -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw '브라우저 설치 실패' }
& $Python -m kaist_login setup
if ($LASTEXITCODE -ne 0) { throw '계정 설정 실패' }
& $Python -m kaist_login mcp-config
Write-Host '설치 완료. README.md의 Gmail 연결 및 최초 화면 등록을 진행하세요.'
