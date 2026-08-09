# 會議助理 - 網頁應用快速開始

## 🚀 3 步快速啟動

### 方式 1: 使用啟動腳本（推薦）

```bash
# 進入項目目錄
cd /home/cgu-csie/meeting-assistence

# 給腳本執行權限
chmod +x start_web_app.sh

# 運行腳本
./start_web_app.sh
```

### 方式 2: 直接運行 Python

```bash
cd /home/cgu-csie/meeting-assistence
python3 web_app.py
```

### 方式 3: 使用 Conda 環境

```bash
# 激活 conda 環境
conda activate your_env_name

# 進入項目目錄
cd /home/cgu-csie/meeting-assistence

# 運行應用
python3 web_app.py
```

## 📱 訪問應用

啟動後，打開瀏覽器訪問：
```
http://localhost:5000
```

## 🎯 基本使用流程

1. **配置設置**
   - 模型路徑（預設正確）
   - 時間間隔和重疊時長（可保留預設）
   - 啟用藍牙（如需要）
   - 點擊「開始新會議」

2. **上傳音頻**
   - 選擇會議音頻檔案
   - 支持 MP3、WAV、M4A、MKV 等格式

3. **按順序執行**
   - 🗣️ ASR → 👥 PKD → ✅ Actions → 📋 Summary → 📤 Export → 📱 Bluetooth

4. **監控進度**
   - 查看訊息日誌
   - 觀察各步驟狀態

5. **下載結果**
   - 完成後在「下載結果」區域下載文件

## ⚠️ 常見問題

### 應用無法啟動

```bash
# 檢查埠是否被佔用
lsof -i :5000

# 安裝 Flask
pip install Flask Flask-CORS

# 查看完整錯誤
python3 -u web_app.py
```

### ASR 轉錄失敗

```bash
# 檢查音頻文件
file your_audio.mp3

# 測試 conda 環境
/home/cgu-csie/miniconda3/bin/python3 -c "import funasr; print('OK')"
```

### 藍牙傳送不工作

```bash
# 檢查藍牙服務
systemctl --user status obex

# 啟動服務
systemctl --user start obex

# 查看已配對裝置
bluetoothctl paired-devices
```

## 🔧 自訂配置

編輯 `web_app.py` 的配置部分：

```python
# 修改埠號
app.run(host='0.0.0.0', port=8080)

# 修改上傳限制（MB）
app.config['MAX_CONTENT_LENGTH'] = 4000 * 1024 * 1024  # 4GB
```

## 📊 監控應用

### 查看實時日誌

```bash
# 帶詳細日誌運行
FLASK_ENV=development python3 web_app.py

# 在另一個終端查看
tail -f /path/to/output/output_run_*.log
```

### 檢查會話狀態

```bash
# 查看輸出目錄
ls -la web_output/

# 查看特定會話
ls -la web_output/abc12345/
```

## 🌐 遠程訪問

如需從其他機器訪問，使用機器的 IP 地址：

```
http://your-machine-ip:5000
```

或使用 SSH 隧道：

```bash
# 在本地機器上
ssh -L 5000:localhost:5000 user@remote-machine
# 然後訪問 http://localhost:5000
```

## 📈 生產環境部署

### 使用 Gunicorn

```bash
# 安裝 Gunicorn
pip install gunicorn

# 運行多個 worker
gunicorn -w 4 -b 0.0.0.0:5000 web_app:app

# 後台運行
nohup gunicorn -w 4 -b 0.0.0.0:5000 web_app:app > app.log 2>&1 &
```

### 使用 Systemd 服務

創建 `/etc/systemd/user/meeting-app.service`：

```ini
[Unit]
Description=Meeting Assistant Web App
After=network.target

[Service]
Type=simple
User=cgu-csie
WorkingDirectory=/home/cgu-csie/meeting-assistence
ExecStart=/home/cgu-csie/miniconda3/bin/python3 /home/cgu-csie/meeting-assistence/web_app.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

啟動服務：

```bash
# 重新加載服務配置
systemctl --user daemon-reload

# 啟動服務
systemctl --user start meeting-app

# 設置自動啟動
systemctl --user enable meeting-app

# 查看狀態
systemctl --user status meeting-app

# 查看日誌
journalctl --user -u meeting-app -f
```

## 💾 備份和恢復

```bash
# 備份所有會議輸出
tar -czf meeting_backups_$(date +%Y%m%d).tar.gz web_output/

# 清理舊輸出（保留 30 天內的）
find web_output -type f -mtime +30 -delete
```

## 🆘 獲取幫助

查看完整文檔：
```bash
cat WEB_APP_GUIDE.md
```

檢查應用日誌：
```bash
ls -la web_output/*/output_run_*.log
```

## 📞 支持

遇到問題？檢查以下文件：
- [WEB_APP_GUIDE.md](WEB_APP_GUIDE.md) - 完整文檔
- [readme.md](readme.md) - 項目說明

---

**祝你使用愉快！** 🎉
