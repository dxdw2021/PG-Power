"""GitCode 自动创建 Release + 上传 exe"""
import os, json, urllib.request, urllib.error, time, subprocess

token = os.environ.get('AG_TOKEN', '')
repo = 'dxdw2021/PG-Power'
tag = 'v2.0.16'
exe_path = 'dist/PG-Power_v2.0.16.exe'
exe_size = os.path.getsize(exe_path)

print(f"exe: {exe_path} ({exe_size/1024/1024:.1f}MB)")
print()

# 1. 获取/创建 tag
print("=== 1. tag ===")
r = subprocess.run(['git', 'ls-remote', 'origin', f'refs/tags/{tag}'],
                   capture_output=True, text=True)
if r.stdout.strip():
    print(f"  已存在: {tag}")
else:
    r2 = subprocess.run(['git', 'log', '-1', '--format=%H'], capture_output=True, text=True)
    sha = r2.stdout.strip()
    data = json.dumps({'ref': tag, 'sha': sha}).encode()
    req = urllib.request.Request(
        f'https://gitcode.com/api/v5/repos/{repo}/git/tags',
        data=data,
        headers={'PRIVATE-TOKEN': token, 'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"  ✅ 创建 tag: {json.loads(r.read()).get('name')}")
    except urllib.error.HTTPError as e:
        print(f"  ❌ {e.code}: {e.read().decode()[:200]}")

# 2. 创建 Release
print("\n=== 2. Release ===")
release_data = json.dumps({
    'tag_name': tag,
    'name': f'PG-Power {tag}',
    'body': 'v2.0.16: PowerShell独立进程修复更新替换\n\n- 国内 GitCode 下载源\n- 纯 PowerShell 独立进程\n- move→copy 降级 + pg_power_update.log 追踪',
    'target_commitish': 'master',
}).encode()

req = urllib.request.Request(
    f'https://gitcode.com/api/v5/repos/{repo}/releases',
    data=release_data,
    headers={'PRIVATE-TOKEN': token, 'Content-Type': 'application/json'},
    method='POST'
)
release_id = None
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        rel = json.loads(r.read())
    release_id = rel.get('id')
    print(f"  ✅ id={release_id}, name={rel.get('name')}")
except urllib.error.HTTPError as e:
    body = e.read().decode()[:300]
    print(f"  创建 release: {e.code} {body}")
    # 已有则取现有的
    try:
        req2 = urllib.request.Request(
            f'https://gitcode.com/api/v5/repos/{repo}/releases/tags/{tag}',
            headers={'PRIVATE-TOKEN': token}
        )
        with urllib.request.urlopen(req2, timeout=10) as r:
            rel = json.loads(r.read())
        release_id = rel.get('id')
        print(f"  已有 release: id={release_id}")
    except urllib.error.HTTPError as e2:
        print(f"  GET release: {e2.code}")

# 3. 上传附件
if release_id:
    print(f"\n=== 3. 上传 exe -> release {release_id} ===")
    exe_data = open(exe_path, 'rb').read()
    boundary = '----PGPowerBoundary'
    
    parts = []
    parts.append(f'--{boundary}'.encode())
    parts.append(b'Content-Disposition: form-data; name="file"; filename="PG-Power_v2.0.16.exe"')
    parts.append(b'Content-Type: application/octet-stream')
    parts.append(b'')
    parts.append(exe_data)
    parts.append(f'--{boundary}--'.encode())
    parts.append(b'')
    body = b'\r\n'.join(parts)
    
    req = urllib.request.Request(
        f'https://gitcode.com/api/v5/repos/{repo}/releases/{release_id}/attach_files',
        data=body,
        headers={
            'PRIVATE-TOKEN': token,
            'Content-Type': f'multipart/form-data; boundary={boundary}',
        },
        method='POST'
    )
    try:
        print(f"  上传中 ({exe_size/1024/1024:.0f}MB)...", flush=True)
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=600) as r:
            result = json.loads(r.read())
        dt = time.time() - t0
        print(f"  ✅ 上传成功! {dt:.1f}s ({exe_size/dt/1024/1024:.1f} MB/s)")
        print(f"     {json.dumps(result, indent=2, ensure_ascii=False)[:400]}")
    except urllib.error.HTTPError as e:
        print(f"  ❌ HTTP {e.code}")
        print(f"     {e.read().decode()[:300]}")
else:
    print("\n❌ 没有 release id, 无法上传附件")
