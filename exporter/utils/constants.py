#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
常量定义模块
"""

# 状态文件名
STATE_FILE = 'processing_state.json'

# 录像常量参数 
TYPICAL_VIDEO_LENGTH = 40  # 典型视频长度（秒）
TYPICAL_KILL_POSITION = 20  # 击杀通常出现在视频的位置（秒）

# 视频编码参数
GPU_ENCODE_PRESET = 'p7'  # NVENC预设
CPU_ENCODE_PRESET = 'fast'  # CPU预设
VIDEO_BITRATE = '8M'  # 视频码率
MAX_BITRATE = '10M'  # 最大码率
BUFFER_SIZE = '20M'  # 缓冲区大小
AUDIO_BITRATE = '192k'  # 音频码率
CRF_VALUE = '18'  # 恒定质量因子
CQ_VALUE = '20'  # NVENC质量值 