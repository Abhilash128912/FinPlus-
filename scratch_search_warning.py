import re

with open(r'C:\Users\AbhilashBabu\FINALXYUP.py', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.splitlines()
for i, line in enumerate(lines):
    if 'historical data not loaded' in line.lower() or 'wait for auto-refresh' in line.lower():
        print(f"Line {i+1}: {line.strip()}")
