import shutil
import subprocess
import sys

def check_dependencies():
    errors = []
    if not shutil.which("node"):
        errors.append("Node.js未安装，请先安装：https://nodejs.org/")
    else:
        try:
            result = subprocess.run(["node", "-e", "require('koffi'); console.log('ok')"],
                                  capture_output=True, text=True, timeout=5)
            if "ok" not in result.stdout:
                errors.append("koffi模块未安装，请运行：npm install koffi")
        except Exception:
            errors.append("koffi模块检测失败")
    return errors

if __name__ == "__main__":
    errors = check_dependencies()
    if errors:
        for e in errors:
            print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    print("✅ 依赖检查通过")
