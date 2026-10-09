"""在 updater.py 里加 GitCode 支持"""
import os

with open('updater.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在 check_update 函数里加 gitcode_repo 源 (在 github_repo 之前, 优先走 GitCode)
old_block = '''    github_repo = (config or {}).get("github_repo", "").strip()
    gitlab_repo = (config or {}).get("gitlab_repo", "").strip()
    static_url = (config or {}).get("static_url", "").strip()
    if github_repo:
        sources.append(("github", lambda: _check_github(github_repo)))
    if gitlab_repo:
        sources.append(("gitlab", lambda: _check_gitlab(gitlab_repo)))
    if static_url:
        sources.append(("static", lambda: _check_static(static_url)))'''

new_block = '''    gitcode_repo = (config or {}).get("gitcode_repo", "").strip()
    github_repo = (config or {}).get("github_repo", "").strip()
    gitlab_repo = (config or {}).get("gitlab_repo", "").strip()
    static_url = (config or {}).get("static_url", "").strip()
    # GitCode 优先 (国内快)
    if gitcode_repo:
        sources.append(("gitcode", lambda: _check_gitcode(gitcode_repo)))
    if github_repo:
        sources.append(("github", lambda: _check_github(github_repo)))
    if gitlab_repo:
        sources.append(("gitlab", lambda: _check_gitlab(gitlab_repo)))
    if static_url:
        sources.append(("static", lambda: _check_static(static_url)))'''

assert old_block in content, "找不到 check_update 里的配置块!"
content = content.replace(old_block, new_block)

# 2. 加 _check_gitcode 函数 (在 _check_github 之前)
gitcode_func = '''
def _check_gitcode(repo):
    """GitCode API: contents 读 version.json (国内速度快)"""
    import base64
    # 优先: contents API 读 version.json 文件
    url = f"https://gitcode.com/api/v5/repos/{repo}/contents/version.json?ref=master"
    data = _http_get_json(url)
    if data and data.get("type") == "file" and data.get("content"):
        try:
            raw = base64.b64decode(data["content"]).decode("utf-8")
            import json as _j
            vj = _j.loads(raw)
            return {"tag": vj.get("version", ""),
                    "exe_url": vj.get("exe_url", ""),
                    "notes": vj.get("notes", "")}
        except Exception:
            pass
    # 降级: Release API
    url2 = f"https://gitcode.com/api/v5/repos/{repo}/releases/latest"
    data2 = _http_get_json(url2)
    if data2:
        exe_url = _discover_asset_from_api(data2)
        tag = data2.get("tag_name", "")
        if exe_url and tag:
            return {"tag": tag, "exe_url": exe_url, "notes": data2.get("body", "")[:4000]}
    return None


'''

# 插入在 _check_github 之前
content = content.replace('\ndef _check_github(repo):\n', gitcode_func + 'def _check_github(repo):\n')

# 3. 改 _default_static_candidates 也加 GitCode
old_static = '''def _default_static_candidates():
    """基于 github_repo 自动推导几个 CDN 版本文件地址, 国内可用"""
    cfg = _last_config or {}
    gh = (cfg.get("github_repo") or "").strip()
    urls = []
    if gh:
        # 优先直接读 GitHub raw (最准, 刚 push 就生效), 国内不通则自动降级 CDN
        urls.append(f"https://raw.githubusercontent.com/{gh}/master/version.json")
        urls.append(f"https://cdn.jsdelivr.net/gh/{gh}@master/version.json?v=1")
        urls.append(f"https://fastly.jsdelivr.net/gh/{gh}@master/version.json")
        urls.append(f"https://raw.fastgit.org/{gh}/master/version.json")
    return urls'''

new_static = '''def _default_static_candidates():
    """基于 repo 自动推导 CDN 版本文件地址, 国内优先"""
    cfg = _last_config or {}
    urls = []
    # GitCode contents API (国内最快, 排第一)
    gc = (cfg.get("gitcode_repo") or "").strip()
    if gc:
        urls.append(f"https://gitcode.com/api/v5/repos/{gc}/contents/version.json?ref=master&_type=gitcode")
    # GitHub raw + CDN 降级
    gh = (cfg.get("github_repo") or "").strip()
    if gh:
        urls.append(f"https://raw.githubusercontent.com/{gh}/master/version.json")
        urls.append(f"https://cdn.jsdelivr.net/gh/{gh}@master/version.json?v=1")
        urls.append(f"https://fastly.jsdelivr.net/gh/{gh}@master/version.json")
        urls.append(f"https://raw.fastgit.org/{gh}/master/version.json")
    return urls'''

content = content.replace(old_static, new_static)

# 4. _check_static 函数里处理 GitCode contents 格式 (base64)
# 找到 _check_static, 在开头加个 gitcode 特殊处理
old_static_check = '''def _check_static(url):
    """从静态 JSON 读取版本"""
    data = _http_get_json(url)
    if not data:
        return None'''

new_static_check = '''def _check_static(url):
    """从静态 JSON 读取版本 (支持 GitCode contents base64 格式)"""
    data = _http_get_json(url)
    if not data:
        return None
    # GitCode contents API 返回 {type, content(base64), ...}
    if data.get("type") == "file" and data.get("content"):
        try:
            import base64 as _b64
            import json as _j
            raw = _b64.b64decode(data["content"]).decode("utf-8")
            vj = _j.loads(raw)
            return {"tag": vj.get("version", ""),
                    "exe_url": vj.get("exe_url", ""),
                    "notes": vj.get("notes", "")}
        except Exception:
            pass'''

content = content.replace(old_static_check, new_static_check)

with open('updater.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
ast.parse(content)
print("✅ updater.py 加 GitCode 支持成功, 语法 OK")
print()
for ch in ['gitcode_repo', '_check_gitcode', 'gitcode.com/api/v5/repos']:
    print(f"  {ch}: {ch in content}")
