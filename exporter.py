import os
import re
import subprocess
from datetime import datetime, timedelta
import json # 用于持久化状态
import time

# 为Windows系统添加startupinfo配置
import sys
import platform

# 创建隐藏窗口的startupinfo对象
def get_startupinfo():
    """根据平台返回适当的startupinfo对象，用于隐藏命令行窗口"""
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        return startupinfo
    return None

STATE_FILE = 'processing_state.json' # 状态文件名

def parse_video_time(filename):
    """解析文件名中的时间信息"""
    # 支持多种常见模式:
    # War Thunder 2024.06.18 - 19.29.51.02.DVR.mp4  (旧格式)
    # War Thunder 2025.04.14 - 14.00.35.105.DVR.mp4 (新格式)
    # War Thunder 2025.04.12 - 20.01.55.06.DVR.mp4  (另一种格式)
    
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
            '-preset', 'p7',
            '-rc', 'vbr',
            '-cq', '20',
            '-b:v', '8M',
            '-maxrate', '10M',
            '-bufsize', '20M',
            '-c:a', 'aac',
            '-b:a', '192k',
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
                '-preset', 'fast',
                '-crf', '18',
                '-b:v', '8M',
                '-maxrate', '10M',
                '-bufsize', '20M',
                '-c:a', 'aac',
                '-b:a', '192k',
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
            '-preset', 'p7',
            '-rc', 'vbr',
            '-cq', '20',
            '-b:v', '8M',
            '-maxrate', '10M',
            '-bufsize', '20M',
            '-c:a', 'aac',
            '-b:a', '192k',
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
                '-preset', 'fast',
                '-crf', '18',
                '-b:v', '8M',
                '-maxrate', '10M',
                '-bufsize', '20M',
                '-c:a', 'aac',
                '-b:a', '192k',
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


class TimeSegment:
    """表示一个时间段，用于区间合并"""
    def __init__(self, start_time, end_time, video_info=None):
        self.start_time = start_time
        self.end_time = end_time
        self.video_infos = [video_info] if video_info else []  # 用于跟踪此段对应的视频文件信息
        self.kill_times = []  # 此段中的击杀时间点
        if video_info and "kill" in video_info:  # 修改为字典键检查
            self.kill_times.append(video_info["kill"])
    
    def duration(self):
        """返回时间段的持续时间（秒）"""
        return (self.end_time - self.start_time).total_seconds()
    
    def overlaps(self, other):
        """判断是否与另一个时间段重叠"""
        return self.start_time <= other.end_time and other.start_time <= self.end_time
    
    def contains(self, time_point):
        """判断是否包含某个时间点"""
        return self.start_time <= time_point <= self.end_time
    
    def extend(self, other):
        """扩展当前时间段以包含另一个时间段"""
        self.start_time = min(self.start_time, other.start_time)
        self.end_time = max(self.end_time, other.end_time)
        # 合并视频信息
        for video_info in other.video_infos:
            if video_info not in self.video_infos:
                self.video_infos.append(video_info)
        # 合并击杀时间点
        for kill_time in other.kill_times:
            if kill_time not in self.kill_times:
                self.kill_times.append(kill_time)
        # 保持击杀时间排序
        self.kill_times.sort()
    
    def __repr__(self):
        return f"TimeSegment({self.start_time} -> {self.end_time}, kills={len(self.kill_times)})"


def merge_overlapping_segments(segments):
    """合并重叠的时间段"""
    if not segments:
        return []
    
    # 按开始时间排序
    sorted_segments = sorted(segments, key=lambda x: x.start_time)
    merged = [sorted_segments[0]]
    
    for segment in sorted_segments[1:]:
        last = merged[-1]
        # 如果当前段与上一个合并段重叠，则扩展上一个段
        if last.overlaps(segment):
            last.extend(segment)
        else:
            # 否则添加为新段
            merged.append(segment)
    
    return merged


def process_videos(input_dir, output_dir, lead=10, tail=2, threshold=30, min_kills=2, progress_callback=None, state_file=None, temp_dir=None, is_running=None):
    """处理视频文件，跳过已处理的，并保存状态"""
    
    # 载入录像常量参数 (一般Shadow Play录制的视频长度为40秒，击杀约在第20秒)
    TYPICAL_VIDEO_LENGTH = 40  # 典型视频长度（秒）
    TYPICAL_KILL_POSITION = 20  # 击杀通常出现在视频的位置（秒）
    
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
    
    for fname in mp4_files:
        # 检查是否应该停止处理
        if is_running is not None and not is_running():
            print("用户取消处理，正在退出...")
            return 0
            
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
        # 假设击杀时间仍在视频开始后20秒（这个假设可能需要改进）
        kill_time = start_time + timedelta(seconds=min(20, duration_sec / 2)) # 取20秒或时长一半的较小值

        all_files_info.append({
            "path": full_path,
            "start": start_time,
            "kill": kill_time, # 用于排序和分组逻辑
            "end": end_time,   # 实际视频结束时间
            "filename": fname,
            "duration": duration_sec
        })
        
        # 更新扫描进度
        if progress_callback:
            progress_callback(processed_files, total_files, f"扫描: {fname}")

    print(f"扫描完成: 找到 {len(all_files_info)} 个新视频文件，跳过 {skipped_count} 个已处理或过早的视频。")

    if not all_files_info:
        print("未找到需要处理的新视频文件。")
        return 0

    # 按 kill 时间排序（注意：kill 时间是基于假设的）
    videos = sorted(all_files_info, key=lambda x: x["kill"])
    
    # 记录本次处理的最后一个视频的开始时间，用于更新状态
    latest_video_time_in_batch = videos[-1]['start'] 

    # 为每个击杀创建一个时间段（击杀前lead秒到击杀后tail秒）
    kill_segments = []
    for video in videos:
        # 检查是否应该停止处理
        if is_running is not None and not is_running():
            print("用户取消处理，正在退出...")
            return 0
            
        kill_time = video["kill"]
        segment_start = kill_time - timedelta(seconds=lead)
        segment_end = kill_time + timedelta(seconds=tail)
        segment = TimeSegment(segment_start, segment_end, video)
        kill_segments.append(segment)
    
    # 合并间隔小于阈值的时间段
    # 首先，以时间顺序排序所有段
    kill_segments.sort(key=lambda x: x.start_time)
    
    # 初始化合并结果列表
    merged_segments = [kill_segments[0]]
    
    # 开始合并过程
    for i in range(1, len(kill_segments)):
        current = kill_segments[i]
        last = merged_segments[-1]
        
        # 计算时间间隔（从上一段的结束到当前段的开始）
        time_gap = (current.start_time - last.end_time).total_seconds()
        
        # 如果间隔小于阈值，合并段
        if time_gap <= threshold:
            last.extend(current)
        else:
            # 否则添加为新段
            merged_segments.append(current)
    
    # 过滤掉击杀次数不足的段
    valid_segments = [seg for seg in merged_segments if len(seg.kill_times) >= min_kills]
    
    print(f"识别出 {len(valid_segments)} 个连杀时间段 (最少 {min_kills} 次击杀，间隔 <= {threshold} 秒)")

    # 处理每个合并后的时间段
    successful_exports = 0
    temp_file_counter = 0 # 用于生成唯一的临时文件名
    
    # 更新处理进度
    segment_count = len(valid_segments)
    
    for idx, segment in enumerate(valid_segments, 1):
        # 检查是否应该停止处理
        if is_running is not None and not is_running():
            print("用户取消处理，正在退出...")
            return 0
            
        # 更新段处理进度
        if progress_callback:
            progress_callback(idx-1, segment_count, f"处理连杀片段 {idx}/{segment_count} (击杀数: {len(segment.kill_times)})")
        
        print(f"\n处理第 {idx} 个连杀片段 (击杀数: {len(segment.kill_times)})")
        print(f"  时间范围: {segment.start_time} -> {segment.end_time}")
        print(f"  击杀时间点: {segment.kill_times}")
        
        # 计算调整后的时间段，确保包含所有击杀前后的时间
        first_kill = min(segment.kill_times)
        last_kill = max(segment.kill_times)
        adjusted_start = first_kill - timedelta(seconds=lead)
        adjusted_end = last_kill + timedelta(seconds=tail)
        
        # 更新段的时间范围，确保覆盖从第一个击杀到最后一个击杀的完整时间范围
        segment.start_time = adjusted_start
        segment.end_time = adjusted_end
        print(f"  调整后时间范围: {segment.start_time} -> {segment.end_time}")
        print(f"  击杀时间点的有效范围: {first_kill} -> {last_kill}")
        
        # 获取与此段重叠的所有原始视频文件
        relevant_videos = []
        for video in videos:
            video_start = video["start"]
            video_end = video["end"]
            # 检查视频是否与该段时间重叠
            if (video_start <= segment.end_time and video_end >= segment.start_time):
                relevant_videos.append(video)
        
        print(f"  涉及原始文件: {[v['filename'] for v in relevant_videos]}")
        
        # 创建该时间段完整的时间线
        timeline_segments = []
        
        # 对每个录像时段进行处理，尝试创建更连续的观感
        kill_times_sorted = sorted(segment.kill_times)
        
        # 如果录像片段恰好覆盖了所有击杀点，直接使用
        all_kills_covered = False
        for video in relevant_videos:
            video_start = video["start"]
            video_end = video["end"]
            if (video_start <= adjusted_start and video_end >= adjusted_end):
                # 一个视频完全包含了所有击杀
                all_kills_covered = True
                timeline_segment = TimeSegment(adjusted_start, adjusted_end, video)
                timeline_segment.kill_times = kill_times_sorted.copy()
                timeline_segments.append(timeline_segment)
                print(f"  找到完全覆盖所有击杀的视频: {video['filename']}")
                break
                
        # 如果没有单个视频覆盖所有击杀，需要拼接多段
        if not all_kills_covered:
            print(f"  需要拼接多个片段以覆盖所有击杀")
            
            # 按击杀点对相关视频进行处理
            for i, kill_time in enumerate(kill_times_sorted):
                # 找出包含此击杀的视频
                kill_video = None
                for video in relevant_videos:
                    if video["start"] <= kill_time <= video["end"]:
                        kill_video = video
                        break
                
                if not kill_video:
                    print(f"  警告: 无法找到包含击杀时间点 {kill_time} 的视频，跳过")
                    continue
                
                # 计算剪辑点
                video_start = kill_video["start"]
                video_end = kill_video["end"]
                
                # 计算当前击杀在视频中的位置（秒）
                kill_position_in_video = (kill_time - video_start).total_seconds()
                
                # 根据录像和击杀特点计算最佳剪辑区间
                segment_start = max(video_start, kill_time - timedelta(seconds=min(kill_position_in_video, lead)))
                
                # 处理视频结尾
                remaining_video = (video_end - kill_time).total_seconds()
                segment_end = min(video_end, kill_time + timedelta(seconds=min(remaining_video, tail)))
                
                # 特殊逻辑：当有连续击杀且间隔小于阈值但大于典型录像结尾时
                if i < len(kill_times_sorted) - 1:
                    next_kill = kill_times_sorted[i + 1]
                    time_to_next_kill = (next_kill - kill_time).total_seconds()
                    
                    if time_to_next_kill <= threshold:
                        # 计算这段录像还剩多少时间
                        time_left_in_video = (video_end - kill_time).total_seconds()
                        
                        # 如果这段录像无法覆盖到下一个击杀，那么就不要剪切太多末尾
                        # 以免造成太多不必要的跳跃感
                        if time_left_in_video < time_to_next_kill:
                            # 留下可以看得见击杀的合理结尾
                            ideal_tail = min(time_left_in_video, TYPICAL_VIDEO_LENGTH - TYPICAL_KILL_POSITION)
                            segment_end = kill_time + timedelta(seconds=ideal_tail)
                
                # 创建时间段
                timeline_segment = TimeSegment(segment_start, segment_end, kill_video)
                timeline_segment.kill_times = [kill_time]  # 记录此段包含的击杀点
                
                # 检查是否有其他击杀点也落在此区间
                for other_kill in kill_times_sorted:
                    if other_kill != kill_time and segment_start <= other_kill <= segment_end:
                        timeline_segment.kill_times.append(other_kill)
                
                timeline_segments.append(timeline_segment)
            
            # 合并重叠的时间段，确保不出现短小碎片
            timeline_segments = merge_overlapping_segments(timeline_segments)
        
        # 确保时间段按时间顺序排序
        timeline_segments.sort(key=lambda x: x.start_time)
        
        print(f"  分析得到 {len(timeline_segments)} 个连续时间段")
        
        # 输出每个连续片段包含的击杀点数量和时间
        for seg_idx, seg in enumerate(timeline_segments):
            kill_counts = len(seg.kill_times)
            kill_times_str = ", ".join([kt.strftime('%H:%M:%S') for kt in sorted(seg.kill_times)])
            duration = seg.duration()
            print(f"  片段 {seg_idx+1}: 持续 {duration:.1f}秒，包含 {kill_counts} 个击杀点 ({kill_times_str})")
        
        # 为每个连续段剪辑视频片段
        temp_clips = []
        
        for seg_idx, seg in enumerate(timeline_segments):
            # 检查是否应该停止处理
            if is_running is not None and not is_running():
                print("用户取消处理，正在退出...")
                return 0
                
            # 更新剪辑进度
            if progress_callback:
                sub_progress = f"剪辑片段 {seg_idx+1}/{len(timeline_segments)}"
                progress_callback(idx-1, segment_count, sub_progress)
            
            # 为这个时间段选择最佳的源视频
            # 简单策略：选择包含时间段最长的视频
            best_video = None
            best_overlap = 0
            
            for video_info in seg.video_infos:
                video_start = video_info["start"]
                video_end = video_info["end"]
                
                overlap_start = max(video_start, seg.start_time)
                overlap_end = min(video_end, seg.end_time)
                overlap_duration = (overlap_end - overlap_start).total_seconds()
                
                if overlap_duration > best_overlap:
                    best_overlap = overlap_duration
                    best_video = video_info
            
            if not best_video:
                print(f"  警告: 无法为时间段 {seg} 找到合适的源视频，跳过")
                continue
            
            # 计算在源视频中的剪切点
            start_sec_in_video = max(0, (seg.start_time - best_video["start"]).total_seconds())
            duration_sec_to_cut = (seg.end_time - seg.start_time).total_seconds()
            
            temp_file_counter += 1
            temp_output_filename = f"temp_{idx}_{temp_file_counter}_{os.path.basename(best_video['path'])}"
            
            # 根据是否指定了temp_dir决定临时文件的存放位置
            if temp_dir and os.path.isdir(temp_dir):
                temp_output_path = os.path.join(temp_dir, temp_output_filename)
            else:
                temp_output_path = os.path.join(output_dir, temp_output_filename)
            
            print(f"  准备剪切第 {seg_idx+1}/{len(timeline_segments)} 段: {best_video['path']}")
            print(f"    源时间: {best_video['start']} -> {best_video['end']}")
            print(f"    目标段: {seg.start_time} -> {seg.end_time}")
            print(f"    剪切参数: 从 {start_sec_in_video:.2f} 秒开始，持续 {duration_sec_to_cut:.2f} 秒")
            
            if cut_video(best_video["path"], temp_output_path, start_sec_in_video, duration_sec_to_cut):
                temp_clips.append(temp_output_path)
            else:
                print(f"  剪切失败: {best_video['path']}")
        
        if not temp_clips:
            print(f"  组 {idx} 没有生成有效的临时片段，无法合并。")
            continue
            
        # 合并当前组的所有临时片段
        # 优化输出文件名，包含日期和组信息
        first_kill_time_str = segment.kill_times[0].strftime('%Y%m%d_%H%M%S')
        final_output_filename = f"连杀{len(segment.kill_times)}_{first_kill_time_str}_组{idx}.mp4"
        final_output_path = os.path.join(output_dir, final_output_filename)
        
        # 更新合并进度
        if progress_callback:
            progress_callback(idx-1, segment_count, f"合并片段: {final_output_filename}")
        
        print(f"  准备合并 {len(temp_clips)} 个片段 -> {final_output_path}")
        if len(temp_clips) == 1:
            # 如果只有一个临时片段，直接重命名
            try:
                os.rename(temp_clips[0], final_output_path)
                print(f"成功导出连杀片段: {final_output_path} (单片段直接重命名)")
                successful_exports += 1
            except Exception as e:
                print(f"重命名失败 {temp_clips[0]} -> {final_output_path}: {e}")
                try:
                    # 尝试复制而不是重命名
                    import shutil
                    shutil.copy2(temp_clips[0], final_output_path)
                    os.remove(temp_clips[0])
                    print(f"成功导出连杀片段: {final_output_path} (通过复制完成)")
                    successful_exports += 1
                except Exception as e2:
                    print(f"复制也失败了: {e2}")
        else:
            # 需要合并多个片段
            if concat_videos(temp_clips, final_output_path, temp_dir=temp_dir):
                print(f"成功导出连杀片段: {final_output_path}")
                successful_exports += 1
            else:
                print(f"导出失败: {final_output_path}")
                # 保留临时文件供调试
    
    # 更新最终进度
    if progress_callback:
        progress_callback(segment_count, segment_count, "处理完成")

    # 处理完成所有组后
    if successful_exports > 0:
        print(f"\n处理完成，共成功导出 {successful_exports} 个连杀片段。")
        # 更新状态文件，记录本次处理的最后一个视频的开始时间
        print(f"将更新上次处理时间为: {latest_video_time_in_batch}")
        save_last_processed_time(latest_video_time_in_batch, state_file)
    elif not all_files_info:
        pass # 没有新文件处理，无需更新状态
    else:
        print("\n本次运行没有成功导出任何片段，不更新上次处理时间。")
        
    return successful_exports


def convert_windows_path(path):
    """将Windows路径转换为Python程序能识别的路径"""
    return path.replace('\\', '/')

if __name__ == "__main__":
    # === 配置参数 ===
    # 注意：请确保 ffprobe 和 ffmpeg 在系统 PATH 中，或者提供完整路径
    # 示例： INPUT_DIR = "D:/GameVideos/ShadowPlay/War Thunder"
    INPUT_DIR = convert_windows_path("D:\GameVideos\9343b833-e7af-42ea-8a61-31bc41eefe2b\War Thunder")
    # 示例： OUTPUT_DIR = "D:/GameWorkplace/WT_Exports"
    OUTPUT_DIR = convert_windows_path("D:\GameWorkplace\exported")
    
    LEAD_TIME = 10        # 第一次击杀前保留时间（秒）
    TAIL_TIME = 5         # 最后一次击杀后保留时间（秒） - 稍微增加一点
    KILL_THRESHOLD = 30   # 两次击杀视为连杀的最大间隔（秒）
    MIN_KILLS = 2         # 构成连杀的最少击杀次数
    STATE_FILE_PATH = None # 自定义状态文件路径，默认使用模块中定义的 STATE_FILE
    
    # 临时目录配置
    import tempfile
    TEMP_DIR = tempfile.gettempdir()  # 使用系统临时目录
    # ===============

    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("开始视频处理任务...")
    print(f"输入目录: {INPUT_DIR}")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"连杀参数: Lead={LEAD_TIME}s, Tail={TAIL_TIME}s, Threshold={KILL_THRESHOLD}s, Min Kills={MIN_KILLS}")
    print(f"状态文件: {STATE_FILE_PATH or STATE_FILE} (默认)")
    print(f"临时目录: {TEMP_DIR}")
    
    # 执行处理
    process_videos(
        input_dir=INPUT_DIR,
        output_dir=OUTPUT_DIR,
        lead=LEAD_TIME,
        tail=TAIL_TIME,
        threshold=KILL_THRESHOLD,
        min_kills=MIN_KILLS,
        state_file=STATE_FILE_PATH,
        temp_dir=TEMP_DIR
    )
    
    print("\n视频处理任务结束。")
