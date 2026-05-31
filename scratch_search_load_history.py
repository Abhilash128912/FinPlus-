import re

with open(r'C:\Users\AbhilashBabu\FINALXYUP.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Let's search for "load_history"
lines = content.splitlines()
for i, line in enumerate(lines):
    if 'load_history' in line:
        print(f"Line {i+1}: {line.strip()}")
