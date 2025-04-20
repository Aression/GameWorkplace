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
    KILL_LEAD_TIME, KILL_TAIL_TIME
)
from exporter.utils.file_utils import (
    parse_video_time, load_last_processed_time, save_last_processed_time
)
from exporter.utils.ffmpeg_utils import (
    get_video_duration, cut_video, get_startupinfo, check_encoder_availability
)
from exporter.core.models import TimeSegment

# 视频素材覆盖范围
VIDEO_COVER_RANGE = 20  # 视频素材通常以击杀前后 20 秒范围录制

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
    
    for idx, segment in enumerate(valid_segments, 1):
        # 检查是否应该停止处理
        if is_running is not None and not is_running():
            return successful_exports
            
        # 更新进度
        if progress_callback:
            progress_callback(idx-1, segment_count, f"处理连杀片段 {idx}/{segment_count} (击杀数: {len(segment.kill_times)})")
        
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
            # 按开始时间排序
            kill_intervals.sort(key=lambda x: x[0])
            current_start, current_end = kill_intervals[0]
            
            for start, end in kill_intervals[1:]:
                # 如果当前区间与累积区间重叠，则合并
                if start <= current_end:
                    current_end = max(current_end, end)
                else:
                    # 无重叠，保存当前累积区间并开始新区间
                    merged_intervals.append((current_start, current_end))
                    current_start, current_end = start, end
                    
            # 添加最后一个区间
            merged_intervals.append((current_start, current_end))
        
        print(f"  合并后得到 {len(merged_intervals)} 个不重叠区间")
        for i, (start, end) in enumerate(merged_intervals):
            print(f"    区间 {i+1}: {start} -> {end} (持续: {(end-start).total_seconds():.1f}秒)")
            
        # 3. 为每个合并区间选择源视频
        first_kill = kill_times_sorted[0]
        first_kill_time_str = first_kill.strftime('%Y%m%d_%H%M%S')
        final_output_filename = f"连杀{len(segment.kill_times)}_{first_kill_time_str}_组{idx}.mp4"
        final_output_path = os.path.join(output_dir, final_output_filename)
        
        # 创建临时文件以存储FFmpeg复杂过滤器命令
        filter_script_path = os.path.join(temp_dir, f"filter_complex_{idx}.txt")
        
        # 如果只有一个区间，尝试用单个视频覆盖
        if len(merged_intervals) == 1:
            result = _process_single_interval(
                merged_intervals[0], videos, final_output_path, temp_dir, progress_callback
            )
            if result:
                successful_exports += 1
                continue
        
        # 多区间或单区间但无法单视频覆盖的情况
        result = _process_multiple_intervals(
            merged_intervals, videos, final_output_path, temp_dir, 
            filter_script_path, progress_callback, is_running
        )
        if result:
            successful_exports += 1
    
    # 更新最终进度
    if progress_callback:
        progress_callback(segment_count, segment_count, "处理完成")
        
    return successful_exports

def _process_single_interval(interval, videos, output_path, temp_dir, progress_callback=None):
    """处理单个时间区间，寻找可完全覆盖此区间的视频
    
    Args:
        interval: 合并后的时间区间 (start_time, end_time)
        videos: 所有视频信息列表
        output_path: 最终输出文件路径
        temp_dir: 临时文件目录
        progress_callback: 进度回调函数
        
    Returns:
        bool: 是否成功导出
    """
    interval_start, interval_end = interval
    interval_duration = (interval_end - interval_start).total_seconds()
    
    # 查找可完全覆盖区间的源视频
    print(f"  尝试寻找单个视频覆盖整个区间...")
    
    for video in videos:
        filter_script_path = None
        try:
            video_start = video["start"]
            video_end = video["end"]
            
            # 检查是否完全覆盖
            if video_start <= interval_start and video_end >= interval_end:
                # 计算在视频中的相对时间位置
                rel_start = (interval_start - video_start).total_seconds()
                
                print(f"  找到可完全覆盖的视频: {video['filename']}")
                print(f"    视频范围: {video_start} -> {video_end}")
                print(f"    相对裁剪位置: 从 {rel_start:.2f}秒 开始，持续 {interval_duration:.2f}秒")
                
                # 更新进度
                if progress_callback:
                    progress_callback(-1, -1, f"剪切视频: {video['filename']}")
                
                # 创建一个临时过滤器文件，添加去重帧处理
                filter_script_path = os.path.join(temp_dir, f"filter_single_{os.getpid()}.txt")
                filter_content = (f"[0:v]trim=start={rel_start}:duration={interval_duration},setpts=PTS-STARTPTS,"
                                f"mpdecimate=hi=64:lo=32:frac=0.33,setpts=N/FRAME_RATE/TB[v];"
                                f"[0:a]atrim=start={rel_start}:duration={interval_duration},asetpts=PTS-STARTPTS[a]")
                
                with open(filter_script_path, 'w', encoding='utf-8') as f:
                    f.write(filter_content)
                
                # 检查可用的编码器
                available_encoders = check_encoder_availability()
                
                # 根据可用编码器选择使用GPU还是CPU
                if "h264_nvenc" in available_encoders:
                    # 使用GPU H.264编码
                    print("  使用NVIDIA H.264硬件加速...")
                    cmd = [
                        'ffmpeg',
                        '-i', video["path"],
                        '-filter_complex_script', filter_script_path,
                        '-map', '[v]',
                        '-map', '[a]',
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
                elif "hevc_nvenc" in available_encoders:
                    # 使用GPU HEVC编码 (H.265)
                    print("  使用NVIDIA HEVC硬件加速...")
                    cmd = [
                        'ffmpeg',
                        '-i', video["path"],
                        '-filter_complex_script', filter_script_path,
                        '-map', '[v]',
                        '-map', '[a]',
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
                else:
                    # 直接使用CPU编码，不尝试GPU
                    raise ValueError("未检测到支持的GPU编码器，直接使用CPU编码")
                
                print(f"  执行GPU编码导出: {' '.join(cmd)}")
                process = subprocess.run(cmd, check=True, capture_output=True, 
                                      text=True, encoding='utf-8', startupinfo=get_startupinfo())
                
                print(f"  成功导出区间视频: {output_path}")
                return True
                
        except (subprocess.CalledProcessError, ValueError) as e:
            print(f"  GPU编码失败或不可用，尝试CPU编码: {e}")
            
            try:
                # 使用CPU编码
                cmd = [
                    'ffmpeg',
                    '-i', video["path"],
                    '-filter_complex_script', filter_script_path,
                    '-map', '[v]',
                    '-map', '[a]',
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
                
                print(f"  执行CPU编码导出: {' '.join(cmd)}")
                process = subprocess.run(cmd, check=True, capture_output=True, 
                                      text=True, encoding='utf-8', startupinfo=get_startupinfo())
                
                print(f"  成功导出区间视频: {output_path}")
                return True
                
            except subprocess.CalledProcessError as e_cpu:
                print(f"  CPU编码也失败了: {e_cpu}")
                print(f"  单视频剪切失败，将尝试使用多视频拼接方法")
                return False
        
        except Exception as e:
            print(f"  处理视频时发生意外错误: {e}")
            print(f"  尝试使用多视频拼接方法")
            return False
            
        finally:
            # 清理临时文件
            try:
                if filter_script_path and os.path.exists(filter_script_path):
                    os.remove(filter_script_path)
            except Exception as e:
                print(f"  无法删除临时文件 {filter_script_path}: {e}")
    
    print(f"  未找到可完全覆盖区间的单个视频")
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
    
    # 更新进度
    if progress_callback:
        progress_callback(-1, -1, "分析最优视频选择...")
    
    for interval_idx, (interval_start, interval_end) in enumerate(intervals):
        print(f"  处理区间 {interval_idx+1}: {interval_start} -> {interval_end}")
        
        # 找出所有与区间有重叠的视频
        relevant_videos = []
        for video in videos:
            video_start = video["start"]
            video_end = video["end"]
            # 确保所有时间是datetime类型
            if not all(isinstance(t, datetime) for t in [video_start, video_end, interval_start, interval_end]):
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
    
    # 如果没有找到有效片段，返回失败
    if not all_segments:
        print("  未找到有效的视频片段，无法导出")
        return False
    
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
        
        # 简化过滤器链，将trim和mpdecimate合并到一个流中
        # 这样可以减少中间流的数量，降低处理复杂度
        filter_parts.append(
            f"[{i}:v]trim=start={rel_start}:duration={duration},setpts=PTS-STARTPTS,"
            f"mpdecimate=hi=64:lo=32:frac=0.33,setpts=N/FRAME_RATE/TB[v{i}]"
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
    
    # 检查可用的编码器
    available_encoders = check_encoder_availability()
    
    # 创建FFmpeg命令
    try:
        # 先尝试使用两段式处理方法
        # 1. 先用简单的filter合并视频到临时文件
        temp_output = os.path.join(temp_dir, f"temp_concat_{int(time.time())}.mp4")
        
        # 根据可用编码器选择使用GPU还是CPU
        if "h264_nvenc" in available_encoders:
            # 使用GPU H.264编码
            print("  第一步：使用NVIDIA H.264硬件加速合并段...")
            try:
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
                print(f"  GPU两段式处理失败，错误代码: {e.returncode}")
                if os.path.exists(temp_output):
                    os.remove(temp_output)
                # 继续尝试其他方法
        
        # 如果两段式处理失败或不适用，尝试直接一步到位
        # 根据可用编码器选择使用GPU还是CPU
        if "h264_nvenc" in available_encoders:
            # 使用GPU H.264编码
            print("  使用NVIDIA H.264硬件加速...")
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
        elif "hevc_nvenc" in available_encoders:
            # 使用GPU HEVC编码 (H.265)
            print("  使用NVIDIA HEVC硬件加速...")
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
                '-vsync', 'vfr',  # 可变帧率同步
                '-y',
                output_path
            ]
        else:
            # 直接使用CPU编码，不尝试GPU
            raise ValueError("未检测到支持的GPU编码器，直接使用CPU编码")
        
        # 输出命令预览
        ffmpeg_cmd = ['ffmpeg'] + cmd
        print(f"  执行FFmpeg命令导出视频:")
        print(f"    {' '.join(ffmpeg_cmd)}")
        
        # 更新进度
        if progress_callback:
            progress_callback(-1, -1, "使用FFmpeg一次性处理所有片段...")
        
        # 执行命令
        process = subprocess.run(['ffmpeg'] + cmd, check=True, capture_output=True, 
                               text=True, encoding='utf-8', startupinfo=get_startupinfo())
        
        print(f"  成功导出合并视频: {output_path}")
        return True
        
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f"  GPU编码失败或不可用，尝试使用CPU编码: {e}")
        
        try:
            # 尝试使用简化的CPU方法
            print("  尝试使用简化的CPU编码方法...")
            
            # 调整过滤器以简化处理
            simple_filter_parts = []
            simple_concat_parts = []
            
            for i, segment in enumerate(segments):
                video = segment["video"]
                video_start = video["start"]
                overlap_start = segment["overlap_start"]
                overlap_end = segment["overlap_end"]
                
                # 计算在源视频中的相对时间位置
                rel_start = (overlap_start - video_start).total_seconds()
                duration = (overlap_end - overlap_start).total_seconds()
                
                # 非常简化的过滤器，只做基本的裁剪
                simple_filter_parts.append(f"[{i}:v]trim=start={rel_start}:duration={duration},setpts=PTS-STARTPTS[v{i}]")
                simple_filter_parts.append(f"[{i}:a]atrim=start={rel_start}:duration={duration},asetpts=PTS-STARTPTS[a{i}]")
                
                # 添加到concat列表
                simple_concat_parts.append(f"[v{i}][a{i}]")
            
            # 添加concat命令
            simple_filter_parts.append(f"{' '.join(simple_concat_parts)}concat=n={len(segments)}:v=1:a=1[outv][outa]")
            
            # 写入新的过滤器脚本
            simple_filter_path = os.path.join(temp_dir, f"simple_filter_{int(time.time())}.txt")
            with open(simple_filter_path, 'w', encoding='utf-8') as f:
                f.write(";\n".join(simple_filter_parts))
            
            # 使用CPU编码
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
            subprocess.run(['ffmpeg'] + simple_cmd, check=True, capture_output=True, 
                          text=True, encoding='utf-8', startupinfo=get_startupinfo())
            
            print(f"  成功导出合并视频: {output_path}")
            
            # 清理临时文件
            if os.path.exists(simple_filter_path):
                os.remove(simple_filter_path)
                
            return True
        except subprocess.CalledProcessError as e_cpu:
            print(f"  简化的CPU编码也失败了: {e_cpu}")
            print(f"  尝试最后的备用方案：分段处理...")
            
            try:
                # 尝试处理单个片段并逐个连接
                segment_files = []
                
                for i, segment in enumerate(segments):
                    video = segment["video"]
                    video_start = video["start"]
                    overlap_start = segment["overlap_start"]
                    overlap_end = segment["overlap_end"]
                    
                    # 计算在源视频中的相对时间位置
                    rel_start = (overlap_start - video_start).total_seconds()
                    duration = (overlap_end - overlap_start).total_seconds()
                    
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
                    subprocess.run(simple_cut_cmd, check=True, capture_output=True, 
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
                subprocess.run(final_concat_cmd, check=True, capture_output=True, 
                              text=True, encoding='utf-8', startupinfo=get_startupinfo())
                
                print(f"  成功导出合并视频: {output_path}")
                
                # 清理临时文件
                for segment_file in segment_files:
                    if os.path.exists(segment_file):
                        os.remove(segment_file)
                if os.path.exists(concat_list):
                    os.remove(concat_list)
                
                return True
            except subprocess.CalledProcessError as e_final:
                print(f"  所有方法都失败了: {e_final}")
                return False
    finally:
        # 清理临时文件
        try:
            if os.path.exists(filter_script_path):
                os.remove(filter_script_path)
        except Exception as e:
            print(f"  无法删除临时文件 {filter_script_path}: {e}")


def _finalize_processing(successful_exports, latest_time, state_file, all_files_info):
    """完成处理并更新状态"""
    if successful_exports > 0:
        print(f"\n处理完成，共成功导出 {successful_exports} 个连杀片段。")
        # 更新状态文件
        if latest_time:
            print(f"将更新上次处理时间为: {latest_time}")
            save_last_processed_time(latest_time, state_file)
    elif not all_files_info:
        pass  # 没有新文件处理，无需更新状态
    else:
        print("\n本次运行没有成功导出任何片段，不更新上次处理时间。") 