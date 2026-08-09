# 會議助理 Web 應用 - 部署檢查表

## 📋 預部署檢查

### 環境檢查

- [ ] Python 版本 >= 3.6
  ```bash
  python3 --version
  ```

- [ ] pip 已安裝
  ```bash
  pip --version
  ```

- [ ] 磁盤空間 >= 10 GB
  ```bash
  df -h | grep /home
  ```

- [ ] 網絡連接正常
  ```bash
  ping google.com
  ```

### 依賴檢查

- [ ] 克隆或下載了項目
  ```bash
  ls -la /home/cgu-csie/meeting-assistence/
  ```

- [ ] 檢查了 Python 依賴
  ```bash
  pip install -r requirements.txt
  ```

- [ ] 驗證 Flask 安裝
  ```bash
  python3 -c "import flask; print(flask.__version__)"
  ```

### 配置檢查

- [ ] 檢查模型文件存在
  ```bash
  ls -lh /home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf
  ```

- [ ] 檢查原有 conda 工作程序
  ```bash
  ls -la run_*_conda.py
  ```

- [ ] 確認 Conda 環境可用
  ```bash
  /home/cgu-csie/miniconda3/bin/python3 --version
  ```

### 文件檢查

- [ ] 檢查所有必要文件存在
  ```bash
  # 後端
  [ -f web_app.py ] && echo "✓ web_app.py"
  [ -f start_web_app.sh ] && echo "✓ start_web_app.sh"
  
  # 前端
  [ -d templates ] && echo "✓ templates/"
  [ -d static ] && echo "✓ static/"
  [ -f templates/index.html ] && echo "✓ templates/index.html"
  [ -f static/css/style.css ] && echo "✓ static/css/style.css"
  [ -f static/js/app.js ] && echo "✓ static/js/app.js"
  ```

- [ ] 檢查啟動腳本可執行
  ```bash
  [ -x start_web_app.sh ] && echo "✓ start_web_app.sh is executable"
  ```

## 🚀 部署步驟

### 1. 準備環境 (5 分鐘)

```bash
# 進入項目目錄
cd /home/cgu-csie/meeting-assistence

# 創建必要的目錄
mkdir -p uploads web_output

# 設置目錄權限
chmod 755 uploads web_output

# 檢查目錄結構
tree -L 2 -I '__pycache__'
```

**驗證**:
- [ ] 目錄結構正確
- [ ] 目錄權限正確

### 2. 安裝依賴 (10 分鐘)

```bash
# 升級 pip
pip install --upgrade pip

# 安裝所有依賴
pip install -r requirements.txt

# 驗證安裝
pip list | grep -E "Flask|Werkzeug"
```

**驗證**:
- [ ] Flask 已安裝
- [ ] Flask-CORS 已安裝

### 3. 驗證配置 (5 分鐘)

```bash
# 檢查模型路徑
export MODEL_PATH="/home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf"
[ -f "$MODEL_PATH" ] && echo "✓ Model found" || echo "✗ Model not found"

# 檢查 conda Python
/home/cgu-csie/miniconda3/bin/python3 -c "import sys; print(f'✓ Python {sys.version}')"

# 檢查會議工作流程
python3 -c "from meeting_v1_integrated import MeetingWorkflow; print('✓ MeetingWorkflow imported')"
```

**驗證**:
- [ ] 模型文件可訪問
- [ ] Conda Python 正常
- [ ] MeetingWorkflow 可導入

### 4. 啟動應用 (5 分鐘)

```bash
# 方式 A: 使用啟動腳本
./start_web_app.sh

# 方式 B: 直接運行
python3 web_app.py

# 方式 C: 後台運行
nohup python3 web_app.py > app.log 2>&1 &
```

**驗證**:
- [ ] 應用啟動無錯誤
- [ ] 監聽地址顯示正確
- [ ] 日誌輸出正常

### 5. 驗證應用 (5 分鐘)

在瀏覽器訪問:
```
http://localhost:5000
```

**驗證**:
- [ ] 頁面正常加載
- [ ] 樣式正確顯示
- [ ] 按鈕可點擊

## 🧪 功能測試

### 基礎功能測試

#### 1. 會議創建測試

- [ ] 點擊「開始新會議」
- [ ] 應用成功創建會話
- [ ] 會話 ID 顯示正確
- [ ] 進度面板展開

```bash
# 驗證命令
curl -X POST http://localhost:5000/api/session/create \
  -H "Content-Type: application/json" \
  -d '{
    "model_path": "/home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf",
    "interval_minutes": 5,
    "overlap_seconds": 60,
    "enable_bluetooth": false
  }'
```

#### 2. 音頻上傳測試

- [ ] 選擇一個小音頻文件 (< 10 MB)
- [ ] 上傳成功提示出現
- [ ] ASR 按鈕變為可用

```bash
# 驗證命令
curl -X POST http://localhost:5000/api/session/test-session/upload \
  -F "file=@test_audio.mp3"
```

#### 3. API 健康檢查

```bash
# 檢查應用是否正常運行
curl http://localhost:5000/

# 檢查 API 狀態端點
curl http://localhost:5000/api/session/test-session/status
```

**預期結果**:
- [ ] 主頁返回 HTTP 200
- [ ] HTML 內容正確
- [ ] API 返回 JSON 格式

### 步驟功能測試 (針對測試會議)

#### 前置條件

```bash
# 上傳測試音頻 (需要準備測試文件)
# 可以使用簡短的音頻文件進行測試
```

#### 測試清單

- [ ] **ASR 步驟**
  - 點擊「執行 ASR」
  - 觀察訊息日誌更新
  - 等待完成（取決於音頻長度）
  - 驗證日誌中有「ASR 完成」消息

- [ ] **PKD 步驟**
  - 點擊「執行 PKD」
  - 觀察進度指示器
  - 驗證完成後有綠色勾號

- [ ] **Actions 步驟**
  - 點擊「執行 Actions」
  - 驗證行動項目提取

- [ ] **Summary 步驟**
  - 點擊「執行 Summary」
  - 驗證摘要生成

- [ ] **Export 步驟**
  - 點擊「執行 Export」
  - 驗證 TXT 文件生成

- [ ] **Bluetooth 步驟** (可選)
  - 如果有配對的藍牙設備
  - 點擊「執行 Bluetooth」
  - 驗證傳送完成

### 下載測試

- [ ] 檢查「下載結果」區域顯示
- [ ] 點擊「下載」按鈕
- [ ] 驗證文件正確下載
- [ ] 驗證文件內容完整

## 📊 性能測試

### 負載測試

```bash
# 使用 ab (Apache Bench) 進行負載測試
ab -n 100 -c 10 http://localhost:5000/

# 或使用 wrk
wrk -t4 -c100 -d30s http://localhost:5000/
```

**驗證**:
- [ ] 應用穩定運行
- [ ] 無明顯性能下降
- [ ] 錯誤率低於 1%

### 內存使用

```bash
# 監控 Python 進程的內存使用
ps aux | grep web_app.py
top -p $(pgrep -f web_app.py)
```

**預期**:
- [ ] 內存使用穩定
- [ ] 無內存洩漏跡象

## 🔧 故障排除

### 問題 1: 應用無法啟動

```bash
# 1. 檢查 Python 環境
python3 --version

# 2. 檢查 Flask 安裝
pip list | grep Flask

# 3. 檢查項目文件
ls -la web_app.py

# 4. 嘗試導入模塊
python3 -c "import flask; print(flask.__version__)"

# 5. 查看詳細錯誤
python3 -u web_app.py 2>&1 | head -50
```

### 問題 2: 端口被佔用

```bash
# 查找佔用進程
lsof -i :5000

# 殺死進程
kill -9 <PID>

# 或者修改配置
# 編輯 web_app.py 的 app.run() 行
# 改為 app.run(host='0.0.0.0', port=8080)
```

### 問題 3: ASR 失敗

```bash
# 檢查 conda 環境
/home/cgu-csie/miniconda3/bin/python3 -c "import funasr"

# 檢查 run_asr_conda.py
ls -la speech/run_asr_conda.py

# 測試運行
sudo -u cgu-csie /home/cgu-csie/miniconda3/bin/python3 speech/run_asr_conda.py --help
```

## ✅ 生產環境檢查清單

### 安全性

- [ ] 更改了 SECRET_KEY
- [ ] 禁用了 DEBUG 模式
- [ ] 配置了 HTTPS
- [ ] 設置了防火牆規則
- [ ] 配置了身份認證

### 可靠性

- [ ] 配置了日誌轉輪
- [ ] 設置了監控告警
- [ ] 配置了自動重啟
- [ ] 設置了備份計劃
- [ ] 配置了錯誤報告

### 性能

- [ ] 優化了數據庫查詢
- [ ] 配置了緩存
- [ ] 使用了 CDN (如適用)
- [ ] 配置了 gzip 壓縮
- [ ] 進行了負載測試

### 監控

- [ ] 設置了應用監控
- [ ] 配置了服務器監控
- [ ] 設置了日誌分析
- [ ] 配置了告警規則
- [ ] 準備了事件應對方案

## 📞 測試報告提交

測試完成後，記錄以下信息：

```
應用版本: 1.0.0
部署日期: YYYY-MM-DD
測試人員: 
環境: 

測試結果:
- 基礎功能: [ ] 通過 [ ] 失敗
- API 端點: [ ] 通過 [ ] 失敗
- 步驟執行: [ ] 通過 [ ] 失敗
- 文件上傳: [ ] 通過 [ ] 失敗
- 文件下載: [ ] 通過 [ ] 失敗

遇到的問題:
[列出所有問題和解決方案]

建議:
[提出改進建議]
```

## 🚀 上線檢查

- [ ] 所有測試通過
- [ ] 文檔更新完成
- [ ] 監控告警配置
- [ ] 備份策略實施
- [ ] 團隊培訓完成
- [ ] 緊急聯繫方式確認

---

**祝部署順利！** 🎉

---

版本: 1.0.0
最後更新: 2024 年 8 月
