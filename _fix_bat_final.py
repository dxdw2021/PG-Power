import os, sys

with open('updater.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_start = content.find('def apply_update(new_exe_path')
old_end = content.find('\n\n', old_start + 1)
if old_end < 0: old_end = len(content)

# 用 chr(34) 替代双引号, chr(37) 替代百分号, chr(13)+chr(10) 替代 \r\n
Q = chr(34)  # "
PCT = chr(37)  # %
CRLF = chr(13) + chr(10)

new_apply = '''def apply_update(new_exe_path, current_exe_path, wait_sec=3):
    """bat + VBScript 独立进程: 主进程退出后继续替换 + 启动"""
    import subprocess as _sp
    current_exe_path = os.path.abspath(current_exe_path)
    new_exe_path = os.path.abspath(new_exe_path)

    if not getattr(sys, "frozen", False):
        try:
            shutil.copy2(new_exe_path, current_exe_path)
            logger.info("[更新] dev 模式: 已覆盖, 请手动重启")
        except OSError as e:
            logger.error(f"[更新] copy 失败: {e}")
        return False, None

    def _short_path(long_path):
        """中文路径转 8.3 短路径"""
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            fn = k32.GetShortPathNameW
            fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            fn.restype = wintypes.DWORD
            buf = ctypes.create_unicode_buffer(512)
            if fn(long_path, buf, 512) and buf.value:
                return buf.value
        except Exception:
            pass
        return long_path

    cur_s = _short_path(current_exe_path)
    new_s = _short_path(new_exe_path)
    log_p = os.path.join(tempfile.gettempdir(), "pg_power_update.log")
    bat_p = os.path.join(tempfile.gettempdir(), "pg_power_update.bat")
    vbs_p = os.path.join(tempfile.gettempdir(), "pg_power_update.vbs")
    log_slash = log_p.replace(os.sep, "/")

    # bat: GBK 编码, 用 8.3 短路径避免中文问题
    Q = chr(34)
    P = chr(37)
    bat_lines = [
        "@echo off",
        "echo update start > " + Q + log_slash + Q,
        "echo new=" + new_s + " >> " + Q + log_slash + Q,
        "echo cur=" + cur_s + " >> " + Q + log_slash + Q,
        "timeout /t " + str(max(3, wait_sec)) + " /nobreak >> " + Q + log_slash + Q,
        ":retry",
        "if not exist " + Q + cur_s + Q + " goto do_move",
        "timeout /t 1 /nobreak >nul",
        "goto retry",
        ":do_move",
        "echo moving... >> " + Q + log_slash + Q,
        "move /y " + Q + new_s + Q + " " + Q + cur_s + Q + " >> " + Q + log_slash + Q + " 2>&1",
        "if " + P + "errorlevel" + P + " neq 0 (",
        "    echo move failed, try copy >> " + Q + log_slash + Q,
        "    copy /y " + Q + new_s + Q + " " + Q + cur_s + Q + " >> " + Q + log_slash + Q + " 2>&1",
        ")",
        "start " + Q + Q + " " + Q + cur_s + Q,
        "echo launched >> " + Q + log_slash + Q,
        "timeout /t 2 /nobreak >nul",
        "del /q " + P + "~f0" + P,
    ]
    bat = CRLF.join(bat_lines) + CRLF

    # VBScript: WshShell.Run 隐藏窗口, 独立进程
    bat_vbs = bat_p.replace(os.sep, "\\")
    vbs = (
        'Set WshShell = CreateObject("WScript.Shell")' + CRLF
        + 'WshShell.Run "%COMSPEC% /c ' + Q + bat_vbs + Q + '", 0, False' + CRLF
    )

    try:
        with open(bat_p, "w", encoding="gbk") as f:
            f.write(bat)
        with open(vbs_p, "w") as f:
            f.write(vbs)
        logger.info(f"[更新] bootstrap 已生成: bat={bat_p}")
    except OSError as e:
        logger.error(f"[更新] 写脚本失败: {e}")
        return False, None

    try:
        _sp.Popen(["wscript.exe", vbs_p],
                  creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0))
        logger.info("[更新] bootstrap 已启动, 主进程即将退出")
    except OSError as e:
        logger.error(f"[更新] 启动失败: {e}")
        return False, None

    return True, bat_p
"""

content = content[:old_start] + new_apply + content[old_end:]

with open('updater.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
ast.parse(content)
print("OK 语法验证通过")

# 测试 bat 生成
sys.path.insert(0, '.')
import updater
sys.frozen = True
sys.executable = r"D:\工作文件夹\宠物定位器\P55\测试工具\PG-Power\dist\PG-Power_v2.0.14.exe"
need, bp = updater.apply_update(
    r"D:\Tools\Temp\PG-Power_v2.0.15.exe", sys.executable, wait_sec=1)
print(f"need_restart={need}, bat={bp}")

for p in [bp, bp.replace('.bat', '.vbs')]:
    if os.path.exists(p):
        raw = open(p, 'rb').read()
        text = raw.decode('gbk') if p.endswith('.bat') else raw.decode('ascii')
        print(f"\n=== {os.path.basename(p)} ({len(raw)} bytes) ===")
        print(text)
