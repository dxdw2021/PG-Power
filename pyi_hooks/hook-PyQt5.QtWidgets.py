# -*- mode: python ; coding: utf-8 -*-
# 自定义 PyQt5.QtWidgets hook - 绕过中文路径编码问题
# 所有 Qt 二进制和插件已在 spec 文件中手动指定
from PyQt5 import QtWidgets

hiddenimports = [
    'PyQt5.sip',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
]

# 返回空列表，避免调用 add_qt5_dependencies() 触发中文路径编码问题
binaries = []
datas = []
