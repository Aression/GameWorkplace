#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
命令行入口点，允许直接运行包
"""

import os
import sys
import tempfile
import argparse
from pathlib import Path

from exporter.core.processor import process_videos
from exporter.utils.file_utils import convert_windows_path
from exporter.utils.constants import TYPICAL_VIDEO_LENGTH, TYPICAL_KILL_POSITION

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='战雷连杀片段导出工具')
    
    parser.add_argument('-i', '--input-dir', required=True,
                        help='输入目录，包含战雷录像文件')
    
    parser.add_argument('-o', '--output-dir', required=True,
                        help='输出目录，保存处理后的视频片段')
    
    parser.add_argument('--lead', type=int, default=10,
                       help='击杀前保留时间（秒），默认为10')
    
    parser.add_argument('--tail', type=int, default=5,
                       help='击杀后保留时间（秒），默认为5')
    
    parser.add_argument('--threshold', type=int, default=30,
                       help='连杀间隔阈值（秒），默认为30')
    
    parser.add_argument('--min-kills', type=int, default=2,
                       help='最少击杀数，默认为2')
    
    parser.add_argument('--state-file', 
                       help='状态文件路径，用于记录处理进度')
    
    parser.add_argument('--temp-dir',
                       help='临时文件目录，默认为系统临时目录')
    
    return parser.parse_args()

def main():
    """主函数"""
    args = parse_args()
    
    # 处理输入和输出路径
    input_dir = convert_windows_path(args.input_dir)
    output_dir = convert_windows_path(args.output_dir)
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 临时目录配置 - 如果未指定则使用输出目录下的temp子目录
    temp_dir = args.temp_dir
    
    print("开始视频处理任务...")
    print(f"输入目录: {input_dir}")
    print(f"输出目录: {output_dir}")
    print(f"连杀参数: Lead={args.lead}s, Tail={args.tail}s, Threshold={args.threshold}s, Min Kills={args.min_kills}")
    print(f"状态文件: {args.state_file or '默认'}")
    print(f"临时目录: {temp_dir or '使用输出目录下的temp目录'}")
    
    # 执行处理
    try:
        exported = process_videos(
            input_dir=input_dir,
            output_dir=output_dir,
            lead=args.lead,
            tail=args.tail,
            threshold=args.threshold,
            min_kills=args.min_kills,
            state_file=args.state_file,
            temp_dir=temp_dir
        )
        
        print(f"\n视频处理任务完成，共导出 {exported} 个连杀片段。")
        return 0
    except Exception as e:
        print(f"处理过程中发生错误: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 