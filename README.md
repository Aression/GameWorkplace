# 战雷连杀片段导出工具

![版本](https://img.shields.io/badge/版本-1.0.0-blue)
![语言](https://img.shields.io/badge/语言-Python-green)
![平台](https://img.shields.io/badge/平台-Windows-orange)

一款用于自动从录制的《战争雷霆》(War Thunder) 游戏视频中识别和导出连杀片段的工具。帮助玩家轻松获取精彩战斗瞬间，无需手动剪辑。

![程序截图](doc\79aec47e-e3ba-4d87-ae83-a98e7bf24870.png)

## 主要功能

- 🎮 自动识别N卡录像导出的《战争雷霆》连杀片段
- 🎬 智能剪辑并合并连续击杀场景
- 🧠 使用智能算法避免重复片段
- 📋 精确控制击杀前后保留时间
- 💾 保存处理状态，避免重复处理
- 🖥️ 直观易用的图形界面
- 🚀 支持GPU加速（NVENC）和CPU编码

## 系统要求

- Windows 10/11 操作系统
- 安装了FFmpeg和FFprobe（程序会自动检测或指导安装）
- 支持NVENC的NVIDIA显卡（可选，用于加速视频处理）

## 安装和使用

### 方法1：直接运行（推荐）

1. 从[发布页面](https://github.com/your-username/wt-killstreak-exporter/releases)下载最新版本
2. 解压文件到任意位置
3. 运行 `战雷连杀导出工具.exe`

### 方法2：从源码运行

1. 安装Python 3.8或更高版本
2. 克隆或下载此仓库
3. 安装依赖：`pip install -r requirements.txt`
4. 运行主程序：`python wt_killstreak_exporter.py`

### 安装FFmpeg（如果没有）

1. 从[FFmpeg官网](https://ffmpeg.org/download.html)下载FFmpeg
2. 将ffmpeg.exe和ffprobe.exe添加到系统PATH环境变量
3. 或者将这两个文件放在程序同一目录下

## 使用方法

1. 启动程序
2. 选择输入目录（《战争雷霆》游戏录像所在文件夹）
3. 选择输出目录（处理后的连杀片段将保存到此文件夹）
4. 根据需要调整参数：
   - **击杀前保留**：第一次击杀前保留的时间（秒）
   - **击杀后保留**：最后一次击杀后保留的时间（秒）
   - **连杀间隔**：两次击杀之间的最大时间间隔（秒）
   - **最少击杀**：构成连杀的最少击杀数量
5. 点击"开始处理"按钮
6. 处理完成后，输出目录中将生成命名格式为`连杀X_YYYYMMDD_HHMMSS_组Z.mp4`的视频文件，其中：
   - X表示连杀数
   - YYYYMMDD_HHMMSS表示录制时间
   - Z表示连杀组序号

## 文件命名说明

本程序可以处理《战争雷霆》视频录制功能生成的以下格式文件名：

```
War Thunder 2024.06.18 - 19.29.51.02.DVR.mp4
War Thunder 2025.04.14 - 14.00.35.105.DVR.mp4
```

## 常见问题

**Q: 为什么我启动程序后看不到任何界面？**  
A: 请确保您的电脑满足系统要求，并尝试以管理员身份运行程序。

**Q: 处理时间太长怎么办？**  
A: 视频处理是计算密集型任务。如果有NVIDIA显卡，程序会自动使用GPU加速。您也可以尝试减小处理的视频文件数量。

**Q: 我的视频文件没有被识别？**  
A: 确保视频文件命名符合"War Thunder YYYY.MM.DD - HH.MM.SS.XX.DVR.mp4"格式。

**Q: 输出的视频质量不高？**  
A: 默认使用较高的视频质量设置。如需更高质量，可以编辑源代码中的编码参数。

**Q: 状态文件保存在哪里？**

A: 取决于具体使用方式：

1. 当使用GUI版本(`wt_killstreak_exporter.py`)时：
   - 文件保存在应用数据目录中，由`APP_DIR`变量定义
   - 在Windows系统上，路径通常是：`C:\Users\用户名\AppData\Roaming\战雷连杀导出工具\processing_state.json`
   - 完整路径通过这行代码设置：`state_file = os.path.join(APP_DIR, "processing_state.json")`

2. 当直接运行`exporter.py`时：
   - 若没有设置`STATE_FILE_PATH`，则使用默认值`STATE_FILE = 'processing_state.json'`
   - 此时文件保存在当前工作目录中

状态文件存储了上次处理的视频时间戳，这样程序可以跳过已经处理过的视频文件，避免重复处理。

您可以在GUI程序的日志区域看到具体的数据目录路径，会显示为：`[时间] 数据目录: 路径`。如需手动管理或重置处理状态，可以直接删除或修改此文件。


## 开发者信息
更多安装信息参照 [安装指南](doc/INSTALL.md)

### 环境设置

```bash
# 克隆仓库
git clone https://github.com/your-username/wt-killstreak-exporter.git
cd wt-killstreak-exporter

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

### 打包应用

```bash
# 使用打包脚本
python build.py
```

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 贡献

欢迎贡献！如果您发现任何问题或有改进建议，请提交issue或pull request。 