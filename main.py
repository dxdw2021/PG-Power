import sys
import os
import ctypes
import threading
import platform
import time
from ctypes import c_int, c_char_p, create_string_buffer

# ==============================================
# 0. 设置 Qt 平台插件路径（必须在导入 PyQt5 之前）
# ==============================================
if getattr(sys, 'frozen', False):
    # PyInstaller 单文件模式：插件在临时解压目录
    _base = sys._MEIPASS
else:
    # 开发模式：插件在 venv 内
    _base = os.path.dirname(os.path.abspath(__file__))

_qt_platforms = os.path.join(_base, "PyQt5", "Qt5", "plugins", "platforms")
if os.path.isdir(_qt_platforms):
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _qt_platforms
    # 同时把 Qt bin 目录加到 PATH，确保依赖 DLL 能被找到
    _qt_bin = os.path.join(_base, "PyQt5", "Qt5", "bin")
    if os.path.isdir(_qt_bin):
        os.environ["PATH"] = _qt_bin + os.pathsep + os.environ.get("PATH", "")

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QSpinBox, QGroupBox,
                             QMessageBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
import pyqtgraph as pg

# ==============================================
# 自动检测位数 + 优先加载项目根目录 DLL
# ==============================================
def get_ni4882_dll_path():
    python_bits = platform.architecture()[0]
    print(f"[系统信息] 当前 Python 位数: {python_bits}")

    # 项目根目录
    project_dir = os.path.dirname(os.path.abspath(__file__))
    local_dll = os.path.join(project_dir, "ni4882.dll")

    # 优先使用项目目录下的 DLL
    if os.path.exists(local_dll):
        print(f"[加载] 检测到项目目录DLL: {local_dll}")
        return local_dll

    # 项目目录无文件，读取系统目录
    sys_root = os.environ["SystemRoot"]
    if python_bits == "64bit":
        sys_dll = os.path.join(sys_root, "System32", "ni4882.dll")
    else:
        sys_dll = os.path.join(sys_root, "SysWOW64", "ni4882.dll")
        if not os.path.exists(sys_dll):
            sys_dll = os.path.join(sys_root, "System32", "ni4882.dll")

    if os.path.exists(sys_dll):
        print(f"[加载] 检测到系统目录DLL: {sys_dll}")
        return sys_dll
    else:
        return None

# 全局标记：DLL是否加载成功、GPIB是否可用
GPIB_AVAILABLE = False
ni4882 = None

# 尝试加载DLL（非致命，失败不退出程序）
dll_path = get_ni4882_dll_path()
if dll_path:
    try:
        ni4882 = ctypes.WinDLL(dll_path)
        # 声明函数原型
        ni4882.ibdev.argtypes = [c_int, c_int, c_int, c_int, c_int, c_int]
        ni4882.ibdev.restype = c_int

        ni4882.ibwrt.argtypes = [c_int, c_char_p, c_int]
        ni4882.ibwrt.restype = c_int

        ni4882.ibrd.argtypes = [c_int, c_char_p, c_int]
        ni4882.ibrd.restype = c_int

        ni4882.ibonl.argtypes = [c_int, c_int]
        ni4882.ibonl.restype = c_int

        GPIB_AVAILABLE = True
        print("[成功] ni4882.dll 加载完成，GPIB功能可用")
    except Exception as e:
        print(f"[警告] ni4882.dll 加载失败，缺少NI-488.2依赖组件：{e}")
        GPIB_AVAILABLE = False
else:
    print("[警告] 未找到 ni4882.dll 文件，GPIB功能不可用")
    GPIB_AVAILABLE = False

# ===================== 全局配置 =====================
BOARD_IDX = 0
SAD_ADDR = 0
TIMEOUT_LVL = 13
EOT = 1
EOS = 0
READ_BUF_LEN = 256

gpib_ud = -1
collect_running = False
data_lock = threading.Lock()

# ===================== GPIB 工具函数 =====================
def gpib_open(pad_addr: int) -> bool:
    if not GPIB_AVAILABLE or ni4882 is None:
        return False
    global gpib_ud
    gpib_ud = ni4882.ibdev(BOARD_IDX, pad_addr, SAD_ADDR, TIMEOUT_LVL, EOT, EOS)
    return gpib_ud >= 0

def gpib_close():
    if not GPIB_AVAILABLE or ni4882 is None:
        return
    global gpib_ud
    if gpib_ud >= 0:
        ni4882.ibonl(gpib_ud, 0)
        gpib_ud = -1

def gpib_send_cmd(cmd: str):
    if not GPIB_AVAILABLE or ni4882 is None or gpib_ud < 0:
        return
    cmd_bytes = (cmd + "\r\n").encode("ascii")
    ni4882.ibwrt(gpib_ud, cmd_bytes, len(cmd_bytes))

def gpib_query(cmd: str) -> str:
    if not GPIB_AVAILABLE or ni4882 is None or gpib_ud < 0:
        return ""
    buf = create_string_buffer(READ_BUF_LEN)
    cmd_bytes = (cmd + "\r\n").encode("ascii")
    ni4882.ibwrt(gpib_ud, cmd_bytes, len(cmd_bytes))
    ni4882.ibrd(gpib_ud, buf, READ_BUF_LEN)
    return buf.value.decode("ascii").strip()

# ===================== 界面与绘图 =====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GPIB 电源采集工具")
        self.resize(1000, 600)

        self.x_data = []
        self.y_volt = []
        self.y_curr = []
        self.time_count = 0

        self.init_ui()
        # 检测GPIB状态，弹出提示、禁用按钮
        self.check_gpib_status()

        self.ui_timer = QTimer()
        self.ui_timer.setInterval(20)
        self.ui_timer.timeout.connect(self.update_plot)
        self.ui_timer.start()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        ctrl_group = QGroupBox("设备控制")
        ctrl_layout = QHBoxLayout(ctrl_group)

        self.lbl_addr = QLabel("GPIB地址:")
        self.spin_addr = QSpinBox()
        self.spin_addr.setRange(0, 30)
        self.spin_addr.setValue(5)

        self.btn_connect = QPushButton("连接设备")
        self.btn_connect.clicked.connect(self.on_connect)

        self.btn_output_on = QPushButton("开启输出")
        self.btn_output_on.clicked.connect(lambda: gpib_send_cmd("OUTP ON"))

        self.btn_output_off = QPushButton("关闭输出")
        self.btn_output_off.clicked.connect(lambda: gpib_send_cmd("OUTP OFF"))

        self.btn_start = QPushButton("开始采集")
        self.btn_start.clicked.connect(self.on_start_collect)

        self.btn_stop = QPushButton("停止采集")
        self.btn_stop.clicked.connect(self.on_stop_collect)

        # 保存按钮引用，后续统一禁用
        self.gpib_btns = [
            self.btn_connect,
            self.btn_output_on,
            self.btn_output_off,
            self.btn_start,
            self.btn_stop
        ]

        ctrl_layout.addWidget(self.lbl_addr)
        ctrl_layout.addWidget(self.spin_addr)
        for btn in self.gpib_btns:
            ctrl_layout.addWidget(btn)
        main_layout.addWidget(ctrl_group)

        # 绘图区域
        pg.setConfigOptions(antialias=True)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setTitle("电压/电流 实时曲线")
        self.plot_widget.setLabel("left", "数值")
        self.plot_widget.setLabel("bottom", "采集点数")
        self.plot_widget.addLegend()

        self.curve_volt = self.plot_widget.plot(pen=pg.mkPen((255, 0, 0), width=2), name="电压(V)")
        self.curve_curr = self.plot_widget.plot(pen=pg.mkPen((0, 255, 0), width=2), name="电流(A)")
        main_layout.addWidget(self.plot_widget)

    def check_gpib_status(self):
        """检查GPIB可用性，弹窗提示 + 禁用按钮"""
        if not GPIB_AVAILABLE:
            # 禁用所有GPIB相关按钮
            for btn in self.gpib_btns:
                btn.setEnabled(False)
                btn.setToolTip("GPIB不可用：缺少NI-488.2驱动或依赖组件")
            # 弹出警告框
            QMessageBox.warning(
                self,
                "GPIB 功能异常",
                "ni4882.dll 加载失败，缺少 NI-488.2 驱动依赖组件\n"
                "如需使用GPIB功能，请安装官方 NI-488.2 驱动！"
            )

    @pyqtSlot()
    def on_connect(self):
        if not GPIB_AVAILABLE:
            QMessageBox.information(self, "提示", "GPIB功能不可用，请先安装NI-488.2驱动")
            return

        addr = self.spin_addr.value()
        if gpib_ud >= 0:
            gpib_close()
            self.btn_connect.setText("连接设备")
            print("设备已断开")
        else:
            if gpib_open(addr):
                self.btn_connect.setText("断开设备")
                print(f"GPIB 设备 {addr} 连接成功")
            else:
                print("GPIB 连接失败，请检查地址、硬件")
                QMessageBox.critical(self, "连接失败", "GPIB设备连接失败，请检查地址与硬件")

    @pyqtSlot()
    def on_start_collect(self):
        if not GPIB_AVAILABLE:
            QMessageBox.information(self, "提示", "GPIB功能不可用，请先安装NI-488.2驱动")
            return
        if gpib_ud < 0:
            QMessageBox.information(self, "提示", "请先连接GPIB设备")
            return

        global collect_running
        if not collect_running:
            collect_running = True
            t = threading.Thread(target=self.collect_thread, daemon=True)
            t.start()
            print("开始采集")

    @pyqtSlot()
    def on_stop_collect(self):
        global collect_running
        collect_running = False
        print("停止采集")

    def collect_thread(self):
        global collect_running, data_lock
        while collect_running:
            try:
                volt_str = gpib_query("MEAS:VOLT?")
                curr_str = gpib_query("MEAS:CURR?")
                volt = float(volt_str) if volt_str else 0.0
                curr = float(curr_str) if curr_str else 0.0

                with data_lock:
                    self.time_count += 1
                    self.x_data.append(self.time_count)
                    self.y_volt.append(volt)
                    self.y_curr.append(curr)
                    if len(self.x_data) > 1000:
                        self.x_data.pop(0)
                        self.y_volt.pop(0)
                        self.y_curr.pop(0)
            except Exception as e:
                print(f"采集异常: {e}")
            time.sleep(0.1)

    @pyqtSlot()
    def update_plot(self):
        with data_lock:
            self.curve_volt.setData(self.x_data, self.y_volt)
            self.curve_curr.setData(self.x_data, self.y_curr)

    def closeEvent(self, event):
        global collect_running
        collect_running = False
        gpib_close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
