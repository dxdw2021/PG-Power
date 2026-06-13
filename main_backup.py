import sys
import os
import ctypes
import threading
import platform
import time
import csv
import logging
import random
from datetime import datetime
from ctypes import c_int, c_char_p, create_string_buffer

# ==============================================
# 日志配置
# ==============================================
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"pg_power_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("PG-Power")
logger.info(f"日志文件: {log_file}")

# ==============================================
# Qt 平台插件路径设置
# ==============================================
if getattr(sys, 'frozen', False):
    _base = sys._MEIPASS
else:
    _base = os.path.dirname(os.path.abspath(__file__))
_qt_search_paths = [
    os.path.join(_base, "PyQt5", "Qt5", "plugins", "platforms"),
    os.path.join(_base, "venv", "Lib", "site-packages", "PyQt5", "Qt5", "plugins", "platforms"),
]
_qt_platforms = None
for _path in _qt_search_paths:
    if os.path.isdir(_path):
        _qt_platforms = _path
        break
if _qt_platforms:
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _qt_platforms
    _qt_bin = os.path.join(os.path.dirname(_qt_platforms), "bin")
    if os.path.isdir(_qt_bin):
        os.environ["PATH"] = _qt_bin + os.pathsep + os.environ.get("PATH", "")

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSpinBox, QDoubleSpinBox, QGroupBox, QMessageBox,
    QFileDialog, QTabWidget, QTextEdit, QSplitter, QFrame,
    QToolBar, QAction
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QIcon
import pyqtgraph as pg

# ==============================================
# GPIB 底层封装
# ==============================================
def get_ni4882_dll_path():
    python_bits = platform.architecture()[0]
    sys_root = os.environ["SystemRoot"]
    if python_bits == "64bit":
        search_paths = [
            os.path.join(sys_root, "System32", "ni4882.dll"),
            os.path.join(sys_root, "SysWOW64", "ni4882.dll"),
        ]
    else:
        search_paths = [
            os.path.join(sys_root, "SysWOW64", "ni4882.dll"),
            os.path.join(sys_root, "System32", "ni4882.dll"),
        ]
    local_dll = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ni4882.dll")
    search_paths.append(local_dll)
    for dll_path in search_paths:
        if os.path.exists(dll_path):
            logger.info(f"加载DLL: {dll_path}")
            return dll_path
    return None

GPIB_AVAILABLE = False
ni4882 = None
dll_path = get_ni4882_dll_path()
if dll_path:
    try:
        ni4882 = ctypes.WinDLL(dll_path)
        ni4882.ibdev.argtypes = [c_int, c_int, c_int, c_int, c_int, c_int]
        ni4882.ibdev.restype = c_int
        ni4882.ibwrt.argtypes = [c_int, c_char_p, c_int]
        ni4882.ibwrt.restype = c_int
        ni4882.ibrd.argtypes = [c_int, c_char_p, c_int]
        ni4882.ibrd.restype = c_int
        ni4882.ibonl.argtypes = [c_int, c_int]
        ni4882.ibonl.restype = c_int
        GPIB_AVAILABLE = True
        logger.info("GPIB驱动加载成功")
    except Exception as e:
        logger.warning(f"GPIB DLL加载失败: {e}")
else:
    logger.warning("未找到ni4882.dll，GPIB功能禁用")

BOARD_IDX = 0
SAD_ADDR = 0
TIMEOUT_LVL = 13
EOT = 1
EOS = 0
READ_BUF_LEN = 256
gpib_ud = -1
data_lock = threading.Lock()

def gpib_open(pad_addr):
    global gpib_ud
    if not GPIB_AVAILABLE or ni4882 is None:
        return False
    gpib_ud = ni4882.ibdev(BOARD_IDX, pad_addr, SAD_ADDR, TIMEOUT_LVL, EOT, EOS)
    return gpib_ud >= 0

def gpib_close():
    global gpib_ud
    if not GPIB_AVAILABLE or ni4882 is None:
        return
    if gpib_ud >= 0:
        ni4882.ibonl(gpib_ud, 0)
        gpib_ud = -1

def gpib_send(cmd):
    if not GPIB_AVAILABLE or gpib_ud < 0:
        return
    cmd_bytes = (cmd + "\r\n").encode("ascii")
    ni4882.ibwrt(gpib_ud, cmd_bytes, len(cmd_bytes))

def gpib_query(cmd):
    if not GPIB_AVAILABLE or gpib_ud < 0:
        return ""
    buf = create_string_buffer(READ_BUF_LEN)
    cmd_bytes = (cmd + "\r\n").encode("ascii")
    ni4882.ibwrt(gpib_ud, cmd_bytes, len(cmd_bytes))
    ni4882.ibrd(gpib_ud, buf, READ_BUF_LEN)
    return buf.value.decode("ascii").strip()

# ==============================================
# 深色主题
# ==============================================
DARK_THEME = """
QMainWindow, QWidget { background-color: #0a0a0c; color: #f0f0f0; font-family: "Microsoft YaHei","Segoe UI",sans-serif; font-size: 13px; }
QGroupBox { background-color: #121212; border: 1px solid #2a2a2a; border-radius: 6px; margin-top: 12px; padding: 12px; font-weight: bold; color: #e0e0e0; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #888; font-size: 11px; }
QLabel { color: #ccc; background: transparent; }
QLabel#valueLabel { color: #fff; font-size: 18px; font-weight: bold; }
QPushButton { border: none; border-radius: 4px; padding: 6px 12px; min-height: 28px; font-weight: bold; color: #fff; }
QPushButton:hover { opacity: 0.9; }
QPushButton:pressed { padding-top: 7px; padding-bottom: 5px; }
QPushButton:disabled { background-color: #333 !important; color: #666 !important; }
QPushButton#btnConnect { background-color: #4a9eff; }
QPushButton#btnStart { background-color: #2fb344; }
QPushButton#btnStop { background-color: #e03131; }
QPushButton#btnTest { background-color: #333; color: #ccc; }
QPushButton#btnTest:checked { background-color: #e67e22; }
QPushButton#btnSave { background-color: #0096ff; }
QPushButton#btnLoad { background-color: #6c5ce7; }
QPushButton#btnClear { background-color: #636e72; }
QTabWidget::pane { border: 1px solid #2a2a2a; }
QTabBar::tab { background: #1a1a1e; color: #888; padding: 8px 16px; border: none; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #fff; border-bottom: 2px solid #4a9eff; }
QTextEdit { background-color: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 4px; color: #ccc; font-family: "Consolas",monospace; font-size: 12px; }
QSpinBox, QDoubleSpinBox { background-color: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 4px; padding: 4px 8px; color: #fff; min-height: 22px; }
QToolBar { background: #0a0a0c; border-bottom: 1px solid #2a2a2a; spacing: 4px; }
QToolBar QToolButton { background: transparent; color: #ccc; border: none; padding: 4px 8px; }
QToolBar QToolButton:hover { background: #1a1a1e; color: #fff; }
QFrame#statusBar { background-color: #121212; border-top: 1px solid #2a2a2a; padding: 4px 8px; }
"""

# ==============================================
# 主窗口
# ==============================================
class IoTPowerMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PG-Power | GPIB电源测试工具")
        self.resize(1400, 850)

        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.timestamps = []
        self.voltages = []
        self.currents = []
        self.powers = []
        self.start_time = time.time()
        self.total_energy_mwh = 0.0
        self.max_current = 0.0
        self.min_current = float("inf")
        self.unit_flag = 0
        self.collecting = False
        self.test_mode = False
        self.plot_mode = "merged"

        self.phases = [
            {"name": "开机", "duration": 310, "volt": 5.0, "curr": 0.300, "std": 0.020},
            {"name": "待机", "duration": 445, "volt": 5.0, "curr": 0.075, "std": 0.005},
            {"name": "通话", "duration": 150, "volt": 5.0, "curr": 0.280, "std": 0.015},
            {"name": "待机", "duration": 443, "volt": 5.0, "curr": 0.075, "std": 0.005},
            {"name": "通话", "duration": 150, "volt": 5.0, "curr": 0.280, "std": 0.015},
            {"name": "待机", "duration": 445, "volt": 5.0, "curr": 0.075, "std": 0.005},
            {"name": "重启", "duration": 310, "volt": 5.0, "curr": 0.300, "std": 0.020},
        ]
        self.current_phase_idx = 0
        self.phase_elapsed = 0

        self.init_ui()

        self.ui_timer = QTimer()
        self.ui_timer.setInterval(50)
        self.ui_timer.timeout.connect(self.update_ui)
        self.ui_timer.start()

        if not GPIB_AVAILABLE:
            QMessageBox.warning(self, "提示", "未检测到NI-488.2驱动，GPIB功能禁用，可使用测试模式预览")

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.tool_bar = QToolBar("工具栏")
        self.addToolBar(self.tool_bar)
        self.action_float = QAction("悬浮窗", self)
        self.action_float.triggered.connect(self.toggle_float)
        self.tool_bar.addAction(self.action_float)

        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        self.tab_wave = QWidget()
        self.init_wave_tab()
        self.tab_widget.addTab(self.tab_wave, "数据与波形")

        self.tab_setting = QWidget()
        self.init_setting_tab()
        self.tab_widget.addTab(self.tab_setting, "设备与设置")

        self.tab_analysis = QWidget()
        self.init_analysis_tab()
        self.tab_widget.addTab(self.tab_analysis, "选区分析")

        self.tab_script = QWidget()
        self.init_script_tab()
        self.tab_widget.addTab(self.tab_script, "脚本控制")

        self.tab_about = QWidget()
        self.init_about_tab()
        self.tab_widget.addTab(self.tab_about, "关于")

    # ========== 标签1：数据与波形 ==========
    def init_wave_tab(self):
        layout = QHBoxLayout(self.tab_wave)
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：瞬时值 + 统计 + GPIB控制 + 数据操作
        left = QWidget()
        left.setFixedWidth(220)
        left_lay = QVBoxLayout(left)
        left_lay.setSpacing(6)

        # 瞬时值
        grp_inst = QGroupBox("瞬时值")
        il = QVBoxLayout(grp_inst)
        il.setSpacing(2)
        self.lb_inst_c = QLabel("0.000 mA")
        self.lb_inst_c.setStyleSheet("color: #0096ff; font-size: 18px; font-weight: bold;")
        self.lb_inst_v = QLabel("0.000 V")
        self.lb_inst_v.setStyleSheet("color: #ff6b6b; font-size: 18px; font-weight: bold;")
        self.lb_inst_p = QLabel("0.000 mW")
        self.lb_inst_p.setStyleSheet("color: #ffcc44; font-size: 18px; font-weight: bold;")
        il.addWidget(self.lb_inst_c)
        il.addWidget(self.lb_inst_v)
        il.addWidget(self.lb_inst_p)
        left_lay.addWidget(grp_inst)

        # 统计
        grp_stat = QGroupBox("全局统计")
        sl = QVBoxLayout(grp_stat)
        sl.setSpacing(2)
        self.lb_avg_c = QLabel("平均电流: -- mA")
        self.lb_max_c = QLabel("最大电流: -- mA")
        self.lb_max_c.setStyleSheet("color: #ff6b6b;")
        self.lb_min_c = QLabel("最小电流: -- mA")
        self.lb_min_c.setStyleSheet("color: #00cccc;")
        self.lb_energy = QLabel("总耗电: -- mWh")
        self.lb_energy.setStyleSheet("color: #ffcc44;")
        self.lb_time = QLabel("总时长: 00:00:00")
        self.btn_unit = QPushButton("切换电量单位")
        self.btn_unit.setObjectName("btnSave")
        self.btn_unit.clicked.connect(self.switch_unit)
        for w in [self.lb_avg_c, self.lb_max_c, self.lb_min_c, self.lb_energy, self.lb_time, self.btn_unit]:
            sl.addWidget(w)
        left_lay.addWidget(grp_stat)

        # GPIB控制
        grp_gpib = QGroupBox("GPIB控制")
        gl = QVBoxLayout(grp_gpib)
        gl.setSpacing(2)
        self.spin_addr = QSpinBox()
        self.spin_addr.setRange(0, 30)
        self.spin_addr.setValue(5)
        gl.addWidget(QLabel("设备地址:"))
        gl.addWidget(self.spin_addr)
        self.btn_conn = QPushButton("连接设备")
        self.btn_conn.setObjectName("btnConnect")
        self.btn_conn.clicked.connect(self.on_connect)
        gl.addWidget(self.btn_conn)
        self.btn_test = QPushButton("测试模式")
        self.btn_test.setObjectName("btnTest")
        self.btn_test.setCheckable(True)
        self.btn_test.clicked.connect(self.on_toggle_test)
        gl.addWidget(self.btn_test)
        self.btn_start = QPushButton("开始采集")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.clicked.connect(self.on_start)
        gl.addWidget(self.btn_start)
        self.btn_stop = QPushButton("停止采集")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.clicked.connect(self.on_stop)
        gl.addWidget(self.btn_stop)
        left_lay.addWidget(grp_gpib)

        # 数据操作
        grp_data = QGroupBox("数据操作")
        dl = QVBoxLayout(grp_data)
        dl.setSpacing(2)
        self.btn_save = QPushButton("保存CSV")
        self.btn_save.setObjectName("btnSave")
        self.btn_save.clicked.connect(self.save_csv)
        self.btn_load = QPushButton("加载数据")
        self.btn_load.setObjectName("btnLoad")
        self.btn_load.clicked.connect(self.load_csv)
        self.btn_clear = QPushButton("清空数据")
        self.btn_clear.setObjectName("btnClear")
        self.btn_clear.clicked.connect(self.clear_data)
        dl.addWidget(self.btn_save)
        dl.addWidget(self.btn_load)
        dl.addWidget(self.btn_clear)
        left_lay.addWidget(grp_data)
        left_lay.addStretch()

        # 中间：波形区域
        mid = QWidget()
        mid_lay = QVBoxLayout(mid)
        mid_lay.setContentsMargins(0, 0, 0, 0)
        mid_lay.setSpacing(0)

        # 合并模式
        self.plot_merged = pg.PlotWidget()
        self.plot_merged.setBackground("#0a0a0c")
        self.plot_merged.showGrid(x=True, y=True, alpha=0.15)
        self.plot_merged.setLabel("left", "数值", color="#888")
        self.plot_merged.setLabel("bottom", "时间 (s)", color="#888")
        self.plot_merged.setTitle("电压 / 电流 波形", color="#e0e0e0", size="12pt")
        self.curve_c_merged = self.plot_merged.plot(pen=pg.mkPen("#0096ff", width=1.5), name="电流(mA)")
        self.curve_v_merged = self.plot_merged.plot(pen=pg.mkPen("#ff6b6b", width=2), name="电压(V)")
        self.plot_merged.addLegend(offset=(-10, 10))
        # 十字线
        self.vLine_m = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color="#555", style=Qt.DashLine, width=1))
        self.hLine_m = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color="#555", style=Qt.DashLine, width=1))
        self.plot_merged.addItem(self.vLine_m, ignoreBounds=True)
        self.plot_merged.addItem(self.hLine_m, ignoreBounds=True)
        self.crosshair_m = pg.TextItem(color="#e0e0e0", anchor=(0, 1),
            border=pg.mkPen(color="#4a9eff", width=1), fill=pg.mkBrush(color="#1a1a1eee"))
        self.crosshair_m.hide()
        self.plot_merged.addItem(self.crosshair_m)
        # 实时值标签
        self.live_c_m = pg.TextItem(color="#0096ff", anchor=(0, 0.5), fill=pg.mkBrush(color="#0a0a0ccc"))
        self.plot_merged.addItem(self.live_c_m)
        self.live_v_m = pg.TextItem(color="#ff6b6b", anchor=(0, 0.5), fill=pg.mkBrush(color="#0a0a0ccc"))
        self.plot_merged.addItem(self.live_v_m)
        # 跟踪短线（电流）
        self.track_c_m = self.plot_merged.plot(pen=pg.mkPen(color="#0096ff", width=1, style=Qt.DotLine))
        self.track_v_m = self.plot_merged.plot(pen=pg.mkPen(color="#ff6b6b", width=1, style=Qt.DotLine))
        self.plot_merged.scene().sigMouseMoved.connect(self.on_mouse_merged)
        # 选区框
        self.region = pg.LinearRegionItem([0, 10], movable=True, brush=pg.mkBrush(74, 158, 255, 40))
        self.region.sigRegionChanged.connect(self.calc_region)
        self.plot_merged.addItem(self.region)
        self.region.setVisible(False)  # 默认隐藏选区框
        mid_lay.addWidget(self.plot_merged)

        # 双波形模式（隐藏）
        self.dual_widget = QWidget()
        self.dual_lay = QVBoxLayout(self.dual_widget)
        self.dual_lay.setContentsMargins(0, 0, 0, 0)
        self.dual_lay.setSpacing(2)
        self.plot_curr = pg.PlotWidget()
        self.plot_curr.setBackground("#0a0a0c")
        self.plot_curr.showGrid(x=True, y=True, alpha=0.15)
        self.plot_curr.setLabel("left", "电流 (mA)", color="#888")
        self.plot_curr.setLabel("bottom", "时间 (s)", color="#888")
        self.plot_curr.setTitle("电流波形", color="#e0e0e0", size="12pt")
        self.curve_c = self.plot_curr.plot(pen=pg.mkPen("#0096ff", width=1.5), name="电流(mA)")
        self.vLine_c = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color="#555", style=Qt.DashLine, width=1))
        self.hLine_c = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color="#555", style=Qt.DashLine, width=1))
        self.plot_curr.addItem(self.vLine_c, ignoreBounds=True)
        self.plot_curr.addItem(self.hLine_c, ignoreBounds=True)
        self.crosshair_c = pg.TextItem(color="#e0e0e0", anchor=(0, 1),
            border=pg.mkPen(color="#4a9eff", width=1), fill=pg.mkBrush(color="#1a1a1eee"))
        self.crosshair_c.hide()
        self.plot_curr.addItem(self.crosshair_c)
        self.live_c = pg.TextItem(color="#0096ff", anchor=(0, 0.5), fill=pg.mkBrush(color="#0a0a0ccc"))
        self.plot_curr.addItem(self.live_c)
        self.plot_curr.scene().sigMouseMoved.connect(self.on_mouse_curr)
        # 电流图跟踪短线
        self.track_c = self.plot_curr.plot(pen=pg.mkPen(color="#0096ff", width=1, style=Qt.DotLine))
        self.dual_lay.addWidget(self.plot_curr)
        self.plot_volt = pg.PlotWidget()
        self.plot_volt.setBackground("#0a0a0c")
        self.plot_volt.showGrid(x=True, y=True, alpha=0.15)
        self.plot_volt.setLabel("left", "电压 (V)", color="#888")
        self.plot_volt.setLabel("bottom", "时间 (s)", color="#888")
        self.plot_volt.setTitle("电压波形", color="#e0e0e0", size="12pt")
        self.curve_v = self.plot_volt.plot(pen=pg.mkPen("#ff6b6b", width=2), name="电压(V)")
        self.vLine_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color="#555", style=Qt.DashLine, width=1))
        self.hLine_v = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color="#555", style=Qt.DashLine, width=1))
        self.plot_volt.addItem(self.vLine_v, ignoreBounds=True)
        self.plot_volt.addItem(self.hLine_v, ignoreBounds=True)
        self.crosshair_v = pg.TextItem(color="#e0e0e0", anchor=(0, 1),
            border=pg.mkPen(color="#4a9eff", width=1), fill=pg.mkBrush(color="#1a1a1eee"))
        self.crosshair_v.hide()
        self.plot_volt.addItem(self.crosshair_v)
        self.live_v = pg.TextItem(color="#ff6b6b", anchor=(0, 0.5), fill=pg.mkBrush(color="#0a0a0ccc"))
        self.plot_volt.addItem(self.live_v)
        self.plot_volt.scene().sigMouseMoved.connect(self.on_mouse_volt)
        # 电压图跟踪短线
        self.track_v = self.plot_volt.plot(pen=pg.mkPen(color="#ff6b6b", width=1, style=Qt.DotLine))
        self.dual_lay.addWidget(self.plot_volt)
        self.dual_widget.hide()
        mid_lay.addWidget(self.dual_widget)

        splitter.addWidget(left)
        splitter.addWidget(mid)
        layout.addWidget(splitter)

    # ========== 十字线回调 ==========
    def on_mouse_merged(self, pos):
        if self.plot_merged.sceneBoundingRect().contains(pos):
            mp = self.plot_merged.plotItem.vb.mapSceneToView(pos)
            self.vLine_m.setPos(mp.x())
            self.hLine_m.setPos(mp.y())
            with data_lock:
                if self.timestamps:
                    idx = max(0, min(int(mp.x()), len(self.timestamps) - 1))
                    v = self.voltages[idx]
                    c = self.currents[idx]
                    p = v * c
                    self.crosshair_m.setText(f" t={mp.x():.1f}s  {v:.3f}V  {c:.1f}mA  {p:.1f}mW ")
                    self.crosshair_m.setPos(mp)
                    self.crosshair_m.show()
        else:
            self.crosshair_m.hide()

    def on_mouse_curr(self, pos):
        if self.plot_curr.sceneBoundingRect().contains(pos):
            mp = self.plot_curr.plotItem.vb.mapSceneToView(pos)
            self.vLine_c.setPos(mp.x())
            self.hLine_c.setPos(mp.y())
            with data_lock:
                if self.timestamps:
                    idx = max(0, min(int(mp.x()), len(self.timestamps) - 1))
                    c = self.currents[idx]
                    self.crosshair_c.setText(f" t={mp.x():.1f}s  {c:.1f}mA ")
                    self.crosshair_c.setPos(mp)
                    self.crosshair_c.show()
        else:
            self.crosshair_c.hide()

    def on_mouse_volt(self, pos):
        if self.plot_volt.sceneBoundingRect().contains(pos):
            mp = self.plot_volt.plotItem.vb.mapSceneToView(pos)
            self.vLine_v.setPos(mp.x())
            self.hLine_v.setPos(mp.y())
            with data_lock:
                if self.timestamps:
                    idx = max(0, min(int(mp.x()), len(self.timestamps) - 1))
                    v = self.voltages[idx]
                    self.crosshair_v.setText(f" t={mp.x():.1f}s  {v:.3f}V ")
                    self.crosshair_v.setPos(mp)
                    self.crosshair_v.show()
        else:
            self.crosshair_v.hide()

    # ========== 标签2：设备与设置 ==========
    def init_setting_tab(self):
        layout = QVBoxLayout(self.tab_setting)
        # 波形模式
        grp_mode = QGroupBox("波形显示")
        m = QVBoxLayout(grp_mode)
        self.btn_mode = QPushButton("切换到双波形模式")
        self.btn_mode.setObjectName("btnTest")
        self.btn_mode.setCheckable(True)
        self.btn_mode.clicked.connect(self.toggle_plot_mode)
        m.addWidget(self.btn_mode)
        layout.addWidget(grp_mode)

        # 跟踪线设置
        grp_track = QGroupBox("跟踪线设置")
        t = QVBoxLayout(grp_track)
        self.track_side = "right"  # 默认右侧
        self.btn_track_left = QPushButton("左侧")
        self.btn_track_left.clicked.connect(lambda: self.set_track_side("left"))
        self.btn_track_right = QPushButton("右侧")
        self.btn_track_right.setObjectName("btnConnect")
        self.btn_track_right.clicked.connect(lambda: self.set_track_side("right"))
        t.addWidget(QLabel("跟踪线位置:"))
        t.addWidget(self.btn_track_left)
        t.addWidget(self.btn_track_right)
        layout.addWidget(grp_track)

        # 输出设置
        grp_out = QGroupBox("输出设置")
        o = QVBoxLayout(grp_out)
        self.spin_max_v = QDoubleSpinBox()
        self.spin_max_v.setRange(0, 5.0)
        self.spin_max_v.setSingleStep(0.001)
        self.spin_max_v.setValue(4.2)
        self.spin_max_c = QDoubleSpinBox()
        self.spin_max_c.setRange(0, 2000)
        self.spin_max_c.setValue(1000)
        self.btn_apply = QPushButton("应用设置")
        self.btn_apply.clicked.connect(self.apply_setting)
        o.addWidget(QLabel("最大电压(V):"))
        o.addWidget(self.spin_max_v)
        o.addWidget(QLabel("最大电流(mA):"))
        o.addWidget(self.spin_max_c)
        o.addWidget(self.btn_apply)
        layout.addWidget(grp_out)
        layout.addStretch()

    def set_track_side(self, side):
        self.track_side = side
        if side == "left":
            self.btn_track_left.setStyleSheet("background-color: #2fb344;")
            self.btn_track_right.setStyleSheet("")
        else:
            self.btn_track_right.setStyleSheet("background-color: #2fb344;")
            self.btn_track_left.setStyleSheet("")
        logger.info(f"跟踪线位置切换到: {side}")

    # ========== 标签3：选区分析 ==========
    def init_analysis_tab(self):
        layout = QVBoxLayout(self.tab_analysis)
        grp = QGroupBox("选区分析")
        g = QVBoxLayout(grp)
        g.setSpacing(8)
        self.lb_reg_v = QLabel("平均电压: -- V")
        self.lb_reg_c = QLabel("平均电流: -- mA")
        self.lb_reg_p = QLabel("平均功率: -- mW")
        self.lb_reg_max = QLabel("最大电流: -- mA")
        self.lb_reg_min = QLabel("最小电流: -- mA")
        self.lb_reg_charge = QLabel("电量: -- μAh")
        self.lb_reg_energy = QLabel("能量: -- μWh")
        self.lb_reg_time = QLabel("时长: -- 秒")
        for lb in [self.lb_reg_v, self.lb_reg_c, self.lb_reg_p,
                   self.lb_reg_max, self.lb_reg_min,
                   self.lb_reg_charge, self.lb_reg_energy, self.lb_reg_time]:
            lb.setStyleSheet("font-size: 14px; padding: 4px;")
            g.addWidget(lb)
        layout.addWidget(grp)
        layout.addStretch()

    # ========== 标签4：脚本控制 ==========
    def init_script_tab(self):
        layout = QVBoxLayout(self.tab_script)
        btn_lay = QHBoxLayout()
        self.btn_run = QPushButton("运行脚本")
        self.btn_run.clicked.connect(self.run_script)
        self.btn_clear_log = QPushButton("清空日志")
        self.btn_clear_log.clicked.connect(lambda: self.log_edit.clear())
        btn_lay.addWidget(self.btn_run)
        btn_lay.addWidget(self.btn_clear_log)
        layout.addLayout(btn_lay)
        splitter = QSplitter(Qt.Vertical)
        self.script_edit = QTextEdit()
        self.script_edit.setPlaceholderText("-- 在此编写脚本\n-- 示例:\ngpib_send('VOLT 4.2')\ngpib_send('OUTP ON')")
        splitter.addWidget(self.script_edit)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("脚本运行日志...")
        splitter.addWidget(self.log_edit)
        layout.addWidget(splitter)

    # ========== 标签5：关于 ==========
    def init_about_tab(self):
        layout = QVBoxLayout(self.tab_about)
        lb = QLabel("<h2>PG-Power | GPIB电源测试工具</h2><p>基于 Python + PyQt5 + PyQtGraph</p><p>兼容 NI-488.2 GPIB 通信协议</p>")
        lb.setAlignment(Qt.AlignCenter)
        layout.addWidget(lb)

    # ========== 模式切换 ==========
    def toggle_plot_mode(self):
        if self.btn_mode.isChecked():
            self.btn_mode.setText("切换到合并模式")
            self.plot_merged.hide()
            self.dual_widget.show()
            self.plot_mode = "dual"
        else:
            self.btn_mode.setText("切换到双波形模式")
            self.dual_widget.hide()
            self.plot_merged.show()
            self.plot_mode = "merged"

    # ========== GPIB ==========
    @pyqtSlot()
    def on_connect(self):
        if not GPIB_AVAILABLE:
            QMessageBox.warning(self, "提示", "GPIB驱动未加载")
            return
        addr = self.spin_addr.value()
        if gpib_ud >= 0:
            gpib_close()
            self.btn_conn.setText("连接设备")
            logger.info("设备已断开")
        else:
            if gpib_open(addr):
                self.btn_conn.setText("断开设备")
                logger.info(f"GPIB设备{addr}连接成功")
            else:
                QMessageBox.critical(self, "失败", "连接失败")

    @pyqtSlot()
    def on_start(self):
        if not self.test_mode and (not GPIB_AVAILABLE or gpib_ud < 0):
            QMessageBox.warning(self, "提示", "请先连接设备或启用测试模式")
            return
        if not self.collecting:
            self.collecting = True
            self.start_time = time.time()
            self.current_phase_idx = 0
            self.phase_elapsed = 0
            threading.Thread(target=self.collect_loop, daemon=True).start()
            logger.info("采集已启动")

    @pyqtSlot()
    def on_stop(self):
        self.collecting = False
        logger.info("采集已停止")

    @pyqtSlot()
    def on_toggle_test(self):
        if self.btn_test.text() == "测试模式":
            self.test_mode = True
            self.btn_test.setText("退出测试")
            self.clear_data()
            logger.info("进入测试模式")
            if not self.collecting:
                self.collecting = True
                self.start_time = time.time()
                self.current_phase_idx = 0
                self.phase_elapsed = 0
                threading.Thread(target=self.collect_loop, daemon=True).start()
                logger.info("采集已启动")
        else:
            self.test_mode = False
            self.btn_test.setText("测试模式")
            self.collecting = False
            logger.info("退出测试模式")

    def collect_loop(self):
        while self.collecting:
            try:
                if self.test_mode:
                    phase = self.phases[self.current_phase_idx]
                    self.phase_elapsed += 1
                    if self.phase_elapsed >= phase["duration"] and self.current_phase_idx < len(self.phases) - 1:
                        self.current_phase_idx += 1
                        self.phase_elapsed = 0
                    volt = phase["volt"] + random.uniform(-0.02, 0.02)
                    curr = (phase["curr"] + random.gauss(0, phase["std"])) * 1000
                else:
                    v_str = gpib_query("MEAS:VOLT?")
                    c_str = gpib_query("MEAS:CURR?")
                    volt = float(v_str) if v_str else 0
                    curr = float(c_str) * 1000 if c_str else 0
                t = time.time() - self.start_time
                power = volt * curr
                self.timestamps.append(t)
                self.voltages.append(volt)
                self.currents.append(curr)
                self.powers.append(power)
                self.max_current = max(self.max_current, curr)
                self.min_current = min(self.min_current, curr)
                if len(self.timestamps) > 1:
                    dt = self.timestamps[-1] - self.timestamps[-2]
                    self.total_energy_mwh += power * dt / 3600
            except Exception as e:
                logger.error(f"采集异常: {e}")
            time.sleep(0.05)

    # ========== UI刷新 ==========
    def update_ui(self):
        if not self.timestamps:
            return
        last_v = self.voltages[-1]
        last_c = self.currents[-1]
        last_p = self.powers[-1]

        if self.plot_mode == "merged":
            self.curve_c_merged.setData(self.timestamps, self.currents)
            self.curve_v_merged.setData(self.timestamps, self.voltages)
            # 只在数据末尾接近视图右边缘时自动滚动
            view = self.plot_merged.plotItem.vb.viewRange()
            x_max_data = self.timestamps[-1] if self.timestamps else 0
            x_max_view = view[0][1]
            # 如果数据末尾接近视图右边缘（差值小于5秒），自动滚动
            if x_max_data >= x_max_view - 5:
                x_min = max(0, x_max_data - 60)
                self.plot_merged.plotItem.vb.setXRange(x_min, x_max_data, padding=0)
            # Y轴自适应
            if self.currents:
                y_max = max(max(self.currents) * 1.1, 10)
                self.plot_merged.plotItem.vb.setYRange(0, y_max, padding=0)
            # 更新跟踪虚线位置（短线段）
            x_right = self.timestamps[-1] if self.timestamps else 0
            x_left = max(0, x_right - 2)
            if self.track_side == "left":
                x_left = max(0, x_right - 60)
                x_right_draw = x_left + 2
                self.track_c_m.setData([x_left, x_right_draw], [last_c, last_c])
                self.track_v_m.setData([x_left, x_right_draw], [last_v, last_v])
            else:
                self.track_c_m.setData([x_left, x_right], [last_c, last_c])
                self.track_v_m.setData([x_left, x_right], [last_v, last_v])
            # 实时值标签
            x_label = max(0, x_right - 60) if self.track_side == "left" else x_right
            self.live_c_m.setText(f" {last_c:.1f}mA ")
            self.live_c_m.setPos(x_label, last_c)
            self.live_c_m.show()
            self.live_v_m.setText(f" {last_v:.3f}V ")
            self.live_v_m.setPos(x_label, last_v)
            self.live_v_m.show()
        else:
            self.curve_c.setData(self.timestamps, self.currents)
            self.curve_v.setData(self.timestamps, self.voltages)
            # 电流图
            view_c = self.plot_curr.plotItem.vb.viewRange()
            x_max_data = self.timestamps[-1] if self.timestamps else 0
            x_max_view_c = view_c[0][1]
            if x_max_data >= x_max_view_c - 5:
                x_min = max(0, x_max_data - 60)
                self.plot_curr.plotItem.vb.setXRange(x_min, x_max_data, padding=0)
            if self.currents:
                y_max = max(max(self.currents) * 1.1, 10)
                self.plot_curr.plotItem.vb.setYRange(0, y_max, padding=0)
            x_label_c = max(0, x_max_data - 60) if self.track_side == "left" else x_max_data
            self.live_c.setText(f" {last_c:.1f}mA ")
            self.live_c.setPos(x_label_c, last_c)
            self.live_c.show()
            # 更新电流图跟踪线（短线段）
            if self.track_side == "left":
                x_left = max(0, x_max_data - 60)
                x_right_draw = x_left + 2
                self.track_c.setData([x_left, x_right_draw], [last_c, last_c])
            else:
                x_left = max(0, x_max_data - 2)
                self.track_c.setData([x_left, x_max_data], [last_c, last_c])
            # 电压图
            view_v = self.plot_volt.plotItem.vb.viewRange()
            x_max_view_v = view_v[0][1]
            if x_max_data >= x_max_view_v - 5:
                x_min = max(0, x_max_data - 60)
                self.plot_volt.plotItem.vb.setXRange(x_min, x_max_data, padding=0)
            if self.voltages:
                y_min_v = min(self.voltages) * 0.9
                y_max_v = max(self.voltages) * 1.1
                self.plot_volt.plotItem.vb.setYRange(y_min_v, y_max_v, padding=0)
            x_label_v = max(0, x_max_data - 60) if self.track_side == "left" else x_max_data
            self.live_v.setText(f" {last_v:.3f}V ")
            self.live_v.setPos(x_label_v, last_v)
            self.live_v.show()
            # 更新电压图跟踪线（短线段）
            if self.track_side == "left":
                x_left = max(0, x_max_data - 60)
                x_right_draw = x_left + 2
                self.track_v.setData([x_left, x_right_draw], [last_v, last_v])
            else:
                x_left = max(0, x_max_data - 2)
                self.track_v.setData([x_left, x_max_data], [last_v, last_v])

        self.lb_inst_c.setText(f"{last_c:.3f} mA")
        self.lb_inst_v.setText(f"{last_v:.4f} V")
        self.lb_inst_p.setText(f"{last_p:.3f} mW")
        avg_c = sum(self.currents) / len(self.currents)
        self.lb_avg_c.setText(f"平均: {avg_c:.1f} mA")
        self.lb_max_c.setText(f"最大: {self.max_current:.1f} mA")
        self.lb_min_c.setText(f"最小: {self.min_current:.1f} mA")
        total_t = self.timestamps[-1]
        h, m, s = int(total_t // 3600), int((total_t % 3600) // 60), int(total_t % 60)
        self.lb_time.setText(f"时长: {h:02d}:{m:02d}:{s:02d}")
        if self.unit_flag == 0:
            self.lb_energy.setText(f"耗电: {self.total_energy_mwh:.2f} mWh")
        else:
            self.lb_energy.setText(f"耗电: {self.total_energy_mwh/1000:.4f} Wh")

    def calc_region(self):
        if not self.timestamps:
            return
        t0, t1 = self.region.getRegion()
        idx = [i for i, t in enumerate(self.timestamps) if t0 <= t <= t1]
        if len(idx) < 2:
            return
        v_reg = [self.voltages[i] for i in idx]
        c_reg = [self.currents[i] for i in idx]
        p_reg = [self.powers[i] for i in idx]
        dt = self.timestamps[idx[-1]] - self.timestamps[idx[0]]
        self.lb_reg_v.setText(f"平均电压: {sum(v_reg)/len(v_reg):.4f} V")
        self.lb_reg_c.setText(f"平均电流: {sum(c_reg)/len(c_reg):.4f} mA")
        self.lb_reg_p.setText(f"平均功率: {sum(p_reg)/len(p_reg):.4f} mW")
        self.lb_reg_max.setText(f"最大电流: {max(c_reg):.4f} mA")
        self.lb_reg_min.setText(f"最小电流: {min(c_reg):.4f} mA")
        self.lb_reg_charge.setText(f"电量: {sum(c_reg)/len(c_reg)*dt/3600*1000:.4f} μAh")
        self.lb_reg_energy.setText(f"能量: {sum(p_reg)/len(p_reg)*dt/3600:.4f} μWh")
        self.lb_reg_time.setText(f"时长: {dt:.2f} 秒")

    def switch_unit(self):
        self.unit_flag = 1 - self.unit_flag
        self.update_ui()

    def apply_setting(self):
        if not GPIB_AVAILABLE or gpib_ud < 0:
            QMessageBox.warning(self, "提示", "请先连接GPIB设备")
            return
        gpib_send(f"VOLT {self.spin_max_v.value():.3f}")
        gpib_send(f"CURR {self.spin_max_c.value()/1000:.3f}")
        QMessageBox.information(self, "成功", "设置已生效")

    def run_script(self):
        code = self.script_edit.toPlainText()
        if not code.strip():
            return
        try:
            exec(code, {"gpib_send": gpib_send, "gpib_query": gpib_query})
            self.log_edit.append(f"[成功] {time.strftime('%H:%M:%S')} 脚本执行完成")
        except Exception as e:
            self.log_edit.append(f"[错误] {time.strftime('%H:%M:%S')} {str(e)}")

    def save_csv(self):
        if not self.timestamps:
            QMessageBox.information(self, "提示", "无数据可保存")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存", "", "CSV (*.csv)")
        if path:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["时间(秒)", "电压(V)", "电流(mA)", "功率(mW)"])
                for t, v, c, p in zip(self.timestamps, self.voltages, self.currents, self.powers):
                    w.writerow([f"{t:.4f}", f"{v:.4f}", f"{c:.4f}", f"{p:.4f}"])
            QMessageBox.information(self, "成功", "数据已保存")

    def load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载", "", "CSV (*.csv)")
        if not path:
            return
        self.clear_data()
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader)
                for row in reader:
                    self.timestamps.append(float(row[0]))
                    self.voltages.append(float(row[1]))
                    self.currents.append(float(row[2]))
                    self.powers.append(float(row[3]))
            QMessageBox.information(self, "成功", "数据加载完成")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def clear_data(self):
        self.timestamps.clear()
        self.voltages.clear()
        self.currents.clear()
        self.powers.clear()
        self.total_energy_mwh = 0
        self.max_current = 0
        self.min_current = float("inf")
        self.curve_c_merged.clear()
        self.curve_v_merged.clear()
        self.curve_c.clear()
        self.curve_v.clear()

    def toggle_float(self):
        if self.windowFlags() & Qt.WindowStaysOnTopHint:
            self.setWindowFlags(Qt.Window)
            self.action_float.setText("悬浮窗")
        else:
            self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
            self.action_float.setText("取消悬浮")
        self.show()

    def closeEvent(self, event):
        self.collecting = False
        gpib_close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME)
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = IoTPowerMainWindow()
    win.show()
    sys.exit(app.exec_())
