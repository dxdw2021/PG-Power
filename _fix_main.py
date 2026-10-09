import os

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. L888 空配置
content = content.replace(
    'self.update_config = {"github_repo":"","gitlab_repo":"","static_url":""}',
    'self.update_config = {"gitcode_repo":"dxdw2021/PG-Power","github_repo":"","gitlab_repo":"","static_url":""}'
)

# 2. L3225 硬编码配置
old2 = '''# 在线更新配置 (github_repo 硬编码, 不从 QSettings 读 — 旧版本可能污染空串)
self._update_config = {
    "github_repo": "dxdw2021/PG-Power",
    "gitlab_repo": "",
    "static_url":  "",
}'''

new2 = '''# 在线更新配置 (GitCode 优先, 国内速度快)
self._update_config = {
    "gitcode_repo": "dxdw2021/PG-Power",
    "github_repo":  "dxdw2021/PG-Power",
    "gitlab_repo":  "",
    "static_url":   "",
}'''

content = content.replace(old2, new2)

# 3. 版本号 2.0.14 -> 2.0.15
content = content.replace('APP_VERSION = "2.0.14"', 'APP_VERSION = "2.0.15"')

# 4. version.json 更新
with open('version.json', 'r', encoding='utf-8') as f:
    import json
    vj = json.load(f)
vj['version'] = '2.0.15'
# exe_url 先占位, 等 Release 创建后再改
with open('version.json', 'w', encoding='utf-8') as f:
    json.dump(vj, f, indent=2, ensure_ascii=False)
    f.write('\n')

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ main.py + version.json 已更新")
print()
print("main.py 配置检查:")
for line in content.split('\n'):
    if 'gitcode_repo' in line or 'APP_VERSION' in line:
        print(f"  {line.strip()}")
