#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BaseExtractor
從 pasted.txt 中抽取的共用 llama.cpp 推論與記憶體管理邏輯
【使用 ModelConfig（class-based）】
"""

from llama_cpp import Llama
import os
import gc
import time
import psutil
from config.model_config import ModelConfig


class BaseExtractor:
    """共用 llama.cpp 推論基底類"""

    def __init__(self, extractor_type="people", model_path=None, n_ctx=None):
        """
        extractor_type: people | keypoints | decisions | actions | summary
        若未指定 model_path / n_ctx，則從 ModelConfig 取得
        """
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        os.environ['OMP_NUM_THREADS'] = '4'

        # ======================
        # 從 ModelConfig 取設定
        # ======================
        model_cfg = ModelConfig.get_model_config(extractor_type)
        llama_cfg = ModelConfig.LLAMA_CONFIG
        mem_cfg = ModelConfig.MEMORY_CONFIG

        self.model_path = model_path or model_cfg["path"]
        self.n_ctx = n_ctx or llama_cfg["n_ctx"]
        self.max_retries = mem_cfg["max_retries"]

        self.temperature = model_cfg["temperature"]
        self.top_p = model_cfg["top_p"]
        self.top_k = model_cfg["top_k"]

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"模型檔案不存在: {self.model_path}")

        # ======================
        # 初始化 Llama
        # ======================
        self.model = Llama(
            model_path=self.model_path,
            n_gpu_layers=llama_cfg["n_gpu_layers"],
            n_threads=llama_cfg["n_threads"],
            n_ctx=self.n_ctx,
            verbose=llama_cfg["verbose"],
        )

        print(f"✅ Loaded model [{extractor_type}]: {self.model_path}")

    # ======================
    # 記憶體相關（不動）
    # ======================

    def get_memory_usage(self):
        return {
            'cpu_percent': psutil.virtual_memory().percent,
            'cpu_available': psutil.virtual_memory().available / 1024**3,
            'cpu_used': psutil.virtual_memory().used / 1024**3,
        }

    def print_memory_usage(self, stage=""):
        memory = self.get_memory_usage()
        print(f"📊 記憶體狀況 {stage}:")
        print(f"   使用率: {memory['cpu_percent']:.1f}%")
        print(f"   已用: {memory['cpu_used']:.1f}GB")
        print(f"   可用: {memory['cpu_available']:.1f}GB")

    def aggressive_memory_cleanup(self):
        gc.collect()
        time.sleep(0.05)

    def check_memory_pressure(self):
        return self.get_memory_usage()['cpu_percent'] > 90

    # ======================
    # 推論（只小改：用 self.xxx）
    # ======================

    def generate_response(self, prompt, max_tokens, retry_count=0):
        if retry_count >= self.max_retries:
            return "記憶體不足，無法生成回應。"

        try:
            if self.check_memory_pressure():
                self.aggressive_memory_cleanup()
                print("   ⚠️ 記憶體預先清理")

            response = self.model(
                prompt,
                max_tokens=max_tokens,
                temperature=0.7,
                top_p=0.8,
                top_k=20,
                min_p=0,
                stop=["###end###"]
            )
            

            return response['choices'][0]['text'].strip()

        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                print(f"   ⚠️ 記憶體不足 (重試 {retry_count + 1}/{self.max_retries})")
                self.aggressive_memory_cleanup()
                time.sleep(1)
                return self.generate_response(
                    prompt,
                    max_tokens=max(100, max_tokens - 50),
                    retry_count=retry_count + 1
                )
            else:
                raise e
