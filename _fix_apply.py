"""修复 updater.py 的 apply_update — 纯 Python 线程方案"""
import os, sys

with open('updater.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_start = content.find('def apply_update(new_exe_path')
old_end = content.find('\n\n', old_start + 1)

new_func = '''def apply_update(new_exe_path, current_exe_path, wait_sec=3):
    """纯 Python 后台线程方案: 等进程退出 -> 覆盖 -> 重启。不依赖 bat/cmd"""
    import threading, time as _time
    current_exe_path = os.path.abspath(current_exe_path)
    new_exe_path = os.path.abspath(new_exe_path)

    if not getattr(sys, "frozen", False):
        try:
            shutil.copy2(new_exe_path, current_exe_path)
            logger.info("[更新] dev 模式: 已覆盖, 请手动重启")
        except OSError as e:
            logger.error(f"[更新] copy 失败: {e}")
        return False, None

    def _do_update():
        """后台线程: 等主进程退出 -> 覆盖 -> 启动"""
        log_path = os.path.join(tempfile.gettempdir(), "pg_power_update.log")
        try:
            with open(log_path, "w", encoding="utf-8") as log:
                def L(msg):
                    log.write(msg + chr(10))
                    log.flush()
                L("update start")
                L(f"  new={new_exe_path}")
                L(f"  cur={current_exe_path}")

                # 等主进程退出 (最多 wait_sec + 30 秒)
                L("  waiting main process exit...")
                for i in range(wait_sec, wait_sec + 35):
                    # 检查文件是否可写 (进程还在运行时文件被锁定)
                    try:
                        with open(current_exe_path, "ab") as test_f:
                            pass
                        L(f"  target free after {i}s")
                        break
                    except PermissionError:
                        pass
                    if i == wait_sec + 34:
                        L("  TIMEOUT giving up after 35s")
                        return
                    _time.sleep(1)

                # 移动新 exe 到旧位置 (先 move 再 copy fallback)
                L("  trying move...")
                try:
                    shutil.move(new_exe_path, current_exe_path)
                    L("  move OK")
                except Exception as e:
                    L(f"  move failed: {e}, trying copy...")
                    try:
                        shutil.copy2(new_exe_path, current_exe_path)
                        L("  copy OK")
                    except Exception as e2:
                        L(f"  copy failed: {e2}, trying delete+copy...")
                        try:
                            os.remove(current_exe_path)
                            _time.sleep(1)
                            shutil.copy2(new_exe_path, current_exe_path)
                            L("  delete+copy OK")
                        except Exception as e3:
                            L(f"  ALL FAILED: {e3}")
                            return

                # 启动新版本
                L("  launching new exe...")
                import subprocess as _sp
                _sp.Popen([current_exe_path], cwd=os.path.dirname(current_exe_path))
                L("  launched! update done")
        except Exception as e:
            logger.exception(f"[更新] 后台更新异常: {e}")

    t = threading.Thread(target=_do_update, daemon=True)
    t.start()
    logger.info("[更新] 后台更新线程已启动, 等主进程退出后自动覆盖")
    return True, None
'''

content = content[:old_start] + new_func + content[old_end:]

with open('updater.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
ast.parse(content)
print("✅ updater.py 修复成功, 语法 OK")
print()

# 检查关键元素
for ch in ['def apply_update', 'threading.Thread', 'shutil.move', 'shutil.copy2',
           'pg_power_update.log', 'PermissionError', '_do_update']:
    found = ch in content
    print(f"  {ch}: {'OK' if found else 'MISSING!'}")
