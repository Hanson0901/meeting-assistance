"""
會議記錄整理系統 - Flask 後端 (修正版 v2.2.3)

【融合 srt.py 的語音轉文字最佳實踐】

【修正】支持 'file', 'audio_file', 'audio' 三種欄位格式

【修正】result 是 list，需要取第一個元素

【修正】返回字段名與前端匹配 (transcript / segments)

【修正】SRT 下載檔案名稱問題 (srt.txt → srt)

【保留】meeting_process 的會議分析功能

"""

from flask import Flask, request, jsonify, send_file, render_template

from flask_cors import CORS

from werkzeug.utils import secure_filename

import os

import threading

import traceback

from datetime import datetime


# 語音轉文字相關

from funasr import AutoModel


# 會議記錄整理相關 - 正確導入 meeting_process

try:

    from meeting_process2 import (

        SRTParser, SRTSegmentizer, GPTQInt8Qwen3Extractor

    )

    EXTRACTOR_AVAILABLE = True

except ImportError as e:

    print(f"⚠️  警告：無法導入 meeting_process 模組: {e}")

    EXTRACTOR_AVAILABLE = False

    # 定義備用類，防止代碼崩潰

    class SRTParser:

        pass

    class SRTSegmentizer:

        pass

    class MemoryOptimizedQwen3Extractor:

        pass


# 初始化 Flask 應用

app = Flask(__name__)

CORS(app)


# 配置

app.config['UPLOAD_FOLDER'] = 'uploads'

app.config['OUTPUT_FOLDER'] = 'outputs'

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

ALLOWED_EXTENSIONS = {'wav', 'mp3', 'flac', 'm4a', 'ogg'}


# 確保資料夾存在

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)


# 全域變數

asr_model = None

extractor = None

processing_status = {}

extraction_results = {}


# ============ 【參考 srt.py】模型初始化函數 ============

def initialize_asr_model():

    """

    初始化FunASR模型，整合ASR、VAD、標點和說話人分離

    【參考 srt.py 的做法】

    """

    global asr_model

    try:

        print("正在加載FunASR模型...")

        print("提示：首次運行會下載模型文件，需要穩定的網絡連接")

        # 整合方案：一次性加載所有功能

        asr_model = AutoModel(

            model="paraformer-zh",  # 主要ASR模型

            vad_model="fsmn-vad",  # 語音活動檢測

            punc_model="ct-punc",  # 標點恢復

            spk_model="cam++",  # 說話人分離 (CAM++)

            device="cpu",  # 使用CPU，如有GPU可改為 "cuda:0"

        )

        print("✓ 語音轉文字模型加載成功！")

        return True

    except Exception as e:

        print(f"✗ 語音模型加載失敗: {str(e)}")

        print("請檢查網絡連接或嘗試手動安裝：pip install funasr modelscope")

        return False


def initialize_meeting_analyzer():

    """

    初始化會議記錄分析模型

    """

    global extractor

    try:

        if EXTRACTOR_AVAILABLE:

            print("正在加載會議記錄分析模型...")

            extractor = GPTQInt8Qwen3Extractor()

            print("✓ 會議記錄模型加載完成")

            return True

        else:

            print("⚠️  會議記錄模型不可用 (meeting_process 模組未找到)")

            extractor = None

            return False

    except Exception as e:

        print(f"✗ 會議記錄模型加載失敗: {e}")

        extractor = None

        return False


def initialize_all_models():

    """

    初始化所有模型

    """

    print("\n" + "="*60)

    print("開始初始化模型...")

    print("="*60)

    

    asr_ok = initialize_asr_model()

    meeting_ok = initialize_meeting_analyzer()

    

    print("="*60)

    if asr_ok:

        print("✓ ASR 模型: 已載入")

    else:

        print("✗ ASR 模型: 載入失敗")

    

    if meeting_ok:

        print("✓ 會議分析模型: 已載入")

    else:

        print("⚠️  會議分析模型: 不可用")

    print("="*60 + "\n")

    

    return asr_ok


# ============ 【參考 srt.py】時間戳和結果處理函數 ============

def format_timestamp(milliseconds):

    """

    將毫秒轉換為SRT時間戳格式

    輸入: 毫秒 (int)

    輸出: "HH:MM:SS,mmm" 格式字符串

    """

    total_seconds = int(milliseconds / 1000)

    hours = total_seconds // 3600

    minutes = (total_seconds % 3600) // 60

    seconds = total_seconds % 60

    millis = int(milliseconds % 1000)

    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def process_funasr_result(result):

    """

    處理FunASR返回結果，提取說話人和時間戳信息

    Args:

        result: FunASR返回的結果字典

    Returns:

        list: 包含說話人、文本、時間戳的字典列表

    """

    processed_results = []

    # 檢查是否有詳細的句子信息

    if 'sentence_info' in result and result['sentence_info']:

        print(f"檢測到 {len(result['sentence_info'])} 個語音片段")

        for idx, sent in enumerate(result['sentence_info']):

            # 提取說話人標籤，默認為 "說話人1"

            speaker = sent.get('spk', f'說話人{idx % 2 + 1}')

            text = sent.get('text', '').strip()

            # 時間戳（毫秒）

            start_ms = sent.get('start', 0)

            end_ms = sent.get('end', 0)

            if text:  # 只添加非空文本

                processed_results.append({

                    'speaker': speaker,

                    'text': text,

                    'start': start_ms,

                    'end': end_ms

                })

    else:

        # 如果沒有詳細信息，使用整體結果

        print("未檢測到句子級別信息，使用整體結果")

        processed_results.append({

            'speaker': result.get('spk', '說話人1'),

            'text': result.get('text', ''),

            'start': 0,

            'end': 0

        })

    return processed_results


def generate_srt(results, output_path):

    """

    生成SRT字幕文件

    Args:

        results: 處理後的結果列表

        output_path: 輸出文件路徑

    """

    try:

        with open(output_path, 'w', encoding='utf-8') as f:

            for idx, item in enumerate(results, 1):

                # SRT格式：

                # 序號

                # 開始時間 --> 結束時間

                # 說話人: 文本內容

                # 空行

                f.write(f"{idx}\n")

                f.write(f"{format_timestamp(item['start'])} --> {format_timestamp(item['end'])}\n")

                f.write(f"{item['speaker']}: {item['text']}\n")

                f.write("\n")

        print(f"✓ SRT文件已生成: {output_path}")

        return True

    except Exception as e:

        print(f"✗ SRT生成失敗: {str(e)}")

        return False


# ============ API 端點 ============

def allowed_file(filename):

    """檢查檔案類型"""

    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_session_id():

    """生成會話 ID"""

    return datetime.now().strftime('%Y%m%d_%H%M%S_%f')


@app.route('/api/health', methods=['GET'])

def health_check():

    """健康檢查"""

    return jsonify({

        'status': 'ok',

        'asr_available': asr_model is not None,

        'extractor_available': extractor is not None

    })


@app.route('/api/transcribe', methods=['POST'])

def transcribe_audio():

    """

    語音轉文字端點 (修正版 v2.2.3)

    POST /api/transcribe

    【改進點】

    - 支持多種文件輸入格式 (file / audio_file / audio)

    - 支持熱詞提高識別準確率

    - 簡潔的返回格式

    - 完整的調試日誌

    【修正 v2.2.3】

    - 修正 result 是 list 的問題

    - 修正返回字段名 (transcript / segments)

    - 修正 SRT 檔案下載問題

    """

    # 調試信息（可選）

    print(f"request.files: {request.files}")

    print(f"可用的鍵: {list(request.files.keys())}")

    

    if asr_model is None:

        return jsonify({'error': '語音模型未初始化'}), 503

    # 【修正】支持 'file', 'audio_file', 'audio' 三種格式

    audio_file = (

        request.files.get('file') or 

        request.files.get('audio_file') or 

        request.files.get('audio')

    )

    if not audio_file:

        return jsonify({'error': '未找到音頻文件，請使用 file、audio_file 或 audio 欄位'}), 400

    if audio_file.filename == '':

        return jsonify({'error': '未選擇文件'}), 400

    if not allowed_file(audio_file.filename):

        return jsonify({'error': f'不支援的格式，允許: {", ".join(ALLOWED_EXTENSIONS)}'}), 400

    try:

        # 保存上傳的文件

        filename = secure_filename(audio_file.filename)

        session_id = generate_session_id()

        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{session_id}_{filename}")

        audio_file.save(temp_path)

        print(f"\n{'='*60}")

        print(f"開始處理音頻: {filename}")

        print(f"Session ID: {session_id}")

        print(f"{'='*60}")

        

        # 獲取熱詞（可選）【參考 srt.py】

        hotword = request.form.get('hotword', '').strip()

        if hotword:

            print(f"使用熱詞: {hotword}")

        

        # 執行語音識別和說話人分離

        print("正在執行語音識別...")

        result = asr_model.generate(

            input=temp_path,

            batch_size_s=300,  # 批處理大小

            hotword=hotword,  # 熱詞【新增】

            sentence_timestamp=True  # 啟用句子級時間戳

        )

        

        # 【修正】result 是列表，取第一個元素

        result_dict = result[0] if isinstance(result, list) else result

        

        print(f"識別完成，原始結果: {result_dict.get('text', '')[:100]}...")

        

        # 處理結果

        processed_results = process_funasr_result(result_dict)

        

        # 生成SRT文件

        base_name = os.path.splitext(filename)[0]

        srt_filename = f"{session_id}.srt"

        srt_path = os.path.join(app.config['OUTPUT_FOLDER'], srt_filename)

        

        if not generate_srt(processed_results, srt_path):

            raise Exception("SRT文件生成失敗")

        

        # 保存完整轉錄文本

        transcript_txt_path = os.path.join(

            app.config['OUTPUT_FOLDER'],

            f"{session_id}_transcribe.txt"

        )

        with open(transcript_txt_path, 'w', encoding='utf-8') as f:

            f.write("# 語音轉文字結果\n\n")

            f.write(f"**轉錄時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

            f.write(f"**原始檔案**: {filename}\n")

            f.write(f"**Session ID**: {session_id}\n")

            f.write(f"**檢測到分段數**: {len(processed_results)}\n\n")

            f.write("---\n\n")

            f.write("## 轉錄文本\n\n")

            f.write(result_dict.get('text', ''))

        

        print(f"✓ 轉錄文本已保存: {transcript_txt_path}")

        

        # 清理臨時上傳文件

        try:

            if os.path.exists(temp_path):

                os.remove(temp_path)

                print(f"✓ 清理臨時文件: {temp_path}")

        except Exception as e:

            print(f"警告：臨時文件清理失敗: {str(e)}")

        

        # 保存到全域結果字典

        full_text = result_dict.get('text', '')

        extraction_results[session_id] = {

            'transcript': full_text,

            'filename': filename,

            'timestamp': datetime.now().isoformat(),

            'segments': processed_results,

            'summary': None,

            'output_files': {

                'transcript_txt': transcript_txt_path,

                'srt': srt_path

            }

        }

        

        print(f"✓ 處理完成！")

        print(f"{'='*60}\n")

        

        # 【改進】簡潔的返回格式【參考 srt.py】

        # 【修正】返回字段名與前端匹配

        return jsonify({

            'success': True,

            'session_id': session_id,

            'transcript': full_text,

            'segments': processed_results,

            'srt_file': srt_filename,

            'segments_count': len(processed_results)

        })

    except Exception as e:

        print(f"\n{'='*60}")

        print(f"✗ 處理錯誤: {str(e)}")

        print(f"{'='*60}")

        traceback.print_exc()

        return jsonify({'error': f'轉錄失敗: {str(e)}'}), 500


def run_meeting_analysis(session_id, transcript):

    """

    後台執行會議分析

    """

    if not extractor:

        print(f"✗ 會議記錄模型未載入，無法執行分析")

        processing_status[session_id] = {

            'stage': '✗ 分析模型未載入',

            'progress': 0,

            'error': True,

            'complete': False

        }

        return

    try:

        print(f"\n{'='*60}")

        print(f"開始後台會議分析 (Session: {session_id})")

        print(f"{'='*60}")

        

        processing_status[session_id] = {

            'stage': '後台分析進行中...',

            'progress': 50,

            'timestamp': datetime.now().isoformat()

        }

        

        # 將轉錄文本轉換為 SRT 格式

        srt_content = generate_srt_from_transcript(transcript)

        

        # 保存 SRT 檔案

        srt_filename = f"{session_id}_analysis.srt"

        srt_filepath = os.path.join(app.config['OUTPUT_FOLDER'], srt_filename)

        with open(srt_filepath, 'w', encoding='utf-8') as f:

            f.write(srt_content)

        print(f"✓ 分析用 SRT 已生成: {srt_filepath}")

        

        processing_status[session_id] = {

            'stage': '開始會議分析...',

            'progress': 60,

            'timestamp': datetime.now().isoformat()

        }

        

        # 處理 SRT 檔案

        segments_csv_path = os.path.join(

            app.config['OUTPUT_FOLDER'],

            f"{session_id}_segments.csv"

        )

        result = extractor.process_srt_file_optimized(

            srt_filepath,

            output_file_path=segments_csv_path,

            max_duration=300,

            max_chars=5000

        )

        if result is None:

            raise Exception("會議分析失敗")

        segments_df, overall_summary = result

        

        # 保存摘要 MD

        summary_md_path = os.path.join(

            app.config['OUTPUT_FOLDER'],

            f"{session_id}_summary.md"

        )

        with open(summary_md_path, 'w', encoding='utf-8') as f:

            f.write("# 會議整體主題總結\n\n")

            f.write(f"**分析時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            f.write("---\n\n")

            f.write(overall_summary)

        print(f"✓ 摘要已保存: {summary_md_path}")

        

        # 保存轉錄文本 TXT

        transcript_txt_path = os.path.join(

            app.config['OUTPUT_FOLDER'],

            f"{session_id}_transcript.txt"

        )

        with open(transcript_txt_path, 'w', encoding='utf-8') as f:

            f.write("# 會議轉錄文本\n\n")

            f.write(f"**錄製時間**: {extraction_results.get(session_id, {}).get('timestamp', 'N/A')}\n\n")

            f.write("---\n\n")

            f.write(transcript)

        print(f"✓ 轉錄文本已保存: {transcript_txt_path}")

        

        # 更新結果

        extraction_results[session_id].update({

            'segments': segments_df.to_dict('records'),

            'summary': overall_summary,

            'output_files': {

                'transcript_txt': extraction_results[session_id]['output_files'].get('transcript_txt'),

                'transcript_source_txt': transcript_txt_path,

                'summary_md': summary_md_path,

                'segments_csv': segments_csv_path,

                'srt': extraction_results[session_id]['output_files'].get('srt')

            }

        })

        

        # 最終狀態：完成

        processing_status[session_id] = {

            'stage': '✓ 會議分析完成！',

            'progress': 100,

            'timestamp': datetime.now().isoformat(),

            'complete': True

        }

        print(f"\n✓ 後台分析完成!")

        print(f" - 分段數: {len(segments_df)}")

        print(f" - 輸出檔案已保存到: {app.config['OUTPUT_FOLDER']}")

        print(f"{'='*60}\n")

    except Exception as e:

        print(f"\n✗ 後台分析失敗: {str(e)}")

        traceback.print_exc()

        processing_status[session_id] = {

            'stage': f'✗ 分析失敗: {str(e)}',

            'progress': 0,

            'error': True,

            'complete': False

        }


@app.route('/api/process-meeting', methods=['POST'])

def process_meeting():

    """

    處理會議記錄端點

    POST /api/process-meeting

    """

    if extractor is None:

        return jsonify({'error': '會議記錄模型未載入，請稍後重試'}), 503

    data = request.get_json()

    session_id = data.get('session_id')

    transcript = data.get('transcript', '')

    if not session_id or not transcript:

        return jsonify({'error': '缺少必要參數'}), 400

    try:

        print(f"\n✓ 分析請求已接收，開始後台分析... (Session: {session_id})")

        thread = threading.Thread(

            target=run_meeting_analysis,

            args=(session_id, transcript)

        )

        thread.daemon = True

        thread.start()

        return jsonify({

            'success': True,

            'session_id': session_id,

            'message': '分析已在後台進行，請稍候...',

            'status': 'processing'

        })

    except Exception as e:

        print(f"✗ 分析啟動失敗: {str(e)}")

        processing_status[session_id] = {

            'stage': f'錯誤: {str(e)}',

            'progress': 0,

            'error': True

        }

        return jsonify({'error': f'分析啟動失敗: {str(e)}'}), 500


@app.route('/api/status/<session_id>', methods=['GET'])

def get_status(session_id):

    """獲取處理狀態"""

    status = processing_status.get(session_id, {'stage': '未知', 'progress': 0})

    if 'complete' not in status:

        status['complete'] = status.get('progress', 0) >= 100

    return jsonify(status)


@app.route('/api/result/<session_id>', methods=['GET'])

def get_result(session_id):

    """獲取處理結果"""

    result = extraction_results.get(session_id)

    if not result:

        return jsonify({'error': '找不到結果'}), 404

    return jsonify({

        'success': True,

        'transcript': result.get('transcript', ''),

        'summary': result.get('summary', ''),

        'segments': result.get('segments', []),

        'output_files': result.get('output_files', {})

    })


@app.route('/api/download/<session_id>/<file_type>', methods=['GET'])

def download_file(session_id, file_type):

    """下載檔案"""

    try:

        result = extraction_results.get(session_id)

        if not result:

            return jsonify({'error': '找不到會話'}), 404

        output_files = result.get('output_files', {})

        # 根據類型選擇檔案

        if file_type == 'transcript':

            filepath = output_files.get('transcript_txt')

            filename = f"{session_id}_transcribe.txt"

            mime = 'text/plain; charset=utf-8'

        elif file_type == 'summary':

            filepath = output_files.get('summary_md')

            filename = f"{session_id}_summary.md"

            mime = 'text/markdown; charset=utf-8'

        elif file_type == 'segments':

            filepath = output_files.get('segments_csv')

            filename = f"{session_id}_segments.csv"

            mime = 'text/csv; charset=utf-8'

        elif file_type == 'srt':

            filepath = output_files.get('srt')

            # 【修正 v2.2.3】SRT 檔案名稱修正

            filename = f"{session_id}.srt"  # 確保副檔名是 .srt 而不是 .srt.txt

            mime = 'text/plain; charset=utf-8'

        else:

            return jsonify({'error': '不支援的檔案類型'}), 400

        # 驗證檔案

        if not filepath or not os.path.exists(filepath):

            print(f"✗ 檔案不存在: {filepath}")

            return jsonify({'error': f'檔案不存在'}), 404

        print(f"✓ 下載: {filepath} → {filename}")

        return send_file(

            filepath,

            mimetype=mime,

            as_attachment=True,

            download_name=filename

        )

    except Exception as e:

        print(f"✗ 下載失敗: {str(e)}")

        return jsonify({'error': str(e)}), 500


@app.route('/')

def index():

    return render_template('index.html')


def generate_srt_from_transcript(transcript, avg_words_per_minute=80):

    """

    將轉錄文本轉換為 SRT 格式

    按時間和字數分割字幕

    """

    import re

    sentences = re.split(r'([。！？])', transcript)

    # 重新組合句子和標點

    text_chunks = []

    for i in range(0, len(sentences) - 1, 2):

        if i + 1 < len(sentences):

            text_chunks.append(sentences[i] + sentences[i + 1])

        elif i < len(sentences):

            text_chunks.append(sentences[i])

    srt_content = []

    current_time_ms = 0

    sequence = 1

    for chunk in text_chunks:

        if not chunk.strip():

            continue

        # 計算時間（基於字數）

        duration_ms = int((len(chunk) / avg_words_per_minute) * 60 * 1000)

        start_time = format_timestamp(current_time_ms)

        end_time = format_timestamp(current_time_ms + duration_ms)

        srt_content.append(f"{sequence}")

        srt_content.append(f"{start_time} --> {end_time}")

        srt_content.append(chunk.strip())

        srt_content.append("")

        current_time_ms += duration_ms

        sequence += 1

    return "\n".join(srt_content)


if __name__ == '__main__':

    print("\n" + "="*60)

    print("會議記錄整理系統 - Flask 後端 (修正版 v2.2.3)")

    print("="*60)

    print("【融合 srt.py 的最佳實踐】")

    print("【支持多種文件欄位格式】")

    print("【修正 result 是 list 的問題】")

    print("【修正返回字段名與前端匹配】")

    print("【修正 SRT 檔案下載問題】")

    print("="*60 + "\n")

    

    # 初始化所有模型

    if initialize_all_models():

        print("\n" + "="*60)

        print("✓ 服務啟動成功！")

        print("="*60)

        print("訪問地址: http://localhost:5000")

        print("支持的文件欄位: file, audio_file, audio")

        print("按 Ctrl+C 停止服務")

        print("="*60 + "\n")

        

        # 禁用 Debug 自動重啟，避免模型重複載入

        app.run(

            debug=False,

            host='0.0.0.0',

            port=5000,

            use_reloader=False,

            threaded=True

        )

    else:

        print("\n" + "="*60)

        print("✗ 服務啟動失敗：模型初始化錯誤")

        print("="*60 + "\n")

        print("請檢查以下事項：")

        print("1. 網絡連接是否正常")

        print("2. 是否已安裝依賴: pip install funasr modelscope transformers")

        print("3. 磁盤空間是否充足（需要約2GB用於模型文件）")

        print("4. meeting_process.py 是否存在")

        print("\n")