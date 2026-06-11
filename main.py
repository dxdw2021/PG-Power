import sys
import os
import ctypes
import threading
import platform
import time
from ctypes import c_int, c_char_p, create_string_buffer
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QSpinBox, QGroupBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
import pyqtgraph as pg

# ==============================================
# 1. 自动检测 Python 位数，选择对应 ni4882.dll
# ==============================================
def get_ni4882_dll_path():
    """
    自动检测当前 Python 位数，返回对应的 ni4882.dll 路径
    优先级：
    1. 当前目录下的 ni4882.dll
    2. 系统目录下的对应位数 DLL
    """
    python_bits = platform.architecture()[0]
    print(f"当前 Python 位数: {python_bits}")

    # 1. 优先检查当前目录
    local_dll = os.path.join(os.path.dirname(__file__), "ni4882.dll")
    if os.path.exists(local_dll):
        print(f"使用当前目录下的 DLL: {local_dll}")
        return local_dll

    # 2. 检查系统目录
    if python_bits == "64bit":
        # 64位系统下 System32 放的是64位 DLL
        sys_path = os.path.join(os.environ["SystemRoot"], "System32", "ni4882.dll")
    else:
        # 32位 DLL 在 SysWOW64（64位系统）或 System32（32位系统）
        sys_path = os.path.join(os.environ["SystemRoot"], "SysWOW64", "ni4882.dll")
        if not os.path.exists(sys_path):
            sys_path = os.path.join(os.environ["SystemRoot"], "System32", "ni4882.dll")

    if os.path.exists(sys_path):
        print(f"使用系统目录下的 DLL: {sys_path}")
        return sys_path
    else:
        raise FileNotFoundError("找不到 ni4882.dll，请安装 NI-488.2 驱动或放置在程序目录")

# 加载 DLL（自动适配位数）
try:
    ni4882 = ctypes.WinDLL(get_ni4882_dll_path())
except Exception as e:
    print(f"加载 ni4882.dll 失败: {e}")
    sys.exit(1)

# ===================== 2. 底层 GPIB 函数声明 =====================
ni4882.ibdev.argtypes = [c_int, c_int, c_int, c_int, c_int, c_int]
ni4882.ibdev.restype = c_int

ni4882.ibwrt.argtypes = [c_int, c_char_p, c_int]
ni4882.ibwrt.restype = c_int

ni4882.ibrd.argtypes = [c_int, c_char_p, c_int]
ni4882.ibrd.restype = c_int

ni4882.ibonl.argtypes = [c_int, c_int]
ni4882.ibonl.restype = c_int

# ===================== 3. GPIB 配置与全局变量 =====================
BOARD_IDX = 0       # GPIB板卡号（通常为0）
SAD_ADDR = 0        # 副地址，普通仪器填0
TIMEOUT_LVL = 13    # 超时等级(13=10s)
EOT = 1
EOS = 0
READ_BUF_LEN = 256

gpib_ud = -1        # 设备句柄
collect_running = False  # 采集启停标志
data_lock = threading.Lock()

# ===================== 4. GPIB 基础封装 =====================
def gpib_open(pad_addr: int) -> bool:
    """打开GPIB设备"""
    global gpib_ud
    gpib_ud = ni4882.ibdev(BOARD_IDX, pad_addr, SAD_ADDR, TIMEOUT_LVL, EOT, EOS)
    return gpib_ud >= 0

def gpib_close():
    """关闭GPIB设备"""
    global gpib_ud
    if gpib_ud >= 0:
        ni4882.ibonl(gpib_ud, 0)
        gpib_ud = -1

def gpib_send_cmd(cmd: str):
    """发送SCPI命令"""
    if gpib_ud < 0:
        return
    cmd_bytes = (cmd + "\r\n").encode("ascii")
    ni4882.ibwrt(gpib_ud, cmd_bytes, len(cmd_bytes))

def gpib_query(cmd: str) -> str:
    """发送查询命令并读取返回值"""
    if gpib_ud < 0:
        return ""
    buf = create_string_buffer(READ_BUF_LEN)
    cmd_bytes = (cmd + "\r\n").encode("ascii")
    ni4882.ibwrt(gpib_ud, cmd_bytes, len(cmd_bytes))
    ni4882.ibrd(gpib_ud, buf, READ_BUF_LEN)
    return buf.value.decode("ascii").strip()

# ===================== 5. 主界面 + 绘图逻辑 =====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GPIB 电源实时采集工具（自动适配DLL位数）")
        self.resize(1000, 600)

        # 采集数据缓存
        self.x_data = []
        self.y_volt = []
        self.y_curr = []
        self.time_count = 0

        # 初始化UI
        self.init_ui()
        # 定时器：界面刷新(20ms)
        self.ui_timer = QTimer()
        self.ui_timer.setInterval(20)
        self.ui_timer.timeout.connect(self.update_plot)
        self.ui_timer.start()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 顶部控制区
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

        ctrl_layout.addWidget(self.lbl_addr)
        ctrl_layout.addWidget(self.spin_addr)
        ctrl_layout.addWidget(self.btn_connect)
        ctrl_layout.addWidget(self.btn_output_on)
        ctrl_layout.addWidget(self.btn_output_off)
        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_stop)
        main_layout.addWidget(ctrl_group)

        # 绘图区域
        pg.setConfigOptions(antialias=True)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setTitle("电压/电流 实时曲线")
        self.plot_widget.setLabel("left", "数值")
        self.plot_widget.setLabel("bottom", "采集点数")
        self.plot_widget.addLegend()

        # 两条曲线：电压(红色)、电流(绿色)
        self.curve_volt = self.plot_widget.plot(pen=pg.mkPen(color=(255, 0, 0), width=2), name="电压(V)")
        self.curve_curr = self.plot_widget.plot(pen=pg.mkPen(color=(0, 255, 0), width=2), name="电流(A)")

        main_layout.addWidget(self.plot_widget)

    # 连接/断开设备
    @pyqtSlot()
    def on_connect(self):
        addr = self.spin_addr.value()
        if gpib_ud >= 0:
            gpib_close()
            self.btn_connect.setText("连接设备")
            print("设备已断开")
        else:
            if gpib_open(addr):
                self.btn_connect.setText("断开设备")
                print(f"GPIB设备 {addr} 连接成功")
            else:
                print("GPIB设备连接失败，请检查地址、驱动、硬件")

    # 开始采集
    @pyqtSlot()
    def on_start_collect(self):
        global collect_running
        if gpib_ud < 0:
            print("请先连接设备！")
            return
        if not collect_running:
            collect_running = True
            # 后台线程采集，不阻塞UI
            t = threading.Thread(target=self.collect_thread, daemon=True)
            t.start()
            print("开始采集...")

    # 停止采集
    @pyqtSlot()
    def on_stop_collect(self):
        global collect_running
        collect_running = False
        print("停止采集")

    # 后台采集线程
    def collect_thread(self):
        global collect_running, data_lock
        while collect_running:
            try:
                # 读取电压、电流（根据你的仪器SCPI指令修改）
                volt_str = gpib_query("MEAS:VOLT?")
                curr_str = gpib_query("MEAS:CURR?")

                volt = float(volt_str) if volt_str else 0.0
                curr = float(curr_str) if curr_str else 0.0

                with data_lock:
                    self.time_count += 1
                    self.x_data.append(self.time_count)
                    self.y_volt.append(volt)
                    self.y_curr.append(curr)

                    # 限制最大点数，防止数据过多卡顿
                    max_points = 1000
                    if len(self.x_data) > max_points:
                        self.x_data.pop(0)
                        self.y_volt.pop(0)
                        self.y_curr.pop(0)
            except Exception as e:
                print(f"采集异常: {e}")
            time.sleep(0.1)  # 采集间隔 100ms

    # 更新绘图（UI线程执行）
    @pyqtSlot()
    def update_plot(self):
        with data_lock:
            self.curve_volt.setData(self.x_data, self.y_volt)
            self.curve_curr.setData(self.x_data, self.y_curr)

    # 窗口关闭时释放资源
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
