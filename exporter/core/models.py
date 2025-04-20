#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视频处理模型定义
"""

from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Tuple


@dataclass
class TimeSegment:
    """表示一个连杀时间段"""
    start_time: datetime
    end_time: datetime
    videos: List[Dict] = None
    kill_times: List[datetime] = None
    
    def __init__(self, start_time, end_time, video=None):
        self.start_time = start_time
        self.end_time = end_time
        self.videos = []
        self.kill_times = []
        
        if video:
            self.videos.append(video)
            self.kill_times.append(video["kill"])
    
    def extend(self, other):
        """扩展时间段，合并另一个段"""
        self.end_time = max(self.end_time, other.end_time)
        self.videos.extend(other.videos)
        self.kill_times.extend(other.kill_times)
        
        # 去重
        self.videos = list({v['path']: v for v in self.videos}.values())
        self.kill_times = sorted(list(set(self.kill_times)))
    
    def duration(self):
        """获取时间段持续时间（秒）"""
        delta = self.end_time - self.start_time
        return delta.total_seconds()
    
    def __str__(self):
        kill_count = len(self.kill_times) if self.kill_times else 0
        return f"时间段: {self.start_time} -> {self.end_time} (持续: {self.duration():.1f}秒, 击杀: {kill_count}次)"


@dataclass
class DuplicateSegment:
    """表示一个重复的视频片段"""
    segment1_start: float  # 第一个片段开始时间（秒）
    segment1_end: float    # 第一个片段结束时间（秒）
    segment2_start: float  # 第二个片段开始时间（秒）
    segment2_end: float    # 第二个片段结束时间（秒）
    similarity: float      # 相似度得分
    
    def segment1_duration(self) -> float:
        """获取第一个片段的持续时间"""
        return self.segment1_end - self.segment1_start
    
    def segment2_duration(self) -> float:
        """获取第二个片段的持续时间"""
        return self.segment2_end - self.segment2_start
    
    def __str__(self):
        return (f"重复片段: {self.segment1_start:.2f}-{self.segment1_end:.2f}秒 和 "
                f"{self.segment2_start:.2f}-{self.segment2_end:.2f}秒 "
                f"(相似度: {self.similarity:.2f})")


@dataclass
class VideoProcessingOptions:
    """视频处理选项"""
    use_gpu: bool = True               # 是否使用GPU加速
    remove_duplicates: bool = True     # 是否移除重复帧
    duplicate_threshold: int = 5       # 重复帧检测阈值（越小越严格）
    frame_sample_rate: int = 10        # 帧采样率（每N帧采样一次）
    hash_size: int = 16                # 哈希大小
    min_duplicate_length: float = 1.0  # 最小考虑的重复片段长度（秒）


def merge_overlapping_segments(segments: List[TimeSegment]) -> List[TimeSegment]:
    """合并重叠的时间段
    
    Args:
        segments: 时间段列表
        
    Returns:
        合并后的时间段列表
    """
    if not segments:
        return []
    
    # 按开始时间排序
    sorted_segments = sorted(segments, key=lambda x: x.start_time)
    
    merged = [sorted_segments[0]]
    
    for current in sorted_segments[1:]:
        last = merged[-1]
        
        # 检查是否有重叠
        if current.start_time <= last.end_time:
            # 合并段
            last.extend(current)
        else:
            # 添加新段
            merged.append(current)
    
    return merged


def filter_duplicates_from_segments(duplicates: List[DuplicateSegment], 
                                    segments: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """基于检测到的重复片段过滤时间段
    
    Args:
        duplicates: 检测到的重复片段列表
        segments: 原始时间段列表 [(start, end), ...]
        
    Returns:
        过滤后的时间段列表
    """
    if not duplicates:
        return segments
    
    # 排序重复片段，按第二段的开始时间
    duplicates.sort(key=lambda x: x.segment2_start)
    
    # 创建时间掩码，标记哪些时间需要保留
    filtered_segments = []
    
    for start, end in segments:
        # 检查当前段是否是某个重复片段的第二部分
        is_duplicate = False
        duplicate_replaced = False
        
        for dup in duplicates:
            # 检查当前段是否与重复片段的第二部分有重叠
            if not (end <= dup.segment2_start or start >= dup.segment2_end):
                # 有重叠，这是一个重复片段
                is_duplicate = True
                
                # 第一次遇到重复段时，添加第一部分作为替代
                if not duplicate_replaced:
                    # 添加第一段作为替代
                    filtered_segments.append((dup.segment1_start, dup.segment1_end))
                    duplicate_replaced = True
                
                break
        
        # 如果不是重复片段，保留原始段
        if not is_duplicate:
            filtered_segments.append((start, end))
    
    # 合并重叠的段
    if filtered_segments:
        filtered_segments.sort()
        merged = [filtered_segments[0]]
        
        for current_start, current_end in filtered_segments[1:]:
            prev_start, prev_end = merged[-1]
            
            # 检查是否有重叠
            if current_start <= prev_end:
                # 扩展上一个段
                merged[-1] = (prev_start, max(prev_end, current_end))
            else:
                # 添加新段
                merged.append((current_start, current_end))
        
        return merged
    
    return [] 