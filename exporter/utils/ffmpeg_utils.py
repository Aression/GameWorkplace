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
    BUFFER_SIZE, AUDIO_BITRATE, CRF_VALUE, CQ_VALUE,
    REMOVE_DUPLICATE_FRAMES, DUPLICATE_THRESHOLD_HI, DUPLICATE_THRESHOLD_LO, DUPLICATE_FRACTION,
    FREEZE_DETECT_NOISE, FREEZE_DETECT_DURATION, SCENE_CHANGE_THRESHOLD
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
        # 检查可用的编码器
        available_encoders = check_encoder_availability()
        
        # 根据可用编码器选择命令
        if "h264_nvenc" in available_encoders:
            # 使用 NVIDIA H.264 编码
            print(f"  使用NVIDIA H.264硬件加速剪辑...")
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
        elif "hevc_nvenc" in available_encoders:
            # 使用 NVIDIA HEVC 编码 (H.265)
            print(f"  使用NVIDIA HEVC硬件加速剪辑...")
            cmd = [
                'ffmpeg', '-i', input_path,
                '-ss', str(start_time),
                '-t', str(duration),
                '-c:v', 'hevc_nvenc',
                '-preset', GPU_ENCODE_PRESET,
                '-rc', 'vbr',
                '-cq', CQ_VALUE,
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
        else:
            # 没有可用的GPU编码器，直接使用CPU
            raise ValueError("未检测到支持的GPU编码器，直接使用CPU编码")
        
        print(f"  尝试GPU剪辑: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8',
                     startupinfo=get_startupinfo())
        print(f"  GPU剪辑成功: {output_path}")
        return True
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f"GPU剪辑失败或不可用: {e}")
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
            print(f"CPU剪辑也失败了 {input_path}: {e_cpu}")
            return False
    except Exception as ex:
         print(f"剪辑过程中发生未知错误 {input_path}: {ex}")
         return False

def concat_videos(video_list, output_path, temp_dir=None, remove_duplicates=None):
    """使用ffmpeg合并视频，重新编码以确保兼容性，并可选择去除重复帧
    
    Args:
        video_list: 要合并的视频文件列表
        output_path: 输出文件路径
        temp_dir: 临时文件目录
        remove_duplicates: 是否去除重复帧，默认使用REMOVE_DUPLICATE_FRAMES常量设置
    """
    if not video_list:
        print("没有视频文件可供合并。")
        return False
    
    # 使用常量默认值，除非明确指定
    if remove_duplicates is None:
        remove_duplicates = REMOVE_DUPLICATE_FRAMES
    
    # 确定临时文件的目录
    if temp_dir is None:
        # 使用系统临时目录
        import tempfile
        temp_dir = tempfile.gettempdir()
    
    # 确保临时目录存在
    os.makedirs(temp_dir, exist_ok=True)
    
    # 创建唯一的临时文件名
    list_file = os.path.join(temp_dir, f'temp_list_{os.getpid()}_{int(time.time())}.txt')
    intermediate_file = None
    valid_inputs = []
    
    try:
        # 检查输入文件是否存在且非空
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

        # 首先合并视频到一个中间文件，不做去重处理
        intermediate_file = os.path.join(temp_dir, f'intermediate_{os.getpid()}_{int(time.time())}.mp4')
        
        # 基本的合并命令
        base_concat_cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', list_file,
            '-c', 'copy',  # 直接复制流，不重新编码
            '-y',
            intermediate_file
        ]
        
        print(f"第一步：简单合并视频到临时文件: {' '.join(base_concat_cmd)}")
        try:
            subprocess.run(base_concat_cmd, check=True, capture_output=True, text=True, encoding='utf-8',
                          startupinfo=get_startupinfo())
            print(f"简单合并成功: {intermediate_file}")
        except subprocess.CalledProcessError as e:
            print(f"简单合并失败: {e}")
            if os.path.exists(list_file): os.remove(list_file)
            return False
            
        # 然后，如果启用去重帧功能，对中间文件进行处理
        if remove_duplicates:
            print(f"第二步：执行去重帧处理")
            
            # 使用scene检测+基于哈希的去重方法
            # 1. 创建场景检测命令
            scene_filter = f"select='gt(scene,{SCENE_CHANGE_THRESHOLD})',metadata=print:file='{temp_dir}/scenes.txt'"
            frame_info_cmd = [
                'ffmpeg',
                '-i', intermediate_file,
                '-vf', scene_filter,
                '-f', 'null',
                '-'
            ]
            
            print(f"检测场景变化: {' '.join(frame_info_cmd)}")
            try:
                subprocess.run(frame_info_cmd, check=True, capture_output=True, text=True, encoding='utf-8',
                              startupinfo=get_startupinfo())
                print(f"场景检测完成")
            except subprocess.CalledProcessError as e:
                print(f"场景检测失败: {e}")
                # 继续执行，使用备用方法
            
            # 2. 使用较复杂的过滤器组合去重
            # - 使用freezedetect检测静止帧
            # - 使用mpdecimate检测连续相似帧
            # - 调整FPS确保平滑播放
            filter_complex = [
                '-filter_complex', 
                f'[0:v]freezedetect=n={FREEZE_DETECT_NOISE}:d={FREEZE_DETECT_DURATION},metadata=mode=print:file={temp_dir}/freeze.txt,mpdecimate=hi={DUPLICATE_THRESHOLD_HI}:lo={DUPLICATE_THRESHOLD_LO}:frac={DUPLICATE_FRACTION},setpts=N/FRAME_RATE/TB[v];[0:a]asetpts=N/SR/TB[a]',
                '-map', '[v]', 
                '-map', '[a]'
            ]
            
            # 检查可用编码器
            available_encoders = check_encoder_availability()
            encode_type = "CPU"  # 默认使用CPU
            
            # 构建命令
            if "h264_nvenc" in available_encoders:
                # 使用 NVIDIA H.264 编码
                print(f"使用NVIDIA H.264硬件加速编码...")
                cmd = [
                    'ffmpeg',
                    '-i', intermediate_file,
                ] + filter_complex + [
                    '-c:v', 'h264_nvenc',
                    '-preset', GPU_ENCODE_PRESET,
                    '-rc', 'vbr',
                    '-cq', CQ_VALUE,
                    '-b:v', VIDEO_BITRATE,
                    '-maxrate', MAX_BITRATE,
                    '-bufsize', BUFFER_SIZE,
                    '-c:a', 'aac',
                    '-b:a', AUDIO_BITRATE,
                    '-vsync', 'vfr',  # 可变帧率同步
                    '-y',
                    output_path
                ]
                encode_type = "NVIDIA H.264"
            elif "hevc_nvenc" in available_encoders:
                # 使用 NVIDIA HEVC 编码
                print(f"使用NVIDIA HEVC硬件加速编码...")
                cmd = [
                    'ffmpeg',
                    '-i', intermediate_file,
                ] + filter_complex + [
                    '-c:v', 'hevc_nvenc',
                    '-preset', GPU_ENCODE_PRESET,
                    '-rc', 'vbr',
                    '-cq', CQ_VALUE,
                    '-b:v', VIDEO_BITRATE,
                    '-maxrate', MAX_BITRATE,
                    '-bufsize', BUFFER_SIZE,
                    '-c:a', 'aac',
                    '-b:a', AUDIO_BITRATE,
                    '-vsync', 'vfr',  # 可变帧率同步
                    '-y',
                    output_path
                ]
                encode_type = "NVIDIA HEVC"
            else:
                # 使用CPU编码
                print(f"未检测到支持的硬件编码器，使用CPU编码...")
                cmd = [
                    'ffmpeg',
                    '-i', intermediate_file,
                ] + filter_complex + [
                    '-c:v', 'libx264',
                    '-preset', CPU_ENCODE_PRESET,
                    '-crf', CRF_VALUE,
                    '-b:v', VIDEO_BITRATE,
                    '-maxrate', MAX_BITRATE,
                    '-bufsize', BUFFER_SIZE,
                    '-c:a', 'aac',
                    '-b:a', AUDIO_BITRATE,
                    '-vsync', 'vfr',
                    '-y',
                    output_path
                ]
                encode_type = "CPU"
                
            print(f"使用{encode_type}进行去重编码: {' '.join(cmd)}")
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8',
                              startupinfo=get_startupinfo())
                print(f"{encode_type}去重编码成功: {output_path}")
                # 清理临时文件
                cleanup_temp_files(temp_dir, [
                    intermediate_file, list_file,
                    f"{temp_dir}/scenes.txt", f"{temp_dir}/freeze.txt"
                ])
                return True
            except subprocess.CalledProcessError as e:
                print(f"{encode_type}去重编码失败: {e}")
                
                # 如果使用的是GPU，尝试回退到CPU
                if encode_type != "CPU":
                    print(f"尝试使用CPU编码作为备选...")
                    try:
                        cpu_cmd = [
                            'ffmpeg',
                            '-i', intermediate_file,
                        ] + filter_complex + [
                            '-c:v', 'libx264',
                            '-preset', CPU_ENCODE_PRESET,
                            '-crf', CRF_VALUE,
                            '-b:v', VIDEO_BITRATE,
                            '-maxrate', MAX_BITRATE,
                            '-bufsize', BUFFER_SIZE,
                            '-c:a', 'aac',
                            '-b:a', AUDIO_BITRATE,
                            '-vsync', 'vfr',
                            '-y',
                            output_path
                        ]
                        print(f"尝试使用CPU进行去重编码: {' '.join(cpu_cmd)}")
                        subprocess.run(cpu_cmd, check=True, capture_output=True, text=True, encoding='utf-8',
                                      startupinfo=get_startupinfo())
                        print(f"CPU去重编码成功: {output_path}")
                        # 清理临时文件
                        cleanup_temp_files(temp_dir, [
                            intermediate_file, list_file,
                            f"{temp_dir}/scenes.txt", f"{temp_dir}/freeze.txt"
                        ])
                        return True
                    except subprocess.CalledProcessError as e_cpu:
                        print(f"CPU去重编码也失败了: {e_cpu}")
        
        # 如果没有启用去重或去重失败，使用简单的重编码方法
        try:
            print("尝试使用简单重编码...")
            
            # 检查可用编码器
            if not 'available_encoders' in locals():
                available_encoders = check_encoder_availability()
                
            # 选择编码器
            if "h264_nvenc" in available_encoders:
                print(f"使用NVIDIA H.264硬件加速编码...")
                simple_cmd = [
                    'ffmpeg',
                    '-i', intermediate_file if os.path.exists(intermediate_file) else list_file,
                    '-c:v', 'h264_nvenc',
                    '-preset', GPU_ENCODE_PRESET,
                    '-b:v', VIDEO_BITRATE,
                    '-c:a', 'aac',
                    '-b:a', AUDIO_BITRATE,
                    '-y',
                    output_path
                ]
            elif "hevc_nvenc" in available_encoders:
                print(f"使用NVIDIA HEVC硬件加速编码...")
                simple_cmd = [
                    'ffmpeg',
                    '-i', intermediate_file if os.path.exists(intermediate_file) else list_file,
                    '-c:v', 'hevc_nvenc',
                    '-preset', GPU_ENCODE_PRESET,
                    '-b:v', VIDEO_BITRATE, 
                    '-c:a', 'aac',
                    '-b:a', AUDIO_BITRATE,
                    '-y',
                    output_path
                ]
            else:
                print(f"使用CPU编码...")
                simple_cmd = [
                    'ffmpeg',
                    '-i', intermediate_file if os.path.exists(intermediate_file) else list_file,
                    '-c:v', 'libx264',
                    '-preset', CPU_ENCODE_PRESET,
                    '-crf', CRF_VALUE,
                    '-c:a', 'aac',
                    '-b:a', AUDIO_BITRATE,
                    '-y',
                    output_path
                ]
                
            print(f"简单重编码命令: {' '.join(simple_cmd)}")
            subprocess.run(simple_cmd, check=True, capture_output=True, text=True, encoding='utf-8',
                          startupinfo=get_startupinfo())
            print(f"简单重编码成功: {output_path}")
            return True
        except Exception as e:
            print(f"所有编码方法都失败了: {e}")
            return False
        finally:
            # 清理临时文件
            cleanup_temp_files(temp_dir, [
                intermediate_file, list_file,
                f"{temp_dir}/scenes.txt", f"{temp_dir}/freeze.txt"
            ])
            
    except Exception as e:
        print(f"合并视频时发生错误: {e}")
        cleanup_temp_files(temp_dir, [list_file, intermediate_file] if intermediate_file else [list_file])
        return False

def cleanup_temp_files(temp_dir, file_list):
    """清理临时文件
    
    Args:
        temp_dir: 临时文件目录
        file_list: 临时文件列表
    """
    for temp_file in file_list:
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                print(f"清理临时文件: {temp_file}")
        except Exception as e_rm:
            print(f"警告：无法删除临时文件 {temp_file}: {e_rm}")
    return False

def check_encoder_availability():
    """检查系统中可用的编码器
    
    Returns:
        List[str]: 可用编码器列表
    """
    available_encoders = []
    
    try:
        # 运行FFmpeg命令以获取所有可用编码器
        cmd = ["ffmpeg", "-hide_banner", "-encoders"]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                              startupinfo=get_startupinfo())
        
        # 检查输出中的各种编码器
        output = result.stdout
        
        # 检查常用的GPU编码器
        encoders_to_check = [
            "h264_nvenc",   # NVIDIA H.264
            "hevc_nvenc",   # NVIDIA H.265
            "av1_nvenc",    # NVIDIA AV1
            "h264_qsv",     # Intel Quick Sync H.264
            "hevc_qsv",     # Intel Quick Sync H.265
            "h264_amf",     # AMD AMF H.264
            "hevc_amf"      # AMD AMF H.265
        ]
        
        # 从输出中检查每个编码器
        for encoder in encoders_to_check:
            if encoder in output:
                available_encoders.append(encoder)
        
        print(f"检测到的可用硬件编码器: {', '.join(available_encoders) if available_encoders else '无'}")
        
    except Exception as e:
        print(f"检查编码器时出错: {e}")
    
    return available_encoders 