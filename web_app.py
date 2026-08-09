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

from meeting_v1_integrated import MeetingWorkflow
from print_log_utils import setup_print_logging

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
            'files': {}
        }
        
        print(f"[WEB] 建立會話: {session_id}")
        
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
        
        print(f"[WEB][{session_id}] 上傳音頻: {filepath}")
        
        return jsonify({
            'success': True,
            'filename': filename,
            'filepath': filepath
        }), 200
    except Exception as e:
        print(f"[WEB][upload_audio] 錯誤: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/step/asr', methods=['POST'])
def run_asr(session_id):
    """執行 ASR 轉錄"""
    if session_id not in workflows:
        return jsonify({'success': False, 'error': '會話不存在'}), 404
    
    try:
        workflow = workflows[session_id]
        state = workflow_states[session_id]
        
        state['current_step'] = 'asr'
        
        def asr_task():
            try:
                print(f"[WEB][{session_id}] 開始 ASR...")
                result = workflow.step2_transcribe()
                
                if result:
                    state['steps_completed'].append('asr')
                    state['messages'].append('✓ ASR 轉錄完成')
                    print(f"[WEB][{session_id}] ASR 完成")
                else:
                    state['errors'].append('ASR 轉錄失敗')
                    print(f"[WEB][{session_id}] ASR 失敗")
                
                state['current_step'] = None
            except Exception as e:
                state['errors'].append(f'ASR 錯誤: {str(e)}')
                print(f"[WEB][{session_id}] ASR 異常: {e}")
                state['current_step'] = None
        
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
                print(f"[WEB][{session_id}] 開始 PKD...")
                result = workflow.step3_run_pkd_reports()
                
                if result:
                    state['steps_completed'].append('pkd')
                    state['messages'].append('✓ People/Keypoints/Decisions 已生成')
                    print(f"[WEB][{session_id}] PKD 完成")
                else:
                    state['errors'].append('PKD 報告生成失敗')
                    print(f"[WEB][{session_id}] PKD 失敗")
                
                state['current_step'] = None
            except Exception as e:
                state['errors'].append(f'PKD 錯誤: {str(e)}')
                print(f"[WEB][{session_id}] PKD 異常: {e}")
                state['current_step'] = None
        
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
                print(f"[WEB][{session_id}] 開始提取行動項目...")
                result = workflow.step4_extract_actions()
                
                if result:
                    state['steps_completed'].append('actions')
                    state['messages'].append('✓ 行動項目已提取')
                    print(f"[WEB][{session_id}] Actions 完成")
                else:
                    state['errors'].append('行動項目提取失敗')
                    print(f"[WEB][{session_id}] Actions 失敗")
                
                state['current_step'] = None
            except Exception as e:
                state['errors'].append(f'Actions 錯誤: {str(e)}')
                print(f"[WEB][{session_id}] Actions 異常: {e}")
                state['current_step'] = None
        
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
                print(f"[WEB][{session_id}] 開始生成摘要...")
                result = workflow.step5_generate_summary()
                
                if result:
                    state['steps_completed'].append('summary')
                    state['messages'].append('✓ 會議摘要已生成')
                    print(f"[WEB][{session_id}] Summary 完成")
                else:
                    state['errors'].append('會議摘要生成失敗')
                    print(f"[WEB][{session_id}] Summary 失敗")
                
                state['current_step'] = None
            except Exception as e:
                state['errors'].append(f'Summary 錯誤: {str(e)}')
                print(f"[WEB][{session_id}] Summary 異常: {e}")
                state['current_step'] = None
        
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
                print(f"[WEB][{session_id}] 開始匯出...")
                result = workflow.step6_export_txt()
                
                if result:
                    state['steps_completed'].append('export')
                    state['messages'].append('✓ TXT 已匯出')
                    
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
                    print(f"[WEB][{session_id}] Export 完成")
                else:
                    state['errors'].append('TXT 匯出失敗')
                    print(f"[WEB][{session_id}] Export 失敗")
                
                state['current_step'] = None
            except Exception as e:
                state['errors'].append(f'Export 錯誤: {str(e)}')
                print(f"[WEB][{session_id}] Export 異常: {e}")
                state['current_step'] = None
        
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
                print(f"[WEB][{session_id}] 開始藍牙傳送...")
                
                if not workflow.enable_bluetooth:
                    state['messages'].append('⚠ 藍牙功能未啟用')
                    state['current_step'] = None
                    return
                
                # 收集要傳送的檔案
                files_to_send = []
                for filepath in state['files'].values():
                    if os.path.exists(filepath):
                        files_to_send.append(filepath)
                
                if not files_to_send:
                    state['errors'].append('沒有檔案可傳送')
                    state['current_step'] = None
                    return
                
                # 執行藍牙傳送
                try:
                    mac, name = workflow.bt_sender.auto_send_to_first_paired(files_to_send)
                    state['steps_completed'].append('bluetooth')
                    state['messages'].append(f'✓ 已傳送至 {name} ({mac})')
                    print(f"[WEB][{session_id}] Bluetooth 完成")
                except Exception as e:
                    state['errors'].append(f'藍牙傳送失敗: {str(e)}')
                    print(f"[WEB][{session_id}] Bluetooth 失敗: {e}")
                
                state['current_step'] = None
            except Exception as e:
                state['errors'].append(f'Bluetooth 錯誤: {str(e)}')
                print(f"[WEB][{session_id}] Bluetooth 異常: {e}")
                state['current_step'] = None
        
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
            'files': state['files']
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
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True
    )
