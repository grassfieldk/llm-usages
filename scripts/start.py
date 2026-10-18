from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
python = root / ".venv/Scripts/pythonw.exe"
if not python.exists():
    raise SystemExit("先に mise run setup を実行してください")
subprocess.Popen([str(python), str(root / "app.py")], cwd=root)
