import sys, os, ctypes, threading, platform, time, csv, logging, json, random
from datetime import datetime
from ctypes import c_int, c_char_p, create_string_buffer

# ===== Log =====
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"pg_power_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(log_file, encoding='utf-8'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("PG-Power")
logger.info(f"日志: {log_file}")

# ===== Qt Plugin =====
if not getattr(sys, 'frozen', False):
    _base = os.path.dirname(os.path.abspath(__file__))
    for _p in [os.path.join(_base, "PyQt5", "Qt5", "plugins", "platforms"),
               os.path.join(_base, "venv", "Lib", "site-packages", "PyQt5", "Qt5", "plugins", "platforms")]:
        if os.path.isdir(_p):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _p
            _b = os.path.join(os.path.dirname(_p), "bin")
            if os.path.isdir(_b): os.environ["PATH"] = _b + os.pathsep + os.environ.get("PATH", "")
            break

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSpinBox, QDoubleSpinBox, QGroupBox, QMessageBox, QFileDialog,
    QTabWidget, QTextEdit, QSplitter, QFrame, QToolBar, QAction, QComboBox, QGridLayout,
    QSlider, QStatusBar, QProgressBar)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QSettings
from PyQt5.QtGui import QIcon
import pyqtgraph as pg

# ===== GPIB =====
def get_dll():
    bits = platform.architecture()[0]; root = os.environ["SystemRoot"]
    for p in [os.path.join(root, "System32" if bits=="64bit" else "SysWOW64", "ni4882.dll"),
              os.path.join(root, "SysWOW64" if bits=="64bit" else "System32", "ni4882.dll"),
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "ni4882.dll")]:
        if os.path.exists(p): return p
    return None

GPIB_OK = False; ni4882 = None; gpib_ud = -1; lock = threading.Lock()
dll = get_dll()
if dll:
    try:
        ni4882 = ctypes.WinDLL(dll)
        ni4882.ibdev.argtypes = [c_int]*6; ni4882.ibdev.restype = c_int
        ni4882.ibwrt.argtypes = [c_int, c_char_p, c_int]; ni4882.ibwrt.restype = c_int
        ni4882.ibrd.argtypes = [c_int, c_char_p, c_int]; ni4882.ibrd.restype = c_int
        ni4882.ibonl.argtypes = [c_int, c_int]; ni4882.ibonl.restype = c_int
        GPIB_OK = True; logger.info("GPIB OK")
    except Exception as e: logger.warning(f"GPIB: {e}")

def g_open(a):
    global gpib_ud
    if not GPIB_OK: return False
    gpib_ud = ni4882.ibdev(0, a, 0, 13, 1, 0); return gpib_ud >= 0
def g_close():
    global gpib_ud
    if GPIB_OK and gpib_ud >= 0: ni4882.ibonl(gpib_ud, 0); gpib_ud = -1
def g_send(c):
    if GPIB_OK and gpib_ud >= 0: ni4882.ibwrt(gpib_ud, (c+"\r\n").encode(), len(c)+2)
def g_qry(c):
    if not GPIB_OK or gpib_ud < 0: return ""
    buf = create_string_buffer(256); ni4882.ibwrt(gpib_ud, (c+"\r\n").encode(), len(c)+2)
    ni4882.ibrd(gpib_ud, buf, 256); return buf.value.decode().strip()

# ===== Theme =====
DARK = """
QMainWindow,QWidget{background:#1e1e2e;color:#cdd6f4;font-family:"Microsoft YaHei","Segoe UI",sans-serif;font-size:13px}
QGroupBox{background:#181825;border:1px solid #313244;border-radius:8px;margin-top:14px;padding:12px;font-weight:bold;color:#cdd6f4}
QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;color:#6c7086;font-size:11px}
QLabel{color:#bac2de;background:transparent}
QPushButton{border:1px solid #313244;border-radius:6px;padding:6px 12px;min-height:28px;font-weight:bold;color:#fff}
QPushButton:hover{opacity:0.9;background:#313244}QPushButton:pressed{padding-top:7px;padding-bottom:5px}
QPushButton:disabled{background:#313244!important;color:#585b70!important;border-color:#313244!important}
QPushButton#conn{background:#89b4fa;border-color:#89b4fa}QPushButton#start{background:#a6e3a1;border-color:#a6e3a1}
QPushButton#stop{background:#f38ba8;border-color:#f38ba8}
QPushButton#test{background:#313244;color:#bac2de;border-color:#45475a}QPushButton#test:checked{background:#fab387;border-color:#fab387}
QPushButton#save{background:#89b4fa;border-color:#89b4fa}QPushButton#load{background:#cba6f7;border-color:#cba6f7}
QPushButton#clear{background:#6c7086;border-color:#6c7086}
QPushButton#on{background:#a6e3a1;border-color:#a6e3a1}QPushButton#off{background:#f38ba8;border-color:#f38ba8}
QMessageBox{background:#1e1e2e}
QMessageBox QLabel{color:#cdd6f4}
QMessageBox QPushButton{min-width:80px;padding:8px 16px}
QTabWidget::pane{border:1px solid #313244;border-radius:4px;background:#1e1e2e}
QTabBar::tab{background:#181825;color:#6c7086;padding:8px 16px;border:1px solid #313244;border-bottom:none;border-radius:4px 4px 0 0;margin-right:2px}
QTabBar::tab:selected{color:#cdd6f4;background:#1e1e2e;border-color:#89b4fa;border-bottom:2px solid #89b4fa}
QTabBar::tab:hover{color:#bac2de;background:#1e1e2e}
QTextEdit{background:#11111b;border:1px solid #313244;border-radius:4px;color:#bac2de;font-family:"Consolas",monospace;font-size:12px}
QSpinBox,QDoubleSpinBox,QComboBox{background:#11111b;border:1px solid #313244;border-radius:4px;padding:4px 8px;color:#cdd6f4;min-height:22px}
QToolBar{background:#11111b;border-bottom:1px solid #313244;spacing:4px;padding:2px}
QToolBar QToolButton{background:#1e1e2e;color:#bac2de;border:1px solid #313244;border-radius:4px;padding:4px 10px;font-weight:bold}
QToolBar QToolButton:hover{background:#313244;color:#cdd6f4;border-color:#45475a}
QToolBar QToolButton:pressed{background:#45475a}
QStatusBar{background:#11111b;border-top:1px solid #313244;color:#6c7086;font-size:11px}
QSlider::groove:horizontal{height:4px;background:#313244;border-radius:2px}
QSlider::handle:horizontal{width:14px;height:14px;margin:-5px 0;background:#89b4fa;border-radius:7px}
QProgressBar{border:1px solid #313244;border-radius:4px;text-align:center;color:#cdd6f4}
QProgressBar::chunk{background:#89b4fa;border-radius:3px}
"""

LIGHT = """
QMainWindow,QWidget{background:#eff1f5;color:#4c4f69;font-family:"Microsoft YaHei","Segoe UI",sans-serif;font-size:13px}
QGroupBox{background:#e6e9ef;border:1px solid #ccd0da;border-radius:8px;margin-top:14px;padding:12px;font-weight:bold;color:#4c4f69}
QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;color:#7c7f93;font-size:11px}
QLabel{color:#5c5f77;background:transparent}
QPushButton{border:none;border-radius:6px;padding:6px 12px;min-height:28px;font-weight:bold;color:#fff}
QPushButton:hover{opacity:0.9}QPushButton:pressed{padding-top:7px;padding-bottom:5px}
QPushButton:disabled{background:#ccd0da!important;color:#9ca0b0!important}
QPushButton#conn{background:#1e66f5}QPushButton#start{background:#40a02b}QPushButton#stop{background:#d20f39}
QPushButton#test{background:#ccd0da;color:#5c5f77}QPushButton#test:checked{background:#fe640b}
QPushButton#save{background:#1e66f5}QPushButton#load{background:#8839ef}QPushButton#clear{background:#7c7f93}
QPushButton#on{background:#40a02b}QPushButton#off{background:#d20f39}
QTabWidget::pane{border:1px solid #ccd0da}
QTabBar::tab{background:#e6e9ef;color:#7c7f93;padding:8px 16px;border:none;border-bottom:2px solid transparent}
QTabBar::tab:selected{color:#4c4f69;border-bottom:2px solid #1e66f5}
QTextEdit{background:#fff;background:#eff1f5;border:1px solid #ccd0da;border-radius:4px;color:#5c5f77;font-family:"Consolas",monospace;font-size:12px}
QSpinBox,QDoubleSpinBox,QComboBox{background:#eff1f5;border:1px solid #ccd0da;border-radius:4px;padding:4px 8px;color:#4c4f69;min-height:22px}
QToolBar{background:#e6e9ef;border-bottom:1px solid #ccd0da;spacing:4px;padding:2px}
QToolBar QToolButton{background:#eff1f5;color:#5c5f77;border:1px solid #ccd0da;border-radius:4px;padding:4px 10px;font-weight:bold}
QToolBar QToolButton:hover{background:#ccd0da;color:#4c4f69;border-color:#bcc0cc}
QToolBar QToolButton:pressed{background:#bcc0cc}
QStatusBar{background:#e6e9ef;border-top:1px solid #ccd0da;color:#7c7f93;font-size:11px}
QSlider::groove:horizontal{height:4px;background:#ccd0da;border-radius:2px}
QSlider::handle:horizontal{width:14px;height:14px;margin:-5px 0;background:#1e66f5;border-radius:7px}
QProgressBar{border:1px solid #ccd0da;border-radius:4px;text-align:center;color:#4c4f69}
QProgressBar::chunk{background:#1e66f5;border-radius:3px}
"""

class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PG-Power | GPIB电源测试工具 v2.0")
        self.resize(1500, 900)
        ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(ico): self.setWindowIcon(QIcon(ico))

        # Data
        self.ts=[]; self.vs=[]; self.cs=[]; self.ps=[]
        self.t0=time.time(); self.e_mwh=0.0; self.max_c=0.0; self.min_c=float("inf")
        self.collecting=False; self.test_mode=False; self.track_side="right"
        self.display_mode="instant"  # instant / average
        self.unit=0  # 0=mWh/Ah  1=Wh/Ah
        self.coord_mode=0  # 0=adaptive 1=fixed 2=log
        self.scroll_pos=0

        # Test phases
        self.phases=[{"n":"开机","d":310,"v":5.0,"c":0.300,"s":0.020},
            {"n":"待机","d":445,"v":5.0,"c":0.075,"s":0.005},{"n":"通话","d":150,"v":5.0,"c":0.280,"s":0.015},
            {"n":"待机","d":443,"v":5.0,"c":0.075,"s":0.005},{"n":"通话","d":150,"v":5.0,"c":0.280,"s":0.015},
            {"n":"待机","d":445,"v":5.0,"c":0.075,"s":0.005},{"n":"重启","d":310,"v":5.0,"c":0.300,"s":0.020}]
        self.phi=0; self.pe=0

        # Cache settings
        self.auto_save_threshold=50000
        self.save_count=0

        self._init_ui()
        self._load_settings()

        self.timer=QTimer(); self.timer.setInterval(50); self.timer.timeout.connect(self._ui); self.timer.start()
        self.statusBar().showMessage("就绪 | GPIB: " + ("可用" if GPIB_OK else "不可用"))

        if not GPIB_OK:
            QMessageBox.warning(self,"提示","GPIB驱动未加载，可使用测试模式预览")

    def _init_ui(self):
        m=QVBoxLayout(self); m.setContentsMargins(0,0,0,0); m.setSpacing(0)
        tb=QToolBar(); self.addToolBar(tb)
        self.act_float=QAction("悬浮窗",self); self.act_float.triggered.connect(self._float); tb.addAction(self.act_float)
        self.act_save_auto=QAction("自动保存:开",self); self.act_save_auto.setCheckable(True)
        self.act_save_auto.setChecked(True); self.act_save_auto.triggered.connect(self._toggle_auto_save)
        tb.addAction(self.act_save_auto)
        self.act_mode=QAction("切换到合并模式",self); self.act_mode.triggered.connect(self._mode); tb.addAction(self.act_mode)
        # Theme toggle
        self.theme_idx=0  # 0=dark 1=light 2=auto
        self.act_theme=QAction("深色主题",self); self.act_theme.triggered.connect(self._toggle_theme); tb.addAction(self.act_theme)
        # Region analysis toggle
        self.act_region=QAction("选区分析:关",self); self.act_region.triggered.connect(self._toggle_region_tb); tb.addAction(self.act_region)

        tabs=QTabWidget(); self.setCentralWidget(tabs)
        w1=QWidget(); tabs.addTab(w1,"数据与波形")
        w2=QWidget(); tabs.addTab(w2,"设备与设置")
        w3=QWidget(); tabs.addTab(w3,"选区分析")
        w4=QWidget(); tabs.addTab(w4,"脚本控制")
        w5=QWidget(); tabs.addTab(w5,"关于")

        self._init_wave(w1); self._init_settings(w2); self._init_analysis(w3)
        self._init_script(w4)
        QVBoxLayout(w5).addWidget(QLabel("<h2>PG-Power v2.0</h2><p>基于LuatOS PC客户端功能规范</p><p>Python + PyQt5 + PyQtGraph</p>"))

    # ===== Tab1: Wave =====
    def _init_wave(self, parent):
        lay=QHBoxLayout(parent); sp=QSplitter(Qt.Horizontal)

        # Left
        left=QWidget(); left.setFixedWidth(220); ll=QVBoxLayout(left); ll.setSpacing(4)

        # Display mode selector
        g0=QGroupBox("显示模式"); gl0=QVBoxLayout(g0)
        self.cb_disp=QComboBox(); self.cb_disp.addItems(["瞬时值","滑动平均值"])
        self.cb_disp.currentIndexChanged.connect(lambda i: setattr(self,'display_mode',['instant','average'][i]))
        gl0.addWidget(self.cb_disp); ll.addWidget(g0)

        # Instant values
        g1=QGroupBox("当前数据"); gl1=QVBoxLayout(g1); gl1.setSpacing(2)
        self.lb_ic=QLabel("0.000 mA"); self.lb_ic.setStyleSheet("color:#89b4fa;font-size:18px;font-weight:bold")
        self.lb_iv=QLabel("0.000 V"); self.lb_iv.setStyleSheet("color:#f38ba8;font-size:18px;font-weight:bold")
        self.lb_ip=QLabel("0.000 mW"); self.lb_ip.setStyleSheet("color:#f9e2af;font-size:18px;font-weight:bold")
        gl1.addWidget(self.lb_ic); gl1.addWidget(self.lb_iv); gl1.addWidget(self.lb_ip); ll.addWidget(g1)

        # Average
        g2=QGroupBox("平均数据"); gl2=QVBoxLayout(g2); gl2.setSpacing(2)
        self.lb_ac=QLabel("平均电流: -- mA")
        self.lb_av=QLabel("平均电压: -- V")
        self.lb_ap=QLabel("平均功率: -- mW")
        gl2.addWidget(self.lb_ac); gl2.addWidget(self.lb_av); gl2.addWidget(self.lb_ap); ll.addWidget(g2)

        # Cumulative
        g3=QGroupBox("累计数据"); gl3=QVBoxLayout(g3); gl3.setSpacing(2)
        self.lb_mx=QLabel("最大电流: -- mA"); self.lb_mx.setStyleSheet("color:#f38ba8")
        self.lb_mn=QLabel("最小电流: -- mA"); self.lb_mn.setStyleSheet("color:#a6e3a1")
        self.lb_en=QLabel("总耗电: -- mWh"); self.lb_en.setStyleSheet("color:#f9e2af")
        self.lb_ah=QLabel("累计电量: -- mAh"); self.lb_ah.setStyleSheet("color:#89dceb")
        self.lb_tm=QLabel("总时长: 00:00:00")
        self.lb_n=QLabel("采样点数: 0")
        self.btn_unit=QPushButton("切换 mWh/Wh"); self.btn_unit.setObjectName("save")
        self.btn_unit.clicked.connect(self._switch_unit)
        gl3.addWidget(self.lb_mx); gl3.addWidget(self.lb_mn); gl3.addWidget(self.lb_en)
        gl3.addWidget(self.lb_ah); gl3.addWidget(self.lb_tm); gl3.addWidget(self.lb_n)
        gl3.addWidget(self.btn_unit); ll.addWidget(g3)

        # GPIB
        g4=QGroupBox("GPIB控制"); gl4=QVBoxLayout(g4); gl4.setSpacing(2)
        self.spin_a=QSpinBox(); self.spin_a.setRange(0,30); self.spin_a.setValue(5)
        gl4.addWidget(QLabel("设备地址:")); gl4.addWidget(self.spin_a)
        self.btn_co=QPushButton("连接设备"); self.btn_co.setObjectName("conn")
        self.btn_co.clicked.connect(self._connect); gl4.addWidget(self.btn_co)
        self.btn_te=QPushButton("测试模式"); self.btn_te.setObjectName("test")
        self.btn_te.setCheckable(True); self.btn_te.clicked.connect(self._toggle_test); gl4.addWidget(self.btn_te)
        self.btn_st=QPushButton("开始采集"); self.btn_st.setObjectName("start")
        self.btn_st.clicked.connect(self._start); gl4.addWidget(self.btn_st)
        self.btn_sp=QPushButton("停止采集"); self.btn_sp.setObjectName("stop")
        self.btn_sp.clicked.connect(self._stop); gl4.addWidget(self.btn_sp)
        ll.addWidget(g4)

        # Data ops
        g5=QGroupBox("数据操作"); gl5=QVBoxLayout(g5); gl5.setSpacing(2)
        self.btn_sv=QPushButton("保存CSV"); self.btn_sv.setObjectName("save"); self.btn_sv.clicked.connect(self._save)
        self.btn_ld=QPushButton("加载数据"); self.btn_ld.setObjectName("load"); self.btn_ld.clicked.connect(self._load)
        self.btn_cl=QPushButton("清空数据"); self.btn_cl.setObjectName("clear"); self.btn_cl.clicked.connect(self._clear)
        gl5.addWidget(self.btn_sv); gl5.addWidget(self.btn_ld); gl5.addWidget(self.btn_cl)
        ll.addWidget(g5); ll.addStretch()

        # Mid
        mid=QWidget(); ml=QVBoxLayout(mid); ml.setContentsMargins(0,0,0,0); ml.setSpacing(2)

        # Merged plot (dual Y-axis: left=current, right=voltage)
        self.pm=pg.PlotWidget(); self.pm.setBackground("#11111b"); self.pm.showGrid(x=True,y=True,alpha=0.1)
        self.pm.setLabel("left","电流 (mA)",color="#89b4fa"); self.pm.setLabel("bottom","时间 (s)",color="#6c7086")
        self.pm.setTitle("电压 / 电流 波形",color="#cdd6f4",size="12pt")
        # Right axis for voltage
        self.pm.showAxis('right')
        self.pm.plotItem.getAxis('right').setLabel("电压 (V)",color="#f38ba8")
        # Current curve (left Y-axis) - with fill effect like dual mode
        self.cm_c=self.pm.plot(pen=pg.mkPen("#89b4fa",width=2),fillLevel=0,brush=pg.mkBrush(137,180,250,40),name="电流(mA)")
        # Voltage curve (right Y-axis) - use secondary ViewBox
        self.pm_vb2=pg.ViewBox()
        self.pm.plotItem.scene().addItem(self.pm_vb2)
        self.pm.plotItem.getAxis('right').linkToView(self.pm_vb2)
        self.pm_vb2.setXLink(self.pm.plotItem.vb)
        self.cm_v=pg.PlotDataItem(pen=pg.mkPen("#f38ba8",width=2),name="电压(V)")
        self.pm_vb2.addItem(self.cm_v)
        self.pm.addLegend(offset=(-10,10))
        # Sync ViewBoxes - defer initial sync
        self.pm.plotItem.vb.sigResized.connect(self._sync_vb)
        self.vm=pg.InfiniteLine(90,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.hm=pg.InfiniteLine(0,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.pm.addItem(self.vm,ignoreBounds=True); self.pm.addItem(self.hm,ignoreBounds=True)
        self.xm=pg.TextItem(color="#cdd6f4",anchor=(0,1),border=pg.mkPen("#585b70",width=1),fill=pg.mkBrush("#1e1e2eee"))
        self.xm.hide(); self.pm.addItem(self.xm)
        # Real-time labels for merged mode
        self.lmc=pg.TextItem(color="#89b4fa",anchor=(0,0.5),fill=pg.mkBrush("#11111bcc"))
        self.pm.addItem(self.lmc)
        self.lmv=pg.TextItem(color="#f38ba8",anchor=(1,0.5),fill=pg.mkBrush("#11111bcc"))
        self.pm.addItem(self.lmv)
        self.pm.scene().sigMouseMoved.connect(self._mm)
        self.pm.hide()
        ml.addWidget(self.pm)

        # Dual mode: Current plot
        self.pc=pg.PlotWidget(); self.pc.setBackground("#11111b"); self.pc.showGrid(x=True,y=True,alpha=0.1)
        self.pc.setLabel("left","电流 (mA)",color="#6c7086"); self.pc.setLabel("bottom","时间 (s)",color="#6c7086")
        self.pc.setTitle("电流波形",color="#cdd6f4",size="12pt")
        self.cc=self.pc.plot(pen=pg.mkPen("#89b4fa",width=2),fillLevel=0,brush=pg.mkBrush(137,180,250,40))
        self.vc=pg.InfiniteLine(90,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.hc=pg.InfiniteLine(0,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.pc.addItem(self.vc,ignoreBounds=True); self.pc.addItem(self.hc,ignoreBounds=True)
        self.xc=pg.TextItem(color="#cdd6f4",anchor=(0,1),border=pg.mkPen("#585b70",width=1),fill=pg.mkBrush("#1e1e2eee"))
        self.xc.hide(); self.pc.addItem(self.xc)
        self.lc=pg.TextItem(color="#89b4fa",anchor=(0,0.5),fill=pg.mkBrush("#11111bcc"))
        self.pc.addItem(self.lc)
        self.tc=self.pc.plot(pen=pg.mkPen("#89b4fa",width=1,style=Qt.DotLine))
        self.pc.scene().sigMouseMoved.connect(self._mc)
        ml.addWidget(self.pc)

        # Dual mode: Voltage plot
        self.pv=pg.PlotWidget(); self.pv.setBackground("#11111b"); self.pv.showGrid(x=True,y=True,alpha=0.1)
        self.pv.setLabel("left","电压 (V)",color="#6c7086"); self.pv.setLabel("bottom","时间 (s)",color="#6c7086")
        self.pv.setTitle("电压波形",color="#cdd6f4",size="12pt")
        self.cv=self.pv.plot(pen=pg.mkPen("#f38ba8",width=2))
        self.vvl=pg.InfiniteLine(90,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.hvl=pg.InfiniteLine(0,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.pv.addItem(self.vvl,ignoreBounds=True); self.pv.addItem(self.hvl,ignoreBounds=True)
        self.xvl=pg.TextItem(color="#cdd6f4",anchor=(0,1),border=pg.mkPen("#585b70",width=1),fill=pg.mkBrush("#1e1e2eee"))
        self.xvl.hide(); self.pv.addItem(self.xvl)
        self.lvl=pg.TextItem(color="#f38ba8",anchor=(0,0.5),fill=pg.mkBrush("#11111bcc"))
        self.pv.addItem(self.lvl)
        self.tvl=self.pv.plot(pen=pg.mkPen("#f38ba8",width=1,style=Qt.DotLine))
        self.pv.scene().sigMouseMoved.connect(self._mv)
        ml.addWidget(self.pv)

        # Time slider
        self.slider=QSlider(Qt.Horizontal); self.slider.setRange(0,100); self.slider.setValue(100)
        self.slider.valueChanged.connect(self._on_slider)
        ml.addWidget(self.slider)

        # Selection state
        self.sel_active=False; self.sel_start=None; self.sel_rect=None
        self.sel_region=None; self.sel_analysis=None
        self.user_scrolling=False; self.scroll_timer=QTimer(); self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(lambda: setattr(self,'user_scrolling',False))

        sp.addWidget(left); sp.addWidget(mid); lay.addWidget(sp)

    def _sync_vb(self):
        self.pm_vb2.setGeometry(self.pm.plotItem.vb.sceneBoundingRect())

    # ===== Crosshair =====
    def _mc(self, pos):
        if self.pc.sceneBoundingRect().contains(pos):
            mp=self.pc.plotItem.vb.mapSceneToView(pos)
            self.vc.setPos(mp.x()); self.hc.setPos(mp.y())
            with lock:
                if self.ts:
                    i=max(0,min(int(mp.x()),len(self.ts)-1))
                    v,c,p=self.vs[i],self.cs[i],self.ps[i]
                    self.xc.setText(f" t={mp.x():.1f}s  {v:.3f}V  {c:.1f}mA  {p:.1f}mW ")
                    self.xc.setPos(mp); self.xc.show()
        else: self.xc.hide()

    def _mv(self, pos):
        if self.pv.sceneBoundingRect().contains(pos):
            mp=self.pv.plotItem.vb.mapSceneToView(pos)
            self.vvl.setPos(mp.x()); self.hvl.setPos(mp.y())
            with lock:
                if self.ts:
                    i=max(0,min(int(mp.x()),len(self.ts)-1))
                    self.xvl.setText(f" t={mp.x():.1f}s  {self.vs[i]:.3f}V ")
                    self.xvl.setPos(mp); self.xvl.show()
        else: self.xvl.hide()

    def _mm(self, pos):
        if self.pm.sceneBoundingRect().contains(pos):
            mp=self.pm.plotItem.vb.mapSceneToView(pos)
            self.vm.setPos(mp.x()); self.hm.setPos(mp.y())
            with lock:
                if self.ts:
                    i=max(0,min(int(mp.x()),len(self.ts)-1))
                    v,c,p=self.vs[i],self.cs[i],self.ps[i]
                    self.xm.setText(f" t={mp.x():.1f}s  {v:.3f}V  {c:.1f}mA  {p:.1f}mW ")
                    self.xm.setPos(mp); self.xm.show()
        else: self.xm.hide()

    def mousePressEvent(self, event):
        if event.button()==Qt.RightButton and (self.btn_region.isChecked() or self.act_region.text()=="选区分析:开"):
            pos=event.pos()
            if self.pm.isVisible():
                if self.pm.sceneBoundingRect().contains(pos):
                    mp=self.pm.plotItem.vb.mapSceneToView(pos)
                    self.sel_start=mp.x(); self.sel_active=True
            elif self.pc.isVisible():
                if self.pc.sceneBoundingRect().contains(pos):
                    mp=self.pc.plotItem.vb.mapSceneToView(pos)
                    self.sel_start=mp.x(); self.sel_active=True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button()==Qt.RightButton and self.sel_active:
            self.sel_active=False
            pos=event.pos()
            if self.pm.isVisible() and self.pm.sceneBoundingRect().contains(pos):
                mp=self.pm.plotItem.vb.mapSceneToView(pos)
                self._show_analysis(min(self.sel_start,mp.x()),max(self.sel_start,mp.x()))
            elif self.pc.isVisible() and self.pc.sceneBoundingRect().contains(pos):
                mp=self.pc.plotItem.vb.mapSceneToView(pos)
                self._show_analysis(min(self.sel_start,mp.x()),max(self.sel_start,mp.x()))
        super().mouseReleaseEvent(event)

    def _show_analysis(self,t0,t1):
        if not self.ts or t1-t0<1: return
        idx=[i for i,t in enumerate(self.ts) if t0<=t<=t1]
        if len(idx)<2: return
        vr=[self.vs[i] for i in idx]; cr=[self.cs[i] for i in idx]; pr=[self.ps[i] for i in idx]
        dt=self.ts[idx[-1]]-self.ts[idx[0]]
        self.rv.setText(f"平均电压: {sum(vr)/len(vr):.4f} V")
        self.rc.setText(f"平均电流: {sum(cr)/len(cr):.4f} mA")
        self.rp.setText(f"平均功率: {sum(pr)/len(pr):.4f} mW")
        self.rmx.setText(f"最大电流: {max(cr):.4f} mA")
        self.rmn.setText(f"最小电流: {min(cr):.4f} mA")
        self.rch.setText(f"电量(μAh): {sum(cr)/len(cr)*dt/3600*1000:.4f}")
        self.ren.setText(f"能量(μWh): {sum(pr)/len(pr)*dt/3600:.4f}")
        self.rtm.setText(f"时长: {dt:.2f} 秒")
        self.rn.setText(f"采样点数: {len(idx)}")
        QMessageBox.information(self,"选区分析",f"选区 {t0:.1f}s ~ {t1:.1f}s 分析结果已显示在选区分析标签页")

    # ===== Tab2: Settings =====
    def _init_settings(self, parent):
        lay=QVBoxLayout(parent); lay.setSpacing(8)

        # Row 1: Coord + Track + Region (horizontal)
        row1=QHBoxLayout()
        # Coord mode
        g=QGroupBox("坐标设置"); gl=QGridLayout(g); gl.setSpacing(4)
        self.cb_coord=QComboBox(); self.cb_coord.addItems(["自适应坐标","固定最大值坐标","对数坐标"])
        self.cb_coord.currentIndexChanged.connect(lambda i: setattr(self,'coord_mode',i))
        gl.addWidget(QLabel("模式:"),0,0); gl.addWidget(self.cb_coord,0,1)
        self.chk_auto=QPushButton("自动适应"); self.chk_auto.setCheckable(True)
        self.chk_auto.setChecked(True); self.chk_auto.clicked.connect(self._auto_adapt)
        gl.addWidget(self.chk_auto,1,0,1,2)
        row1.addWidget(g)
        # Track
        gt=QGroupBox("跟踪线"); tl=QGridLayout(gt); tl.setSpacing(4)
        tl.addWidget(QLabel("位置:"),0,0)
        self.btn_tl=QPushButton("左"); self.btn_tl.clicked.connect(lambda:self._ts("left"))
        self.btn_tr=QPushButton("右"); self.btn_tr.setObjectName("conn"); self.btn_tr.clicked.connect(lambda:self._ts("right"))
        tl.addWidget(self.btn_tl,0,1); tl.addWidget(self.btn_tr,0,2)
        row1.addWidget(gt)
        # Region
        ga=QGroupBox("选区分析"); al=QVBoxLayout(ga); al.setSpacing(4)
        self.btn_region=QPushButton("开启选区"); self.btn_region.setObjectName("test")
        self.btn_region.setCheckable(True); self.btn_region.clicked.connect(self._toggle_region)
        al.addWidget(self.btn_region)
        row1.addWidget(ga)
        lay.addLayout(row1)

        # Row 2: Output (horizontal)
        go=QGroupBox("设备输出"); ol=QGridLayout(go); ol.setSpacing(4)
        ol.addWidget(QLabel("最大电压(V):"),0,0); self.sv=QDoubleSpinBox(); self.sv.setRange(0,5); self.sv.setSingleStep(0.001); self.sv.setValue(4.2); ol.addWidget(self.sv,0,1)
        ol.addWidget(QLabel("最大电流(mA):"),0,2); self.sc=QDoubleSpinBox(); self.sc.setRange(0,2000); self.sc.setValue(1000); ol.addWidget(self.sc,0,3)
        self.btn_on=QPushButton("开启输出"); self.btn_on.setObjectName("on"); self.btn_on.clicked.connect(lambda: g_send("OUTP ON"))
        self.btn_off=QPushButton("关闭输出"); self.btn_off.setObjectName("off"); self.btn_off.clicked.connect(lambda: g_send("OUTP OFF"))
        ba=QPushButton("应用设置"); ba.clicked.connect(self._apply)
        ol.addWidget(self.btn_on,1,0); ol.addWidget(self.btn_off,1,1); ol.addWidget(ba,1,2)
        lay.addWidget(go)

        # Row 3: Scale + Cache + Line (horizontal)
        row3=QHBoxLayout()
        # Scale
        gv=QGroupBox("刻度设置"); vl=QGridLayout(gv); vl.setSpacing(4)
        vl.addWidget(QLabel("电流(mA):"),0,0); self.spin_cmin=QDoubleSpinBox(); self.spin_cmin.setRange(-1000,1000); self.spin_cmin.setValue(0); self.spin_cmin.setSingleStep(10); vl.addWidget(self.spin_cmin,0,1)
        vl.addWidget(QLabel("~"),0,2); self.spin_cmax=QDoubleSpinBox(); self.spin_cmax.setRange(1,10000); self.spin_cmax.setValue(350); self.spin_cmax.setSingleStep(10); vl.addWidget(self.spin_cmax,0,3)
        vl.addWidget(QLabel("电压(V):"),1,0); self.spin_vmin=QDoubleSpinBox(); self.spin_vmin.setRange(-10,10); self.spin_vmin.setValue(0); self.spin_vmin.setSingleStep(0.5); vl.addWidget(self.spin_vmin,1,1)
        vl.addWidget(QLabel("~"),1,2); self.spin_vmax=QDoubleSpinBox(); self.spin_vmax.setRange(0.1,100); self.spin_vmax.setValue(20); self.spin_vmax.setSingleStep(1); vl.addWidget(self.spin_vmax,1,3)
        row3.addWidget(gv)
        # Cache
        gc=QGroupBox("数据缓存"); cl=QGridLayout(gc); cl.setSpacing(4)
        cl.addWidget(QLabel("自动保存阈值:"),0,0); self.spin_cache=QSpinBox(); self.spin_cache.setRange(10000,1000000); self.spin_cache.setValue(50000); self.spin_cache.setSingleStep(10000); cl.addWidget(self.spin_cache,0,1)
        cl.addWidget(QLabel("点"),0,2)
        row3.addWidget(gc)
        # Line width
        glw=QGroupBox("曲线样式"); lw=QGridLayout(glw); lw.setSpacing(4)
        lw.addWidget(QLabel("线条粗细:"),0,0); self.spin_lw=QDoubleSpinBox(); self.spin_lw.setRange(0.5,10); self.spin_lw.setValue(2); self.spin_lw.setSingleStep(0.5); self.spin_lw.setSuffix(" px"); lw.addWidget(self.spin_lw,0,1)
        row3.addWidget(glw)
        lay.addLayout(row3)

        lay.addStretch()

    def _auto_adapt(self):
        if self.chk_auto.isChecked():
            self.chk_auto.setText("自动适应坐标")
            self.pm.plotItem.vb.enableAutoRange(axis=self.pm.plotItem.vb.YAxis)
            self.pm_vb2.enableAutoRange(axis=self.pm_vb2.YAxis)
        else:
            self.chk_auto.setText("固定坐标")
            self.pm.plotItem.vb.enableAutoRange(axis=self.pm.plotItem.vb.YAxis, enable=False)
            self.pm_vb2.enableAutoRange(axis=self.pm_vb2.YAxis, enable=False)
            cmin=self.spin_cmin.value(); cmax=self.spin_cmax.value()
            self.pm.plotItem.vb.setYRange(cmin,cmax,padding=0)
            vmin=self.spin_vmin.value(); vmax=self.spin_vmax.value()
            self.pm_vb2.setYRange(vmin,vmax,padding=0)

    def _ts(self, s):
        self.track_side=s
        self.btn_tl.setStyleSheet("background:#a6e3a1;" if s=="left" else "")
        self.btn_tr.setStyleSheet("background:#a6e3a1;" if s=="right" else "")

    def _toggle_region(self):
        if self.btn_region.isChecked():
            self.btn_region.setText("关闭选区分析")
            self.act_region.setText("选区分析:开")
        else:
            self.btn_region.setText("开启选区分析")
            self.act_region.setText("选区分析:关")

    def _toggle_region_tb(self):
        if self.act_region.text()=="选区分析:关":
            self.act_region.setText("选区分析:开")
            self.btn_region.setChecked(True)
            self.btn_region.setText("关闭选区分析")
        else:
            self.act_region.setText("选区分析:关")
            self.btn_region.setChecked(False)
            self.btn_region.setText("开启选区分析")

    def _mode(self):
        if self.act_mode.text()=="切换到合并模式":
            self.act_mode.setText("切换到双波形模式")
            self.pc.hide(); self.pv.hide(); self.pm.show()
            if self.btn_region.isChecked():
                self.region.setVisible(False); self.region_m.setVisible(True)
            # Auto-adapt off for merged mode
            self.chk_auto.setChecked(False)
            self._auto_adapt()
        else:
            self.act_mode.setText("切换到合并模式")
            self.pm.hide(); self.pc.show(); self.pv.show()
            if self.btn_region.isChecked():
                self.region.setVisible(True); self.region_m.setVisible(False)

    # ===== Tab3: Analysis =====
    def _init_analysis(self, parent):
        lay=QVBoxLayout(parent)
        hint=QLabel("在波形图上右键拖动选取区域，此处显示分析结果")
        hint.setStyleSheet("color:#6c7086;font-size:12px;padding:8px"); lay.addWidget(hint)
        g=QGroupBox("选区分析"); gl=QVBoxLayout(g)
        self.rv=QLabel("平均电压: -- V"); self.rc=QLabel("平均电流: -- mA")
        self.rp=QLabel("平均功率: -- mW"); self.rmx=QLabel("最大电流: -- mA")
        self.rmn=QLabel("最小电流: -- mA"); self.rch=QLabel("电量(μAh): --")
        self.ren=QLabel("能量(μWh): --"); self.rtm=QLabel("时长: -- 秒")
        self.rn=QLabel("采样点数: --")
        for lb in [self.rv,self.rc,self.rp,self.rmx,self.rmn,self.rch,self.ren,self.rtm,self.rn]:
            lb.setStyleSheet("font-size:14px;padding:4px"); gl.addWidget(lb)
        lay.addWidget(g); lay.addStretch()

    # ===== Tab4: Script =====
    def _init_script(self, parent):
        lay=QVBoxLayout(parent)
        bl=QHBoxLayout()
        br=QPushButton("运行脚本"); br.clicked.connect(self._run); bl.addWidget(br)
        bc=QPushButton("清空日志"); bc.clicked.connect(lambda:self.le.clear()); bl.addWidget(bc)
        lay.addLayout(bl)
        sp=QSplitter(Qt.Vertical)
        self.se=QTextEdit(); self.se.setPlaceholderText("-- Lua风格脚本\n-- 示例:\ng_send('VOLT 4.2')\ng_send('OUTP ON')")
        sp.addWidget(self.se); self.le=QTextEdit(); self.le.setReadOnly(True); self.le.setPlaceholderText("日志...")
        sp.addWidget(self.le); lay.addWidget(sp)

    # ===== Actions =====
    def _connect(self):
        if not GPIB_OK: QMessageBox.warning(self,"提示","GPIB驱动未加载"); return
        a=self.spin_a.value()
        if gpib_ud>=0: g_close(); self.btn_co.setText("连接设备"); self.statusBar().showMessage("已断开")
        elif g_open(a): self.btn_co.setText("断开设备"); self.statusBar().showMessage(f"已连接 (地址{a})")
        else: QMessageBox.critical(self,"失败","连接失败")

    def _start(self):
        if not self.test_mode and (not GPIB_OK or gpib_ud<0):
            QMessageBox.warning(self,"提示","请先连接设备或启用测试模式"); return
        if not self.collecting:
            self.collecting=True; self.t0=time.time(); self.phi=0; self.pe=0
            threading.Thread(target=self._loop,daemon=True).start()
            self.statusBar().showMessage("采集中...")
            logger.info("采集已启动")

    def _stop(self):
        self.collecting=False; self.statusBar().showMessage("已停止")
        logger.info("采集已停止")

    def _toggle_test(self):
        if self.btn_te.text()=="测试模式":
            self.test_mode=True; self.btn_te.setText("退出测试"); self._clear(); self._start()
        else: self.test_mode=False; self.btn_te.setText("测试模式"); self._stop()

    def _loop(self):
        while self.collecting:
            try:
                if self.test_mode:
                    ph=self.phases[self.phi]; self.pe+=1
                    if self.pe>=ph["d"] and self.phi<len(self.phases)-1: self.phi+=1; self.pe=0
                    v=ph["v"]+random.uniform(-0.02,0.02); c=(ph["c"]+random.gauss(0,ph["s"]))*1000
                else:
                    vs=g_qry("MEAS:VOLT?"); cs=g_qry("MEAS:CURR?")
                    v=float(vs) if vs else 0; c=float(cs)*1000 if cs else 0
                t=time.time()-self.t0; p=v*c
                with lock:
                    self.ts.append(t); self.vs.append(v); self.cs.append(c); self.ps.append(p)
                    self.max_c=max(self.max_c,c); self.min_c=min(self.min_c,c)
                    if len(self.ts)>1: self.e_mwh+=p*(self.ts[-1]-self.ts[-2])/3600
                    self.save_count+=1
                    # Auto save
                    if self.act_save_auto.isChecked() and self.save_count>=self.spin_cache.value():
                        self._auto_save(); self.save_count=0
            except Exception as e: logger.error(f"异常: {e}")
            time.sleep(0.05)

    def _auto_save(self):
        try:
            path=os.path.join(log_dir, f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            with open(path,"w",newline="",encoding="utf-8") as f:
                w=csv.writer(f); w.writerow(["时间","电压(V)","电流(mA)","功率(mW)"])
                for t,v,c,p in zip(self.ts,self.vs,self.cs,self.ps): w.writerow([f"{t:.4f}",f"{v:.4f}",f"{c:.4f}",f"{p:.4f}"])
            logger.info(f"自动保存: {path}")
        except Exception as e: logger.error(f"自动保存失败: {e}")

    def _toggle_auto_save(self):
        s="开" if self.act_save_auto.isChecked() else "关"
        self.act_save_auto.setText(f"自动保存:{s}")

    # ===== UI Update =====
    def _ui(self):
        if not self.ts: return
        lc,lv,lp=self.cs[-1],self.vs[-1],self.ps[-1]
        is_merged=self.act_mode.text()=="切换到双波形模式"

        # Update plots based on mode
        lw=self.spin_lw.value()
        if is_merged:
            self.cm_c.setData(self.ts,self.cs)
            self.cm_c.setPen(pg.mkPen("#89b4fa",width=lw))
            self.cm_c.setBrush(pg.mkBrush(137,180,250,40))
            self.cm_v.setData(self.ts,self.vs)
            self.cm_v.setPen(pg.mkPen("#f38ba8",width=lw))
            # Auto scroll for merged (only if not user scrolling)
            if self.ts[-1]>60 and not self.user_scrolling:
                vb=self.pm.plotItem.vb; vr=vb.viewRange()[0]
                if self.ts[-1] >= vr[1]-5: vb.setXRange(self.ts[-1]-60,self.ts[-1],padding=0)
        else:
            self.cc.setData(self.ts,self.cs)
            self.cc.setPen(pg.mkPen("#89b4fa",width=lw))
            self.cv.setData(self.ts,self.vs)
            self.cv.setPen(pg.mkPen("#f38ba8",width=lw))
            # Auto scroll for dual (only if not user scrolling)
            if self.ts[-1]>60 and not self.user_scrolling:
                vb=self.pc.plotItem.vb; vr=vb.viewRange()[0]
                if self.ts[-1] >= vr[1]-5:
                    vb.setXRange(self.ts[-1]-60,self.ts[-1],padding=0)
                    self.pv.plotItem.vb.setXRange(self.ts[-1]-60,self.ts[-1],padding=0)
            # Y range for dual (only when not auto-adapt)
            if not self.chk_auto.isChecked():
                if self.cs:
                    ym=max(max(self.cs)*1.1,10)
                    if self.coord_mode==0: self.pc.plotItem.vb.setYRange(0,ym,padding=0)
                    elif self.coord_mode==1: self.pc.plotItem.vb.setYRange(0,200,padding=0)
                if self.vs:
                    ymn=min(self.vs)*0.9; ymx=max(self.vs)*1.1
                    if self.coord_mode==0: self.pv.plotItem.vb.setYRange(ymn,ymx,padding=0)
                    elif self.coord_mode==1: self.pv.plotItem.vb.setYRange(0,6,padding=0)
            else:
                # Auto-adapt Y range based on data
                if self.cs:
                    ym=max(max(self.cs)*1.1,10)
                    self.pc.plotItem.vb.setYRange(0,ym,padding=0)
                if self.vs:
                    ymn=min(self.vs)*0.9; ymx=max(self.vs)*1.1
                    self.pv.plotItem.vb.setYRange(ymn,ymx,padding=0)

        # Labels
        if is_merged:
            self.lmc.setText(f" {lc:.1f}mA "); self.lmc.setPos(self.ts[-1],lc); self.lmc.show()
            # Voltage label position: use left Y range for positioning
            y_range = self.pm.plotItem.vb.viewRange()[1]
            y_pos = y_range[1] * 0.95  # Position near top of left Y range
            self.lmv.setText(f" {lv:.3f}V "); self.lmv.setPos(self.ts[-1],y_pos); self.lmv.show()
        else:
            self.lc.setText(f" {lc:.1f}mA "); self.lc.setPos(self.ts[-1],lc); self.lc.show()
            self.lvl.setText(f" {lv:.3f}V "); self.lvl.setPos(self.ts[-1],lv); self.lvl.show()
            xl=max(0,self.ts[-1]-2)
            self.tc.setData([xl,self.ts[-1]],[lc,lc]); self.tvl.setData([xl,self.ts[-1]],[lv,lv])

        # Stats - instant or average
        if self.display_mode=="instant":
            self.lb_ic.setText(f"{lc:.3f} mA"); self.lb_iv.setText(f"{lv:.4f} V"); self.lb_ip.setText(f"{lp:.3f} mW")
        else:
            # Sliding average (last 100 points)
            n=min(100,len(self.cs))
            avg_c=sum(self.cs[-n:])/n; avg_v=sum(self.vs[-n:])/n; avg_p=sum(self.ps[-n:])/n
            self.lb_ic.setText(f"{avg_c:.3f} mA"); self.lb_iv.setText(f"{avg_v:.4f} V"); self.lb_ip.setText(f"{avg_p:.3f} mW")

        # Global stats
        ac=sum(self.cs)/len(self.cs); av=sum(self.vs)/len(self.vs); ap=sum(self.ps)/len(self.ps)
        self.lb_ac.setText(f"平均电流: {ac:.1f} mA"); self.lb_av.setText(f"平均电压: {av:.4f} V")
        self.lb_ap.setText(f"平均功率: {ap:.1f} mW")
        self.lb_mx.setText(f"最大电流: {self.max_c:.1f} mA"); self.lb_mn.setText(f"最小电流: {self.min_c:.1f} mA")
        self.lb_n.setText(f"采样点数: {len(self.ts)}")

        # Time
        h,m,s=int(self.ts[-1]//3600),int((self.ts[-1]%3600)//60),int(self.ts[-1]%60)
        self.lb_tm.setText(f"总时长: {h:02d}:{m:02d}:{s:02d}")

        # Energy
        if self.unit==0:
            self.lb_en.setText(f"总耗电: {self.e_mwh:.2f} mWh")
            self.lb_ah.setText(f"累计电量: {sum(self.cs)/len(self.cs)*self.ts[-1]/3600:.4f} mAh")
        else:
            self.lb_en.setText(f"总耗电: {self.e_mwh/1000:.4f} Wh")
            self.lb_ah.setText(f"累计电量: {sum(self.cs)/len(self.cs)*self.ts[-1]/3600000:.6f} Ah")

        # Slider
        if len(self.ts)>1:
            self.slider.blockSignals(True)
            self.slider.setMaximum(len(self.ts)-1)
            self.slider.setValue(len(self.ts)-1)
            self.slider.blockSignals(False)

    def _on_slider(self, val):
        if not self.ts or val>=len(self.ts): return
        self.user_scrolling=True; self.scroll_timer.start(3000)
        x=self.ts[val]; x_min=max(0,x-60)
        is_merged=self.act_mode.text()=="切换到双波形模式"
        if is_merged:
            self.pm.plotItem.vb.setXRange(x_min,x,padding=0)
        else:
            self.pc.plotItem.vb.setXRange(x_min,x,padding=0)
            self.pv.plotItem.vb.setXRange(x_min,x,padding=0)

    def _switch_unit(self):
        self.unit=1-self.unit; self._ui()

    def _calc_m(self):
        if not self.ts: return
        t0,t1=self.region_m.getRegion(); idx=[i for i,t in enumerate(self.ts) if t0<=t<=t1]
        if len(idx)<2: return
        vr=[self.vs[i] for i in idx]; cr=[self.cs[i] for i in idx]; pr=[self.ps[i] for i in idx]
        dt=self.ts[idx[-1]]-self.ts[idx[0]]
        self.rv.setText(f"平均电压: {sum(vr)/len(vr):.4f} V")
        self.rc.setText(f"平均电流: {sum(cr)/len(cr):.4f} mA")
        self.rp.setText(f"平均功率: {sum(pr)/len(pr):.4f} mW")
        self.rmx.setText(f"最大电流: {max(cr):.4f} mA")
        self.rmn.setText(f"最小电流: {min(cr):.4f} mA")
        self.rch.setText(f"电量(μAh): {sum(cr)/len(cr)*dt/3600*1000:.4f}")
        self.ren.setText(f"能量(μWh): {sum(pr)/len(pr)*dt/3600:.4f}")
        self.rtm.setText(f"时长: {dt:.2f} 秒")
        self.rn.setText(f"采样点数: {len(idx)}")

    def _apply(self):
        if not GPIB_OK or gpib_ud<0: QMessageBox.warning(self,"提示","请先连接GPIB设备"); return
        g_send(f"VOLT {self.sv.value():.3f}"); g_send(f"CURR {self.sc.value()/1000:.3f}")
        QMessageBox.information(self,"成功","设置已生效")

    def _run(self):
        c=self.se.toPlainText()
        if not c.strip(): return
        try: exec(c,{"g_send":g_send,"g_qry":g_qry}); self.le.append(f"[OK] {time.strftime('%H:%M:%S')}")
        except Exception as e: self.le.append(f"[ERR] {time.strftime('%H:%M:%S')} {e}")

    def _save(self):
        if not self.ts: QMessageBox.information(self,"提示","无数据"); return
        p,_=QFileDialog.getSaveFileName(self,"保存","","CSV (*.csv)")
        if p:
            with open(p,"w",newline="",encoding="utf-8") as f:
                w=csv.writer(f); w.writerow(["时间","电压(V)","电流(mA)","功率(mW)"])
                for t,v,c,pp in zip(self.ts,self.vs,self.cs,self.ps): w.writerow([f"{t:.4f}",f"{v:.4f}",f"{c:.4f}",f"{pp:.4f}"])
            QMessageBox.information(self,"成功","已保存")

    def _load(self):
        p,_=QFileDialog.getOpenFileName(self,"加载","","CSV (*.csv)")
        if not p: return
        self._clear()
        try:
            with open(p,"r",encoding="utf-8") as f:
                r=csv.reader(f); next(r)
                for row in r: self.ts.append(float(row[0])); self.vs.append(float(row[1])); self.cs.append(float(row[2])); self.ps.append(float(row[3]))
            QMessageBox.information(self,"成功","已加载")
        except Exception as e: QMessageBox.critical(self,"错误",str(e))

    def _clear(self):
        self.ts.clear(); self.vs.clear(); self.cs.clear(); self.ps.clear()
        self.e_mwh=0; self.max_c=0; self.min_c=float("inf"); self.save_count=0
        self.cc.clear(); self.cv.clear()

    def _float(self):
        if self.windowFlags()&Qt.WindowStaysOnTopHint: self.setWindowFlags(Qt.Window); self.act_float.setText("悬浮窗")
        else: self.setWindowFlags(Qt.Window|Qt.WindowStaysOnTopHint); self.act_float.setText("取消悬浮")
        self.show()

    def _toggle_theme(self):
        themes=[DARK, LIGHT, DARK]
        names=["深色主题","浅色主题","跟随系统"]
        self.theme_idx=(self.theme_idx+1)%3
        self.act_theme.setText(names[self.theme_idx])
        QApplication.instance().setStyleSheet(themes[self.theme_idx])
        # Update plot backgrounds for light mode
        bg="#eff1f5" if self.theme_idx==1 else "#11111b"
        grid_c="#ccd0da" if self.theme_idx==1 else "#45475a"
        self.pm.setBackground(bg); self.pc.setBackground(bg); self.pv.setBackground(bg)

    def _load_settings(self):
        s=QSettings("PG-Power","settings")
        self.spin_a.setValue(s.value("gpib_addr",5,type=int))
        self.sv.setValue(s.value("max_volt",4.2,type=float))
        self.sc.setValue(s.value("max_curr",1000,type=float))
        self.spin_cmax.setValue(s.value("c_max",350,type=float))
        self.spin_cmin.setValue(s.value("c_min",0,type=float))
        self.spin_vmax.setValue(s.value("v_max",20,type=float))
        self.spin_vmin.setValue(s.value("v_min",0,type=float))
        self.spin_cache.setValue(s.value("cache",50000,type=int))
        self.spin_lw.setValue(s.value("line_width",2,type=float))
        self.cb_coord.setCurrentIndex(s.value("coord",0,type=int))
        self.track_side=s.value("track_side","right")
        if self.track_side=="left": self.btn_tl.setStyleSheet("background:#a6e3a1;")
        else: self.btn_tr.setStyleSheet("background:#a6e3a1;")

    def _save_settings(self):
        s=QSettings("PG-Power","settings")
        s.setValue("gpib_addr",self.spin_a.value())
        s.setValue("max_volt",self.sv.value())
        s.setValue("max_curr",self.sc.value())
        s.setValue("c_max",self.spin_cmax.value())
        s.setValue("c_min",self.spin_cmin.value())
        s.setValue("v_max",self.spin_vmax.value())
        s.setValue("v_min",self.spin_vmin.value())
        s.setValue("cache",self.spin_cache.value())
        s.setValue("line_width",self.spin_lw.value())
        s.setValue("coord",self.cb_coord.currentIndex())
        s.setValue("track_side",self.track_side)

    def closeEvent(self, e):
        self.collecting=False; g_close(); self._save_settings(); e.accept()

if __name__=="__main__":
    app=QApplication(sys.argv); app.setStyleSheet(DARK)
    ico=os.path.join(os.path.dirname(os.path.abspath(__file__)),"icon.ico")
    if os.path.exists(ico): app.setWindowIcon(QIcon(ico))
    w=Main(); w.show(); sys.exit(app.exec_())
