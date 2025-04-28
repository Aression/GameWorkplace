#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
连杀片段导出工具 - 现代UI版
用于自动从录制的游戏视频中识别和导出连杀片段
"""

import os
import sys
import json
import time
import logging
import threading
from datetime import datetime
from pathlib import Path

# PyQt5和PyQt-Fluent-Widgets库
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings, QSize, QUrl, QTimer, QStandardPaths
from PyQt5.QtGui import QIcon, QFont, QDesktopServices, QPixmap
from PyQt5.QtWidgets import QApplication, QFileDialog, QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QGridLayout, QCheckBox, QSizePolicy, QDialog

# 导入Fluent Widgets组件
from qfluentwidgets import (
    MessageBox, InfoBarPosition, InfoBar, PrimaryPushButton, 
    PushButton, ComboBox, SpinBox, setTheme, Theme, ProgressBar,
    ToolButton, LineEdit, TextEdit, 
    FluentIcon as FIF, SubtitleLabel, CardWidget, StrongBodyLabel, BodyLabel,
    ScrollArea, TitleLabel, SimpleCardWidget
)

from qfluentwidgets.common.icon import FluentIconBase
from qfluentwidgets.common.style_sheet import isDarkTheme

try:
    # 尝试导入新版本的InfoBar管理器
    from qfluentwidgets.components.widgets.info_bar import InfoBarManager
except ImportError:
    # 如果失败，使用旧版本的接口
    from qfluentwidgets.components.widgets.info_bar import InfoBar as InfoBarManager

# 导入处理模块
import exporter
from exporter.core.processor import process_videos

# 获取程序版本
VERSION = exporter.__version__

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 路径常量
APP_NAME = "连杀导出工具"
ORG_NAME = "WTKillStreakExporter"

def get_app_dir():
    """获取应用程序数据目录"""
    # 使用QStandardPaths获取跨平台的应用程序数据目录
    app_data_location = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    app_dir = os.path.join(app_data_location, APP_NAME)
    
    # 确保目录存在
    os.makedirs(app_dir, exist_ok=True)
    logger.info(f"应用数据目录: {app_dir}")
    return app_dir

# 获取应用程序目录
APP_DIR = get_app_dir()

# 应用程序图标路径
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "icon.png")

# 自定义图标类
class AppIcon(FluentIconBase):
    """ 自定义应用图标 """
    
    def __init__(self, icon_name):
        super().__init__()
        self.icon_name = icon_name
        
    def path(self, theme=Theme.AUTO, **kwargs):
        if self.icon_name == "app":
            return ICON_PATH
        return ""

# 处理线程类
class ProcessingThread(QThread):
    """处理视频的后台线程"""
    update_signal = pyqtSignal(str)  # 进度更新信号
    progress_signal = pyqtSignal(int, int)  # 进度条更新信号(当前值, 最大值)
    complete_signal = pyqtSignal(bool, str)  # 完成信号(是否成功, 消息)
    scanning_signal = pyqtSignal(bool)  # 扫描状态信号(True表示正在扫描，False表示处理中)
    
    def __init__(self, input_dir, output_dir, lead_time, tail_time, threshold, min_kills):
        super().__init__()
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.lead_time = lead_time
        self.tail_time = tail_time
        self.threshold = threshold
        self.min_kills = min_kills
        self.is_running = True
        self.is_scanning = False
        
    def run(self):
        """运行处理线程"""
        try:
            # 重定向标准输出到自定义函数
            self._redirect_stdout()
            
            # 确保输出目录存在
            os.makedirs(self.output_dir, exist_ok=True)
            
            # 通知UI开始处理
            self.update_signal.emit("开始处理视频...")
            
            # 获取应用程序状态文件路径
            state_file = os.path.join(APP_DIR, "processing_state.json")
            
            # 执行视频处理
            process_videos(
                input_dir=self.input_dir,
                output_dir=self.output_dir,
                lead=self.lead_time,
                tail=self.tail_time,
                threshold=self.threshold,
                min_kills=self.min_kills,
                progress_callback=self._progress_callback,
                state_file=state_file,
                temp_dir=None,  # 使用默认的输出目录/temp
                is_running=lambda: self.is_running  # 传递检查函数
            )
            
            # 通知UI处理完成
            self.complete_signal.emit(True, f"处理完成！输出目录: {self.output_dir}")
            
        except Exception as e:
            logger.error(f"处理过程中发生错误: {str(e)}")
            self.update_signal.emit(f"错误: {str(e)}")
            self.complete_signal.emit(False, f"处理失败: {str(e)}")
        finally:
            # 恢复标准输出
            self._restore_stdout()
    
    def _progress_callback(self, current, total, message=""):
        """处理进度回调"""
        # 检测是否正在扫描阶段
        if message and ("扫描" in message or "寻找" in message):
            if not self.is_scanning:
                self.is_scanning = True
                self.scanning_signal.emit(True)
        elif current > 0 and total > 0:
            # 当开始处理视频并且有具体进度时，表示不再是扫描阶段
            if self.is_scanning:
                self.is_scanning = False
                self.scanning_signal.emit(False)
        
        # 发送进度信号
        self.progress_signal.emit(current, total)
        
        # 如果有消息则发送更新信号
        if message:
            self.update_signal.emit(message)
    
    def _redirect_stdout(self):
        """重定向标准输出"""
        self.old_stdout = sys.stdout
        sys.stdout = self
        
    def _restore_stdout(self):
        """恢复标准输出"""
        sys.stdout = self.old_stdout
    
    def write(self, text):
        """接收标准输出内容并发送信号"""
        if text.strip():  # 跳过空白行
            self.update_signal.emit(text.rstrip())
    
    def flush(self):
        """实现flush方法以兼容标准输出"""
        pass
    
    def stop(self):
        """停止处理"""
        self.is_running = False
        self.update_signal.emit("正在停止处理，请稍候...")

# 主页界面
class MainInterface(ScrollArea):
    """主页界面"""
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent_window = parent
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.init_ui()
        self.processing_thread = None
        self.load_settings()
        
    def init_ui(self):
        """初始化主界面UI"""
        # 创建主容器
        self.main_widget = QWidget()
        self.main_layout = QVBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)
        
        # 顶部标题
        title_card = SimpleCardWidget(self.main_widget)
        title_layout = QVBoxLayout(title_card)
        
        # 应用图标和标题
        header_layout = QHBoxLayout()
        icon_label = QLabel()
        if os.path.exists(ICON_PATH):
            pixmap = QPixmap(ICON_PATH).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(pixmap)
        else:
            icon_label.setPixmap(FIF.VIDEO.icon().pixmap(64, 64))
        icon_label.setFixedSize(64, 64)
        header_layout.addWidget(icon_label)
        
        title_label_layout = QVBoxLayout()
        title_text = TitleLabel("连杀片段导出工具")
        title_label_layout.addWidget(title_text)
        
        description = BodyLabel(f"自动从录制的游戏视频中识别和导出连杀片段 (v{VERSION})")
        title_label_layout.addWidget(description)
        
        header_layout.addLayout(title_label_layout, 1)
        header_layout.addStretch(0)
        
        title_layout.addLayout(header_layout)
        self.main_layout.addWidget(title_card)
        
        # 添加输入输出路径选择卡片
        self.create_path_selection_card()
        
        # 添加参数设置卡片
        self.create_parameter_settings_card()
        
        # 添加操作按钮卡片
        self.create_action_buttons_card()
        
        # 添加进度条卡片
        self.create_progress_card()
        
        # 添加弹性空间
        self.main_layout.addStretch(1)
        
        # 设置主部件
        self.setWidget(self.main_widget)
        self.setWidgetResizable(True)
    
    def create_path_selection_card(self):
        """创建路径选择卡片"""
        path_card = CardWidget(self.main_widget)
        path_layout = QVBoxLayout(path_card)
        
        # 标题
        path_title = SubtitleLabel("路径设置")
        path_layout.addWidget(path_title)
        
        # 输入目录
        input_layout = QHBoxLayout()
        input_label = StrongBodyLabel("输入目录:")
        input_label.setFixedWidth(70)
        self.input_dir_edit = LineEdit()
        self.input_dir_edit.setPlaceholderText("选择录像所在目录")
        self.input_dir_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        input_browse_btn = PushButton("浏览...")
        input_browse_btn.setIcon(FIF.FOLDER)
        input_browse_btn.setFixedWidth(80)
        input_browse_btn.clicked.connect(self._browse_input_dir)
        
        input_layout.addWidget(input_label)
        input_layout.addWidget(self.input_dir_edit, 1)
        input_layout.addWidget(input_browse_btn)
        path_layout.addLayout(input_layout)
        
        # 输出目录
        output_layout = QHBoxLayout()
        output_label = StrongBodyLabel("输出目录:")
        output_label.setFixedWidth(70)
        self.output_dir_edit = LineEdit()
        self.output_dir_edit.setPlaceholderText("选择导出片段保存目录")
        self.output_dir_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        output_browse_btn = PushButton("浏览...")
        output_browse_btn.setIcon(FIF.FOLDER)
        output_browse_btn.setFixedWidth(80)
        output_browse_btn.clicked.connect(self._browse_output_dir)
        
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_dir_edit, 1)
        output_layout.addWidget(output_browse_btn)
        path_layout.addLayout(output_layout)
        
        self.main_layout.addWidget(path_card)
    
    def create_parameter_settings_card(self):
        """创建参数设置卡片"""
        param_card = CardWidget(self.main_widget)
        param_layout = QVBoxLayout(param_card)
        
        # 标题
        param_title = SubtitleLabel("连杀参数设置")
        param_layout.addWidget(param_title)
        
        # 参数网格布局
        param_grid = QGridLayout()
        param_grid.setColumnStretch(1, 1)
        param_grid.setColumnStretch(3, 1)
        param_grid.setHorizontalSpacing(15)
        param_grid.setVerticalSpacing(10)
        
        # 击杀前保留时间
        lead_label = StrongBodyLabel("击杀前保留:")
        self.lead_time_spinbox = SpinBox()
        self.lead_time_spinbox.setRange(1, 60)
        self.lead_time_spinbox.setValue(10)
        self.lead_time_spinbox.setSuffix(" 秒")
        self.lead_time_spinbox.setMinimumWidth(100)
        
        # 最后击杀后保留时间
        tail_label = StrongBodyLabel("击杀后保留:")
        self.tail_time_spinbox = SpinBox()
        self.tail_time_spinbox.setRange(1, 60)
        self.tail_time_spinbox.setValue(5)
        self.tail_time_spinbox.setSuffix(" 秒")
        self.tail_time_spinbox.setMinimumWidth(100)
        
        # 连杀时间阈值
        threshold_label = StrongBodyLabel("连杀间隔:")
        self.threshold_spinbox = SpinBox()
        self.threshold_spinbox.setRange(5, 120)
        self.threshold_spinbox.setValue(30)
        self.threshold_spinbox.setSuffix(" 秒")
        self.threshold_spinbox.setMinimumWidth(100)
        
        # 最少击杀数
        min_kills_label = StrongBodyLabel("最少击杀:")
        self.min_kills_spinbox = SpinBox()
        self.min_kills_spinbox.setRange(2, 10)
        self.min_kills_spinbox.setValue(2)
        self.min_kills_spinbox.setSuffix(" 次")
        self.min_kills_spinbox.setMinimumWidth(100)
        
        # 添加到网格布局
        param_grid.addWidget(lead_label, 0, 0)
        param_grid.addWidget(self.lead_time_spinbox, 0, 1)
        param_grid.addWidget(tail_label, 0, 2)
        param_grid.addWidget(self.tail_time_spinbox, 0, 3)
        param_grid.addWidget(threshold_label, 1, 0)
        param_grid.addWidget(self.threshold_spinbox, 1, 1)
        param_grid.addWidget(min_kills_label, 1, 2)
        param_grid.addWidget(self.min_kills_spinbox, 1, 3)
        
        param_layout.addLayout(param_grid)
        self.main_layout.addWidget(param_card)
    
    def create_action_buttons_card(self):
        """创建操作按钮卡片"""
        button_card = CardWidget(self.main_widget)
        button_layout = QHBoxLayout(button_card)
        button_layout.setSpacing(10)
        
        # 创建一个按钮容器
        button_container = QWidget()
        button_grid = QGridLayout(button_container)
        button_grid.setHorizontalSpacing(10)
        button_grid.setVerticalSpacing(10)
        
        # 开始处理按钮
        self.start_button = PrimaryPushButton("开始处理")
        self.start_button.setIcon(FIF.PLAY)
        self.start_button.clicked.connect(self._start_processing)
        self.start_button.setMinimumHeight(40)
        self.start_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # 停止处理按钮
        self.stop_button = PushButton("停止处理")
        self.stop_button.setIcon(FIF.CANCEL)
        self.stop_button.clicked.connect(self._stop_processing)
        self.stop_button.setEnabled(False)
        self.stop_button.setMinimumHeight(40)
        self.stop_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # 打开输出目录按钮
        self.open_output_button = PushButton("打开输出目录")
        self.open_output_button.setIcon(FIF.FOLDER)
        self.open_output_button.clicked.connect(self._open_output_dir)
        self.open_output_button.setMinimumHeight(40)
        self.open_output_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # 重置处理时间戳按钮
        self.reset_button = PushButton("重置处理时间戳")
        self.reset_button.setIcon(FIF.SYNC)
        self.reset_button.clicked.connect(self._reset_timestamp)
        self.reset_button.setMinimumHeight(40)
        self.reset_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # 在小屏幕上采用两行布局，在大屏幕上采用一行布局
        button_grid.addWidget(self.start_button, 0, 0)
        button_grid.addWidget(self.stop_button, 0, 1)
        button_grid.addWidget(self.open_output_button, 1, 0)
        button_grid.addWidget(self.reset_button, 1, 1)
        
        # 使两列宽度相等
        button_grid.setColumnStretch(0, 1)
        button_grid.setColumnStretch(1, 1)
        
        button_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        button_layout.addWidget(button_container)
        
        self.main_layout.addWidget(button_card)
    
    def create_progress_card(self):
        """创建进度条卡片"""
        progress_card = CardWidget(self.main_widget)
        progress_layout = QVBoxLayout(progress_card)
        
        # 标题
        progress_title = SubtitleLabel("处理进度")
        progress_layout.addWidget(progress_title)
        
        # 进度条
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        # 进度文本
        self.progress_text = BodyLabel("准备就绪")
        self.progress_text.setAlignment(Qt.AlignCenter)
        progress_layout.addWidget(self.progress_text)
        
        self.main_layout.addWidget(progress_card)
    
    def load_settings(self):
        """从配置文件加载设置"""
        self.input_dir_edit.setText(self.settings.value("input_dir", ""))
        self.output_dir_edit.setText(self.settings.value("output_dir", ""))
        self.lead_time_spinbox.setValue(int(self.settings.value("lead_time", 10)))
        self.tail_time_spinbox.setValue(int(self.settings.value("tail_time", 5)))
        self.threshold_spinbox.setValue(int(self.settings.value("threshold", 30)))
        self.min_kills_spinbox.setValue(int(self.settings.value("min_kills", 2)))
        
        # 应用日志字体大小设置
        log_font_size = int(self.settings.value("log_font_size", 9))
        self.progress_text.setFont(QFont("Consolas", log_font_size))
    
    def save_settings(self):
        """保存当前设置到配置文件"""
        self.settings.setValue("input_dir", self.input_dir_edit.text())
        self.settings.setValue("output_dir", self.output_dir_edit.text())
        self.settings.setValue("lead_time", self.lead_time_spinbox.value())
        self.settings.setValue("tail_time", self.tail_time_spinbox.value())
        self.settings.setValue("threshold", self.threshold_spinbox.value())
        self.settings.setValue("min_kills", self.min_kills_spinbox.value())
        self.settings.sync()
    
    def _browse_input_dir(self):
        """浏览并选择输入目录"""
        current_dir = self.input_dir_edit.text() or os.path.expanduser("~")
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择War Thunder录像目录", current_dir)
        if dir_path:
            self.input_dir_edit.setText(dir_path)
    
    def _browse_output_dir(self):
        """浏览并选择输出目录"""
        current_dir = self.output_dir_edit.text() or os.path.expanduser("~")
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择输出目录", current_dir)
        if dir_path:
            self.output_dir_edit.setText(dir_path)
    
    def _open_output_dir(self):
        """打开输出目录"""
        output_dir = self.output_dir_edit.text()
        if output_dir and os.path.exists(output_dir):
            # 使用系统默认程序打开文件夹
            QDesktopServices.openUrl(QUrl.fromLocalFile(output_dir))
        else:
            MessageBox("警告", "输出目录不存在", self.parent_window).exec()
    
    def _reset_timestamp(self):
        """重置处理时间戳，允许重新处理所有视频"""
        state_file = os.path.join(APP_DIR, "processing_state.json")
        
        if os.path.exists(state_file):
            dialog = MessageBox(
                "确认重置", 
                "确定要重置处理时间戳吗？这将允许程序重新处理所有视频文件，包括已经处理过的。",
                self.parent_window
            )
            
            if dialog.exec():
                try:
                    os.remove(state_file)
                    self._update_log("✅ 处理时间戳已重置，下次运行将处理所有视频文件")
                    InfoBar.success(
                        title="重置成功",
                        content="处理时间戳已成功重置，下次运行将处理所有视频文件。",
                        parent=self.parent_window,
                        position=InfoBarPosition.TOP,
                        duration=3000
                    )
                except Exception as e:
                    self._update_log(f"❌ 重置时间戳失败: {str(e)}")
                    InfoBar.error(
                        title="重置失败",
                        content=f"无法重置处理时间戳: {str(e)}",
                        parent=self.parent_window,
                        position=InfoBarPosition.TOP,
                        duration=3000
                    )
        else:
            self._update_log("ℹ️ 未找到处理状态文件，无需重置")
            InfoBar.info(
                title="提示",
                content="未找到处理状态文件，当前已经处于初始状态，下次运行将处理所有视频文件。",
                parent=self.parent_window,
                position=InfoBarPosition.TOP,
                duration=3000
            )
    
    def _validate_inputs(self):
        """验证输入参数有效性"""
        input_dir = self.input_dir_edit.text()
        output_dir = self.output_dir_edit.text()
        
        if not input_dir:
            InfoBar.warning(
                title="警告",
                content="请选择输入目录",
                parent=self.parent_window,
                position=InfoBarPosition.TOP
            )
            return False
        
        if not os.path.exists(input_dir):
            InfoBar.warning(
                title="警告",
                content="输入目录不存在",
                parent=self.parent_window,
                position=InfoBarPosition.TOP
            )
            return False
        
        if not output_dir:
            InfoBar.warning(
                title="警告",
                content="请选择输出目录",
                parent=self.parent_window,
                position=InfoBarPosition.TOP
            )
            return False
        
        # 检查击杀前保留和击杀后保留总时长是否超过典型视频长度
        lead_time = self.lead_time_spinbox.value()
        tail_time = self.tail_time_spinbox.value()
        
        # 从导入的常量获取典型视频长度
        from exporter.utils.constants import TYPICAL_VIDEO_LENGTH
        
        total_segment_time = lead_time + tail_time
        
        # 如果总时间超过典型视频长度，显示警告
        if total_segment_time > TYPICAL_VIDEO_LENGTH:
            warning_msg = f"击杀前({lead_time}秒)和击杀后({tail_time}秒)保留时间总计{total_segment_time}秒，超过典型视频长度({TYPICAL_VIDEO_LENGTH}秒)，可能导致部分片段无法导出"
            
            dialog = MessageBox(
                "参数警告", 
                f"{warning_msg}\n\n是否仍要继续处理？",
                self.parent_window
            )
            
            if not dialog.exec():
                return False
        
        return True
    
    def _start_processing(self):
        """开始处理视频"""
        if not self._validate_inputs():
            return
        
        # 保存当前设置
        self.save_settings()
        
        # 准备参数
        input_dir = self.input_dir_edit.text()
        output_dir = self.output_dir_edit.text()
        lead_time = self.lead_time_spinbox.value()
        tail_time = self.tail_time_spinbox.value()
        threshold = self.threshold_spinbox.value()
        min_kills = self.min_kills_spinbox.value()
        
        # 更新UI状态
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_text.setText("正在准备...")
        self.is_scanning = False  # 初始化扫描状态为False
        
        # 更新日志
        self._update_log("开始处理视频...")
        self._update_log(f"输入目录: {input_dir}")
        self._update_log(f"输出目录: {output_dir}")
        self._update_log(f"参数: 前置={lead_time}秒, 后置={tail_time}秒, 阈值={threshold}秒, 最少击杀={min_kills}次")
        self._update_log(f"数据目录: {APP_DIR}")
        self._update_log("命令行窗口已隐藏，所有操作信息将显示在日志中")
        
        # 创建并启动处理线程
        self.processing_thread = ProcessingThread(
            input_dir, output_dir, lead_time, tail_time, threshold, min_kills
        )
        self.processing_thread.update_signal.connect(self._update_log)
        self.processing_thread.progress_signal.connect(self._update_progress)
        self.processing_thread.complete_signal.connect(self._process_complete)
        self.processing_thread.scanning_signal.connect(self._update_scanning_state)
        self.processing_thread.start()
        
        # 显示通知
        InfoBar.success(
            title="处理开始",
            content="视频处理已开始，请耐心等待...",
            parent=self.parent_window,
            position=InfoBarPosition.TOP,
            duration=3000
        )
    
    def _stop_processing(self):
        """停止处理"""
        if self.processing_thread and self.processing_thread.isRunning():
            dialog = MessageBox(
                "确认停止", 
                "确定要停止当前处理任务吗？未完成的导出可能会丢失。",
                self.parent_window
            )
            
            if dialog.exec():
                self._update_log("用户已取消处理")
                self.progress_text.setText("正在停止...")
                # 禁用停止按钮，防止多次点击
                self.stop_button.setEnabled(False)
                
                # 停止处理线程
                self.processing_thread.stop()
                
                # 使用定时器检查线程状态，避免UI卡死
                def check_thread_status():
                    if not self.processing_thread.isRunning():
                        # 线程已停止，恢复UI状态
                        self.is_scanning = False  # 重置扫描状态
                        self._process_complete(False, "处理已取消")
                        timer.stop()
                
                # 创建定时器
                timer = QTimer(self)
                timer.timeout.connect(check_thread_status)
                timer.start(200)  # 每200毫秒检查一次
    
    def _update_log(self, message):
        """更新日志输出"""
        # 转发到主窗口的日志显示
        if hasattr(self.parent_window, 'update_log'):
            self.parent_window.update_log(message)
    
    def _update_progress(self, current, total):
        """更新进度条"""
        if self.is_scanning:
            # 处于扫描状态，显示忙碌状态
            self.progress_bar.setMaximum(0)
            self.progress_bar.setValue(0)
            self.progress_text.setText("正在扫描视频文件...")
        elif total > 0:
            # 处理视频状态，显示具体进度
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            self.progress_text.setText(f"进度: {current}/{total} ({int(current/total*100)}%)")
        else:
            # 未知状态，显示忙碌状态
            self.progress_bar.setMaximum(0)
            self.progress_bar.setValue(0)
            self.progress_text.setText("正在准备...")
    
    def _process_complete(self, success, message):
        """处理完成回调"""
        # 恢复UI状态
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.is_scanning = False  # 重置扫描状态
        
        if success:
            self.progress_bar.setMaximum(100)  # 确保进度条有最大值
            self.progress_bar.setValue(100)    # 设置为100%
            self.progress_text.setText("处理完成")
            self._update_log(f"✅ {message}")
            
            # 弹出成功提示
            dialog = MessageBox(
                "处理完成", 
                f"{message}\n\n是否需要打开输出目录查看导出的视频？",
                self.parent_window
            )
            if dialog.exec():
                self._open_output_dir()
                
            # 显示通知
            InfoBar.success(
                title="处理完成",
                content="所有视频处理完成！",
                parent=self.parent_window,
                position=InfoBarPosition.TOP,
                duration=3000
            )
        else:
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(0)
            self.progress_text.setText("处理已中断")
            self._update_log(f"❌ {message}")
            
            # 显示通知
            InfoBar.error(
                title="处理中断",
                content=message,
                parent=self.parent_window,
                position=InfoBarPosition.TOP,
                duration=5000
            )
    
    def _update_scanning_state(self, is_scanning):
        """更新扫描状态"""
        self.is_scanning = is_scanning
        self._update_progress(0, 0)

# 设置界面
class SettingsInterface(QDialog):
    """设置对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        
        # 设置窗口属性
        self.setWindowTitle("设置")
        self.setWindowIcon(QIcon(ICON_PATH) if os.path.exists(ICON_PATH) else FIF.SETTING.icon())
        self.setMinimumWidth(500)
        self.setMinimumHeight(300)
        
        # 创建布局
        self.main_layout = QVBoxLayout(self)
        
        # 添加设置项
        self._add_settings(self.main_layout)
        
        # 添加按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        
        self.cancel_button = PushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        
        self.ok_button = PrimaryPushButton("确定")
        self.ok_button.clicked.connect(self.accept)
        
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.ok_button)
        
        self.main_layout.addLayout(button_layout)
        
    def _add_settings(self, layout):
        """添加设置项"""
        # 创建设置容器
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        
        # 创建外观设置
        appearance_card = CardWidget(settings_widget)
        appearance_layout = QVBoxLayout(appearance_card)
        
        # 标题
        appearance_title = SubtitleLabel("外观设置")
        appearance_layout.addWidget(appearance_title)
        
        # 主题选择
        theme_layout = QHBoxLayout()
        theme_label = StrongBodyLabel("应用主题:")
        theme_label.setFixedWidth(120)
        self.theme_combo = ComboBox(self)
        self.theme_combo.addItems(["浅色", "深色", "跟随系统"])
        self.theme_combo.setCurrentIndex(int(self.parent_window.settings.value("theme", 2)))
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.theme_combo)
        appearance_layout.addLayout(theme_layout)
        
        # 日志字体大小
        log_font_layout = QHBoxLayout()
        log_font_label = StrongBodyLabel("日志字体大小:")
        log_font_label.setFixedWidth(120)
        self.log_font_spinbox = SpinBox()
        self.log_font_spinbox.setRange(8, 16)
        self.log_font_spinbox.setValue(int(self.parent_window.settings.value("log_font_size", 9)))
        log_font_layout.addWidget(log_font_label)
        log_font_layout.addWidget(self.log_font_spinbox)
        appearance_layout.addLayout(log_font_layout)
        
        settings_layout.addWidget(appearance_card)
        
        # 关于卡片
        about_card = CardWidget(settings_widget)
        about_layout = QVBoxLayout(about_card)
        
        about_title = SubtitleLabel("关于")
        about_layout.addWidget(about_title)
        
        about_text = BodyLabel(f"连杀片段导出工具 v{VERSION}\n\n"
                              f"数据目录: {APP_DIR}")
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)
        
        settings_layout.addWidget(about_card)
        
        # 添加设置容器到对话框布局
        layout.addWidget(settings_widget)
    
    def exec(self):
        """显示对话框并应用设置"""
        result = super().exec()
        if result:
            self._apply_settings()
        return result
    
    # 为了向后兼容保留exec_方法
    def exec_(self):
        """向后兼容的方法，调用exec"""
        return self.exec()
    
    def _apply_settings(self):
        """应用设置"""
        # 主题设置
        theme_index = self.theme_combo.currentIndex()
        self.parent_window.settings.setValue("theme", theme_index)
        
        # 使用字典映射主题
        theme_map = {
            0: Theme.LIGHT,
            1: Theme.DARK,
            2: Theme.AUTO
        }
        current_theme = theme_map.get(theme_index, Theme.AUTO)  # 使用get避免索引错误
        setTheme(current_theme)
        
        # 日志字体大小
        log_font_size = self.log_font_spinbox.value()
        self.parent_window.settings.setValue("log_font_size", log_font_size)
        
        # 更新日志字体大小 - 安全地访问属性
        if hasattr(self.parent_window, 'log_text') and self.parent_window.log_text:
            self.parent_window.log_text.setFont(QFont("Consolas", log_font_size))
        
        # 更新主界面进度文字字体 - 安全地访问属性
        if (hasattr(self.parent_window, 'main_interface') and 
                self.parent_window.main_interface and 
                hasattr(self.parent_window.main_interface, 'progress_text') and
                self.parent_window.main_interface.progress_text):
            self.parent_window.main_interface.progress_text.setFont(QFont("Consolas", log_font_size))
        
        # 显示应用通知
        InfoBar.success(
            title="设置已更新",
            content="应用设置已成功保存",
            parent=self.parent_window,
            position=InfoBarPosition.TOP,
            duration=3000
        )

# 主窗口
class MainWindow(QWidget):
    """主窗口"""
    def __init__(self):
        super().__init__()
        
        # 设置窗口属性
        self.setWindowTitle(f"连杀片段导出工具 v{VERSION}")
        self.resize(1200, 750)  # 调整默认窗口大小，更适合显示内容
        self.setMinimumSize(1000, 600)
        
        # 设置应用程序图标
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        
        # 初始化设置
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self._load_app_settings()
        
        # 创建主布局
        self._create_main_layout()
        
        # 恢复窗口状态
        self._restore_window_state()
    
    def _load_app_settings(self):
        """加载应用程序设置"""
        # 主题设置
        theme_index = int(self.settings.value("theme", 2))  # 默认跟随系统
        theme_map = {
            0: Theme.LIGHT,
            1: Theme.DARK,
            2: Theme.AUTO
        }
        setTheme(theme_map[theme_index])
    
    def _create_main_layout(self):
        """创建主布局"""
        # 创建主布局
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 创建主界面
        self.main_interface = MainInterface(self)
        main_layout.addWidget(self.main_interface, 2)  # 主界面占2/3宽度
        
        # 创建设置页面
        self.settings_interface = SettingsInterface(self)
        
        # 创建日志卡片（放在右侧）
        self.log_card = self._create_log_widget()
        main_layout.addWidget(self.log_card, 1)  # 日志占1/3宽度
    
    def _create_log_widget(self):
        """创建日志显示部件"""
        # 创建日志卡片
        log_card = CardWidget(self)
        log_layout = QVBoxLayout(log_card)
        
        # 标题区域
        title_layout = QHBoxLayout()
        
        # 标题
        log_title = SubtitleLabel("处理日志")
        title_layout.addWidget(log_title)
        
        # 添加设置按钮
        settings_btn = ToolButton()
        settings_btn.setIcon(FIF.SETTING)
        settings_btn.setToolTip("打开设置")
        settings_btn.clicked.connect(self._show_settings)
        title_layout.addWidget(settings_btn)
        
        title_layout.addStretch(1)
        log_layout.addLayout(title_layout)
        
        # 日志文本框
        self.log_text = TextEdit()
        self.log_text.setReadOnly(True)
        log_font_size = int(self.settings.value("log_font_size", 9))
        self.log_text.setFont(QFont("Consolas", log_font_size))
        self.log_text.setMinimumWidth(300)
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout.addWidget(self.log_text)
        
        # 日志卡片应该占用更多空间
        log_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        return log_card
    
    def _show_settings(self):
        """显示设置对话框"""
        self.settings_interface.exec_()
    
    def _restore_window_state(self):
        """恢复窗口状态"""
        # 恢复窗口大小和位置
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
    
    def _save_window_state(self):
        """保存窗口状态"""
        # 保存窗口大小和位置
        self.settings.setValue("window_geometry", self.saveGeometry())
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        # 检查是否有处理正在进行
        if (hasattr(self, 'main_interface') and 
            self.main_interface.processing_thread and 
            self.main_interface.processing_thread.isRunning()):
            
            dialog = MessageBox(
                "确认退出", 
                "处理任务仍在进行中，确定要退出吗？",
                self
            )
            
            if dialog.exec():
                # 停止处理线程
                self.main_interface.processing_thread.stop()
                
                # 创建一个定时器来检查线程状态，避免UI卡死
                self.close_timer = QTimer(self)
                self.close_timer.timeout.connect(self._check_close_status)
                self.close_timer.start(200)  # 每200毫秒检查一次
                
                # 保存要关闭的事件以便稍后处理
                self.pending_close_event = event
                event.ignore()  # 先不关闭
            else:
                event.ignore()
        else:
            # 保存窗口状态
            self._save_window_state()
            
            # 保存设置
            if hasattr(self, 'main_interface'):
                self.main_interface.save_settings()
            event.accept()
    
    def _check_close_status(self):
        """检查线程是否已经停止，以便完成窗口关闭"""
        if not self.main_interface.processing_thread.isRunning():
            self.close_timer.stop()
            
            # 保存窗口状态
            self._save_window_state()
            
            # 保存设置
            self.main_interface.save_settings()
            
            # 接受关闭事件
            self.pending_close_event.accept()
            
    def update_log(self, message):
        """更新日志输出"""
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


if __name__ == "__main__":
    # 确保应用程序目录存在
    os.makedirs(APP_DIR, exist_ok=True)
    
    # 设置应用程序日志文件
    log_file = os.path.join(APP_DIR, "app.log")
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    logger.info(f"应用程序启动，版本: {VERSION}")
    
    # 设置高DPI属性
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    # 创建应用程序
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 运行应用程序
    sys.exit(app.exec_()) 