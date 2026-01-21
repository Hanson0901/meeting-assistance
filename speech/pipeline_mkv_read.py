import os
import sys
import time
import subprocess
import soundfile as sf
import numpy as np
from numpy.linalg import norm
from collections import deque

# 設置離線模式環境變數（必須在 import funasr 之前）
os.environ['MODELSCOPE_CACHE'] = '/home/cgu-csie/.cache/modelscope'
os.environ['HF_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_DATASETS_OFFLINE'] = '1'
os.environ['DISABLE_MODEL_DOWNLOADING'] = '1'

from funasr import AutoModel
from opencc import OpenCC


class RealtimeASR:
    """
    即時語音辨識與說話者識別系統
    
    主要參數（必須或常用）：
        audio_file: 輸入音訊檔案路徑
        output_dir: 輸出目錄
        output_prefix: 輸出檔案前綴
        
    次要參數（有合理預設值）：
        max_srt_duration: 每個SRT檔案的最大時長（秒）
        speaker_sim_threshold: 說話者相似度閾值
        segment_duration: 語音片段處理時長（秒）
        buffer_overlap: buffer 重疊時間（秒），用於避免切斷句子
        
    進階參數（通常不需要改）：
        sample_rate, chunk_duration 等
    """
    
    def __init__(
        self,
        # ========== 核心參數 ==========
        audio_file,
        output_dir=".",
        output_prefix="output",
        
        # ========== 常用參數 ==========
        max_srt_duration=300,
        speaker_sim_threshold=0.70,
        segment_duration=30.0,
        buffer_overlap=0.0,  # 新增：buffer 重疊時間（秒）
        
        # ========== 進階參數 ==========
        sample_rate=16000,
        chunk_duration=1.0,
        prototype_alpha=0.2,
        max_speakers=50,
        max_empty_segments_before_eof=5,
        max_read_failures=10,
        enable_simplified_to_traditional=True,
        
        # ========== 模型路徑（通常使用預設） ==========
        model_cache_dir="/home/cgu-csie/.cache/modelscope",
        paraformer_path=None,
        vad_path=None,
        punc_path=None,
        cam_path=None,
        
        # ========== 回調函數 ==========
        on_segment_callback=None,
        on_progress_callback=None,
        verbose=True
    ):
        """
        初始化即時 ASR 系統
        
        Args:
            audio_file: 音訊檔案路徑
            output_dir: 輸出目錄
            output_prefix: 輸出檔案前綴名稱
            max_srt_duration: 每個 SRT 檔案的最大累積秒數
            speaker_sim_threshold: 說話者識別相似度閾值（0-1）
            segment_duration: 處理語音片段的時長（秒）
            buffer_overlap: buffer 重疊時間（秒）
                - 0.0: 不重疊，可能切斷句子（最省記憶體）
                - 2.0-5.0: 適度重疊，減少切斷句子的機率
                - 注意：重疊過多可能導致重複輸出
            max_read_failures: 連續讀取失敗的最大次數，超過後判定檔案結束
            on_segment_callback: 當識別出新片段時的回調函數 callback(speaker_id, start, end, text)
            on_progress_callback: 進度回調函數 callback(processed_seconds)
            verbose: 是否輸出詳細訊息
        """
        # 核心參數
        self.audio_file = audio_file
        self.output_dir = output_dir
        self.output_prefix = output_prefix
        
        # 常用參數
        self.max_srt_duration = max_srt_duration
        self.speaker_sim_threshold = speaker_sim_threshold
        self.segment_duration = segment_duration
        self.buffer_overlap = buffer_overlap
        
        # 進階參數
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.prototype_alpha = prototype_alpha
        self.max_speakers = max_speakers
        self.max_empty_segments_before_eof = max_empty_segments_before_eof
        self.max_read_failures = max_read_failures
        self.enable_s2t = enable_simplified_to_traditional
        
        # 回調函數
        self.on_segment_callback = on_segment_callback
        self.on_progress_callback = on_progress_callback
        self.verbose = verbose
        
        # 臨時檔案（使用唯一名稱避免衝突）
        import uuid
        self.session_id = str(uuid.uuid4())[:8]
        self.tmp_seg_wav = f"tmp_seg_{self.session_id}.wav"
        self.tmp_spk_wav = f"tmp_spk_{self.session_id}.wav"
        
        # 內部狀態
        self.speaker_bank = {}
        self.next_spk_id = 1
        self.is_running = False
        self.empty_segments_count = 0
        
        # 模型路徑
        self.model_cache_dir = model_cache_dir
        self.paraformer_path = paraformer_path or f"{model_cache_dir}/hub/models/iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        self.vad_path = vad_path or f"{model_cache_dir}/hub/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
        self.punc_path = punc_path or f"{model_cache_dir}/hub/models/iic/punc_ct-transformer_cn-en-common-vocab471067-large"
        self.cam_path = cam_path or f"{model_cache_dir}/hub/models/iic/speech_campplus_sv_zh-cn_16k-common"
        
        # 初始化 OpenCC
        self.cc = OpenCC('s2t') if self.enable_s2t else None
        
        # 模型（延遲載入）
        self.model = None
        self.spk_model = None
        
        # 確保輸出目錄存在
        os.makedirs(self.output_dir, exist_ok=True)
    
    def _log(self, message):
        """內部日誌輸出"""
        if self.verbose:
            print(message, flush=True)
    
    def _load_models(self):
        """載入 ASR 和 Speaker 模型"""
        if self.model is not None and self.spk_model is not None:
            return  # 已載入
        
        self._log("載入模型中...")
        
        # 檢查模型路徑
        model_paths_exist = all(os.path.exists(path) for path in [
            self.paraformer_path, self.vad_path, self.punc_path, self.cam_path
        ])
        
        if not model_paths_exist:
            self._log("警告：部分本地模型路徑不存在，將嘗試使用模型名稱")
        
        # 靜默載入
        old_stderr = sys.stderr
        sys.stderr = open(os.devnull, 'w')
        
        try:
            # 載入主模型
            if model_paths_exist:
                try:
                    self.model = AutoModel(
                        model=self.paraformer_path,
                        vad_model=self.vad_path,
                        punc_model=self.punc_path,
                        spk_model=self.cam_path,
                        disable_update=True,
                        device="cpu"
                    )
                    self._log("成功載入本地模型")
                except Exception as e:
                    self._log(f"使用完整本地路徑失敗: {e}")
                    self.model = None
            
            if self.model is None:
                self.model = AutoModel(
                    model="paraformer-zh",
                    vad_model="fsmn-vad",
                    punc_model="ct-punc",
                    spk_model="cam++",
                    disable_update=True,
                    device="cpu"
                )
                self._log("成功載入本地模型（模型名稱）")
            
            # 載入 cam++ 模型
            if os.path.exists(self.cam_path):
                try:
                    self.spk_model = AutoModel(
                        model=self.cam_path,
                        disable_update=True,
                        device="cpu"
                    )
                except Exception:
                    self.spk_model = None
            
            if self.spk_model is None:
                self.spk_model = AutoModel(
                    model="cam++",
                    disable_update=True,
                    device="cpu"
                )
            
            self._log("模型載入完成\n" + "=" * 60)
        
        finally:
            sys.stderr.close()
            sys.stderr = old_stderr
    
    def _extract_chunk(self, start, duration):
        """提取音訊片段"""
        try:
            cmd = [
                "ffmpeg", "-loglevel", "error",
                "-ss", str(start),
                "-i", self.audio_file,
                "-t", str(duration),
                "-vn", "-acodec", "pcm_s16le",
                "-ac", "1", "-ar", str(self.sample_rate),
                "-avoid_negative_ts", "make_zero",
                "-fflags", "+discardcorrupt",
                "-f", "s16le", "pipe:1"
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30
            )
            
            if result.returncode != 0 or len(result.stdout) == 0:
                return None
            
            audio_data = np.frombuffer(result.stdout, dtype=np.int16)
            return audio_data if len(audio_data) > 0 else None
        
        except Exception:
            return None
    
    def _cosine_similarity(self, a, b):
        """計算餘弦相似度"""
        if a is None or b is None:
            return -1
        na = norm(a)
        nb = norm(b)
        if na == 0 or nb == 0:
            return -1
        return np.dot(a, b) / (na * nb)
    
    def _extract_speaker_embedding(self, audio_data, start_ms, end_ms):
        """提取說話者 embedding"""
        if audio_data is None or len(audio_data) == 0:
            return None
        
        start_sample = int((start_ms / 1000) * self.sample_rate)
        end_sample = int((end_ms / 1000) * self.sample_rate)
        
        start_sample = max(0, min(start_sample, len(audio_data)))
        end_sample = max(start_sample, min(end_sample, len(audio_data)))
        
        segment = audio_data[start_sample:end_sample]
        
        if len(segment) < self.sample_rate * 2:
            return None
        
        try:
            sf.write(self.tmp_spk_wav, segment, self.sample_rate)
            
            old_stderr = sys.stderr
            sys.stderr = open(os.devnull, 'w')
            
            result = self.spk_model.generate(
                input=self.tmp_spk_wav,
                batch_size_s=len(segment) / self.sample_rate
            )
            
            sys.stderr.close()
            sys.stderr = old_stderr
            
            if result and len(result) > 0:
                res = result[0]
                
                if isinstance(res, np.ndarray):
                    emb = res.flatten()
                    if emb.size > 0 and not np.isnan(emb).any():
                        emb_norm = np.linalg.norm(emb)
                        if emb_norm > 1e-8:
                            return emb / emb_norm
                
                if isinstance(res, dict):
                    for key in ['spk_embedding', 'embedding', 'spk_emb']:
                        if key in res and res[key] is not None:
                            emb = np.array(res[key]).flatten()
                            if emb.size > 0 and not np.isnan(emb).any():
                                emb_norm = np.linalg.norm(emb)
                                if emb_norm > 1e-8:
                                    return emb / emb_norm
        
        except Exception:
            pass
        
        return None
    
    def _identify_speaker(self, emb):
        """識別或創建說話者"""
        if emb is None:
            return None, 0.0
        
        if not self.speaker_bank:
            self.speaker_bank[1] = emb
            self.next_spk_id = 2
            return 1, 1.0
        
        best_match = None
        best_sim = -1
        
        for sid, proto in self.speaker_bank.items():
            sim = self._cosine_similarity(emb, proto)
            if sim > best_sim:
                best_sim = sim
                best_match = sid
        
        if best_sim >= self.speaker_sim_threshold:
            self.speaker_bank[best_match] = (
                self.prototype_alpha * emb +
                (1 - self.prototype_alpha) * self.speaker_bank[best_match]
            )
            return best_match, best_sim
        
        if len(self.speaker_bank) >= self.max_speakers:
            if best_match is not None:
                return best_match, best_sim
            else:
                return 1, 0.0
        
        self.speaker_bank[self.next_spk_id] = emb
        result_id = self.next_spk_id
        self.next_spk_id += 1
        return result_id, best_sim
    
    def _cleanup_temp_files(self):
        """清理臨時檔案"""
        temp_files = [self.tmp_seg_wav, self.tmp_spk_wav]
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
    
    def start(self):
        """開始處理音訊"""
        self.is_running = True
        
        # 載入模型
        self._load_models()
        
        # 等待音訊檔案
        self._log(f"等待音訊檔案: {self.audio_file}")
        while not os.path.exists(self.audio_file):
            if not self.is_running:
                return
            time.sleep(1)
        self._log("開始處理...\n")
        
        read_pos = 0.0
        consecutive_read_failures = 0
        long_buffer = deque()
        long_buffer_start = 0.0
        
        srt_file_index = 1
        srt_accumulated_time = 0.0
        srt_file = open(
            os.path.join(self.output_dir, f"{self.output_prefix}_{srt_file_index}.srt"),
            "w", encoding="utf-8"
        )
        
        try:
            while self.is_running:
                try:
                    chunk = self._extract_chunk(read_pos, self.chunk_duration)
                    
                    if chunk is None or len(chunk) == 0:
                        consecutive_read_failures += 1
                        
                        if consecutive_read_failures >= self.max_read_failures:
                            self._log(f"[檔案結束] 連續{self.max_read_failures}次讀取失敗，音訊檔案可能已結束")
                            break
                        
                        time.sleep(0.2)
                        continue
                    
                    consecutive_read_failures = 0
                    
                    long_buffer.append(chunk)
                    read_pos += self.chunk_duration
                    
                    # 定期清理和進度回調
                    if int(read_pos / self.chunk_duration) % 100 == 0:
                        self._cleanup_temp_files()
                        if int(read_pos / self.chunk_duration) % 500 == 0:
                            self._log(f"[進度] 已處理 {read_pos:.1f}秒音訊")
                            if self.on_progress_callback:
                                self.on_progress_callback(read_pos)
                    
                    # 處理語音片段
                    long_duration = sum(len(c) for c in long_buffer) / self.sample_rate
                    
                    if long_duration >= self.segment_duration:
                        self._log(f"[{read_pos:.1f}s] 處理{self.segment_duration}s語音片段...")
                        audio = np.concatenate(list(long_buffer))
                        
                        if audio.size > 0:
                            sf.write(self.tmp_seg_wav, audio, self.sample_rate)
                            
                            try:
                                old_stderr = sys.stderr
                                sys.stderr = open(os.devnull, 'w')
                                
                                results = self.model.generate(
                                    input=self.tmp_seg_wav,
                                    batch_size_s=long_duration,
                                    return_spk_emb=False
                                )
                                
                                sys.stderr.close()
                                sys.stderr = old_stderr
                                
                                if results and len(results) > 0:
                                    res = results[0]
                                    cam_segments = res.get("sentence_info", [])
                                    self._log(f"[{read_pos:.1f}s] 獲得 {len(cam_segments)} 個語音片段")
                                    
                                    # 檢測空片段
                                    if len(cam_segments) == 0:
                                        self.empty_segments_count += 1
                                        if self.empty_segments_count >= self.max_empty_segments_before_eof:
                                            self._log(f"[檔案結束] 連續{self.max_empty_segments_before_eof}次獲得0個語音片段")
                                            break
                                    else:
                                        self.empty_segments_count = 0
                                    
                                    if cam_segments:
                                        # 分組處理
                                        spk_groups = {}
                                        for seg in cam_segments:
                                            cam_spk = seg.get('spk', 0)
                                            if cam_spk not in spk_groups:
                                                spk_groups[cam_spk] = []
                                            spk_groups[cam_spk].append(seg)
                                        
                                        # 提取 embedding
                                        cam_to_global = {}
                                        for cam_spk, segs in spk_groups.items():
                                            longest_seg = max(segs, key=lambda s: s.get('end', 0) - s.get('start', 0))
                                            start_ms = longest_seg.get('start', 0)
                                            end_ms = longest_seg.get('end', 0)
                                            
                                            if (end_ms - start_ms) < 3000:
                                                start_ms = min(s.get('start', 0) for s in segs)
                                                end_ms = max(s.get('end', 0) for s in segs)
                                            
                                            emb = self._extract_speaker_embedding(audio, start_ms, end_ms)
                                            
                                            if emb is not None:
                                                global_spk, sim = self._identify_speaker(emb)
                                                if global_spk is not None:
                                                    cam_to_global[cam_spk] = global_spk
                                        
                                        # 輸出結果
                                        for seg in cam_segments:
                                            cam_spk = seg.get('spk', 0)
                                            start_ms = seg.get('start', 0)
                                            end_ms = seg.get('end', 0)
                                            text = seg.get('text', '').strip()
                                            
                                            if text and self.cc:
                                                text = self.cc.convert(text)
                                            
                                            if not text:
                                                continue
                                            
                                            abs_start = long_buffer_start + start_ms / 1000
                                            abs_end = long_buffer_start + end_ms / 1000
                                            global_spk = cam_to_global.get(cam_spk, None)
                                            
                                            # 切換 SRT 檔案
                                            if srt_accumulated_time + (abs_end - abs_start) > self.max_srt_duration:
                                                srt_file.close()
                                                srt_file_index += 1
                                                srt_accumulated_time = 0.0
                                                srt_file = open(
                                                    os.path.join(self.output_dir, f"{self.output_prefix}_{srt_file_index}.srt"),
                                                    "w", encoding="utf-8"
                                                )
                                            
                                            srt_accumulated_time += (abs_end - abs_start)
                                            
                                            # 寫入 SRT
                                            spk_label = str(global_spk) if global_spk is not None else "未知"
                                            srt_file.write(f"{spk_label}\n{abs_start:.3f} --> {abs_end:.3f}\n{text}\n\n")
                                            self._log(f"[{abs_start:.1f}s-{abs_end:.1f}s] [Speaker {spk_label}] {text}")
                                            
                                            # 回調
                                            if self.on_segment_callback:
                                                self.on_segment_callback(global_spk, abs_start, abs_end, text)
                            
                            except Exception as e:
                                self._log(f"語者分析層錯誤: {e}")
                        
                        # 清理 buffer - 使用 buffer_overlap 參數
                        if self.buffer_overlap <= 0:
                            # 完全清空 buffer
                            total_duration = sum(len(c) for c in long_buffer) / self.sample_rate
                            long_buffer.clear()
                            long_buffer_start += total_duration
                        else:
                            # 保留 buffer_overlap 秒的重疊
                            target_overlap_samples = int(self.buffer_overlap * self.sample_rate)
                            current_samples = sum(len(c) for c in long_buffer)
                            
                            while long_buffer and current_samples > target_overlap_samples:
                                removed = long_buffer.popleft()
                                current_samples -= len(removed)
                                long_buffer_start += len(removed) / self.sample_rate
                
                except KeyboardInterrupt:
                    self._log("\n程式結束")
                    break
                except Exception as e:
                    self._log(f"主循環錯誤: {e}")
        
        finally:
            # 處理剩餘資料
            if long_buffer:
                self._log("\n處理剩餘的 long_buffer 資料...")
                audio = np.concatenate(list(long_buffer))
                long_duration = sum(len(c) for c in long_buffer) / self.sample_rate

                if audio.size > 0:
                    sf.write(self.tmp_seg_wav, audio, self.sample_rate)

                    try:
                        old_stderr = sys.stderr
                        sys.stderr = open(os.devnull, 'w')

                        results = self.model.generate(
                            input=self.tmp_seg_wav,
                            batch_size_s=long_duration,
                            return_spk_emb=False
                        )

                        sys.stderr.close()
                        sys.stderr = old_stderr

                        if results and len(results) > 0:
                            res = results[0]
                            cam_segments = res.get("sentence_info", [])

                            if cam_segments:
                                self._log(f"\n處理剩餘的 {len(cam_segments)} 個語音片段")

                                spk_groups = {}
                                for seg in cam_segments:
                                    cam_spk = seg.get('spk', 0)
                                    if cam_spk not in spk_groups:
                                        spk_groups[cam_spk] = []
                                    spk_groups[cam_spk].append(seg)

                                cam_to_global = {}

                                for cam_spk, segs in spk_groups.items():
                                    longest_seg = max(segs, key=lambda s: s.get('end', 0) - s.get('start', 0))
                                    start_ms = longest_seg.get('start', 0)
                                    end_ms = longest_seg.get('end', 0)

                                    if (end_ms - start_ms) < 3000:
                                        start_ms = min(s.get('start', 0) for s in segs)
                                        end_ms = max(s.get('end', 0) for s in segs)

                                    emb = self._extract_speaker_embedding(audio, start_ms, end_ms)

                                    if emb is not None:
                                        global_spk, sim = self._identify_speaker(emb)
                                        if global_spk is not None:
                                            cam_to_global[cam_spk] = global_spk

                                for seg in cam_segments:
                                    cam_spk = seg.get('spk', 0)
                                    start_ms = seg.get('start', 0)
                                    end_ms = seg.get('end', 0)
                                    text = seg.get('text', '').strip()

                                    if text and self.cc:
                                        text = self.cc.convert(text)
                                    
                                    if not text:
                                        continue

                                    abs_start = long_buffer_start + start_ms / 1000
                                    abs_end = long_buffer_start + end_ms / 1000

                                    global_spk = cam_to_global.get(cam_spk, None)
                                    spk_label = str(global_spk) if global_spk is not None else "未知"

                                    srt_file.write(f"{spk_label}\n{abs_start:.3f} --> {abs_end:.3f}\n{text}\n\n")
                                    self._log(f"[{abs_start:.1f}s-{abs_end:.1f}s] [Speaker {spk_label}] {text}")
                                    
                                    if self.on_segment_callback:
                                        self.on_segment_callback(global_spk, abs_start, abs_end, text)

                    except Exception as e:
                        self._log(f"處理剩餘資料時發生錯誤: {e}")
                        import traceback
                        traceback.print_exc()
            
            srt_file.close()
            self._cleanup_temp_files()
            self._log("程式結束，已清理所有資源")
    
    def stop(self):
        """停止處理"""
        self.is_running = False
        self._log("正在停止...")


# ========== 向後相容：保留原有的 main() 函數介面 ==========
def main():
    """向後相容的 main 函數"""
    asr = RealtimeASR(
        audio_file="output_audio.mkv",
        output_dir=".",
        output_prefix="output",
        prototype_alpha=0.0,
        buffer_overlap=5.0  # 不重疊，避免重複輸出
    )
    asr.start()


if __name__ == "__main__":
    main()