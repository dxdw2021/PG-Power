"""v2.0.16 发版: PowerShell + GitCode"""
import os, re, json, subprocess, shutil

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 1. 版本号
with open("main.py", "r", encoding="utf-8") as f:
    c = f.read()
old_v = re.search(r'APP_VERSION = "([^"]+)"', c).group(1)
c = c.replace(f'APP_VERSION = "{old_v}"', 'APP_VERSION = "2.0.16"')
with open("main.py", "w", encoding="utf-8") as f:
    f.write(c)
print(f"1. main.py: {old_v} → 2.0.16")

# 2. version.json
vj = {
    "version": "2.0.16",
    "exe_url": "https://gitcode.com/dxdw2021/PG-Power/releases/download/v2.0.16/PG-Power_v2.0.16.exe",
    "notes": "v2.0.16: PowerShell独立进程修复更新替换, 切换GitCode国内下载源"
}
with open("version.json", "w", encoding="utf-8") as f:
    json.dump(vj, f, indent=2, ensure_ascii=False)
    f.write("\n")
print("2. version.json → v2.0.16 (GitCode URL)")

# 3. 清 build
shutil.rmtree("build", ignore_errors=True)
print("3. build cleaned")

# 4. PyInstaller
print("4. PyInstaller 打包中...")
r = subprocess.run(
    ["venv/Scripts/pyinstaller", "pg-power.spec", "--noconfirm"],
    capture_output=True, text=True, encoding="utf-8", errors="ignore"
)
last_lines = [l for l in r.stdout.split("\n") if l.strip()][-5:]
for l in last_lines:
    print(f"   {l}")
exe_size = os.path.getsize("dist/PG-Power_v2.0.16.exe") / 1024 / 1024
print(f"   ✅ dist/PG-Power_v2.0.16.exe ({exe_size:.1f}MB)")

# 5. git
print("5. git commit + tag + push...")
subprocess.run(["git", "add", "-A"], check=True)
subprocess.run(["git", "commit", "-m",
    "fix: PowerShell独立进程修复更新替换, 切换GitCode国内下载源"],
    check=True, capture_output=True)
subprocess.run(["git", "tag", "-f", "v2.0.16"], check=True)
for remote in ["origin", "github"]:
    r = subprocess.run(["git", "push", remote, "master", "--tags", "-f"],
                      capture_output=True, text=True)
    print(f"   push {remote}: {r.returncode==0 and 'OK' or 'FAIL'}")

print("\n✅ v2.0.16 自动步骤完成!")
print("   exe: dist/PG-Power_v2.0.16.exe")
print("   下一步: 手动去 GitCode Release 页面上传 exe")
print("   URL: https://gitcode.com/dxdw2021/PG-Power/releases/edit/v2.0.16")
