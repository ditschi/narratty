"""A stand-in for the project's real build: slow on purpose, writes into dist/."""

import pathlib
import time

for step in ("compile", "test", "package"):
    print(f"[{step}] ...", flush=True)
    time.sleep(1)
pathlib.Path("dist").mkdir(exist_ok=True)
pathlib.Path("dist/report.txt").write_text("greeter 1.0: 3 steps, all green\n")
print("build finished")
