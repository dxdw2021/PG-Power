"""
PG-Power 在线更新模块
--------------------
支持 3 种发布源（依次尝试，第一个成功就用）:
    1. GitHub Release API         : https://api.github.com/repos/{owner}/{repo}/releases/latest
    2. GitLab/Gitee API (公共项目) : https://gitee.com/api/v5/repos/{owner}/{repo}/releases/latest
                                    (gitcode 若无公网 API 则自动跳过)
    3. 静态版本文件 (兜底)         : 用户在设置里填一个可公开访问的 JSON URL
                                    JSON 格式:
                                    {
                                        "version": "2.0.2",
                                        "exe_url": "https://.../PG-Power_v2.0.2.exe",
                                        "notes": "12V 电压支持"
                                    }

设计目标: 零第三方依赖, 只用 Python 标准库
"""

import os, sys, json, time, shutil, tempfile, subprocess, threading, logging
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

logger = logging.getLogger("PG-Power.updater")

UPDATE_CHECK_TIMEOUT = 10
DOWNLOAD_CHUNK = 64 * 1024


def _http_get_json(url, headers=None, timeout=UPDATE_CHECK_TIMEOUT):
    try:
        hdrs = {"User-Agent": "PG-Power-Updater/1.0", "Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        req = Request(url, headers=hdrs)
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError, json.JSONDecodeError, TimeoutError, OSError) as e:
        logger.debug(f"[updater] GET {url} 失败: {e}")
        return None


def _parse_version(v):
    v = v.strip().lstrip("vV")
    for sep in ("-", "_", "+"):
        if sep in v:
            v = v.split(sep)[0]
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def compare_versions(a, b):
    pa, pb = _parse_version(a), _parse_version(b)
    if pa > pb:
        return 1
    if pa < pb:
        return -1
    return 0


def _discover_asset_from_api(data):
    assets = data.get("assets") or []
    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(".exe"):
            return a.get("browser_download_url") or a.get("url")
    for a in assets:
        url = a.get("browser_download_url") or a.get("url") or a.get("link")
        if url and str(url).lower().endswith(".exe"):
            return url
    return None


def check_update(current_version, config):
    result = {"available": False, "latest": None, "exe_url": None,
              "notes": None, "source": None, "error": None}
    sources = []
    github_repo = (config or {}).get("github_repo", "").strip()
    gitlab_repo = (config or {}).get("gitlab_repo", "").strip()
    static_url = (config or {}).get("static_url", "").strip()
    if github_repo:
        sources.append(("github", lambda: _check_github(github_repo)))
    if gitlab_repo:
        sources.append(("gitlab", lambda: _check_gitlab(gitlab_repo)))
    if static_url:
        sources.append(("static", lambda: _check_static(static_url)))
    if not sources:
        result["error"] = "未配置任何发布源 (github_repo / gitlab_repo / static_url 均为空)"
        return result
    last_err = None
    for name, getter in sources:
        data = getter()
        if not data:
            continue
        tag = data.get("tag") or data.get("version")
        exe_url = data.get("exe_url")
        if not tag or not exe_url:
            last_err = f"{name} 返回数据缺少 tag 或 exe_url 字段"
            continue
        cmp = compare_versions(tag, current_version)
        if cmp > 0:
            result.update(available=True, latest=tag, exe_url=exe_url,
                          notes=data.get("notes", ""), source=name)
            return result
        else:
            last_err = f"{name} 最新版本 {tag} 不高于当前 {current_version}"
    result["error"] = last_err or "所有发布源都无更新"
    return result


def _check_github(repo):
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    data = _http_get_json(url)
    if not data:
        return None
    exe_url = _discover_asset_from_api(data)
    tag = data.get("tag_name", "")
    body = data.get("body", "") or ""
    if not exe_url or not tag:
        return None
    return {"tag": tag, "exe_url": exe_url, "notes": body[:4000]}


def _check_gitlab(repo):
    for api_base in ("https://gitee.com/api/v5/repos",
                     "https://gitcode.com/api/v5/repos"):
        url = f"{api_base}/{repo}/releases/latest"
        data = _http_get_json(url)
        if data:
            assets = data.get("assets") or data.get("assets_info") or []
            exe_url = None
            for a in assets:
                u = a.get("browser_download_url") or a.get("url")
                if u and u.lower().endswith(".exe"):
                    exe_url = u
                    break
            tag = data.get("tag_name", "")
            body = data.get("body", "") or data.get("description", "") or ""
            if tag and exe_url:
                return {"tag": tag, "exe_url": exe_url, "notes": body[:4000]}
    return None


def _check_static(url):
    data = _http_get_json(url)
    if not data:
        return None
    tag = data.get("version") or data.get("tag")
    exe_url = data.get("exe_url")
    notes = data.get("notes", "")
    if not tag or not exe_url:
        return None
    return {"tag": tag, "exe_url": exe_url, "notes": notes}


def download_exe(url, dest_path, progress_cb=None):
    try:
        req = Request(url, headers={
            "User-Agent": "PG-Power-Updater/1.0", "Accept": "*/*"})
        with urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            received = 0
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(received, total)
                        except Exception:
                            pass
        return True, received
    except (URLError, HTTPError, TimeoutError, OSError) as e:
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        return False, str(e)


def apply_update(new_exe_path, current_exe_path, wait_sec=3):
    current_exe_path = os.path.abspath(current_exe_path)
    new_exe_path = os.path.abspath(new_exe_path)
    if not getattr(sys, "frozen", False):
        shutil.copy2(new_exe_path, current_exe_path)
        return False, None
    bat_path = os.path.join(tempfile.gettempdir(), "pg_power_update.bat")
    bat_content = f"""@echo off
chcp 65001 >nul
echo PG-Power 正在更新...
timeout /t {max(3, wait_sec)} /nobreak >nul
:retry
if not exist "{current_exe_path}" goto do_copy
timeout /t 1 /nobreak >nul
goto retry
:do_copy
copy /y "{new_exe_path}" "{current_exe_path}"
start "" "{current_exe_path}"
del /q "%~f0"
"""
    try:
        with open(bat_path, "w", encoding="gbk") as f:
            f.write(bat_content)
    except OSError as e:
        logger.error(f"写 bootstrap 脚本失败: {e}")
        return False, None
    try:
        subprocess.Popen(["cmd", "/c", bat_path],
                         creationflags=subprocess.CREATE_NO_WINDOW)
    except OSError as e:
        logger.error(f"启动 bootstrap 脚本失败: {e}")
        return False, None
    return True, bat_path


def current_exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))
