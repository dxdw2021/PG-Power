"""
模拟电压数据流，测试 s_readline() 中的电压异常值过滤逻辑。
运行: python test_v_filter.py
"""
import random
import logging

# 设置日志格式，与 main.py 中的 logger 保持一致
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("test")

# ===== 复刻 main.py 中的过滤逻辑 =====
_debug_cnt = 0
_debug_v_cnt = 0
_v_filtered = 0
_sample_cnt = 0
_c_raw_history = []
_v_raw_history = []


def s_readline_sim(v_raw, c_raw=688):
    """模拟 s_readline() 的电压过滤逻辑（跳过 USB 读取和数据包解析）"""
    global _debug_cnt, _debug_v_cnt, _v_filtered, _sample_cnt, _c_raw_history, _v_raw_history

    v_med = v_raw
    c_med = c_raw

    # Filter sync packet outliers (c_raw jumps to 7000+ while normal is ~688)
    if len(_c_raw_history) >= 5:
        hist_mid = sorted(_c_raw_history)[len(_c_raw_history) // 2]
        if hist_mid > 100 and abs(c_med - hist_mid) > hist_mid * 5:
            if _debug_cnt < 10:
                logger.debug(f"OUTLIER: c={c_med} hist_mid={hist_mid:.0f}")
                _debug_cnt += 1
            return None

    # Filter voltage outliers (v_raw jumps to ~34386/49200 while normal is ~16400-17024)
    if len(_v_raw_history) >= 5:
        hist_v_mid = sorted(_v_raw_history)[len(_v_raw_history) // 2]
        deviation = abs(v_med - hist_v_mid) / hist_v_mid if hist_v_mid > 0 else 0
        if hist_v_mid > 100 and deviation > 0.3:
            _v_filtered += 1
            logger.info(
                f"[V-FILTER] #{_v_filtered} v_raw={v_med} hist_mid={hist_v_mid:.0f} "
                f"偏差={deviation*100:.1f}% v_换算={v_med/4044.0:.2f}V c_raw={c_med} 已过滤"
            )
            if _debug_v_cnt < 10:
                hist_v_all = sorted(_v_raw_history)
                logger.debug(
                    f"[V-FILTER-DBG] v_hist(最近{len(hist_v_all)}) "
                    f"min={hist_v_all[0]} max={hist_v_all[-1]} mid={hist_v_mid:.0f}"
                )
                _debug_v_cnt += 1
            return None

    # 每200次有效采样输出一次电压过滤器状态
    if _sample_cnt > 0 and _sample_cnt % 200 == 0:
        if len(_v_raw_history) >= 5:
            hv = sorted(_v_raw_history)
            logger.debug(
                f"[V-FILTER-STAT] sample_cnt={_sample_cnt} 累计过滤={_v_filtered} "
                f"v_min={hv[0]} v_mid={hv[len(hv)//2]} v_max={hv[-1]}"
            )

    _c_raw_history.append(c_med)
    if len(_c_raw_history) > 50:
        _c_raw_history.pop(0)

    _v_raw_history.append(v_med)
    if len(_v_raw_history) > 50:
        _v_raw_history.pop(0)

    _sample_cnt += 1
    return (v_med, c_med)


# ===== 构造模拟数据流 =====
def simulate():
    """
    模拟场景：待机 → 异常电压 → 恢复
    - 前 300 个点：正常待机电压 ~16985 (4.2V)
    - 30 个点：异常跳变 ~34386 (8.5V)
    - 50 个点：恢复正常
    - 70 个点：异常跳变 ~49200 (12.2V)
    - 100 个点：恢复正常
    """
    logger.info("=" * 60)
    logger.info("开始模拟电压过滤测试")
    logger.info("=" * 60)

    total = 0
    passed = 0
    filtered = 0

    phases = [
        ("阶段1: 正常待机 (~4.2V)", 300, 16985, 300),
        ("阶段2: 异常跳变 (~8.5V)", 30, 34386, 200),
        ("阶段3: 恢复正常 (~4.2V)", 50, 16985, 300),
        ("阶段4: 异常跳变 (~12.2V)", 70, 49200, 200),
        ("阶段5: 恢复正常 (~4.2V)", 100, 16985, 300),
    ]

    for label, count, base, noise in phases:
        logger.info(f"\n--- {label}: {count} 个采样点 ---")
        for i in range(count):
            # 模拟正常的电压抖动 ±noise
            v_raw = base + random.randint(-noise, noise)
            result = s_readline_sim(v_raw, 688 + random.randint(-5, 5))
            total += 1
            if result is None:
                filtered += 1
            else:
                passed += 1

    logger.info(f"\n" + "=" * 60)
    logger.info(f"测试结果汇总:")
    logger.info(f"  总采样数: {total}")
    logger.info(f"  通过数:   {passed}")
    logger.info(f"  过滤数:   {filtered}")
    logger.info(f"  过滤率:   {filtered/total*100:.1f}%")
    logger.info(f"  预期过滤: 30+70 = 100 (8.5V和12.2V异常)")
    if filtered >= 95:
        logger.info(f"  结论: ✅ 过滤逻辑正常，异常电压点被正确过滤")
    else:
        logger.warning(f"  结论: ⚠️ 过滤数量异常，请检查")
    logger.info("=" * 60)


def simulate_high_filter_rate():
    """
    模拟高过滤率场景：连续异常数据，触发告警
    场景：基线被污染 → 正常数据反而被误过滤
    """
    global _debug_cnt, _debug_v_cnt, _v_filtered, _sample_cnt
    global _c_raw_history, _v_raw_history
    # 重置全局状态
    _debug_cnt = 0
    _debug_v_cnt = 0
    _v_filtered = 0
    _sample_cnt = 0
    _c_raw_history = []
    _v_raw_history = []

    logger.info("\n" + "=" * 60)
    logger.info("场景B: 高过滤率告警测试 — 异常数据持续250个点")
    logger.info("=" * 60)

    total = 0
    passed = 0
    filtered = 0

    # 前50个正常点建立基线
    for i in range(50):
        v_raw = 16985 + random.randint(-300, 300)
        result = s_readline_sim(v_raw, 688)
        total += 1
        if result is None:
            filtered += 1
        else:
            passed += 1

    logger.info(f"  基线建立完成，v_mid={sorted(_v_raw_history)[len(_v_raw_history)//2]}")

    # 连续250个异常点 → 触发每200次统计时的告警
    for i in range(250):
        v_raw = 49200 + random.randint(-200, 200)  # 12.2V异常
        result = s_readline_sim(v_raw, 688)
        total += 1
        if result is None:
            filtered += 1
        else:
            passed += 1

    logger.info(f"\n" + "-" * 40)
    logger.info(f"场景B 结果: 总={total} 通过={passed} 过滤={filtered}")
    logger.info(f"  预期: 过滤率应在 200/300 处触发 [V-FILTER-ALARM] 告警")
    logger.info("-" * 40)


if __name__ == "__main__":
    logger.info("\n场景A: 正常过滤测试 (8.5V/12.2V 间歇性异常)")
    logger.info("=" * 60)
    simulate()
    logger.info("\n")
    simulate_high_filter_rate()
