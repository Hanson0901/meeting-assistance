// Configuration
const CONFIG = {
  API_BASE_URL: 'http://192.168.31.208:5000', //ip of the raspberry pi
  MAX_FILE_SIZE: 500 * 1024 * 1024, // 500MB
  POLLING_INTERVAL: 1000, // 1 second
  ALLOWED_FORMATS: ['wav', 'mp3', 'flac', 'm4a', 'ogg']
};

// Application State (using in-memory storage instead of localStorage)
const AppState = {
  sessionId: null,
  uploadedFile: null,
  transcriptText: '',
  summaryData: null,
  segmentsData: null,

  reset() {
    this.sessionId = null;
    this.uploadedFile = null;
    this.transcriptText = '';
    this.summaryData = null;
    this.segmentsData = null;
  }
};

// DOM Elements
const elements = {
  uploadZone: document.getElementById('upload-zone'),
  fileInput: document.getElementById('file-input'),
  fileInfo: document.getElementById('file-info'),
  fileName: document.getElementById('file-name'),
  fileSize: document.getElementById('file-size'),
  uploadProgress: document.getElementById('upload-progress'),
  uploadProgressFill: document.getElementById('upload-progress-fill'),
  transcribeBtn: document.getElementById('transcribe-btn'),
  transcribeBtnText: document.getElementById('transcribe-btn-text'),
  transcribeSpinner: document.getElementById('transcribe-spinner'),
  transcribeProgress: document.getElementById('transcribe-progress'),
  transcribeProgressFill: document.getElementById('transcribe-progress-fill'),
  transcribeStatus: document.getElementById('transcribe-status'),
  transcriptText: document.getElementById('transcript-text'),
  transcriptStats: document.getElementById('transcript-stats'),
  analyzeBtn: document.getElementById('analyze-btn'),
  analyzeBtnText: document.getElementById('analyze-btn-text'),
  analyzeSpinner: document.getElementById('analyze-spinner'),
  analyzeProgress: document.getElementById('analyze-progress'),
  analyzeProgressFill: document.getElementById('analyze-progress-fill'),
  analyzeStatus: document.getElementById('analyze-status'),
  summarySection: document.getElementById('summary-section'),
  summaryContent: document.getElementById('summary-content'),
  statsGrid: document.getElementById('stats-grid'),
  segmentsSection: document.getElementById('segments-section'),
  segmentsTbody: document.getElementById('segments-tbody'),
  downloadTranscriptBtn: document.getElementById('download-transcript-btn'),
  downloadSummaryBtn: document.getElementById('download-summary-btn'),
  downloadCsvBtn: document.getElementById('download-csv-btn'),
  downloadSrtBtn: document.getElementById('download-srt-btn'),
  resetBtn: document.getElementById('reset-btn'),
  asrStatus: document.getElementById('asr-status'),
  analysisStatus: document.getElementById('analysis-status'),
  statusMessage: document.getElementById('status-message'),
  step1Number: document.getElementById('step1-number'),
  step2Number: document.getElementById('step2-number'),
  step3Number: document.getElementById('step3-number'),
  step4Number: document.getElementById('step4-number')
};

// Utility Functions
function formatFileSize(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function getFileExtension(filename) {
  return filename.split('.').pop().toLowerCase();
}

function showMessage(message, type = 'info') {
  elements.statusMessage.textContent = message;
  elements.statusMessage.className = 'status-message ' + type;
}

function setStepActive(stepNumber) {
  const steps = [
    elements.step1Number,
    elements.step2Number,
    elements.step3Number,
    elements.step4Number
  ];
  steps.forEach((step, index) => {
    if (index + 1 === stepNumber) {
      step.classList.add('active');
    } else {
      step.classList.remove('active');
    }
  });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function parseMarkdown(text) {
  // Simple markdown to HTML conversion
  let html = escapeHtml(text);
  // Headers
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // Lists
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
  // Paragraphs
  html = html.replace(/\n\n/g, '</p><p>');
  html = '<p>' + html + '</p>';
  return html;
}

// API Functions
async function checkHealth() {
  try {
    const response = await fetch(`${CONFIG.API_BASE_URL}/api/health`);
    const data = await response.json();

    if (data.asr_available) {
      elements.asrStatus.classList.add('ready');
    } else {
      elements.asrStatus.classList.add('loading');
    }

    if (data.extractor_available) {
      elements.analysisStatus.classList.add('ready');
    } else {
      elements.analysisStatus.classList.add('loading');
    }

    showMessage('系統已就緒', 'success');
  } catch (error) {
    console.error('Health check failed:', error);
    elements.asrStatus.classList.add('error');
    elements.analysisStatus.classList.add('error');
    showMessage('無法連接到後端服務，請確認服務已啟動', 'error');
  }
}

async function uploadAndTranscribe(file) {
  const formData = new FormData();
  formData.append('file', file);

  try {
    elements.transcribeBtn.disabled = true;
    elements.transcribeBtnText.textContent = '上傳中...';
    elements.transcribeSpinner.classList.remove('hidden');
    elements.transcribeProgress.classList.remove('hidden');

    const response = await fetch(`${CONFIG.API_BASE_URL}/api/transcribe`, {
      method: 'POST',
      body: formData
    });

    if (!response.ok) {
      throw new Error('上傳失敗');
    }

    const data = await response.json();
    AppState.sessionId = data.session_id;

    // 直接顯示轉錄結果（不再輪詢）
    if (data.transcript) {
      AppState.transcriptText = data.transcript;
      elements.transcriptText.value = data.transcript;
      elements.transcriptText.classList.remove('hidden');
      elements.transcriptStats.textContent = `字數: ${data.transcript.length} 字 | 分段數: ${data.segments_count}`;
      elements.transcriptStats.classList.remove('hidden');

      elements.transcribeProgressFill.style.width = '100%';
      elements.transcribeStatus.textContent = '✓ 轉錄完成！';
      elements.transcribeStatus.classList.remove('hidden');

      showMessage('✓ 轉錄完成！可以下載文檔或生成會議重點', 'success');

      resetTranscribeButton();

      // 【改修】啟用分析按鈕和下載按鈕
      elements.analyzeBtn.disabled = false;
      elements.downloadTranscriptBtn.disabled = false;
      elements.downloadSrtBtn.disabled = false;

      setStepActive(3);
    }
  } catch (error) {
    console.error('Upload failed:', error);
    showMessage('上傳失敗: ' + error.message, 'error');
    elements.transcribeBtn.disabled = false;
    elements.transcribeBtnText.textContent = '開始轉錄';
    elements.transcribeSpinner.classList.add('hidden');
    elements.transcribeProgress.classList.add('hidden');
  }
}

function resetTranscribeButton() {
  elements.transcribeBtn.disabled = false;
  elements.transcribeBtnText.textContent = '開始轉錄';
  elements.transcribeSpinner.classList.add('hidden');
}

async function analyzeMeeting() {
  if (!AppState.transcriptText) {
    showMessage('請先完成語音轉文字', 'error');
    return;
  }

  try {
    elements.analyzeBtn.disabled = true;
    elements.analyzeBtnText.textContent = '分析中...';
    elements.analyzeSpinner.classList.remove('hidden');
    elements.analyzeProgress.classList.remove('hidden');

    const response = await fetch(`${CONFIG.API_BASE_URL}/api/process-meeting`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        session_id: AppState.sessionId,
        transcript: AppState.transcriptText
      })
    });

    if (!response.ok) {
      throw new Error('分析請求失敗');
    }

    const data = await response.json();

    // 開始輪詢分析狀態
    pollAnalysisStatus();

  } catch (error) {
    console.error('Analysis failed:', error);
    showMessage('分析失敗: ' + error.message, 'error');
    resetAnalyzeButton();
  }
}

let analysisPollInterval;

async function pollAnalysisStatus() {
  elements.analyzeBtnText.textContent = '生成中...';

  analysisPollInterval = setInterval(async () => {
    try {
      const response = await fetch(`${CONFIG.API_BASE_URL}/api/status/${AppState.sessionId}`);
      const data = await response.json();

      if (data.progress !== undefined) {
        const progress = Math.min(100, Math.max(0, data.progress));
        elements.analyzeProgressFill.style.width = progress + '%';
        elements.analyzeStatus.textContent = `生成中: ${progress}%`;
        elements.analyzeStatus.classList.remove('hidden');
      }

      // 檢查是否完成
      if (data.progress >= 100) {
        clearInterval(analysisPollInterval);
        await fetchAnalysisResult();
      }
    } catch (error) {
      console.error('Polling error:', error);
    }
  }, CONFIG.POLLING_INTERVAL);
}

async function fetchAnalysisResult() {
  try {
    const response = await fetch(`${CONFIG.API_BASE_URL}/api/result/${AppState.sessionId}`);
    const data = await response.json();

    if (data.summary) {
      AppState.summaryData = data.summary;
      AppState.segmentsData = data.segments || [];

      // Display summary
      elements.summaryContent.innerHTML = parseMarkdown(data.summary);
      elements.summarySection.classList.remove('hidden');

      // Display segments
      if (data.segments && data.segments.length > 0) {
        displaySegments(data.segments);
      }

      elements.analyzeProgressFill.style.width = '100%';
      elements.analyzeStatus.textContent = '✓ 分析完成！';
      showMessage('會議分析完成，可以下載檔案', 'success');

      resetAnalyzeButton();

      elements.downloadSummaryBtn.disabled = false;
      elements.downloadCsvBtn.disabled = false;

      setStepActive(4);
    }
  } catch (error) {
    console.error('Failed to fetch analysis result:', error);
    showMessage('獲取分析結果失敗', 'error');
    resetAnalyzeButton();
  }
}

function resetAnalyzeButton() {
  elements.analyzeBtn.disabled = false;
  elements.analyzeBtnText.textContent = '生成會議重點';
  elements.analyzeSpinner.classList.add('hidden');
}

function displaySegments(segments) {
  elements.segmentsTbody.innerHTML = '';
  segments.forEach((segment) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${escapeHtml(segment.time || '-')}</td>
      <td>${escapeHtml(segment.speaker || '-')}</td>
      <td>${escapeHtml(segment.keypoint || '-')}</td>
      <td>${escapeHtml(segment.emotion || '-')}</td>
    `;
    elements.segmentsTbody.appendChild(row);
  });
  elements.segmentsSection.classList.remove('hidden');
}

// Download Functions
async function downloadFile(fileType) {
  if (!AppState.sessionId) {
    showMessage('無效的會話', 'error');
    return;
  }

  try {
    const url = `${CONFIG.API_BASE_URL}/api/download/${AppState.sessionId}/${fileType}`;
    const response = await fetch(url);

    if (!response.ok) {
      throw new Error('下載失敗');
    }

    // 從 Content-Disposition 取得檔案名
    const contentDisposition = response.headers.get('content-disposition');
    let filename = `download_${fileType}`;
    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
      if (filenameMatch) {
        filename = filenameMatch[1];
      }
    }

    const blob = await response.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);

    showMessage(`已下載: ${filename}`, 'success');
  } catch (error) {
    console.error('Download failed:', error);
    showMessage('下載失敗: ' + error.message, 'error');
  }
}

function resetApplication() {
  if (confirm('確定要清空並重新開始嗎？')) {
    // 清除輪詢定時器
    if (analysisPollInterval) {
      clearInterval(analysisPollInterval);
    }

    // 重置狀態
    AppState.reset();

    // 重置 UI
    elements.fileInfo.classList.add('hidden');
    elements.uploadProgress.classList.add('hidden');
    elements.uploadProgressFill.style.width = '0%';

    elements.transcriptText.classList.add('hidden');
    elements.transcriptText.value = '';
    elements.transcriptStats.classList.add('hidden');

    elements.transcribeProgress.classList.add('hidden');
    elements.transcribeProgressFill.style.width = '0%';
    elements.transcribeStatus.classList.add('hidden');
    elements.transcribeBtn.disabled = true;

    elements.summarySection.classList.add('hidden');
    elements.analyzeProgress.classList.add('hidden');
    elements.analyzeProgressFill.style.width = '0%';
    elements.analyzeStatus.classList.add('hidden');
    elements.analyzeBtn.disabled = true;

    elements.downloadTranscriptBtn.disabled = true;
    elements.downloadSummaryBtn.disabled = true;
    elements.downloadCsvBtn.disabled = true;
    elements.downloadSrtBtn.disabled = true;

    setStepActive(1);

    showMessage('已重置，請上傳新的音檔', 'info');
  }
}

// File Upload Handlers
function handleFileSelect(file) {
  if (!file) return;

  // Validate file size
  if (file.size > CONFIG.MAX_FILE_SIZE) {
    showMessage(`檔案過大，最大 ${formatFileSize(CONFIG.MAX_FILE_SIZE)}`, 'error');
    return;
  }

  // Validate file format
  const ext = getFileExtension(file.name);
  if (!CONFIG.ALLOWED_FORMATS.includes(ext)) {
    showMessage(`不支援的格式，允許: ${CONFIG.ALLOWED_FORMATS.join(', ').toUpperCase()}`, 'error');
    return;
  }

  AppState.uploadedFile = file;

  // Display file info
  elements.fileName.textContent = file.name;
  elements.fileSize.textContent = formatFileSize(file.size);
  elements.fileInfo.classList.remove('hidden');

  // Enable transcribe button
  elements.transcribeBtn.disabled = false;

  setStepActive(2);

  showMessage(`已選擇: ${file.name}`, 'success');
}

// Event Listeners
elements.uploadZone.addEventListener('click', () => {
  elements.fileInput.click();
});

elements.fileInput.addEventListener('change', (e) => {
  const file = e.target.files[0];
  handleFileSelect(file);
});

// Drag and drop
elements.uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  elements.uploadZone.classList.add('drag-over');
});

elements.uploadZone.addEventListener('dragleave', () => {
  elements.uploadZone.classList.remove('drag-over');
});

elements.uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  elements.uploadZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  handleFileSelect(file);
});

// Button Handlers
elements.transcribeBtn.addEventListener('click', () => {
  if (AppState.uploadedFile) {
    uploadAndTranscribe(AppState.uploadedFile);
  }
});

elements.analyzeBtn.addEventListener('click', analyzeMeeting);

elements.downloadTranscriptBtn.addEventListener('click', () => downloadFile('srt'));
elements.downloadSummaryBtn.addEventListener('click', () => downloadFile('summary'));
elements.downloadCsvBtn.addEventListener('click', () => downloadFile('segments'));
elements.downloadSrtBtn.addEventListener('click', () => downloadFile('srt'));

elements.resetBtn.addEventListener('click', resetApplication);

// Allow editing transcript
elements.transcriptText.addEventListener('input', () => {
  AppState.transcriptText = elements.transcriptText.value;
  elements.transcriptStats.textContent = `字數: ${AppState.transcriptText.length} 字`;
});

// Initialize
checkHealth();
setStepActive(1);