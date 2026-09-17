#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
網頁應用 - 會議助理 Web Interface
基於 Flask 框架，提供按鈕觸發各環節的功能
"""

from flask import Flask, render_template, request, jsonify, send_file, session
from flask_cors import CORS
from pathlib import Path
import os
import sys
import json
import subprocess
import threading
import time
from datetime import datetime
from typing import Dict, Any
import uuid

# 將專案根目錄加入 Python 路徑
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from meeting_v1_integrated import MeetingWorkflow, ObexPushError
from print_log_utils import (
    setup_print_logging,
    set_log_callback,
    find_session_log_file,
    read_log_tail,
)

# ==========================================
# Flask App 初始化
# ==========================================
app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = 'meeting-assistant-secret-key-' + str(uuid.uuid4())
CORS(app)

# 全局配置
UPLOAD_FOLDER = os.path.join(project_root, 'uploads')
OUTPUT_FOLDER = os.path.join(project_root, 'web_output')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2000 * 1024 * 1024  # 2GB 上傳限制

# 會話管理
workflows: Dict[str, MeetingWorkflow] = {}
workflow_states: Dict[str, Dict[str, Any]] = {}
session_logs: Dict[str, list] = {}  # 存儲每個會話的日誌
step_logs: Dict[str, Dict[str, list]] = {}  # 存儲每個會話每個步驟的日誌：{session_id: {step_name: [logs]}}
recording_threads: Dict[str, threading.Thread] = {}  # 存儲每個會話目前執行中的錄音背景執行緒

# 進程名前綴到步驟的映射
PROCESS_TO_STEP = {
    'run_asr_conda': 'asr',
    'run_pkd_conda': 'pkd',
    'run_actions_conda': 'actions',
    'run_summary_conda': 'summary',
    'run_export_conda': 'export',
    'run_bluetooth_conda': 'bluetooth'
}


def log_collection_callback(message, prefix, timestamp, process_name):
    """日誌收集回調函數
    
    根據進程名分類日誌到不同步驟
    """
    # 查找對應的步驟
    step_name = PROCESS_TO_STEP.get(process_name)
    
    if not step_name:
        return
    
    # 從所有活躍會話中查找使用該步驟的會話
    # （簡單方案：存儲當前活躍的會話 ID）
    if hasattr(log_collection_callback, 'current_session_id'):
        session_id = log_collection_callback.current_session_id
        
        # 初始化該會話的步驟日誌
        if session_id not in step_logs:
            step_logs[session_id] = {}
        if step_name not in step_logs[session_id]:
            step_logs[session_id][step_name] = []
        
        # 添加日誌
        formatted_log = f"[{timestamp}] {message}"
        step_logs[session_id][step_name].append(formatted_log)


# 設置日誌回調
set_log_callback(log_collection_callback)


def log_message(session_id, message):
    """同時記錄日誌到標準輸出和內存"""
    print(message)
    if session_id and session_id in session_logs:
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        session_logs[session_id].append(log_entry)

# ==========================================
# API 端點
# ==========================================

@app.route('/')
def index():
    """主頁"""
    return render_template('index.html')


@app.route('/api/session/create', methods=['POST'])
def create_session():
    """建立新的會議處理會話"""
    try:
        data = request.json or {}
        session_id = str(uuid.uuid4())[:8]
        
        output_dir = os.path.join(OUTPUT_FOLDER, session_id)
        os.makedirs(output_dir, exist_ok=True)
        
        # 初始化會議工作流程
        model_path = data.get('model_path', '/home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf')
        interval_minutes = int(data.get('interval_minutes', 5))
        overlap_seconds = int(data.get('overlap_seconds', 60))
        enable_bluetooth = data.get('enable_bluetooth', True)
        
        workflow = MeetingWorkflow(
            audio_device="hw:2,0",
            output_dir=output_dir,
            output_prefix="output",
            model_path=model_path,
            interval_minutes=interval_minutes,
            overlap_seconds=overlap_seconds,
            enable_recording=False,
            enable_bluetooth=enable_bluetooth,
            enable_proximity_monitor=False,
            enable_write_output=True,
            include_actions_and_summary_files=True,
            include_decisions_in_final_txt=True,
        )
        
        workflows[session_id] = workflow
        workflow_states[session_id] = {
            'status': 'created',
            'steps_completed': [],
            'current_step': None,
            'errors': [],
            'messages': [],
            'audio_file': None,
            'files': {},
            'is_recording': False,
            'bluetooth_target': None
        }
        
        # 初始化會話日誌
        session_logs[session_id] = []
        step_logs[session_id] = {}  # 初始化步驟日誌
        
        print(f"[WEB] 建立會話: {session_id}")
        session_logs[session_id].append(f"[{datetime.now().strftime('%H:%M:%S')}] 會話已建立")
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'output_dir': output_dir
        }), 200
    except Exception as e:
        print(f"[WEB][create_session] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/upload', methods=['POST'])
def upload_audio(session_id):
    """上傳音頻檔案"""
    try:
        if session_id not in workflows:
            return jsonify({'success': False, 'error': '會話不存在'}), 404
        
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '未找到檔案'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': '檔案名稱為空'}), 400
        
        output_dir = workflows[session_id].output_dir
        filename = os.path.basename(file.filename)
        filepath = os.path.join(output_dir, filename)
        
        file.save(filepath)
        
        workflows[session_id].audio_file = filepath
        workflow_states[session_id]['audio_file'] = filepath
        
        log_message(session_id, f"[WEB][{session_id}] 上傳音頻: {filepath}")
        log_message(session_id, f"[WEB][{session_id}] 檔案大小: {os.path.getsize(filepath) / 1024 / 1024:.2f} MB")
        
        return jsonify({
            'success': True,
            'filename': filename,
            'filepath': filepath
        }), 200
    except Exception as e:
        print(f"[WEB][upload_audio] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/record/start', methods=['POST'])
def start_recording(session_id):
    """使用樹梅派麥克風開始錄音"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404

    try:
        workflow = workflows[session_id]
        state = workflow_states[session_id]

        if workflow.is_recording:
            return jsonify({'success': False, 'error': '目前已在錄音中'}), 400

        # 重設為預設錄音路徑，避免覆蓋之前上傳的檔案（可能庫尾不同）
        workflow.audio_file = os.path.join(workflow.output_dir, f"{workflow.output_prefix}_audio.mkv")

        state['current_step'] = 'recording'
        state['is_recording'] = True

        def record_task():
            log_collection_callback.current_session_id = session_id
            try:
                log_message(session_id, f"[STEP] 開始使用麥克風錄音（裝置: {workflow.audio_device}）...")
                result = workflow.step1_record()

                if result and os.path.exists(workflow.audio_file):
                    workflow_states[session_id]['audio_file'] = workflow.audio_file
                    state['messages'].append('麥克風錄音已完成')
                    log_message(session_id, f"[SUCCESS] 錄音完成，檔案: {workflow.audio_file}")
                else:
                    state['errors'].append('錄音失敗，找不到輸出檔案')
                    log_message(session_id, f"[ERROR] 錄音失敗，找不到輸出檔案")
            except Exception as e:
                state['errors'].append(f'錄音錯誤: {str(e)}')
                log_message(session_id, f"[ERROR] 錄音異常: {e}")
            finally:
                state['is_recording'] = False
                state['current_step'] = None
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')

        thread = threading.Thread(target=record_task, daemon=True)
        recording_threads[session_id] = thread
        thread.start()

        return jsonify({
            'success': True,
            'message': '錄音已開始',
            'session_id': session_id
        }), 200
    except Exception as e:
        print(f"[WEB][start_recording] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/record/stop', methods=['POST'])
def stop_recording(session_id):
    """停止麥克風錄音"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404

    try:
        workflow = workflows[session_id]

        if not workflow.is_recording:
            return jsonify({'success': False, 'error': '目前不在錄音中'}), 400

        log_message(session_id, "[STEP] 收到停止錄音指令，正在完成檔案封裝...")
        workflow.is_recording = False

        thread = recording_threads.get(session_id)
        if thread:
            thread.join(timeout=10)

        ready = os.path.exists(workflow.audio_file)

        return jsonify({
            'success': True,
            'ready': ready,
            'audio_file': workflow.audio_file if ready else None
        }), 200
    except Exception as e:
        print(f"[WEB][stop_recording] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/step/asr', methods=['POST'])
def run_asr(session_id):
    """執行 ASR 轉錄"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        workflow = workflows[session_id]
        state = workflow_states[session_id]
        
        # 驗證音頻檔案是否存在
        if not workflow.audio_file or not os.path.exists(workflow.audio_file):
            error_msg = '未找到音頻檔案。請先上傳音頻檔案後再執行 ASR'
            state['errors'].append(error_msg)
            log_message(session_id, f"[WEB][{session_id}] ASR 前置檢查失敗: 音頻檔案不存在")
            return jsonify({
                'success': False,
                'error': error_msg
            }), 400
        
        state['current_step'] = 'asr'
        
        def asr_task():
            try:
                # 設置當前會話 ID 用於日誌回調
                log_collection_callback.current_session_id = session_id
                
                log_message(session_id, f"[STEP] 開始執行 ASR 語音轉文字...")
                result = workflow.step2_transcribe()
                
                if result:
                    state['steps_completed'].append('asr')
                    state['messages'].append('ASR 轉錄完成')
                    log_message(session_id, f"[SUCCESS] ASR 轉錄完成")
                else:
                    state['errors'].append('ASR 轉錄失敗 - 請檢查音頻檔案格式')
                    log_message(session_id, f"[ERROR] ASR 轉錄失敗 - 請檢查音頻檔案格式")
                
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
            except Exception as e:
                state['errors'].append(f'ASR 錯誤: {str(e)}')
                log_message(session_id, f"[ERROR] ASR 異常: {e}")
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
        
        thread = threading.Thread(target=asr_task, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'ASR 已開始執行',
            'session_id': session_id
        }), 200
    except Exception as e:
        print(f"[WEB][run_asr] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/step/pkd', methods=['POST'])
def run_pkd(session_id):
    """執行 People/Keypoints/Decisions 報告"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        workflow = workflows[session_id]
        state = workflow_states[session_id]
        
        state['current_step'] = 'pkd'
        
        def pkd_task():
            try:
                # 設置當前會話 ID 用於日誌回調
                log_collection_callback.current_session_id = session_id
                
                log_message(session_id, f"[STEP] 開始執行 PKD 報告提取...")
                result = workflow.step3_run_pkd_reports()
                
                if result:
                    state['steps_completed'].append('pkd')
                    state['messages'].append('PKD 報告完成')
                    log_message(session_id, f"[SUCCESS] PKD 報告生成完成")
                else:
                    state['errors'].append('PKD 報告生成失敗')
                    log_message(session_id, f"[ERROR] PKD 報告生成失敗")
                
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
            except Exception as e:
                state['errors'].append(f'PKD 錯誤: {str(e)}')
                log_message(session_id, f"[ERROR] PKD 異常: {e}")
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
        
        thread = threading.Thread(target=pkd_task, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'PKD 已開始執行',
            'session_id': session_id
        }), 200
    except Exception as e:
        print(f"[WEB][run_pkd] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/step/actions', methods=['POST'])
def run_actions(session_id):
    """執行提取行動項目"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        workflow = workflows[session_id]
        state = workflow_states[session_id]
        
        state['current_step'] = 'actions'
        
        def actions_task():
            try:
                # 設置當前會話 ID 用於日誌回調
                log_collection_callback.current_session_id = session_id
                
                log_message(session_id, f"[STEP] 開始提取行動項目...")
                result = workflow.step4_extract_actions()
                
                if result:
                    state['steps_completed'].append('actions')
                    state['messages'].append('行動項目提取完成')
                    log_message(session_id, f"[SUCCESS] 行動項目提取完成")
                else:
                    state['errors'].append('行動項目提取失敗')
                    log_message(session_id, f"[ERROR] 行動項目提取失敗")
                
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
            except Exception as e:
                state['errors'].append(f'Actions 錯誤: {str(e)}')
                log_message(session_id, f"[ERROR] Actions 異常: {e}")
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
        
        thread = threading.Thread(target=actions_task, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Actions 已開始執行',
            'session_id': session_id
        }), 200
    except Exception as e:
        print(f"[WEB][run_actions] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/step/summary', methods=['POST'])
def run_summary(session_id):
    """執行生成摘要"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        workflow = workflows[session_id]
        state = workflow_states[session_id]
        
        state['current_step'] = 'summary'
        
        def summary_task():
            try:
                # 設置當前會話 ID 用於日誌回調
                log_collection_callback.current_session_id = session_id
                
                log_message(session_id, f"[STEP] 開始生成會議摘要...")
                result = workflow.step5_generate_summary()
                
                if result:
                    state['steps_completed'].append('summary')
                    state['messages'].append('會議摘要已生成')
                    log_message(session_id, f"[SUCCESS] 會議摘要生成完成")
                else:
                    state['errors'].append('會議摘要生成失敗')
                    log_message(session_id, f"[ERROR] 會議摘要生成失敗")
                
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
            except Exception as e:
                state['errors'].append(f'Summary 錯誤: {str(e)}')
                log_message(session_id, f"[ERROR] Summary 異常: {e}")
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
        
        thread = threading.Thread(target=summary_task, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Summary 已開始執行',
            'session_id': session_id
        }), 200
    except Exception as e:
        print(f"[WEB][run_summary] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/step/export', methods=['POST'])
def run_export(session_id):
    """執行匯出 TXT"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        workflow = workflows[session_id]
        state = workflow_states[session_id]
        
        state['current_step'] = 'export'
        
        def export_task():
            try:
                # 設置當前會話 ID 用於日誌回調
                log_collection_callback.current_session_id = session_id
                
                log_message(session_id, f"[STEP] 開始將結果匯出為 TXT 檔案...")
                result = workflow.step6_export_txt()
                
                if result:
                    state['steps_completed'].append('export')
                    state['messages'].append('TXT 已匯出')
                    
                    # 收集輸出文件
                    output_dir = workflow.output_dir
                    txt_file = workflow.txt_file
                    actions_file = workflow.actions_file
                    summary_file = workflow.summary_file
                    
                    files = {}
                    if os.path.exists(txt_file):
                        files['meeting_summary'] = txt_file
                    if os.path.exists(actions_file):
                        files['actions'] = actions_file
                    if os.path.exists(summary_file):
                        files['summary'] = summary_file
                    
                    state['files'] = files
                    log_message(session_id, f"[SUCCESS] TXT 匯出完成，共 {len(files)} 個檔案")
                else:
                    state['errors'].append('TXT 匯出失敗')
                    log_message(session_id, f"[ERROR] TXT 匯出失敗")
                
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
            except Exception as e:
                state['errors'].append(f'Export 錯誤: {str(e)}')
                log_message(session_id, f"[ERROR] Export 異常: {e}")
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
        
        thread = threading.Thread(target=export_task, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Export 已開始執行',
            'session_id': session_id
        }), 200
    except Exception as e:
        print(f"[WEB][run_export] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/step/bluetooth', methods=['POST'])
def run_bluetooth(session_id):
    """執行藍牙傳送"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        workflow = workflows[session_id]
        state = workflow_states[session_id]
        
        state['current_step'] = 'bluetooth'
        
        def bluetooth_task():
            try:
                # 設置當前會話 ID 用於日誌回調
                log_collection_callback.current_session_id = session_id
                
                log_message(session_id, f"[STEP] 開始進行藍牙檔案傳送...")
                
                if not workflow.enable_bluetooth:
                    state['messages'].append('藍牙功能未啟用')
                    log_message(session_id, f"[WARN] 藍牙功能未啟用")
                    state['current_step'] = None
                    # 清除當前會話 ID
                    if hasattr(log_collection_callback, 'current_session_id'):
                        delattr(log_collection_callback, 'current_session_id')
                    return
                
                # 收集要傳送的檔案
                files_to_send = []
                for filepath in state['files'].values():
                    if os.path.exists(filepath):
                        files_to_send.append(filepath)
                
                if not files_to_send:
                    state['errors'].append('沒有檔案可傳送')
                    log_message(session_id, f"[ERROR] 沒有檔案可傳送")
                    state['current_step'] = None
                    # 清除當前會話 ID
                    if hasattr(log_collection_callback, 'current_session_id'):
                        delattr(log_collection_callback, 'current_session_id')
                    return
                
                # 執行藍牙傳送
                try:
                    target = state.get('bluetooth_target')
                    if target and target.get('mac'):
                        mac = target['mac']
                        name = target.get('name') or mac
                        log_message(session_id, f"[STEP] 使用已選擇的裝置: {name} ({mac})...")
                        success_count = 0
                        failed_files = []
                        for file_path in files_to_send:
                            try:
                                workflow.bt_sender.send_file(file_path, mac)
                                success_count += 1
                            except Exception as fe:
                                failed_files.append(os.path.basename(file_path))
                                log_message(session_id, f"[ERROR] 傳送 {os.path.basename(file_path)} 失敗: {fe}")
                        if success_count == 0:
                            raise ObexPushError('所有檔案傳送失敗')
                        state['steps_completed'].append('bluetooth')
                        if failed_files:
                            state['messages'].append(f'已傳送至 {name} ({mac})，部分檔案失敗: ' + ', '.join(failed_files))
                        else:
                            state['messages'].append(f'已傳送至 {name} ({mac})')
                        log_message(session_id, f"[SUCCESS] 藍牙傳送完成，目標設備: {name} ({mac})")
                    else:
                        log_message(session_id, f"[STEP] 未選擇裝置，正在搜尋已配對的藍牙設備...")
                        mac, name = workflow.bt_sender.auto_send_to_first_paired(files_to_send)
                        state['steps_completed'].append('bluetooth')
                        state['messages'].append(f'已傳送至 {name} ({mac})')
                        log_message(session_id, f"[SUCCESS] 藍牙傳送完成，目標設備: {name} ({mac})")
                except Exception as e:
                    state['errors'].append(f'藍牙傳送失敗: {str(e)}')
                    log_message(session_id, f"[ERROR] 藍牙傳送失敗: {e}")
                
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
            except Exception as e:
                state['errors'].append(f'Bluetooth 錯誤: {str(e)}')
                log_message(session_id, f"[ERROR] Bluetooth 異常: {e}")
                state['current_step'] = None
                # 清除當前會話 ID
                if hasattr(log_collection_callback, 'current_session_id'):
                    delattr(log_collection_callback, 'current_session_id')
        
        thread = threading.Thread(target=bluetooth_task, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': '藍牙傳送已開始執行',
            'session_id': session_id
        }), 200
    except Exception as e:
        print(f"[WEB][run_bluetooth] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/bluetooth/scan', methods=['POST'])
def scan_bluetooth_devices(session_id):
    """搜尋附近的藍牙裝置 (含已配對與尚未配對)"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404

    try:
        workflow = workflows[session_id]

        if not workflow.enable_bluetooth or not hasattr(workflow, 'bt_sender'):
            return jsonify({
                'success': False,
                'error': '此會話未啟用藍牙功能，請於設置面板勾選「啟用藍牙傳送」後重新建立會話'
            }), 400

        log_message(session_id, "[STEP] 開始搜尋附近的藍牙裝置...")
        devices = workflow.bt_sender.scan_devices(duration=6.0)
        log_message(session_id, f"[SUCCESS] 藍牙搜尋完成，找到 {len(devices)} 個裝置")

        return jsonify({'success': True, 'devices': devices}), 200
    except ObexPushError as e:
        log_message(session_id, f"[ERROR] 藍牙搜尋失敗: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        print(f"[WEB][scan_bluetooth_devices] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/bluetooth/select', methods=['POST'])
def select_bluetooth_device(session_id):
    """選擇藍牙目標裝置 (若尚未配對則自動嘗試配對並信任)"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404

    try:
        workflow = workflows[session_id]
        state = workflow_states[session_id]

        if not workflow.enable_bluetooth or not hasattr(workflow, 'bt_sender'):
            return jsonify({'success': False, 'error': '此會話未啟用藍牙功能'}), 400

        data = request.json or {}
        mac = (data.get('mac') or '').strip()
        name = (data.get('name') or mac).strip()

        if not mac:
            return jsonify({'success': False, 'error': '缺少裝置 MAC 位址'}), 400

        log_message(session_id, f"[STEP] 選擇藍牙目標裝置: {name} ({mac})")

        try:
            workflow.bt_sender.pair_and_trust(mac)
        except ObexPushError as e:
            log_message(session_id, f"[ERROR] 配對裝置失敗: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

        state['bluetooth_target'] = {'mac': mac, 'name': name}
        log_message(session_id, f"[SUCCESS] 已設定藍牙目標裝置: {name} ({mac})")

        return jsonify({'success': True, 'mac': mac, 'name': name}), 200
    except Exception as e:
        print(f"[WEB][select_bluetooth_device] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/logs', methods=['GET'])
def get_logs(session_id):
    """獲取會話日誌"""
    if session_id not in session_logs:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        logs = session_logs[session_id]
        # 只返回最後 100 條日誌以節省頻寬
        recent_logs = logs[-100:] if len(logs) > 100 else logs
        
        return jsonify({
            'success': True,
            'logs': recent_logs,
            'total': len(logs)
        }), 200
    except Exception as e:
        print(f"[WEB][get_logs] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/step/<step_name>/logs', methods=['GET'])
def get_step_logs(session_id, step_name):
    """獲取特定步驟的日誌"""
    if session_id not in step_logs:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        step_logs_data = step_logs[session_id].get(step_name, [])
        
        # 只返回最後 200 條日誌以節省頻寬
        recent_logs = step_logs_data[-200:] if len(step_logs_data) > 200 else step_logs_data
        
        return jsonify({
            'success': True,
            'step': step_name,
            'logs': recent_logs,
            'total': len(step_logs_data)
        }), 200
    except Exception as e:
        print(f"[WEB][get_step_logs] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/status', methods=['GET'])
def get_status(session_id):
    """獲取會話狀態"""
    if session_id not in workflow_states:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        state = workflow_states[session_id]
        return jsonify({
            'success': True,
            'status': state['status'],
            'current_step': state['current_step'],
            'steps_completed': state['steps_completed'],
            'messages': state['messages'],
            'errors': state['errors'],
            'files': state['files'],
            'is_recording': state.get('is_recording', False),
            'bluetooth_target': state.get('bluetooth_target')
        }), 200
    except Exception as e:
        print(f"[WEB][get_status] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/download/<filename>', methods=['GET'])
def download_file(session_id, filename):
    """下載檔案"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        state = workflow_states[session_id]
        
        if filename not in state['files']:
            return jsonify({'success': False, 'error': '檔案不存在'}), 404
        
        filepath = state['files'][filename]
        
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': '檔案已刪除'}), 404
        
        print(f"[WEB][{session_id}] 下載檔案: {filename}")
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=os.path.basename(filepath)
        )
    except Exception as e:
        print(f"[WEB][download_file] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/clear', methods=['POST'])
def clear_session(session_id):
    """清除會話"""
    try:
        if session_id in workflows:
            del workflows[session_id]
        if session_id in workflow_states:
            del workflow_states[session_id]
        
        print(f"[WEB] 清除會話: {session_id}")
        
        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"[WEB][clear_session] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ==========================================
# 歷史 Session 查看功能
# ==========================================
# 以下端點直接掃描 web_output 目錄，不依賴記憶體中的 workflows/
# workflow_states（那些資料伺服器重啟後就會丢失），因此即使是之前執行、
# 現在已不在線上的會議 session，仍可以在歷史列表中查看。

OUTPUT_PREFIX = "output"


def _get_session_output_dir(session_id):
    """安全地取得 session 的輸出目錄路徑，避免路徑穿越攻擊（例如 session_id 包含 ../ ）"""
    if not session_id:
        return None
    safe_id = os.path.basename(session_id)
    output_root = os.path.abspath(OUTPUT_FOLDER)
    session_dir = os.path.abspath(os.path.join(output_root, safe_id))
    if session_dir != output_root and not session_dir.startswith(output_root + os.sep):
        return None
    return session_dir


@app.route('/api/sessions/history', methods=['GET'])
def list_session_history():
    """列出所有歷史 session（掃描 web_output 目錄，不依賴記憶體狀態，
    伺服器重啟後依然可以查看過去的會議記錄）"""
    try:
        sessions = []
        if os.path.isdir(OUTPUT_FOLDER):
            for name in os.listdir(OUTPUT_FOLDER):
                session_dir = os.path.join(OUTPUT_FOLDER, name)
                if not os.path.isdir(session_dir):
                    continue

                try:
                    entries = os.listdir(session_dir)
                except Exception:
                    entries = []

                file_paths = [os.path.join(session_dir, e) for e in entries]
                file_paths = [p for p in file_paths if os.path.isfile(p)]

                if file_paths:
                    mtimes = [os.path.getmtime(p) for p in file_paths]
                    ctimes = [os.path.getctime(p) for p in file_paths]
                else:
                    mtimes = [os.path.getmtime(session_dir)]
                    ctimes = [os.path.getctime(session_dir)]

                created_at = min(ctimes)
                updated_at = max(mtimes)

                log_path = find_session_log_file(session_dir, OUTPUT_PREFIX)

                def _exists(fname):
                    return os.path.exists(os.path.join(session_dir, fname))

                has_asr = any(e.endswith('.srt') for e in entries)
                has_pkd = _exists(f'{OUTPUT_PREFIX}_pkd_cache.json')
                has_actions = _exists(f'{OUTPUT_PREFIX}_actions_cache.json')
                has_summary = _exists(f'{OUTPUT_PREFIX}_summary_cache.json')
                has_export = _exists(f'{OUTPUT_PREFIX}_meeting_summary.txt')

                sessions.append({
                    'session_id': name,
                    'created_at': datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M:%S'),
                    'updated_at': datetime.fromtimestamp(updated_at).strftime('%Y-%m-%d %H:%M:%S'),
                    'updated_at_ts': updated_at,
                    'has_log': log_path is not None,
                    'log_file': os.path.basename(log_path) if log_path else None,
                    'is_active': name in workflows,
                    'steps': {
                        'asr': has_asr,
                        'pkd': has_pkd,
                        'actions': has_actions,
                        'summary': has_summary,
                        'export': has_export,
                    },
                    'file_count': len(file_paths),
                })

        sessions.sort(key=lambda s: s['updated_at_ts'], reverse=True)
        for s in sessions:
            s.pop('updated_at_ts', None)

        return jsonify({'success': True, 'sessions': sessions, 'total': len(sessions)}), 200
    except Exception as e:
        print(f"[WEB][list_session_history] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sessions/<session_id>/output_log', methods=['GET'])
def get_session_output_log(session_id):
    """正確讀取並顯示 web_output/<session_id>/output_run.log 的內容

    Query 參數:
      - tail: 回傳最後 N 行（預設 500）
      - full=1: 回傳整個檔案內容（不截斷）
    """
    session_dir = _get_session_output_dir(session_id)
    if not session_dir or not os.path.isdir(session_dir):
        return jsonify({'success': False, 'error': '找不到此 session 的輸出目錄'}), 404

    try:
        full = request.args.get('full', '0') == '1'
        try:
            tail = int(request.args.get('tail', 500))
        except (TypeError, ValueError):
            tail = 500

        log_path = find_session_log_file(session_dir, OUTPUT_PREFIX)

        if not log_path:
            return jsonify({
                'success': True,
                'session_id': session_id,
                'log_file': None,
                'logs': [],
                'total_lines': 0,
                'returned_lines': 0,
                'truncated': False,
                'message': '尚未產生執行日誌'
            }), 200

        max_lines = -1 if full else max(tail, 1)
        lines, total_lines = read_log_tail(log_path, max_lines=max_lines)

        return jsonify({
            'success': True,
            'session_id': session_id,
            'log_file': os.path.basename(log_path),
            'size_bytes': os.path.getsize(log_path),
            'mtime': datetime.fromtimestamp(os.path.getmtime(log_path)).strftime('%Y-%m-%d %H:%M:%S'),
            'logs': lines,
            'total_lines': total_lines,
            'returned_lines': len(lines),
            'truncated': (not full) and total_lines > len(lines),
        }), 200
    except Exception as e:
        print(f"[WEB][get_session_output_log] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sessions/<session_id>/files', methods=['GET'])
def list_session_files(session_id):
    """列出此 session 輸出目錄下可下載的檔案"""
    session_dir = _get_session_output_dir(session_id)
    if not session_dir or not os.path.isdir(session_dir):
        return jsonify({'success': False, 'error': '找不到此 session 的輸出目錄'}), 404

    try:
        files = []
        for name in sorted(os.listdir(session_dir)):
            filepath = os.path.join(session_dir, name)
            if not os.path.isfile(filepath):
                continue
            files.append({
                'name': name,
                'size_bytes': os.path.getsize(filepath),
                'mtime': datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S'),
            })

        return jsonify({'success': True, 'session_id': session_id, 'files': files}), 200
    except Exception as e:
        print(f"[WEB][list_session_files] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sessions/<session_id>/download-file/<path:filename>', methods=['GET'])
def download_session_file(session_id, filename):
    """下載歷史 session 輸出目錄中的檔案（含路徑安全檢查）"""
    session_dir = _get_session_output_dir(session_id)
    if not session_dir or not os.path.isdir(session_dir):
        return jsonify({'success': False, 'error': '找不到此 session 的輸出目錄'}), 404

    try:
        safe_name = os.path.basename(filename)
        filepath = os.path.abspath(os.path.join(session_dir, safe_name))

        if filepath != session_dir and not filepath.startswith(session_dir + os.sep):
            return jsonify({'success': False, 'error': '不合法的檔案路徑'}), 400

        if not os.path.isfile(filepath):
            return jsonify({'success': False, 'error': '檔案不存在'}), 404

        return send_file(filepath, as_attachment=True, download_name=safe_name)
    except Exception as e:
        print(f"[WEB][download_session_file] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sessions/<session_id>/resume', methods=['POST'])
def resume_session(session_id):
    """恢復一個歷史 session，讓使用者可以接續尚未完成的步驟繼續執行

    行為：
      - 若此 session 目前已是「活躍」狀態（伺服器記憶體中已有對應的 workflow，
        例如剛剛才恢復過、或本來就還在執行中），直接回傳目前狀態，不重複建立。
      - 否則，依照 session_id 對應的輸出目錄，重新建立一個 MeetingWorkflow物件，
        並透過掃描目錄中既有的檔案（.srt / *_pkd_cache.json / *_actions_cache.json /
        *_summary_cache.json / *_meeting_summary.txt）推斷出哪些步驟已經完成，
        同時把先前步驟產生的中間結果（people/keypoints/decisions/actions/summary）
        讀回 workflow.cache，這樣即使中間跳過的步驟沒有重新執行，
        最後的「匯出 TXT」步驟仍能正確組合出完整內容。
      - 恢復後的 session 會被登記進與一般「建立新會議」session 相同的
        workflows / workflow_states / session_logs / step_logs 字典，
        因此前端可以直接沿用既有的 /api/session/<id>/step/<step> 等路由
        繼續執行後續步驟，完全不需要另外實作一套執行邏輯。
    """
    session_dir = _get_session_output_dir(session_id)
    if not session_dir or not os.path.isdir(session_dir):
        return jsonify({'success': False, 'error': '找不到此 session 的輸出目錄'}), 404

    try:
        # 若此 session 已經是活躍狀態，直接回傳目前狀態即可
        if session_id in workflows and session_id in workflow_states:
            workflow = workflows[session_id]
            state = workflow_states[session_id]
            audio_exists = bool(workflow.audio_file and os.path.exists(workflow.audio_file))
            return jsonify({
                'success': True,
                'session_id': session_id,
                'resumed': False,
                'already_active': True,
                'steps_completed': state['steps_completed'],
                'audio_exists': audio_exists,
                'files': state['files'],
            }), 200

        data = request.json or {}
        model_path = data.get('model_path', '/home/cgu-csie/qwen3-4b-instruct-2507-q8_0.gguf')
        interval_minutes = int(data.get('interval_minutes', 5))
        overlap_seconds = int(data.get('overlap_seconds', 60))
        enable_bluetooth = data.get('enable_bluetooth', True)

        workflow = MeetingWorkflow(
            audio_device="hw:2,0",
            output_dir=session_dir,
            output_prefix=OUTPUT_PREFIX,
            model_path=model_path,
            interval_minutes=interval_minutes,
            overlap_seconds=overlap_seconds,
            enable_recording=False,
            enable_bluetooth=enable_bluetooth,
            enable_proximity_monitor=False,
            enable_write_output=True,
            include_actions_and_summary_files=True,
            include_decisions_in_final_txt=True,
        )

        try:
            entries = os.listdir(session_dir)
        except Exception:
            entries = []

        def _exists(fname):
            return os.path.exists(os.path.join(session_dir, fname))

        # 尋找既有音訊檔（優先使用預設命名，找不到再掃描目錄中常見的音訊/視訊副檔名）
        default_audio = os.path.join(session_dir, f'{OUTPUT_PREFIX}_audio.mkv')
        found_audio = default_audio if os.path.exists(default_audio) else None
        if not found_audio:
            audio_exts = ('.mkv', '.wav', '.mp3', '.mp4', '.m4a', '.aac', '.flac', '.ogg', '.webm')
            for name in entries:
                if name.lower().endswith(audio_exts):
                    found_audio = os.path.join(session_dir, name)
                    break
        if found_audio:
            workflow.audio_file = found_audio

        steps_completed = []
        if any(e.endswith('.srt') for e in entries):
            steps_completed.append('asr')

        # 讀回 step3 (PKD) 的既有結果，讓 step6 匯出時仍能取得 people/keypoints/decisions
        cache_json = os.path.join(session_dir, f'{OUTPUT_PREFIX}_cache.json')
        if os.path.exists(cache_json):
            try:
                with open(cache_json, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                for key in ('people', 'keypoints', 'decisions', 'actions_text', 'title', 'summary'):
                    if key in cache_data:
                        workflow.cache[key] = cache_data[key]
            except Exception as e:
                print(f"[WEB][resume_session] 讀取 {OUTPUT_PREFIX}_cache.json 失敗: {e}")

        if _exists(f'{OUTPUT_PREFIX}_pkd_cache.json'):
            steps_completed.append('pkd')

        # 讀回 step4 (Actions) 的既有結果
        actions_cache_json = os.path.join(session_dir, f'{OUTPUT_PREFIX}_actions_cache.json')
        if os.path.exists(actions_cache_json):
            steps_completed.append('actions')
            try:
                with open(actions_cache_json, 'r', encoding='utf-8') as f:
                    adata = json.load(f)
                workflow.cache['segments'] = adata.get('segments', [])
                workflow.cache['actions_lines'] = adata.get('actions_lines', [])
                workflow.cache['actions_text'] = adata.get('actions_text', workflow.cache.get('actions_text', ''))
            except Exception as e:
                print(f"[WEB][resume_session] 讀取 {OUTPUT_PREFIX}_actions_cache.json 失敗: {e}")

        # 讀回 step5 (Summary) 的既有結果
        summary_cache_json = os.path.join(session_dir, f'{OUTPUT_PREFIX}_summary_cache.json')
        if os.path.exists(summary_cache_json):
            steps_completed.append('summary')
            try:
                with open(summary_cache_json, 'r', encoding='utf-8') as f:
                    sdata = json.load(f)
                raw_title = sdata.get('title', None)
                raw_summary = sdata.get('summary', None)
                if raw_title and '無法生成標題' not in str(raw_title):
                    workflow.cache['title'] = str(raw_title).strip()
                if raw_summary and '無法生成摘要' not in str(raw_summary):
                    workflow.cache['summary'] = str(raw_summary).strip()
            except Exception as e:
                print(f"[WEB][resume_session] 讀取 {OUTPUT_PREFIX}_summary_cache.json 失敗: {e}")

        files = {}
        if _exists(f'{OUTPUT_PREFIX}_meeting_summary.txt'):
            steps_completed.append('export')
            files['meeting_summary'] = os.path.join(session_dir, f'{OUTPUT_PREFIX}_meeting_summary.txt')
        if os.path.exists(workflow.actions_file):
            files['actions'] = workflow.actions_file
        if os.path.exists(workflow.summary_file):
            files['summary'] = workflow.summary_file

        audio_exists = bool(workflow.audio_file and os.path.exists(workflow.audio_file))

        workflows[session_id] = workflow
        workflow_states[session_id] = {
            'status': 'resumed',
            'steps_completed': steps_completed,
            'current_step': None,
            'errors': [],
            'messages': [
                f"已恢復歷史 session（已完成步驟: {', '.join(steps_completed) if steps_completed else '無'}）"
            ],
            'audio_file': workflow.audio_file if audio_exists else None,
            'files': files,
        }

        if session_id not in session_logs:
            session_logs[session_id] = []
        if session_id not in step_logs:
            step_logs[session_id] = {}
        session_logs[session_id].append(
            f"[{datetime.now().strftime('%H:%M:%S')}] 已恢復 session，可繼續執行未完成步驟"
        )

        print(f"[WEB] 恢復會話: {session_id}, 已完成步驟: {steps_completed}, 音訊存在: {audio_exists}")

        return jsonify({
            'success': True,
            'session_id': session_id,
            'resumed': True,
            'already_active': False,
            'steps_completed': steps_completed,
            'audio_exists': audio_exists,
            'files': files,
        }), 200
    except Exception as e:
        print(f"[WEB][resume_session] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ==========================================
# 錯誤處理
# ==========================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': '找不到資源'}), 404


@app.errorhandler(500)
def server_error(error):
    return jsonify({'success': False, 'error': '伺服器內部錯誤'}), 500


# ==========================================
# 主函數
# ==========================================

if __name__ == '__main__':
    print("[WEB] 會議助理 Web 應用啟動...")
    print(f"[WEB] 上傳資料夾: {UPLOAD_FOLDER}")
    print(f"[WEB] 輸出資料夾: {OUTPUT_FOLDER}")
    print("[WEB] 訪問 http://localhost:5000")

    # SSL 憑證設定（用於直接以 HTTPS 存取，例如區網內不透過 Nginx 的情境）
    SSL_CERT_PATH = '/etc/nginx/ssl/hyang.icu.pem'
    SSL_KEY_PATH = '/etc/nginx/ssl/hyang.icu.key'
    HTTPS_PORT = 5443

    if os.path.exists(SSL_CERT_PATH) and os.path.exists(SSL_KEY_PATH):
        def run_https():
            print(f"[WEB] 訪問 https://localhost:{HTTPS_PORT} (直接 HTTPS，不經過 Nginx)")
            app.run(
                host='0.0.0.0',
                port=HTTPS_PORT,
                debug=False,
                use_reloader=False,
                threaded=True,
                ssl_context=(SSL_CERT_PATH, SSL_KEY_PATH)
            )

        https_thread = threading.Thread(target=run_https, daemon=True)
        https_thread.start()
    else:
        print(f"[WEB] 警告: 找不到 SSL 憑證檔案 ({SSL_CERT_PATH} / {SSL_KEY_PATH})，僅啟用 HTTP")

    # 原有 HTTP 服務維持不變（供 Nginx 反向代理使用，port 5000）
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True
    )
