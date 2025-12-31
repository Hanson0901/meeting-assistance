#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行動項目提取器
"""

from datetime import datetime
from typing import List, Dict
from .base_extractor import BaseExtractor


class ActionsExtractor(BaseExtractor):
    """行動項目提取器"""
    
    def extract(self, segments: List[Dict], session_id: str = None, 
                processing_status: dict = None) -> Dict:
        """
        提取所有分段的行動項目
        
        Args:
            segments: 分段列表
            session_id: 會話ID
            processing_status: 進度狀態字典
            
        Returns:
            字典，key為段號，value為提取結果
        """
        print("\n【階段 4】提取所有分段的行動項目...")
        
        self.load_model()
        results = {}
        total_segments = len(segments)
        
        for idx, seg in enumerate(segments, 1):
            # 更新進度
            if session_id and processing_status:
                progress = 84 + int(8*(idx / total_segments))
                processing_status[session_id] = {
                    'stage': f'提取行動項目中... ({idx}/{total_segments})',
                    'progress': progress,
                    'timestamp': datetime.now().isoformat()
                }
            
            prompt = self._build_prompt(idx, seg)
            result = self.generate_response(prompt)
            
            results[idx] = result
            self.aggressive_memory_cleanup()
            print(f"  ✓ 分段 {idx}/{total_segments} 行動項目提取完成")
        
        print(f"✓ 所有分段行動項目提取完成")
        return results
    
    def _build_prompt(self, idx: int, seg: Dict) -> str:
        """構建提示詞"""
        return f"""你是一位專業的行動規劃專家,請從以下會議記錄中識別行動項目。

### 任務要求 ###
1. 使用繁體中文回答
2. 識別所有待辦事項、後續行動或指派任務
3. 標註負責人或執行單位(如有提及)
4. 區分緊急程度或時間要求

### 輸出格式 ###
### 行動項目
- [待辦事項內容] - [負責人/單位](如有)
(如無行動項目,則回覆"本段無具體行動項目")

### 會議記錄內容 ###
【分段 {idx}】({seg['start_time_str']} - {seg['end_time_str']})
{seg['text'][:1500]}

###end###

請開始識別:"""