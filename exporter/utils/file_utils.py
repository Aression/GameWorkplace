#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
文件操作工具模块
"""

import os
import re
import json
from datetime import datetime, timedelta

from exporter.utils.constants import STATE_FILE

def convert_windows_path(path):
    """将Windows路径转换为Python程序能识别的路径"""
    return path.replace('\\', '/')

def parse_video_time(filename):
    """解析文件名中的时间信息
    
    支持多种常见模式:
    - War Thunder 2024.06.18 - 19.29.51.02.DVR.mp4  (旧格式)
    - War Thunder 2025.04.14 - 14.00.35.105.DVR.mp4 (新格式)
    - War Thunder 2025.04.12 - 20.01.55.06.DVR.mp4  (另一种格式)
    """
    # 提取基本日期和时间部分的通用模式
    base_pattern = r"War Thunder (\d{4}\.\d{2}\.\d{2}) - (\d{2}\.\d{2}\.\d{2})"
    base_match = re.match(base_pattern, filename)
    
    if not base_match:
        print(f"无法解析文件名基本格式: {filename}")
        return None
    
    # 获取日期和基本时间部分
    date_str, base_time = base_match.groups()
    
    # 尝试提取毫秒/ID部分（如果存在）
    ms_pattern = r"War Thunder \d{4}\.\d{2}\.\d{2} - \d{2}\.\d{2}\.\d{2}\.(\d+)\.DVR\.mp4"
    ms_match = re.match(ms_pattern, filename)
    
    ms_part = ms_match.group(1) if ms_match else ""
    
    try:
        # 将点替换为冒号来格式化时间
        time_part = base_time.replace('.', ':')
        
        # 构建完整的日期时间字符串
        if ms_part:
            # 确保毫秒部分不超过6位（Python的%f限制）
            ms_part = ms_part[:6]
            dt_str = f"{date_str} {time_part}.{ms_part}"
            dt_format = "%Y.%m.%d %H:%M:%S.%f"
        else:
            dt_str = f"{date_str} {time_part}"
            dt_format = "%Y.%m.%d %H:%M:%S"

        return datetime.strptime(dt_str, dt_format)
    except ValueError as e:
        # 解析失败时，尝试不使用毫秒部分
        try:
            dt_str = f"{date_str} {time_part}"
            dt_format = "%Y.%m.%d %H:%M:%S"
            return datetime.strptime(dt_str, dt_format)
        except ValueError:
            print(f"解析时间字符串失败 '{filename}': {e}")
            return None

def load_last_processed_time(state_file=None):
    """加载上次处理的最新视频时间"""
    # 使用自定义状态文件路径或默认值
    file_path = state_file or STATE_FILE
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                state = json.load(f)
                if 'last_processed_iso_time' in state:
                    # 从 ISO 格式字符串转换回 datetime 对象
                    return datetime.fromisoformat(state['last_processed_iso_time'])
    except (IOError, json.JSONDecodeError, ValueError) as e:
        print(f"无法加载处理状态 ({file_path}): {e}. 将处理所有视频。")
    return None

def save_last_processed_time(timestamp: datetime, state_file=None):
    """保存本次处理的最新视频时间"""
    # 使用自定义状态文件路径或默认值
    file_path = state_file or STATE_FILE
    try:
        # 将 datetime 对象转换为 ISO 格式字符串以便 JSON 序列化
        state = {'last_processed_iso_time': timestamp.isoformat()}
        with open(file_path, 'w') as f:
            json.dump(state, f, indent=4) # 使用 indent 美化输出
        print(f"处理状态已保存到 {file_path}")
    except IOError as e:
        print(f"无法保存处理状态 ({file_path}): {e}") 