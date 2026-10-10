$Python = Join-Path $env:LOCALAPPDATA 'KAISTLogin\runtime\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw '먼저 setup-windows.ps1을 실행하세요.' }
if ($args.Count -eq 0) { & $Python -m kaist_login setup }
else { & $Python -m kaist_login @args }
exit $LASTEXITCODE
