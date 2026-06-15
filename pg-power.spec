# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import glob

block_cipher = None

# ---------- 手动收集 PyQt5 Qt 文件 ----------
# 直接在 spec 中计算路径，避免 PyInstaller 的 Qt 钩子在中文路径下编码出错

PROJECT_DIR = os.getcwd()

pyqt5_dir = os.path.join(
    PROJECT_DIR,
    "venv", "Lib", "site-packages", "PyQt5"
)
qt5_dir = os.path.join(pyqt5_dir, "Qt5")

# 收集 Qt bin 下的 .dll
qt_binaries = []
bin_dir = os.path.join(qt5_dir, "bin")
if os.path.isdir(bin_dir):
    for f in os.listdir(bin_dir):
        if f.lower().endswith('.dll'):
            qt_binaries.append((os.path.join(bin_dir, f), 'PyQt5/Qt5/bin'))

# 收集 Qt plugins 下的所有文件（保持 PyQt5/ 前缀）
qt_datas = []
plugins_dir = os.path.join(qt5_dir, "plugins")
if os.path.isdir(plugins_dir):
    for root, dirs, files in os.walk(plugins_dir):
        for f in files:
            src = os.path.join(root, f)
            # 保留 PyQt5/ 前缀：PyQt5/Qt5/plugins/...
            rel = os.path.relpath(root, os.path.dirname(pyqt5_dir))
            qt_datas.append((src, rel))

# 收集 PyQt5 目录下的 .pyd 文件
pyd_datas = []
for f in os.listdir(pyqt5_dir):
    if f.lower().endswith('.pyd'):
        pyd_datas.append((os.path.join(pyqt5_dir, f), 'PyQt5'))

# ni4882.dll
ni4882_dll = os.path.join(PROJECT_DIR, 'ni4882.dll')
ni4882_datas = [(ni4882_dll, '.')] if os.path.exists(ni4882_dll) else []

# libusb-1.0.dll
libusb_dll = os.path.join(PROJECT_DIR, 'libusb-1.0.dll')
libusb_datas = [(libusb_dll, '.')] if os.path.exists(libusb_dll) else []

# icon.ico
icon_ico = os.path.join(PROJECT_DIR, 'icon.ico')
icon_datas = [(icon_ico, '.')] if os.path.exists(icon_ico) else []

# 合并所有 data
all_datas = qt_datas + pyd_datas + ni4882_datas + libusb_datas + icon_datas
all_binaries = qt_binaries

# ---------- 配置 Analysis ----------
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=[
        'PyQt5.sip',
        'PyQt5.QtCore',
        'PyQt5.QtWidgets',
        'PyQt5.QtGui',
        'pyqtgraph',
        'numpy',
        'usb.core',
        'usb.backend.libusb1',
        'lupa',
    ],
    hookspath=[os.path.join(PROJECT_DIR, 'pyi_hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不必要的 Qt 模块，减小体积
        'PyQt5.QtBluetooth',
        'PyQt5.QtDBus',
        'PyQt5.QtDesigner',
        'PyQt5.QtHelp',
        'PyQt5.QtLocation',
        'PyQt5.QtMultimedia',
        'PyQt5.QtMultimediaWidgets',
        'PyQt5.QtNetwork',
        'PyQt5.QtNfc',
        'PyQt5.QtOpenGL',
        'PyQt5.QtPositioning',
        'PyQt5.QtPrintSupport',
        'PyQt5.QtQml',
        'PyQt5.QtQuick',
        'PyQt5.QtQuick3D',
        'PyQt5.QtRemoteObjects',
        'PyQt5.QtSensors',
        'PyQt5.QtSerialPort',
        'PyQt5.QtSql',
        'PyQt5.QtSvg',
        'PyQt5.QtTest',
        'PyQt5.QtTextToSpeech',
        'PyQt5.QtWebChannel',
        'PyQt5.QtWebSockets',
        'PyQt5.QtWebView',
        'PyQt5.QtXml',
        'PyQt5.QtXmlPatterns',
        'PyQt5.QtWinExtras',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PG-Power',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI 模式，无控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_DIR, 'icon.ico'),
)
