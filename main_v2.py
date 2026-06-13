import sys, os, ctypes, threading, platform, time, csv, logging, random
from datetime import datetime
from ctypes import c_int, c_char_p, create_string_buffer

log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"pg_power_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(log_file, encoding='utf-8'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("PG-Power")
logger.info(f"日志: {log_file}")

if getattr(sys, 'frozen', False):
    _base = sys._MEIPASS
else:
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
    QTabWidget, QTextEdit, QSplitter, QFrame, QToolBar, QAction, QComboBox)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QIcon, QPen, QColor
import pyqtgraph as pg

# ===== GPIB =====
def get_ni4882_dll_path():
    bits = platform.architecture()[0]; root = os.environ["SystemRoot"]
    paths = [os.path.join(root, "System32" if bits=="64bit" else "SysWOW64", "ni4882.dll"),
             os.path.join(root, "SysWOW64" if bits=="64bit" else "System32", "ni4882.dll"),
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "ni4882.dll")]
    for p in paths:
        if os.path.exists(p): logger.info(f"DLL: {p}"); return p
    return None

GPIB_AVAILABLE = False; ni4882 = None; gpib_ud = -1; data_lock = threading.Lock()
dll_path = get_ni4882_dll_path()
if dll_path:
    try:
        ni4882 = ctypes.WinDLL(dll_path)
        ni4882.ibdev.argtypes = [c_int]*6; ni4882.ibdev.restype = c_int
        ni4882.ibwrt.argtypes = [c_int, c_char_p, c_int]; ni4882.ibwrt.restype = c_int
        ni4882.ibrd.argtypes = [c_int, c_char_p, c_int]; ni4882.ibrd.restype = c_int
        ni4882.ibonl.argtypes = [c_int, c_int]; ni4882.ibonl.restype = c_int
        GPIB_AVAILABLE = True; logger.info("GPIB OK")
    except Exception as e: logger.warning(f"GPIB fail: {e}")

def gpib_open(addr):
    global gpib_ud
    if not GPIB_AVAILABLE: return False
    gpib_ud = ni4882.ibdev(0, addr, 0, 13, 1, 0); return gpib_ud >= 0
def gpib_close():
    global gpib_ud
    if GPIB_AVAILABLE and gpib_ud >= 0: ni4882.ibonl(gpib_ud, 0); gpib_ud = -1
def gpib_send(cmd):
    if GPIB_AVAILABLE and gpib_ud >= 0: ni4882.ibwrt(gpib_ud, (cmd+"\r\n").encode(), len(cmd)+2)
def gpib_query(cmd):
    if not GPIB_AVAILABLE or gpib_ud < 0: return ""
    buf = create_string_buffer(256); ni4882.ibwrt(gpib_ud, (cmd+"\r\n").encode(), len(cmd)+2)
    ni4882.ibrd(gpib_ud, buf, 256); return buf.value.decode().strip()

# ===== Theme =====
DARK = """
QMainWindow,QWidget{background:#1e1e2e;color:#cdd6f4;font-family:"Microsoft YaHei","Segoe UI",sans-serif;font-size:13px}
QGroupBox{background:#181825;border:1px solid #313244;border-radius:8px;margin-top:14px;padding:12px;font-weight:bold;color:#cdd6f4}
QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;color:#6c7086;font-size:11px}
QLabel{color:#bac2de;background:transparent}
QPushButton{border:none;border-radius:6px;padding:6px 12px;min-height:28px;font-weight:bold;color:#fff}
QPushButton:hover{opacity:0.9}QPushButton:pressed{padding-top:7px;padding-bottom:5px}
QPushButton:disabled{background:#313244!important;color:#585b70!important}
QPushButton#conn{background:#89b4fa}QPushButton#start{background:#a6e3a1}QPushButton#stop{background:#f38ba8}
QPushButton#test{background:#313244;color:#bac2de}QPushButton#test:checked{background:#fab387}
QPushButton#save{background:#89b4fa}QPushButton#load{background:#cba6f7}QPushButton#clear{background:#6c7086}
QTabWidget::pane{border:1px solid #313244}
QTabBar::tab{background:#181825;color:#6c7086;padding:8px 16px;border:none;border-bottom:2px solid transparent}
QTabBar::tab:selected{color:#cdd6f4;border-bottom:2px solid #89b4fa}
QTextEdit{background:#11111b;border:1px solid #313244;border-radius:4px;color:#bac2de;font-family:"Consolas",monospace;font-size:12px}
QSpinBox,QDoubleSpinBox,QComboBox{background:#11111b;border:1px solid #313244;border-radius:4px;padding:4px 8px;color:#cdd6f4;min-height:22px}
QToolBar{background:#11111b;border-bottom:1px solid #313244;spacing:4px}
QToolBar QToolButton{background:transparent;color:#bac2de;border:none;padding:4px 8px}
QToolBar QToolButton:hover{background:#1e1e2e;color:#cdd6f4}
"""

class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PG-Power | GPIB电源测试工具"); self.resize(1500, 880)
        ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(ico): self.setWindowIcon(QIcon(ico))
        self.ts=[]; self.vs=[]; self.cs=[]; self.ps=[]
        self.t0=time.time(); self.e_wh=0.0; self.max_c=0.0; self.min_c=float("inf")
        self.unit=0; self.collecting=False; self.test_mode=False; self.track_side="right"
        self.phases=[{"n":"开机","d":310,"v":5.0,"c":0.300,"s":0.020},{"n":"待机","d":445,"v":5.0,"c":0.075,"s":0.005},
            {"n":"通话","d":150,"v":5.0,"c":0.280,"s":0.015},{"n":"待机","d":443,"v":5.0,"c":0.075,"s":0.005},
            {"n":"通话","d":150,"v":5.0,"c":0.280,"s":0.015},{"n":"待机","d":445,"v":5.0,"c":0.075,"s":0.005},
            {"n":"重启","d":310,"v":5.0,"c":0.300,"s":0.020}]
        self.phi=0; self.pe=0
        self._init_ui()
        self.timer=QTimer(); self.timer.setInterval(50); self.timer.timeout.connect(self._ui); self.timer.start()
        if not GPIB_AVAILABLE: QMessageBox.warning(self,"提示","GPIB驱动未加载，可使用测试模式预览")

    def _init_ui(self):
        m=QVBoxLayout(self); m.setContentsMargins(0,0,0,0); m.setSpacing(0)
        tb=QToolBar(); self.addToolBar(tb)
        self.act_float=QAction("悬浮窗",self); self.act_float.triggered.connect(self._float); tb.addAction(self.act_float)
        tabs=QTabWidget(); self.setCentralWidget(tabs)

        # Tab1: Wave
        w1=QWidget(); tabs.addTab(w1,"数据与波形")
        self._init_wave(w1)
        # Tab2: Settings
        w2=QWidget(); tabs.addTab(w2,"设备与设置")
        self._init_settings(w2)
        # Tab3: Analysis
        w3=QWidget(); tabs.addTab(w3,"选区分析")
        self._init_analysis(w3)
        # Tab4: Script
        w4=QWidget(); tabs.addTab(w4,"脚本控制")
        self._init_script(w4)
        # Tab5: About
        w5=QWidget(); tabs.addTab(w5,"关于")
        QVBoxLayout(w5).addWidget(QLabel("<h2>PG-Power | GPIB电源测试工具</h2><p>Python + PyQt5 + PyQtGraph</p>"))

    def _init_wave(self, parent):
        lay=QHBoxLayout(parent); sp=QSplitter(Qt.Horizontal)
        # Left panel
        left=QWidget(); left.setFixedWidth(220); ll=QVBoxLayout(left); ll.setSpacing(6)
        g1=QGroupBox("瞬时值"); gl1=QVBoxLayout(g1); gl1.setSpacing(2)
        self.lb_ic=QLabel("0.000 mA"); self.lb_ic.setStyleSheet("color:#89b4fa;font-size:18px;font-weight:bold")
        self.lb_iv=QLabel("0.000 V"); self.lb_iv.setStyleSheet("color:#f38ba8;font-size:18px;font-weight:bold")
        self.lb_ip=QLabel("0.000 mW"); self.lb_ip.setStyleSheet("color:#f9e2af;font-size:18px;font-weight:bold")
        gl1.addWidget(self.lb_ic); gl1.addWidget(self.lb_iv); gl1.addWidget(self.lb_ip); ll.addWidget(g1)

        g2=QGroupBox("全局统计"); gl2=QVBoxLayout(g2); gl2.setSpacing(2)
        self.lb_ac=QLabel("平均电流: -- mA")
        self.lb_mx=QLabel("最大电流: -- mA"); self.lb_mx.setStyleSheet("color:#f38ba8")
        self.lb_mn=QLabel("最小电流: -- mA"); self.lb_mn.setStyleSheet("color:#a6e3a1")
        self.lb_en=QLabel("总耗电: -- mWh"); self.lb_en.setStyleSheet("color:#f9e2af")
        self.lb_tm=QLabel("总时长: 00:00:00")
        self.btn_unit=QPushButton("切换电量单位"); self.btn_unit.setObjectName("save")
        self.btn_unit.clicked.connect(lambda: (setattr(self,'unit',1-self.unit), self._ui()))
        for w in [self.lb_ac,self.lb_mx,self.lb_mn,self.lb_en,self.lb_tm,self.btn_unit]: gl2.addWidget(w)
        ll.addWidget(g2)

        g3=QGroupBox("GPIB控制"); gl3=QVBoxLayout(g3); gl3.setSpacing(2)
        self.spin_addr=QSpinBox(); self.spin_addr.setRange(0,30); self.spin_addr.setValue(5)
        gl3.addWidget(QLabel("设备地址:")); gl3.addWidget(self.spin_addr)
        self.btn_conn=QPushButton("连接设备"); self.btn_conn.setObjectName("conn")
        self.btn_conn.clicked.connect(self._connect); gl3.addWidget(self.btn_conn)
        self.btn_test=QPushButton("测试模式"); self.btn_test.setObjectName("test")
        self.btn_test.setCheckable(True); self.btn_test.clicked.connect(self._toggle_test); gl3.addWidget(self.btn_test)
        self.btn_start=QPushButton("开始采集"); self.btn_start.setObjectName("start")
        self.btn_start.clicked.connect(self._start); gl3.addWidget(self.btn_start)
        self.btn_stop=QPushButton("停止采集"); self.btn_stop.setObjectName("stop")
        self.btn_stop.clicked.connect(self._stop); gl3.addWidget(self.btn_stop)
        ll.addWidget(g3)

        g4=QGroupBox("数据操作"); gl4=QVBoxLayout(g4); gl4.setSpacing(2)
        self.btn_sv=QPushButton("保存CSV"); self.btn_sv.setObjectName("save"); self.btn_sv.clicked.connect(self._save)
        self.btn_ld=QPushButton("加载数据"); self.btn_ld.setObjectName("load"); self.btn_ld.clicked.connect(self._load)
        self.btn_cl=QPushButton("清空数据"); self.btn_cl.setObjectName("clear"); self.btn_cl.clicked.connect(self._clear)
        gl4.addWidget(self.btn_sv); gl4.addWidget(self.btn_ld); gl4.addWidget(self.btn_cl)
        ll.addWidget(g4); ll.addStretch()

        # Mid: dual plots
        mid=QWidget(); ml=QVBoxLayout(mid); ml.setContentsMargins(0,0,0,0); ml.setSpacing(2)
        # Current plot
        self.pc=pg.PlotWidget(); self.pc.setBackground("#11111b"); self.pc.showGrid(x=True,y=True,alpha=0.1)
        self.pc.setLabel("left","电流 (mA)",color="#6c7086"); self.pc.setLabel("bottom","时间 (s)",color="#6c7086")
        self.pc.setTitle("电流波形",color="#cdd6f4",size="12pt")
        self.cc=self.pc.plot(pen=pg.mkPen("#89b4fa",width=2),fillLevel=0,brush=pg.mkBrush(137,180,250,40),name="电流(mA)")
        # Crosshair for current
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
        # Voltage plot
        self.pv=pg.PlotWidget(); self.pv.setBackground("#11111b"); self.pv.showGrid(x=True,y=True,alpha=0.1)
        self.pv.setLabel("left","电压 (V)",color="#6c7086"); self.pv.setLabel("bottom","时间 (s)",color="#6c7086")
        self.pv.setTitle("电压波形",color="#cdd6f4",size="12pt")
        self.cv=self.pv.plot(pen=pg.mkPen("#f38ba8",width=2),name="电压(V)")
        self.vv=pg.InfiniteLine(90,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.hv=pg.InfiniteLine(0,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.pv.addItem(self.vv,ignoreBounds=True); self.pv.addItem(self.hv,ignoreBounds=True)
        self.xv=pg.TextItem(color="#cdd6f4",anchor=(0,1),border=pg.mkPen("#585b70",width=1),fill=pg.mkBrush("#1e1e2eee"))
        self.xv.hide(); self.pv.addItem(self.xv)
        self.lv=pg.TextItem(color="#f38ba8",anchor=(0,0.5),fill=pg.mkBrush("#11111bcc"))
        self.pv.addItem(self.lv)
        self.tv=self.pv.plot(pen=pg.mkPen("#f38ba8",width=1,style=Qt.DotLine))
        self.pv.scene().sigMouseMoved.connect(self._mv)
        ml.addWidget(self.pv)

        # Region
        self.region=pg.LinearRegionItem([0,10],movable=True,brush=pg.mkBrush(137,180,250,30))
        self.region.sigRegionChanged.connect(self._calc)
        self.pc.addItem(self.region); self.region.setVisible(False)

        sp.addWidget(left); sp.addWidget(mid); lay.addWidget(sp)

    def _mc(self, pos):
        if self.pc.sceneBoundingRect().contains(pos):
            mp=self.pc.plotItem.vb.mapSceneToView(pos)
            self.vc.setPos(mp.x()); self.hc.setPos(mp.y())
            with data_lock:
                if self.ts:
                    i=max(0,min(int(mp.x()),len(self.ts)-1))
                    v,c,p=self.vs[i],self.cs[i],self.ps[i]
                    self.xc.setText(f" t={mp.x():.1f}s  {v:.3f}V  {c:.1f}mA  {p:.1f}mW ")
                    self.xc.setPos(mp); self.xc.show()
        else: self.xc.hide()

    def _mv(self, pos):
        if self.pv.sceneBoundingRect().contains(pos):
            mp=self.pv.plotItem.vb.mapSceneToView(pos)
            self.vv.setPos(mp.x()); self.hv.setPos(mp.y())
            with data_lock:
                if self.ts:
                    i=max(0,min(int(mp.x()),len(self.ts)-1))
                    v=self.vs[i]
                    self.xv.setText(f" t={mp.x():.1f}s  {v:.3f}V ")
                    self.xv.setPos(mp); self.xv.show()
        else: self.xv.hide()

    def _init_settings(self, parent):
        lay=QVBoxLayout(parent)
        g=QGroupBox("波形显示"); gl=QVBoxLayout(g)
        self.btn_mode=QPushButton("切换到合并模式"); self.btn_mode.setObjectName("test")
        self.btn_mode.setCheckable(True); self.btn_mode.clicked.connect(self._mode)
        gl.addWidget(self.btn_mode); lay.addWidget(g)
        gt=QGroupBox("跟踪线"); tl=QVBoxLayout(gt)
        tl.addWidget(QLabel("显示位置:"))
        self.btn_tl=QPushButton("左侧"); self.btn_tl.clicked.connect(lambda:self._tside("left"))
        self.btn_tr=QPushButton("右侧"); self.btn_tr.setObjectName("conn"); self.btn_tr.clicked.connect(lambda:self._tside("right"))
        tl.addWidget(self.btn_tl); tl.addWidget(self.btn_tr); lay.addWidget(gt)
        go=QGroupBox("输出设置"); ol=QVBoxLayout(go)
        self.sv=QDoubleSpinBox(); self.sv.setRange(0,5); self.sv.setSingleStep(0.001); self.sv.setValue(4.2)
        self.sc=QDoubleSpinBox(); self.sc.setRange(0,2000); self.sc.setValue(1000)
        ba=QPushButton("应用设置"); ba.clicked.connect(self._apply)
        ol.addWidget(QLabel("最大电压(V):")); ol.addWidget(self.sv)
        ol.addWidget(QLabel("最大电流(mA):")); ol.addWidget(self.sc); ol.addWidget(ba)
        lay.addWidget(go); lay.addStretch()

    def _tside(self, s):
        self.track_side=s
        self.btn_tl.setStyleSheet("background:#a6e3a1;" if s=="left" else "")
        self.btn_tr.setStyleSheet("background:#a6e3a1;" if s=="right" else "")

    def _init_analysis(self, parent):
        lay=QVBoxLayout(parent); g=QGroupBox("选区分析"); gl=QVBoxLayout(g)
        self.rv=QLabel("平均电压: -- V"); self.rc=QLabel("平均电流: -- mA")
        self.rp=QLabel("平均功率: -- mW"); self.rmx=QLabel("最大电流: -- mA")
        self.rmn=QLabel("最小电流: -- mA"); self.rch=QLabel("电量: -- μAh")
        self.ren=QLabel("能量: -- μWh"); self.rtm=QLabel("时长: -- 秒")
        for lb in [self.rv,self.rc,self.rp,self.rmx,self.rmn,self.rch,self.ren,self.rtm]:
            lb.setStyleSheet("font-size:14px;padding:4px"); gl.addWidget(lb)
        lay.addWidget(g); lay.addStretch()

    def _init_script(self, parent):
        lay=QVBoxLayout(parent)
        bl=QHBoxLayout()
        br=QPushButton("运行脚本"); br.clicked.connect(self._run); bl.addWidget(br)
        bc=QPushButton("清空日志"); bc.clicked.connect(lambda:self.le.clear()); bl.addWidget(bc)
        lay.addLayout(bl)
        sp=QSplitter(Qt.Vertical)
        self.se=QTextEdit(); self.se.setPlaceholderText("-- 在此编写脚本\n-- 示例:\ngpib_send('VOLT 4.2')")
        sp.addWidget(self.se); self.le=QTextEdit(); self.le.setReadOnly(True); self.le.setPlaceholderText("日志...")
        sp.addWidget(self.le); lay.addWidget(sp)

    def _mode(self):
        if self.btn_mode.isChecked():
            self.btn_mode.setText("切换到合并模式"); self.pc.hide(); self.pv.show()
        else:
            self.btn_mode.setText("切换到双波形模式"); self.pv.hide(); self.pc.show()

    def _connect(self):
        if not GPIB_AVAILABLE: QMessageBox.warning(self,"提示","GPIB驱动未加载"); return
        a=self.spin_addr.value()
        if gpib_ud>=0: gpib_close(); self.btn_conn.setText("连接设备")
        elif gpib_open(a): self.btn_conn.setText("断开设备")
        else: QMessageBox.critical(self,"失败","连接失败")

    def _start(self):
        if not self.test_mode and (not GPIB_AVAILABLE or gpib_ud<0):
            QMessageBox.warning(self,"提示","请先连接设备或启用测试模式"); return
        if not self.collecting:
            self.collecting=True; self.t0=time.time(); self.phi=0; self.pe=0
            threading.Thread(target=self._loop,daemon=True).start(); logger.info("采集已启动")

    def _stop(self): self.collecting=False; logger.info("采集已停止")

    def _toggle_test(self):
        if self.btn_test.text()=="测试模式":
            self.test_mode=True; self.btn_test.setText("退出测试"); self._clear()
            if not self.collecting: self._start()
        else: self.test_mode=False; self.btn_test.setText("测试模式"); self._stop()

    def _loop(self):
        while self.collecting:
            try:
                if self.test_mode:
                    ph=self.phases[self.phi]; self.pe+=1
                    if self.pe>=ph["d"] and self.phi<len(self.phases)-1: self.phi+=1; self.pe=0
                    v=ph["v"]+random.uniform(-0.02,0.02); c=(ph["c"]+random.gauss(0,ph["s"]))*1000
                else:
                    vs=gpib_query("MEAS:VOLT?"); cs=gpib_query("MEAS:CURR?")
                    v=float(vs) if vs else 0; c=float(cs)*1000 if cs else 0
                t=time.time()-self.t0; p=v*c
                self.ts.append(t); self.vs.append(v); self.cs.append(c); self.ps.append(p)
                self.max_c=max(self.max_c,c); self.min_c=min(self.min_c,c)
                if len(self.ts)>1: self.e_wh+=p*(self.ts[-1]-self.ts[-2])/3600
            except Exception as e: logger.error(f"异常: {e}")
            time.sleep(0.05)

    def _ui(self):
        if not self.ts: return
        lc,lv,lp=self.cs[-1],self.vs[-1],self.ps[-1]
        # Current plot
        self.cc.setData(self.ts,self.cs)
        xd=max(0,self.ts[-1]-60) if self.track_side=="left" else 0
        self.pc.plotItem.vb.enableAutoRange(axis=self.pc.plotItem.vb.XAxis,enable=False)
        self.pc.plotItem.vb.setXRange(self.ts[-1]-60 if self.ts[-1]>60 else 0,self.ts[-1],padding=0)
        ym=max(max(self.cs)*1.1,10); self.pc.plotItem.vb.setYRange(0,ym,padding=0)
        # Voltage plot
        self.cv.setData(self.ts,self.vs)
        self.pv.plotItem.vb.enableAutoRange(axis=self.pv.plotItem.vb.XAxis,enable=False)
        self.pv.plotItem.vb.setXRange(self.ts[-1]-60 if self.ts[-1]>60 else 0,self.ts[-1],padding=0)
        if self.vs: ymn=min(self.vs)*0.9; ymx=max(self.vs)*1.1; self.pv.plotItem.vb.setYRange(ymn,ymx,padding=0)
        # Track dots
        xt=self.ts[-1]
        self.lc.setText(f" {lc:.1f}mA "); self.lc.setPos(xt,lc); self.lc.show()
        self.lv.setText(f" {lv:.3f}V "); self.lv.setPos(xt,lv); self.lv.show()
        xl=max(0,xt-2)
        self.tc.setData([xl,xt],[lc,lc]); self.tv.setData([xl,xt],[lv,lv])
        # Stats
        self.lb_ic.setText(f"{lc:.3f} mA"); self.lb_iv.setText(f"{lv:.4f} V"); self.lb_ip.setText(f"{lp:.3f} mW")
        ac=sum(self.cs)/len(self.cs); self.lb_ac.setText(f"平均电流: {ac:.1f} mA")
        self.lb_mx.setText(f"最大电流: {self.max_c:.1f} mA"); self.lb_mn.setText(f"最小电流: {self.min_c:.1f} mA")
        h,m,s=int(self.ts[-1]//3600),int((self.ts[-1]%3600)//60),int(self.ts[-1]%60)
        self.lb_tm.setText(f"总时长: {h:02d}:{m:02d}:{s:02d}")
        self.lb_en.setText(f"总耗电: {self.e_wh:.2f} mWh" if self.unit==0 else f"总耗电: {self.e_wh/1000:.4f} Wh")

    def _calc(self):
        if not self.ts: return
        t0,t1=self.region.getRegion(); idx=[i for i,t in enumerate(self.ts) if t0<=t<=t1]
        if len(idx)<2: return
        vr=[self.vs[i] for i in idx]; cr=[self.cs[i] for i in idx]; pr=[self.ps[i] for i in idx]
        dt=self.ts[idx[-1]]-self.ts[idx[0]]
        self.rv.setText(f"平均电压: {sum(vr)/len(vr):.4f} V"); self.rc.setText(f"平均电流: {sum(cr)/len(cr):.4f} mA")
        self.rp.setText(f"平均功率: {sum(pr)/len(pr):.4f} mW")
        self.rmx.setText(f"最大电流: {max(cr):.4f} mA"); self.rmn.setText(f"最小电流: {min(cr):.4f} mA")
        self.rch.setText(f"电量: {sum(cr)/len(cr)*dt/3600*1000:.4f} μAh")
        self.ren.setText(f"能量: {sum(pr)/len(pr)*dt/3600:.4f} μWh"); self.rtm.setText(f"时长: {dt:.2f} 秒")

    def _apply(self):
        if not GPIB_AVAILABLE or gpib_ud<0: QMessageBox.warning(self,"提示","请先连接GPIB设备"); return
        gpib_send(f"VOLT {self.sv.value():.3f}"); gpib_send(f"CURR {self.sc.value()/1000:.3f}")
        QMessageBox.information(self,"成功","设置已生效")

    def _run(self):
        c=self.se.toPlainText()
        if not c.strip(): return
        try: exec(c,{"gpib_send":gpib_send,"gpib_query":gpib_query}); self.le.append(f"[OK] {time.strftime('%H:%M:%S')}")
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
        self.e_wh=0; self.max_c=0; self.min_c=float("inf")
        self.cc.clear(); self.cv.clear()

    def _float(self):
        if self.windowFlags()&Qt.WindowStaysOnTopHint: self.setWindowFlags(Qt.Window); self.act_float.setText("悬浮窗")
        else: self.setWindowFlags(Qt.Window|Qt.WindowStaysOnTopHint); self.act_float.setText("取消悬浮")
        self.show()

    def closeEvent(self, e): self.collecting=False; gpib_close(); e.accept()

if __name__=="__main__":
    app=QApplication(sys.argv); app.setStyleSheet(DARK)
    ico=os.path.join(os.path.dirname(os.path.abspath(__file__)),"icon.ico")
    if os.path.exists(ico): app.setWindowIcon(QIcon(ico))
    w=Main(); w.show(); sys.exit(app.exec_())
