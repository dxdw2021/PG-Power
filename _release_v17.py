"""v2.0.17 一键发版"""
import os, re, json, sys, subprocess, shutil, time

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

# 1. 改版本号
with open('main.py', 'r', encoding='utf-8') as f:
    c = f.read()
old_v = re.search(r'APP_VERSION = "([^"]+)"', c).group(1)
c_new = c.replace(f'APP_VERSION = "{old_v}"', 'APP_VERSION = "2.0.17"')
with open('main.py', 'w', encoding='utf-8') as f:
    f.write(c_new)
print(f"1. main.py: {old_v} → 2.0.17")

# 2. 验证 apply_update 是 PowerShell
updater = open('updater.py', encoding='utf-8').read()
assert 'powershell.exe' in updater, "❌ 不是 PowerShell!"
assert 'pg_power_update.vbs' not in updater, "❌ 还有 VBS!"
assert 'Move-Item' in updater, "❌ 无 Move-Item!"
print("2. updater.py ✅ PowerShell 方案")

# 3. PyInstaller
shutil.rmtree('build', ignore_errors=True)
print("3. PyInstaller 打包...")
r = subprocess.run(['venv/Scripts/pyinstaller', 'pg-power.spec', '--noconfirm'],
                   capture_output=True, text=True, encoding='utf-8', errors='ignore')
exe = 'dist/PG-Power_v2.0.17.exe'
size = os.path.getsize(exe) / 1024 / 1024
print(f"   ✅ {exe} ({size:.1f}MB)")

# 4. 归档
os.makedirs('releases', exist_ok=True)
shutil.copy2(exe, 'releases/PG-Power_v2.0.17.exe')
print("4. 归档到 releases/")

# 5. commit + tag + push
print("5. git commit + tag + push...")
subprocess.run(['git', 'add', '-A'], check=True)
subprocess.run(['git', 'commit', '-m', 'fix: PowerShell独立进程修复更新替换 v2.0.17'],
               check=True, capture_output=True)
subprocess.run(['git', 'tag', '-f', 'v2.0.17'], check=True)
for remote in ['origin', 'github']:
    subprocess.run(['git', 'push', remote, 'master', '--tags', '-f'], check=True)
print("   ✅ 双仓库 push 完成")

# 6. 等 GitCode 索引 + 更新 version.json
print("6. 更新 version.json...")
time.sleep(3)

import urllib.request
token = os.environ.get('AG_TOKEN', '')
req = urllib.request.Request(
    'https://gitcode.com/api/v5/repos/dxdw2021/PG-Power/contents/releases/PG-Power_v2.0.17.exe?ref=master',
    headers={'PRIVATE-TOKEN': token}
)
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        info = json.loads(r.read())
    exe_url = info['download_url']
    print(f"   ✅ blobs URL: {exe_url[:80]}...")
except urllib.error.HTTPError as e:
    print(f"   ❌ contents API {e.code}, 等 5s 重试...")
    time.sleep(5)
    with urllib.request.urlopen(req, timeout=10) as r:
        info = json.loads(r.read())
    exe_url = info['download_url']
    print(f"   ✅ blobs URL: {exe_url[:80]}...")

vj = {
    'version': '2.0.17',
    'exe_url': exe_url,
    'notes': 'v2.0.17: PowerShell独立进程修复更新替换, GitCode blobs 5.9MB/s'
}
with open('version.json', 'w', encoding='utf-8') as f:
    json.dump(vj, f, indent=2, ensure_ascii=False)
    f.write('\n')

# 7. push version.json
subprocess.run(['git', 'add', 'version.json'], check=True)
subprocess.run(['git', 'commit', '-m', 'chore: version.json v2.0.17'],
               check=True, capture_output=True)
subprocess.run(['git', 'push', 'origin', 'master'], check=True)
subprocess.run(['git', 'push', 'github', 'master'], check=True)

print()
print("=" * 60)
print("✅ v2.0.17 发版完成!")
print()
print("🧪 测试方案:")
print("  方案 A: 直接跑 v2.0.17 exe, 假装自己是 v2.0.16")
print("    (改 main.py APP_VERSION='2.0.16' 再打包)")
print()
print("  方案 B: 在 v2.0.17 里手动触发 apply_update")
print("    (Python 控制台调用 updater.apply_update)")
print()
print("  替换失败看: %TEMP%\\pg_power_update.log")
print("=" * 60)
