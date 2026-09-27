Set-Location -LiteralPath 'C:\JARVIS'
$env:JARVIS_LOG_LEVEL = 'DEBUG'
Start-Transcript -Path 'C:\JARVIS\data\v04-live-console.txt' -Append
Write-Host 'JARVIS v0.4 continuous microphone verification'
Write-Host 'Use ONE session. ENTER starts recording; ENTER stops recording.'
Write-Host 'Wait for the spoken response before starting the next command.'
Write-Host '1. Give me system information'
Write-Host '2. Open Streetlight'
Write-Host '3. Close Streetlight'
Write-Host '4. Open Sentinel AI'
Write-Host '5. Close Sentinel AI'
Write-Host '6. Open K E E R'
Write-Host '7. Close K E E R'
Write-Host '8. Give me system information'
Write-Host 'After command 8, type q at the prompt and report whether you heard all eight responses.'
& 'C:\JARVIS\venv\Scripts\python.exe' -m app.main --voice
Stop-Transcript
