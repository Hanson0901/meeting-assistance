# 會議助理 - 網頁應用使用指南

## 📌 概述

這是一個基於 Flask 的網頁應用，提供了一個用戶友好的界面來執行會議助理的各個環節。用戶可以通過按鈕輕鬆觸發 ASR、PKD 報告、行動項目提取、摘要生成、TXT 匯出和藍牙傳送等功能。

## 🎯 功能特性

| 功能 | 描述 |
|------|------|
| **ASR 語音轉文字** | 將音頻文件轉換為文字轉錄 |
| **PKD 報告** | 生成 People (參與者) / Keypoints (重點) / Decisions (決策) |
| **行動項目提取** | 自動提取會議中需要跟進的行動項目 |
| **摘要生成** | 生成整體會議摘要和標題 |
| **TXT 匯出** | 將所有結果匯出為結構化的 TXT 檔案 |
| **藍牙傳送** | 自動將檔案傳送到已配對的藍牙裝置 |

## 🚀 快速開始

### 1. 安裝依賴

```bash
# 進入項目目錄
cd /home/cgu-csie/meeting-assistence

# 安裝所有依賴
pip install -r requirements.txt
```

### 2. 啟動網頁應用

```bash
# 使用 Python 直接運行
python3 web_app.py
```

或者使用 Conda 環境：

```bash
# 激活 conda 環境
conda activate your_env_name

# 運行應用
python3 web_app.py
```

### 3. 訪問應用

打開瀏覽器，訪問：
```
http://localhost:5000
```

## 📖 使用步驟

### 步驟 1: 配置設置

在網頁界面上：
1. **模型路徑**: 輸入 LLM 模型的絕對路徑（預設: `/home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf`）
2. **時間間隔**: 設置會議分段時間（預設: 5 分鐘）
3. **重疊時長**: 設置分段之間的重疊時間（預設: 60 秒）
4. **藍牙傳送**: 勾選是否啟用藍牙功能

點擊「開始新會議」按鈕。

### 步驟 2: 上傳音頻

1. 在「步驟 0: 上傳音頻」區域選擇音頻檔案
2. 支持格式: `.mp3`, `.wav`, `.m4a`, `.mkv` 等大多數音頻/視頻格式
3. 文件上傳後，「執行 ASR」按鈕將啟用

### 步驟 3: 執行各環節

按順序點擊各個步驟的按鈕：

#### 🗣️ 步驟 1: ASR 語音轉文字
- 執行時間: 取決於音頻長度
- 輸出: SRT 字幕文件和 JSON 緩存

#### 👥 步驟 2: PKD 報告
- 執行時間: 5-10 分鐘（取決於音頻長度和模型）
- 輸出: People、Keypoints、Decisions 報告

#### ✅ 步驟 3: 提取行動項目
- 執行時間: 2-3 分鐘
- 輸出: 行動項目清單

#### 📋 步驟 4: 生成摘要
- 執行時間: 2-3 分鐘
- 輸出: 會議摘要和標題

#### 📤 步驟 5: 匯出 TXT
- 執行時間: 立即
- 輸出: 整合的 TXT 報告檔案

#### 📱 步驟 6: 藍牙傳送
- 執行時間: 取決於檔案大小
- 前提: 需要已配對的藍牙裝置

### 步驟 4: 監控進度

- **訊息日誌**: 實時顯示各步驟的執行狀態
- **綠色勾號** (✓): 步驟已完成
- **黃色旋轉圖標**: 步驟執行中
- **紅色 X**: 步驟出錯

### 步驟 5: 下載結果

完成所有步驟後，在「下載結果」區域會顯示生成的檔案：
- 會議摘要 (TXT)
- 行動項目 (TXT)
- 摘要 (TXT)

點擊「下載」按鈕下載各個檔案。

### 步驟 6: 結束會議

點擊「結束會議」按鈕清除此次會議的所有數據。

## 🗂️ 文件結構

```
meeting-assistence/
├── web_app.py                 # Flask 後端應用
├── templates/
│   └── index.html             # 前端主頁
├── static/
│   ├── css/
│   │   └── style.css          # 樣式表
│   └── js/
│       └── app.js             # 前端邏輯
├── web_output/                # Web 應用輸出目錄
│   └── [session_id]/          # 各會議會話的輸出
├── requirements.txt           # Python 依賴
└── meeting_v1_integrated.py   # 核心會議工作流程
```

## 🔧 API 端點

### 會話管理

```
POST /api/session/create
  建立新的會議會話
  參數: model_path, interval_minutes, overlap_seconds, enable_bluetooth
  返回: session_id, output_dir

POST /api/session/<session_id>/upload
  上傳音頻檔案
  參數: file (multipart form data)

GET /api/session/<session_id>/status
  獲取會話狀態
  返回: current_step, steps_completed, messages, errors, files

POST /api/session/<session_id>/clear
  清除會話
```

### 執行步驟

```
POST /api/session/<session_id>/step/asr
  執行 ASR 轉錄

POST /api/session/<session_id>/step/pkd
  執行 PKD 報告生成

POST /api/session/<session_id>/step/actions
  執行行動項目提取

POST /api/session/<session_id>/step/summary
  執行摘要生成

POST /api/session/<session_id>/step/export
  執行 TXT 匯出

POST /api/session/<session_id>/step/bluetooth
  執行藍牙傳送
```

### 檔案下載

```
GET /api/session/<session_id>/download/<filename>
  下載指定檔案
  支持的檔案名: meeting_summary, actions, summary
```

## 🐛 故障排除

### 問題: ASR 失敗

**原因**: 可能是音頻設備配置或模型路徑問題

**解決方案**:
1. 檢查音頻檔案格式是否正確
2. 確保 conda 環境配置正確
3. 檢查 `run_asr_conda.py` 的執行權限

```bash
chmod +x /home/cgu-csie/meeting-assistence/speech/run_asr_conda.py
```

### 問題: PKD/Actions/Summary 執行失敗

**原因**: 可能是模型路徑錯誤或 conda 環境問題

**解決方案**:
1. 驗證模型文件是否存在:
```bash
ls -lh /home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf
```

2. 測試 conda 環境中的 Python:
```bash
/home/cgu-csie/miniconda3/bin/python3 --version
```

3. 檢查項目根目錄的 sys.path 設置

### 問題: 藍牙傳送失敗

**原因**: 藍牙服務未啟動或裝置未配對

**解決方案**:
1. 檢查藍牙服務:
```bash
systemctl --user status obex
```

2. 啟動 OBEX 服務:
```bash
systemctl --user start obex
```

3. 檢查已配對的裝置:
```bash
bluetoothctl paired-devices
```

### 問題: 網頁無法訪問

**原因**: Flask 應用未啟動或埠被佔用

**解決方案**:
1. 檢查應用是否在運行:
```bash
ps aux | grep web_app.py
```

2. 檢查埠 5000 是否被佔用:
```bash
lsof -i :5000
```

3. 如果埠被佔用，修改 `web_app.py` 中的埠號:
```python
app.run(host='0.0.0.0', port=5001)  # 改為其他埠
```

## 📊 性能優化建議

1. **使用高性能模型**: 確保 GPU 環境配置良好
2. **增加時間間隔**: 如果音頻很長，增加時間間隔以減少處理時間
3. **並行處理**: 系統支持多個會話並行運行
4. **定期清理**: 定期清除舊的會議輸出以節省磁盤空間

```bash
# 清理超過 7 天的輸出
find /home/cgu-csie/meeting-assistence/web_output -type f -mtime +7 -delete
```

## 🔐 安全考慮

1. **訪問控制**: 目前無身份驗證，建議在生產環境中添加
2. **檔案上傳限制**: 預設最大 2GB，可根據需要調整
3. **HTTPS**: 建議使用反向代理（如 Nginx）配置 HTTPS
4. **日誌監控**: 檢查應用日誌以發現潛在問題

## 📝 日誌文件

應用日誌保存在各會話的輸出目錄中：
```
/home/cgu-csie/meeting-assistence/web_output/[session_id]/output_run_*.log
```

查看日誌:
```bash
tail -f /home/cgu-csie/meeting-assistence/web_output/[session_id]/output_run_*.log
```

## 🚀 高級配置

### 使用 Gunicorn 部署

```bash
# 安裝 Gunicorn
pip install gunicorn

# 運行應用
gunicorn -w 4 -b 0.0.0.0:5000 web_app:app
```

### 使用 Nginx 反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 環境變量配置

```bash
# 設置自訂埠
export FLASK_PORT=5001

# 設置 Flask 環境
export FLASK_ENV=production

# 設置日誌級別
export LOG_LEVEL=INFO
```

## 📧 支持與反饋

如有任何問題或建議，請提交 Issue 或 Pull Request。

## 📄 許可證

本項目遵循 [LICENSE.txt](LICENSE.txt) 中的許可條款。

---

**最後更新**: 2024 年 8 月
**版本**: 1.0.0
