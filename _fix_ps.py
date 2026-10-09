"""修复 updater.py apply_update → PowerShell 独立进程"""
import os

with open("updater.py", "r", encoding="utf-8") as f:
    content = f.read()

start = content.find('def apply_update(new_exe_path')
end = content.find('def current_exe_dir')
print(f"replace chars {start}-{end}")

# 用列表 + join 构建 PowerShell 脚本, 避免引号嵌套问题
new_apply = '''def apply_update(new_exe_path, current_exe_path, wait_sec=3):
    """PowerShell 独立进程: 原生支持 Unicode 中文路径"""
    import subprocess as _sp
    current_exe_path = os.path.abspath(current_exe_path)
    new_exe_path = os.path.abspath(new_exe_path)
    proc_name = os.path.splitext(os.path.basename(current_exe_path))[0]

    if not getattr(sys, "frozen", False):
        try:
            shutil.copy2(new_exe_path, current_exe_path)
            logger.info("[更新] dev 模式: 已覆盖, 请手动重启")
        except OSError as e:
            logger.error(f"[更新] copy 失败: {e}")
        return False, None

    log_p = os.path.join(tempfile.gettempdir(), "pg_power_update.log")
    ps1_p = os.path.join(tempfile.gettempdir(), "pg_power_update.ps1")
    NL = chr(13) + chr(10)
    DQ = chr(34)

    lp = log_p.replace(os.sep, "/")
    np_ = new_exe_path.replace(os.sep, "/")
    cp_ = current_exe_path.replace(os.sep, "/")

    lines = [
        "$ErrorActionPreference = 'Continue'",
        "$log = " + DQ + lp + DQ,
        '"update start" > $log',
        '"new=' + np_ + '" >> $log',
        '"cur=' + cp_ + '" >> $log',
        '"proc=' + proc_name + '" >> $log',
        'Start-Sleep -Seconds ' + str(max(3, wait_sec)),
        '"waiting process exit..." >> $log',
        "$deadline = (Get-Date).AddSeconds(60)",
        "while ((Get-Date) -lt $deadline) {",
        "    $p = Get-Process -Name " + DQ + proc_name + DQ + " -ErrorAction SilentlyContinue",
        "    if (-not $p) { break }",
        "    Start-Sleep -Seconds 1",
        "}",
        '"process exited, moving..." >> $log',
        "try {",
        "    Move-Item -LiteralPath " + DQ + np_ + DQ + " -Destination " + DQ + cp_ + DQ + " -Force >> $log 2>&1",
        '    "move OK" >> $log',
        "} catch {",
        '    "move failed: $_" >> $log',
        "    try { Copy-Item -LiteralPath " + DQ + np_ + DQ + " -Destination " + DQ + cp_ + DQ + " -Force >> $log 2>&1; 'copy OK' >> $log }",
        '    catch { "copy failed: $_" >> $log }',
        "}",
        '"launching..." >> $log',
        "Start-Process -FilePath " + DQ + cp_ + DQ,
        '"launched, done" >> $log',
    ]
    ps_script = NL.join(lines) + NL

    try:
        with open(ps1_p, "w", encoding="utf-8-sig") as f:
            f.write(ps_script)
        logger.info(f"[更新] ps1 已生成: {ps1_p}")
    except OSError as e:
        logger.error(f"[更新] 写 ps1 失败: {e}")
        return False, None

    try:
        _sp.Popen(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden",
             "-ExecutionPolicy", "Bypass", "-File", ps1_p],
            creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
        )
        logger.info("[更新] PowerShell 已启动, 主进程即将退出")
    except OSError as e:
        logger.error(f"[更新] 启动 PowerShell 失败: {e}")
        return False, None

    return True, ps1_p

'''

content = content[:start] + new_apply + content[end:]
with open("updater.py", "w", encoding="utf-8") as f:
    f.write(content)

import ast
ast.parse(content)
print("OK 语法验证通过")

# 测试
import sys
sys.path.insert(0, ".")
import updater
sys.frozen = True
sys.executable = r"D:\工作文件夹\宠物定位器\P55\测试工具\PG-Power\dist\PG-Power_v2.0.14.exe"
need, ps1 = updater.apply_update(
    r"D:\Tools\Temp\PG-Power_v2.0.15.exe", sys.executable, wait_sec=1)
print(f"need_restart={need}, ps1={ps1}")

if os.path.exists(ps1):
    text = open(ps1, "r", encoding="utf-8-sig").read()
    print(f"\n=== 生成的 PowerShell 脚本 ({len(text)} chars) ===")
    print(text)
