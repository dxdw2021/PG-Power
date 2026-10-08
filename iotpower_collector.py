"""
IotPower-cc 独立采集脚本
================================
功能：USB通信 → 数据包解析 → 异常值过滤 → CSV输出 + 日志

官方标定系数（已与官网 IotPower-cc 客户端校准日志交叉验证）：
  V = v_raw / 4044.0  (等价于 v_raw × 0.000247)
  I(μA) = c_raw / 9.9  (等价于 c_raw × 0.101017)

USB协议：
  设备 VID=0x1209 PID=0x7301 (上海合宙 IotPower-cc)
  64字节Bulk传输，4字节LE采样格式 [v_lo, v_hi, c_lo, c_hi]
  同步包标记：0xAA 0x55 开头

用法：
  python iotpower_collector.py              # 默认采样率50ms，持续采集直到 Ctrl+C
  python iotpower_collector.py -r 100       # 采样率100ms
  python iotpower_collector.py -o mydata    # 指定输出CSV前缀
  python iotpower_collector.py --list       # 仅扫描设备

依赖：
  - libusb-1.0.dll (与脚本同目录)
  - pyusb (pip install pyusb)
"""

import sys
import os
import time
import csv
import logging
import argparse
import signal
from datetime import datetime

# ============================================================================
# 日志配置
# ============================================================================

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, f"iotpower_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-5s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("IotPower")

# ============================================================================
# USB 后端初始化 (libusb-1.0.dll)
# ============================================================================

LUATOS_VID = 0x1209
LUATOS_PID = 0x7301

_libusb_dll = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libusb-1.0.dll")

if not os.path.exists(_libusb_dll):
    logger.error(f"未找到 libusb-1.0.dll，请放置到脚本同目录: {_libusb_dll}")
    sys.exit(1)

try:
    import usb.core
    import usb.backend.libusb1

    _libusb_be = usb.backend.libusb1.get_backend(find_library=lambda x: _libusb_dll)
    if not _libusb_be:
        logger.error("无法加载 libusb 后端")
        sys.exit(1)
    logger.info("libusb 后端加载成功")
except ImportError:
    logger.error("请安装 pyusb: pip install pyusb")
    sys.exit(1)
except Exception as e:
    logger.error(f"USB 初始化失败: {e}")
    sys.exit(1)

# ============================================================================
# 设备管理
# ============================================================================

_dev = None
_ep_out = None
_ep_in = None


def scan_devices():
    """扫描 IotPower-cc 设备"""
    try:
        devs = list(
            usb.core.find(
                backend=_libusb_be, find_all=True, idVendor=LUATOS_VID, idProduct=LUATOS_PID
            )
        )
        return devs
    except Exception as e:
        logger.warning(f"扫描失败: {e}")
        return []


def open_device():
    """打开 IotPower-cc 设备，返回 True/False"""
    global _dev, _ep_out, _ep_in

    devs = scan_devices()
    if not devs:
        logger.error(f"未找到设备 VID={LUATOS_VID:04X} PID={LUATOS_PID:04X}")
        return False

    dev = devs[0]
    try:
        dev.set_configuration()
    except Exception as e:
        logger.debug(f"set_configuration (可忽略): {e}")

    cfg = dev.get_active_configuration()
    _ep_out = None
    _ep_in = None
    for intf in cfg:
        for ep in intf:
            if ep.bEndpointAddress & 0x80:
                if _ep_in is None:
                    _ep_in = ep.bEndpointAddress
            else:
                if _ep_out is None:
                    _ep_out = ep.bEndpointAddress

    if _ep_out is None or _ep_in is None:
        logger.error("未找到USB端点")
        return False

    _dev = dev
    logger.info(
        f"设备已连接: VID={LUATOS_VID:04X} PID={LUATOS_PID:04X} "
        f"EP_IN=0x{_ep_in:02X} EP_OUT=0x{_ep_out:02X}"
    )
    return True


def close_device():
    """关闭设备"""
    global _dev, _ep_out, _ep_in
    try:
        if _dev:
            try:
                _dev.reset()
            except Exception:
                pass
    except Exception:
        pass
    _dev = None
    _ep_out = None
    _ep_in = None
    logger.info("设备已断开")


# ============================================================================
# 数据包解析 + 异常过滤
# ============================================================================

# 全局过滤状态
_debug_cnt = 0
_debug_v_cnt = 0
_v_filtered = 0
_c_filtered = 0
_sample_cnt = 0
_c_raw_history = []  # size: 50
_v_raw_history = []  # size: 50
_prev_hist_v_mid = 0  # 上次历史中位数（基线漂移/负载切换检测）
_last_good_c_med = 0  # 上次稳定电流中位数（跳变限幅用）
_adc_range = 1        # 当前电压ADC量程（用于检测量程切换）


def read_packet():
    """
    读取一个64字节USB数据包，解析并过滤后返回 (v_raw, c_raw)。
    返回 None 表示本次数据被过滤或无效。

    数据包格式:
      - 64 字节 Bulk IN 传输
      - 每 4 字节一组: [v_lo, v_hi, c_lo, c_hi] (little-endian)
      - 跳过 0xAA 0x55 同步包
      - 16 组采样取中位数
    """
    global _debug_cnt, _debug_v_cnt, _v_filtered, _c_filtered, _sample_cnt
    global _c_raw_history, _v_raw_history, _prev_hist_v_mid, _adc_range, _last_good_c_med

    if _dev is None or _ep_in is None:
        return None

    try:
        raw = _dev.read(_ep_in, 64, timeout=50)
        if not raw or len(raw) < 4:
            return None
        raw = bytes(raw)
    except usb.core.USBTimeoutError:
        return None
    except Exception as e:
        logger.debug(f"USB读取异常: {e}")
        return None

    # 跳过同步/控制包 (以 0xAA 0x55 开头)
    if len(raw) >= 2 and raw[0] == 0xAA and raw[1] == 0x55:
        return None

    # 解析所有 4 字节 LE 采样: [v_lo, v_hi, c_lo, c_hi]
    vs, cs = [], []
    i = 0
    while i + 3 < len(raw):
        v = raw[i] | (raw[i + 1] << 8)
        c = raw[i + 2] | (raw[i + 3] << 8)
        if v > 1000 and c > 0:  # 基本有效性检查
            vs.append(v)
            cs.append(c)
        i += 4

    if not vs:
        return None

    # 取中位数（抗个别毛刺）
    vs.sort()
    cs.sort()
    v_mid = len(vs) // 2
    v_med = vs[v_mid]
    c_mid = len(cs) // 2
    c_med = cs[c_mid]

    # ===== ADC量程归一化: 将不同量程下的raw值归一化到量程1 =====
    # ⚡ 电压和电流使用独立的量程检测（硬件可能在不同通道使用不同量程）
    def _detect_range(v):
        if 15000 < v < 18000: return 1
        if 33000 < v < 36000: return 2
        if 48000 < v < 50000: return 3
        return 0
    def _detect_current_range(c):
        if c < 18000: return 1
        if 33000 < c < 36000: return 2
        if 48000 < c < 50000: return 3
        return 1
    v_range = _detect_range(v_med)
    c_range = _detect_current_range(c_med)
    range_changed = False
    if v_range > 1:
        v_med = (v_med + v_range // 2) // v_range
        range_changed = (_adc_range != v_range)
        if range_changed:
            logger.debug(f"[IOT-RANGE] 电压量程 {_adc_range}→{v_range}，raw已归一化到量程1")
        _adc_range = v_range
    elif v_range == 1 and _adc_range != 1:
        range_changed = True
        _adc_range = 1
    if c_range > 1:
        old_c = c_med
        c_med = (c_med + c_range // 2) // c_range
        logger.debug(f"[IOT-RANGE-C] 电流量程{c_range}归一化: c_raw {old_c}→{c_med}")

    # ===== 负载切换检测: 电流突变时重置所有历史基线 =====
    # ⚡ 必须放在电流限幅器之前，否则负载接入电流会被限幅器误拦截
    # ⏱ 每 3 秒最多重置一次，避免放电过渡期连续触发
    global _last_good_c_med
    _now = time.time()
    if _now - getattr(read_packet, '_last_reset_time', 0) < 3.0:
        pass  # 冷却期内跳过
    elif len(_c_raw_history) >= 5 and len(_v_raw_history) >= 5:
        c_hist_mid = sorted(_c_raw_history)[len(_c_raw_history) // 2]
        if c_hist_mid > 100 and abs(c_med - c_hist_mid) > c_hist_mid * 2.5:
            _v_raw_history.clear()
            _c_raw_history.clear()
            _prev_hist_v_mid = 0
            _last_good_c_med = 0  # 同步清零限幅器基线
            read_packet._limiter_cooldown = 5  # 负载切换后跳过限幅器5个样本
            read_packet._last_reset_time = _now
            logger.info(
                f"[BASELINE-RESET] 检测到负载切换，重置基线 "
                f"c_med={c_med}(→{c_med/9.9:.1f}μA) "
                f"历史c_mid={c_hist_mid:.0f}(→{c_hist_mid/9.9:.1f}μA) "
                f"变化={abs(c_med-c_hist_mid)/c_hist_mid*100:.0f}%"
            )
            _sample_cnt += 1
            return (v_med, c_med)

    # ---- 电流跳变限幅: 抑制ADC漂移导致的尖峰 ----
    # 负载切换后冷却期内跳过限幅器，让新基线稳定
    cooldown = getattr(read_packet, '_limiter_cooldown', 0)
    if cooldown > 0:
        read_packet._limiter_cooldown = cooldown - 1
        if read_packet._limiter_cooldown == 0:
            _last_good_c_med = c_med  # 冷却结束后用当前值建立基线
            logger.debug(f"[LIMITER-COOLDOWN] 冷却结束，建立新基线 c_med={c_med}")
    elif _last_good_c_med > 0 and c_med > 100:
        if c_med > _last_good_c_med * 3 or c_med < _last_good_c_med / 3:
            logger.debug(f"[LIMITER] {c_med}→{_last_good_c_med} (变化{c_med/_last_good_c_med:.1f}x)")
            c_med = _last_good_c_med
    _last_good_c_med = c_med

    # ---- 电流异常过滤 (仅日志，不丢弃 — 原始客户端即如此) ----
    if len(_c_raw_history) >= 5:
        hist_mid = sorted(_c_raw_history)[len(_c_raw_history) // 2]
        if hist_mid > 100 and abs(c_med - hist_mid) > hist_mid * 5:
            _c_filtered += 1
            if _debug_cnt < 10:
                logger.debug(
                    f"[C-FILTER] #{_c_filtered} c_raw={c_med} "
                    f"hist_mid={hist_mid:.0f} 偏差={abs(c_med-hist_mid)/hist_mid*100:.0f}% (记录不过滤)"
                )
                _debug_cnt += 1
            # 不再 return None — 允许数据通过

    # ---- 电压异常过滤 ----
    # 量程切换保护：量程刚变化时跳过过滤
    if range_changed:
        logger.debug(f"[V-FILTER] 量程刚切换，跳过本次电压过滤")
    elif len(_v_raw_history) >= 5:
        hist_v_all = sorted(_v_raw_history)
        hist_v_mid = hist_v_all[len(hist_v_all) // 2]
        deviation = abs(v_med - hist_v_mid) / hist_v_mid if hist_v_mid > 0 else 0
        dev_threshold = 0.45

        # ---- 异常判定 ----
        is_anomaly = (hist_v_mid > 100 and deviation > dev_threshold)

        if is_anomaly:
            _v_filtered += 1
            logger.info(
                f"[V-FILTER] #{_v_filtered} v_raw={v_med} hist_mid={hist_v_mid:.0f} "
                f"偏差={deviation*100:.1f}% (阈值{dev_threshold*100:.0f}%) 已过滤"
            )
            if _debug_v_cnt < 10:
                logger.debug(
                    f"[V-FILTER-DBG] v_hist(最近{len(hist_v_all)}点) "
                    f"min={hist_v_all[0]} max={hist_v_all[-1]} mid={hist_v_mid:.0f}"
                )
                _debug_v_cnt += 1

            # 连续过滤超阈值时自动重置基线
            if _v_filtered % 100 == 0:
                logger.warning(f"[V-FILTER-AUTO-RESET] 已过滤{_v_filtered}次，自动重置基线")
                _v_raw_history.clear()
                _prev_hist_v_mid = 0

            return None

    # ---- 定期状态报告 ----
    if _sample_cnt > 0 and _sample_cnt % 200 == 0:
        if len(_v_raw_history) >= 5:
            hv = sorted(_v_raw_history)
            v_rate = _v_filtered / _sample_cnt * 100
            c_rate = _c_filtered / _sample_cnt * 100
            logger.debug(
                f"[FILTER-STAT] sample={_sample_cnt} "
                f"v_过滤={_v_filtered}({v_rate:.1f}%) c_过滤={_c_filtered}({c_rate:.1f}%) "
                f"v_range=[{hv[0]}, {hv[len(hv)//2]}, {hv[-1]}]"
            )
            # 过滤率 > 20% 时自动告警
            if v_rate > 20:
                logger.warning(
                    f"[FILTER-ALARM] ⚠ 电压过滤率异常高 {v_rate:.1f}%！"
                    f" 近200次采样中 {_v_filtered}/{_sample_cnt} 被过滤"
                )
                logger.warning(
                    f"[FILTER-ALARM] 当前基线: v_min={hv[0]} v_mid={hv[len(hv)//2]} v_max={hv[-1]}"
                )
                logger.warning(
                    f"[FILTER-ALARM] 排查建议:"
                    f" 1)若v_baseline正常但频繁过滤 → USB数据异常"
                    f" 2)若v_baseline已偏大(>30000) → 历史缓冲区被污染，需重启采集"
                    f" 3)若v_min/v_max跨度大 → 设备电压剧烈波动，检查供电"
                )

    # 更新历史缓冲区
    _c_raw_history.append(c_med)
    if len(_c_raw_history) > 50:
        _c_raw_history.pop(0)

    _v_raw_history.append(v_med)
    if len(_v_raw_history) > 50:
        _v_raw_history.pop(0)

    _sample_cnt += 1
    return (v_med, c_med)


# ============================================================================
# 标定转换
# ============================================================================


def calibrate(v_raw, c_raw):
    """
    官方标定系数转换（与 IotPower-cc 客户端校准日志交叉验证通过）。
    返回 (电压_V, 电流_uA, 功率_mW)。
    """
    v = v_raw / 4044.0  # V
    c = c_raw / 9.9  # μA
    p = v * c / 1000.0  # mW
    return v, c, p


# ============================================================================
# 数据采集主循环
# ============================================================================


def collect(sample_interval_ms=50, csv_prefix="iotpower"):
    """
    主采集循环。

    参数:
      sample_interval_ms: 采样间隔 (毫秒)，默认 50ms
      csv_prefix:       输出 CSV 文件名前缀

    输出:
      - CSV 文件: logs/{prefix}_{timestamp}.csv
      - 日志文件: logs/iotpower_{timestamp}.log
    """
    csv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(csv_dir, exist_ok=True)
    csv_path = os.path.join(csv_dir, f"{csv_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    logger.info(f"采样率: {sample_interval_ms}ms")
    logger.info(f"CSV输出: {csv_path}")
    logger.info("开始采集... (按 Ctrl+C 停止)")

    csv_file = open(csv_path, "w", newline="", encoding="utf-8")
    writer = csv.writer(csv_file)
    writer.writerow(["时间(s)", "电压(V)", "电流(uA)", "功率(mW)", "备注"])

    t0 = time.time()
    sample_count = 0
    valid_count = 0
    filtered_count = 0
    no_data_count = 0

    try:
        while True:
            t_elapsed = time.time() - t0

            packet = read_packet()
            if packet is None:
                no_data_count += 1
                if no_data_count % 200 == 0:
                    logger.warning(f"连续无数据 {no_data_count}次")
                time.sleep(sample_interval_ms / 1000.0)
                continue

            no_data_count = 0
            v_raw, c_raw = packet
            v, c_uA, p_mW = calibrate(v_raw, c_raw)

            valid_count += 1

            # 每200次输出一行摘要
            if valid_count <= 3 or valid_count % 200 == 0:
                c_label = f"{c_uA:.1f}μA" if c_uA < 1000 else f"{c_uA/1000:.1f}mA"
                logger.info(
                    f"#{valid_count} t={t_elapsed:.2f}s "
                    f"v_raw={v_raw} c_raw={c_raw} → V={v:.4f} I={c_label} P={p_mW:.4f}mW"
                )

            writer.writerow([f"{t_elapsed:.4f}", f"{v:.4f}", f"{c_uA:.2f}", f"{p_mW:.6f}", ""])
            csv_file.flush()

            sample_count = valid_count
            time.sleep(sample_interval_ms / 1000.0)

    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，停止采集")
    except Exception as e:
        logger.error(f"采集异常: {e}", exc_info=True)
    finally:
        csv_file.close()

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("采集结束，统计汇总:")
    logger.info(f"  总时长:     {elapsed:.1f}s")
    logger.info(f"  有效采样:   {valid_count}")
    logger.info(f"  电压过滤:   {_v_filtered}次")
    logger.info(f"  电流过滤:   {_c_filtered}次")
    logger.info(f"  实际采样率: {valid_count/elapsed:.1f} Hz")
    logger.info(f"  CSV文件:    {csv_path}")
    logger.info(f"  日志文件:   {LOG_FILE}")
    logger.info("=" * 60)


# ============================================================================
# CLI
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="IotPower-cc 独立采集工具 - USB通信/解析/过滤/记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python iotpower_collector.py                    默认 50ms 采样率
  python iotpower_collector.py -r 100             100ms 采样率
  python iotpower_collector.py -o pet_tracker     CSV文件前缀 pet_tracker
  python iotpower_collector.py --list             仅扫描并列出设备
  python iotpower_collector.py -r 20 -o test      20ms 高速采样

标定系数 (与官方客户端校准日志交叉验证):
  V = v_raw / 4044.0
  I(μA) = c_raw / 9.9
  P(mW) = V × I(μA) / 1000
        """,
    )
    parser.add_argument(
        "-r",
        "--rate",
        type=int,
        default=50,
        metavar="MS",
        help="采样间隔 (毫秒)，默认 50ms",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="iotpower",
        metavar="PREFIX",
        help="CSV 文件名前缀，默认 iotpower",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="仅扫描设备列表，不采集",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用 DEBUG 级别日志输出到控制台",
    )

    args = parser.parse_args()

    # 如果只扫描
    if args.list:
        devs = scan_devices()
        if devs:
            print(f"发现 {len(devs)} 个 IotPower-cc 设备:")
            for d in devs:
                print(f"  VID=0x{LUATOS_VID:04X} PID=0x{LUATOS_PID:04X}")
        else:
            print("未发现 IotPower-cc 设备")
        return

    # 调整控制台日志级别
    if not args.debug:
        root = logging.getLogger()
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler) and h.stream == sys.stdout:
                h.setLevel(logging.INFO)

    logger.info(f"IotPower-cc 独立采集工具 v1.0")
    logger.info(f"日志文件: {LOG_FILE}")

    # 打开设备
    if not open_device():
        logger.error("无法打开设备，请确认 IotPower-cc 已连接")
        sys.exit(1)

    try:
        collect(sample_interval_ms=args.rate, csv_prefix=args.output)
    finally:
        close_device()


def signal_handler(sig, frame):
    """Ctrl+C 信号处理"""
    pass


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    main()
