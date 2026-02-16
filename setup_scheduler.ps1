# YouShorts 자동 생산 스케줄러 등록
# 매일 오전 8시 자동 실행

$taskName = "YouShorts_AutoProduce"
$batPath = "C:\tool\yousohrts\auto_produce.bat"

# 기존 작업 삭제 (있으면)
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# 작업 액션: bat 파일 실행
$action = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory "C:\tool\yousohrts"

# 트리거: 매일 오전 8시
$trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM

# 설정: 배터리에서도 실행, 놓친 실행 즉시 실행
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# 스케줄러 등록
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "YouShorts: 매일 오전 8시 쇼츠 3개 자동 생성" `
    -Force

Write-Host ""
Write-Host "========================================"
Write-Host " 스케줄러 등록 완료!"
Write-Host " 작업명: $taskName"
Write-Host " 실행: 매일 오전 8:00"
Write-Host " 스크립트: $batPath"
Write-Host "========================================"
Write-Host ""

# 등록 확인
Get-ScheduledTask -TaskName $taskName | Format-List TaskName, State, Description
