#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
构建脚本 - 用于打包连杀片段导出工具
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 构建配置
APP_NAME = "战雷连杀导出工具"
MAIN_SCRIPT = "wt_killstreak_exporter.py"
ICON_FILE = "icon.ico"
VERSION_FILE = "exporter/__init__.py"

def get_version():
    """从版本文件中获取当前版本号"""
    version_pattern = r'__version__\s*=\s*["\']([^"\']+)["\']'
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        content = f.read()
        match = re.search(version_pattern, content)
        if match:
            return match.group(1)
    return "1.0.0"  # 默认版本号

def update_version(version_str=None):
    """更新版本号"""
    current_version = get_version()
    if not version_str:
        # 自动增加版本号的补丁版本部分
        parts = current_version.split('.')
        if len(parts) >= 3:
            parts[2] = str(int(parts[2]) + 1)
        version_str = '.'.join(parts)
    
    # 更新版本文件
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    
    content = re.sub(
        r'__version__\s*=\s*["\']([^"\']+)["\']',
        f'__version__ = "{version_str}"',
        content
    )
    
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"版本号从 {current_version} 更新到 {version_str}")
    return version_str

def clean_build_dir():
    """清理构建目录"""
    print("清理构建目录...")
    dirs_to_clean = ["build", "dist"]
    
    for dir_path in dirs_to_clean:
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
            print(f"已删除: {dir_path}")

def create_resource_dirs():
    """创建资源目录"""
    print("创建资源目录...")
    
    # 确保ico文件存在
    if not os.path.exists(ICON_FILE):
        print(f"警告: 图标文件 {ICON_FILE} 不存在！将使用默认图标。")

def build_executable():
    """构建可执行文件"""
    icon_param = f"--icon={ICON_FILE}" if os.path.exists(ICON_FILE) else ""
    version = get_version()
    
    print(f"开始构建 {APP_NAME} v{version}...")
    
    # 不需要的模块列表 - 优化打包大小
    exclude_modules = [
        "matplotlib",
        "notebook", 
        "scipy", 
        "pandas",
        "tensorboard",
        "tensorflow",
        "torch",
        "cv2",
        "scikit-learn",
        "sphinx",
        "pytest",
        "IPython",
        "numpy.distutils",
        "numpy.testing",
        "docutils",
        "cython",
        "lib2to3",
        "tkinter",
        "pydoc",
        "unittest",
        "xml.dom",
        "email.mime"
    ]
    
    # 需要显式包含的隐藏导入
    hidden_imports = [
        "PyQt5.QtPrintSupport",
        "PyQt5.QtWidgets",
        "PyQt5.QtCore",
        "PyQt5.QtGui"
    ]
    
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        f"--name={APP_NAME}",
        icon_param,
    ]
    
    # 添加icon.png如果存在
    if os.path.exists("icon.png"):
        cmd.extend(["--add-data", "icon.png;."])
    else:
        print("警告: icon.png文件不存在，将不会被包含在打包中。")
    
    # 添加需要排除的模块
    for module in exclude_modules:
        cmd.extend(["--exclude-module", module])
    
    # 添加隐藏导入
    for module in hidden_imports:
        cmd.extend(["--hidden-import", module])
    
    # 添加主脚本
    cmd.append(MAIN_SCRIPT)
    
    # 过滤掉空字符串
    cmd = [c for c in cmd if c]
    
    print(f"运行命令: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    # 复制其他需要的文件
    copy_additional_files()
    
    print(f"构建完成! 可执行文件位于 dist/{APP_NAME}/ 目录下")
    return True

def copy_additional_files():
    """复制额外需要的文件到打包目录"""
    dst_dir = f"dist/{APP_NAME}"
    os.makedirs(dst_dir, exist_ok=True)
    
    # 复制README和LICENSE文件
    for file in ["README.md", "LICENSE"]:
        if os.path.exists(file):
            shutil.copy2(file, os.path.join(dst_dir, file))
            print(f"已复制 {file} 到输出目录")

def main():
    """主函数"""
    print("=" * 60)
    print(f"构建工具 - {APP_NAME}")
    print("=" * 60)
    
    # 命令行参数
    if len(sys.argv) > 1:
        if sys.argv[1] == "--clean":
            clean_build_dir()
            return
        elif sys.argv[1] == "--version":
            ver = get_version()
            print(f"当前版本: {ver}")
            return
        elif sys.argv[1] == "--update-version":
            if len(sys.argv) > 2:
                ver = update_version(sys.argv[2])
            else:
                ver = update_version()
            print(f"已更新版本到: {ver}")
            return
    
    try:
        # 清理旧的构建目录
        clean_build_dir()
        
        # 创建资源目录
        create_resource_dirs()
        
        # 构建可执行文件
        if build_executable():
            print(f"\n构建成功! {APP_NAME} 已准备就绪。")
        else:
            print("\n构建过程中出现错误。")
    except Exception as e:
        print(f"构建过程中发生错误: {str(e)}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 