#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视频处理核心模块

实现了基于区间合并算法的视频处理逻辑，相比传统去重方式有以下优势：
1. 计算目标剪辑区间：对每次击杀取前后范围而非整段
2. 合并重叠区间：减少不必要的切换
3. 最小化源视频选择：优先单视频覆盖，必要时多视频拼接
4. FFmpeg一体化处理：一次性完成所有裁剪和拼接
"""

import os
import subprocess
import platform
from datetime import datetime, timedelta
import time

from exporter.utils.constants import (
    TYPICAL_VIDEO_LENGTH, TYPICAL_KILL_POSITION,
    GPU_ENCODE_PRESET, CPU_ENCODE_PRESET, VIDEO_BITRATE, MAX_BITRATE,
    BUFFER_SIZE, AUDIO_BITRATE, CRF_VALUE, CQ_VALUE,
    KILL_LEAD_TIME, KILL_TAIL_TIME, ENFORCE_CPU_ENCODE
)
from exporter.utils.file_utils import (
    parse_video_time, load_last_processed_time, save_last_processed_time
)
from exporter.utils.ffmpeg_utils import (
    get_video_duration, cut_video, get_startupinfo, check_encoder_availability, get_video_info
)
from exporter.core.models import TimeSegment

# 视频素材覆盖范围
VIDEO_COVER_RANGE = 20  # 视频素材通常以击杀前后 20 秒范围录制

def _is_valid_datetime(*times):
    """检查所有时间参数是否都是datetime类型"""
    return all(isinstance(t, datetime) for t in times)

def process_videos(input_dir, output_dir, lead=10, tail=2, threshold=30, min_kills=2, 
                  progress_callback=None, state_file=None, temp_dir=None, is_running=None):
    """处理视频文件，识别连杀片段并导出
    
    Args:
        input_dir: 输入目录，包含War Thunder视频文件
        output_dir: 输出目录，保存处理后的视频
        lead: 击杀前保留时间（秒），用于连杀识别
        tail: 击杀后保留时间（秒），用于连杀识别
        threshold: 连杀时间阈值（秒）
        min_kills: 最少击杀数
        progress_callback: 进度回调函数
        state_file: 状态文件路径
        temp_dir: 临时文件目录
        is_running: 运行状态检查函数
        
    Returns:
        int: 成功导出的视频数量
    """
    # 1. 初始化处理环境
    temp_dir = _init_processing_environment(output_dir, temp_dir)
    
    # 2. 扫描并加载视频文件信息
    all_files_info, skipped_count, latest_time = _scan_video_files(
        input_dir, state_file, progress_callback, is_running
    )
    
    if not all_files_info:
        print("未找到需要处理的新视频文件。")
        return 0
    
    # 3. 识别连杀片段（使用传入的lead和tail参数）
    valid_segments = _identify_killstreaks(all_files_info, lead, tail, threshold, min_kills, is_running)
    
    # 4. 使用区间合并算法处理并导出视频片段（使用常量定义的lead和tail参数）
    successful_exports = _process_killstreak_segments(
        valid_segments, all_files_info, output_dir, temp_dir, 
        KILL_LEAD_TIME, KILL_TAIL_TIME, progress_callback, is_running
    )
    
    # 5. 完成处理并更新状态
    _finalize_processing(successful_exports, latest_time, state_file, all_files_info)
    
    return successful_exports


def _init_processing_environment(output_dir, temp_dir=None):
    """初始化处理环境，设置临时目录"""
    cache_dir = os.path.join(output_dir, "temp")
    os.makedirs(cache_dir, exist_ok=True)
    
    if not temp_dir:
        temp_dir = cache_dir
    
    print(f"临时文件将保存在: {temp_dir}")
    return temp_dir


def _scan_video_files(input_dir, state_file, progress_callback=None, is_running=None):
    """扫描视频文件并加载信息"""
    last_processed_time = load_last_processed_time(state_file)
    print(f"上次处理到时间: {last_processed_time}" if last_processed_time else "首次处理或未找到记录，将处理所有视频。")
    
    all_files_info = []
    skipped_count = 0
    print(f"扫描输入目录: {input_dir}")
    
    # 扫描所有MP4文件
    mp4_files = [f for f in os.listdir(input_dir) if f.endswith(".mp4")]
    total_files = len(mp4_files)
    processed_files = 0
    
    # 更新初始进度
    if progress_callback:
        progress_callback(0, total_files, "开始扫描视频文件...")
    
    latest_video_time = None
    
    for fname in mp4_files:
        # 检查是否应该停止处理
        if is_running is not None and not is_running():
            print("用户取消处理，正在退出...")
            return [], 0, None
            
        processed_files += 1
        full_path = os.path.join(input_dir, fname)
        start_time = parse_video_time(fname)
        
        if not start_time:
            print(f"  跳过: 无法解析时间 {fname}")
            continue
        
        # 如果设置了上次处理时间，则跳过旧视频
        if last_processed_time and start_time <= last_processed_time:
            skipped_count += 1
            continue # 跳过这个文件

        # 使用 ffprobe 获取实际视频时长
        duration_sec = get_video_duration(full_path)
        if duration_sec <= 0:
            print(f"  跳过: 无法获取有效时长 {fname}")
            continue
        
        end_time = start_time + timedelta(seconds=duration_sec)
        # 简化假设：击杀时间在视频中间位置
        kill_time = start_time + timedelta(seconds=min(TYPICAL_KILL_POSITION, duration_sec / 2))

        all_files_info.append({
            "path": full_path,
            "start": start_time,
            "kill": kill_time,
            "end": end_time,
            "filename": fname,
            "duration": duration_sec
        })
        
        # 更新最新处理视频时间
        if not latest_video_time or start_time > latest_video_time:
            latest_video_time = start_time
        
        # 更新扫描进度
        if progress_callback:
            progress_callback(processed_files, total_files, f"扫描: {fname}")

    print(f"扫描完成: 找到 {len(all_files_info)} 个新视频文件，跳过 {skipped_count} 个已处理或过早的视频。")
    return all_files_info, skipped_count, latest_video_time


def _identify_killstreaks(video_files, lead, tail, threshold, min_kills, is_running=None):
    """识别连杀片段"""
    if not video_files:
        return []
        
    # 按 kill 时间排序
    videos = sorted(video_files, key=lambda x: x["kill"])
    
    # 为每个击杀创建一个时间段（击杀前lead秒到击杀后tail秒）
    kill_segments = []
    for video in videos:
        # 检查是否应该停止处理
        if is_running is not None and not is_running():
            return []
            
        kill_time = video["kill"]
        segment_start = kill_time - timedelta(seconds=lead)
        segment_end = kill_time + timedelta(seconds=tail)
        segment = TimeSegment(segment_start, segment_end, video)
        kill_segments.append(segment)
    
    # 合并间隔小于阈值的时间段
    kill_segments.sort(key=lambda x: x.start_time)
    merged_segments = [kill_segments[0]]
    
    for i in range(1, len(kill_segments)):
        current = kill_segments[i]
        last = merged_segments[-1]
        
        # 计算时间间隔
        time_gap = (current.start_time - last.end_time).total_seconds()
        
        # 如果间隔小于阈值，合并段
        if time_gap <= threshold:
            last.extend(current)
        else:
            merged_segments.append(current)
    
    # 过滤掉击杀次数不足的段
    valid_segments = [seg for seg in merged_segments if len(seg.kill_times) >= min_kills]
    
    print(f"识别出 {len(valid_segments)} 个连杀时间段 (最少 {min_kills} 次击杀，间隔 <= {threshold} 秒)")
    return valid_segments


def _process_killstreak_segments(valid_segments, videos, output_dir, temp_dir, 
                               lead, tail, progress_callback=None, is_running=None):
    """处理每个连杀片段并导出视频
    
    使用区间合并算法：
    1. 计算所有击杀的目标剪辑区间 [Tᵢ - lead, Tᵢ + tail]
    2. 合并重叠区间
    3. 为每个区间选择最少数量的源视频
    4. 使用FFmpeg一次性完成所有裁剪和拼接操作
    """
    if not valid_segments:
        return 0
        
    successful_exports = 0
    segment_count = len(valid_segments)
    
    # 添加总处理进度计数
    total_processing_steps = segment_count * 2  # 每个片段需要两个步骤：合并区间和导出视频
    current_step = 0
    
    for idx, segment in enumerate(valid_segments, 1):
        # 检查是否应该停止处理
        if is_running is not None and not is_running():
            return successful_exports
            
        # 更新进度 - 合并区间阶段
        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_processing_steps, f"分析连杀片段 {idx}/{segment_count} (击杀数: {len(segment.kill_times)})")
        
        print(f"\n处理第 {idx} 个连杀片段 (击杀数: {len(segment.kill_times)})")
        
        # 1. 计算每个击杀的目标剪辑区间
        kill_times_sorted = sorted(segment.kill_times)
        kill_intervals = []
        
        for kill_time in kill_times_sorted:
            interval_start = kill_time - timedelta(seconds=lead)
            interval_end = kill_time + timedelta(seconds=tail)
            kill_intervals.append((interval_start, interval_end))
            
        print(f"  击杀时间点: {kill_times_sorted}")
        print(f"  计算了 {len(kill_intervals)} 个击杀区间")
        
        # 2. 合并重叠的目标区间
        merged_intervals = []
        if kill_intervals:
            merged_intervals.append(kill_intervals[0])
            
            for current_interval in kill_intervals[1:]:
                current_start, current_end = current_interval
                last_start, last_end = merged_intervals[-1]
                
                # 如果当前区间与上一个合并区间重叠，合并它们
                if current_start <= last_end:
                    # 更新结束时间为较晚的结束时间
                    merged_intervals[-1] = (last_start, max(last_end, current_end))
                else:
                    # 没有重叠，添加为新区间
                    merged_intervals.append(current_interval)
        
        print(f"  合并后共 {len(merged_intervals)} 个区间")
        
        # 3. 生成输出文件名
        timestamp_str = kill_times_sorted[0].strftime("%Y%m%d_%H%M%S")
        kills_count = len(kill_times_sorted)
        output_filename = f"连杀_{kills_count}杀_{timestamp_str}.mp4"
        final_output_path = os.path.join(output_dir, output_filename)
        
        # 4. 准备过滤器脚本文件
        filter_script_path = os.path.join(temp_dir, f"filter_script_{timestamp_str}.txt")
        
        # 5. 处理区间
        print(f"  输出文件: {final_output_path}")
        
        # 对于只有一个区间的情况，尝试使用单视频覆盖
        if len(merged_intervals) == 1:
            result = _process_single_interval(
                merged_intervals[0], videos, final_output_path, temp_dir, is_running
            )
            
            if result:
                successful_exports += 1
                # 更新进度 - 导出阶段完成
                current_step += 1
                if progress_callback:
                    progress_callback(current_step, total_processing_steps, f"导出完成 {idx}/{segment_count} (文件: {output_filename})")
                continue
        
        # 多区间或单区间但无法单视频覆盖的情况
        result = _process_multiple_intervals(
            merged_intervals, videos, final_output_path, temp_dir, 
            filter_script_path, progress_callback, is_running
        )
        if result:
            successful_exports += 1
        
        # 更新进度 - 导出阶段完成，无论成功与否
        current_step += 1
        if progress_callback:
            progress_callback(current_step, total_processing_steps, 
                             f"导出{'成功' if result else '失败'} {idx}/{segment_count} (文件: {output_filename})")
    
    # 更新最终进度
    if progress_callback:
        progress_callback(total_processing_steps, total_processing_steps, f"处理完成，成功导出 {successful_exports}/{segment_count} 个片段")
        
    return successful_exports

def _process_single_interval(interval, videos, output_path, temp_dir, is_running=None):
    """处理单个时间区间，优先使用无损复制，失败则尝试高质量编码
    
    尝试找到能够完全覆盖该区间的单个视频，并剪辑出对应片段
    
    Args:
        interval: 要处理的时间区间, (start_time, end_time)的元组
        videos: 可用视频列表，每个视频是包含路径、开始时间、结束时间的字典
        output_path: 输出文件路径
        temp_dir: 临时文件目录
        is_running: 运行状态检查函数
        
    Returns:
        bool: 是否成功找到并处理了区间
    """
    interval_start, interval_end = interval
    interval_duration = (interval_end - interval_start).total_seconds()
    
    print(f"尝试单视频处理区间: {interval_start} -> {interval_end} (时长: {interval_duration:.2f}秒)")
    
    # 检查是否有视频可以完全覆盖该区间
    for video in videos:
        # 检查是否应该停止处理
        if is_running is not None and not is_running():
            return False
            
        video_start = video["start"]
        video_end = video["end"]
        
        # 确保时间类型一致
        if not all(isinstance(t, datetime) for t in [video_start, video_end, interval_start, interval_end]):
            continue
        
        # 如果视频完全覆盖了区间
        if video_start <= interval_start and video_end >= interval_end:
            print(f"  找到覆盖区间的视频: {video['filename']}")
            
            # 计算在原视频中的相对位置
            rel_start = (interval_start - video_start).total_seconds()
            duration = interval_duration
            
            # 首先尝试无损复制
            try:
                print(f"  尝试无损复制剪辑...")
                copy_cmd = [
                    'ffmpeg',
                    '-i', video["path"],
                    '-ss', str(rel_start),
                    '-t', str(duration),
                    '-c', 'copy',  # 直接复制流，不重新编码
                    '-avoid_negative_ts', 'make_zero',
                    '-y',
                    output_path
                ]
                
                print(f"  执行无损复制: {' '.join(copy_cmd)}")
                subprocess.run(copy_cmd, check=True, capture_output=True, text=True, encoding='utf-8',
                             startupinfo=get_startupinfo())
                print(f"  无损复制成功: {output_path}")
                return True
            except subprocess.CalledProcessError as e:
                print(f"  无损复制失败，尝试高质量编码: {e}")
            
            # 如果无损复制失败，尝试高质量编码
            # 创建过滤器脚本
            filter_script_path = os.path.join(temp_dir, f'filter_{os.getpid()}_{int(time.time())}.txt')
            
            # 获取视频信息（分辨率和码率）
            video_info = get_video_info(video["path"])
            if not video_info:
                print(f"  无法获取视频信息，使用默认设置")
                video_width = None
                video_height = None
                video_bitrate = None
            else:
                video_width = video_info.get('width')
                video_height = video_info.get('height')
                video_bitrate = video_info.get('bitrate')
                print(f"  获取到视频信息: 分辨率={video_width}x{video_height}, 码率={video_bitrate/1000 if video_bitrate else 'unknown'}kbps")
            
            # 如果视频尺寸无效，则忽略分辨率设置
            if not video_width or not video_height:
                video_width = None
                video_height = None
                
            # 构建FFmpeg过滤器脚本
            filter_parts = []
            filter_parts.append(f"[0:v]trim=start={rel_start}:duration={duration},setpts=PTS-STARTPTS[v]")
            filter_parts.append(f"[0:a]atrim=start={rel_start}:duration={duration},asetpts=PTS-STARTPTS[a]")
            
            # 写入过滤器脚本
            with open(filter_script_path, 'w', encoding='utf-8') as f:
                f.write(";\n".join(filter_parts))
            
            # 如果已经有成功使用的编码器，直接使用它
            if hasattr(_process_single_interval, '_successful_encoder'):
                encoder_name = _process_single_interval._successful_encoder
                print(f"  使用之前成功的编码器: {encoder_name}")
                
                if encoder_name == "h264_nvenc":
                    try:
                        # 获取可用的编码器
                        available_encoders = check_encoder_availability()
                        if "h264_nvenc" not in available_encoders:
                            raise ValueError("NVIDIA H.264编码器不可用")
                            
                        # 使用GPU H.264编码
                        print("  使用NVIDIA H.264硬件加速...")
                        cmd = [
                            'ffmpeg',
                            '-i', video["path"],
                            '-filter_complex_script', filter_script_path,
                            '-map', '[v]',
                            '-map', '[a]'
                        ]
                        
                        # 添加视频尺寸参数（如果有效）
                        if video_width and video_height:
                            cmd.extend(['-s', f'{video_width}x{video_height}'])
                            
                        # 添加编码器和参数
                        cmd.extend([
                            '-c:v', 'h264_nvenc',
                            '-preset', GPU_ENCODE_PRESET,
                            '-rc', 'vbr',
                            '-cq', CQ_VALUE,
                            '-b:v', VIDEO_BITRATE,
                            '-maxrate', MAX_BITRATE,
                            '-bufsize', BUFFER_SIZE,
                            '-c:a', 'copy',  # 保持原始音频
                            '-vsync', 'vfr',
                            '-y',
                            output_path
                        ])
                        
                        print(f"  执行高质量编码: {' '.join(cmd)}")
                        process = subprocess.run(cmd, check=True, capture_output=True, 
                                               text=True, encoding='utf-8', startupinfo=get_startupinfo())
                        
                        print(f"  高质量编码成功: {output_path}")
                        return True
                    except Exception as e:
                        print(f"  使用已知编码器失败，尝试其他方法: {e}")
                        # 继续使用其他方法
                
                elif encoder_name == "hevc_nvenc":
                    try:
                        # 同样的逻辑，但使用HEVC编码器
                        available_encoders = check_encoder_availability()
                        if "hevc_nvenc" not in available_encoders:
                            raise ValueError("NVIDIA HEVC编码器不可用")
                            
                        print("  使用NVIDIA HEVC硬件加速...")
                        cmd = [
                            'ffmpeg',
                            '-i', video["path"],
                            '-filter_complex_script', filter_script_path,
                            '-map', '[v]',
                            '-map', '[a]'
                        ]
                        
                        # 添加视频尺寸参数（如果有效）
                        if video_width and video_height:
                            cmd.extend(['-s', f'{video_width}x{video_height}'])
                            
                        # 添加编码器和参数
                        cmd.extend([
                            '-c:v', 'hevc_nvenc',
                            '-preset', GPU_ENCODE_PRESET,
                            '-rc', 'vbr',
                            '-cq', CQ_VALUE,
                            '-b:v', VIDEO_BITRATE,
                            '-maxrate', MAX_BITRATE,
                            '-bufsize', BUFFER_SIZE,
                            '-c:a', 'copy',  # 保持原始音频
                            '-vsync', 'vfr',
                            '-y',
                            output_path
                        ])
                        
                        print(f"  执行高质量编码: {' '.join(cmd)}")
                        process = subprocess.run(cmd, check=True, capture_output=True, 
                                               text=True, encoding='utf-8', startupinfo=get_startupinfo())
                        
                        print(f"  高质量编码成功: {output_path}")
                        return True
                    except Exception as e:
                        print(f"  使用已知编码器失败，尝试其他方法: {e}")
                        # 继续使用其他方法
                
                elif encoder_name == "cpu":
                    try:
                        print("  使用CPU高质量编码...")
                        cmd = [
                            'ffmpeg',
                            '-i', video["path"],
                            '-filter_complex_script', filter_script_path,
                            '-map', '[v]',
                            '-map', '[a]'
                        ]
                        
                        # 添加视频尺寸参数（如果有效）
                        if video_width and video_height:
                            cmd.extend(['-s', f'{video_width}x{video_height}'])
                            
                        # 添加编码器和参数
                        cmd.extend([
                            '-c:v', 'libx264',
                            '-preset', CPU_ENCODE_PRESET,
                            '-crf', CRF_VALUE,
                            '-b:v', VIDEO_BITRATE,
                            '-maxrate', MAX_BITRATE,
                            '-bufsize', BUFFER_SIZE,
                            '-c:a', 'copy',  # 保持原始音频
                            '-vsync', 'vfr',
                            '-y',
                            output_path
                        ])
                        
                        print(f"  执行高质量编码: {' '.join(cmd)}")
                        process = subprocess.run(cmd, check=True, capture_output=True, 
                                               text=True, encoding='utf-8', startupinfo=get_startupinfo())
                        
                        print(f"  高质量编码成功: {output_path}")
                        return True
                    except Exception as e:
                        print(f"  使用已知编码器失败，尝试其他方法: {e}")
                        # 继续使用其他方法

    # 如果没找到能完全覆盖区间的视频，返回False
    print("  没有找到能完全覆盖区间的单个视频，将使用多视频拼接")
    return False

def _process_multiple_intervals(intervals, videos, output_path, temp_dir, 
                              filter_script_path, progress_callback=None, is_running=None):
    """处理多个时间区间或无法单视频覆盖的区间
    
    使用FFmpeg filter_complex进行一次性裁剪和拼接
    
    Args:
        intervals: 合并后的时间区间列表
        videos: 所有视频信息列表
        output_path: 最终输出文件路径
        temp_dir: 临时文件目录
        filter_script_path: FFmpeg过滤器脚本路径
        progress_callback: 进度回调函数
        is_running: 运行状态检查函数
        
    Returns:
        bool: 是否成功导出
    """
    # 为每个区间找到覆盖它的最少视频
    all_segments = []
    
    # 更新进度 - 分析阶段
    if progress_callback:
        progress_callback(-1, -1, "分析视频区间...")
    
    # 设置分析子进度
    interval_count = len(intervals)
    
    for interval_idx, (interval_start, interval_end) in enumerate(intervals):
        # 检查是否应该停止处理
        if is_running is not None and not is_running():
            return False
            
        # 更新分析子进度
        if progress_callback and interval_count > 1:
            sub_progress_msg = f"分析区间 {interval_idx+1}/{interval_count}"
            progress_callback(-1, -1, sub_progress_msg)
            
        print(f"  处理区间 {interval_idx+1}: {interval_start} -> {interval_end}")
        
        # 找出所有与区间有重叠的视频
        relevant_videos = []
        for video in videos:
            video_start = video["start"]
            video_end = video["end"]
            
            # 检查时间类型
            if not _is_valid_datetime(video_start, video_end, interval_start, interval_end):
                print(f"  警告: 无效的时间类型，跳过视频 {video.get('filename', 'unknown')}")
                continue
                
            # 检查视频是否与区间有重叠
            if video_start <= interval_end and video_end >= interval_start:
                overlap_start = max(video_start, interval_start)
                overlap_end = min(video_end, interval_end)
                overlap_duration = (overlap_end - overlap_start).total_seconds()
                
                # 确保有足够的重叠
                if overlap_duration >= 0.5:
                    relevant_videos.append({
                        "video": video,
                        "overlap_start": overlap_start,
                        "overlap_end": overlap_end,
                        "overlap_duration": overlap_duration
                    })
        
        # 按覆盖范围排序（优先选择覆盖面积更大的视频）
        relevant_videos.sort(key=lambda x: x["overlap_duration"], reverse=True)
        
        # 确定要使用的视频片段
        used_segments = []
        current_end = interval_start
        
        # 改进的选择算法：优先选择更长的连续片段而非多个小片段
        while current_end < interval_end and relevant_videos:
            best_segment = None
            best_coverage = 0
            
            for segment in relevant_videos:
                segment_start = segment["overlap_start"]
                segment_end = segment["overlap_end"]
                
                # 确保时间类型是datetime
                if not all(isinstance(t, datetime) for t in [segment_start, segment_end, current_end]):
                    continue
                    
                # 必须能覆盖当前位置或与当前位置最近
                if segment_start <= current_end + timedelta(seconds=1):  # 允许最多1秒的小间隔
                    # 计算新增覆盖范围（仅考虑未覆盖部分）
                    time_diff = min(segment_end, interval_end) - max(segment_start, current_end)
                    new_coverage = max(0, time_diff.total_seconds())
                    
                    # 选择能提供最大新增覆盖的片段
                    if new_coverage > best_coverage:
                        best_segment = segment
                        best_coverage = new_coverage
            
            # 如果找不到适合的片段，尝试找到能最早连接的片段
            if best_segment is None:
                # 按开始时间排序，找到开始时间最早的片段
                relevant_videos.sort(key=lambda x: x["overlap_start"])
                earliest_segment = relevant_videos[0] if relevant_videos else None
                
                if earliest_segment and isinstance(earliest_segment["overlap_start"], datetime) and isinstance(interval_end, datetime):
                    if earliest_segment["overlap_start"] <= interval_end:
                        best_segment = earliest_segment
                        # 可能存在间隙，记录这个情况
                        if isinstance(current_end, datetime) and earliest_segment["overlap_start"] > current_end:
                            gap = (earliest_segment["overlap_start"] - current_end).total_seconds()
                            print(f"    警告: 区间 {interval_idx+1} 在 {current_end} 和 {earliest_segment['overlap_start']} 之间存在 {gap:.2f}秒 间隙")
            
            # 添加选中的片段
            if best_segment is not None:
                # 检查是否与已添加片段有重叠
                overlap_with_existing = False
                
                for existing in used_segments:
                    # 确保都是datetime类型
                    if not all(isinstance(t, datetime) for t in [
                        best_segment["overlap_start"], best_segment["overlap_end"],
                        existing["overlap_start"], existing["overlap_end"]
                    ]):
                        continue
                        
                    # 如果新片段开始时间比已有片段结束时间早，且结束时间比已有片段开始时间晚，则有重叠
                    if (best_segment["overlap_start"] < existing["overlap_end"] and 
                        best_segment["overlap_end"] > existing["overlap_start"]):
                        
                        overlap_start = max(best_segment["overlap_start"], existing["overlap_start"])
                        overlap_end = min(best_segment["overlap_end"], existing["overlap_end"])
                        overlap_duration = (overlap_end - overlap_start).total_seconds()
                        
                        # 如果重叠超过0.5秒，认为有显著重叠
                        if overlap_duration > 0.5:
                            print(f"    警告: 片段与已有片段重叠 {overlap_duration:.2f}秒, 调整边界")
                            overlap_with_existing = True
                            
                            # 调整新片段边界，避免重叠
                            if best_segment["overlap_start"] < existing["overlap_end"]:
                                # 如果新片段从中间开始，调整开始时间到已有片段之后
                                best_segment["overlap_start"] = existing["overlap_end"]
                            
                            # 如果调整后片段太短，跳过此片段
                            if isinstance(best_segment["overlap_end"], datetime) and isinstance(best_segment["overlap_start"], datetime):
                                new_duration = (best_segment["overlap_end"] - best_segment["overlap_start"]).total_seconds()
                                if new_duration < 0.5:
                                    print(f"    跳过: 调整后片段太短 ({new_duration:.2f}秒)")
                                    best_segment = None
                                    break
                
                if best_segment:
                    # 更新当前覆盖位置到所选片段的结束
                    new_end = best_segment["overlap_end"]
                    
                    # 只有在真正推进覆盖位置时才添加片段
                    # 确保使用时间比较而非直接比较
                    time_advanced = False
                    if isinstance(new_end, datetime) and isinstance(current_end, datetime):
                        time_advanced = new_end > current_end
                    
                    if time_advanced:
                        used_segments.append(best_segment)
                        print(f"    选择片段: {best_segment['video']['filename']} 从 {best_segment['overlap_start']} 到 {best_segment['overlap_end']}")
                        current_end = new_end
                    else:
                        print(f"    跳过: 片段不会推进覆盖位置")
                
                # 从候选列表中移除使用过的片段
                if best_segment in relevant_videos:
                    relevant_videos.remove(best_segment)
            else:
                # 无法继续覆盖
                # 确保remaining是数值
                if isinstance(interval_end, datetime) and isinstance(current_end, datetime):
                    remaining = (interval_end - current_end).total_seconds()
                else:
                    remaining = 0
                print(f"    警告: 无法完全覆盖区间 {interval_idx+1}，剩余 {remaining:.2f} 秒未覆盖")
                break
        
        # 再次排序已选择的片段，确保按时间顺序
        used_segments.sort(key=lambda x: x["overlap_start"])
        
        # 检查是否完全覆盖
        is_fully_covered = False
        if isinstance(current_end, datetime) and isinstance(interval_end, datetime):
            is_fully_covered = current_end >= interval_end
            
        if is_fully_covered:
            print(f"    成功找到覆盖区间 {interval_idx+1} 的 {len(used_segments)} 个片段:")
            for i, segment in enumerate(used_segments):
                video = segment["video"]
                overlap_start = segment["overlap_start"]
                overlap_end = segment["overlap_end"]
                print(f"      片段 {i+1}: {video['filename']} {overlap_start} -> {overlap_end}")
                
            # 添加到总片段列表
            all_segments.extend(used_segments)
        else:
            print(f"    警告: 区间 {interval_idx+1} 未能完全覆盖，将使用可用部分")
            all_segments.extend(used_segments)
    
    # 对于合并区间的流程完成后
    if progress_callback:
        progress_callback(-1, -1, "准备导出视频...")
    
    # 按照开始时间排序所有片段并再次去重
    all_segments.sort(key=lambda x: x["overlap_start"])
    
    # 去除所有重叠片段
    deduped_segments = []
    for segment in all_segments:
        # 检查是否与已添加片段有显著重叠
        should_add = True
        
        for existing in deduped_segments:
            # 确保都是datetime类型
            if not all(isinstance(t, datetime) for t in [
                segment["overlap_start"], segment["overlap_end"],
                existing["overlap_start"], existing["overlap_end"]
            ]):
                continue
                
            # 检查重叠
            if (segment["overlap_start"] < existing["overlap_end"] and 
                segment["overlap_end"] > existing["overlap_start"]):
                
                overlap_start = max(segment["overlap_start"], existing["overlap_start"])
                overlap_end = min(segment["overlap_end"], existing["overlap_end"])
                overlap_duration = (overlap_end - overlap_start).total_seconds()
                
                # 确保可以计算段时长
                if isinstance(segment["overlap_end"], datetime) and isinstance(segment["overlap_start"], datetime):
                    # 如果重叠超过片段长度的30%，认为有显著重叠
                    segment_duration = (segment["overlap_end"] - segment["overlap_start"]).total_seconds()
                    if overlap_duration > 0.3 * segment_duration:
                        # 确保可以计算已存在片段时长
                        if isinstance(existing["overlap_end"], datetime) and isinstance(existing["overlap_start"], datetime):
                            # 如果新片段长度不大于已有片段，则跳过
                            existing_duration = (existing["overlap_end"] - existing["overlap_start"]).total_seconds()
                            if segment_duration <= existing_duration:
                                print(f"  跳过重叠片段: {segment['video']['filename']}")
                                should_add = False
                                break
                            # 否则，新片段更长，替换现有片段
                            else:
                                print(f"  替换较短片段: {existing['video']['filename']} -> {segment['video']['filename']}")
                                deduped_segments.remove(existing)
        
        if should_add:
            deduped_segments.append(segment)
    
    print(f"  去重后保留 {len(deduped_segments)}/{len(all_segments)} 个片段")
    
    # 使用FFmpeg的filter_complex创建单个命令处理所有片段
    return _create_ffmpeg_concat_command(deduped_segments, output_path, temp_dir, 
                                      filter_script_path, progress_callback, is_running)

def _create_ffmpeg_concat_command(segments, output_path, temp_dir, 
                               filter_script_path, progress_callback=None, is_running=None):
    """创建并执行FFmpeg命令，一次性完成所有裁剪和拼接操作
    
    Args:
        segments: 要使用的视频片段列表
        output_path: 最终输出文件路径
        temp_dir: 临时文件目录
        filter_script_path: FFmpeg过滤器脚本路径
        progress_callback: 进度回调函数
        is_running: 运行状态检查函数
        
    Returns:
        bool: 是否成功导出
    """
    # 全局变量记录成功使用的编码器，避免重复尝试失败的方法
    global _successful_concat_encoder
    if not hasattr(_create_ffmpeg_concat_command, "_successful_concat_encoder"):
        _create_ffmpeg_concat_command._successful_concat_encoder = None
    
    # 如果进度回调存在，更新编码准备状态
    if progress_callback:
        progress_callback(-1, -1, "准备编码参数...")
    
    # 如果强制使用CPU编码，直接设置使用CPU
    if ENFORCE_CPU_ENCODE and not _create_ffmpeg_concat_command._successful_concat_encoder:
        print("  设置了强制使用CPU编码")
        _create_ffmpeg_concat_command._successful_concat_encoder = "cpu"
    
    # 准备FFmpeg命令的输入部分
    input_args = []
    for i, segment in enumerate(segments):
        input_args.extend(['-i', segment["video"]["path"]])
    
    # 准备filter_complex脚本，优化处理流程
    filter_parts = []
    concat_parts = []
    
    for i, segment in enumerate(segments):
        video = segment["video"]
        video_start = video["start"]
        overlap_start = segment["overlap_start"]
        overlap_end = segment["overlap_end"]
        
        # 计算在源视频中的相对时间位置
        rel_start = (overlap_start - video_start).total_seconds()
        duration = (overlap_end - overlap_start).total_seconds()
        
        # 添加调试信息
        print(f"  片段{i+1}详情: 文件={video['filename']}, 相对起点={rel_start:.2f}秒, 时长={duration:.2f}秒")
        
        # 简化过滤器链，将trim合并到一个流中
        # 这样可以减少中间流的数量，降低处理复杂度
        filter_parts.append(
            f"[{i}:v]trim=start={rel_start}:duration={duration},setpts=PTS-STARTPTS[v{i}]"
        )
        
        # 添加音频流裁剪命令
        filter_parts.append(f"[{i}:a]atrim=start={rel_start}:duration={duration},asetpts=PTS-STARTPTS[a{i}]")
        
        # 添加到concat列表
        concat_parts.append(f"[v{i}][a{i}]")
    
    # 添加concat命令
    filter_parts.append(f"{' '.join(concat_parts)}concat=n={len(segments)}:v=1:a=1[outv][outa]")
    
    # 将filter_complex脚本写入文件
    with open(filter_script_path, 'w', encoding='utf-8') as f:
        f.write(";\n".join(filter_parts))
    
    # 如果已经有成功使用的编码器，直接使用它
    if _create_ffmpeg_concat_command._successful_concat_encoder:
        encoder_name = _create_ffmpeg_concat_command._successful_concat_encoder
        print(f"  使用之前成功的编码器: {encoder_name}")
        
        if progress_callback:
            progress_callback(-1, -1, f"使用编码器: {encoder_name}...")
        
        if encoder_name == "h264_nvenc_2step":
            # 使用GPU H.264两步法编码
            return _try_nvidia_h264_two_step(input_args, filter_script_path, temp_dir, output_path)
        elif encoder_name == "hevc_nvenc_2step":
            # 使用GPU HEVC两步法编码
            return _try_nvidia_hevc_two_step(input_args, filter_script_path, temp_dir, output_path)
        elif encoder_name == "h264_nvenc":
            # 使用GPU H.264单步编码
            return _try_nvidia_h264(input_args, filter_script_path, output_path)
        elif encoder_name == "hevc_nvenc":
            # 使用GPU HEVC单步编码
            return _try_nvidia_hevc(input_args, filter_script_path, output_path)
        elif encoder_name == "cpu":
            # 使用CPU编码
            return _try_cpu_encode(input_args, filter_script_path, output_path)
        elif encoder_name == "cpu_simple":
            # 使用简化CPU编码
            return _try_simple_cpu_encode(input_args, filter_script_path, temp_dir, output_path)
        elif encoder_name == "segment_by_segment":
            # 使用分段逐一处理
            return _try_segment_by_segment(segments, temp_dir, output_path)
    
    # 强制使用CPU编码时，直接尝试CPU方法
    if ENFORCE_CPU_ENCODE:
        print("  强制使用CPU编码，跳过GPU编码尝试")
        if progress_callback:
            progress_callback(-1, -1, "尝试CPU编码...")
            
        # 尝试CPU编码
        print("  尝试CPU编码...")
        result = _try_cpu_encode(input_args, filter_script_path, output_path)
        if result:
            _create_ffmpeg_concat_command._successful_concat_encoder = "cpu"
            return True
        
        if progress_callback:
            progress_callback(-1, -1, "尝试简化CPU编码...")
            
        # 尝试简化CPU编码
        print("  尝试简化CPU编码...")
        result = _try_simple_cpu_encode(input_args, filter_script_path, temp_dir, output_path)
        if result:
            _create_ffmpeg_concat_command._successful_concat_encoder = "cpu_simple"
            return True
        
        if progress_callback:
            progress_callback(-1, -1, "尝试分段处理...")
            
        # 最后尝试最基本的分段处理方式
        print("  尝试分段逐一处理...")
        result = _try_segment_by_segment(segments, temp_dir, output_path)
        if result:
            _create_ffmpeg_concat_command._successful_concat_encoder = "segment_by_segment"
            return True
        
        print("  所有CPU编码方法均失败")
        return False
    
    # 检查可用的编码器
    available_encoders = check_encoder_availability()
    
    # 尝试各种编码方式，从最优到最简
    # 1. 首先尝试两步法GPU处理
    if "h264_nvenc" in available_encoders:
        if progress_callback:
            progress_callback(-1, -1, "尝试NVIDIA H.264两步法编码...")
        print("  尝试NVIDIA H.264两步法编码...")
        result = _try_nvidia_h264_two_step(input_args, filter_script_path, temp_dir, output_path)
        if result:
            _create_ffmpeg_concat_command._successful_concat_encoder = "h264_nvenc_2step"
            return True
    
    if "hevc_nvenc" in available_encoders:
        if progress_callback:
            progress_callback(-1, -1, "尝试NVIDIA HEVC两步法编码...")
        print("  尝试NVIDIA HEVC两步法编码...")
        result = _try_nvidia_hevc_two_step(input_args, filter_script_path, temp_dir, output_path)
        if result:
            _create_ffmpeg_concat_command._successful_concat_encoder = "hevc_nvenc_2step"
            return True
    
    # 2. 尝试单步GPU编码
    if "h264_nvenc" in available_encoders:
        if progress_callback:
            progress_callback(-1, -1, "尝试NVIDIA H.264单步编码...")
        print("  尝试NVIDIA H.264单步编码...")
        result = _try_nvidia_h264(input_args, filter_script_path, output_path)
        if result:
            _create_ffmpeg_concat_command._successful_concat_encoder = "h264_nvenc"
            return True
    
    if "hevc_nvenc" in available_encoders:
        if progress_callback:
            progress_callback(-1, -1, "尝试NVIDIA HEVC单步编码...")
        print("  尝试NVIDIA HEVC单步编码...")
        result = _try_nvidia_hevc(input_args, filter_script_path, output_path)
        if result:
            _create_ffmpeg_concat_command._successful_concat_encoder = "hevc_nvenc"
            return True
    
    # 3. 尝试CPU编码
    if progress_callback:
        progress_callback(-1, -1, "尝试CPU编码...")
    print("  尝试CPU编码...")
    result = _try_cpu_encode(input_args, filter_script_path, output_path)
    if result:
        _create_ffmpeg_concat_command._successful_concat_encoder = "cpu"
        return True
    
    # 4. 尝试简化CPU编码
    if progress_callback:
        progress_callback(-1, -1, "尝试简化CPU编码...")
    print("  尝试简化CPU编码...")
    result = _try_simple_cpu_encode(input_args, filter_script_path, temp_dir, output_path)
    if result:
        _create_ffmpeg_concat_command._successful_concat_encoder = "cpu_simple"
        return True
    
    # 5. 最后尝试最基本的分段处理方式
    if progress_callback:
        progress_callback(-1, -1, "尝试分段逐一处理...")
    print("  尝试分段逐一处理...")
    result = _try_segment_by_segment(segments, temp_dir, output_path)
    if result:
        _create_ffmpeg_concat_command._successful_concat_encoder = "segment_by_segment"
        return True
    
    print("  所有编码方法均失败")
    if progress_callback:
        progress_callback(-1, -1, "所有编码方法均失败")
    return False

def _try_nvidia_h264_two_step(input_args, filter_script_path, temp_dir, output_path):
    """尝试使用NVIDIA H.264两步法编码"""
    try:
        # 1. 先用简单的filter合并视频到临时文件
        temp_output = os.path.join(temp_dir, f"temp_concat_{int(time.time())}.mp4")
        
        # 使用简化的过滤器命令合并视频
        simple_cmd = input_args + [
            '-filter_complex_script', filter_script_path,
            '-map', '[outv]',
            '-map', '[outa]',
            '-c:v', 'h264_nvenc',
            '-preset', 'p2',  # 使用更快的预设值
            '-rc', 'vbr',
            '-b:v', VIDEO_BITRATE,
            '-c:a', 'aac',
            '-b:a', AUDIO_BITRATE,
            '-y',
            temp_output
        ]
        
        # 执行命令
        print(f"  执行FFmpeg命令合并视频段:")
        print(f"    {' '.join(['ffmpeg'] + simple_cmd)}")
        
        process = subprocess.run(['ffmpeg'] + simple_cmd, check=True, capture_output=True, 
                               text=True, encoding='utf-8', startupinfo=get_startupinfo())
        
        # 2. 第二步：对合并后的视频做进一步处理
        print("  第二步：使用NVIDIA H.264硬件加速优化视频...")
        second_cmd = [
            'ffmpeg',
            '-i', temp_output,
            '-c:v', 'h264_nvenc',
            '-preset', GPU_ENCODE_PRESET,
            '-rc', 'vbr',
            '-cq', CQ_VALUE,
            '-b:v', VIDEO_BITRATE,
            '-maxrate', MAX_BITRATE,
            '-bufsize', BUFFER_SIZE,
            '-c:a', 'copy',
            '-vsync', 'vfr',
            '-y',
            output_path
        ]
        
        print(f"  执行FFmpeg命令优化视频:")
        print(f"    {' '.join(second_cmd)}")
        
        process = subprocess.run(second_cmd, check=True, capture_output=True, 
                               text=True, encoding='utf-8', startupinfo=get_startupinfo())
        
        print(f"  成功导出合并视频: {output_path}")
        
        # 清理临时文件
        if os.path.exists(temp_output):
            os.remove(temp_output)
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"  NVIDIA H.264两步法编码失败，错误代码: {e.returncode}")
        # 清理临时文件
        if 'temp_output' in locals() and os.path.exists(temp_output):
            os.remove(temp_output)
        return False
    except UnicodeDecodeError as e:
        print(f"  编码解码错误: {e}")
        print(f"  这可能是由于ffmpeg输出包含无法解码的字符")
        return False
    except Exception as e:
        print(f"  NVIDIA H.264两步法编码出现异常: {e}")
        # 清理临时文件
        if 'temp_output' in locals() and os.path.exists(temp_output):
            os.remove(temp_output)
        return False

def _try_nvidia_hevc_two_step(input_args, filter_script_path, temp_dir, output_path):
    """尝试使用NVIDIA HEVC两步法编码"""
    try:
        # 1. 先用简单的filter合并视频到临时文件
        temp_output = os.path.join(temp_dir, f"temp_concat_{int(time.time())}.mp4")
        
        # 使用简化的过滤器命令合并视频
        simple_cmd = input_args + [
            '-filter_complex_script', filter_script_path,
            '-map', '[outv]',
            '-map', '[outa]',
            '-c:v', 'hevc_nvenc',
            '-preset', 'p2',  # 使用更快的预设值
            '-rc', 'vbr',
            '-b:v', VIDEO_BITRATE,
            '-c:a', 'aac',
            '-b:a', AUDIO_BITRATE,
            '-y',
            temp_output
        ]
        
        # 执行命令
        print(f"  执行FFmpeg命令合并视频段:")
        print(f"    {' '.join(['ffmpeg'] + simple_cmd)}")
        
        process = subprocess.run(['ffmpeg'] + simple_cmd, check=True, capture_output=True, 
                               text=True, encoding='utf-8', startupinfo=get_startupinfo())
        
        # 2. 第二步：对合并后的视频做进一步处理
        print("  第二步：使用NVIDIA HEVC硬件加速优化视频...")
        second_cmd = [
            'ffmpeg',
            '-i', temp_output,
            '-c:v', 'hevc_nvenc',
            '-preset', GPU_ENCODE_PRESET,
            '-rc', 'vbr',
            '-cq', CQ_VALUE,
            '-b:v', VIDEO_BITRATE,
            '-maxrate', MAX_BITRATE,
            '-bufsize', BUFFER_SIZE,
            '-c:a', 'copy',
            '-vsync', 'vfr',
            '-y',
            output_path
        ]
        
        print(f"  执行FFmpeg命令优化视频:")
        print(f"    {' '.join(second_cmd)}")
        
        process = subprocess.run(second_cmd, check=True, capture_output=True, 
                               text=True, encoding='utf-8', startupinfo=get_startupinfo())
        
        print(f"  成功导出合并视频: {output_path}")
        
        # 清理临时文件
        if os.path.exists(temp_output):
            os.remove(temp_output)
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"  NVIDIA HEVC两步法编码失败，错误代码: {e.returncode}")
        # 清理临时文件
        if 'temp_output' in locals() and os.path.exists(temp_output):
            os.remove(temp_output)
        return False
    except UnicodeDecodeError as e:
        print(f"  编码解码错误: {e}")
        print(f"  这可能是由于ffmpeg输出包含无法解码的字符")
        return False
    except Exception as e:
        print(f"  NVIDIA HEVC两步法编码出现异常: {e}")
        # 清理临时文件
        if 'temp_output' in locals() and os.path.exists(temp_output):
            os.remove(temp_output)
        return False

def _try_nvidia_h264(input_args, filter_script_path, output_path):
    """尝试使用NVIDIA H.264单步编码"""
    try:
        cmd = input_args + [
            '-filter_complex_script', filter_script_path,
            '-map', '[outv]',
            '-map', '[outa]',
            '-c:v', 'h264_nvenc',
            '-preset', GPU_ENCODE_PRESET,
            '-rc', 'vbr',
            '-cq', CQ_VALUE,
            '-b:v', VIDEO_BITRATE,
            '-maxrate', MAX_BITRATE,
            '-bufsize', BUFFER_SIZE,
            '-c:a', 'aac',
            '-b:a', AUDIO_BITRATE,
            '-vsync', 'vfr',  # 可变帧率同步，配合mpdecimate使用
            '-y',
            output_path
        ]
        
        # 输出命令预览
        ffmpeg_cmd = ['ffmpeg'] + cmd
        print(f"  执行FFmpeg命令导出视频:")
        print(f"    {' '.join(ffmpeg_cmd)}")
        
        # 执行命令
        try:
            process = subprocess.run(['ffmpeg'] + cmd, check=True, capture_output=True, 
                                text=True, encoding='utf-8', startupinfo=get_startupinfo())
            
            print(f"  成功导出合并视频: {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"  NVIDIA H.264单步编码失败: {e}")
            return False
        except UnicodeDecodeError as e:
            print(f"  编码解码错误: {e}")
            print(f"  这可能是由于ffmpeg输出包含无法解码的字符")
            return False
    except Exception as e:
        print(f"  NVIDIA H.264单步编码出现异常: {e}")
        return False

def _try_nvidia_hevc(input_args, filter_script_path, output_path):
    """尝试使用NVIDIA HEVC单步编码"""
    try:
        cmd = input_args + [
            '-filter_complex_script', filter_script_path,
            '-map', '[outv]',
            '-map', '[outa]',
            '-c:v', 'hevc_nvenc',
            '-preset', GPU_ENCODE_PRESET,
            '-rc', 'vbr',
            '-cq', CQ_VALUE,
            '-b:v', VIDEO_BITRATE,
            '-maxrate', MAX_BITRATE,
            '-bufsize', BUFFER_SIZE,
            '-c:a', 'aac',
            '-b:a', AUDIO_BITRATE,
            '-vsync', 'vfr',  # 可变帧率同步，配合mpdecimate使用
            '-y',
            output_path
        ]
        
        # 输出命令预览
        ffmpeg_cmd = ['ffmpeg'] + cmd
        print(f"  执行FFmpeg命令导出视频:")
        print(f"    {' '.join(ffmpeg_cmd)}")
        
        # 执行命令
        try:
            process = subprocess.run(['ffmpeg'] + cmd, check=True, capture_output=True, 
                                text=True, encoding='utf-8', startupinfo=get_startupinfo())
            
            print(f"  成功导出合并视频: {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"  NVIDIA HEVC单步编码失败: {e}")
            return False
        except UnicodeDecodeError as e:
            print(f"  编码解码错误: {e}")
            print(f"  这可能是由于ffmpeg输出包含无法解码的字符")
            return False
    except Exception as e:
        print(f"  NVIDIA HEVC单步编码出现异常: {e}")
        return False

def _try_cpu_encode(input_args, filter_script_path, output_path):
    """尝试使用CPU编码"""
    try:
        cmd = input_args + [
            '-filter_complex_script', filter_script_path,
            '-map', '[outv]',
            '-map', '[outa]',
            '-c:v', 'libx264',
            '-preset', CPU_ENCODE_PRESET,
            '-crf', CRF_VALUE,
            '-b:v', VIDEO_BITRATE,
            '-maxrate', MAX_BITRATE,
            '-bufsize', BUFFER_SIZE,
            '-c:a', 'aac',
            '-b:a', AUDIO_BITRATE,
            '-vsync', 'vfr',  # 可变帧率同步，配合mpdecimate使用
            '-y',
            output_path
        ]
        
        # 输出命令预览
        print(f"  执行CPU编码:")
        print(f"    {' '.join(['ffmpeg'] + cmd)}")
        
        # 执行命令
        try:
            subprocess.run(['ffmpeg'] + cmd, check=True, capture_output=True, 
                        text=True, encoding='utf-8', startupinfo=get_startupinfo())
            
            print(f"  成功导出合并视频: {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"  CPU编码失败: {e}")
            return False
        except UnicodeDecodeError as e:
            print(f"  编码解码错误: {e}")
            print(f"  这可能是由于ffmpeg输出包含无法解码的字符")
            return False
    except Exception as e:
        print(f"  CPU编码出现异常: {e}")
        return False

def _try_simple_cpu_encode(input_args, filter_script_path, temp_dir, output_path):
    """尝试使用简化的CPU编码方法"""
    try:
        # 从原始过滤器脚本中读取内容，并简化过滤器
        with open(filter_script_path, 'r', encoding='utf-8') as f:
            filter_content = f.read()
        
        # 创建一个新的临时过滤器文件
        simple_filter_path = os.path.join(temp_dir, f"simple_filter_{int(time.time())}.txt")
        
        # 简化过滤器：完全移除mpdecimate部分以解决编码错误
        simplified_content = filter_content.replace("mpdecimate=hi=32:lo=16:frac=0.1,", "")
        
        with open(simple_filter_path, 'w', encoding='utf-8') as f:
            f.write(simplified_content)
        
        # 使用超快速预设和简化过滤器
        simple_cmd = input_args + [
            '-filter_complex_script', simple_filter_path,
            '-map', '[outv]',
            '-map', '[outa]',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',  # 使用超快速预设
            '-crf', '23',            # 稍微降低质量以提高速度
            '-c:a', 'aac',
            '-b:a', AUDIO_BITRATE,
            '-y',
            output_path
        ]
        
        # 输出命令预览
        print(f"  尝试简化CPU编码:")
        print(f"    {' '.join(['ffmpeg'] + simple_cmd)}")
        
        # 执行命令
        process = subprocess.run(['ffmpeg'] + simple_cmd, check=True, capture_output=True, 
                              text=True, encoding='utf-8', startupinfo=get_startupinfo())
        
        print(f"  成功导出合并视频: {output_path}")
        
        # 清理临时文件
        if os.path.exists(simple_filter_path):
            os.remove(simple_filter_path)
            
        return True
    except subprocess.CalledProcessError as e:
        print(f"  简化CPU编码失败: {e}")
        # 清理临时文件
        if 'simple_filter_path' in locals() and os.path.exists(simple_filter_path):
            os.remove(simple_filter_path)
        return False
    except UnicodeDecodeError as e:
        print(f"  编码解码错误: {e}")
        print(f"  这可能是由于ffmpeg输出包含无法解码的字符")
        return False
    except Exception as e:
        print(f"  简化CPU编码出现异常: {e}")
        # 清理临时文件
        if 'simple_filter_path' in locals() and os.path.exists(simple_filter_path):
            os.remove(simple_filter_path)
        return False

def _try_segment_by_segment(segments, temp_dir, output_path):
    """尝试处理单个片段并逐个连接"""
    try:
        segment_files = []
        
        for i, segment in enumerate(segments):
            video = segment["video"]
            video_start = video["start"]
            overlap_start = segment["overlap_start"]
            overlap_end = segment["overlap_end"]
            
            # 计算在源视频中的相对时间位置
            rel_start = (overlap_start - video_start).total_seconds()
            duration = (overlap_end - overlap_start).total_seconds()
            
            # 添加调试信息
            print(f"  片段{i+1}详情: 文件={video['filename']}, 相对起点={rel_start:.2f}秒, 时长={duration:.2f}秒")
            
            # 创建单个片段的临时文件
            segment_output = os.path.join(temp_dir, f"segment_{i}_{int(time.time())}.mp4")
            segment_files.append(segment_output)
            
            # 使用最简单的裁剪命令
            simple_cut_cmd = [
                'ffmpeg',
                '-i', video["path"],
                '-ss', str(rel_start),
                '-t', str(duration),
                '-c:v', 'libx264',
                '-preset', 'ultrafast',
                '-c:a', 'aac',
                '-y',
                segment_output
            ]
            
            print(f"  裁剪片段 {i+1}/{len(segments)}: {' '.join(simple_cut_cmd)}")
            process = subprocess.run(simple_cut_cmd, check=True, capture_output=True, 
                                  text=True, encoding='utf-8', startupinfo=get_startupinfo())
        
        # 创建一个合并用的文件列表
        concat_list = os.path.join(temp_dir, f"concat_list_{int(time.time())}.txt")
        with open(concat_list, 'w', encoding='utf-8') as f:
            for segment_file in segment_files:
                # 使用正规化路径
                norm_path = os.path.abspath(segment_file).replace('\\', '/')
                f.write(f"file '{norm_path}'\n")
        
        # 执行简单的合并
        final_concat_cmd = [
            'ffmpeg',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_list,
            '-c', 'copy',
            '-y',
            output_path
        ]
        
        print(f"  执行最终合并: {' '.join(final_concat_cmd)}")
        process = subprocess.run(final_concat_cmd, check=True, capture_output=True, 
                              text=True, encoding='utf-8', startupinfo=get_startupinfo())
        
        print(f"  成功导出合并视频: {output_path}")
        
        # 清理临时文件
        for segment_file in segment_files:
            if os.path.exists(segment_file):
                os.remove(segment_file)
        if os.path.exists(concat_list):
            os.remove(concat_list)
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"  分段逐一处理失败: {e}")
        return False
    except UnicodeDecodeError as e:
        print(f"  编码解码错误: {e}")
        print(f"  这可能是由于ffmpeg输出包含无法解码的字符")
        return False
    except Exception as e:
        print(f"  分段逐一处理出现异常: {e}")
        return False

def _finalize_processing(successful_exports, latest_time, state_file, all_files_info):
    """完成处理并更新状态"""
    if successful_exports > 0:
        print(f"\n处理完成，共成功导出 {successful_exports} 个连杀片段。")
        # 更新状态文件
        if latest_time:
            print(f"将更新上次处理时间为: {latest_time}")
            save_last_processed_time(latest_time, state_file)
    elif not all_files_info:
        print("\n没有新文件需要处理。")
    else:
        print("\n本次运行没有成功导出任何片段，不更新上次处理时间。") 