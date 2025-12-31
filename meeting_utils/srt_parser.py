#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SRT 檔案解析器
"""

class SRTParser:
    """SRT 檔案解析器"""
    
    @staticmethod
    def parse_srt_file(file_path):
        """解析 SRT 檔案，返回字幕條目列表"""
        subtitles = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            blocks = content.strip().split('\n\n')
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) >= 3:
                    try:
                        seq_num = int(lines[0].strip())
                        time_line = lines[1].strip()
                        start_time_str, end_time_str = time_line.split(' --> ')
                        start_time = SRTParser.parse_time(start_time_str.strip())
                        end_time = SRTParser.parse_time(end_time_str.strip())
                        
                        content_lines = lines[2:]
                        subtitle_text = '\n'.join(content_lines).strip()
                        
                        subtitles.append({
                            'seq': seq_num,
                            'start_time': start_time,
                            'end_time': end_time,
                            'start_time_str': start_time_str.strip(),
                            'end_time_str': end_time_str.strip(),
                            'text': subtitle_text
                        })
                    except Exception as e:
                        print(f"   ⚠️ 解析字幕塊失敗: {e}")
                        continue
            return subtitles
        except Exception as e:
            print(f"   ❌ 讀取 SRT 檔案失敗: {e}")
            return []

    @staticmethod
    def parse_time(time_str):
        """將 SRT 時間格式轉換為秒數"""
        try:
            parts = time_str.replace(',', '.').split(':')
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            total_seconds = hours * 3600 + minutes * 60 + seconds
            return total_seconds
        except Exception as e:
            print(f"   ⚠️ 時間解析失敗 '{time_str}': {e}")
            return 0