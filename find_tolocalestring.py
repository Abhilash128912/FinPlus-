import os

file_path = r'd:\FINPLUS PNL APP\src\App.jsx'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('tolocalestring_report.txt', 'w', encoding='utf-8') as out:
    for i, line in enumerate(lines):
        if 'toLocaleString' in line:
            out.write(f"Line {i+1}: {line.strip()}\n")

print("REPORT_GENERATED")
