# -*- mode: python ; coding: utf-8 -*-
# 自定义 PyQt5.QtCore hook - 绕过中文路径编码问题
# 所有 Qt 二进制和插件已在 spec 文件中手动指定
from PyQt5 import QtCore

hiddenimports = []
binaries = []
datas = []
