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
            return json.loads(resp.read().decode("utf-8-sig"))
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


_last_config = None

def _default_static_candidates():
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
    return urls

def check_update(current_version, config):
    result = {"available": False, "latest": None, "exe_url": None,
              "notes": None, "source": None, "error": None}
    sources = []
    global _last_config; _last_config = config
    gitcode_repo = (config or {}).get("gitcode_repo", "").strip()
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
        sources.append(("static", lambda: _check_static(static_url)))
    # 根据 github_repo 自动推导 CDN 静态版本 (用户无需手动配置)
    for au in _default_static_candidates():
        sources.append((f"static-auto({au.split('/')[2]})", lambda u=au: _check_static(u)))
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
        '"process exited, cleaning leftover _MEI* dirs..." >> $log',
        "$tmpDir = [System.IO.Path]::GetTempPath()",
        "Get-ChildItem -Path $tmpDir -Directory -Filter \"_MEI*\" -ErrorAction SilentlyContinue | ForEach-Object {",
        "    try {",
        "        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue",
        '        \"cleaned $($_.FullName)\" >> $log',
        "    } catch {",
        '        \"clean failed: $($_.FullName) - $_\" >> $log',
        "    }",
        "}",
        "Start-Sleep -Seconds 2",
        '"moving..." >> $log',
        "try {",
        "    Move-Item -LiteralPath " + DQ + np_ + DQ + " -Destination " + DQ + cp_ + DQ + " -Force >> $log 2>&1",
        '    "move OK" >> $log',
        "} catch {",
        '    "move failed: $_" >> $log',
        "    try { Copy-Item -LiteralPath " + DQ + np_ + DQ + " -Destination " + DQ + cp_ + DQ + " -Force >> $log 2>&1; 'copy OK' >> $log }",
        '    catch { "copy failed: $_" >> $log }',
        "}",
        '"launching..." >> $log',
        "Start-Sleep -Seconds 3",
        "$ok = $false",
        "for ($i = 1; $i -le 3; $i++) {",
        "    try {",
        "        $sp = Start-Process -FilePath " + DQ + cp_ + DQ + " -PassThru",
        '        "attempt $i started PID=$($sp.Id)" >> $log',
        "        $verdict = " + DQ + "timeout" + DQ,
        "        $deadline = (Get-Date).AddSeconds(30)",
        "        while ((Get-Date) -lt $deadline) {",
        "            $alive = $false; $good = $false; $hasWin = $false",
        "            foreach ($q in @(Get-Process -Name " + DQ + proc_name + DQ + " -ErrorAction SilentlyContinue)) {",
        "                $alive = $true",
        "                if ($q.MainWindowTitle) {",
        "                    $hasWin = $true",
        "                    if ($q.MainWindowTitle -match " + DQ + "PG-Power \|" + DQ + ") { $good = $true }",
        "                }",
        "            }",
        "            if (-not $alive) { $verdict = " + DQ + "died" + DQ + "; break }",
        "            if ($good) { $verdict = " + DQ + "ok" + DQ + "; break }",
        "            if ($hasWin) { $verdict = " + DQ + "errwin" + DQ + "; break }",
        "            Start-Sleep -Seconds 1",
        "        }",
        '        "attempt $i verdict=$verdict" >> $log',
        "        if ($verdict -eq " + DQ + "ok" + DQ + ") { $ok = $true; break }",
        '        "attempt $i killing and cleaning _MEI..." >> $log',
        "        Get-Process -Name " + DQ + proc_name + DQ + " -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue",
        "        Start-Sleep -Seconds 2",
        "        Get-ChildItem -Path $tmpDir -Directory -Filter " + DQ + "_MEI*" + DQ + " -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue",
        "    } catch {",
        '        "attempt $i error: $_" >> $log',
        "    }",
        "    Start-Sleep -Seconds 3",
        "}",
        'if ($ok) { "launched ok" >> $log } else {',
        '    "ALL 3 LAUNCH ATTEMPTS FAILED" >> $log',
        '    try {',
        '        $wsh = New-Object -ComObject WScript.Shell',
        '        $wsh.Popup("更新文件已替换, 但新版启动失败. 请手动运行: ' + cp_ + '", 0, "PG-Power Update", 16) | Out-Null',
        '    } catch { }',
        "}",
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

def current_exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))
