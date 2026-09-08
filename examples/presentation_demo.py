"""Replay the bundled response fixtures and summarize their actual contract diff."""
import json
import subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
result=subprocess.run([str(root/".venv/bin/tooldrift"),"run","--old","deepseek","--new","qwen","--from-fixtures","--format","json"],cwd=root,text=True,capture_output=True)
report=json.loads(result.stdout)
print("fixture comparison exit:",result.returncode)
for tool in report["tools"]:
    print(json.dumps({"tool":tool["tool"],"differing_fields":[f["field"] for f in tool["fields"]]},ensure_ascii=False))
assert result.returncode == 1
print("Scope: bundled offline response fixtures; these are not current provider measurements.")
