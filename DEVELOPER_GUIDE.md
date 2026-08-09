# 會議助理網頁應用 - 開發者指南

## 🛠️ 架構設計

### 技術棧

- **後端**: Flask 3.x
- **前端**: HTML5 + CSS3 + Vanilla JavaScript
- **數據交換**: RESTful JSON API
- **會話管理**: 內存存儲（可擴展到 Redis）
- **文件存儲**: 本地文件系統

### 系統架構圖

```
┌─────────────────────────────────────────────────────────┐
│                   前端界面 (HTML/CSS/JS)                 │
│  - 設置面板                                              │
│  - 進度面板                                              │
│  - 訊息日誌                                              │
│  - 下載管理                                              │
└──────────────────┬──────────────────────────────────────┘
                   │ AJAX/JSON API
                   │
┌──────────────────▼──────────────────────────────────────┐
│              Flask Web 應用 (web_app.py)                 │
│  ┌────────────────────────────────────────────────────┐ │
│  │  API 層                                            │ │
│  │  - /api/session/* (會話管理)                        │ │
│  │  - /api/session/step/* (步驟執行)                   │ │
│  │  - /api/session/download/* (檔案下載)               │ │
│  └────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────┐ │
│  │  業務邏輯層                                        │ │
│  │  - 會話管理                                        │ │
│  │  - 狀態跟踪                                        │ │
│  │  - 錯誤處理                                        │ │
│  └────────────────────────────────────────────────────┘ │
└──────────────────┬──────────────────────────────────────┘
                   │ 調用 MeetingWorkflow
                   │
┌──────────────────▼──────────────────────────────────────┐
│         會議工作流程 (meeting_v1_integrated.py)           │
│  - step2_transcribe() - ASR                            │
│  - step3_run_pkd_reports() - PKD                       │
│  - step4_extract_actions() - Actions                  │
│  - step5_generate_summary() - Summary                 │
│  - step6_export_txt() - Export                        │
│  - 藍牙傳送功能                                        │
└──────────────────┬──────────────────────────────────────┘
                   │ 調用 conda worker
                   │
┌──────────────────▼──────────────────────────────────────┐
│               外部資源 (子進程)                           │
│  - run_asr_conda.py - Conda ASR Worker                │
│  - run_pkd_conda.py - Conda PKD Worker                │
│  - run_actions_conda.py - Conda Actions Worker        │
│  - run_summary_conda.py - Conda Summary Worker        │
└─────────────────────────────────────────────────────────┘
```

## 📁 代碼結構

### web_app.py 組織

```
web_app.py
├── 導入和配置
│   └── Flask 應用初始化
├── 全局變量
│   ├── workflows: 會話工作流程存儲
│   └── workflow_states: 會話狀態存儲
├── 路由和 API 端點
│   ├── @app.route('/') - 主頁
│   ├── @app.route('/api/session/*') - 會話 API
│   ├── @app.route('/api/session/*/step/*') - 步驟執行 API
│   └── @app.route('/api/session/*/download/*') - 文件下載 API
├── 錯誤處理
│   ├── @app.errorhandler(404)
│   └── @app.errorhandler(500)
└── 主函數
    └── if __name__ == '__main__'
```

### app.js 組織

```
app.js
├── 全局變量
│   ├── currentSessionId
│   └── statusCheckInterval
├── 主要函數
│   ├── startNewSession() - 開始會議
│   ├── handleFileSelect() - 處理檔案上傳
│   ├── runStep() - 執行步驟
│   ├── monitorStep() - 監控步驟執行
│   ├── refreshStatus() - 刷新狀態
│   └── endSession() - 結束會議
├── 輔助函數
│   ├── getSessionStatus() - 獲取狀態
│   ├── updateStepStatus() - 更新步驟狀態
│   ├── updateNextEnabledButtons() - 更新按鈕狀態
│   ├── showMessage() - 顯示訊息
│   ├── updateDownloadList() - 更新下載列表
│   └── downloadFile() - 下載文件
└── 初始化
    └── DOMContentLoaded 事件
```

## 🔄 數據流程

### 會話建立流程

```
1. 用戶點擊「開始新會議」
   ↓
2. 前端 POST /api/session/create
   ↓
3. 後端建立 MeetingWorkflow 實例
   ↓
4. 後端初始化工作目錄和日誌
   ↓
5. 返回 session_id 和 output_dir
   ↓
6. 前端存儲 currentSessionId
   ↓
7. 顯示進度面板
```

### 步驟執行流程

```
1. 用戶點擊步驟按鈕（如「執行 ASR」）
   ↓
2. 前端禁用所有按鈕
   ↓
3. 前端 POST /api/session/<id>/step/<name>
   ↓
4. 後端在線程中執行步驟
   ↓
5. 步驟返回後端結果
   ↓
6. 前端每秒輪詢 GET /api/session/<id>/status
   ↓
7. 前端檢測步驟完成或錯誤
   ↓
8. 前端更新 UI 和啟用下一步按鈕
```

## 🧵 多線程設計

### 為什麼使用線程？

避免阻塞 Flask 主線程，提供實時的用戶界面反應。

### 線程模型

```python
# ASR 執行
thread = threading.Thread(target=asr_task, daemon=True)
thread.start()

# 前端持續輪詢狀態
GET /api/session/<id>/status
```

### 注意事項

- 所有線程都是守護線程 (daemon=True)
- 狀態通過全局字典存儲
- 建議添加鎖（threading.Lock）以保護共享資源

## 🔐 安全考慮

### 當前實現

- 會話 ID 基於 UUID
- 輸出目錄隔離
- 無身份驗證

### 建議改進

```python
# 添加簡單身份驗證
from functools import wraps
from flask import request

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Auth-Token')
        if not token or not verify_token(token):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# 使用會話鎖
import threading
session_locks = {}

def get_session_lock(session_id):
    if session_id not in session_locks:
        session_locks[session_id] = threading.Lock()
    return session_locks[session_id]
```

## 🧪 單元測試

### 測試框架設置

```bash
pip install pytest pytest-flask
```

### 示例測試

```python
# tests/test_api.py
import pytest
from web_app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_create_session(client):
    response = client.post('/api/session/create', json={
        'model_path': '/path/to/model.gguf',
        'interval_minutes': 5,
        'overlap_seconds': 60,
        'enable_bluetooth': False
    })
    assert response.status_code == 200
    data = response.get_json()
    assert 'session_id' in data
```

運行測試：

```bash
pytest tests/
```

## 📈 性能優化

### 1. 緩存優化

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def get_workflow(session_id):
    return workflows.get(session_id)
```

### 2. 異步任務隊列

使用 Celery 替代線程：

```bash
pip install celery redis
```

```python
from celery import Celery

celery = Celery('meeting_app', broker='redis://localhost:6379')

@celery.task
def run_asr_task(session_id):
    # 長時間運行的任務
    pass
```

### 3. 數據庫持久化

使用 SQLAlchemy 存儲會話：

```python
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy(app)

class Session(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    status = db.Column(db.String(50))
    created_at = db.Column(db.DateTime)
    output_dir = db.Column(db.String(500))
```

## 🐛 調試技巧

### 啟用詳細日誌

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 在代碼中添加
logger.debug(f"Session {session_id}: {message}")
```

### 前端調試

打開瀏覽器開發工具 (F12)：
- **Console**: 查看 JavaScript 錯誤
- **Network**: 監控 API 請求
- **Storage**: 查看會話存儲

### 後端調試

```bash
# 啟用 Flask 調試模式
FLASK_ENV=development python3 web_app.py

# 使用 pdb 調試
import pdb; pdb.set_trace()
```

## 📚 擴展功能

### 添加新的步驟

1. 在 `meeting_v1_integrated.py` 中添加方法
2. 在 `web_app.py` 中創建 API 端點
3. 在前端 HTML 中添加按鈕
4. 在 `app.js` 中添加處理邏輯

### 示例：添加「文字搜索」步驟

```python
# web_app.py
@app.route('/api/session/<session_id>/step/search', methods=['POST'])
def run_search(session_id):
    query = request.json.get('query')
    # 執行搜索邏輯
    # ...
```

```html
<!-- templates/index.html -->
<div class="step-section">
    <h3>🔍 步驟 7: 文字搜索</h3>
    <input type="text" id="searchQuery" placeholder="輸入搜索詞...">
    <button onclick="runSearch()">執行搜索</button>
</div>
```

## 🌍 本地化

### 多語言支持

使用 Flask-Babel：

```bash
pip install Flask-Babel
```

```python
from flask_babel import Babel, gettext

babel = Babel(app)

@app.route('/api/session/create')
def create_session():
    message = gettext('Session created successfully')
```

## 🚀 部署檢查清單

- [ ] 安裝所有依賴 (pip install -r requirements.txt)
- [ ] 配置模型路徑
- [ ] 設置上傳和輸出目錄權限
- [ ] 配置 HTTPS (生產環境)
- [ ] 設置反向代理 (Nginx/Apache)
- [ ] 配置日誌輪轉
- [ ] 設置備份計劃
- [ ] 監控磁盤空間
- [ ] 設置錯誤警報
- [ ] 進行負載測試

## 📞 貢獻指南

1. Fork 項目
2. 創建功能分支 (git checkout -b feature/new-feature)
3. 提交更改 (git commit -m 'Add feature')
4. 推送到分支 (git push origin feature/new-feature)
5. 開啟 Pull Request

---

**最後更新**: 2024 年 8 月
**版本**: 1.0.0 Developer Guide
