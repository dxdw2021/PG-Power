import sys, os, ctypes, threading, platform, time, csv, logging, json, random
from datetime import datetime, timedelta
from ctypes import c_int, c_char_p, create_string_buffer, Structure, byref, sizeof

APP_VERSION = "2.0.1"
REPORT_VERSION = "2.0.1"

def set_dark_titlebar(window, enable=True):
    """Windows 10/11 深色标题栏"""
    if sys.platform != "win32": return
    try:
        hwnd = int(window.winId())
        value = c_int(1 if enable else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, byref(value), sizeof(value))
    except Exception:
        pass

# ===== Log =====
# Use EXE directory for logs in frozen mode, script directory otherwise
if getattr(sys, 'frozen', False):
    log_dir = os.path.join(os.path.dirname(sys.executable), "logs")
    screenshot_dir = os.path.join(os.path.dirname(sys.executable), "screenshots")
else:
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    screenshot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(log_dir, exist_ok=True)
os.makedirs(screenshot_dir, exist_ok=True)
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
    QSlider, QStatusBar, QProgressBar, QLineEdit, QScrollArea, QCheckBox, QRadioButton)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot, QSettings, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QRadialGradient
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
_gpib_current_offset = 0.0  # mA, GPIB电流零位校准偏移量
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

def g_open(board, addr):
    global gpib_ud
    if not GPIB_OK: return False
    gpib_ud = ni4882.ibdev(board, addr, 0, 13, 1, 0); return gpib_ud >= 0
def g_close():
    global gpib_ud
    if GPIB_OK and gpib_ud >= 0: ni4882.ibonl(gpib_ud, 0); gpib_ud = -1
def g_send(c):
    if GPIB_OK and gpib_ud >= 0: ni4882.ibwrt(gpib_ud, (c+"\r\n").encode(), len(c)+2)
def g_qry(c):
    if not GPIB_OK or gpib_ud < 0: return ""
    buf = create_string_buffer(256); ni4882.ibwrt(gpib_ud, (c+"\r\n").encode(), len(c)+2)
    ni4882.ibrd(gpib_ud, buf, 256); return buf.value.decode().strip()

# ===== IotPower-cc USB (pyusb + libusb, WinUSB) =====
LUATOS_VID = 0x1209
LUATOS_PID = 0x7301

_libusb_dev = None
_libusb_be = None
_libusb_ep_out = None
_libusb_ep_in = None
_serial_lock = threading.Lock()

_libusb_dll = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libusb-1.0.dll")
USB_OK = os.path.exists(_libusb_dll)

if USB_OK:
    try:
        import usb.core
        import usb.backend.libusb1
        _libusb_be = usb.backend.libusb1.get_backend(
            find_library=lambda x: _libusb_dll)
        if not _libusb_be:
            USB_OK = False
    except Exception as e:
        logger.warning(f"USB库加载失败: {e}")
        USB_OK = False

def s_scan():
    """Scan for IotPower-cc WinUSB device"""
    if not USB_OK:
        return []
    try:
        dev = usb.core.find(backend=_libusb_be, find_all=True,
                            idVendor=LUATOS_VID, idProduct=LUATOS_PID)
        if dev:
            return [f"IotPower-cc (VID_{LUATOS_VID:04X}/PID_{LUATOS_PID:04X})"]
        return []
    except Exception:
        return []

def s_open(dev_id=None, baud=None):
    """Open IotPower-cc WinUSB device"""
    global _libusb_dev, _libusb_ep_out, _libusb_ep_in
    if not USB_OK:
        logger.warning("libusb-1.0.dll未找到"); return False
    try:
        dev = usb.core.find(backend=_libusb_be,
                            idVendor=LUATOS_VID, idProduct=LUATOS_PID)
        if dev is None:
            logger.warning(f"未找到设备 VID_{LUATOS_VID:04X}/PID_{LUATOS_PID:04X}")
            return False
        try:
            dev.set_configuration()
        except Exception as e:
            logger.debug(f"设置配置(可忽略): {e}")
        cfg = dev.get_active_configuration()
        _libusb_ep_out = None
        _libusb_ep_in = None
        for intf in cfg:
            for ep in intf:
                if ep.bEndpointAddress & 0x80:
                    if _libusb_ep_in is None:
                        _libusb_ep_in = ep.bEndpointAddress
                else:
                    if _libusb_ep_out is None:
                        _libusb_ep_out = ep.bEndpointAddress
        if _libusb_ep_out is None or _libusb_ep_in is None:
            logger.warning("未找到USB端点")
            return False
        _libusb_dev = dev
        logger.info(f"USB设备已连接: VID={LUATOS_VID:04X} PID={LUATOS_PID:04X} EP_IN=0x{_libusb_ep_in:02X} EP_OUT=0x{_libusb_ep_out:02X}")
        return True
    except Exception as e:
        logger.warning(f"USB打开失败: {e}")
        return False

def s_close():
    """Close USB device"""
    global _libusb_dev, _libusb_ep_out, _libusb_ep_in
    try:
        if _libusb_dev:
            try: _libusb_dev.reset()
            except: pass
    except Exception:
        pass
    _libusb_dev = None
    _libusb_ep_out = None
    _libusb_ep_in = None
    logger.info("USB设备已断开")

def s_send(c):
    """Send command to IotPower-cc"""
    if not _libusb_dev or _libusb_ep_out is None: return
    try:
        data = (c + "\r\n").encode()
        _libusb_dev.write(_libusb_ep_out, data, timeout=1000)
    except Exception as e:
        logger.warning(f"USB发送失败: {e}")

def s_qry(c):
    """Send query and read response"""
    if not _libusb_dev or _libusb_ep_in is None: return None
    try:
        s_send(c)
        time.sleep(0.05)
        raw = _libusb_dev.read(_libusb_ep_in, 256, timeout=1000)
        if raw and len(raw) > 0:
            return bytes(raw)
        return None
    except Exception as e:
        logger.warning(f"USB查询失败: {e}")
        return None

_debug_cnt = 0
_debug_v_cnt = 0
_v_filtered = 0
_sample_cnt = 0
_consec_v_filtered = 0   # 连续电压过滤计数（突发检测）
_last_v_filtered_ts = 0  # 上次过滤时的 sample_cnt
_c_raw_history = []
_v_raw_history = []
_prev_hist_v_mid = 0     # 上次历史中位数（基线漂移检测）
_packet_dump_cnt = 0     # 已dump的异常包数量
_adc_range = 1           # 当前ADC量程 (1/2/3)


def _detect_range(v):
    """检测v_raw所处的ADC量程"""
    if 15000 < v < 18000: return 1
    if 33000 < v < 36000: return 2
    if 48000 < v < 50000: return 3
    return 0


def s_readline():
    """Read one 64-byte USB packet, return filtered (v_raw, c_raw)"""
    global _debug_cnt, _debug_v_cnt, _v_filtered, _sample_cnt
    global _consec_v_filtered, _last_v_filtered_ts
    global _c_raw_history, _v_raw_history, _prev_hist_v_mid, _packet_dump_cnt, _adc_range
    if not _libusb_dev or _libusb_ep_in is None:
        return None
    try:
        raw = _libusb_dev.read(_libusb_ep_in, 64, timeout=50)
        if not raw or len(raw) < 4:
            return None
        raw = bytes(raw)
    except usb.core.USBTimeoutError:
        return None
    except Exception:
        return None

    # Skip control/sync packet (starts with 0xAA 0x55)
    if len(raw) >= 2 and raw[0] == 0xAA and raw[1] == 0x55:
        return None

    # Parse all 4-byte LE samples: [v_lo, v_hi, c_lo, c_hi]
    vs, cs = [], []
    i = 0
    while i + 3 < len(raw):
        v = raw[i] | (raw[i + 1] << 8)
        c = raw[i + 2] | (raw[i + 3] << 8)
        if v > 1000 and c > 0:
            vs.append(v)
            cs.append(c)
        i += 4

    if not vs:
        return None

    vs.sort(); cs.sort()
    mid = len(vs) // 2
    v_med = vs[mid]
    c_med = cs[mid]

    # ===== ADC量程检测与归一化 =====
    # 将不同量程下的raw值归一化到量程1，使后续换算系数(v/4044, c/9.9)始终正确
    cur_range = _detect_range(v_med)
    if cur_range > 1:
        v_med = v_med // cur_range
        c_med = c_med // cur_range
        if _adc_range != cur_range:
            logger.info(
                f"[ADC-RANGE] 量程 {_adc_range}→{cur_range}，raw已归一化到量程1"
            )
            _adc_range = cur_range
    elif cur_range == 1:
        _adc_range = 1

    # ===== 负载状态切换检测: 电流突变时重置电压+电流历史基线 =====
    # ⚡ 必须放在 OUTLIER 过滤之前，否则负载接入电流会被 OUTLIER 误拦截
    if len(_c_raw_history) >= 5 and len(_v_raw_history) >= 5:
        c_hist_mid = sorted(_c_raw_history)[len(_c_raw_history) // 2]
        if c_hist_mid > 100 and abs(c_med - c_hist_mid) > c_hist_mid * 2.5:
            # 电流变化 > 2.5× → 负载切换，重置所有历史基线
            _v_raw_history.clear()
            _c_raw_history.clear()
            _prev_hist_v_mid = 0
            _consec_v_filtered = 0
            logger.info(
                f"[BASELINE-RESET] 检测到负载切换，重置电压+电流基线 "
                f"c_med={c_med}(→{c_med/9.9:.1f}μA) "
                f"历史c_mid={c_hist_mid:.0f}(→{c_hist_mid/9.9:.1f}μA) "
                f"电流变化={abs(c_med-c_hist_mid)/c_hist_mid*100:.0f}%"
            )
            # 重置后跳过本次过滤，直接返回数据
            _sample_cnt += 1
            return (v_med, c_med)

    # 放宽: 仅日志记录大跳变，不丢弃数据（原始客户端即如此）
    if len(_c_raw_history) >= 5:
        hist_mid = sorted(_c_raw_history)[len(_c_raw_history)//2]
        if hist_mid > 100 and abs(c_med - hist_mid) > hist_mid * 8:
            if _debug_cnt < 10:
                logger.debug(f"OUTLIER(LOG): c={c_med} hist_mid={hist_mid:.0f} — 记录但不过滤")
                _debug_cnt += 1
            # 不再 return None — 允许数据通过

    # ===== 电压异常过滤 =====
    if len(_v_raw_history) >= 5:
        hist_v_all = sorted(_v_raw_history)
        hist_v_mid = hist_v_all[len(hist_v_all) // 2]
        deviation = abs(v_med - hist_v_mid) / hist_v_mid if hist_v_mid > 0 else 0
        dev_threshold = 0.45  # 45% 偏差阈值（raw已归一化，不应有大跳变）

        # ---- 基线漂移检测 ----
        if _prev_hist_v_mid > 0:
            hist_shift = abs(hist_v_mid - _prev_hist_v_mid) / _prev_hist_v_mid
            if hist_shift > 0.15 and _sample_cnt % 100 == 0:
                logger.warning(
                    f"[V-BASELINE] ⚠ 历史基线漂移: {_prev_hist_v_mid:.0f} → {hist_v_mid:.0f} "
                    f"(偏移{hist_shift*100:.1f}%)"
                )

        # ---- 异常判定 ----
        is_anomaly = (hist_v_mid > 100 and deviation > dev_threshold)

        if is_anomaly:
            _v_filtered += 1
            _consec_v_filtered += 1
            _last_v_filtered_ts = _sample_cnt

            # ---- 原始包字节 dump (前10次异常触发) ----
            pkt_hex = ""
            if _packet_dump_cnt < 10:
                pkt_hex = raw.hex(" ")
                _packet_dump_cnt += 1

            # ---- 当前包的原始采样统计 ----
            raw_v_min, raw_v_max = min(vs), max(vs)
            raw_c_min, raw_c_max = min(cs), max(cs)
            hist_v_volt = hist_v_mid / 4044.0
            cur_v_volt = v_med / 4044.0
            c_mid = cs[mid]

            logger.info(
                f"[V-FILTER] #{_v_filtered} │ "
                f"v_med={v_med}(→{cur_v_volt:.2f}V) "
                f"vs 历史中位数={hist_v_mid:.0f}(→{hist_v_volt:.2f}V) "
                f"偏离={deviation*100:.1f}% (阈值{dev_threshold*100:.0f}%)"
            )
            logger.info(
                f"[V-FILTER] #{_v_filtered} │ "
                f"当前包raw: v范围[{raw_v_min},{raw_v_max}] c范围[{raw_c_min},{raw_c_max}] "
                f"c_med={c_mid}(→{c_mid/9.9:.1f}μA) │ "
                f"连续过滤={_consec_v_filtered}次 │ 历史v范围[{hist_v_all[0]},{hist_v_all[-1]}]"
            )

            if pkt_hex:
                logger.debug(f"[V-FILTER-DUMP] #{_v_filtered} 原始包(64B hex): {pkt_hex}")

            if _debug_v_cnt < 10:
                _debug_v_cnt += 1
                hist_n = min(10, len(hist_v_all))
                hist_recent = hist_v_all[-hist_n:]
                logger.debug(f"[V-FILTER-HIST] #{_v_filtered} 历史v_raw最近{hist_n}个: {hist_recent}")

            _prev_hist_v_mid = hist_v_mid

            # ---- 连续过滤超过 100 次时自动重置基线（防止永久死锁） ----
            if _consec_v_filtered >= 100:
                logger.warning(
                    f"[V-FILTER-AUTO-RESET] 连续过滤 {_consec_v_filtered} 次，自动重置电压基线"
                )
                _v_raw_history.clear()
                _prev_hist_v_mid = 0

            return None

        else:
            # ---- 突发结束检测 ----
            if _consec_v_filtered >= 3:
                logger.info(
                    f"[V-FILTER-END] 电压异常突发结束，共连续过滤 {_consec_v_filtered} 个点，"
                    f"当前v_med={v_med}(→{v_med/4044.0:.2f}V) 恢复正常"
                )
            _consec_v_filtered = 0

        _prev_hist_v_mid = hist_v_mid

    # ===== 每200次有效采样输出电压过滤器状态 =====
    if _sample_cnt > 0 and _sample_cnt % 200 == 0:
        if len(_v_raw_history) >= 5:
            hv = sorted(_v_raw_history)
            rate = _v_filtered / _sample_cnt * 100 if _sample_cnt > 0 else 0
            c_filt_approx = _debug_cnt  # 电流过滤次数
            logger.debug(
                f"[V-FILTER-STAT] sample={_sample_cnt} "
                f"v过滤={_v_filtered}({rate:.1f}%) c过滤≈{c_filt_approx} "
                f"v范围[{hv[0]},{hv[len(hv)//2]},{hv[-1]}]"
            )
            # 过滤率 > 20% 时自动告警，输出诊断信息
            if rate > 20:
                logger.warning(
                    f"[V-FILTER-ALARM] ⚠ 电压过滤率异常高 {rate:.1f}%！"
                    f" 近200次采样中 {_v_filtered}/{_sample_cnt} 被过滤"
                )
                hv_mid = hv[len(hv)//2]
                r = _detect_range(hv_mid)
                range_hint = {1: "量程1(4V)", 2: "量程2(8V)", 3: "量程3(12V)", 0: "未知"}.get(r, "未知")
                hv_volt = hv_mid / 4044.0  # 已归一化到量程1
                logger.warning(
                    f"[V-FILTER-ALARM] 当前基线: v_mid={hv_mid}→{hv_volt:.2f}V ({range_hint}) "
                    f"v_min={hv[0]} v_max={hv[-1]}"
                )
                logger.warning(
                    f"[V-FILTER-ALARM] 排查建议:"
                    f" 1)超过45%偏差 → 可能是USB数据异常"
                    f" 2)连续过滤>100次 → 自动重置基线"
                    f" 3)检查量程归一化是否正常工作"
                )

    _c_raw_history.append(c_med)
    if len(_c_raw_history) > 50:
        _c_raw_history.pop(0)

    _v_raw_history.append(v_med)
    if len(_v_raw_history) > 50:
        _v_raw_history.pop(0)

    _sample_cnt += 1
    return (v_med, c_med)

# ===== Theme =====
def get_themes(is_low_res):
    fs = "11px" if is_low_res else "13px"
    fs_title = "10px" if is_low_res else "11px"
    fs_btn = "11px" if is_low_res else "13px"
    pad = "4px 8px" if is_low_res else "6px 12px"
    h = "24px" if is_low_res else "28px"
    gp_pad = "6px" if is_low_res else "12px"
    tab_pad = "5px 10px" if is_low_res else "8px 16px"
    
    DARK = f"""
    QMainWindow,QWidget{{background:#1e1e2e;color:#cdd6f4;font-family:"Microsoft YaHei","Segoe UI",sans-serif;font-size:{fs}}}
    QGroupBox{{background:#181825;border:1px solid #313244;border-radius:8px;margin-top:14px;padding:{gp_pad};font-weight:bold;color:#cdd6f4}}
    QGroupBox::title{{subcontrol-origin:margin;left:10px;padding:0 4px;color:#6c7086;font-size:{fs_title}}}
    QLabel{{color:#bac2de;background:transparent}}
    QPushButton{{border:1px solid #313244;border-radius:6px;padding:{pad};min-height:{h};font-weight:bold;color:#fff;font-size:{fs_btn}}}
    QPushButton:hover{{opacity:0.9;background:#313244}}QPushButton:pressed{{padding-top:7px;padding-bottom:5px}}
    QPushButton:disabled{{background:#313244!important;color:#585b70!important;border-color:#313244!important}}
    QPushButton#conn{{background:#89b4fa;border-color:#89b4fa}}QPushButton#start{{background:#a6e3a1;border-color:#a6e3a1}}
    QPushButton#stop{{background:#f38ba8;border-color:#f38ba8}}
    QPushButton#test{{background:#313244;color:#bac2de;border-color:#45475a}}QPushButton#test:checked{{background:#fab387;border-color:#fab387}}
    QPushButton#save{{background:#89b4fa;border-color:#89b4fa}}QPushButton#load{{background:#cba6f7;border-color:#cba6f7}}
    QPushButton#clear{{background:#6c7086;border-color:#6c7086}}
    QPushButton#on{{background:#a6e3a1;border-color:#a6e3a1}}QPushButton#off{{background:#f38ba8;border-color:#f38ba8}}
    QMessageBox{{background:#1e1e2e;color:#cdd6f4}}
    QMessageBox QLabel{{color:#cdd6f4;background:transparent}}
    QMessageBox QPushButton{{background:#313244;color:#cdd6f4;border:1px solid #45475a;border-radius:6px;padding:8px 16px;min-width:80px;font-weight:bold}}
    QMessageBox QPushButton:hover{{background:#45475a}}
    QMessageBox QPushButton:pressed{{background:#585b70}}
    QTabWidget::pane{{border:1px solid #313244;border-radius:4px;background:#1e1e2e}}
    QTabBar::tab{{background:#181825;color:#6c7086;padding:{tab_pad};border:1px solid #313244;border-bottom:none;border-radius:4px 4px 0 0;margin-right:2px;font-size:{fs_btn}}}
    QTabBar::tab:selected{{color:#cdd6f4;background:#1e1e2e;border-color:#89b4fa;border-bottom:2px solid #89b4fa}}
    QTabBar::tab:hover{{color:#bac2de;background:#1e1e2e}}
    QTextEdit{{background:#11111b;border:1px solid #313244;border-radius:4px;color:#bac2de;font-family:"Consolas",monospace;font-size:12px}}
    QSpinBox,QDoubleSpinBox,QComboBox{{background:#11111b;border:1px solid #313244;border-radius:4px;padding:4px 8px;color:#cdd6f4;min-height:22px;font-size:{fs_btn}}}
    QToolBar{{background:#11111b;border-bottom:1px solid #313244;spacing:4px;padding:2px}}
    QToolBar QToolButton{{background:#1e1e2e;color:#bac2de;border:1px solid #313244;border-radius:4px;padding:4px 10px;font-weight:bold;font-size:{fs_btn}}}
    QToolBar QToolButton:hover{{background:#313244;color:#cdd6f4;border-color:#45475a}}
    QToolBar QToolButton:pressed{{background:#45475a}}
    QStatusBar{{background:#11111b;border-top:1px solid #313244;color:#6c7086;font-size:11px}}
    QSlider::groove:horizontal{{height:4px;background:#313244;border-radius:2px}}
    QSlider::handle:horizontal{{width:14px;height:14px;margin:-5px 0;background:#89b4fa;border-radius:7px}}
    QProgressBar{{border:1px solid #313244;border-radius:4px;text-align:center;color:#cdd6f4}}
    QProgressBar::chunk{{background:#89b4fa;border-radius:3px}}
    """
    
    LIGHT = f"""
    QMainWindow,QWidget{{background:#eff1f5;color:#4c4f69;font-family:"Microsoft YaHei","Segoe UI",sans-serif;font-size:{fs}}}
    QGroupBox{{background:#e6e9ef;border:1px solid #ccd0da;border-radius:8px;margin-top:14px;padding:{gp_pad};font-weight:bold;color:#4c4f69}}
    QGroupBox::title{{subcontrol-origin:margin;left:10px;padding:0 4px;color:#7c7f93;font-size:{fs_title}}}
    QLabel{{color:#5c5f77;background:transparent}}
    QPushButton{{border:none;border-radius:6px;padding:{pad};min-height:{h};font-weight:bold;color:#fff;font-size:{fs_btn}}}
    QPushButton:hover{{opacity:0.9}}QPushButton:pressed{{padding-top:7px;padding-bottom:5px}}
    QPushButton:disabled{{background:#ccd0da!important;color:#9ca0b0!important}}
    QPushButton#conn{{background:#1e66f5}}QPushButton#start{{background:#40a02b}}QPushButton#stop{{background:#d20f39}}
    QPushButton#test{{background:#ccd0da;color:#5c5f77}}QPushButton#test:checked{{background:#fe640b}}
    QPushButton#save{{background:#1e66f5}}QPushButton#load{{background:#8839ef}}QPushButton#clear{{background:#7c7f93}}
    QPushButton#on{{background:#40a02b}}QPushButton#off{{background:#d20f39}}
    QMessageBox{{background:#eff1f5;color:#4c4f69}}
    QMessageBox QLabel{{color:#4c4f69;background:transparent}}
    QMessageBox QPushButton{{background:#1e66f5;color:#ffffff;border:none;border-radius:6px;padding:8px 16px;min-width:80px;font-weight:bold}}
    QMessageBox QPushButton:hover{{background:#1557d0}}
    QMessageBox QPushButton:pressed{{background:#1248b0}}
    QTabWidget::pane{{border:1px solid #ccd0da}}
    QTabBar::tab{{background:#e6e9ef;color:#7c7f93;padding:{tab_pad};border:none;border-bottom:2px solid transparent;font-size:{fs_btn}}}
    QTabBar::tab:selected{{color:#4c4f69;border-bottom:2px solid #1e66f5}}
    QTextEdit{{background:#fff;background:#eff1f5;border:1px solid #ccd0da;border-radius:4px;color:#5c5f77;font-family:"Consolas",monospace;font-size:12px}}
    QSpinBox,QDoubleSpinBox,QComboBox{{background:#eff1f5;border:1px solid #ccd0da;border-radius:4px;padding:4px 8px;color:#4c4f69;min-height:22px;font-size:{fs_btn}}}
    QToolBar{{background:#e6e9ef;border-bottom:1px solid #ccd0da;spacing:4px;padding:2px}}
    QToolBar QToolButton{{background:#eff1f5;color:#5c5f77;border:1px solid #ccd0da;border-radius:4px;padding:4px 10px;font-weight:bold;font-size:{fs_btn}}}
    QToolBar QToolButton:hover{{background:#ccd0da;color:#4c4f69;border-color:#bcc0cc}}
    QToolBar QToolButton:pressed{{background:#bcc0cc}}
    QStatusBar{{background:#e6e9ef;border-top:1px solid #ccd0da;color:#7c7f93;font-size:11px}}
    QSlider::groove:horizontal{{height:4px;background:#ccd0da;border-radius:2px}}
    QSlider::handle:horizontal{{width:14px;height:14px;margin:-5px 0;background:#1e66f5;border-radius:7px}}
    QProgressBar{{border:1px solid #ccd0da;border-radius:4px;text-align:center;color:#4c4f69}}
    QProgressBar::chunk{{background:#1e66f5;border-radius:3px}}
    """
    return DARK, LIGHT

class RoundSwitch(QCheckBox):
    _off_bg = "#585b70"
    _on_bg = "#a6e3a1"
    _handle = "#cdd6f4"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setText("")
        self._handle_pos = 3.0
        self._setup_animation()

    def _setup_animation(self):
        self._anim = QPropertyAnimation(self, b"handle_pos")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

    def get_handle_pos(self):
        return self._handle_pos

    def set_handle_pos(self, val):
        self._handle_pos = val
        self.update()

    handle_pos = pyqtProperty(float, get_handle_pos, set_handle_pos)

    def set_dark(self, is_dark):
        if is_dark:
            RoundSwitch._off_bg = "#585b70"
            RoundSwitch._on_bg = "#a6e3a1"
            RoundSwitch._handle = "#cdd6f4"
        else:
            RoundSwitch._off_bg = "#bcc0cc"
            RoundSwitch._on_bg = "#40a02b"
            RoundSwitch._handle = "#ffffff"
        self.update()

    def nextCheckState(self):
        super().nextCheckState()
        target = 27.0 if self.isChecked() else 3.0
        self._anim.stop()
        self._anim.setStartValue(self._handle_pos)
        self._anim.setEndValue(target)
        self._anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self.isChecked())
            target = 27.0 if self.isChecked() else 3.0
            self._anim.stop()
            self._anim.setStartValue(self._handle_pos)
            self._anim.setEndValue(target)
            self._anim.start()
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2.0

        if self.isChecked():
            bg = QColor(RoundSwitch._on_bg)
        else:
            bg = QColor(RoundSwitch._off_bg)

        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(0, 0, w, h, r, r)

        hx = self._handle_pos
        hr = (h - 6) / 2.0
        hy = (h - hr * 2) / 2.0
        grad = QRadialGradient(hx + hr, hy + hr, hr)
        grad.setColorAt(0, QColor(RoundSwitch._handle))
        grad.setColorAt(1, QColor(RoundSwitch._handle).darker(110))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(0, 0, 0, 20), 0.5))
        p.drawEllipse(int(hx), int(hy), int(hr * 2), int(hr * 2))
        p.end()

class RegionAnalysisPanel(QWidget):
    """选区分析面板（含截图/报告/关闭按钮）"""
    screenshot_requested = pyqtSignal()
    report_requested = pyqtSignal()
    close_requested = pyqtSignal()
    minimize_requested = pyqtSignal()

    def __init__(self, is_dark=True, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)
        self.is_dark = is_dark
        self._apply_theme()
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 8)
        main_layout.setSpacing(14)

        # Top bar: minimize + close
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.btn_mini = QPushButton("─")
        self.btn_mini.setFixedSize(28, 28)
        self.btn_mini.setStyleSheet("""
            QPushButton { background: transparent; color: #6c7086; border: none;
                border-radius: 4px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: #313244; color: #cdd6f4; }
        """)
        self.btn_mini.clicked.connect(self.minimize_requested.emit)
        top.addWidget(self.btn_mini)
        top.addStretch()
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setStyleSheet("""
            QPushButton { background: transparent; color: #6c7086; border: none;
                border-radius: 4px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: #e81123; color: white; }
        """)
        self.btn_close.clicked.connect(self.close_requested.emit)
        top.addWidget(self.btn_close)
        main_layout.addLayout(top)

        self.avg_block = self._create_block("∿", "平均", "#77ff77", ["-- V", "-- mA", "-- mW"])
        main_layout.addWidget(self.avg_block)
        self.max_block = self._create_block("↑", "最高", "#ff6666", ["-- V", "-- mA"])
        main_layout.addWidget(self.max_block)
        self.min_block = self._create_block("↓", "最低", "#77bbff", ["-- V", "-- mA"])
        main_layout.addWidget(self.min_block)
        self.energy_block = self._create_block("⚡", "电量", "#e6b87a", ["-- μAh", "-- μWh"])
        main_layout.addWidget(self.energy_block)
        self.time_block = self._create_block("⟳", "时间", "#aaaaaa", ["-- 秒", "-- Hz"])
        main_layout.addWidget(self.time_block)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_screenshot = QPushButton("截图区域")
        self.btn_screenshot.setStyleSheet("""
            QPushButton { background: #313244; color: #cdd6f4; border: 1px solid #45475a;
                border-radius: 6px; padding: 8px 12px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background: #45475a; }
        """)
        self.btn_screenshot.clicked.connect(self.screenshot_requested.emit)
        btn_row.addWidget(self.btn_screenshot)

        self.btn_report = QPushButton("生成报告")
        self.btn_report.setStyleSheet("""
            QPushButton { background: #89b4fa; color: #1e1e2e; border: none;
                border-radius: 6px; padding: 8px 12px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background: #74a8fa; }
        """)
        self.btn_report.clicked.connect(self.report_requested.emit)
        btn_row.addWidget(self.btn_report)
        main_layout.addLayout(btn_row)

        main_layout.addStretch()

    def set_dark(self, is_dark):
        self.is_dark = is_dark
        self._apply_theme()

    def _apply_theme(self):
        bg = "#121212" if self.is_dark else "#eff1f5"
        self.setStyleSheet(f"background-color: {bg};")

    def _create_block(self, icon_text, title, color, value_texts):
        block = QWidget()
        block.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(6)
        
        sub_color = "#888888" if self.is_dark else "#7c7f93"
        
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        icon_label = QLabel(icon_text)
        icon_label.setStyleSheet(f"color: {color}; font-size: 18px; background: transparent;")
        icon_label.setFixedWidth(24)
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold; background: transparent;")
        sub_label = QLabel("选中区域")
        sub_label.setStyleSheet(f"color: {sub_color}; font-size: 12px; background: transparent;")
        top_row.addWidget(icon_label)
        top_row.addWidget(title_label)
        top_row.addStretch()
        top_row.addWidget(sub_label)
        layout.addLayout(top_row)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {color};")
        layout.addWidget(line)
        
        value_layout = QVBoxLayout()
        value_layout.setSpacing(4)
        value_layout.setContentsMargins(4, 4, 4, 0)
        value_labels = []
        for text in value_texts:
            lb = QLabel(text)
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lb.setStyleSheet(f"color: {color}; font-size: 26px; font-family: Consolas; font-weight: bold; background: transparent;")
            value_layout.addWidget(lb)
            value_labels.append(lb)
        layout.addLayout(value_layout)
        
        block.value_labels = value_labels
        return block

    def update_avg(self, volt, curr, power):
        self.avg_block.value_labels[0].setText(f"{volt:.4f} V")
        self.avg_block.value_labels[1].setText(f"{curr:.4f} mA")
        self.avg_block.value_labels[2].setText(f"{power:.4f} mW")

    def update_max(self, volt, curr):
        self.max_block.value_labels[0].setText(f"{volt:.4f} V")
        self.max_block.value_labels[1].setText(f"{curr:.4f} mA")

    def update_min(self, volt, curr):
        self.min_block.value_labels[0].setText(f"{volt:.4f} V")
        self.min_block.value_labels[1].setText(f"{curr:.4f} mA")

    def update_energy(self, charge_uah, energy_uwh):
        self.energy_block.value_labels[0].setText(f"{charge_uah:.4f} μAh")
        self.energy_block.value_labels[1].setText(f"{energy_uwh:.4f} μWh")

    def update_time(self, duration_sec, freq_hz):
        self.time_block.value_labels[0].setText(f"{duration_sec:.4f} 秒")
        self.time_block.value_labels[1].setText(f"{freq_hz:.4f} Hz")

class TimeAxisItem(pg.AxisItem):
    """Custom axis item that displays system time"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.t0_abs = None

    def setStartTime(self, t0):
        self.t0_abs = t0

    def _format_system_time(self, dt):
        total_sec = (dt.hour * 3600 + dt.minute * 60 + dt.second)
        if total_sec < 3600:
            return dt.strftime("%H:%M:%S")
        return dt.strftime("%H:%M:%S")

    def tickStrings(self, values, scale, spacing):
        if self.t0_abs is None:
            return [f"{v:.1f}" for v in values]
        strings = []
        for v in values:
            dt = self.t0_abs + timedelta(seconds=v)
            strings.append(dt.strftime("%H:%M:%S"))
        return strings

class Main(QMainWindow):
    def _curr_axis_label(self):
        """Y-axis label: always mA"""
        return "电流 (mA)"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PG-Power | GPIB电源测试工具 v{APP_VERSION}")
        # Adaptive window size based on screen resolution
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.is_low_res = geo.width() < 1280 or geo.height() < 800
            if self.is_low_res:
                self.resize(min(geo.width() - 50, 1024), min(geo.height() - 50, 768))
            else:
                self.resize(1500, 900)
        else:
            self.is_low_res = False
            self.resize(1500, 900)
        ico = os.path.join(sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(ico): self.setWindowIcon(QIcon(ico))

        # Data
        self.ts=[]; self.vs=[]; self.cs=[]; self.ps=[]
        self.t0=time.time(); self.e_mwh=0.0; self.max_c=0.0; self.min_c=float("inf")
        self.collecting=False; self.test_mode=False; self.track_side="right"
        self.display_mode="instant"  # instant / average
        self.unit=0  # 0=mWh/Ah  1=Wh/Ah
        self.coord_mode=0  # 0=adaptive 1=fixed 2=log
        self.scroll_pos=0
        self.time_mode=0  # 0=relative seconds, 1=system time
        self.sample_interval=50  # ms
        self.data_font_size=18  # px for average/cumulative labels
        self.data_font_bold=True
        self.device_mode="gpib"  # "gpib" or "luatos"
        self.serial_port_name=""
        self.analysis_win=None
        self.region_panel=None
        self.t0_abs=None
        self.setMouseTracking(True)

        # Test phases — 阶梯升降波形 (mA单位, *1000→µA)
        _ph = []
        # 待机
        _ph.append({"n":"待机","d":60,"v":5.0,"c":0.3,"s":0.010})
        # 上升: 0→1000mA, 5mA步进, 每步100ms (d=2 @50ms)
        for c in range(0, 1005, 5):
            _ph.append({"n":f"↑{c}mA","d":2,"v":5.0,"c":c,"s":max(c*0.005, 0.01)})
        # 峰值保持 2s
        _ph.append({"n":"峰值1000mA","d":40,"v":5.0,"c":1000,"s":2.0})
        # 下降: 995→0mA, 5mA步进, 每步1秒 (d=20 @50ms)
        for c in range(995, -5, -5):
            _ph.append({"n":f"↓{c}mA","d":20,"v":5.0,"c":c,"s":max(c*0.005, 0.01)})
        # 待机结束
        _ph.append({"n":"待机","d":60,"v":5.0,"c":0.3,"s":0.010})
        self.phases = _ph
        self.phi=0; self.pe=0

        # Cache settings
        self.auto_save_threshold=50000
        self.save_count=0

        self._init_ui()
        self._load_settings()
        set_dark_titlebar(self, self.theme_idx != 1)

        self.timer=QTimer(); self.timer.setInterval(50); self.timer.timeout.connect(self._ui); self.timer.start()
        self.statusBar().showMessage("就绪 | GPIB: " + ("可用" if GPIB_OK else "不可用"))

        if not GPIB_OK:
            QMessageBox.warning(self,"提示","GPIB驱动未加载，可使用测试模式预览")

    def _init_ui(self):
        m=QVBoxLayout(self); m.setContentsMargins(0,0,0,0); m.setSpacing(0)
        tb=QToolBar(); tb.setMovable(False); self.addToolBar(tb)
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
        # Screenshot
        self.act_screenshot=QAction("截图",self); self.act_screenshot.triggered.connect(self._screenshot); tb.addAction(self.act_screenshot)
        # Voltage visibility toggle
        self.act_voltage=QAction("电压:显示",self); self.act_voltage.setCheckable(True)
        self.act_voltage.setChecked(True); self.act_voltage.triggered.connect(self._toggle_voltage)
        tb.addAction(self.act_voltage)
        self.show_voltage=True

        tabs=QTabWidget(); self.setCentralWidget(tabs)
        w1=QWidget(); tabs.addTab(w1,"数据与波形")
        w2=QWidget(); tabs.addTab(w2,"设备与设置")
        w3=QWidget(); tabs.addTab(w3,"选区分析")
        w4=QWidget(); tabs.addTab(w4,"脚本控制")
        w5=QWidget(); tabs.addTab(w5,"关于")

        self._init_wave(w1); self._init_settings(w2); self._init_analysis(w3)
        self._init_script(w4)
        scroll_a = QScrollArea()
        scroll_a.setWidgetResizable(True)
        scroll_a.setFrameShape(QFrame.NoFrame)
        about_w = QWidget()
        lo = QVBoxLayout(about_w)
        lo.setAlignment(Qt.AlignCenter)
        lo.setSpacing(6)
        ico_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "Icons", "ios_ios-1024.png"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "Icons", "web_web-256.png"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "Icons", "windows_windows-256.png"),
        ]
        for p in ico_paths:
            if os.path.exists(p):
                ico_path = p
                break
        else:
            ico_path = None
        if ico_path:
            icon = QLabel()
            pix = QPixmap(ico_path)
            if not pix.isNull():
                icon.setPixmap(pix.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                icon.setAlignment(Qt.AlignCenter)
                lo.addWidget(icon)
        lo.addSpacing(8)
        ver = QLabel(f"<h1 style='margin:0;font-size:22pt;'>PG-Power v{APP_VERSION}</h1>")
        ver.setAlignment(Qt.AlignCenter)
        lo.addWidget(ver)
        for txt in [
            "<span style='font-size:14pt;'><b>基于LuatOS PC客户端功能规范</b></span>",
            "<span style='font-size:14pt;'>Python + PyQt5 + PyQtGraph</span>",
            "<hr width='60%'>",
            "<span style='font-size:14pt;'><b>开发者：</b>zhaohuwei</span>",
            "<span style='font-size:14pt;'><b>项目地址：</b><a href='https://gitcode.com/dxdw2021/PG-Power' style='color:#89b4fa;'>gitcode.com/dxdw2021/PG-Power</a></span>",
            "<hr width='60%'>",
            "<span style='color:#6c7086;font-size:11pt;'>GPIB电源测试工具 &copy; 2026</span>"
        ]:
            lb = QLabel(txt)
            lb.setAlignment(Qt.AlignCenter)
            lb.setOpenExternalLinks(True)
            lo.addWidget(lb)
        lo.addStretch()
        scroll_a.setWidget(about_w)
        QVBoxLayout(w5).addWidget(scroll_a)

    # ===== Tab1: Wave =====
    def _init_wave(self, parent):
        lay=QHBoxLayout(parent); sp=QSplitter(Qt.Horizontal)

        # Left panel - scrollable
        left_scroll=QScrollArea(); left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left=QWidget()
        left_width = 200 if self.is_low_res else 260
        left_scroll.setFixedWidth(left_width + 20)
        ll=QVBoxLayout(left); ll.setSpacing(2 if self.is_low_res else 4)
        
        # Adaptive font sizes
        fs_big = "14px" if self.is_low_res else "18px"
        fs_normal = "11px" if self.is_low_res else "13px"
        fs_small = "10px" if self.is_low_res else "11px"

        # Display mode selector
        # ---- 快速连接（左侧菜单顶部） ----
        g_quick = QGroupBox("快速连接")
        gq_lay = QHBoxLayout(g_quick); gq_lay.setSpacing(4)
        gq_lay.setContentsMargins(6, 8, 6, 8)
        self.cb_quick_type = QComboBox()
        self.cb_quick_type.addItems(["GPIB", "USB (IotPower-cc)"])
        self.cb_quick_type.setMinimumHeight(24)
        gq_lay.addWidget(self.cb_quick_type)
        self.btn_quick_conn = QPushButton("连接")
        self.btn_quick_conn.setObjectName("conn")
        self.btn_quick_conn.setMinimumHeight(24)
        self.btn_quick_conn.clicked.connect(self._quick_connect)
        gq_lay.addWidget(self.btn_quick_conn)
        ll.addWidget(g_quick)

        g0=QGroupBox("显示模式"); gl0=QVBoxLayout(g0)
        self.cb_disp=QComboBox(); self.cb_disp.addItems(["瞬时值","滑动平均值"])
        self.cb_disp.currentIndexChanged.connect(lambda i: setattr(self,'display_mode',['instant','average'][i]))
        gl0.addWidget(self.cb_disp); ll.addWidget(g0)

        # Instant values
        g1=QGroupBox("当前数据"); gl1=QVBoxLayout(g1); gl1.setSpacing(2)
        self.lb_ic=QLabel("0.000 mA"); self.lb_ic.setStyleSheet(f"color:#3b82f6;font-size:{fs_big};font-weight:bold;background:transparent")
        self.lb_iv=QLabel("0.000 V"); self.lb_iv.setStyleSheet(f"color:#e11d48;font-size:{fs_big};font-weight:bold;background:transparent")
        self.lb_ip=QLabel("0.000 mW"); self.lb_ip.setStyleSheet(f"color:#d97706;font-size:{fs_big};font-weight:bold;background:transparent")
        gl1.addWidget(self.lb_ic); gl1.addWidget(self.lb_iv); gl1.addWidget(self.lb_ip); ll.addWidget(g1)

        # Average
        g2=QGroupBox("平均数据"); gl2=QVBoxLayout(g2); gl2.setSpacing(2)
        fs_data = f"{self.data_font_size}px"
        self.lb_ac=QLabel("平均电流: -- mA"); self.lb_ac.setStyleSheet(f"color:#3b82f6;font-size:{fs_data};background:transparent")
        self.lb_av=QLabel("平均电压: -- V"); self.lb_av.setStyleSheet(f"color:#e11d48;font-size:{fs_data};background:transparent")
        self.lb_ap=QLabel("平均功率: -- mW"); self.lb_ap.setStyleSheet(f"color:#d97706;font-size:{fs_data};background:transparent")
        gl2.addWidget(self.lb_ac); gl2.addWidget(self.lb_av); gl2.addWidget(self.lb_ap); ll.addWidget(g2)

        # Cumulative
        g3=QGroupBox("累计数据"); gl3=QVBoxLayout(g3); gl3.setSpacing(2)
        self.lb_mx=QLabel("最大电流: -- mA"); self.lb_mx.setStyleSheet(f"color:#e11d48;font-size:{fs_data};background:transparent")
        self.lb_mn=QLabel("最小电流: -- mA"); self.lb_mn.setStyleSheet(f"color:#16a34a;font-size:{fs_data};background:transparent")
        self.lb_en=QLabel("总耗电: -- mWh"); self.lb_en.setStyleSheet(f"color:#d97706;font-size:{fs_data};background:transparent")
        self.lb_ah=QLabel("累计电量: -- mAh"); self.lb_ah.setStyleSheet(f"color:#0891b2;font-size:{fs_data};background:transparent")
        self.lb_tm=QLabel("总时长: 00:00:00"); self.lb_tm.setStyleSheet(f"font-size:{fs_data};background:transparent")
        self.lb_n=QLabel("采样点数: 0"); self.lb_n.setStyleSheet(f"font-size:{fs_data};background:transparent")
        self.btn_unit=QPushButton("切换 mWh/Wh"); self.btn_unit.setObjectName("save")
        self.btn_unit.clicked.connect(self._switch_unit)
        gl3.addWidget(self.lb_mx); gl3.addWidget(self.lb_mn); gl3.addWidget(self.lb_en)
        gl3.addWidget(self.lb_ah); gl3.addWidget(self.lb_tm); gl3.addWidget(self.lb_n)
        gl3.addWidget(self.btn_unit); ll.addWidget(g3)

        # 采集控制
        g4=QGroupBox("采集控制"); gl4=QVBoxLayout(g4); gl4.setSpacing(2)
        self.btn_te=QPushButton("测试模式"); self.btn_te.setObjectName("test")
        self.btn_te.setCheckable(True); self.btn_te.clicked.connect(self._toggle_test); gl4.addWidget(self.btn_te)
        self.btn_st=QPushButton("开始采集"); self.btn_st.setObjectName("start")
        self.btn_st.clicked.connect(self._start); gl4.addWidget(self.btn_st)
        self.btn_sp=QPushButton("停止采集"); self.btn_sp.setObjectName("stop")
        self.btn_sp.clicked.connect(self._stop); gl4.addWidget(self.btn_sp)
        gl4.addWidget(QLabel("采样率(ms):"))
        self.cb_sample=QComboBox(); self.cb_sample.setEditable(True)
        self.cb_sample.addItems(["20","50","70","100","200","300","500","1000"])
        self.cb_sample.setCurrentText("50")
        self.cb_sample.currentTextChanged.connect(lambda v: setattr(self,'sample_interval',int(v) if v.isdigit() else 50))
        gl4.addWidget(self.cb_sample)
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
        if self.time_mode:
            self.time_axis_m = TimeAxisItem(orientation='bottom')
            self.pm = pg.PlotWidget(axisItems={'bottom': self.time_axis_m})
        else:
            self.pm = pg.PlotWidget()
        self.pm.setMouseTracking(True)
        self.pm.setBackground("#11111b"); self.pm.showGrid(x=True,y=True,alpha=0.1)
        self.pm.setLabel("left", self._curr_axis_label(), color="#89b4fa"); self.pm.setLabel("bottom","系统时间" if self.time_mode else "时间 (s)",color="#6c7086")
        self.pm.getAxis('left').autoSIPrefix = False
        self.pm.setTitle("电压 / 电流 波形",color="#cdd6f4",size="12pt")
        self._cn_menu(self.pm)
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
        # Set ViewBox limits to prevent negative values
        self.pm.plotItem.vb.setLimits(xMin=0, yMin=0)
        self.pm_vb2.setLimits(xMin=0, yMin=0)
        self.cm_v=pg.PlotDataItem(pen=pg.mkPen("#f38ba8",width=2),name="电压(V)")
        self.pm_vb2.addItem(self.cm_v)
        self.pm.addLegend(offset=(-10,10))
        # Sync ViewBoxes - defer initial sync
        self.pm.plotItem.vb.sigResized.connect(self._sync_vb)
        # Current indicator line (horizontal, movable, will be repositioned)
        self.tc_m=pg.InfiniteLine(angle=0,movable=False,pen=pg.mkPen("#89b4fa",width=1,style=Qt.DotLine))
        self.pm.addItem(self.tc_m, ignoreBounds=True)
        # Vertical time indicator line (merged)
        self.tm_m=pg.InfiniteLine(angle=90,movable=False,pen=pg.mkPen("#89b4fa",width=1,style=Qt.DotLine))
        self.pm.addItem(self.tm_m, ignoreBounds=True)
        # Voltage indicator line (horizontal, mapped Y)
        self.tvl_m=pg.InfiniteLine(angle=0,movable=False,pen=pg.mkPen("#f38ba8",width=1,style=Qt.DotLine))
        self.pm.addItem(self.tvl_m, ignoreBounds=True)
        self.vm=pg.InfiniteLine(90,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.hm=pg.InfiniteLine(0,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.pm.addItem(self.vm,ignoreBounds=True); self.pm.addItem(self.hm,ignoreBounds=True)
        self.xm=pg.TextItem(color="#cdd6f4",anchor=(0,1),border=pg.mkPen("#585b70",width=1),fill=pg.mkBrush("#1e1e2eee"))
        self.xm.hide(); self.pm.addItem(self.xm)
        # Real-time labels for merged mode (added to scene to avoid clipping)
        self.lmc=pg.TextItem(color="#89b4fa",anchor=(0,0.5),fill=pg.mkBrush("#11111bcc"))
        self.pm.scene().addItem(self.lmc)
        self.lmv=pg.TextItem(color="#f38ba8",anchor=(1,0.5),fill=pg.mkBrush("#11111bcc"))
        self.pm.scene().addItem(self.lmv)
        self.pm.scene().sigMouseMoved.connect(self._mm)
        self.pm.hide()
        ml.addWidget(self.pm)

        # Dual mode: Current plot
        if self.time_mode:
            self.time_axis_c = TimeAxisItem(orientation='bottom')
            self.pc = pg.PlotWidget(axisItems={'bottom': self.time_axis_c})
        else:
            self.pc = pg.PlotWidget()
        self.pc.setMouseTracking(True)
        self.pc.setBackground("#11111b"); self.pc.showGrid(x=True,y=True,alpha=0.1)
        self.pc.setLabel("left", self._curr_axis_label(), color="#6c7086"); self.pc.setLabel("bottom","系统时间" if self.time_mode else "时间 (s)",color="#6c7086")
        self.pc.getAxis('left').autoSIPrefix = False
        self.pc.setTitle("电流波形",color="#cdd6f4",size="12pt")
        self._cn_menu(self.pc)
        # Set ViewBox limits to prevent negative values
        self.pc.plotItem.vb.setLimits(xMin=0, yMin=0)
        self.pc.plotItem.vb.enableAutoRange(enable=False)
        if hasattr(self.pc.plotItem.vb, 'autoRangeBtn') and self.pc.plotItem.vb.autoRangeBtn:
            self.pc.plotItem.vb.autoRangeBtn.show()
        self.cc=self.pc.plot(pen=pg.mkPen("#89b4fa",width=2),fillLevel=0,brush=pg.mkBrush(137,180,250,40))
        self.vc=pg.InfiniteLine(90,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.hc=pg.InfiniteLine(0,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.pc.addItem(self.vc,ignoreBounds=True); self.pc.addItem(self.hc,ignoreBounds=True)
        self.xc=pg.TextItem(color="#cdd6f4",anchor=(0,1),border=pg.mkPen("#585b70",width=1),fill=pg.mkBrush("#1e1e2eee"))
        self.xc.hide(); self.pc.addItem(self.xc)
        self.lc=pg.TextItem(color="#89b4fa",anchor=(0,0.5),fill=pg.mkBrush("#11111bcc"))
        self.pc.scene().addItem(self.lc)
        self.tc=pg.InfiniteLine(angle=0,movable=False,pen=pg.mkPen("#89b4fa",width=1,style=Qt.DotLine))
        self.pc.addItem(self.tc, ignoreBounds=True)
        # Vertical time indicator line (current)
        self.tm_c=pg.InfiniteLine(angle=90,movable=False,pen=pg.mkPen("#89b4fa",width=1,style=Qt.DotLine))
        self.pc.addItem(self.tm_c, ignoreBounds=True)
        self.pc.scene().sigMouseMoved.connect(self._mc)
        ml.addWidget(self.pc)

        # Dual mode: Voltage plot
        if self.time_mode:
            self.time_axis_v = TimeAxisItem(orientation='bottom')
            self.pv = pg.PlotWidget(axisItems={'bottom': self.time_axis_v})
        else:
            self.pv = pg.PlotWidget()
        self.pv.setMouseTracking(True)
        self.pv.setBackground("#11111b"); self.pv.showGrid(x=True,y=True,alpha=0.1)
        self.pv.setLabel("left","电压 (V)",color="#6c7086"); self.pv.setLabel("bottom","系统时间" if self.time_mode else "时间 (s)",color="#6c7086")
        self.pv.setTitle("电压波形",color="#cdd6f4",size="12pt")
        self._cn_menu(self.pv)
        # Set ViewBox limits to prevent negative values
        self.pv.plotItem.vb.setLimits(xMin=0, yMin=0)
        self.pv.plotItem.vb.enableAutoRange(enable=False)
        if hasattr(self.pv.plotItem.vb, 'autoRangeBtn') and self.pv.plotItem.vb.autoRangeBtn:
            self.pv.plotItem.vb.autoRangeBtn.show()
        self.cv=self.pv.plot(pen=pg.mkPen("#f38ba8",width=2))
        self.vvl=pg.InfiniteLine(90,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.hvl=pg.InfiniteLine(0,movable=False,pen=pg.mkPen("#45475a",style=Qt.DashLine,width=1))
        self.pv.addItem(self.vvl,ignoreBounds=True); self.pv.addItem(self.hvl,ignoreBounds=True)
        self.xvl=pg.TextItem(color="#cdd6f4",anchor=(0,1),border=pg.mkPen("#585b70",width=1),fill=pg.mkBrush("#1e1e2eee"))
        self.xvl.hide(); self.pv.addItem(self.xvl)
        self.lvl=pg.TextItem(color="#f38ba8",anchor=(0,0.5),fill=pg.mkBrush("#11111bcc"))
        self.pv.scene().addItem(self.lvl)
        self.tvl=pg.InfiniteLine(angle=0,movable=False,pen=pg.mkPen("#f38ba8",width=1,style=Qt.DotLine))
        self.pv.addItem(self.tvl, ignoreBounds=True)
        # Vertical time indicator line (voltage)
        self.tm_v=pg.InfiniteLine(angle=90,movable=False,pen=pg.mkPen("#f38ba8",width=1,style=Qt.DotLine))
        self.pv.addItem(self.tm_v, ignoreBounds=True)
        self.pv.scene().sigMouseMoved.connect(self._mv)
        ml.addWidget(self.pv)

        # Time slider with pause button
        slider_row = QHBoxLayout()
        self.btn_pause = QPushButton("⏸")
        self.btn_pause.setFixedSize(30, 28)
        self.btn_pause.setCheckable(True)
        self.btn_pause.setToolTip("暂停/恢复自动滚动")
        self.btn_pause.clicked.connect(self._toggle_pause)
        slider_row.addWidget(self.btn_pause)
        self.slider=QSlider(Qt.Horizontal); self.slider.setRange(0,100); self.slider.setValue(100)
        self.slider.valueChanged.connect(self._on_slider)
        slider_row.addWidget(self.slider)
        ml.addLayout(slider_row)

        # Selection state
        self.sel_active=False; self.sel_start=None; self.sel_rect=None
        self.sel_region=None; self.sel_analysis=None
        self.sel_line=None; self.sel_region_rect=None
        self.analysis_win=None
        self._resizing=None; self._resize_start_x=None; self._resize_orig=None
        
        self.user_scrolling=False; self.scroll_timer=QTimer(); self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(lambda: setattr(self,'user_scrolling',False))

        left_scroll.setWidget(left)
        sp.addWidget(left_scroll); sp.addWidget(mid); lay.addWidget(sp)

    def _sync_vb(self):
        try:
            self.pm_vb2.setGeometry(self.pm.plotItem.vb.sceneBoundingRect())
        except Exception:
            pass

    def _format_tooltip_time(self, rel_sec):
        if self.time_mode == 1 and self.t0_abs:
            dt = self.t0_abs + timedelta(seconds=rel_sec)
            return dt.strftime("%H:%M:%S")
        else:
            return f"{rel_sec:.1f}s"

    def _mm(self, pos):
        if self.pm.sceneBoundingRect().contains(pos):
            mp = self.pm.plotItem.vb.mapSceneToView(pos)
            self.vm.setPos(mp.x()); self.hm.setPos(mp.y())
            if self.ts:
                i = max(0, min(int(mp.x()), len(self.ts) - 1))
                v, c, p = self.vs[i], self.cs[i], self.ps[i]
                t_str = self._format_tooltip_time(mp.x())
                c_str = f"{c/1000:.3f} mA"
                self.xm.setText(f" {t_str}  {v:.3f}V  {c_str}  {p:.3f}mW ")
                self.xm.setPos(mp); self.xm.show()
        else:
            self.xm.hide()

    def _mc(self, pos):
        if self.pc.sceneBoundingRect().contains(pos):
            mp = self.pc.plotItem.vb.mapSceneToView(pos)
            self.vc.setPos(mp.x()); self.hc.setPos(mp.y())
            if self.ts:
                i = max(0, min(int(mp.x()), len(self.ts) - 1))
                v, c, p = self.vs[i], self.cs[i], self.ps[i]
                t_str = self._format_tooltip_time(mp.x())
                c_str = f"{c/1000:.3f} mA"
                self.xc.setText(f" {t_str}  {v:.3f}V  {c_str}  {p:.3f}mW ")
                self.xc.setPos(mp); self.xc.show()
        else:
            self.xc.hide()

    def _mv(self, pos):
        if self.pv.sceneBoundingRect().contains(pos):
            mp = self.pv.plotItem.vb.mapSceneToView(pos)
            self.vvl.setPos(mp.x()); self.hvl.setPos(mp.y())
            if self.ts:
                i = max(0, min(int(mp.x()), len(self.ts) - 1))
                v = self.vs[i]
                t_str = self._format_tooltip_time(mp.x())
                self.xvl.setText(f" {t_str}  {v:.3f}V ")
                self.xvl.setPos(mp); self.xvl.show()
        else:
            self.xvl.hide()

    def _cn_menu(self, pw):
        """设置PlotWidget右键菜单为中文"""
        from PyQt5.QtWidgets import QMenu
        menu = QMenu()
        menu.setStyleSheet("QMenu{background:#1e1e2e;color:#cdd6f4;border:1px solid #313244;}QMenu::item:selected{background:#313244;}")
        menu.addAction("平移模式", lambda: pw.plotItem.vb.setMouseMode(pg.ViewBox.PanMode))
        menu.addAction("框选模式", lambda: pw.plotItem.vb.setMouseMode(pg.ViewBox.RectMode))
        menu.addSeparator()
        menu.addAction("清空选区", self._clear_selection)
        menu.addAction("清空数据", self._clear)
        pw.plotItem.vb.menu = menu

    def _clear_selection(self):
        """清空选区和分析窗口"""
        if self.sel_region_rect:
            plot = self._get_active_plot()
            if plot:
                try: plot.removeItem(self.sel_region_rect)
                except: pass
            self.sel_region_rect = None
        if self.sel_line:
            plot = self._get_active_plot()
            if plot:
                try: plot.removeItem(self.sel_line)
                except: pass
            self.sel_line = None
        self.sel_start = None
        if hasattr(self, 'analysis_win') and self.analysis_win:
            self.analysis_win.close()
        if hasattr(self, 'analysis_mini_btn') and self.analysis_mini_btn:
            self.analysis_mini_btn.close()
            self.analysis_mini_btn = None
        self.statusBar().showMessage("选区已清空")

    def _get_active_plot(self):
        """获取当前活动的绘图控件"""
        if self.pm.isVisible():
            return self.pm
        elif self.pc.isVisible():
            return self.pc
        return None

    def _get_sel_edges(self, plot):
        """Get selection edges in view coordinates"""
        if not self.sel_region_rect: return None, None
        r = self.sel_region_rect.getRegion()
        return r[0], r[1]

    def _near_edge(self, plot, x, threshold=5.0):
        """Check if x is near a selection edge, return 'left', 'right', or None"""
        t0, t1 = self._get_sel_edges(plot)
        if t0 is None: return None
        vr = plot.plotItem.vb.viewRange()[0]
        # Convert pixel threshold to data units
        plot_width = plot.width() - plot.plotItem.vb.width()  # subtract axis width
        if plot_width <= 0: return None
        scale = (vr[1] - vr[0]) / plot_width
        thr = threshold * scale
        if abs(x - t0) < thr: return 'left'
        if abs(x - t1) < thr: return 'right'
        return None

    def mousePressEvent(self, event):
        if event.button()==Qt.LeftButton and (self.btn_region.isChecked() or self.act_region.text()=="选区分析:开"):
            pos=event.pos()
            plot=self._get_active_plot()
            if plot:
                scene_pos = plot.mapFromGlobal(self.mapToGlobal(pos))
                if plot.plotItem.vb.sceneBoundingRect().contains(scene_pos):
                    mp=plot.plotItem.vb.mapSceneToView(scene_pos)
                    # Check if clicking near an existing edge to resize
                    if self.sel_region_rect:
                        edge = self._near_edge(plot, mp.x())
                        if edge:
                            self._resizing = edge
                            self._resize_start_x = mp.x()
                            self._resize_orig = self.sel_region_rect.getRegion()
                            return
                    # Start new selection
                    if self.sel_start is None:
                        self._clear_selection()
                        self.sel_start=mp.x()
                        t_str = self._format_tooltip_time(mp.x())
                        self.statusBar().showMessage(f"已选择起点: {t_str}，请点击终点")
                        self._draw_sel_line(plot, mp.x())
                    else:
                        t0=min(self.sel_start,mp.x()); t1=max(self.sel_start,mp.x())
                        self.sel_start=None
                        self._draw_sel_region(plot, t0,t1)
                        self._show_analysis(t0,t1)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Handle resize of selection region
        if getattr(self, '_resizing', None):
            pos = event.pos()
            plot = self._get_active_plot()
            if plot:
                scene_pos = plot.mapFromGlobal(self.mapToGlobal(pos))
                if plot.plotItem.vb.sceneBoundingRect().contains(scene_pos):
                    mp = plot.plotItem.vb.mapSceneToView(scene_pos)
                    t0, t1 = self._resize_orig
                    if self._resizing == 'left':
                        t0 = min(mp.x(), t1 - 0.1)
                    else:
                        t1 = max(mp.x(), t0 + 0.1)
                    self.sel_region_rect.setRegion([t0, t1])
            # Update cursor based on hover position
        else:
            # Update cursor when hovering near edges
            pos = event.pos()
            plot = self._get_active_plot()
            if plot and self.sel_region_rect:
                scene_pos = plot.mapFromGlobal(self.mapToGlobal(pos))
                if plot.plotItem.vb.sceneBoundingRect().contains(scene_pos):
                    mp = plot.plotItem.vb.mapSceneToView(scene_pos)
                    edge = self._near_edge(plot, mp.x())
                    if edge:
                        self.setCursor(Qt.SizeHorCursor)
                    else:
                        self.setCursor(Qt.ArrowCursor)
                else:
                    self.setCursor(Qt.ArrowCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, '_resizing', None):
            self._resizing = None
            self.setCursor(Qt.ArrowCursor)
            # Update analysis with new region
            if self.sel_region_rect:
                r = self.sel_region_rect.getRegion()
                self._show_analysis(r[0], r[1])
        super().mouseReleaseEvent(event)

    def _draw_sel_line(self, plot, x):
        """Draw start marker line"""
        if self.sel_line:
            try: plot.removeItem(self.sel_line)
            except: pass
        self.sel_line = pg.InfiniteLine(angle=90, movable=False, 
            pen=pg.mkPen(color="#4a9eff", width=2, style=Qt.DashLine))
        plot.addItem(self.sel_line)
        self.sel_line.setPos(x)

    def _draw_sel_region(self, plot, t0, t1):
        """Draw selection region rectangle (resizable)"""
        if self.sel_line:
            try: plot.removeItem(self.sel_line)
            except: pass
            self.sel_line = None
        if self.sel_region_rect:
            try: plot.removeItem(self.sel_region_rect)
            except: pass
        self.sel_region_rect = pg.LinearRegionItem([t0, t1], movable=True,
            brush=pg.mkBrush(74, 158, 255, 50), pen=pg.mkPen(color="#4a9eff", width=1))
        self.sel_region_rect.sigRegionChanged.connect(self._on_sel_region_changed)
        plot.addItem(self.sel_region_rect)

    def _on_sel_region_changed(self):
        """Update analysis when selection region is resized"""
        if self.sel_region_rect is None: return
        r = self.sel_region_rect.getRegion()
        self._show_analysis(r[0], r[1])

    def _show_analysis(self,t0,t1):
        if not self.ts or t1-t0<0.5: 
            self.statusBar().showMessage("选区太小，请重新选择")
            return
        idx=[i for i,t in enumerate(self.ts) if t0<=t<=t1]
        if len(idx)<2:
            self.statusBar().showMessage("选区内数据不足")
            return
        vr=[self.vs[i] for i in idx]; cr=[self.cs[i] for i in idx]; pr=[self.ps[i] for i in idx]
        dt=self.ts[idx[-1]]-self.ts[idx[0]]
        avg_v=sum(vr)/len(vr); avg_c=sum(cr)/len(cr); avg_p=sum(pr)/len(pr)
        charge=sum(cr)/len(cr)*dt/3600*1000
        energy=sum(pr)/len(pr)*dt/3600
        freq=len(idx)/dt if dt>0 else 0

        # Update tab analysis
        c_avg_str = f"{avg_c/1000:.3f} mA"
        c_max_str = f"{max(cr)/1000:.3f} mA"
        c_min_str = f"{min(cr)/1000:.3f} mA"
        self.rv.setText(f"平均电压: {avg_v:.4f} V")
        self.rc.setText(f"平均电流: {c_avg_str}")
        self.rp.setText(f"平均功率: {avg_p:.4f} mW")
        self.rmx.setText(f"最大电流: {c_max_str}")
        self.rmn.setText(f"最小电流: {c_min_str}")
        self.rch.setText(f"电量(μAh): {charge:.4f}")
        self.ren.setText(f"能量(μWh): {energy:.4f}")
        self.rtm.setText(f"时长: {dt:.2f} 秒")
        self.rn.setText(f"采样点数: {len(idx)}")

        # Show floating analysis panel
        self._show_floating_analysis(t0, t1, avg_v, avg_c, avg_p, charge, energy, dt, len(idx), freq)
        t0_str = self._format_tooltip_time(t0)
        t1_str = self._format_tooltip_time(t1)
        self.statusBar().showMessage(f"选区分析: {t0_str} ~ {t1_str} | 平均功率: {avg_p:.1f}mW | 能量: {energy:.2f}μWh")

    def _show_floating_analysis(self, t0, t1, avg_v, avg_c, avg_p, charge, energy, dt, count, freq=0):
        """Show independent analysis panel"""
        if hasattr(self, 'analysis_win') and self.analysis_win:
            self.analysis_win.close()
        if hasattr(self, 'analysis_mini_btn') and self.analysis_mini_btn:
            self.analysis_mini_btn.close()
        
        idx = [i for i, t in enumerate(self.ts) if t0 <= t <= t1]
        cr = [self.cs[i] for i in idx] if idx else [0]
        vr = [self.vs[i] for i in idx] if idx else [0]
        
        self.analysis_win = QMainWindow(self)
        self.analysis_win.setMinimumSize(300, 350)
        self.analysis_win.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.Tool)
        
        central = QWidget()
        self.analysis_win.setCentralWidget(central)
        # Enable dragging on frameless window
        self._drag_pos = None
        self._drag_win_pos = None
        def _press(e):
            if e.button() == Qt.LeftButton:
                self._drag_pos = e.globalPos()
                self._drag_win_pos = self.analysis_win.pos()
        def _move(e):
            if self._drag_pos and self._drag_win_pos:
                delta = e.globalPos() - self._drag_pos
                self.analysis_win.move(self._drag_win_pos + delta)
        def _release(e):
            self._drag_pos = None
            self._drag_win_pos = None
        central.mousePressEvent = _press
        central.mouseMoveEvent = _move
        central.mouseReleaseEvent = _release
        
        is_dark = self.theme_idx != 1
        
        self.region_panel = RegionAnalysisPanel(is_dark=is_dark)
        self.region_panel.update_avg(avg_v, avg_c, avg_p)
        self.region_panel.update_max(max(vr), max(cr))
        self.region_panel.update_min(min(vr), min(cr))
        self.region_panel.update_energy(charge, energy)
        self.region_panel.update_time(dt, freq)
        self.region_panel.screenshot_requested.connect(self._screenshot_region)
        self.region_panel.report_requested.connect(self._generate_report)
        self.region_panel.minimize_requested.connect(self._minimize_analysis)
        self.region_panel.close_requested.connect(self._close_analysis)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.region_panel)
        
        plot = self._get_active_plot()
        if plot:
            mid_x = (t0 + t1) / 2
            y_range = plot.plotItem.vb.viewRange()[1]
            mid_y = (y_range[0] + y_range[1]) / 2
            scene_pos = plot.plotItem.vb.mapViewToScene(pg.Point(mid_x, mid_y))
            global_pos = self.mapToGlobal(scene_pos.toPoint())
            self.analysis_win.move(global_pos.x() + 30, global_pos.y() - 50)
        
        try:
            self._apply_analysis_win_theme()
        except Exception as e:
            logger.warning(f"主题更新失败: {e}")
        self.analysis_win.show()
        self.analysis_win.raise_()
    
    def _minimize_analysis(self):
        """Minimize analysis window to bottom-left corner"""
        if hasattr(self, 'analysis_win') and self.analysis_win:
            self.analysis_win.hide()
            # Create or reuse restore button at bottom-left
            if not hasattr(self, 'analysis_mini_btn') or not self.analysis_mini_btn:
                self.analysis_mini_btn = QPushButton("▲", self)
                self.analysis_mini_btn.setFixedSize(40, 40)
                self.analysis_mini_btn.setStyleSheet("""
                    QPushButton {
                        background: #89b4fa; color: #1e1e2e; border: none;
                        border-radius: 20px; font-size: 16px; font-weight: bold;
                    }
                    QPushButton:hover { background: #74a8fa; }
                """)
                self.analysis_mini_btn.clicked.connect(self._restore_analysis)
            # Position at bottom-left of main window
            self.analysis_mini_btn.move(10, self.height() - 50)
            self.analysis_mini_btn.show()
            self.analysis_mini_btn.raise_()
            self.analysis_mini_btn.setFocus()
    
    def _restore_analysis(self):
        """Restore analysis window from minimized state"""
        if hasattr(self, 'analysis_win') and self.analysis_win:
            self.analysis_win.show()
            self.analysis_win.raise_()
            self.analysis_win.setFocus()
        if hasattr(self, 'analysis_mini_btn') and self.analysis_mini_btn:
            self.analysis_mini_btn.hide()
    
    def _close_analysis(self):
        """Close analysis window and clear selection"""
        if hasattr(self, 'analysis_win') and self.analysis_win:
            self.analysis_win.close()
            self.analysis_win = None
        if hasattr(self, 'analysis_mini_btn') and self.analysis_mini_btn:
            self.analysis_mini_btn.close()
            self.analysis_mini_btn = None
        # Clear selection region from plot
        if self.sel_region_rect:
            plot = self._get_active_plot()
            if plot:
                try: plot.removeItem(self.sel_region_rect)
                except: pass
            self.sel_region_rect = None
        if self.sel_line:
            plot = self._get_active_plot()
            if plot:
                try: plot.removeItem(self.sel_line)
                except: pass
            self.sel_line = None
        self.sel_start = None
        # Sync toggle to off
        if self.btn_region.isChecked():
            self.btn_region.setChecked(False)
            self.act_region.setText("选区分析:关")
            self.statusBar().showMessage("选区分析已关闭")

    # ===== Tab2: Settings =====
    def _init_settings(self, parent):
        # Wrap in scroll area for low resolution
        scroll=QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        content=QWidget()
        lay=QVBoxLayout(content); lay.setSpacing(12); lay.setContentsMargins(16,12,16,12)

        # === 设备模式 ===
        g_mode=QGroupBox("设备模式")
        mode_lay=QHBoxLayout(g_mode); mode_lay.setSpacing(12)
        mode_lay.addWidget(QLabel("工作模式:"))
        self.cb_mode=QComboBox(); self.cb_mode.addItems(["GPIB", "LuatOS串口"])
        self.cb_mode.currentIndexChanged.connect(self._on_device_mode_changed)
        mode_lay.addWidget(self.cb_mode)
        mode_lay.addStretch()
        lay.addWidget(g_mode)

        # === GPIB连接控制 ===
        self.g_gpi=QGroupBox("GPIB连接控制")
        gpi_lay=QGridLayout(self.g_gpi); gpi_lay.setSpacing(8)
        gpi_lay.addWidget(QLabel("电源型号:"),0,0)
        self.cb_power=QComboBox(); self.cb_power.setEditable(True); self.cb_power.addItems(["66309D","66312D","66321D","66332A","66342A"])
        self.cb_power.setCurrentText("663XX")
        gpi_lay.addWidget(self.cb_power,0,1)
        gpi_lay.addWidget(QLabel("GPIB板卡:"),0,2)
        self.spin_board=QSpinBox(); self.spin_board.setRange(0,30); self.spin_board.setValue(0)
        gpi_lay.addWidget(self.spin_board,0,3)
        gpi_lay.addWidget(QLabel("设备地址:"),1,0)
        self.spin_a=QSpinBox(); self.spin_a.setRange(0,30); self.spin_a.setValue(5)
        gpi_lay.addWidget(self.spin_a,1,1)
        self.btn_co=QPushButton("连接设备"); self.btn_co.setObjectName("conn")
        self.btn_co.clicked.connect(self._connect); gpi_lay.addWidget(self.btn_co,1,2)
        # 电流零位校准
        cal_lay = QHBoxLayout()
        self.lb_gpib_offset = QLabel("电流零位: 0.000 mA")
        self.lb_gpib_offset.setStyleSheet("color:#6c7086;font-size:11px")
        cal_lay.addWidget(self.lb_gpib_offset)
        self.btn_zero_cal = QPushButton("零位校准")
        self.btn_zero_cal.setObjectName("test")
        self.btn_zero_cal.setMinimumHeight(22)
        self.btn_zero_cal.clicked.connect(self._calibrate_gpib_zero)
        cal_lay.addWidget(self.btn_zero_cal)
        self.btn_reset_zero = QPushButton("重置")
        self.btn_reset_zero.setObjectName("clear")
        self.btn_reset_zero.setMinimumHeight(22)
        self.btn_reset_zero.clicked.connect(self._reset_gpib_zero)
        cal_lay.addWidget(self.btn_reset_zero)
        gpi_lay.addLayout(cal_lay, 2, 0, 1, 4)
        lay.addWidget(self.g_gpi)

        # === 串口连接控制 ===
        self.g_ser=QGroupBox("USB连接控制")
        ser_lay=QGridLayout(self.g_ser); ser_lay.setSpacing(8)
        ser_lay.addWidget(QLabel("设备:"),0,0)
        self.cb_serial_port=QComboBox()
        self.cb_serial_port.addItem("(扫描USB设备)")
        ser_lay.addWidget(self.cb_serial_port,0,1)
        self.btn_scan=QPushButton("扫描设备"); self.btn_scan.clicked.connect(self._scan_serial)
        ser_lay.addWidget(self.btn_scan,0,2)
        self.btn_ser_co=QPushButton("连接设备"); self.btn_ser_co.setObjectName("conn")
        self.btn_ser_co.clicked.connect(self._connect)
        ser_lay.addWidget(self.btn_ser_co,1,1)
        self.g_ser.hide()
        lay.addWidget(self.g_ser)

        # === Row 1: 设备输出控制 ===
        go=QGroupBox("设备输出控制")
        go_lay=QGridLayout(go); go_lay.setSpacing(8); go_lay.setColumnStretch(1,1); go_lay.setColumnStretch(3,1)
        go_lay.addWidget(QLabel("最大电压(V):"),0,0)
        self.sv=QDoubleSpinBox(); self.sv.setRange(0,5); self.sv.setSingleStep(0.001); self.sv.setValue(4.2)
        go_lay.addWidget(self.sv,0,1)
        go_lay.addWidget(QLabel("最大电流(mA):"),0,2)
        self.sc=QDoubleSpinBox(); self.sc.setRange(0,2000); self.sc.setValue(1000)
        go_lay.addWidget(self.sc,0,3)
        btn_row=QHBoxLayout(); btn_row.setSpacing(8)
        self.btn_on=QPushButton("开启输出"); self.btn_on.setObjectName("on"); self.btn_on.clicked.connect(lambda: self._set_output(True))
        self.btn_off=QPushButton("关闭输出"); self.btn_off.setObjectName("off"); self.btn_off.clicked.connect(lambda: self._set_output(False))
        ba=QPushButton("应用设置"); ba.clicked.connect(self._apply)
        btn_row.addWidget(self.btn_on); btn_row.addWidget(self.btn_off); btn_row.addWidget(ba); btn_row.addStretch()
        go_lay.addLayout(btn_row,1,0,1,4)
        lay.addWidget(go)

        # === Row 2: 显示设置 (两列) ===
        display_row=QHBoxLayout(); display_row.setSpacing(12)

        # 左列：坐标与跟踪
        left_col=QVBoxLayout(); left_col.setSpacing(8)
        g1=QGroupBox("坐标与跟踪")
        g1_lay=QGridLayout(g1); g1_lay.setSpacing(6)
        g1_lay.addWidget(QLabel("坐标模式:"),0,0)
        self.cb_coord=QComboBox(); self.cb_coord.addItems(["自适应坐标","固定最大值坐标","对数坐标"])
        self.cb_coord.currentIndexChanged.connect(lambda i: setattr(self,'coord_mode',i))
        g1_lay.addWidget(self.cb_coord,0,1)
        self.chk_auto=RoundSwitch(); self.chk_auto.setChecked(True)
        self.chk_auto.stateChanged.connect(self._auto_adapt)
        g1_lay.addWidget(self.chk_auto,0,2)
        g1_lay.addWidget(QLabel("跟踪线位置:"),1,0)
        track_row=QHBoxLayout(); track_row.setSpacing(6)
        self.lb_track_left=QLabel("左侧"); self.lb_track_right=QLabel("右侧")
        self.sw_track=RoundSwitch(); self.sw_track.setChecked(self.track_side=="right")
        self.sw_track.stateChanged.connect(lambda s: self._ts("right" if s else "left"))
        track_row.addWidget(self.lb_track_left); track_row.addWidget(self.sw_track); track_row.addWidget(self.lb_track_right)
        track_row.addStretch()
        g1_lay.addLayout(track_row,1,1,1,2)
        left_col.addWidget(g1)

        # 选区分析
        g2=QGroupBox("选区分析")
        g2_lay=QHBoxLayout(g2); g2_lay.setSpacing(8)
        self.btn_region=RoundSwitch()
        self.btn_region.stateChanged.connect(self._toggle_region)
        g2_lay.addWidget(self.btn_region)
        g2_lay.addWidget(QLabel("启用选区分析"))
        g2_lay.addStretch()
        left_col.addWidget(g2)
        left_col.addStretch()
        display_row.addLayout(left_col)

        # 右列：刻度与样式
        right_col=QVBoxLayout(); right_col.setSpacing(8)
        g3=QGroupBox("合并模式刻度")
        g3_lay=QGridLayout(g3); g3_lay.setSpacing(6)
        g3_lay.addWidget(QLabel("电流(mA):"),0,0)
        self.spin_cmin=QDoubleSpinBox(); self.spin_cmin.setRange(-1000,1000); self.spin_cmin.setValue(0); self.spin_cmin.setSingleStep(10)
        g3_lay.addWidget(self.spin_cmin,0,1)
        g3_lay.addWidget(QLabel("~", alignment=Qt.AlignCenter),0,2)
        self.spin_cmax=QDoubleSpinBox(); self.spin_cmax.setRange(1,10000); self.spin_cmax.setValue(350); self.spin_cmax.setSingleStep(10)
        g3_lay.addWidget(self.spin_cmax,0,3)
        g3_lay.addWidget(QLabel("电压(V):"),1,0)
        self.spin_vmin=QDoubleSpinBox(); self.spin_vmin.setRange(-10,10); self.spin_vmin.setValue(0); self.spin_vmin.setSingleStep(0.5)
        g3_lay.addWidget(self.spin_vmin,1,1)
        g3_lay.addWidget(QLabel("~", alignment=Qt.AlignCenter),1,2)
        self.spin_vmax=QDoubleSpinBox(); self.spin_vmax.setRange(0.1,100); self.spin_vmax.setValue(20); self.spin_vmax.setSingleStep(1)
        g3_lay.addWidget(self.spin_vmax,1,3)
        right_col.addWidget(g3)

        g4=QGroupBox("数据与曲线")
        g4_lay=QGridLayout(g4); g4_lay.setSpacing(6)
        g4_lay.addWidget(QLabel("自动保存阈值:"),0,0)
        self.spin_cache=QSpinBox(); self.spin_cache.setRange(10000,1000000); self.spin_cache.setValue(50000); self.spin_cache.setSingleStep(10000)
        g4_lay.addWidget(self.spin_cache,0,1)
        g4_lay.addWidget(QLabel("点"),0,2)
        g4_lay.addWidget(QLabel("线条粗细:"),1,0)
        self.spin_lw=QDoubleSpinBox(); self.spin_lw.setRange(0.5,10); self.spin_lw.setValue(2); self.spin_lw.setSingleStep(0.5); self.spin_lw.setSuffix(" px")
        g4_lay.addWidget(self.spin_lw,1,1)
        g4_lay.addWidget(QLabel("数据字体:"),2,0)
        self.spin_font_size=QSpinBox(); self.spin_font_size.setRange(8,36); self.spin_font_size.setValue(18); self.spin_font_size.setSuffix(" px")
        self.spin_font_size.valueChanged.connect(self._update_data_font_size)
        g4_lay.addWidget(self.spin_font_size,2,1)
        g4_lay.addWidget(QLabel("px"),2,2)
        self.chk_bold=RoundSwitch(); self.chk_bold.setChecked(True)
        self.chk_bold.stateChanged.connect(self._update_data_font_size_bold)
        bold_lay=QHBoxLayout(); bold_lay.setSpacing(6)
        bold_lay.addWidget(self.chk_bold); bold_lay.addWidget(QLabel("加粗")); bold_lay.addStretch()
        g4_lay.addLayout(bold_lay,3,0,1,3)
        right_col.addWidget(g4)
        right_col.addStretch()
        display_row.addLayout(right_col)

        lay.addLayout(display_row)

        # === 时间与采样设置 ===
        g_time=QGroupBox("时间与采样设置")
        g_time_lay=QGridLayout(g_time); g_time_lay.setSpacing(8)
        g_time_lay.addWidget(QLabel("时间轴显示:"),0,0)
        self.cb_time_mode=QComboBox(); self.cb_time_mode.addItems(["相对时间(秒)","系统时间"])
        self.cb_time_mode.currentIndexChanged.connect(self._switch_time_mode)
        g_time_lay.addWidget(self.cb_time_mode,0,1)
        g_time_lay.addWidget(QLabel("采样率(ms):"),0,2)
        g_time_lay.addWidget(self.cb_sample,0,3)
        lay.addWidget(g_time)

        # === 日志设置 ===
        g_log=QGroupBox("日志设置")
        g_log_lay=QGridLayout(g_log); g_log_lay.setSpacing(8)
        g_log_lay.addWidget(QLabel("日志路径:"),0,0)
        self.le_log_path=QLineEdit(log_dir)
        self.le_log_path.setReadOnly(True)
        g_log_lay.addWidget(self.le_log_path,0,1)
        self.btn_open_log=QPushButton("打开日志文件夹"); self.btn_open_log.setObjectName("load")
        self.btn_open_log.clicked.connect(lambda: os.startfile(log_dir))
        g_log_lay.addWidget(self.btn_open_log,0,2)
        g_log_lay.addWidget(QLabel("当前日志:"),1,0)
        self.lb_log_file=QLabel(os.path.basename(log_file))
        self.lb_log_file.setStyleSheet("color:#89b4fa;font-size:12px")
        g_log_lay.addWidget(self.lb_log_file,1,1,1,2)
        lay.addWidget(g_log)

        # === 截图设置 ===
        g_scr=QGroupBox("截图设置")
        g_scr_lay=QGridLayout(g_scr); g_scr_lay.setSpacing(8)
        g_scr_lay.addWidget(QLabel("截图路径:"),0,0)
        self.le_screenshot_path=QLineEdit(screenshot_dir)
        g_scr_lay.addWidget(self.le_screenshot_path,0,1)
        btn_screenshot_dir=QPushButton("浏览..."); btn_screenshot_dir.clicked.connect(self._browse_screenshot)
        g_scr_lay.addWidget(btn_screenshot_dir,0,2)
        btn_open_screenshot=QPushButton("打开截图文件夹"); btn_open_screenshot.setObjectName("load")
        btn_open_screenshot.clicked.connect(lambda: os.startfile(self.le_screenshot_path.text()))
        g_scr_lay.addWidget(btn_open_screenshot,1,1,1,2)
        lay.addWidget(g_scr)

        lay.addStretch()
        
        scroll.setWidget(content)
        parent_layout=QVBoxLayout(parent)
        parent_layout.setContentsMargins(0,0,0,0)
        parent_layout.addWidget(scroll)

    def _on_device_mode_changed(self, idx):
        modes = ["gpib", "luatos"]
        self.device_mode = modes[idx]
        self.g_gpi.setVisible(self.device_mode == "gpib")
        self.g_ser.setVisible(self.device_mode == "luatos")
        self._update_connect_btn()
        self._update_chart_axis_labels()
        self.statusBar().showMessage(f"设备模式: {'GPIB' if self.device_mode=='gpib' else 'LuatOS串口'}")

    def _update_chart_axis_labels(self):
        """Refresh Y-axis labels for current unit (mA/uA) based on device mode"""
        label = self._curr_axis_label()
        is_dark = self.theme_idx != 1
        self.pm.setLabel("left", label, color="#89b4fa" if is_dark else "#1e66f5")
        label_color = "#6c7086" if is_dark else "#7c7f93"
        self.pc.setLabel("left", label, color=label_color)

    def _update_connect_btn(self):
        if self.device_mode == "gpib":
            connected = gpib_ud >= 0
            self.btn_co.setText("断开设备" if connected else "连接设备")
        else:
            connected = _libusb_dev is not None
            self.btn_ser_co.setText("断开设备" if connected else "连接设备")

    def _scan_serial(self):
        ports = s_scan()
        self.cb_serial_port.clear()
        if ports:
            self.cb_serial_port.addItems(ports)
            self.statusBar().showMessage(f"发现 {len(ports)} 个 USB 设备")
        else:
            self.cb_serial_port.addItem("(无设备)")
            self.statusBar().showMessage("未发现 IotPower-cc 设备")

    def _set_output(self, on):
        cmd = "OUTP ON" if on else "OUTP OFF"
        if self.device_mode == "gpib":
            g_send(cmd)
        elif self.device_mode == "luatos":
            s_send(cmd)

    def _auto_adapt(self):
        if self.chk_auto.isChecked():
            self.pm.plotItem.vb.enableAutoRange(axis=self.pm.plotItem.vb.YAxis)
            self.pm_vb2.enableAutoRange(axis=self.pm_vb2.YAxis)
            self.pm.plotItem.vb.enableAutoRange(axis=self.pm.plotItem.vb.XAxis, enable=False)
            self.pm.plotItem.vb.setXRange(0, max(self.ts[-1] if self.ts else 10, 10), padding=0)
        else:
            self.pm.plotItem.vb.enableAutoRange(axis=self.pm.plotItem.vb.YAxis, enable=False)
            self.pm_vb2.enableAutoRange(axis=self.pm_vb2.YAxis, enable=False)
            if self.cs:
                cs_disp = [c * 0.001 for c in self.cs]
                ym = max(max(cs_disp) * 1.1, 0.01)
                self.pm.plotItem.vb.setYRange(0, ym, padding=0)
            if self.vs:
                vmin = min(self.vs); vmax = max(self.vs)
                if vmax > vmin:
                    self.pm_vb2.setYRange(vmin * 0.9, vmax * 1.1, padding=0)
                else:
                    self.pm_vb2.setYRange(0, max(vmax * 1.1, 0.1), padding=0)

    def _ts(self, s):
        self.track_side=s
        self.lb_track_left.setStyleSheet(f"color:{'#a6e3a1' if s=='left' else '#6c7086'};font-weight:bold")
        self.lb_track_right.setStyleSheet(f"color:{'#a6e3a1' if s=='right' else '#6c7086'};font-weight:bold")

    def _toggle_region(self):
        if self.btn_region.isChecked():
            self.act_region.setText("选区分析:开")
            self.statusBar().showMessage("选区分析已开启：左键点击第1个点设置起点，再点击第2个点设置终点")
            # Auto-analyze existing selection if present
            if self.sel_region_rect:
                r = self.sel_region_rect.getRegion()
                self._show_analysis(r[0], r[1])
        else:
            self.act_region.setText("选区分析:关")
            self.sel_start=None
            # Close analysis window
            if hasattr(self, 'analysis_win') and self.analysis_win:
                self.analysis_win.close()
                self.analysis_win = None
            self.statusBar().showMessage("选区分析已关闭")

    def _toggle_region_tb(self):
        if self.act_region.text()=="选区分析:关":
            self.act_region.setText("选区分析:开")
            self.btn_region.setChecked(True)
            # Auto-analyze existing selection if present
            if self.sel_region_rect:
                r = self.sel_region_rect.getRegion()
                self._show_analysis(r[0], r[1])
        else:
            self.act_region.setText("选区分析:关")
            self.btn_region.setChecked(False)
            # Close analysis window
            if hasattr(self, 'analysis_win') and self.analysis_win:
                self.analysis_win.close()
                self.analysis_win = None

    def _mode(self):
        try:
            if self.act_mode.text()=="切换到合并模式":
                self.act_mode.setText("切换到双波形模式")
                self.pc.hide(); self.pv.hide(); self.pm.show()
                self.chk_auto.setChecked(False)
            else:
                self.act_mode.setText("切换到合并模式")
                self.pm.hide(); self.pc.show(); self.pv.show()
            # Refresh display with current data
            self._ui()
        except Exception as e:
            logger.error(f"切换模式异常: {e}")

    def _screenshot_region(self):
        """Screenshot the current plot with selection region"""
        plot = self._get_active_plot()
        if not plot: return
        # Capture the plot widget
        pixmap = plot.grab()
        path = self.le_screenshot_path.text() if hasattr(self, 'le_screenshot_path') else screenshot_dir
        os.makedirs(path, exist_ok=True)
        fname = os.path.join(path, f"region_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        pixmap.save(fname, "PNG")
        QMessageBox.information(self, "截图成功", f"选区截图已保存到:\n{fname}")
        logger.info(f"选区截图: {fname}")

    def _generate_report(self):
        """Generate test report PDF"""
        if not self.ts or not self.sel_region_rect:
            QMessageBox.warning(self, "提示", "请先选择分析区域")
            return
        
        analysis_was_visible = False
        if hasattr(self, 'analysis_win') and self.analysis_win and self.analysis_win.isVisible():
            analysis_was_visible = True
            self.analysis_win.hide()
        
        # Load saved settings
        s = QSettings("PG-Power", "report")
        saved_products = s.value("products", [], type=list)
        saved_voltages = s.value("voltages", ["3.7"], type=list)
        saved_capacities = s.value("capacities", ["500"], type=list)
        
        # Create dialog
        from PyQt5.QtWidgets import QDialog, QComboBox as CmB
        dlg = QDialog(self)
        dlg.setWindowTitle("生成测试报告")
        dlg.setMinimumWidth(400)
        is_dark = self.theme_idx != 1
        if is_dark:
            dlg.setStyleSheet("""
                QDialog { background: #1e1e2e; color: #cdd6f4; }
                QLabel { color: #bac2de; }
                QComboBox, QLineEdit { background: #11111b; color: #cdd6f4; border: 1px solid #313244;
                    border-radius: 4px; padding: 6px 10px; }
                QPushButton { background: #313244; color: #cdd6f4; border: 1px solid #45475a;
                    border-radius: 6px; padding: 8px 16px; font-weight: bold; }
                QPushButton:hover { background: #45475a; }
                QPushButton#ok { background: #89b4fa; color: #1e1e2e; border-color: #89b4fa; }
            """)
        else:
            dlg.setStyleSheet("""
                QDialog { background: #eff1f5; color: #4c4f69; }
                QLabel { color: #5c5f77; }
                QComboBox, QLineEdit { background: #eff1f5; color: #4c4f69; border: 1px solid #ccd0da;
                    border-radius: 4px; padding: 6px 10px; }
                QPushButton { background: #ccd0da; color: #4c4f69; border: 1px solid #bcc0cc;
                    border-radius: 6px; padding: 8px 16px; font-weight: bold; }
                QPushButton:hover { background: #bcc0cc; }
                QPushButton#ok { background: #1e66f5; color: #ffffff; border-color: #1e66f5; }
            """)
        layout = QGridLayout(dlg)
        
        layout.addWidget(QLabel("被测产品名称:"), 0, 0)
        product_input = CmB() if saved_products else QLineEdit()
        if isinstance(product_input, CmB):
            product_input.setEditable(True)
            product_input.addItems(saved_products)
            product_input.setCurrentText(saved_products[0] if saved_products else "")
        else:
            product_input.setPlaceholderText("输入产品名称")
        layout.addWidget(product_input, 0, 1)
        
        layout.addWidget(QLabel("电池额定电压 (V):"), 1, 0)
        volt_input = CmB() if saved_voltages else QLineEdit()
        if isinstance(volt_input, CmB):
            volt_input.setEditable(True)
            volt_input.addItems(saved_voltages)
            volt_input.setCurrentText(saved_voltages[0] if saved_voltages else "3.7")
        else:
            volt_input.setText("3.7")
        layout.addWidget(volt_input, 1, 1)
        
        layout.addWidget(QLabel("电池总电量 (mAh):"), 2, 0)
        cap_input = CmB() if saved_capacities else QLineEdit()
        if isinstance(cap_input, CmB):
            cap_input.setEditable(True)
            cap_input.addItems(saved_capacities)
            cap_input.setCurrentText(saved_capacities[0] if saved_capacities else "500")
        else:
            cap_input.setText("500")
        layout.addWidget(cap_input, 2, 1)
        
        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cancel)
        btn_ok = QPushButton("确认生成")
        btn_ok.setObjectName("ok")
        btn_ok.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row, 3, 0, 1, 2)
        
        if dlg.exec_() != QDialog.Accepted:
            if analysis_was_visible: self.analysis_win.show()
            return
        
        product_name = product_input.currentText() if isinstance(product_input, CmB) else product_input.text()
        battery_v = float(volt_input.currentText() if isinstance(volt_input, CmB) else volt_input.text())
        battery_mah = float(cap_input.currentText() if isinstance(cap_input, CmB) else cap_input.text())
        
        # Save settings
        if isinstance(product_input, CmB):
            products = [product_input.itemText(i) for i in range(product_input.count())]
            if product_name and product_name not in products:
                products.insert(0, product_name)
            s.setValue("products", products[:20])
        if isinstance(volt_input, CmB):
            voltages = [volt_input.itemText(i) for i in range(volt_input.count())]
            if str(battery_v) not in voltages:
                voltages.insert(0, str(battery_v))
            s.setValue("voltages", voltages[:10])
        if isinstance(cap_input, CmB):
            caps = [cap_input.itemText(i) for i in range(cap_input.count())]
            if str(battery_mah) not in caps:
                caps.insert(0, str(battery_mah))
            s.setValue("capacities", caps[:10])
        
        # Generate report
        self._do_generate_report(product_name, battery_v, battery_mah)
        if analysis_was_visible: self.analysis_win.show()

    def _do_generate_report(self, product_name, battery_v, battery_mah):
        """Generate PDF report using HTML layout for clean formatting"""
        if not self.sel_region_rect: return
        r = self.sel_region_rect.getRegion()
        t0, t1 = r[0], r[1]
        idx = [i for i, t in enumerate(self.ts) if t0 <= t <= t1]
        if len(idx) < 2:
            QMessageBox.warning(self, "提示", "选区内数据不足")
            return

        vr = [self.vs[i] for i in idx]
        cr = [self.cs[i] for i in idx]
        pr = [self.ps[i] for i in idx]

        dt = self.ts[idx[-1]] - self.ts[idx[0]]
        avg_v = sum(vr) / len(vr)
        avg_c = sum(cr) / len(cr)
        avg_p = avg_v * avg_c
        min_v = min(vr); min_c = min(cr)
        max_v = max(vr); max_c = max(cr)
        min_p = min_v * min_c
        max_p = max_v * max_c

        charge_uah = avg_c * dt / 3600 * 1000
        energy_uwh = avg_p * dt / 3600 * 1000

        charge_mah = charge_uah / 1000
        energy_mwh = energy_uwh / 1000

        time_ratio = 86400 / dt if dt > 0 else 0
        e_1d_mah = charge_mah * time_ratio
        e_1d_mwh = energy_mwh * time_ratio
        e_30d_mah = e_1d_mah * 30
        e_30d_mwh = e_1d_mwh * 30

        if e_1d_mah > 0:
            est_hours = battery_mah / e_1d_mah * 24
            est_int_days = int(est_hours / 24)
            est_int_hours = int(est_hours - est_int_days * 24)
        else:
            est_int_days = 0; est_int_hours = 0

        h = int(dt // 3600); mi = int((dt % 3600) // 60); s = dt % 60
        dur = f"{h:02d}:{mi:02d}:{s:06.3f}"
        gen_time = datetime.now().strftime('%Y/%m/%d %H:%M:%S')

        fname, _ = QFileDialog.getSaveFileName(self, "保存报告",
            f"{product_name}_power_report.pdf", "PDF (*.pdf)")
        if not fname: return

        from PyQt5.QtPrintSupport import QPrinter
        from PyQt5.QtGui import QTextDocument
        
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 18mm 15mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: "Microsoft YaHei", "SimHei", "Arial", sans-serif; color: #1a1a1a; margin: 0; padding: 0; line-height: 1.6; }}

/* === Header === */
.header {{ text-align: center; padding: 24pt 0 12pt 0; border-bottom: 3pt solid #2563eb; margin-bottom: 18pt; }}
.header h1 {{ font-size: 36pt; font-weight: 700; margin: 0 0 4pt 0; color: #2563eb; letter-spacing: 3pt; }}
.header .ver {{ font-size: 11pt; color: #6b7280; margin: 0 0 6pt 0; }}
.header h2 {{ font-size: 22pt; font-weight: 600; margin: 0; color: #111827; }}

/* === Device Info === */
.device-info {{ background: #f0f5ff; border-left: 4pt solid #2563eb; padding: 10pt 16pt; margin: 0 0 18pt 0; border-radius: 0 4pt 4pt 0; }}
.device-info .label {{ font-size: 12pt; color: #6b7280; }}
.device-info .value {{ font-size: 16pt; font-weight: 600; color: #111827; }}

/* === Section Title === */
.sec-title {{ font-size: 16pt; font-weight: 700; color: #2563eb; margin: 20pt 0 10pt 0; padding: 6pt 10pt; background: #eff6ff; border-left: 3pt solid #2563eb; border-radius: 0 4pt 4pt 0; }}

/* === Data Table === */
table {{ width: 100%; border-collapse: collapse; margin: 8pt 0 16pt 0; font-size: 13pt; }}
th {{ background: #1e40af; color: #ffffff; font-weight: 600; padding: 10pt 14pt; text-align: center; font-size: 13pt; border: 1pt solid #1e3a8a; }}
td {{ padding: 10pt 14pt; text-align: center; font-size: 13pt; border: 1pt solid #d1d5db; }}
tr:nth-child(even) td {{ background: #f9fafb; }}
tr:hover td {{ background: #eff6ff; }}
td.left {{ text-align: left; font-weight: 600; color: #374151; }}
td.right {{ text-align: right; font-variant-numeric: tabular-nums; color: #111827; }}

/* === Estimate Box === */
.est-box {{ background: #ecfdf5; border: 1.5pt solid #6ee7b7; border-radius: 6pt; padding: 16pt 20pt; margin: 16pt 0; }}
.est-box .est-title {{ font-size: 16pt; font-weight: 700; color: #065f46; margin: 0 0 8pt 0; }}
.est-box .est-value {{ font-size: 20pt; font-weight: 700; color: #047857; margin: 4pt 0; }}

/* === Footer === */
.footer {{ border-top: 2pt solid #d1d5db; padding-top: 10pt; margin-top: 20pt; }}
.footer table {{ margin: 0; font-size: 11pt; }}
.footer td {{ border: none; padding: 4pt 0; color: #6b7280; font-size: 11pt; }}
.footer td:first-child {{ text-align: left; width: 130pt; }}
.footer td:last-child {{ text-align: left; }}
</style></head><body>

<div class="header">
  <h1>PG-Power</h1>
  <div class="ver">软件版本：v{REPORT_VERSION}</div>
  <h2>功耗测试报告</h2>
</div>

<div class="device-info">
  <span class="label">被测设备：</span><span class="value">{product_name}</span>
</div>

<div class="sec-title">一、测量数据</div>
<table>
  <tr><th>测试项</th><th>最小值</th><th>平均值</th><th>最大值</th></tr>
  <tr><td class="left">电流 (mA)</td><td class="right">{min_c:.3f}</td><td class="right">{avg_c:.3f}</td><td class="right">{max_c:.3f}</td></tr>
  <tr><td class="left">电压 (V)</td><td class="right">{min_v:.3f}</td><td class="right">{avg_v:.3f}</td><td class="right">{max_v:.3f}</td></tr>
  <tr><td class="left">功率 (mW)</td><td class="right">{min_p:.3f}</td><td class="right">{avg_p:.3f}</td><td class="right">{max_p:.3f}</td></tr>
</table>

<div class="sec-title">二、能量累计</div>
<table>
  <tr><th>项目</th><th>本次测试</th><th>1 天</th><th>30 天</th></tr>
  <tr><td class="left">电量</td><td class="right">{charge_uah:.3f} μAh</td><td class="right">{e_1d_mah:.3f} mAh</td><td class="right">{e_30d_mah:.3f} mAh</td></tr>
  <tr><td class="left">能量</td><td class="right">{energy_uwh:.3f} μWh</td><td class="right">{e_1d_mwh:.3f} mWh</td><td class="right">{e_30d_mwh:.3f} mWh</td></tr>
</table>

<div class="sec-title">三、电池参数与预估续航</div>
<table>
  <tr><th>参数</th><th>规格</th></tr>
  <tr><td class="left">电池额定电压</td><td class="right">{battery_v} V</td></tr>
  <tr><td class="left">电池额定容量</td><td class="right">{battery_mah} mAh</td></tr>
</table>

<div class="est-box">
  <div class="est-title">预估续航</div>
  <div class="est-value">预计可用 {est_int_days} 天 {est_int_hours} 小时</div>
</div>

<div class="footer">
  <table>
    <tr><td>报告测试时长</td><td>{dur}</td></tr>
    <tr><td>报告生成时间</td><td>{gen_time}</td></tr>
  </table>
</div>

</body></html>"""
        
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(fname)
        printer.setPageSize(QPrinter.A4)
        
        doc = QTextDocument()
        doc.setHtml(html)
        doc.print_(printer)
        
        QMessageBox.information(self, "生成成功", f"报告已保存:\n{fname}")
        logger.info(f"报告: {fname}")
        os.startfile(fname)

    # ===== Tab3: Analysis =====
    def _init_analysis(self, parent):
        lay=QVBoxLayout(parent)
        hint=QLabel("在波形图上右键拖动选取区域，此处显示分析结果")
        hint.setStyleSheet("color:#6c7086;font-size:12px;padding:8px"); lay.addWidget(hint)
        self.analysis_hint = hint
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
        bs=QPushButton("发送到设备"); bs.clicked.connect(self._send_script); bl.addWidget(bs)
        bc=QPushButton("清空日志"); bc.clicked.connect(lambda:self.le.clear()); bl.addWidget(bc)
        lay.addLayout(bl)
        sp=QSplitter(Qt.Vertical)
        self.se=QTextEdit()
        self.se.setPlaceholderText("-- Lua 脚本\n-- GPIB 操作:\ng_send('VOLT 4.2')\nlocal v = g_qry('MEAS:VOLT?')\nprint(v)\n\n-- 串口操作 (LuatOS):\ns_send('STATUS?')\nlocal resp = s_qry('STATUS?')\nprint(resp)")
        sp.addWidget(self.se); self.le=QTextEdit(); self.le.setReadOnly(True); self.le.setPlaceholderText("日志...")
        sp.addWidget(self.le); lay.addWidget(sp)

    # ===== Actions =====
    def _connect(self):
        if self.device_mode == "gpib":
            self._connect_gpib()
        else:
            self._connect_serial()

    def _quick_connect(self):
        """快速连接按钮：根据下拉框选择设备类型"""
        mode = self.cb_quick_type.currentText()
        if mode.startswith("GPIB"):
            # 同步到settings页面的模式选择
            self.cb_mode.setCurrentIndex(0)
            self._on_device_mode_changed(0)
            self._connect_gpib()
            # 更新按钮状态
            self.btn_quick_conn.setText("断开" if gpib_ud >= 0 else "连接")
        else:
            self.cb_mode.setCurrentIndex(1)
            self._on_device_mode_changed(1)
            self._connect_serial()
            self.btn_quick_conn.setText("断开" if _libusb_dev else "连接")

    def _connect_gpib(self):
        if not GPIB_OK: QMessageBox.warning(self,"提示","GPIB驱动未加载"); return
        board=self.spin_board.value(); addr=self.spin_a.value()
        if gpib_ud>=0: g_close(); self.btn_co.setText("连接设备"); self.btn_quick_conn.setText("连接"); self.statusBar().showMessage("已断开")
        elif g_open(board,addr): self.btn_co.setText("断开设备"); self.btn_quick_conn.setText("断开"); self.statusBar().showMessage(f"已连接 (板卡{board} 地址{addr})")
        else: QMessageBox.critical(self,"失败","连接失败")

    def _connect_serial(self):
        if _libusb_dev:
            s_close()
            self.btn_ser_co.setText("连接设备")
            self.btn_quick_conn.setText("连接")
            self.statusBar().showMessage("USB设备已断开")
        elif s_open():
            self.btn_ser_co.setText("断开设备")
            self.btn_quick_conn.setText("断开")
            self.statusBar().showMessage(f"IotPower-cc 已连接")
        else:
            QMessageBox.critical(self, "失败", "未找到 IotPower-cc 设备，请确认设备已连接")

    def _calibrate_gpib_zero(self):
        """GPIB电流零位校准：空载时测量偏置电流"""
        global _gpib_current_offset
        if not GPIB_OK or gpib_ud < 0:
            QMessageBox.warning(self, "提示", "请先连接GPIB设备")
            return
        ret = QMessageBox.question(self, "零位校准",
            "请确保输出已关闭(OUTP OFF)且负载已断开，\n"
            "然后点击「是」开始测量零位偏置电流。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        samples = []
        for i in range(10):
            cs = g_qry("MEAS:CURR?")
            if cs:
                try:
                    samples.append(float(cs) * 1000)  # A→mA
                except:
                    pass
            time.sleep(0.05)
        if samples:
            offset = sum(samples) / len(samples)
            _gpib_current_offset = round(offset, 4)
            self.lb_gpib_offset.setText(f"电流零位: {_gpib_current_offset:.4f} mA")
            logger.info(f"[GPIB-ZERO] 零位校准完成: {_gpib_current_offset:.4f} mA (共{len(samples)}个样本)")
            QMessageBox.information(self, "完成",
                f"零位校准完成\n偏置电流: {_gpib_current_offset:.4f} mA\n"
                f"后续测量将自动减去该值")
        else:
            QMessageBox.warning(self, "失败", "未能读取到电流数据")

    def _reset_gpib_zero(self):
        """重置GPIB电流零位偏移"""
        global _gpib_current_offset
        _gpib_current_offset = 0.0
        self.lb_gpib_offset.setText("电流零位: 0.0000 mA")
        logger.info("[GPIB-ZERO] 零位偏移已重置为0")
        QMessageBox.information(self, "已重置", "电流零位偏移已清除")

    def _start(self):
        if not self.test_mode:
            if self.device_mode == "gpib" and (not GPIB_OK or gpib_ud < 0):
                QMessageBox.warning(self, "提示", "请先连接GPIB设备或启用测试模式"); return
            elif self.device_mode == "luatos" and (not USB_OK or not _libusb_dev):
                QMessageBox.warning(self, "提示", "请先连接 USB 设备或启用测试模式"); return
        if not self.collecting:
            self.ts.clear(); self.vs.clear(); self.cs.clear(); self.ps.clear()
            self.e_mwh=0; self.max_c=0; self.min_c=float("inf"); self.save_count=0
            self.collecting=True; self.t0=time.time(); self.t0_abs=datetime.now(); self.phi=0; self.pe=0
            # Set time axis start time
            if self.time_mode:
                if hasattr(self, 'time_axis_m'): self.time_axis_m.setStartTime(self.t0_abs)
                if hasattr(self, 'time_axis_c'): self.time_axis_c.setStartTime(self.t0_abs)
                if hasattr(self, 'time_axis_v'): self.time_axis_v.setStartTime(self.t0_abs)
            # Reset view to origin
            for pw in [self.pm, self.pc, self.pv]:
                pw.plotItem.vb.setXRange(0, 60, padding=0)
            logger.info(f"采集启动: mode={self.device_mode}, USB_OK={USB_OK}, dev={_libusb_dev}")
            threading.Thread(target=self._loop,daemon=True).start()
            self.statusBar().showMessage("采集中...")
            logger.info("采集已启动")

    def _stop(self):
        self.collecting=False; self.statusBar().showMessage("已停止")
        logger.info("采集已停止")

    def _toggle_test(self):
        if self.btn_te.text()=="测试模式":
            self.test_mode=True; self.btn_te.setText("退出测试"); self._clear(force=True); self._start()
        else: self.test_mode=False; self.btn_te.setText("测试模式"); self._stop()

    def _loop(self):
        loop_cnt = 0
        sample_cnt = 0
        logger.info("_loop线程已启动")
        while self.collecting:
            try:
                if self.test_mode:
                    ph=self.phases[self.phi]; self.pe+=1
                    if self.pe>=ph["d"] and self.phi<len(self.phases)-1: self.phi+=1; self.pe=0
                    v=ph["v"]+random.uniform(-0.02,0.02); c=(ph["c"]+random.gauss(0,ph["s"]))*1000
                elif self.device_mode == "luatos":
                    sample = s_readline()
                    if sample is not None:
                        v_raw, c_raw = sample
                        # Calibration: v_raw~16985→4.2V, c_raw~688→69.5uA
                        # v = v_raw / 4044 (V)
                        # c = c_raw / 9900 (mA) = c_raw / 9.9 (uA)
                        v = v_raw / 4044.0
                        c = c_raw / 9.9  # uA
                        sample_cnt += 1
                        if sample_cnt <= 3 or sample_cnt % 200 == 0:
                            logger.info(f"#{sample_cnt} v_raw={v_raw} c_raw={c_raw} → V={v:.3f} C={c:.1f}uA")
                    else:
                        loop_cnt += 1
                        if loop_cnt % 200 == 0:
                            logger.warning(f"无数据 {loop_cnt}次")
                        continue
                else:
                    vs=g_qry("MEAS:VOLT?"); cs=g_qry("MEAS:CURR?")
                    v=float(vs) if vs else 0; c=float(cs)*1000000 if cs else 0  # A → µA
                    c -= _gpib_current_offset * 1000  # 减去零位偏置（mA→µA）
                t=time.time()-self.t0; p=v*c/1000.0  # V * µA / 1000 = mW
                with lock:
                    self.ts.append(t); self.vs.append(v); self.cs.append(c); self.ps.append(p)
                    self.max_c=max(self.max_c,c); self.min_c=min(self.min_c,c)
                    if len(self.ts)>1: self.e_mwh+=p*(self.ts[-1]-self.ts[-2])/3600
                    self.save_count+=1
                    # Auto save
                    if self.act_save_auto.isChecked() and self.save_count>=self.spin_cache.value():
                        self._auto_save(); self.save_count=0
            except Exception as e: logger.error(f"异常: {e}")
            time.sleep(self.sample_interval/1000.0)

    def _auto_save(self):
        try:
            path=os.path.join(log_dir, f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            if self.time_mode and self.t0_abs:
                time_header = "系统时间"
                time_fmt = "%Y/%m/%d %H:%M:%S.%f"
            else:
                time_header = "时间(s)"
                time_fmt = None
            with open(path,"w",newline="",encoding="utf-8") as f:
                w=csv.writer(f); w.writerow([time_header,"电压(V)","电流(uA)","功率(mW)"])
                for t,v,c,p in zip(self.ts,self.vs,self.cs,self.ps):
                    if time_fmt:
                        dt = self.t0_abs + timedelta(seconds=t)
                        ts = dt.strftime(time_fmt)[:-3]
                    else:
                        ts = f"{t:.4f}"
                    w.writerow([ts,f"{v:.4f}",f"{c:.4f}",f"{p:.4f}"])
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

        # Always display in mA (internal µA ÷ 1000)
        cs_disp = [c * 0.001 for c in self.cs]

        # Update plots based on mode
        lw=self.spin_lw.value()
        if is_merged:
            self.cm_c.setData(self.ts, cs_disp)
            self.cm_c.setPen(pg.mkPen("#89b4fa",width=lw))
            self.cm_c.setBrush(pg.mkBrush(137,180,250,40))
            self.cm_v.setData(self.ts,self.vs)
            self.cm_v.setPen(pg.mkPen("#f38ba8",width=lw))
            # Auto scroll for merged
            if self.ts[-1]>60 and not self.user_scrolling:
                vb=self.pm.plotItem.vb; vr=vb.viewRange()[0]
                if self.ts[-1] >= vr[1]-5:
                    x_min=max(0, self.ts[-1]-60)
                    vb.setXRange(x_min,self.ts[-1],padding=0)
        else:
            self.cc.setData(self.ts, cs_disp)
            self.cc.setPen(pg.mkPen("#89b4fa",width=lw))
            self.cv.setData(self.ts,self.vs)
            self.cv.setPen(pg.mkPen("#f38ba8",width=lw))
            # Auto scroll for dual
            if self.ts[-1]>60 and not self.user_scrolling:
                vb=self.pc.plotItem.vb; vr=vb.viewRange()[0]
                if self.ts[-1] >= vr[1]-5:
                    x_min=max(0, self.ts[-1]-60)
                    vb.setXRange(x_min,self.ts[-1],padding=0)
                    self.pv.plotItem.vb.setXRange(x_min,self.ts[-1],padding=0)
            # Y range for dual (only when not auto-adapt)
            if not self.chk_auto.isChecked():
                if self.cs:
                    ym=max(max(cs_disp)*1.1,0.01)
                    if self.coord_mode==0: self.pc.plotItem.vb.setYRange(0,ym,padding=0)
                    elif self.coord_mode==1: self.pc.plotItem.vb.setYRange(0,200,padding=0)
                if self.vs:
                    ymn=max(0,min(self.vs)*0.9); ymx=max(self.vs)*1.1
                    if self.coord_mode==0: self.pv.plotItem.vb.setYRange(ymn,ymx,padding=0)
                    elif self.coord_mode==1: self.pv.plotItem.vb.setYRange(0,6,padding=0)
            else:
                # Auto-adapt Y range based on data
                if self.cs:
                    ym=max(max(cs_disp)*1.1,0.01)
                    self.pc.plotItem.vb.setYRange(0,ym,padding=0)
                if self.vs:
                    ymn=max(0,min(self.vs)*0.9); ymx=max(self.vs)*1.1
                    self.pv.plotItem.vb.setYRange(ymn,ymx,padding=0)

        # Labels
        lc_disp = lc * 0.001  # µA → mA
        if is_merged:
            # Current: label at LEFT axis edge (in scene coordinates)
            self.tc_m.setPos(lc_disp)
            scene_pos = self.pm.plotItem.vb.mapViewToScene(pg.Point(0, lc_disp))
            c_label = f"{lc/1000:.3f} mA"
            self.lmc.setText(f" {c_label} ")
            self.lmc.setPos(scene_pos.x(), scene_pos.y())
            self.lmc.show()
            # Voltage: label at curve tip (in scene coordinates)
            main_y_range = self.pm.plotItem.vb.viewRange()[1]
            vb2_y_range = self.pm_vb2.viewRange()[1]
            if vb2_y_range[1] > vb2_y_range[0]:
                v_ratio = (lv - vb2_y_range[0]) / (vb2_y_range[1] - vb2_y_range[0])
                v_y = main_y_range[0] + v_ratio * (main_y_range[1] - main_y_range[0])
            else:
                v_y = (main_y_range[0] + main_y_range[1]) / 2
            self.tvl_m.setPos(v_y)
            scene_pos_v = self.pm.plotItem.vb.mapViewToScene(pg.Point(self.ts[-1], v_y))
            self.lmv.setText(f" {lv:.3f}V ")
            self.lmv.setPos(scene_pos_v.x(), scene_pos_v.y())
            self.lmv.show()
            # Vertical time indicator line (merged)
            self.tm_m.setPos(self.ts[-1])
        else:
            # Current: label at LEFT axis edge (in scene coordinates)
            self.tc.setPos(lc_disp)
            scene_pos_c = self.pc.plotItem.vb.mapViewToScene(pg.Point(0, lc_disp))
            c_label = f"{lc/1000:.3f} mA"
            self.lc.setText(f" {c_label} ")
            self.lc.setPos(scene_pos_c.x(), scene_pos_c.y())
            self.lc.show()
            # Voltage: label at LEFT axis edge (in scene coordinates)
            self.tvl.setPos(lv)
            scene_pos_v2 = self.pv.plotItem.vb.mapViewToScene(pg.Point(0, lv))
            self.lvl.setText(f" {lv:.3f}V ")
            self.lvl.setPos(scene_pos_v2.x(), scene_pos_v2.y())
            # Vertical time indicator lines (dual)
            self.tm_c.setPos(self.ts[-1])
            self.tm_v.setPos(self.ts[-1])
            self.lvl.show()

        # Stats - instant or average
        if self.display_mode=="instant":
            c_str = f"{lc/1000:.3f} mA"
            self.lb_ic.setText(c_str); self.lb_iv.setText(f"{lv:.4f} V"); self.lb_ip.setText(f"{lp:.3f} mW")
        else:
            # Sliding average (last 100 points)
            n=min(100,len(self.cs))
            avg_c=sum(self.cs[-n:])/n; avg_v=sum(self.vs[-n:])/n; avg_p=sum(self.ps[-n:])/n
            c_str = f"{avg_c/1000:.3f} mA"
            self.lb_ic.setText(c_str); self.lb_iv.setText(f"{avg_v:.4f} V"); self.lb_ip.setText(f"{avg_p:.3f} mW")

        # Global stats
        ac=sum(self.cs)/len(self.cs); av=sum(self.vs)/len(self.vs); ap=sum(self.ps)/len(self.ps)
        ac_str = f"{ac/1000:.3f} mA"
        self.lb_ac.setText(f"平均电流: {ac_str}"); self.lb_av.setText(f"平均电压: {av:.4f} V")
        self.lb_ap.setText(f"平均功率: {ap:.3f} mW")
        mx_str = f"{self.max_c/1000:.3f} mA"
        mn_str = f"{self.min_c/1000:.3f} mA"
        self.lb_mx.setText(f"最大电流: {mx_str}"); self.lb_mn.setText(f"最小电流: {mn_str}")
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
        self.user_scrolling=True
        self.btn_pause.setChecked(True)
        x=self.ts[val]; x_min=max(0,x-60)
        is_merged=self.act_mode.text()=="切换到双波形模式"
        if is_merged:
            self.pm.plotItem.vb.setXRange(x_min,x,padding=0)
        else:
            self.pc.plotItem.vb.setXRange(x_min,x,padding=0)
            self.pv.plotItem.vb.setXRange(x_min,x,padding=0)

    def _toggle_pause(self):
        """Toggle auto-scroll pause/resume"""
        if self.btn_pause.isChecked():
            self.user_scrolling=True
            self.btn_pause.setStyleSheet("background:#f38ba8;")
            self.statusBar().showMessage("自动滚动已暂停")
        else:
            self.user_scrolling=False
            self.btn_pause.setStyleSheet("")
            self.statusBar().showMessage("自动滚动已恢复")

    def _switch_time_mode(self, idx):
        self.time_mode = idx
        is_sys = idx == 1
        label = "系统时间" if is_sys else "时间 (s)"
        label_color = "#6c7086" if self.theme_idx != 1 else "#7c7f93"
        for pw, attr in [(self.pm, 'time_axis_m'), (self.pc, 'time_axis_c'), (self.pv, 'time_axis_v')]:
            pw.setLabel("bottom", label, color=label_color)
            old_axis = pw.plotItem.axes['bottom']['item']
            if is_sys:
                if not isinstance(old_axis, TimeAxisItem):
                    new_axis = TimeAxisItem(orientation='bottom')
                    if self.t0_abs:
                        new_axis.setStartTime(self.t0_abs)
                    pw.plotItem.setAxisItems({'bottom': new_axis})
                    setattr(self, attr, new_axis)
            else:
                if isinstance(old_axis, TimeAxisItem):
                    from pyqtgraph import AxisItem
                    new_axis = AxisItem(orientation='bottom')
                    pw.plotItem.setAxisItems({'bottom': new_axis})
                    setattr(self, attr, None)
        if self.ts:
            self._ui()

    def _switch_unit(self):
        self.unit=1-self.unit; self._ui()
        self.btn_unit.setText("切换 mWh/Wh" if self.unit == 0 else "切换 Wh/mWh")

    def _calc_m(self):
        if not self.ts: return
        t0,t1=self.region_m.getRegion(); idx=[i for i,t in enumerate(self.ts) if t0<=t<=t1]
        if len(idx)<2: return
        vr=[self.vs[i] for i in idx]; cr=[self.cs[i] for i in idx]; pr=[self.ps[i] for i in idx]
        dt=self.ts[idx[-1]]-self.ts[idx[0]]
        avg_c = sum(cr)/len(cr)
        max_c = max(cr)
        min_c = min(cr)
        c_avg_str = f"{avg_c/1000:.3f} mA"
        c_max_str = f"{max_c/1000:.3f} mA"
        c_min_str = f"{min_c/1000:.3f} mA"
        self.rv.setText(f"平均电压: {sum(vr)/len(vr):.4f} V")
        self.rc.setText(f"平均电流: {c_avg_str}")
        self.rp.setText(f"平均功率: {sum(pr)/len(pr):.4f} mW")
        self.rmx.setText(f"最大电流: {c_max_str}")
        self.rmn.setText(f"最小电流: {c_min_str}")
        self.rch.setText(f"电量(μAh): {sum(cr)/len(cr)*dt/3600*1000:.4f}")
        self.ren.setText(f"能量(μWh): {sum(pr)/len(pr)*dt/3600:.4f}")
        self.rtm.setText(f"时长: {dt:.2f} 秒")
        self.rn.setText(f"采样点数: {len(idx)}")

    def _apply(self):
        if self.device_mode == "gpib":
            if not GPIB_OK or gpib_ud<0: QMessageBox.warning(self,"提示","请先连接GPIB设备"); return
            g_send(f"VOLT {self.sv.value():.3f}"); g_send(f"CURR {self.sc.value()/1000:.3f}")
        else:
            if not USB_OK or not _libusb_dev: QMessageBox.warning(self,"提示","请先连接 USB 设备"); return
            s_send(f"VOLT {self.sv.value():.3f}"); s_send(f"CURR {self.sc.value()/1000:.3f}")
        QMessageBox.information(self,"成功","设置已生效")

    def _screenshot(self):
        from PyQt5.QtCore import QRect
        path = self.le_screenshot_path.text() if hasattr(self, 'le_screenshot_path') else screenshot_dir
        os.makedirs(path, exist_ok=True)
        fname = os.path.join(path, f"pg_power_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        screen = QApplication.primaryScreen()
        if screen:
            # Calculate bounding rect of main window + analysis window
            main_rect = self.geometry()
            if hasattr(self, 'analysis_win') and self.analysis_win and self.analysis_win.isVisible():
                analysis_rect = self.analysis_win.geometry()
                capture_rect = main_rect.united(analysis_rect)
            else:
                capture_rect = main_rect
            # Capture that region from screen
            pixmap = screen.grabWindow(0, capture_rect.x(), capture_rect.y(), 
                                        capture_rect.width(), capture_rect.height())
            pixmap.save(fname, "PNG")
            QMessageBox.information(self, "截图成功", f"已保存到:\n{fname}")
            logger.info(f"截图: {fname}")
        else:
            QMessageBox.warning(self, "失败", "无法获取屏幕截图")

    def _browse_screenshot(self):
        d = QFileDialog.getExistingDirectory(self, "选择截图目录", self.le_screenshot_path.text())
        if d:
            self.le_screenshot_path.setText(d)

    def _run(self):
        c=self.se.toPlainText()
        if not c.strip(): return
        try:
            from lupa import LuaRuntime
            lua = LuaRuntime(unpack_returned_tuples=True)
            lua.globals().g_send = g_send
            lua.globals().g_qry = g_qry
            lua.globals().s_send = s_send
            lua.globals().s_qry = s_qry
            lua.globals().s_scan = s_scan
            lua.globals().s_open = s_open
            lua.globals().s_close = s_close
            lua.globals().print = lambda *a: self.le.append(" ".join(str(x) for x in a))
            lua.execute(c)
            self.le.append(f"[OK] {time.strftime('%H:%M:%S')}")
        except Exception as e:
            self.le.append(f"[ERR] {time.strftime('%H:%M:%S')} {e}")

    def _send_script(self):
        c = self.se.toPlainText()
        if not c.strip(): return
        s_send(c)
        self.le.append(f"[发送] {time.strftime('%H:%M:%S')}\n{c}")

    def _save(self):
        if not self.ts: QMessageBox.information(self,"提示","无数据"); return
        p,_=QFileDialog.getSaveFileName(self,"保存","","CSV (*.csv)")
        if p:
            if self.time_mode and self.t0_abs:
                time_header = "系统时间"
                time_fmt = "%Y/%m/%d %H:%M:%S.%f"
            else:
                time_header = "时间(s)"
                time_fmt = None
            with open(p,"w",newline="",encoding="utf-8") as f:
                w=csv.writer(f); w.writerow([time_header,"电压(V)","电流(uA)","功率(mW)"])
                for t,v,c,pp in zip(self.ts,self.vs,self.cs,self.ps):
                    if time_fmt:
                        dt = self.t0_abs + timedelta(seconds=t)
                        ts = dt.strftime(time_fmt)[:-3]
                    else:
                        ts = f"{t:.4f}"
                    w.writerow([ts,f"{v:.4f}",f"{c:.4f}",f"{pp:.4f}"])
            QMessageBox.information(self,"成功","已保存")

    def _load(self):
        p,_=QFileDialog.getOpenFileName(self,"加载","","CSV (*.csv)")
        if not p: return
        self._clear()
        try:
            with open(p,"r",encoding="utf-8") as f:
                r=csv.reader(f)
                header = next(r)
                is_sys_time = header[0] == "系统时间"
                t0_first = None
                for row in r:
                    if is_sys_time:
                        dt = datetime.strptime(row[0], "%Y/%m/%d %H:%M:%S.%f")
                        if t0_first is None:
                            t0_first = dt
                            self.t0_abs = t0_first
                        t = (dt - t0_first).total_seconds()
                    else:
                        t = float(row[0])
                    self.ts.append(t); self.vs.append(float(row[1])); self.cs.append(float(row[2])); self.ps.append(float(row[3]))
            if is_sys_time and self.ts:
                self.t0 = time.time() - self.ts[-1]
            QMessageBox.information(self,"成功","已加载")
        except Exception as e: QMessageBox.critical(self,"错误",str(e))

    def _clear(self, force=False):
        """清空所有波形数据"""
        if self.btn_pause.isChecked() and not force:
            QMessageBox.warning(self, "提示", "采集已暂停，请先恢复自动滚动再清空数据")
            return
        if not force and self.ts:
            ret = QMessageBox.question(self, "确认清空",
                "确定要清空所有波形数据吗？\n此操作不可恢复！",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes: return
        self.ts.clear(); self.vs.clear(); self.cs.clear(); self.ps.clear()
        self.e_mwh=0; self.max_c=0; self.min_c=float("inf"); self.save_count=0
        self.cc.clear(); self.cv.clear()
        self.statusBar().showMessage("数据已清空")

    def _float(self):
        if self.windowFlags()&Qt.WindowStaysOnTopHint: self.setWindowFlags(Qt.Window); self.act_float.setText("悬浮窗")
        else: self.setWindowFlags(Qt.Window|Qt.WindowStaysOnTopHint); self.act_float.setText("取消悬浮")
        self.show()

    def _toggle_voltage(self):
        """Toggle voltage waveform visibility in both merged and dual modes"""
        self.show_voltage = self.act_voltage.isChecked()
        self.act_voltage.setText("电压:显示" if self.show_voltage else "电压:隐藏")
        # Merged mode: hide/show voltage curve and right axis
        self.cm_v.setVisible(self.show_voltage)
        self.pm.plotItem.getAxis('right').setVisible(self.show_voltage)
        self.tvl_m.setVisible(self.show_voltage)
        self.lmv.setVisible(self.show_voltage)
        # Dual mode: hide/show voltage plot
        self.pv.setVisible(self.show_voltage)
        self.tvl.setVisible(self.show_voltage)
        self.lvl.setVisible(self.show_voltage)
        self.tm_v.setVisible(self.show_voltage)

    def _apply_analysis_win_theme(self):
        """Apply current theme to analysis window and related widgets"""
        is_dark = self.theme_idx != 1
        if is_dark:
            win_bg = "#1e1e2e"
            btn_bg = "#313244"; btn_fg = "#cdd6f4"; btn_border = "#45475a"
            btn_hover = "#45475a"
            menu_bg = "#1e1e2e"; menu_fg = "#cdd6f4"; menu_border = "#313244"; menu_sel = "#313244"
            fb_bg = "rgba(30,30,46,220)"; fb_btn_bg = "#313244"; fb_btn_fg = "#cdd6f4"; fb_btn_border = "#45475a"
            fb_btn_hover = "#45475a"; fb_report_bg = "#89b4fa"; fb_report_fg = "#1e1e2e"
            mini_bg = "#89b4fa"; mini_fg = "#1e1e2e"; mini_hover = "#74a8fa"
            title_color = "#cdd6f4"; label_color = "#6c7086"
            tip_text = "#cdd6f4"; tip_fill = "#1e1e2eee"; tip_border = "#585b70"
            lbl_fill = "#11111bcc"
            crosshair_color = "#45475a"
            hint_color = "#6c7086"
        else:
            win_bg = "#eff1f5"
            btn_bg = "#ccd0da"; btn_fg = "#4c4f69"; btn_border = "#bcc0cc"
            btn_hover = "#bcc0cc"
            menu_bg = "#eff1f5"; menu_fg = "#4c4f69"; menu_border = "#ccd0da"; menu_sel = "#ccd0da"
            fb_bg = "rgba(230,233,239,220)"; fb_btn_bg = "#ccd0da"; fb_btn_fg = "#4c4f69"; fb_btn_border = "#bcc0cc"
            fb_btn_hover = "#bcc0cc"; fb_report_bg = "#1e66f5"; fb_report_fg = "#ffffff"
            mini_bg = "#1e66f5"; mini_fg = "#ffffff"; mini_hover = "#1758d4"
            title_color = "#4c4f69"; label_color = "#7c7f93"
            tip_text = "#4c4f69"; tip_fill = "#eff1f5ee"; tip_border = "#bcc0cc"
            lbl_fill = "#e6e9efcc"
            crosshair_color = "#bcc0cc"
            hint_color = "#7c7f93"
        
        if self.region_panel:
            self.region_panel.set_dark(is_dark)
        
        if hasattr(self, 'analysis_win') and self.analysis_win:
            self.analysis_win.setStyleSheet(f"""
                QMainWindow {{ background: {win_bg}; }}
                QWidget {{ background: {win_bg}; }}
                QPushButton {{
                    background: {btn_bg}; color: {btn_fg}; border: 1px solid {btn_border};
                    border-radius: 6px; padding: 8px 16px; font-weight: bold;
                }}
                QPushButton:hover {{ background: {btn_hover}; }}
            """)
        
        if hasattr(self, 'analysis_mini_btn') and self.analysis_mini_btn:
            self.analysis_mini_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {mini_bg}; color: {mini_fg}; border: none;
                    border-radius: 20px; font-size: 16px; font-weight: bold;
                }}
                QPushButton:hover {{ background: {mini_hover}; }}
            """)
        
        for pw in [self.pm, self.pc, self.pv]:
            menu = pw.plotItem.vb.menu
            if menu:
                menu.setStyleSheet(f"QMenu{{background:{menu_bg};color:{menu_fg};border:1px solid {menu_border};}}QMenu::item:selected{{background:{menu_sel};}}")

        time_label = "系统时间" if self.time_mode else "时间 (s)"
        self.pm.setTitle("电压 / 电流 波形", color=title_color, size="12pt")
        self.pm.setLabel("left", self._curr_axis_label(), color="#89b4fa" if is_dark else "#1e66f5")
        self.pm.setLabel("bottom", time_label, color=label_color)
        self.pm.plotItem.getAxis('right').setLabel("电压 (V)", color="#f38ba8" if is_dark else "#d20f39")
        self.pc.setTitle("电流波形", color=title_color, size="12pt")
        self.pc.setLabel("left", self._curr_axis_label(), color=label_color)
        self.pc.setLabel("bottom", time_label, color=label_color)
        self.pv.setTitle("电压波形", color=title_color, size="12pt")
        self.pv.setLabel("left", "电压 (V)", color=label_color)
        self.pv.setLabel("bottom", time_label, color=label_color)

        self.xm.setColor(tip_text); self.xm._border = pg.mkPen(tip_border, width=1); self.xm._fill = pg.mkBrush(tip_fill); self.xm.update()
        self.xc.setColor(tip_text); self.xc._border = pg.mkPen(tip_border, width=1); self.xc._fill = pg.mkBrush(tip_fill); self.xc.update()
        self.xvl.setColor(tip_text); self.xvl._border = pg.mkPen(tip_border, width=1); self.xvl._fill = pg.mkBrush(tip_fill); self.xvl.update()
        self.lmc.setColor("#89b4fa" if is_dark else "#1e66f5"); self.lmc._fill = pg.mkBrush(lbl_fill); self.lmc.update()
        self.lmv.setColor("#f38ba8" if is_dark else "#d20f39"); self.lmv._fill = pg.mkBrush(lbl_fill); self.lmv.update()
        self.lc.setColor("#89b4fa" if is_dark else "#1e66f5"); self.lc._fill = pg.mkBrush(lbl_fill); self.lc.update()
        self.lvl.setColor("#f38ba8" if is_dark else "#d20f39"); self.lvl._fill = pg.mkBrush(lbl_fill); self.lvl.update()

        ch_pen = pg.mkPen(crosshair_color, style=Qt.DashLine, width=1)
        for line in [self.vm, self.hm, self.vc, self.hc, self.vvl, self.hvl]:
            line.setPen(ch_pen)

        if hasattr(self, 'analysis_hint') and self.analysis_hint:
            self.analysis_hint.setStyleSheet(f"color:{hint_color};font-size:12px;padding:8px")

    def _toggle_theme(self):
        dark, light = get_themes(self.is_low_res)
        themes=[dark, light, dark]
        names=["深色主题","浅色主题","跟随系统"]
        self.theme_idx=(self.theme_idx+1)%3
        self.act_theme.setText(names[self.theme_idx])
        QApplication.instance().setStyleSheet(themes[self.theme_idx])
        is_dark = self.theme_idx != 1
        set_dark_titlebar(self, is_dark)
        # Update RoundSwitch themes
        for sw in [self.btn_region, self.chk_auto, self.chk_bold, self.sw_track]:
            sw.set_dark(is_dark)
        bg="#eff1f5" if self.theme_idx==1 else "#11111b"
        grid_c="#ccd0da" if self.theme_idx==1 else "#45475a"
        self.pm.setBackground(bg); self.pc.setBackground(bg); self.pv.setBackground(bg)
        self._apply_analysis_win_theme()

    def _update_data_font_size(self, size=None):
        if size is not None:
            self.data_font_size = size
        self.data_font_bold = self.chk_bold.isChecked()
        fs = f"{self.data_font_size}px"
        fw = "bold" if self.data_font_bold else "normal"
        import re
        for lbl in [self.lb_ac, self.lb_av, self.lb_ap, self.lb_mx, self.lb_mn, self.lb_en, self.lb_ah, self.lb_tm, self.lb_n]:
            style = lbl.styleSheet()
            style = re.sub(r'font-size:\d+px', f'font-size:{fs}', style)
            style = re.sub(r'font-weight:\w+', f'font-weight:{fw}', style)
            if 'font-weight:' not in style:
                style += f';font-weight:{fw}'
            lbl.setStyleSheet(style)

    def _update_data_font_size_bold(self):
        self._update_data_font_size()

    def _load_settings(self):
        s=QSettings("PG-Power","settings")
        self.cb_power.setCurrentText(s.value("power_model","663XX"))
        self.spin_board.setValue(s.value("gpib_board",0,type=int))
        self.spin_a.setValue(s.value("gpib_addr",5,type=int))
        self.sv.setValue(s.value("max_volt",4.2,type=float))
        self.sc.setValue(s.value("max_curr",1000,type=float))
        self.spin_cmax.setValue(s.value("c_max",350,type=float))
        self.spin_cmin.setValue(s.value("c_min",0,type=float))
        self.spin_vmax.setValue(s.value("v_max",20,type=float))
        self.spin_vmin.setValue(s.value("v_min",0,type=float))
        self.spin_cache.setValue(s.value("cache",50000,type=int))
        self.spin_lw.setValue(s.value("line_width",2,type=float))
        self.data_font_size=s.value("data_font_size",18,type=int)
        self.data_font_bold=s.value("data_font_bold",True,type=bool)
        self.spin_font_size.setValue(self.data_font_size)
        self.chk_bold.setChecked(self.data_font_bold)
        self.cb_coord.setCurrentIndex(s.value("coord",0,type=int))
        self.track_side=s.value("track_side","right")
        self.sw_track.blockSignals(True)
        self.sw_track.setChecked(self.track_side=="right")
        self.sw_track.blockSignals(False)
        self._ts(self.track_side)
        sp=s.value("screenshot_path","")
        if sp: self.le_screenshot_path.setText(sp)
        self.time_mode=s.value("time_mode",0,type=int)
        self.cb_time_mode.setCurrentIndex(self.time_mode)
        self.sample_interval=s.value("sample_interval",50,type=int)
        self.cb_sample.setCurrentText(str(self.sample_interval))
        # LuatOS/Serial settings
        self.device_mode=s.value("device_mode","gpib")
        mode_idx=0 if self.device_mode=="gpib" else 1
        self.cb_mode.setCurrentIndex(mode_idx)
        self._on_device_mode_changed(mode_idx)
        port=s.value("serial_port","")
        if port: self.cb_serial_port.setCurrentText(port)
        # 快速连接设备类型持久化
        quick_type_idx = s.value("quick_connect_type", 1, type=int)  # 默认USB
        if 0 <= quick_type_idx < self.cb_quick_type.count():
            self.cb_quick_type.setCurrentIndex(quick_type_idx)
        # GPIB电流零位偏移恢复
        global _gpib_current_offset
        _gpib_current_offset = s.value("gpib_current_offset", 0.0, type=float)
        if hasattr(self, 'lb_gpib_offset'):
            self.lb_gpib_offset.setText(f"电流零位: {_gpib_current_offset:.4f} mA")

    def _save_settings(self):
        s=QSettings("PG-Power","settings")
        s.setValue("power_model",self.cb_power.currentText())
        s.setValue("gpib_board",self.spin_board.value())
        s.setValue("gpib_addr",self.spin_a.value())
        s.setValue("max_volt",self.sv.value())
        s.setValue("max_curr",self.sc.value())
        s.setValue("c_max",self.spin_cmax.value())
        s.setValue("c_min",self.spin_cmin.value())
        s.setValue("v_max",self.spin_vmax.value())
        s.setValue("v_min",self.spin_vmin.value())
        s.setValue("cache",self.spin_cache.value())
        s.setValue("line_width",self.spin_lw.value())
        s.setValue("data_font_size",self.data_font_size)
        s.setValue("data_font_bold",self.data_font_bold)
        s.setValue("coord",self.cb_coord.currentIndex())
        s.setValue("track_side",self.track_side)
        s.setValue("screenshot_path",self.le_screenshot_path.text())
        s.setValue("time_mode",self.time_mode)
        s.setValue("sample_interval",self.sample_interval)
        s.setValue("device_mode",self.device_mode)
        s.setValue("serial_port",self.cb_serial_port.currentText())
        s.setValue("quick_connect_type", self.cb_quick_type.currentIndex())
        s.setValue("gpib_current_offset", _gpib_current_offset)

    def closeEvent(self, e):
        self.collecting=False
        if self.device_mode == "gpib": g_close()
        else: s_close()
        self._save_settings(); e.accept()

if __name__=="__main__":
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PG-Power")
    except Exception:
        pass
    app=QApplication(sys.argv)
    app.setStyle("Fusion")
    # Detect screen resolution for theme
    screen = app.primaryScreen()
    is_low_res = screen and (screen.availableGeometry().width() < 1280 or screen.availableGeometry().height() < 800)
    dark, light = get_themes(is_low_res)
    app.setStyleSheet(dark)
    ico=os.path.join(sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__)),"icon.ico")
    if os.path.exists(ico): app.setWindowIcon(QIcon(ico))
    w=Main(); w.show(); sys.exit(app.exec_())
