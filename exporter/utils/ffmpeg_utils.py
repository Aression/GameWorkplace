#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
FFmpeg视频处理工具模块
"""

import os
import time
import subprocess
import platform
from datetime import datetime

from exporter.utils.constants import (
    GPU_ENCODE_PRESET, CPU_ENCODE_PRESET, VIDEO_BITRATE, MAX_BITRATE,
    BUFFER_SIZE, AUDIO_BITRATE, CRF_VALUE, CQ_VALUE
)

def get_startupinfo():
    """根据平台返回适当的startupinfo对象，用于隐藏命令行窗口"""
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        return startupinfo
    return None

def get_video_duration(video_path):
    """使用 ffprobe 获取视频时长（秒）"""
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', video_path
        ]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, 
                               startupinfo=get_startupinfo())
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        print(f"无法获取视频时长 {video_path}: {e}")
        # 返回一个默认值或引发异常可能更好，这里返回 0 以便后续逻辑处理
        return 0 

def cut_video(input_path, output_path, start_time, duration):
    """使用ffmpeg剪切视频，使用GPU加速，失败则回退CPU"""
    if duration <= 0:
        print(f"剪辑时间无效 (<=0): {duration} for {input_path}. 跳过剪辑。")
        return False
    try:
        cmd = [
            'ffmpeg', '-i', input_path,
            '-ss', str(start_time),
            '-t', str(duration),
            '-c:v', 'h264_nvenc',
            '-preset', GPU_ENCODE_PRESET,
            '-rc', 'vbr',
            '-cq', CQ_VALUE,
            '-b:v', VIDEO_BITRATE,
            '-maxrate', MAX_BITRATE,
            '-bufsize', BUFFER_SIZE,
            '-c:a', 'aac',
            '-b:a', AUDIO_BITRATE,
            '-map_metadata', '-1', # 移除元数据，避免潜在合并问题
            '-avoid_negative_ts', 'make_zero', # 尝试解决时间戳问题
            '-y',
            output_path
        ]
        print(f"  尝试GPU剪辑: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8',
                     startupinfo=get_startupinfo())
        print(f"  GPU剪辑成功: {output_path}")
        return True
    except subprocess.CalledProcessError as e_gpu:
        print(f"GPU剪辑失败 {input_path}: {e_gpu.stderr}")
        print("  尝试使用CPU编码...")
        try:
            cmd_cpu = [
                'ffmpeg', '-i', input_path,
                '-ss', str(start_time),
                '-t', str(duration),
                '-c:v', 'libx264',
                '-preset', CPU_ENCODE_PRESET,
                '-crf', CRF_VALUE,
                '-b:v', VIDEO_BITRATE,
                '-maxrate', MAX_BITRATE,
                '-bufsize', BUFFER_SIZE,
                '-c:a', 'aac',
                '-b:a', AUDIO_BITRATE,
                '-map_metadata', '-1',
                '-avoid_negative_ts', 'make_zero',
                '-y',
                output_path
            ]
            print(f"  尝试CPU剪辑: {' '.join(cmd_cpu)}")
            subprocess.run(cmd_cpu, check=True, capture_output=True, text=True, encoding='utf-8',
                         startupinfo=get_startupinfo())
            print(f"  CPU剪辑成功: {output_path}")
            return True
        except subprocess.CalledProcessError as e_cpu:
            print(f"CPU剪辑也失败了 {input_path}: {e_cpu.stderr}")
            return False
    except Exception as ex:
         print(f"剪辑过程中发生未知错误 {input_path}: {ex}")
         return False

def concat_videos(video_list, output_path, temp_dir=None):
    """使用ffmpeg合并视频，重新编码以确保兼容性"""
    if not video_list:
        print("没有视频文件可供合并。")
        return False
    
    # 确定临时文件的目录
    if temp_dir is None:
        # 使用系统临时目录
        import tempfile
        temp_dir = tempfile.gettempdir()
    
    # 确保临时目录存在
    os.makedirs(temp_dir, exist_ok=True)
    
    # 创建唯一的临时文件名
    list_file = os.path.join(temp_dir, f'temp_list_{os.getpid()}_{int(time.time())}.txt')
    
    try:
        # 检查输入文件是否存在且非空
        valid_inputs = []
        with open(list_file, 'w', encoding='utf-8') as f:
            for video in video_list:
                if os.path.exists(video) and os.path.getsize(video) > 100: # 增加一个最小大小检查
                    # 先处理路径，再放入 f-string
                    normalized_path = os.path.abspath(video).replace('\\', '/')
                    f.write(f"file '{normalized_path}'\n")
                    valid_inputs.append(video)
                else:
                    print(f"警告：跳过无效或过小的临时文件 {video}")

        if not valid_inputs:
            print("没有有效的临时文件可供合并。")
            if os.path.exists(list_file): os.remove(list_file)
            return False

        # 使用ffmpeg合并视频，重新编码
        cmd_gpu = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0', # 允许非安全的路径（虽然我们用了绝对路径）
            '-i', list_file,
            '-c:v', 'h264_nvenc',
            '-preset', GPU_ENCODE_PRESET,
            '-rc', 'vbr',
            '-cq', CQ_VALUE,
            '-b:v', VIDEO_BITRATE,
            '-maxrate', MAX_BITRATE,
            '-bufsize', BUFFER_SIZE,
            '-c:a', 'aac',
            '-b:a', AUDIO_BITRATE,
            '-vsync', 'vfr', # 可变帧率同步，尝试解决时间戳/重复问题
            '-map_metadata', '-1', # 移除元数据
            '-y',
            output_path
        ]
        
        try:
            print(f"尝试使用GPU合并: {' '.join(cmd_gpu)}")
            subprocess.run(cmd_gpu, check=True, capture_output=True, text=True, encoding='utf-8',
                         startupinfo=get_startupinfo())
            print(f"GPU合并成功: {output_path}")
            # 合并成功后删除临时文件
            if os.path.exists(list_file): os.remove(list_file)
            for temp_file in valid_inputs:
                 try:
                     if os.path.exists(temp_file): os.remove(temp_file)
                 except Exception as e_rm:
                     print(f"警告：无法删除临时文件 {temp_file}: {e_rm}")
            return True
        except subprocess.CalledProcessError as e_gpu:
            print(f"GPU合并失败: {e_gpu.stderr}")
            print("尝试使用CPU合并...")
            cmd_cpu = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',
                '-i', list_file,
                '-c:v', 'libx264',
                '-preset', CPU_ENCODE_PRESET,
                '-crf', CRF_VALUE,
                '-b:v', VIDEO_BITRATE,
                '-maxrate', MAX_BITRATE,
                '-bufsize', BUFFER_SIZE,
                '-c:a', 'aac',
                '-b:a', AUDIO_BITRATE,
                '-vsync', 'vfr',
                '-map_metadata', '-1',
                '-y',
                output_path
            ]
            try:
                 print(f"尝试使用CPU合并: {' '.join(cmd_cpu)}")
                 subprocess.run(cmd_cpu, check=True, capture_output=True, text=True, encoding='utf-8',
                               startupinfo=get_startupinfo())
                 print(f"使用CPU合并成功: {output_path}")
                 # 合并成功后删除临时文件
                 if os.path.exists(list_file): os.remove(list_file)
                 for temp_file in valid_inputs:
                      try:
                          if os.path.exists(temp_file): os.remove(temp_file)
                      except Exception as e_rm:
                          print(f"警告：无法删除临时文件 {temp_file}: {e_rm}")
                 return True
            except subprocess.CalledProcessError as e_cpu:
                print(f"CPU合并也失败了: {e_cpu.stderr}")
                # 合并失败时，保留临时文件以便调试
                print(f"  保留临时列表文件: {list_file}")
                print(f"  保留临时视频文件: {valid_inputs}")
                return False
            except Exception as ex_cpu:
                 print(f"CPU合并过程中发生未知错误: {ex_cpu}")
                 if os.path.exists(list_file): os.remove(list_file) # 尝试清理列表文件
                 return False
    except Exception as e:
        print(f"合并过程中发生错误: {str(e)}")
        if 'list_file' in locals() and os.path.exists(list_file):
            os.remove(list_file) # 尝试清理列表文件
        return False 