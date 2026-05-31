with open(r'C:\Users\AbhilashBabu\FINALXYUP.py', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.read().splitlines() if hasattr(content, 'read') else content.splitlines()
for i, line in enumerate(lines):
    if i >= 3680 and i <= 3777:
        clean_line = line.encode('ascii', errors='replace').decode('ascii')
        print(f"Line {i+1}: {clean_line.strip()}")
