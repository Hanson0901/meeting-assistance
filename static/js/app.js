/* ==========================================
   會議助理網頁應用 - 前端邏輯
   ========================================== */

let currentSessionId = null;
let statusCheckInterval = null;
let currentHistorySessionId = null;
let isRecording = false;
let btDevices = [];
let selectedBluetoothDevice = null;

// ==========================================
// 主要函數
// ==========================================

/**
 * 開始新會議
 */
async function startNewSession() {
    try {
        showMessage('正在建立會議會話...', 'info');
        
        const modelPath = document.getElementById('modelPath').value.trim();
        const intervalMinutes = parseInt(document.getElementById('intervalMinutes').value);
        const overlapSeconds = parseInt(document.getElementById('overlapSeconds').value);
        const enableBluetooth = document.getElementById('enableBluetooth').checked;
        
        if (!modelPath) {
            showMessage('請輸入模型路徑', 'error');
            return;
        }
        
        const response = await fetch('/api/session/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                model_path: modelPath,
                interval_minutes: intervalMinutes,
                overlap_seconds: overlapSeconds,
                enable_bluetooth: enableBluetooth
            })
        });
        
        const data = await response.json();
        
        if (!data.success) {
            showMessage(`建立會話失敗: ${data.error}`, 'error');
            return;
        }
        
        currentSessionId = data.session_id;
        
        // 隱藏設置面板，顯示進度面板
        document.querySelector('.setup-panel').style.display = 'none';
        document.getElementById('progressPanel').style.display = 'block';
        document.getElementById('sessionId').textContent = currentSessionId;
        
        // 重置上傳狀態
        document.getElementById('audioFile').value = '';
        document.getElementById('uploadStatus').textContent = '';
        document.getElementById('uploadStatus').className = '';

        // 重置錄音與藍牙裝置選擇狀態
        isRecording = false;
        updateRecordButtonUI();
        btDevices = [];
        selectedBluetoothDevice = null;
        const btListEl = document.getElementById('btDeviceList');
        if (btListEl) btListEl.innerHTML = '';
        const btStatusEl = document.getElementById('btScanStatus');
        if (btStatusEl) { btStatusEl.textContent = ''; btStatusEl.className = 'status-text'; }
        
        showMessage(`會議會話已建立: ${currentSessionId}`, 'success');
        showMessage('請上傳音頻檔案開始處理...', 'info');
        
        // 確保 ASR 按鈕保持禁用（直到上傳檔案）
        document.getElementById('asrBtn').disabled = true;
        
        // 開始定期檢查狀態
        startStatusCheck();
        
    } catch (error) {
        showMessage(`錯誤: ${error.message}`, 'error');
    }
}

/**
 * 處理檔案選擇
 */
async function handleFileSelect(event) {
    const file = event.target.files[0];
    
    if (!file) {
        return;
    }
    
    if (!currentSessionId) {
        showMessage('請先建立會議會話', 'error');
        return;
    }
    
    try {
        showMessage(`正在上傳 ${file.name}...`, 'info');
        
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch(`/api/session/${currentSessionId}/upload`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (!data.success) {
            showMessage(`上傳失敗: ${data.error}`, 'error');
            return;
        }
        
        const uploadStatusEl = document.getElementById('uploadStatus');
        uploadStatusEl.innerHTML = iconSVG('success', 15) + ` ${escapeHtml(file.name)} 已上傳`;
        uploadStatusEl.className = 'status-text success';
        showMessage(`音頻檔案已上傳: ${file.name}`, 'success');
        
        // 上傳成功後啟用 ASR 按鈕
        document.getElementById('asrBtn').disabled = false;
        showMessage('已準備好執行 ASR，請點擊「執行 ASR」按鈕', 'info');
        
    } catch (error) {
        showMessage(`上傳錯誤: ${error.message}`, 'error');
    }
}

/**
 * 執行特定步驟
 */
async function runStep(stepName) {
    if (!currentSessionId) {
        showMessage('會話不存在', 'error');
        return;
    }
    
    // ASR 必須有上傳的音頻檔案
    if (stepName === 'asr') {
        const uploadStatus = document.getElementById('uploadStatus');
        if (!uploadStatus.classList.contains('success')) {
            showMessage('請先上傳音頻檔案後再執行 ASR', 'error');
            return;
        }
    }
    
    try {
        // 禁用按鈕
        disableStepButtons();
        
        const endpoint = `/api/session/${currentSessionId}/step/${stepName}`;
        
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (!data.success) {
            showMessage(`${stepName.toUpperCase()} 啟動失敗: ${data.error}`, 'error');
            enableStepButtons();
            return;
        }
        
        showMessage(`${stepName.toUpperCase()} 已開始執行...`, 'info', stepName);
        updateStepStatus(stepName, 'running');
        
        // 開始監控狀態
        monitorStep(stepName);
        
    } catch (error) {
        showMessage(`錯誤: ${error.message}`, 'error');
        enableStepButtons();
    }
}

/**
 * 監控步驟執行
 */
async function monitorStep(stepName) {
    const maxAttempts = 300; // 最多等待 5 分鐘
    let attempts = 0;
    
    while (attempts < maxAttempts) {
        await sleep(1000); // 每秒檢查一次
        attempts++;
        
        const status = await getSessionStatus();
        
        if (!status) {
            break;
        }
        
        // 檢查步驟是否完成
        if (status.steps_completed.includes(stepName)) {
            updateStepStatus(stepName, 'completed');
            enableStepButtons();
            
            // 根據完成的步驟，決定下一個可用的步驟
            updateNextEnabledButtons(status.steps_completed);
            
            break;
        }
        
        // 檢查是否有錯誤
        if (status.errors && status.errors.length > 0) {
            const stepError = status.errors.find(e => e.toLowerCase().includes(stepName));
            if (stepError) {
                updateStepStatus(stepName, 'error');
                showMessage(stepError, 'error');
                enableStepButtons();
                break;
            }
        }
        
        // 檢查是否仍在運行
        if (status.current_step === stepName) {
            // 步驟仍在運行
            continue;
        }
    }
}

/**
 * 刷新狀態
 */
async function refreshStatus() {
    if (!currentSessionId) {
        return;
    }
    
    const status = await getSessionStatus();
    
    if (!status) {
        return;
    }
    
    // 更新步驟狀態
    const stepNames = ['asr', 'pkd', 'actions', 'summary', 'export', 'bluetooth'];
    
    stepNames.forEach(step => {
        if (status.steps_completed.includes(step)) {
            updateStepStatus(step, 'completed');
        }
    });
    
    // 更新訊息
    status.messages.forEach(msg => {
        if (!document.getElementById('messagesLog').textContent.includes(msg)) {
            showMessage(msg, 'success');
        }
    });
    
    status.errors.forEach(err => {
        if (!document.getElementById('messagesLog').textContent.includes(err)) {
            showMessage(err, 'error');
        }
    });
    
    // 定期更新系統日誌
    if (document.getElementById('autoRefreshLogs').checked) {
        updateSystemLogs();
    }
    
    // 更新下載列表
    if (status.files && Object.keys(status.files).length > 0) {
        updateDownloadList(status.files);
    }
    
    // 更新可用按鈕
    updateNextEnabledButtons(status.steps_completed);
}

/**
 * 結束會議
 */
function endSession() {
    if (!currentSessionId) {
        return;
    }
    
    if (!confirm('確定要結束此次會議嗎？')) {
        return;
    }
    
    try {
        // 清除會話
        fetch(`/api/session/${currentSessionId}/clear`, {
            method: 'POST'
        });
        
        // 重置 UI
        currentSessionId = null;
        document.querySelector('.setup-panel').style.display = 'block';
        document.getElementById('progressPanel').style.display = 'none';
        document.getElementById('messagesLog').innerHTML = '<div class="message-item info"><div class="message-item-header"><span class="message-item-icon">' + iconSVG('info', 16) + '</span><span class="message-item-text">等待操作...</span><span class="message-item-expand">' + iconSVG('chevron-right', 14) + '</span></div></div>';
        document.getElementById('systemLogs').innerHTML = '<div class="log-line info">等待日誌信息...</div>';
        document.getElementById('downloadPanel').style.display = 'none';
        document.getElementById('downloadList').innerHTML = '';
        
        // 清除狀態檢查
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
        }
        
        showMessage('會議已結束', 'success');
        
    } catch (error) {
        showMessage(`錯誤: ${error.message}`, 'error');
    }
}

// ==========================================
// 主題切換功能（燈泡按鈕：手動覆蓋淺色/深色背景）
// ==========================================

/**
 * 切換淺色/深色主題，並更新燈泡圖示
 * 使用 data-theme 屬性覆蓋 CSS 中依系統設定的預設值
 */
function toggleTheme() {
    const root = document.documentElement;
    const current = getCurrentTheme();
    const next = current === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    localStorage.setItem('meetingAssistantTheme', next);
    updateThemeToggleIcon(next);
}

/**
 * 取得目前生效的主題（優先讀取手動設定，否則以系統偏好為準）
 */
function getCurrentTheme() {
    const attr = document.documentElement.getAttribute('data-theme');
    if (attr === 'dark' || attr === 'light') {
        return attr;
    }
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/**
 * 更新燈泡按鈕圖示：淺色模式顯示「亮燈」，深色模式顯示「熄燈」
 */
function updateThemeToggleIcon(theme) {
    const iconEl = document.getElementById('themeToggleIcon');
    if (!iconEl) return;
    const iconName = theme === 'dark' ? 'bulb-off' : 'bulb-on';
    iconEl.outerHTML = `<span data-icon="${iconName}" data-icon-size="18" id="themeToggleIcon">${iconSVG(iconName, 18)}</span>`;
}

/**
 * 初始化主題：讀取先前儲存的手動選擇，否則跟隨系統設定
 */
function initTheme() {
    const saved = localStorage.getItem('meetingAssistantTheme');
    if (saved === 'dark' || saved === 'light') {
        document.documentElement.setAttribute('data-theme', saved);
    }
    updateThemeToggleIcon(getCurrentTheme());
}

// ==========================================
// 錄音功能（使用樹梅派麥克風）
// ==========================================

/**
 * 切換錄音狀態：尚未錄音時開始錄音，正在錄音時停止錄音
 */
function toggleRecording() {
    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
}

/**
 * 開始使用樹梅派麥克風錄音
 */
async function startRecording() {
    if (!currentSessionId) {
        showMessage('請先建立會議會話', 'error');
        return;
    }

    try {
        const response = await fetch(`/api/session/${currentSessionId}/record/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();

        if (!data.success) {
            showMessage(`開始錄音失敗: ${data.error}`, 'error');
            return;
        }

        isRecording = true;
        updateRecordButtonUI();

        // 錄音期間停用檔案上傳與 ASR 按鈕
        const fileInput = document.getElementById('audioFile');
        if (fileInput) fileInput.disabled = true;
        const asrBtn = document.getElementById('asrBtn');
        if (asrBtn) asrBtn.disabled = true;

        const uploadStatusEl = document.getElementById('uploadStatus');
        uploadStatusEl.innerHTML = '<span class="loading-spinner"></span> 麥克風錄音中...';
        uploadStatusEl.className = 'status-text';

        showMessage('已開始使用樹梅派麥克風錄音，請於錄製完成後點擊「停止錄音」', 'info');

    } catch (error) {
        showMessage(`開始錄音錯誤: ${error.message}`, 'error');
    }
}

/**
 * 停止錄音，並將產生的音訊檔案設為本次會議的音頻來源
 */
async function stopRecording() {
    if (!currentSessionId) {
        return;
    }

    const recordBtn = document.getElementById('recordBtn');
    if (recordBtn) recordBtn.disabled = true;

    try {
        showMessage('正在停止錄音並處理音訊...', 'info');

        const response = await fetch(`/api/session/${currentSessionId}/record/stop`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();

        isRecording = false;
        updateRecordButtonUI();

        const fileInput = document.getElementById('audioFile');
        if (fileInput) fileInput.disabled = false;

        if (!data.success) {
            showMessage(`停止錄音失敗: ${data.error}`, 'error');
            return;
        }

        const uploadStatusEl = document.getElementById('uploadStatus');
        if (data.ready) {
            uploadStatusEl.innerHTML = iconSVG('success', 15) + ' 麥克風錄音已完成，可執行 ASR';
            uploadStatusEl.className = 'status-text success';
            const asrBtn = document.getElementById('asrBtn');
            if (asrBtn) asrBtn.disabled = false;
            showMessage('錄音已完成，已準備好執行 ASR', 'success');
        } else {
            uploadStatusEl.innerHTML = iconSVG('warning', 15) + ' 錄音已停止，但尚未產生可用的音訊檔案';
            uploadStatusEl.className = 'status-text';
            showMessage('錄音已停止，但尚未偵測到輸出音訊檔案', 'warning');
        }

    } catch (error) {
        showMessage(`停止錄音錯誤: ${error.message}`, 'error');
    } finally {
        if (recordBtn) recordBtn.disabled = false;
    }
}

/**
 * 更新錄音按鈕的圖示、文字與樣式
 */
function updateRecordButtonUI() {
    const recordBtn = document.getElementById('recordBtn');
    const iconEl = document.getElementById('recordBtnIcon');
    const labelEl = document.getElementById('recordBtnLabel');
    if (!recordBtn || !iconEl || !labelEl) return;

    if (isRecording) {
        recordBtn.classList.add('recording');
        iconEl.outerHTML = `<span data-icon="stop-circle" data-icon-size="16" id="recordBtnIcon">${iconSVG('stop-circle', 16)}</span>`;
        labelEl.textContent = '停止錄音';
    } else {
        recordBtn.classList.remove('recording');
        iconEl.outerHTML = `<span data-icon="mic" data-icon-size="16" id="recordBtnIcon">${iconSVG('mic', 16)}</span>`;
        labelEl.textContent = '錄音';
    }
}

// ==========================================
// 藍牙裝置搜尋與選擇功能
// ==========================================

/**
 * 搜尋附近的藍牙裝置（包含已配對與尚未配對的裝置）
 */
async function scanBluetoothDevices() {
    if (!currentSessionId) {
        showMessage('請先建立會議會話', 'error');
        return;
    }

    const scanBtn = document.getElementById('btScanBtn');
    const statusEl = document.getElementById('btScanStatus');

    try {
        if (scanBtn) scanBtn.disabled = true;
        if (statusEl) {
            statusEl.innerHTML = '<span class="loading-spinner"></span> 搜尋中（約需數秒）...';
            statusEl.className = 'status-text';
        }

        const response = await fetch(`/api/session/${currentSessionId}/bluetooth/scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();

        if (!data.success) {
            if (statusEl) {
                statusEl.innerHTML = iconSVG('error', 15) + ` 搜尋失敗: ${escapeHtml(data.error || '未知錯誤')}`;
                statusEl.className = 'status-text';
            }
            return;
        }

        btDevices = data.devices || [];
        renderBluetoothDevices();

        if (statusEl) {
            statusEl.innerHTML = iconSVG('success', 15) + ` 找到 ${btDevices.length} 個裝置`;
            statusEl.className = 'status-text success';
        }

    } catch (error) {
        if (statusEl) {
            statusEl.innerHTML = iconSVG('error', 15) + ` 搜尋錯誤: ${escapeHtml(error.message)}`;
            statusEl.className = 'status-text';
        }
    } finally {
        if (scanBtn) scanBtn.disabled = false;
    }
}

/**
 * 將搜尋到的藍牙裝置渲染為可點擊選擇的列表
 */
function renderBluetoothDevices() {
    const listEl = document.getElementById('btDeviceList');
    if (!listEl) return;

    if (!btDevices || btDevices.length === 0) {
        listEl.innerHTML = '<div class="bt-empty-hint">尚未搜尋到任何裝置，請點擊「搜尋裝置」</div>';
        return;
    }

    listEl.innerHTML = '';
    btDevices.forEach(d => {
        const isSelected = selectedBluetoothDevice && selectedBluetoothDevice.mac === d.mac;
        const badgeClass = d.connected ? 'connected' : (d.paired ? 'paired' : 'unpaired');
        const badgeLabel = d.connected ? '已連線' : (d.paired ? '已配對' : '未配對');

        const item = document.createElement('button');
        item.type = 'button';
        item.className = `bt-device-item${isSelected ? ' selected' : ''}`;
        item.dataset.mac = d.mac;
        item.onclick = () => selectBluetoothDevice(d.mac);

        item.innerHTML = `
            ${isSelected ? iconSVG('success', 15) : ''}
            <span class="bt-device-name">${escapeHtml(d.name || '(未命名裝置)')}</span>
            <span class="bt-device-mac">${escapeHtml(d.mac)}</span>
            <span class="bt-badge ${badgeClass}">${badgeLabel}</span>
        `;
        listEl.appendChild(item);
    });
}

/**
 * 選擇指定的藍牙裝置作為本次傳送目標（會嘗試配對/信任該裝置）
 */
async function selectBluetoothDevice(mac) {
    if (!currentSessionId) {
        return;
    }

    const device = btDevices.find(d => d.mac === mac);
    if (!device) {
        return;
    }

    const statusEl = document.getElementById('btScanStatus');
    if (statusEl) {
        statusEl.innerHTML = `<span class="loading-spinner"></span> 正在配對 ${escapeHtml(device.name || mac)}...`;
        statusEl.className = 'status-text';
    }

    try {
        const response = await fetch(`/api/session/${currentSessionId}/bluetooth/select`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mac: device.mac, name: device.name })
        });
        const data = await response.json();

        if (!data.success) {
            if (statusEl) {
                statusEl.innerHTML = iconSVG('error', 15) + ` 配對失敗: ${escapeHtml(data.error || '未知錯誤')}`;
                statusEl.className = 'status-text';
            }
            return;
        }

        selectedBluetoothDevice = { mac: data.mac, name: data.name };
        renderBluetoothDevices();

        if (statusEl) {
            statusEl.innerHTML = iconSVG('success', 15) + ` 已選擇裝置: ${escapeHtml(data.name || data.mac)}`;
            statusEl.className = 'status-text success';
        }
        showMessage(`已選擇藍牙裝置: ${data.name || data.mac}，執行 Bluetooth 步驟時將傳送至此裝置`, 'success');

    } catch (error) {
        if (statusEl) {
            statusEl.innerHTML = iconSVG('error', 15) + ` 配對錯誤: ${escapeHtml(error.message)}`;
            statusEl.className = 'status-text';
        }
    }
}

// ==========================================
// 輔助函數
// ==========================================

/**
 * 獲取會話狀態
 */
async function getSessionStatus() {
    try {
        const response = await fetch(`/api/session/${currentSessionId}/status`);
        const data = await response.json();
        
        if (!data.success) {
            return null;
        }
        
        return data;
    } catch (error) {
        console.error('獲取狀態錯誤:', error);
        return null;
    }
}

/**
 * 更新步驟狀態
 */
function updateStepStatus(stepName, status) {
    const statusEl = document.getElementById(`${stepName}Status`);
    const btnEl = document.getElementById(`${stepName}Btn`);
    
    if (!statusEl || !btnEl) {
        return;
    }
    
    statusEl.className = `step-status ${status}`;
    
    switch (status) {
        case 'completed':
            statusEl.innerHTML = iconSVG('success', 14) + ' 已完成';
            break;
        case 'running':
            statusEl.innerHTML = '<span class="loading-spinner"></span> 執行中';
            break;
        case 'error':
            statusEl.innerHTML = iconSVG('error', 14) + ' 錯誤';
            break;
        default:
            statusEl.textContent = '';
    }
}

/**
 * 更新下一個可用按鈕
 */
function updateNextEnabledButtons(completedSteps) {
    const stepOrder = ['asr', 'pkd', 'actions', 'summary', 'export', 'bluetooth'];
    
    stepOrder.forEach((step, index) => {
        const btn = document.getElementById(`${step}Btn`);
        
        if (!btn) return;
        
        // 如果前一步已完成或沒有前一步，則啟用此按鈕
        if (index === 0) {
            // ASR 只有在上傳了檔案後才啟用
            const uploadStatus = document.getElementById('uploadStatus');
            if (uploadStatus && uploadStatus.classList.contains('success')) {
                btn.disabled = false;
            }
        } else {
            const prevStep = stepOrder[index - 1];
            if (completedSteps.includes(prevStep)) {
                btn.disabled = false;
            }
        }
    });
}

/**
 * 禁用所有步驟按鈕
 */
function disableStepButtons() {
    const stepNames = ['asr', 'pkd', 'actions', 'summary', 'export', 'bluetooth'];
    stepNames.forEach(step => {
        const btn = document.getElementById(`${step}Btn`);
        if (btn) {
            btn.disabled = true;
        }
    });
}

/**
 * 啟用步驟按鈕
 */
function enableStepButtons() {
    // 基於完成的步驟，更新可用按鈕
    if (currentSessionId) {
        getSessionStatus().then(status => {
            if (status) {
                updateNextEnabledButtons(status.steps_completed);
            }
        });
    }
}

/**
 * 顯示訊息 - 創建可展開的訊息項
 */
function showMessage(message, type = 'info', stepName = null) {
    const messagesLog = document.getElementById('messagesLog');
    
    // 清除初始提示
    const placeholder = messagesLog.querySelector('.message-item.info .message-item-text');
    if (placeholder && placeholder.textContent === '等待操作...') {
        messagesLog.innerHTML = '';
    }
    
    // 創建訊息項
    const msgItem = document.createElement('div');
    msgItem.className = `message-item ${type}`;
    
    // 存儲步驟名稱，以便展開時使用
    if (stepName) {
        msgItem.dataset.stepName = stepName;
    }
    
    const iconName = {
        'success': 'success',
        'error': 'error',
        'warning': 'warning',
        'info': 'info'
    }[type] || 'info';
    
    msgItem.innerHTML = `
        <div class="message-item-header" onclick="expandMessage(this.parentElement)">
            <span class="message-item-icon">${iconSVG(iconName, 16)}</span>
            <span class="message-item-text">${escapeHtml(message)}</span>
            <span class="message-item-expand">${iconSVG('chevron-right', 14)}</span>
        </div>
        <div class="message-item-details">
            <div class="logs-container message-item-logs" style="max-height: 200px; margin: 0;">
                <div class="log-line info">點擊查看相關日誌...</div>
            </div>
        </div>
    `;
    
    messagesLog.appendChild(msgItem);
    
    // 自動滾到底部
    messagesLog.scrollTop = messagesLog.scrollHeight;
}

/**
 * 展開/折疊訊息項
 */
function expandMessage(messageItem) {
    messageItem.classList.toggle('expanded');
    
    // 如果展開，則加載相關日誌
    if (messageItem.classList.contains('expanded')) {
        const stepName = messageItem.dataset.stepName;
        if (stepName) {
            // 從步驟特定的 API 加載日誌
            loadStepLogs(stepName, messageItem);
        } else {
            // 加載總體系統日誌
            loadSystemLogs(messageItem);
        }
    }
}

/**
 * 加載特定步驟的日誌
 */
async function loadStepLogs(stepName, messageItem) {
    if (!currentSessionId) {
        return;
    }
    
    try {
        const response = await fetch(`/api/session/${currentSessionId}/step/${stepName}/logs`);
        const data = await response.json();
        
        if (!data.success) {
            return;
        }
        
        const logContainer = messageItem.querySelector('.message-item-logs');
        renderLogLines(logContainer, data.logs);
        
        // 自動滾到底部
        logContainer.scrollTop = logContainer.scrollHeight;
        
    } catch (error) {
        console.error('加載步驟日誌錯誤:', error);
    }
}

/**
 * 根據日誌內容判斷顯示樣式類別（與後端 print_log_utils.classify_log_line 保持一致）
 */
function getLogLineClass(log) {
    if (log.includes('[ERROR]') || log.includes('❌') || log.includes('異常')) {
        return 'error';
    } else if (log.includes('[WARN]') || log.includes('⚠')) {
        return 'warning';
    } else if (log.includes('✓') || log.includes('[SUCCESS]')) {
        return 'success';
    } else if (log.includes('[STEP]') || log.includes('已開始') || log.includes('完成')) {
        return 'step';
    } else if (log.includes('[DEBUG]')) {
        return 'debug';
    }
    return 'info';
}

/**
 * 將一組日誌字串渲染到指定容器中（共享於系統日誌、步驟日誌與歷史 session 日誌）
 */
function renderLogLines(container, logs) {
    container.innerHTML = '';
    if (!logs || logs.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'log-line info';
        empty.textContent = '（無日誌內容）';
        container.appendChild(empty);
        return;
    }
    logs.forEach(log => {
        const logLine = document.createElement('div');
        logLine.className = `log-line ${getLogLineClass(log)}`;
        logLine.textContent = log;
        container.appendChild(logLine);
    });
}

/**
 * HTML 轉義
 */
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

/**
 * 更新系統日誌
 */
async function updateSystemLogs() {
    if (!currentSessionId) {
        return;
    }
    
    try {
        const response = await fetch(`/api/session/${currentSessionId}/logs`);
        const data = await response.json();
        
        if (!data.success) {
            return;
        }
        
        const logsContainer = document.getElementById('systemLogs');
        renderLogLines(logsContainer, data.logs);
        
        // 自動滾到底部
        logsContainer.scrollTop = logsContainer.scrollHeight;
        
        // 更新訊息項中的日誌
        const expandedItems = document.querySelectorAll('.message-item.expanded');
        expandedItems.forEach(item => {
            const itemLogs = item.querySelector('.message-item-logs');
            if (itemLogs) {
                itemLogs.innerHTML = logsContainer.innerHTML;
            }
        });
        
    } catch (error) {
        console.error('更新日誌錯誤:', error);
    }
}

/**
 * 清空系統日誌
 */
function clearSystemLogs() {
    const logsContainer = document.getElementById('systemLogs');
    logsContainer.innerHTML = '<div class="log-line info">日誌已清空...</div>';
}

/**
 * 在訊息項中加載系統日誌
 */
async function loadSystemLogs(messageItem) {
    if (!currentSessionId) {
        return;
    }
    
    try {
        const response = await fetch(`/api/session/${currentSessionId}/logs`);
        const data = await response.json();
        
        if (!data.success) {
            return;
        }
        
        const logContainer = messageItem.querySelector('.message-item-logs');
        renderLogLines(logContainer, data.logs);
        
        // 自動滾到底部
        logContainer.scrollTop = logContainer.scrollHeight;
        
    } catch (error) {
        console.error('加載系統日誌錯誤:', error);
    }
}

/**
 * 更新下載列表
 */
function updateDownloadList(files) {
    const downloadPanel = document.getElementById('downloadPanel');
    const downloadList = document.getElementById('downloadList');
    
    if (!files || Object.keys(files).length === 0) {
        downloadPanel.style.display = 'none';
        return;
    }
    
    downloadPanel.style.display = 'block';
    downloadList.innerHTML = '';
    
    Object.entries(files).forEach(([filename, filepath]) => {
        const item = document.createElement('div');
        item.className = 'download-item';
        
        const displayName = {
            'meeting_summary': '會議摘要 (TXT)',
            'actions': '行動項目 (TXT)',
            'summary': '摘要 (TXT)',
            'people': '參與者 (TXT)',
            'decisions': '決策 (TXT)'
        }[filename] || filename;
        
        item.innerHTML = `
            <div class="file-info">
                <div class="file-name">${iconSVG('document', 15)} ${displayName}</div>
                <div class="file-path">${filepath}</div>
            </div>
            <button class="btn btn-success" onclick="downloadFile('${filename}')">下載</button>
        `;
        
        downloadList.appendChild(item);
    });
}

/**
 * 下載檔案
 */
function downloadFile(filename) {
    if (!currentSessionId) {
        return;
    }
    
    const url = `/api/session/${currentSessionId}/download/${filename}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

/**
 * 開始狀態檢查
 */
function startStatusCheck() {
    if (statusCheckInterval) {
        clearInterval(statusCheckInterval);
    }
    
    statusCheckInterval = setInterval(refreshStatus, 5000); // 每 5 秒檢查一次
}

/**
 * 延遲 (毫秒)
 */
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// ==========================================
// 歷史 Session 查看功能
// ==========================================

/**
 * 顯示歷史 Session 列表面板
 */
function showHistoryView() {
    document.getElementById('historyDetailPanel').style.display = 'none';
    document.getElementById('historyPanel').style.display = 'block';
    loadSessionHistory();
}

/**
 * 關閉歷史 Session 面板，回到主要介面
 */
function closeHistoryView() {
    document.getElementById('historyPanel').style.display = 'none';
    document.getElementById('historyDetailPanel').style.display = 'none';
}

/**
 * 從伺服器載入所有歷史 session 列表
 */
async function loadSessionHistory() {
    const listEl = document.getElementById('historyList');
    const countEl = document.getElementById('historyCount');
    listEl.innerHTML = '<div class="history-empty">載入中...</div>';

    try {
        const response = await fetch('/api/sessions/history');
        const data = await response.json();

        if (!data.success) {
            listEl.innerHTML = `<div class="history-empty">載入失敗: ${escapeHtml(data.error || '未知錯誤')}</div>`;
            return;
        }

        countEl.textContent = `共 ${data.total} 個 session`;

        if (data.total === 0) {
            listEl.innerHTML = '<div class="history-empty">尚未發現任何歷史 session</div>';
            return;
        }

        listEl.innerHTML = '';
        data.sessions.forEach(s => {
            const card = document.createElement('div');
            card.className = 'history-card';
            card.onclick = () => viewHistorySession(s.session_id);

            const badge = (label, ok) => `<span class="step-badge ${ok ? 'done' : 'pending'}">${label}</span>`;

            card.innerHTML = `
                <div class="history-card-header">
                    <code class="history-card-id">${escapeHtml(s.session_id)}</code>
                    ${s.is_active ? '<span class="live-badge">進行中</span>' : ''}
                </div>
                <div class="history-card-time">
                    <span>建立: ${escapeHtml(s.created_at)}</span>
                    <span>最新: ${escapeHtml(s.updated_at)}</span>
                </div>
                <div class="history-card-badges">
                    ${badge('ASR', s.steps.asr)}
                    ${badge('簡報', s.steps.pkd)}
                    ${badge('行動項', s.steps.actions)}
                    ${badge('摘要', s.steps.summary)}
                    ${badge('匯出', s.steps.export)}
                </div>
                <div class="history-card-footer">
                    <span>${s.has_log ? iconSVG('file-check', 14) + ' 有執行日誌' : iconSVG('file-x', 14) + ' 無執行日誌'}</span>
                    <span>${s.file_count} 個檔案</span>
                </div>
            `;
            listEl.appendChild(card);
        });
    } catch (error) {
        console.error('載入歷史 session 錯誤:', error);
        listEl.innerHTML = '<div class="history-empty">載入失敗，請重試</div>';
    }
}

/**
 * 進入指定 session 的詳細頁面（顯示日誌與可下載檔案）
 */
function viewHistorySession(sessionId) {
    currentHistorySessionId = sessionId;
    document.getElementById('historyPanel').style.display = 'none';
    document.getElementById('historyDetailPanel').style.display = 'block';
    document.getElementById('historyDetailSessionId').textContent = sessionId;
    document.getElementById('historyDetailMeta').textContent = '';

    loadHistoryFiles(sessionId);
    loadHistoryLog(sessionId);
}

/**
 * 從詳細頁面返回歷史列表
 */
function backToHistoryList() {
    currentHistorySessionId = null;
    document.getElementById('historyDetailPanel').style.display = 'none';
    document.getElementById('historyPanel').style.display = 'block';
}

/**
 * 載入指定 session 的可下載檔案列表
 */
async function loadHistoryFiles(sessionId) {
    const filesEl = document.getElementById('historyFilesList');
    filesEl.innerHTML = '<div class="history-empty">載入中...</div>';

    try {
        const response = await fetch(`/api/sessions/${sessionId}/files`);
        const data = await response.json();

        if (!data.success) {
            filesEl.innerHTML = `<div class="history-empty">載入失敗: ${escapeHtml(data.error || '未知錯誤')}</div>`;
            return;
        }

        if (!data.files || data.files.length === 0) {
            filesEl.innerHTML = '<div class="history-empty">此 session 尚無可下載檔案</div>';
            return;
        }

        filesEl.innerHTML = '';
        data.files.forEach(f => {
            const item = document.createElement('a');
            item.className = 'download-item';
            item.href = `/api/sessions/${sessionId}/download-file/${encodeURIComponent(f.name)}`;
            item.setAttribute('download', f.name);
            const sizeKb = (f.size_bytes / 1024).toFixed(1);
            item.innerHTML = `
                <span class="download-item-name">${iconSVG('document', 15)} ${escapeHtml(f.name)}</span>
                <span class="download-item-meta">${sizeKb} KB · ${escapeHtml(f.mtime)}</span>
            `;
            filesEl.appendChild(item);
        });
    } catch (error) {
        console.error('載入檔案列表錯誤:', error);
        filesEl.innerHTML = '<div class="history-empty">載入失敗，請重試</div>';
    }
}

/**
 * 載入指定 session 的 output_run.log 內容（正確顯示，支援尾部截斷或完整顯示）
 */
async function loadHistoryLog(sessionId) {
    const logEl = document.getElementById('historyLogContainer');
    const metaEl = document.getElementById('historyLogMeta');
    logEl.innerHTML = '<div class="log-line info">載入中...</div>';
    metaEl.textContent = '';

    const showFull = document.getElementById('historyLogFull').checked;
    const url = showFull
        ? `/api/sessions/${sessionId}/output_log?full=1`
        : `/api/sessions/${sessionId}/output_log?tail=500`;

    try {
        const response = await fetch(url);
        const data = await response.json();

        if (!data.success) {
            logEl.innerHTML = `<div class="log-line error">載入失敗: ${escapeHtml(data.error || '未知錯誤')}</div>`;
            return;
        }

        if (!data.log_file) {
            logEl.innerHTML = `<div class="log-line info">${escapeHtml(data.message || '尚未產生執行日誌')}</div>`;
            return;
        }

        renderLogLines(logEl, data.logs);

        const sizeKb = (data.size_bytes / 1024).toFixed(1);
        const truncatedNote = data.truncated
            ? `（僅顯示最後 ${data.returned_lines} / ${data.total_lines} 行，勾選「顯示全部」可看完整內容）`
            : `（共 ${data.total_lines} 行，已全部顯示）`;
        metaEl.textContent = `日誌檔: ${data.log_file} · ${sizeKb} KB · 最後修改: ${data.mtime} ${truncatedNote}`;
    } catch (error) {
        console.error('載入執行日誌錯誤:', error);
        logEl.innerHTML = '<div class="log-line error">載入失敗，請重試</div>';
    }
}

/**
 * 恢復歷史 session：讓使用者可以接續尚未完成的步驟繼續執行，
 * 而不僅僅是唯讀查看歷史內容。
 *
 * 流程：
 *   1. 呼叫後端 /api/sessions/<id>/resume，後端會依照 session 目錄中
 *      既有的檔案判斷哪些步驟已完成，並重新建立對應的 workflow。
 *   2. 切換畫面：關閉歷史面板，顯示與「新建會議」相同的進度面板，
 *      並依據已完成步驟正確標記各步驟狀態、啟用下一個可執行的按鈕。
 *   3. 之後即可直接沿用既有的「執行 ASR/PKD/Actions/Summary/Export/藍牙」按鈕，
 *      完全重用原有流程，已完成的步驟不會被要求重新執行。
 */
async function resumeHistorySession(sessionId) {
    if (!sessionId) {
        showMessage('找不到要恢復的 session', 'error');
        return;
    }

    const resumeBtn = document.getElementById('resumeSessionBtn');

    try {
        if (resumeBtn) {
            resumeBtn.disabled = true;
            resumeBtn.innerHTML = '<span class="loading-spinner"></span> 恢復中...';
        }
        showMessage(`正在恢復 session ${sessionId}...`, 'info');

        const modelPath = document.getElementById('modelPath').value.trim();
        const intervalMinutes = parseInt(document.getElementById('intervalMinutes').value);
        const overlapSeconds = parseInt(document.getElementById('overlapSeconds').value);
        const enableBluetooth = document.getElementById('enableBluetooth').checked;

        const response = await fetch(`/api/sessions/${sessionId}/resume`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                model_path: modelPath,
                interval_minutes: intervalMinutes,
                overlap_seconds: overlapSeconds,
                enable_bluetooth: enableBluetooth
            })
        });

        const data = await response.json();

        if (!data.success) {
            showMessage(`恢復 session 失敗: ${data.error}`, 'error');
            return;
        }

        // 切換畫面：關閉歷史面板與設置面板，顯示進度面板
        document.getElementById('historyPanel').style.display = 'none';
        document.getElementById('historyDetailPanel').style.display = 'none';
        document.querySelector('.setup-panel').style.display = 'none';
        document.getElementById('progressPanel').style.display = 'block';

        currentSessionId = sessionId;
        document.getElementById('sessionId').textContent = currentSessionId;

        // 重置上傳狀態顯示，並依偵測結果還原
        document.getElementById('audioFile').value = '';
        const uploadStatusEl = document.getElementById('uploadStatus');
        if (data.audio_exists) {
            uploadStatusEl.innerHTML = iconSVG('success', 15) + ' 偵測到既有音訊檔案（可直接繼續，或重新上傳以取代）';
            uploadStatusEl.className = 'status-text success';
        } else {
            uploadStatusEl.innerHTML = iconSVG('warning', 15) + ' 尚未偵測到音訊檔案，請上傳後再執行 ASR';
            uploadStatusEl.className = 'status-text';
        }

        // 重置所有步驟狀態顯示，再依已完成步驟標記
        const stepNames = ['asr', 'pkd', 'actions', 'summary', 'export', 'bluetooth'];
        stepNames.forEach(step => {
            const statusEl = document.getElementById(`${step}Status`);
            if (statusEl) {
                statusEl.className = 'step-status';
                statusEl.textContent = '';
            }
        });
        data.steps_completed.forEach(step => updateStepStatus(step, 'completed'));

        // 先全部禁用，再依已完成步驟開放下一個可執行按鈕
        disableStepButtons();
        updateNextEnabledButtons(data.steps_completed);

        // 還原已產出的下載檔案列表
        updateDownloadList(data.files);

        const doneLabel = data.steps_completed.length > 0
            ? data.steps_completed.join(', ')
            : '無（尚未開始）';
        showMessage(`已恢復 session ${sessionId}（已完成步驟: ${doneLabel}），可繼續執行後續步驟`, 'success');

        // 開始定期檢查狀態（沿用既有的狀態輪詢機制）
        startStatusCheck();

    } catch (error) {
        showMessage(`恢復 session 錯誤: ${error.message}`, 'error');
    } finally {
        if (resumeBtn) {
            resumeBtn.disabled = false;
            resumeBtn.innerHTML = iconSVG('play', 16) + ' 繼續執行未完成步驟';
        }
    }
}

/**
 * 重新載入當前歷史 session 的日誌
 */
function reloadHistoryLog() {
    if (currentHistorySessionId) {
        loadHistoryLog(currentHistorySessionId);
    }
}

// ==========================================
// 初始化
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    console.log('會議助理網頁應用已載入');

    // 渲染預先宣告的 [data-icon] 圖示
    if (typeof renderIcons === 'function') {
        renderIcons();
    }

    // 初始化主題（讀取先前手動選擇的深淺色設定）
    initTheme();
    
    // 禁用所有步驟按鈕（直到建立會話）
    const stepNames = ['asr', 'pkd', 'actions', 'summary', 'export', 'bluetooth'];
    stepNames.forEach(step => {
        const btn = document.getElementById(`${step}Btn`);
        if (btn) {
            btn.disabled = true;
        }
    });
});

// 頁面卸載時清理
window.addEventListener('beforeunload', function() {
    if (statusCheckInterval) {
        clearInterval(statusCheckInterval);
    }
});
