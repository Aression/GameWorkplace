import random
from datetime import datetime, timedelta
from collections import Counter
import time

def generate_random_kill_timestamps(num_kills=random.randint(2, 10), base_time=None, max_time_delta=60):
    """生成指定数量的随机击杀时间戳，模拟40s视频中事件的分布。"""
    if base_time is None:
        base_time = datetime(2025, 4, 21, 10, 0, 0)
    timestamps = sorted([
        (base_time + timedelta(seconds=random.uniform(0, 40))).isoformat(timespec='microseconds') + "Z"
        for _ in range(num_kills)
    ])
    return timestamps

def calculate_target_intervals(kill_timestamps):
    """计算每个击杀事件的目标剪辑区间。"""
    target_intervals = []
    for ts_str in kill_timestamps:
        kill_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        start_time = kill_time - timedelta(seconds=15)
        end_time = kill_time + timedelta(seconds=5)
        target_intervals.append((start_time, end_time))
    return target_intervals

def merge_overlapping_intervals(intervals):
    """合并重叠的时间区间。"""
    if not intervals:
        return []

    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged_intervals = [sorted_intervals[0]]

    for current_start, current_end in sorted_intervals[1:]:
        prev_start, prev_end = merged_intervals[-1]
        if current_start <= prev_end:
            merged_intervals[-1] = (prev_start, max(prev_end, current_end))
        else:
            merged_intervals.append((current_start, current_end))

    return merged_intervals

def verify_results(kill_timestamps, merged_intervals):
    """检验合并后的区间是否正确覆盖了所有需要的击杀时间范围。"""
    all_covered = True
    for ts_str in kill_timestamps:
        kill_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        covered = False
        for start, end in merged_intervals:
            if start <= kill_time <= end:
                covered = True
                break
        if not covered:
            all_covered = False
            return False
    return True

if __name__ == "__main__":
    num_tests = 1000000
    successful_merges = 0
    total_merged_intervals = 0
    start_time = time.time()

    for i in range(num_tests):
        kill_timestamps = generate_random_kill_timestamps()
        target_intervals = calculate_target_intervals(kill_timestamps)
        merged_intervals = merge_overlapping_intervals(target_intervals)
        if verify_results(kill_timestamps, merged_intervals):
            successful_merges += 1
            total_merged_intervals += len(merged_intervals)

        if (i + 1) % 100000 == 0:
            elapsed_time = time.time() - start_time
            print(f"Processed {i+1}/{num_tests} tests. Elapsed time: {elapsed_time:.2f} seconds. Success rate: {successful_merges / (i + 1) * 100:.2f}%")

    end_time = time.time()
    total_time = end_time - start_time
    average_merged_intervals = total_merged_intervals / successful_merges if successful_merges > 0 else 0

    print("\n--- 最终评估结果 ---")
    print(f"总共运行测试次数: {num_tests}")
    print(f"成功合并所有击杀事件的次数: {successful_merges}")
    print(f"成功率: {successful_merges / num_tests * 100:.2f}%")
    print(f"平均合并后的区间数 (仅针对成功案例): {average_merged_intervals:.2f}")
    print(f"总耗时: {total_time:.2f} seconds")