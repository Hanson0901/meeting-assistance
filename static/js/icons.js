/* ==========================================
   會議助理網頁應用 - 內嵌 SVG Icon 庫
   不依賴外部 CDN，直接以 inline SVG 取代 emoji
   ========================================== */

const ICON_PATHS = {
    // 品牌標誌 (header logo)
    'logo-mark': '<rect x="3" y="3" width="18" height="18" rx="5" fill="currentColor" opacity="0.12" stroke="none"/><rect x="10" y="6.5" width="4" height="7.5" rx="2"/><path d="M7.2 11a4.8 4.8 0 0 0 9.6 0"/><path d="M12 15.5v2.7"/><path d="M9.2 18.5h5.6"/>',
    // 導覽 / 功能
    'history': '<circle cx="12" cy="13" r="7.2"/><path d="M12 9.3V13l2.6 1.6"/><path d="M9 3.6h6"/>',
    'settings': '<line x1="4" y1="7" x2="20" y2="7"/><circle cx="9" cy="7" r="1.8" fill="currentColor" stroke="none"/><line x1="4" y1="13" x2="20" y2="13"/><circle cx="16" cy="13" r="1.8" fill="currentColor" stroke="none"/><line x1="4" y1="19" x2="20" y2="19"/><circle cx="8" cy="19" r="1.8" fill="currentColor" stroke="none"/>',
    'activity': '<rect x="4" y="14" width="3.2" height="6.2" rx="1" fill="currentColor" stroke="none"/><rect x="10.4" y="8.6" width="3.2" height="11.6" rx="1" fill="currentColor" stroke="none"/><rect x="16.8" y="4" width="3.2" height="16.2" rx="1" fill="currentColor" stroke="none"/>',
    // 步驟
    'upload': '<path d="M12 15V4.3"/><path d="M7.4 8.7L12 4.3l4.6 4.4"/><path d="M4 19h16"/>',
    'waveform': '<path d="M3.5 12h1.8" /><path d="M7.8 8v8"/><path d="M12 5v14"/><path d="M16.2 8v8"/><path d="M18.7 12h1.8"/>',
    'people': '<circle cx="9" cy="8.2" r="2.8"/><path d="M4 19c0-3 2.2-5 5-5s5 2 5 5"/><circle cx="17.2" cy="9.1" r="2.1"/><path d="M15.2 19c.2-2.3 1.7-4.1 3.7-4.4"/>',
    'check-list': '<rect x="4" y="4" width="16" height="16" rx="3.5"/><path d="M8 12.5l2.2 2.2L16.2 9"/>',
    'clipboard': '<rect x="6" y="4" width="12" height="16" rx="2"/><rect x="9" y="2.4" width="6" height="3" rx="1"/><path d="M9 10.2h6"/><path d="M9 13.6h6"/><path d="M9 17h4"/>',
    'export': '<rect x="4" y="4" width="12" height="16" rx="2"/><path d="M9 9.2h4"/><path d="M9 13h4"/><path d="M16.5 9l3 3-3 3"/>',
    'signal': '<circle cx="12" cy="16.2" r="1.9" fill="currentColor" stroke="none"/><path d="M8.3 12.6a5.2 5.2 0 0 1 7.4 0"/><path d="M5.2 9.4a9.4 9.4 0 0 1 13.6 0"/>',
    // 訊息 / 日誌
    'message': '<rect x="4" y="5" width="16" height="10" rx="2.5"/><path d="M8 15v3.2l4-3.2"/>',
    'terminal': '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7.2 9.2l3 2.8-3 2.8"/><path d="M12.2 15h4.6"/>',
    'download': '<path d="M12 4v11"/><path d="M7.4 11.4L12 16l4.6-4.6"/><path d="M4 19h16"/>',
    'refresh': '<path d="M4.5 12a7.5 7.5 0 0 1 13-5.2"/><path d="M19.5 12a7.5 7.5 0 0 1-13 5.2"/><path d="M17.3 4.6v3.6h-3.6"/><path d="M6.7 19.4v-3.6h3.6"/>',
    'close-circle': '<circle cx="12" cy="12" r="8"/><path d="M9.3 9.3l5.4 5.4"/><path d="M14.7 9.3l-5.4 5.4"/>',
    'arrow-left': '<path d="M19 12H6"/><path d="M11 6.2L5.2 12l5.8 5.8"/>',
    'document': '<rect x="6" y="3" width="12" height="18" rx="2"/><path d="M9 8.2h6"/><path d="M9 12h6"/><path d="M9 15.8h4"/>',
    'play': '<path d="M8 5.3v13.4l11-6.7-11-6.7z" fill="currentColor" stroke="none"/>',
    'info': '<circle cx="12" cy="12" r="8"/><path d="M12 11v5"/><circle cx="12" cy="8" r="0.6" fill="currentColor" stroke="none"/>',
    'success': '<circle cx="12" cy="12" r="8"/><path d="M8.3 12.4l2.5 2.5 4.9-5.7"/>',
    'warning': '<path d="M12 4.4L21.2 19.4H2.8z"/><path d="M12 10.2v4"/><circle cx="12" cy="16.8" r="0.6" fill="currentColor" stroke="none"/>',
    'error': '<circle cx="12" cy="12" r="8"/><path d="M9.3 9.3l5.4 5.4"/><path d="M14.7 9.3l-5.4 5.4"/>',
    'chevron-right': '<path d="M9 5l7 7-7 7"/>',
    'file-check': '<rect x="6" y="3" width="12" height="18" rx="2"/><path d="M9 13l1.8 1.8L15 10.7"/>',
    'file-x': '<rect x="6" y="3" width="12" height="18" rx="2"/><path d="M9.6 10.6l4 4"/><path d="M13.6 10.6l-4 4"/>',
    // 主題切換 / 錄音功能
    'bulb-on': '<circle cx="12" cy="9.5" r="5.3"/><path d="M10 9.5h4"/><path d="M12 7.3v4.4"/><rect x="9.6" y="14.6" width="4.8" height="2.4" rx="1"/><path d="M10.5 19.4h3"/><path d="M12 2.4v1.6"/><path d="M6.4 4.9l1.2 1.2"/><path d="M17.6 4.9l-1.2 1.2"/><path d="M4 9.5h1.6"/><path d="M18.4 9.5H20"/>',
    'bulb-off': '<circle cx="12" cy="9.5" r="5.3"/><rect x="9.6" y="14.6" width="4.8" height="2.4" rx="1"/><path d="M10.5 19.4h3"/>',
    'mic': '<rect x="9.2" y="3" width="5.6" height="10.4" rx="2.8"/><path d="M6.4 11.2a5.6 5.6 0 0 0 11.2 0"/><path d="M12 16.8v3.2"/><path d="M9 20h6"/>',
    'stop-circle': '<circle cx="12" cy="12" r="8"/><rect x="9.3" y="9.3" width="5.4" height="5.4" rx="1" fill="currentColor" stroke="none"/>'
};

/**
 * 產生 icon 的 inline SVG 字串
 */
function iconSVG(name, size) {
    size = size || 18;
    const inner = ICON_PATHS[name] || ICON_PATHS['info'];
    return '<svg class="icon" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" ' +
        'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" ' +
        'aria-hidden="true" focusable="false">' + inner + '</svg>';
}

/**
 * 將頁面中所有 [data-icon] 元素替換為對應的 inline SVG
 * 用於初始 HTML 中靜態宣告的 icon（動態產生的內容請直接呼叫 iconSVG()）
 */
function renderIcons(root) {
    (root || document).querySelectorAll('[data-icon]').forEach(function (el) {
        const name = el.getAttribute('data-icon');
        const size = el.getAttribute('data-icon-size') || 18;
        el.innerHTML = iconSVG(name, size);
    });
}
