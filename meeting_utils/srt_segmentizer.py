#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SRT 分段器
"""

class SRTSegmentizer:
    """SRT 分段器"""
    
    def __init__(self, max_duration=120, max_chars=2000):
        self.max_duration = max_duration
        self.max_chars = max_chars

    def segment_subtitles(self, subtitles):
        """將字幕分段"""
        if not subtitles:
            return []
        
        segments = []
        current_segment = []
        current_duration = 0
        current_chars = 0
        segment_start_idx = 0

        for i, subtitle in enumerate(subtitles):
            new_duration = subtitle['end_time'] - subtitles[segment_start_idx]['start_time']
            new_chars = current_chars + len(subtitle['text'])

            if current_segment and (new_duration > self.max_duration or new_chars > self.max_chars):
                segment = self._create_segment(current_segment, segment_start_idx, i - 1, subtitles)
                segments.append(segment)

                current_segment = [subtitle]
                segment_start_idx = i
                current_duration = 0
                current_chars = len(subtitle['text'])
            else:
                current_segment.append(subtitle)
                current_duration = new_duration
                current_chars = new_chars

        if current_segment:
            segment = self._create_segment(current_segment, segment_start_idx, len(subtitles) - 1, subtitles)
            segments.append(segment)

        return segments

    def _create_segment(self, segment_subs, start_idx, end_idx, all_subtitles):
        """創建分段對象"""
        start_time = segment_subs[0]['start_time']
        end_time = segment_subs[-1]['end_time']
        duration = end_time - start_time
        full_text = '\n'.join([sub['text'] for sub in segment_subs])

        return {
            'start_idx': start_idx + 1,
            'end_idx': end_idx + 1,
            'start_time': start_time,
            'end_time': end_time,
            'start_time_str': segment_subs[0]['start_time_str'],
            'end_time_str': segment_subs[-1]['end_time_str'],
            'duration_seconds': duration,
            'duration_formatted': self._format_duration(duration),
            'subtitle_count': len(segment_subs),
            'text': full_text,
            'text_length': len(full_text),
        }

    @staticmethod
    def _format_duration(seconds):
        """格式化時長顯示"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}分{secs}秒"