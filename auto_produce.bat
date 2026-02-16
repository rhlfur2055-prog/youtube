@echo off
chcp 65001 >nul
cd /d C:\tool\yousohrts
set PYTHONIOENCODING=utf-8

echo ============================================
echo [YouShorts] 자동 생산 시작: %date% %time%
echo ============================================

REM 오전 8시 배치 (3개)
py mass_produce.py --count 3 --style community --max-per-day 3 --delay 120 --schedule-interval 120

REM 결과 로그 저장
echo [%date% %time%] 자동 생산 완료 >> logs\auto_schedule.log
