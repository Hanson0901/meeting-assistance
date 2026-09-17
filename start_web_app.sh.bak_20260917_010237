#!/bin/bash

# 會議助理 - 網頁應用啟動腳本

set -e

# 顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     會議助理 - 網頁應用啟動程序           ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo ""

# 檢查 Python
echo -e "${YELLOW}[1/5]${NC} 檢查 Python..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ 找不到 Python 3${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}✓ Python ${PYTHON_VERSION} 已安裝${NC}"
echo ""

# 檢查項目目錄
echo -e "${YELLOW}[2/5]${NC} 檢查項目目錄..."
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo -e "${GREEN}✓ 項目目錄: ${PROJECT_ROOT}${NC}"
echo ""

# 檢查依賴
echo -e "${YELLOW}[3/5]${NC} 檢查 Python 依賴..."
if ! python3 -c "import flask" 2>/dev/null; then
    echo -e "${YELLOW}! Flask 未安裝，正在安裝...${NC}"
    pip install Flask>=2.3.0 Flask-CORS>=4.0.0 Werkzeug>=2.3.0
    echo -e "${GREEN}✓ Flask 已安裝${NC}"
else
    echo -e "${GREEN}✓ Flask 已安裝${NC}"
fi
echo ""

# 檢查必要文件
echo -e "${YELLOW}[4/5]${NC} 檢查必要文件..."
FILES_TO_CHECK=(
    "web_app.py"
    "templates/index.html"
    "static/css/style.css"
    "static/js/app.js"
    "meeting_v1_integrated.py"
)

for file in "${FILES_TO_CHECK[@]}"; do
    if [ -f "$PROJECT_ROOT/$file" ]; then
        echo -e "${GREEN}✓${NC} $file"
    else
        echo -e "${RED}✗${NC} $file 不存在"
        exit 1
    fi
done
echo ""

# 創建必要目錄
echo -e "${YELLOW}[5/5]${NC} 創建必要目錄..."
mkdir -p "$PROJECT_ROOT/uploads"
mkdir -p "$PROJECT_ROOT/web_output"
echo -e "${GREEN}✓ 目錄已創建或已存在${NC}"
echo ""

# 顯示配置信息
echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║             配置信息                       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo -e "${YELLOW}應用地址:${NC}        http://localhost:5000"
echo -e "${YELLOW}項目目錄:${NC}        $PROJECT_ROOT"
echo -e "${YELLOW}上傳目錄:${NC}        $PROJECT_ROOT/uploads"
echo -e "${YELLOW}輸出目錄:${NC}        $PROJECT_ROOT/web_output"
echo ""

# 詢問是否啟動
echo -e "${BLUE}按 Enter 鍵啟動應用... 或按 Ctrl+C 取消${NC}"
read

# 啟動應用
echo -e "${GREEN}正在啟動應用...${NC}"
echo ""

cd "$PROJECT_ROOT"
python3 web_app.py
