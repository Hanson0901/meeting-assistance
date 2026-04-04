#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
會議記錄整理系統主控制流程
Raspberry Pi 5 16GB 優化版本 v6.0 - 模組化架構
"""

import warnings
import pandas as pd
from datetime import datetime
import os

# 導入配置
from config.model_config import ModelConfig

# 導入工具類
from meeting_utils.srt_parser import SRTParser
from meeting_utils.srt_segmentizer import SRTSegmentizer

# 導入提取器
from extractors.people_extractor import PeopleExtractor
from extractors.keypoints_extractor import KeypointsExtractor
from extractors.decisions_extractor import DecisionsExtractor
from extractors.actions_extractor import ActionsExtractor
from extractors.summary_generator import SummaryGenerator

warnings.filterwarnings("ignore")


class MeetingProcessor:
    """會議記錄處理器"""
    
    def __init__(self):
        """初始化處理器"""
        print("="*70)
        print("🚀 會議記錄整理系統 v6.0 (模組化架構)")
        print("="*70)
        print("📦 系統架構:")
        print("   ✓ 模組化設計")
        print("   ✓ 獨立模型配置")
        print("   ✓ 記憶體優化管理")
        print("   ✓ 進度追蹤支持")
        print("="*70)
        
        # 初始化各個提取器（延遲載入模型）
        self.people_extractor = None
        self.keypoints_extractor = None
        self.decisions_extractor = None
        self.actions_extractor = None
        self.summary_generator = None
        
    def _init_extractor(self, extractor_type):
        """初始化指定的提取器"""
        model_config = ModelConfig.get_model_config(extractor_type)
        llama_config = ModelConfig.LLAMA_CONFIG
        memory_config = ModelConfig.MEMORY_CONFIG
        
        if extractor_type == 'people':
            self.people_extractor = PeopleExtractor(
                model_config['path'], llama_config, memory_config
            )
            self.people_extractor.generation_config = model_config
        elif extractor_type == 'keypoints':
            self.keypoints_extractor = KeypointsExtractor(
                model_config['path'], llama_config, memory_config
            )
            self.keypoints_extractor.generation_config = model_config
        elif extractor_type == 'decisions':
            self.decisions_extractor = DecisionsExtractor(
                model_config['path'], llama_config, memory_config
            )
            self.decisions_extractor.generation_config = model_config
        elif extractor_type == 'actions':
            self.actions_extractor = ActionsExtractor(
                model_config['path'], llama_config, memory_config
            )
            self.actions_extractor.generation_config = model_config
        elif extractor_type == 'summary':
            self.summary_generator = SummaryGenerator(
                model_config['path'], llama_config, memory_config
            )
            self.summary_generator.generation_config = model_config
    
    def process_srt_file(self, srt_file_path, output_file_path=None,
                        max_duration=120, max_chars=2000,
                        session_id=None, processing_status=None):
        """
        處理 SRT 檔案
        
        Args:
            srt_file_path: SRT 檔案路徑
            output_file_path: 輸出檔案路徑（可選）
            max_duration: 最大分段時長（秒）
            max_chars: 最大分段字符數
            session_id: 會話ID
            processing_status: 進度狀態字典
            
        Returns:
            (DataFrame, 總結文本) 或 None
        """
        try:
            # ===== 階段 0: 解析和分段 =====
            print(f"\n📂 正在讀取 SRT 檔案: {srt_file_path}")
            parser = SRTParser()
            subtitles = parser.parse_srt_file(srt_file_path)

            if not subtitles:
                print("❌ 未能解析任何字幕條目")
                return None

            print(f"✓ 成功解析 {len(subtitles)} 條字幕條目")

            # 分段
            print(f"\n🔧 正在進行分段處理...")
            segmentizer = SRTSegmentizer(max_duration=max_duration, max_chars=max_chars)
            segments = segmentizer.segment_subtitles(subtitles)
            print(f"✓ 成功分為 {len(segments)} 段")

            # 顯示分段信息
            total_duration_seconds = 0
            for i, seg in enumerate(segments, 1):
                print(f"   段 {i}: {seg['start_time_str']} - {seg['end_time_str']} "
                      f"({seg['duration_formatted']}, {seg['text_length']} 字)")
                total_duration_seconds += seg['duration_seconds']

            total_duration_formatted = SRTSegmentizer._format_duration(total_duration_seconds)
            print(f"\n📊 會議總時長: {total_duration_formatted}")

            # ===== 階段 1-4: 提取各類信息 =====
            print("\n" + "="*70)
            print("【開始提取會議信息】")
            print("="*70)

            # 階段 1: 提取人物
            self._init_extractor('people')
            all_people = self.people_extractor.extract(segments, session_id, processing_status)
            self.people_extractor.unload_model()

            # 階段 2: 提取要點
            self._init_extractor('keypoints')
            all_key_points = self.keypoints_extractor.extract(segments, session_id, processing_status)
            self.keypoints_extractor.unload_model()

            # 階段 3: 提取決策
            self._init_extractor('decisions')
            all_decisions = self.decisions_extractor.extract(segments, session_id, processing_status)
            self.decisions_extractor.unload_model()

            # 階段 4: 提取行動項目
            self._init_extractor('actions')
            all_actions = self.actions_extractor.extract(segments, session_id, processing_status)
            self.actions_extractor.unload_model()

            # ===== 統計信息 =====
            print("\n🔍 正在提取會議關鍵元素...")
            key_themes = []
            decisions_list = []
            actions_list = []
            raw_people_info = []

            # 提取人物
            for result in all_people.values():
                lines = result.split('\n')
                for line in lines:
                    if line.strip().startswith('-') and '本段無具體人物提及' not in line:
                        raw_people_info.append(line.strip().lstrip('- '))

            # 提取主題
            for result in all_key_points.values():
                lines = result.split('\n')
                for line in lines:
                    if line.strip() and any(line.strip().startswith(f"{i}.") for i in range(1, 10)):
                        key_themes.append(line.strip())

            # 提取決策
            for result in all_decisions.values():
                lines = result.split('\n')
                for line in lines:
                    if line.strip().startswith('-') and '本段為討論性質' not in line:
                        decisions_list.append(line.strip().lstrip('- '))

            # 提取行動項目
            for result in all_actions.values():
                lines = result.split('\n')
                for line in lines:
                    if line.strip().startswith('-') and '本段無具體行動項目' not in line:
                        actions_list.append(line.strip().lstrip('- '))

            unique_people_count = len(set([
                PeopleExtractor.extract_person_name(p) for p in raw_people_info
            ]))

            # 統計輸出
            print(f"📊 識別到 {unique_people_count} 位獨立人物")
            print(f"📊 提取到 {len(key_themes)} 個關鍵主題")
            print(f"📊 提取到 {len(decisions_list)} 個決策事項")
            print(f"📊 提取到 {len(actions_list)} 個行動項目")

            # ===== 階段 5: 生成總結 =====
            self._init_extractor('summary')
            overall_summary = self.summary_generator.generate(
                all_people, all_key_points, all_decisions, all_actions,
                len(segments), total_duration_formatted, session_id, processing_status
            )
            self.summary_generator.unload_model()

            print("\n" + "="*70)
            print("【信息提取完成】")
            print("="*70)

            # ===== 生成輸出文件 =====
            print("\n📊 正在構建逐段詳細報告...")
            all_results = []
            
            for idx, seg in enumerate(segments, 1):
                segment_result = {
                    '段號': idx,
                    '開始時間': seg['start_time_str'],
                    '結束時間': seg['end_time_str'],
                    '時長': seg['duration_formatted'],
                    '字幕條數': seg['subtitle_count'],
                    '原文字數': seg['text_length'],
                    '原文': seg['text'],
                    '人物': all_people.get(idx, ""),
                    '要點': all_key_points.get(idx, ""),
                    '決策': all_decisions.get(idx, ""),
                    '行動': all_actions.get(idx, ""),
                    '處理時間': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                all_results.append(segment_result)
            
            results_df = pd.DataFrame(all_results)

            # 生成輸出文件名
            if output_file_path is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                base_name = os.path.splitext(os.path.basename(srt_file_path))[0]
                csv_file_path = f'{base_name}_{timestamp}.csv'
                summary_file_path = f'{base_name}_summary_{timestamp}.md'
            else:
                base_name = output_file_path.replace('.csv', '')
                csv_file_path = f'{base_name}.csv'
                summary_file_path = f'{base_name}_summary.md'

            # 保存 CSV 文件
            results_df.to_csv(csv_file_path, index=False, encoding='utf-8-sig')
            print(f"✓ 逐段詳細報告已保存至: {csv_file_path}")

            # 保存 Markdown 總結
            with open(summary_file_path, 'w', encoding='utf-8') as f:
                f.write("# 會議整體主題總結（v6.0 模組化架構版）\n\n")
                f.write(f"**分析時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**會議時長**: {total_duration_formatted}\n")
                f.write(f"**總分段數**: {len(segments)} 段\n")
                f.write(f"**識別獨立人物數**: {unique_people_count} 位\n")
                f.write(f"**提取關鍵主題數**: {len(key_themes)} 個\n")
                f.write(f"**決策事項數**: {len(decisions_list)} 個\n")
                f.write(f"**行動項目數**: {len(actions_list)} 個\n")
                f.write(f"**詳細報告**: {csv_file_path}\n\n")
                f.write("---\n\n")
                f.write(overall_summary)

            print(f"✓ 會議整體總結已保存至: {summary_file_path}")

            print("\n" + "="*70)
            print("【輸出文件統計】")
            print("="*70)
            print(f"✓ CSV 逐段詳細報告: {csv_file_path}")
            print(f"✓ Markdown 整體總結: {summary_file_path}")
            print(f"✓ 總段數: {len(segments)}")
            print(f"✓ 獨立人物: {unique_people_count}")
            print("="*70)

            return results_df, overall_summary

        except Exception as e:
            print(f"❌ 處理失敗: {str(e)}")
            import traceback
            traceback.print_exc()
            return None


if __name__ == "__main__":
    print("\n" + "="*80)
    print("🚀 會議記錄整理系統 v6.0")
    print("   模組化架構 + 獨立模型配置")
    print("="*80)

    processor = MeetingProcessor()

    print(f"\n✅ 系統初始化完成!")
    print("="*80 + "\n")
    
    # 使用範例
    # processing_status = {}
    # session_id = "test_session"
    # srt_file = r"path/to/your/file.srt"
    # result = processor.process_srt_file(
    #     srt_file,
    #     session_id=session_id,
    #     processing_status=processing_status
    # )