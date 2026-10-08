# Python GPIB电源上位机：基于ni4882\.dll与PyQtGraph的实时采集工具

结合 **Python \+ ctypes 直调 ni4882\.dll \+ PyQtGraph 实时绘图 \+ PyQt5**，实现对标功耗仪的 GPIB 电源上位机：包含设备连接、SCPI 控制、电压 / 电流实时曲线、启停控制、数据采集，代码可直接运行。

> 环境要求：
> 
> 1. 已安装 NI\-488\.2 驱动，`ni4882.dll` 正常可用
> 
> 2. 安装依赖：
> 
>     ```bash
>     pip install pyqt5 pyqtgraph
>     ```
> 
> 3. Python 位数与 `ni4882.dll` 位数一致（32/64 位匹配）
> 
> 

---

## 完整代码

```python
import sys
import time
import ctypes
import threading
from ctypes import c_int, c_char_p, create_string_buffer
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QSpinBox, QGroupBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
import pyqtgraph as pg

# ===================== 1. 底层 GPIB(ni4882.dll) 封装 =====================
# 加载DLL
ni4882 = ctypes.WinDLL("ni4882.dll")

# 函数原型声明
ni4882.ibdev.argtypes = [c_int, c_int, c_int, c_int, c_int, c_int]
ni4882.ibdev.restype = c_int

ni4882.ibwrt.argtypes = [c_int, c_char_p, c_int]
ni4882.ibwrt.restype = c_int

ni4882.ibrd.argtypes = [c_int, c_char_p, c_int]
ni4882.ibrd.restype = c_int

ni4882.ibonl.argtypes = [c_int, c_int]
ni4882.ibonl.restype = c_int

# GPIB 全局配置
BOARD_IDX = 0       # GPIB板卡号
SAD_ADDR = 0        # 副地址
TIMEOUT_LVL = 13    # 超时等级(13=10s)
EOT = 1
EOS = 0
READ_BUF_LEN = 256

# 全局变量
gpib_ud = -1        # 设备句柄
collect_running = False  # 采集启停标志
data_lock = threading.Lock()

# GPIB 基础方法
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

# ===================== 2. 主界面 + 绘图逻辑 =====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GPIB 电源实时采集工具")
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
```

---

## 功能说明

1. **设备连接**

    - 填写 NI MAX 中查到的 GPIB 仪器地址，点击「连接设备」

    - 连接成功按钮变为「断开设备」，关闭窗口自动释放 GPIB 句柄

2. **电源控制**

    - `开启输出` / `关闭输出`：直接发送 SCPI `OUTP ON/OFF`

3. **实时采集 \& 绘图**

    - 独立后台线程采集（100ms 间隔），UI 不卡顿

    - 红色曲线 = 电压，绿色曲线 = 电流

    - 限制最大 1000 个数据点，避免内存占用过高

4. **启停采集**

    - 先连设备，再点「开始采集」；随时可「停止采集」

---

## 关键修改点（适配你的硬件）

1. **GPIB 地址**
修改界面上的 GPIB 地址，和 NI MAX 里仪器地址保持一致。

2. **SCPI 指令适配**
不同品牌电源指令略有差异，根据仪器手册修改这两行：

    ```python
    volt_str = gpib_query("MEAS:VOLT?")   # 读电压
    curr_str = gpib_query("MEAS:CURR?")   # 读电流
    ```

    如需**设置电压 / 电流**，新增按钮调用：

    ```python
    gpib_send_cmd("VOLT 5.0")   # 设置5V输出
    gpib_send_cmd("CURR 1.0")   # 设置限流1A
    ```

3. **采集频率**
采集线程里 `time.sleep(0.1)` 代表 100ms 采集一次，按需修改。

---

## 常见报错排查

1. **找不到 ni4882\.dll**

    - 确认安装 NI\-488\.2 驱动；Python 位数与 DLL 位数统一。

2. **连接设备失败**

    - 检查仪器上电、GPIB 线缆、NI MAX 能否识别设备、地址填写正确。

3. **读取数值为空 / 报错**

    - 仪器 SCPI 指令不匹配，查阅设备手册修正查询指令。

4. **曲线不刷新**

    - 必须先「连接设备」再启动采集；检查后台线程是否正常运行。

---

## 扩展方向（对标合宙客户端）

- 增加**电压 / 电流手动设置**输入框 \+ 按钮

- 增加**数据导出 CSV**功能（采集数据保存到本地文件）

- 增加**自动测试脚本**（阶梯电压 / 电流循环测试）

- 增加**功率计算**（P=U\*I）并新增功率曲线

> （注：文档部分内容可能由 AI 生成）
