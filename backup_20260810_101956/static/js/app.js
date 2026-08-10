/* ==========================================
   會議助理網頁應用 - 前端邏輯
   ========================================== */

let currentSessionId = null;
let statusCheckInterval = null;

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
            showMessage('❌ 請輸入模型路徑', 'error');
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
            showMessage(`❌ 建立會話失敗: ${data.error}`, 'error');
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
        
        showMessage(`✓ 會議會話已建立: ${currentSessionId}`, 'success');
        showMessage('📁 請上傳音頻檔案開始處理...', 'info');
        
        // 確保 ASR 按鈕保持禁用（直到上傳檔案）
        document.getElementById('asrBtn').disabled = true;
        
        // 開始定期檢查狀態
        startStatusCheck();
        
    } catch (error) {
        showMessage(`❌ 錯誤: ${error.message}`, 'error');
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
        showMessage('❌ 請先建立會議會話', 'error');
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
            showMessage(`❌ 上傳失敗: ${data.error}`, 'error');
            return;
        }
        
        document.getElementById('uploadStatus').textContent = `✓ ${file.name} 已上傳`;
        document.getElementById('uploadStatus').className = 'status-text success';
        showMessage(`✓ 音頻檔案已上傳: ${file.name}`, 'success');
        
        // 上傳成功後啟用 ASR 按鈕
        document.getElementById('asrBtn').disabled = false;
        showMessage('📢 已準備好執行 ASR，請點擊「執行 ASR」按鈕', 'info');
        
    } catch (error) {
        showMessage(`❌ 上傳錯誤: ${error.message}`, 'error');
    }
}

/**
 * 執行特定步驟
 */
async function runStep(stepName) {
    if (!currentSessionId) {
        showMessage('❌ 會話不存在', 'error');
        return;
    }
    
    // ASR 必須有上傳的音頻檔案
    if (stepName === 'asr') {
        const uploadStatus = document.getElementById('uploadStatus');
        if (!uploadStatus.textContent.includes('✓')) {
            showMessage('❌ 請先上傳音頻檔案後再執行 ASR', 'error');
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
            showMessage(`❌ ${stepName.toUpperCase()} 啟動失敗: ${data.error}`, 'error');
            enableStepButtons();
            return;
        }
        
        showMessage(`▶ ${stepName.toUpperCase()} 已開始執行...`, 'info', stepName);
        updateStepStatus(stepName, 'running');
        
        // 開始監控狀態
        monitorStep(stepName);
        
    } catch (error) {
        showMessage(`❌ 錯誤: ${error.message}`, 'error');
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
                showMessage(`❌ ${stepError}`, 'error');
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
        document.getElementById('messagesLog').innerHTML = '<div class="message-item info"><div class="message-item-header"><span class="message-item-icon">ℹ️</span><span class="message-item-text">等待操作...</span><span class="message-item-expand">▶</span></div></div>';
        document.getElementById('systemLogs').innerHTML = '<div class="log-line info">等待日誌信息...</div>';
        document.getElementById('downloadPanel').style.display = 'none';
        document.getElementById('downloadList').innerHTML = '';
        
        // 清除狀態檢查
        if (statusCheckInterval) {
            clearInterval(statusCheckInterval);
        }
        
        showMessage('✓ 會議已結束', 'success');
        
    } catch (error) {
        showMessage(`❌ 錯誤: ${error.message}`, 'error');
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
            statusEl.textContent = '✓ 已完成';
            break;
        case 'running':
            statusEl.innerHTML = '<span class="loading-spinner"></span> 執行中';
            break;
        case 'error':
            statusEl.textContent = '✗ 錯誤';
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
            if (uploadStatus && uploadStatus.textContent.includes('✓')) {
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
    
    const icon = {
        'success': '✓',
        'error': '✗',
        'warning': '⚠',
        'info': 'ℹ️'
    }[type] || 'ℹ️';
    
    msgItem.innerHTML = `
        <div class="message-item-header" onclick="expandMessage(this.parentElement)">
            <span class="message-item-icon">${icon}</span>
            <span class="message-item-text">${escapeHtml(message)}</span>
            <span class="message-item-expand">▶</span>
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
        logContainer.innerHTML = '';
        
        data.logs.forEach(log => {
            const logLine = document.createElement('div');
            logLine.className = 'log-line';
            
            // 根據日誌內容判斷類型
            if (log.includes('[ERROR]') || log.includes('❌') || log.includes('異常')) {
                logLine.classList.add('error');
            } else if (log.includes('[WARN]') || log.includes('⚠')) {
                logLine.classList.add('warning');
            } else if (log.includes('✓') || log.includes('[SUCCESS]')) {
                logLine.classList.add('success');
            } else if (log.includes('[STEP]') || log.includes('已開始') || log.includes('完成')) {
                logLine.classList.add('step');
            } else if (log.includes('[DEBUG]')) {
                logLine.classList.add('debug');
            } else {
                logLine.classList.add('info');
            }
            
            logLine.textContent = log;
            logContainer.appendChild(logLine);
        });
        
        // 自動滾到底部
        logContainer.scrollTop = logContainer.scrollHeight;
        
    } catch (error) {
        console.error('加載步驟日誌錯誤:', error);
    }
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
        logsContainer.innerHTML = '';
        
        data.logs.forEach(log => {
            const logLine = document.createElement('div');
            logLine.className = 'log-line';
            
            // 根據日誌內容判斷類型
            if (log.includes('[ERROR]') || log.includes('❌') || log.includes('異常')) {
                logLine.classList.add('error');
            } else if (log.includes('[WARN]') || log.includes('⚠')) {
                logLine.classList.add('warning');
            } else if (log.includes('✓') || log.includes('[SUCCESS]')) {
                logLine.classList.add('success');
            } else if (log.includes('[STEP]') || log.includes('已開始') || log.includes('完成')) {
                logLine.classList.add('step');
            } else if (log.includes('[DEBUG]')) {
                logLine.classList.add('debug');
            } else {
                logLine.classList.add('info');
            }
            
            logLine.textContent = log;
            logsContainer.appendChild(logLine);
        });
        
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
        logContainer.innerHTML = '';
        
        data.logs.forEach(log => {
            const logLine = document.createElement('div');
            logLine.className = 'log-line';
            
            // 根據日誌內容判斷類型
            if (log.includes('[ERROR]') || log.includes('❌') || log.includes('異常')) {
                logLine.classList.add('error');
            } else if (log.includes('[WARN]') || log.includes('⚠')) {
                logLine.classList.add('warning');
            } else if (log.includes('✓') || log.includes('[SUCCESS]')) {
                logLine.classList.add('success');
            } else if (log.includes('[STEP]') || log.includes('已開始') || log.includes('完成')) {
                logLine.classList.add('step');
            } else if (log.includes('[DEBUG]')) {
                logLine.classList.add('debug');
            } else {
                logLine.classList.add('info');
            }
            
            logLine.textContent = log;
            logContainer.appendChild(logLine);
        });
        
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
                <div class="file-name">📄 ${displayName}</div>
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
// 初始化
// ==========================================

document.addEventListener('DOMContentLoaded', function() {
    console.log('會議助理網頁應用已載入');
    
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
