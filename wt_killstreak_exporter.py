#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
战雷连杀片段导出工具 - GUI版本
用于自动从录制的战雷游戏视频中识别和导出连杀片段
"""

import os
import sys
import json
import time
import logging
import threading
from datetime import datetime
from pathlib import Path

# PyQt5 GUI库
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QLineEdit, QFileDialog, QSpinBox, 
    QTextEdit, QProgressBar, QGroupBox, QFormLayout, QMessageBox,
    QCheckBox, QSlider, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QTabWidget, QToolButton, QSizePolicy, QComboBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings, QSize, QUrl, QTimer
from PyQt5.QtGui import QIcon, QFont, QDesktopServices, QPixmap

# 导入处理模块
import exporter

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 路径常量
VERSION = "1.0.0"
APP_NAME = "战雷连杀导出工具"
ORG_NAME = "WTKillStreakExporter"

def get_app_dir():
    """获取应用程序数据目录"""
    # 在Windows上使用%APPDATA%/[APP_NAME]
    # 在Mac上使用~/Library/Application Support/[APP_NAME]
    # 在Linux上使用~/.local/share/[APP_NAME]
    if sys.platform == 'win32':
        app_data = os.environ.get('APPDATA', '')
        if app_data:
            app_dir = os.path.join(app_data, APP_NAME)
        else:
            # 如果APPDATA不可用，使用应用程序目录
            app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    elif sys.platform == 'darwin':
        app_dir = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    else:
        app_dir = os.path.expanduser(f"~/.local/share/{APP_NAME}")
    
    # 确保目录存在
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

# 获取应用程序目录
APP_DIR = get_app_dir()

# 应用程序图标路径
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "icon.png")

class ProcessingThread(QThread):
    """处理视频的后台线程"""
    update_signal = pyqtSignal(str)  # 进度更新信号
    progress_signal = pyqtSignal(int, int)  # 进度条更新信号(当前值, 最大值)
    complete_signal = pyqtSignal(bool, str)  # 完成信号(是否成功, 消息)
    
    def __init__(self, input_dir, output_dir, lead_time, tail_time, threshold, min_kills):
        super().__init__()
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.lead_time = lead_time
        self.tail_time = tail_time
        self.threshold = threshold
        self.min_kills = min_kills
        self.is_running = True
        
    def run(self):
        """运行处理线程"""
        try:
            # 重定向标准输出到自定义函数
            self._redirect_stdout()
            
            # 确保输出目录存在
            os.makedirs(self.output_dir, exist_ok=True)
            
            # 通知UI开始处理
            self.update_signal.emit("开始处理视频...")
            
            # 获取应用程序状态文件路径和临时目录
            state_file = os.path.join(APP_DIR, "processing_state.json")
            
            # 执行视频处理
            exporter.process_videos(
                input_dir=self.input_dir,
                output_dir=self.output_dir,
                lead=self.lead_time,
                tail=self.tail_time,
                threshold=self.threshold,
                min_kills=self.min_kills,
                progress_callback=self._progress_callback,
                state_file=state_file,
                temp_dir=APP_DIR,
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
        self.progress_signal.emit(current, total)
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


class MainWindow(QMainWindow):
    """主窗口"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"战雷连杀片段导出工具 v{VERSION}")
        self.setMinimumSize(800, 600)
        
        # 设置应用程序图标
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        
        # 加载设置
        self.settings = QSettings(ORG_NAME, APP_NAME)
        
        # 初始化UI
        self._init_ui()
        
        # 加载已保存的设置
        self._load_settings()
        
        # 处理线程
        self.processing_thread = None
        
    def _init_ui(self):
        """初始化用户界面"""
        # 主布局
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        
        # 顶部标题和版本
        header_layout = QHBoxLayout()
        title_label = QLabel("战雷连杀片段导出工具")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        header_layout.addWidget(title_label)
        
        version_label = QLabel(f"v{VERSION}")
        version_label.setFont(QFont("Arial", 10))
        version_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addWidget(version_label)
        main_layout.addLayout(header_layout)
        
        # 参数设置区域
        settings_group = QGroupBox("参数设置")
        settings_layout = QFormLayout()
        
        # 输入输出目录选择
        input_layout = QHBoxLayout()
        self.input_dir_edit = QLineEdit()
        self.input_dir_edit.setPlaceholderText("选择战雷录像所在目录")
        input_browse_btn = QPushButton("浏览...")
        input_browse_btn.clicked.connect(self._browse_input_dir)
        input_layout.addWidget(self.input_dir_edit)
        input_layout.addWidget(input_browse_btn)
        settings_layout.addRow("输入目录:", input_layout)
        
        output_layout = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("选择导出片段保存目录")
        output_browse_btn = QPushButton("浏览...")
        output_browse_btn.clicked.connect(self._browse_output_dir)
        output_layout.addWidget(self.output_dir_edit)
        output_layout.addWidget(output_browse_btn)
        settings_layout.addRow("输出目录:", output_layout)
        
        # 连杀参数设置
        param_layout = QHBoxLayout()
        
        # 击杀前保留时间
        self.lead_time_spinbox = QSpinBox()
        self.lead_time_spinbox.setRange(1, 60)
        self.lead_time_spinbox.setValue(10)
        self.lead_time_spinbox.setSuffix(" 秒")
        param_layout.addWidget(QLabel("击杀前保留:"))
        param_layout.addWidget(self.lead_time_spinbox)
        
        # 最后击杀后保留时间
        self.tail_time_spinbox = QSpinBox()
        self.tail_time_spinbox.setRange(1, 60)
        self.tail_time_spinbox.setValue(5)
        self.tail_time_spinbox.setSuffix(" 秒")
        param_layout.addWidget(QLabel("击杀后保留:"))
        param_layout.addWidget(self.tail_time_spinbox)
        
        # 连杀时间阈值
        self.threshold_spinbox = QSpinBox()
        self.threshold_spinbox.setRange(5, 120)
        self.threshold_spinbox.setValue(30)
        self.threshold_spinbox.setSuffix(" 秒")
        param_layout.addWidget(QLabel("连杀间隔:"))
        param_layout.addWidget(self.threshold_spinbox)
        
        # 最少击杀数
        self.min_kills_spinbox = QSpinBox()
        self.min_kills_spinbox.setRange(2, 10)
        self.min_kills_spinbox.setValue(2)
        self.min_kills_spinbox.setSuffix(" 次")
        param_layout.addWidget(QLabel("最少击杀:"))
        param_layout.addWidget(self.min_kills_spinbox)
        
        settings_layout.addRow("连杀参数:", param_layout)
        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)
        
        # 处理按钮和状态
        action_layout = QHBoxLayout()
        self.start_button = QPushButton("开始处理")
        self.start_button.setIcon(QIcon.fromTheme("media-playback-start"))
        self.start_button.clicked.connect(self._start_processing)
        self.start_button.setMinimumHeight(40)
        action_layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton("停止处理")
        self.stop_button.setIcon(QIcon.fromTheme("media-playback-stop"))
        self.stop_button.clicked.connect(self._stop_processing)
        self.stop_button.setEnabled(False)
        self.stop_button.setMinimumHeight(40)
        action_layout.addWidget(self.stop_button)
        
        self.open_output_button = QPushButton("打开输出目录")
        self.open_output_button.setIcon(QIcon.fromTheme("folder-open"))
        self.open_output_button.clicked.connect(self._open_output_dir)
        self.open_output_button.setMinimumHeight(40)
        action_layout.addWidget(self.open_output_button)
        
        self.reset_button = QPushButton("重置处理时间戳")
        self.reset_button.setIcon(QIcon.fromTheme("edit-clear"))
        self.reset_button.clicked.connect(self._reset_timestamp)
        self.reset_button.setMinimumHeight(40)
        action_layout.addWidget(self.reset_button)
        
        main_layout.addLayout(action_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m (%p%)")
        main_layout.addWidget(self.progress_bar)
        
        # 日志输出
        log_group = QGroupBox("处理日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
        
        # 状态栏
        self.statusBar().showMessage("准备就绪")
        
        # 设置中央控件
        self.setCentralWidget(main_widget)
    
    def _load_settings(self):
        """从配置文件加载设置"""
        self.input_dir_edit.setText(self.settings.value("input_dir", ""))
        self.output_dir_edit.setText(self.settings.value("output_dir", ""))
        self.lead_time_spinbox.setValue(int(self.settings.value("lead_time", 10)))
        self.tail_time_spinbox.setValue(int(self.settings.value("tail_time", 5)))
        self.threshold_spinbox.setValue(int(self.settings.value("threshold", 30)))
        self.min_kills_spinbox.setValue(int(self.settings.value("min_kills", 2)))
    
    def _save_settings(self):
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
            QMessageBox.warning(self, "警告", "输出目录不存在")
    
    def _reset_timestamp(self):
        """重置处理时间戳，允许重新处理所有视频"""
        state_file = os.path.join(APP_DIR, "processing_state.json")
        
        if os.path.exists(state_file):
            reply = QMessageBox.question(
                self, '确认重置', 
                "确定要重置处理时间戳吗？这将允许程序重新处理所有视频文件，包括已经处理过的。",
                QMessageBox.Yes | QMessageBox.No, 
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                try:
                    os.remove(state_file)
                    self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 处理时间戳已重置，下次运行将处理所有视频文件")
                    QMessageBox.information(self, "重置成功", "处理时间戳已成功重置，下次运行将处理所有视频文件。")
                except Exception as e:
                    self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ 重置时间戳失败: {str(e)}")
                    QMessageBox.warning(self, "重置失败", f"无法重置处理时间戳: {str(e)}")
        else:
            self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] ℹ️ 未找到处理状态文件，无需重置")
            QMessageBox.information(self, "提示", "未找到处理状态文件，当前已经处于初始状态，下次运行将处理所有视频文件。")
    
    def _validate_inputs(self):
        """验证输入参数有效性"""
        input_dir = self.input_dir_edit.text()
        output_dir = self.output_dir_edit.text()
        
        if not input_dir:
            QMessageBox.warning(self, "警告", "请选择输入目录")
            return False
        
        if not os.path.exists(input_dir):
            QMessageBox.warning(self, "警告", "输入目录不存在")
            return False
        
        if not output_dir:
            QMessageBox.warning(self, "警告", "请选择输出目录")
            return False
        
        return True
    
    def _start_processing(self):
        """开始处理视频"""
        if not self._validate_inputs():
            return
        
        # 保存当前设置
        self._save_settings()
        
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
        self.log_text.clear()
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始处理视频...")
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 输入目录: {input_dir}")
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 输出目录: {output_dir}")
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 参数: 前置={lead_time}秒, 后置={tail_time}秒, 阈值={threshold}秒, 最少击杀={min_kills}次")
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 数据目录: {APP_DIR}")
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 命令行窗口已隐藏，所有操作信息将显示在本日志中")
        self.statusBar().showMessage("正在处理中...")
        
        # 创建并启动处理线程
        self.processing_thread = ProcessingThread(
            input_dir, output_dir, lead_time, tail_time, threshold, min_kills
        )
        self.processing_thread.update_signal.connect(self._update_log)
        self.processing_thread.progress_signal.connect(self._update_progress)
        self.processing_thread.complete_signal.connect(self._process_complete)
        self.processing_thread.start()
    
    def _stop_processing(self):
        """停止处理"""
        if self.processing_thread and self.processing_thread.isRunning():
            reply = QMessageBox.question(
                self, '确认停止', 
                "确定要停止当前处理任务吗？未完成的导出可能会丢失。",
                QMessageBox.Yes | QMessageBox.No, 
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] 用户已取消处理")
                self.progress_bar.setFormat("正在停止...")
                # 禁用停止按钮，防止多次点击
                self.stop_button.setEnabled(False)
                # 显示取消中状态
                self.statusBar().showMessage("正在取消处理...")
                
                # 停止处理线程
                self.processing_thread.stop()
                
                # 使用定时器检查线程状态，避免UI卡死
                def check_thread_status():
                    if not self.processing_thread.isRunning():
                        # 线程已停止，恢复UI状态
                        self._process_complete(False, "处理已取消")
                        timer.stop()
                
                # 创建定时器
                timer = QTimer(self)
                timer.timeout.connect(check_thread_status)
                timer.start(200)  # 每200毫秒检查一次
    
    def _update_log(self, message):
        """更新日志输出"""
        self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _update_progress(self, current, total):
        """更新进度条"""
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
        else:
            # 如果总数为0，显示忙碌状态
            self.progress_bar.setMaximum(0)
            self.progress_bar.setValue(0)
    
    def _process_complete(self, success, message):
        """处理完成回调"""
        # 恢复UI状态
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        
        if success:
            self.progress_bar.setValue(self.progress_bar.maximum())
            self.statusBar().showMessage("处理完成")
            self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ {message}")
            
            # 弹出成功提示
            reply = QMessageBox.information(self, "处理完成", f"{message}\n\n是否需要打开输出目录查看导出的视频？", 
                                   QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._open_output_dir()
        else:
            self.statusBar().showMessage("处理中断")
            self.log_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ {message}")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        # 检查是否有处理正在进行
        if self.processing_thread and self.processing_thread.isRunning():
            reply = QMessageBox.question(
                self, '确认退出', 
                "处理任务仍在进行中，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No, 
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # 停止处理线程
                self.processing_thread.stop()
                
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
            # 保存设置
            self._save_settings()
            event.accept()
    
    def _check_close_status(self):
        """检查线程是否已经停止，以便完成窗口关闭"""
        if not self.processing_thread.isRunning():
            self.close_timer.stop()
            # 保存设置
            self._save_settings()
            # 使用默认的close事件处理
            QMainWindow.closeEvent(self, self.pending_close_event)
            self.pending_close_event.accept()


if __name__ == "__main__":
    # 确保应用程序目录存在
    os.makedirs(APP_DIR, exist_ok=True)
    
    # 设置应用程序日志文件
    log_file = os.path.join(APP_DIR, "app.log")
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    logger.info(f"应用程序启动，版本: {VERSION}")
    logger.info(f"应用数据目录: {APP_DIR}")
    
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle("Fusion")
    
    # 实例化并显示主窗口
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())
