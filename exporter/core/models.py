#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据模型定义模块
"""

from datetime import datetime, timedelta

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