@echo off
chcp 65001 >nul
cd /d C:\tool\yousohrts
set PYTHONIOENCODING=utf-8

echo ============================================
echo [YouShorts v5.0] 자동 생산 시작: %date% %time%
echo API 비용: $0 (Gemini + edge-tts + 무료 크롤링)
echo ============================================

REM 바이럴 소스 3개 자동 생산
py mass_produce.py --count 3 --source viral --delay 120

REM 결과 로그 저장
echo [%date% %time%] 자동 생산 완료 >> logs\auto_schedule.log
