from pathlib import Path
import subprocess
import sys
import venv

root = Path(__file__).resolve().parents[1]
venv.EnvBuilder(with_pip=True).create(root / ".venv")
subprocess.run([str(root / ".venv/Scripts/python.exe"), "-m", "pip", "install", "-r", str(root / "requirements.txt")], check=True)
