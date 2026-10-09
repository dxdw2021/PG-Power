import sys, os
# 让 v2.0.12 假装是 v2.0.11 来测试更新到真正的 v2.0.12
os.environ["APP_VERSION_OVERRIDE"] = "2.0.11"
sys.argv = ["main.py"]
os.chdir(os.path.dirname(os.path.abspath(__file__)))
exec(open("main.py", encoding="utf-8").read())