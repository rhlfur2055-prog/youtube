#!/bin/bash
# =============================================================
# 🚀 YouTube Shorts 양산형 팩토리 v3.0 - 원커맨드 실행기
# =============================================================
# 📸 v3 변경: 디시/네이트판 스크린샷 배경 + 자연스러운 폰트
#
# 사용법:
#   chmod +x run.sh
#   ./run.sh                         # 디시 유머갤 3개 (기본)
#   ./run.sh dcinside humor 5        # 디시 유머갤 5개
#   ./run.sh natepann 3              # 네이트판 3개
#   ./run.sh url "https://..."       # 특정 URL
#   ./run.sh topic "상견례 파토"      # 주제만으로
#   ./run.sh batch                   # 5개 주제 양산
# =============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════════════╗"
echo "║  🎬 YouTube Shorts 양산형 팩토리 v3.0            ║"
echo "║  📸 스크린샷 배경 + 자연스러운 한글 폰트         ║"
echo "╚═══════════════════════════════════════════════════╝"
echo -e "${NC}"

# ─── 환경변수 ───
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo -e "${RED}❌ ANTHROPIC_API_KEY 미설정!${NC}"
    echo "  export ANTHROPIC_API_KEY='sk-ant-api03-...'"
    exit 1
fi

[ -z "$APIFY_API_TOKEN" ] && echo -e "${YELLOW}⚠️  APIFY_API_TOKEN 미설정 → 폴백 모드${NC}"

# ─── 의존성 ───
echo -e "${CYAN}📦 의존성 확인...${NC}"
pip install anthropic edge-tts requests apify-client Pillow --break-system-packages -q 2>/dev/null

if ! command -v ffmpeg &> /dev/null; then
    echo -e "${YELLOW}📦 FFmpeg 설치...${NC}"
    sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg
fi

# 한글 폰트 설치
if ! fc-list :lang=ko | grep -qi "nanum"; then
    echo -e "${YELLOW}📦 한글 폰트 설치...${NC}"
    sudo apt-get install -y -qq fonts-nanum fonts-nanum-extra 2>/dev/null
    fc-cache -f 2>/dev/null
fi

# ─── 실행 ───
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${DIR}/main.py"
MODE="${1:-dcinside}"
ARG2="${2:-humor}"
ARG3="${3:-3}"

case "$MODE" in
    dcinside)
        echo -e "${GREEN}📡 디시인사이드 [${ARG2}] ${ARG3}개${NC}"
        python3 "$PY" --source dcinside --gallery "$ARG2" --count "$ARG3"
        ;;
    natepann)
        echo -e "${GREEN}📡 네이트판 ${ARG2}개${NC}"
        python3 "$PY" --source natepann --count "$ARG2"
        ;;
    url)
        echo -e "${GREEN}🔗 URL: ${ARG2}${NC}"
        python3 "$PY" --url "$ARG2"
        ;;
    topic)
        echo -e "${GREEN}📝 주제: ${ARG2}${NC}"
        python3 "$PY" --topic "$ARG2" --skip-crawl
        ;;
    batch)
        echo -e "${GREEN}🏭 배치 양산 모드${NC}"
        TOPICS=(
            "상견례에서 파토난 썰"
            "알바하다 레전드 진상 만난 썰"
            "소개팅에서 벌어진 충격 실화"
            "군대에서 생긴 소름돋는 일"
            "회사 면접 역대급 실수"
        )
        for topic in "${TOPICS[@]}"; do
            echo -e "\n${CYAN}━━━ ${topic} ━━━${NC}"
            python3 "$PY" --topic "$topic" --skip-crawl
        done
        ;;
    help|--help|-h)
        python3 "$PY" --help
        ;;
    *)
        echo -e "${RED}❌ 알 수 없는 모드: $MODE${NC}"
        echo "  ./run.sh help"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}✅ 완료! output/ 확인하세요${NC}"
[ -d "./output" ] && find ./output -name "shorts_*.mp4" -newer "$PY" -exec ls -lh {} \; 2>/dev/null
