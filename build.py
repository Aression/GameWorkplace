#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
战雷连杀片段导出工具打包脚本
使用PyInstaller打包为Windows可执行程序
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# 打包配置
APP_NAME = "战雷连杀导出工具"
VERSION = "1.0.1"
MAIN_SCRIPT = "wt_killstreak_exporter.py"
ICON_FILE = "icon.ico"  # 如果有图标文件
INCLUDE_FILES = []  # 需要包含的额外文件

def run_command(cmd, cwd=None):
    """运行命令并打印输出"""
    print(f"Running: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT,
        text=True,
        cwd=cwd
    )
    
    for line in process.stdout:
        print(line.rstrip())
    
    process.wait()
    return process.returncode

def clean_build_dirs():
    """清理构建目录"""
    print("清理构建目录...")
    dirs_to_clean = ["build", "dist"]
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            print(f"  删除 {dir_name}/ 目录")
            shutil.rmtree(dir_name)
    
    spec_file = f"{APP_NAME}.spec"
    if os.path.exists(spec_file):
        print(f"  删除 {spec_file} 文件")
        os.remove(spec_file)

def build_exe():
    """构建可执行文件"""
    # 准备PyInstaller命令
    cmd = [
        "pyinstaller",
        "--clean",
        "--name", APP_NAME,
        "--onedir",  # 创建一个目录包含可执行文件和依赖
        "--noconsole",  # 无控制台窗口
        "--windowed",  # 无控制台窗口
        "--noconfirm",
    ]
    
    # 添加图标
    if os.path.exists(ICON_FILE):
        cmd.extend(["--icon", ICON_FILE])
    
    # 添加主脚本
    cmd.append(MAIN_SCRIPT)
    
    # 运行PyInstaller
    return run_command(cmd)

def copy_additional_files():
    """复制额外需要的文件到dist目录"""
    dist_dir = Path("dist") / APP_NAME
    
    # 确保目标目录存在
    if not dist_dir.exists():
        print(f"错误: 目标目录不存在: {dist_dir}")
        return False
    
    # 复制README
    if os.path.exists("README.md"):
        print("复制 README.md 到dist目录")
        shutil.copy2("README.md", dist_dir / "README.md")
    
    # 复制许可证
    if os.path.exists("LICENSE"):
        print("复制 LICENSE 到dist目录")
        shutil.copy2("LICENSE", dist_dir / "LICENSE")
    
    # 复制其他文件
    for file_path in INCLUDE_FILES:
        if os.path.exists(file_path):
            target_path = dist_dir / os.path.basename(file_path)
            print(f"复制 {file_path} 到 {target_path}")
            shutil.copy2(file_path, target_path)
    
    return True

def create_zip_archive():
    """创建ZIP归档文件"""
    dist_dir = Path("dist")
    app_dir = dist_dir / APP_NAME
    zip_file = dist_dir / f"{APP_NAME}_v{VERSION}.zip"
    
    print(f"正在创建ZIP归档: {zip_file}")
    shutil.make_archive(
        zip_file.with_suffix(""),  # 不带扩展名的路径
        "zip",
        dist_dir,
        APP_NAME
    )
    print(f"ZIP归档创建完成: {zip_file}")
    
    return True

def main():
    """主打包流程"""
    print(f"===== 开始打包 {APP_NAME} v{VERSION} =====")
    
    # 检查依赖
    try:
        import PyInstaller
        print(f"PyInstaller版本: {PyInstaller.__version__}")
    except ImportError:
        print("错误: 未安装PyInstaller. 请先运行: pip install pyinstaller")
        return 1
    
    # 清理旧的构建文件
    clean_build_dirs()
    
    # 构建.exe
    print("\n===== 正在构建可执行文件 =====")
    if build_exe() != 0:
        print("错误: PyInstaller构建失败!")
        return 1
    
    # 复制额外文件
    print("\n===== 正在复制额外文件 =====")
    if not copy_additional_files():
        print("警告: 复制额外文件失败")
    
    # 创建ZIP归档
    print("\n===== 正在创建发布包 =====")
    if not create_zip_archive():
        print("警告: 创建ZIP归档失败")
    
    print(f"\n===== 打包完成! =====")
    print(f"可执行文件位于: dist/{APP_NAME}/{APP_NAME}.exe")
    print(f"发布ZIP包: dist/{APP_NAME}_v{VERSION}.zip")
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 