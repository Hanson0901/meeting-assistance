#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Meeting Assistant - Web API
只負責：
- Web / API
- 控制流程
- 背景分析任務
"""

import os
import threading
from flask import Flask, request, jsonify

# ===== 專案模組 =====
from config import ModelConfig
from meeting_utils import SRTParser
from meeting_utils import SRTSegmentizer
from extractors.people_extractor import PeopleExtractor
from extractors.keypoints_extractor import KeypointsExtractor
from extractors.decisions_extractor import DecisionsExtractor
from extractors.actions_extractor import ActionsExtractor
from extractors.summary_generator import SummaryGenerator

# ===== Flask App =====
app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ===== 全域狀態 =====
extractors = {}
processing_status = {}
analysis_results = {}

# =========================================================
# 初始化分析模組（五個 extractor）
# =========================================================
def initialize_meeting_analyzer():
    global extractors
    try:
        extractors = {
            "people": PeopleExtractor(ModelConfig, "people"),
            "keypoints": KeypointsExtractor(ModelConfig, "keypoints"),
            "decisions": DecisionsExtractor(ModelConfig, "decisions"),
            "actions": ActionsExtractor(ModelConfig, "actions"),
            "summary": SummaryGenerator(ModelConfig, "summary"),
        }
        print("✓ 會議分析模組初始化完成")
        return True
    except Exception as e:
        print(f"✗ 初始化失敗: {e}")
        extractors = {}
        return False


# =========================================================
# 核心分析流程（背景執行）
# =========================================================
def run_meeting_analysis(session_id: str, srt_path: str):
    try:
        processing_status[session_id] = {
            "stage": "解析 SRT",
            "progress": 10
        }

        # 1️⃣ 解析 SRT
        subtitles = SRTParser.parse_srt_file(srt_path)

        # 2️⃣ 分段
        segmentizer = SRTSegmentizer(max_duration=300, max_chars=5000)
        segments = segmentizer.segment_subtitles(subtitles)

        processing_status[session_id] = {
            "stage": "執行人物抽取",
            "progress": 30
        }
        people = extractors["people"].extract(segments)

        processing_status[session_id] = {
            "stage": "執行要點抽取",
            "progress": 45
        }
        keypoints = extractors["keypoints"].extract(segments)

        processing_status[session_id] = {
            "stage": "執行決策抽取",
            "progress": 60
        }
        decisions = extractors["decisions"].extract(segments)

        processing_status[session_id] = {
            "stage": "執行行動項目抽取",
            "progress": 75
        }
        actions = extractors["actions"].extract(segments)

        processing_status[session_id] = {
            "stage": "生成總結",
            "progress": 90
        }
        summary = extractors["summary"].generate(
            segments,
            people,
            keypoints,
            decisions,
            actions
        )

        analysis_results[session_id] = {
            "people": people,
            "keypoints": keypoints,
            "decisions": decisions,
            "actions": actions,
            "summary": summary
        }

        processing_status[session_id] = {
            "stage": "完成",
            "progress": 100,
            "done": True
        }

    except Exception as e:
        processing_status[session_id] = {
            "stage": f"錯誤：{e}",
            "error": True
        }


# =========================================================
# API：啟動分析
# =========================================================
@app.route("/analyze", methods=["POST"])
def analyze_meeting():
    if "file" not in request.files:
        return jsonify({"error": "缺少 SRT 檔案"}), 400

    file = request.files["file"]
    session_id = os.path.splitext(file.filename)[0]

    srt_path = os.path.join(OUTPUT_DIR, f"{session_id}.srt")
    file.save(srt_path)

    processing_status[session_id] = {
        "stage": "初始化",
        "progress": 0
    }

    t = threading.Thread(
        target=run_meeting_analysis,
        args=(session_id, srt_path),
        daemon=True
    )
    t.start()

    return jsonify({
        "session_id": session_id,
        "message": "分析已啟動"
    })


# =========================================================
# API：查詢進度
# =========================================================
@app.route("/status/<session_id>", methods=["GET"])
def get_status(session_id):
    return jsonify(processing_status.get(session_id, {"error": "無此 session"}))


# =========================================================
# API：取得結果
# =========================================================
@app.route("/result/<session_id>", methods=["GET"])
def get_result(session_id):
    if session_id not in analysis_results:
        return jsonify({"error": "尚未完成"}), 404
    return jsonify(analysis_results[session_id])


# =========================================================
# 啟動
# =========================================================
if __name__ == "__main__":
    print("🚀 啟動 Meeting Assistant API")
    initialize_meeting_analyzer()
    app.run(host="0.0.0.0", port=5000, debug=False)
