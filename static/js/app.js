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
        
        showMessage(`✓ 會議會話已建立: ${currentSessionId}`, 'success');
        showMessage('請上傳音頻檔案開始處理...', 'info');
        
        // 啟用 ASR 按鈕（需要上傳檔案）
        document.getElementById('asrBtn').disabled = false;
        
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
        
        showMessage(`▶ ${stepName.toUpperCase()} 已開始執行...`, 'info');
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
        document.getElementById('messagesLog').innerHTML = '<p class="info-text">會話已建立，請上傳音頻檔案開始</p>';
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
            // ASR 總是啟用的（只要上傳了檔案）
            btn.disabled = false;
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
 * 顯示訊息
 */
function showMessage(message, type = 'info') {
    const messagesLog = document.getElementById('messagesLog');
    
    // 如果訊息為空，清除初始提示
    if (messagesLog.querySelector('.info-text:only-child')) {
        messagesLog.innerHTML = '';
    }
    
    const msgEl = document.createElement('p');
    msgEl.className = `${type}-text`;
    msgEl.textContent = message;
    
    messagesLog.appendChild(msgEl);
    
    // 自動滾到底部
    messagesLog.scrollTop = messagesLog.scrollHeight;
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
