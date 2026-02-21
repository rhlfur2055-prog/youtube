@echo off
chcp 65001 >nul
cd /d C:\tool\yousohrts
set PYTHONIOENCODING=utf-8

echo ============================================
echo [YouShorts v6.0] 자동 생산 파이프라인
echo 시작: %date% %time%
echo API 비용: $0 (Gemini + edge-tts + 무료 크롤링)
echo ============================================

REM ── STEP 1: 트렌드 크롤링 → topics.txt 채우기 ──
echo.
echo [STEP 1] 트렌드 크롤링 (7개 소스)
echo ============================================
py crawl_trends.py --count 5

if errorlevel 1 (
    echo [WARN] 크롤링 실패 - 기존 topics.txt로 계속
) else (
    echo [OK] topics.txt 자동 채우기 완료
)

REM ── STEP 2: topics.txt 기반 영상 생산 ──
echo.
echo [STEP 2] 영상 생산 (topics.txt 큐)
echo ============================================
py mass_produce.py --count 5 --topics-file topics.txt --delay 120

REM ── 결과 로그 저장 ──
if not exist logs mkdir logs
echo [%date% %time%] 자동 생산 완료 >> logs\auto_schedule.log

echo.
echo ============================================
echo [DONE] 파이프라인 완료: %date% %time%
echo ============================================
