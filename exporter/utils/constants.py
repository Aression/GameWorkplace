#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
常量定义模块
"""

# 状态文件名
STATE_FILE = 'processing_state.json'

# 录像参数
TYPICAL_VIDEO_LENGTH = 40  # 典型视频长度（秒）
TYPICAL_KILL_POSITION = 20  # 击杀通常出现在视频的位置（秒）
KILL_LEAD_TIME = 15  # 击杀前保留时间（秒）
KILL_TAIL_TIME = 5  # 击杀后保留时间（秒）

# 视频编码参数
GPU_ENCODE_PRESET = 'p7'  # NVENC预设
CPU_ENCODE_PRESET = 'fast'  # CPU预设
VIDEO_BITRATE = '8M'  # 视频码率
MAX_BITRATE = '10M'  # 最大码率
BUFFER_SIZE = '20M'  # 缓冲区大小
AUDIO_BITRATE = '192k'  # 音频码率
CRF_VALUE = '18'  # 恒定质量因子
CQ_VALUE = '20'  # NVENC质量值

# 去重设置 
REMOVE_DUPLICATE_FRAMES = True  # 是否启用去重帧功能
SCENE_CHANGE_THRESHOLD = '0.1'  # 场景变化检测阈值（0-1，越大越不敏感）
FREEZE_DETECT_NOISE = '0.001'  # 冻结帧检测噪声阈值（越小越敏感）
FREEZE_DETECT_DURATION = '2'  # 冻结帧最小持续时间（秒）
DUPLICATE_THRESHOLD_HI = '192'  # 高阈值：像素块差异阈值
DUPLICATE_THRESHOLD_LO = '64'  # 低阈值：整帧差异阈值
DUPLICATE_FRACTION = '0.1'  # 相似帧占比阈值

# GPU加速哈希计算设置
USE_GPU_HASH = True  # 是否使用GPU加速哈希计算
GPU_HASH_SIZE = 16  # 感知哈希大小，越大越精确但更耗资源
HASH_THRESHOLD = 5  # 哈希差异阈值，越小越严格
FRAME_SAMPLE_RATE = 10  # 视频帧采样率，每N帧采样一次
MIN_DUPLICATE_LENGTH = 1.0  # 最小重复片段长度（秒）
ENABLE_SEGMENT_DEDUP = True  # 是否启用片段级去重
ENABLE_FRAME_DEDUP = True  # 是否启用帧级去重 