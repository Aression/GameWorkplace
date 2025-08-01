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

# 视频编码参数 - 设置为无损或最高质量
GPU_ENCODE_PRESET = 'p7'  # NVENC最高质量预设
CPU_ENCODE_PRESET = 'veryslow'  # CPU最高质量预设
VIDEO_BITRATE = '0'  # 不限制码率
MAX_BITRATE = '0'  # 不限制最大码率
BUFFER_SIZE = '0'  # 不限制缓冲区大小
AUDIO_BITRATE = 'copy'  # 保持原始音频质量
CRF_VALUE = '0'  # 最高质量（无损）
CQ_VALUE = '0'  # 最高质量（无损）

# 编码器设置
ENFORCE_CPU_ENCODE = False  # 强制使用CPU编码
DEBUG_GPU_ENCODER = True  # GPU编码调试模式

# 去重设置 
REMOVE_DUPLICATE_FRAMES = True  # 是否启用去重帧功能
SCENE_CHANGE_THRESHOLD = 0.3  # 场景变化检测阈值（0-1，越大越不敏感）
FREEZE_DETECT_NOISE = 0.001  # 冻结帧检测噪声阈值（越小越敏感）
FREEZE_DETECT_DURATION = 2  # 冻结帧最小持续时间（秒）
DUPLICATE_THRESHOLD_HI = 64  # 高阈值：像素块差异阈值
DUPLICATE_THRESHOLD_LO = 32  # 低阈值：整帧差异阈值
DUPLICATE_FRACTION = 0.33  # 相似帧占比阈值

# GPU加速设置
USE_GPU_HASH = True  # 是否使用GPU加速哈希计算
GPU_HASH_SIZE = 16  # 感知哈希大小，越大越精确但更耗资源
HASH_THRESHOLD = 5  # 哈希差异阈值，越小越严格
FRAME_SAMPLE_RATE = 10  # 视频帧采样率，每N帧采样一次
MIN_DUPLICATE_LENGTH = 1.0  # 最小重复片段长度（秒）
ENABLE_SEGMENT_DEDUP = True  # 是否启用片段级去重
ENABLE_FRAME_DEDUP = True  # 是否启用帧级去重 