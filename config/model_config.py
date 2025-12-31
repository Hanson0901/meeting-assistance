#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模型配置文件
統一管理所有功能使用的模型路徑和參數
"""

class ModelConfig:
    """模型配置管理類"""
    
    # 基礎路徑
    BASE_MODEL_PATH = "/home/csie/"
    
    # 各功能使用的模型配置
    MODELS = {
        'people': {
            'path': f'{BASE_MODEL_PATH}qwen3-4b-instruct-2507-q8_0.gguf',
            'max_tokens': 200,
            'temperature': 0.7,
            'top_p': 0.8,
            'top_k': 20,
        },
        'keypoints': {
            'path': f'{BASE_MODEL_PATH}qwen3-4b-instruct-2507-q8_0.gguf',
            'max_tokens': 200,
            'temperature': 0.7,
            'top_p': 0.8,
            'top_k': 20,
        },
        'decisions': {
            'path': f'{BASE_MODEL_PATH}qwen3-4b-instruct-2507-q8_0.gguf',
            'max_tokens': 150,
            'temperature': 0.5,
            'top_p': 0.5,
            'top_k': 20,
        },
        'actions': {
            'path': f'{BASE_MODEL_PATH}qwen3-4b-instruct-2507-q8_0.gguf',
            'max_tokens': 300,
            'temperature': 0.2,
            'top_p': 0.4,
            'top_k': 40,
            'repeat_penalty': 1.3,


        },
        'summary': {
            'path': f'{BASE_MODEL_PATH}qwen3-4b-instruct-2507-q8_0.gguf',
            'max_tokens': 1800,
            'temperature': 0.7,
            'top_p': 0.95,
            'min_p': 0.05,
            'top_k': 20,
        },
    }
    
    # LLM 通用配置
    LLAMA_CONFIG = {
        'n_gpu_layers': 0,
        'n_threads': 4,
        'n_ctx': 8192,  # 16GB 版本
        'verbose': False,
    }
    
    # 記憶體配置
    MEMORY_CONFIG = {
        'threshold_gb': 10.0,
        'batch_size': 1,
        'max_retries': 3,
    }
    
    @classmethod
    def get_model_config(cls, extractor_type):
        """獲取指定功能的模型配置"""
        if extractor_type not in cls.MODELS:
            raise ValueError(f"未知的提取器類型: {extractor_type}")
        return cls.MODELS[extractor_type]
    
    @classmethod
    def update_model_path(cls, extractor_type, new_path):
        """更新指定功能的模型路徑"""
        if extractor_type in cls.MODELS:
            cls.MODELS[extractor_type]['path'] = new_path
        else:
            raise ValueError(f"未知的提取器類型: {extractor_type}")