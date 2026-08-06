content = open(r'd:\FINPLUS PNL APP\src\App.jsx', encoding='utf-8').read()
lines = content.splitlines(keepends=True)

# Find and remove the screener useEffect (lines ~404-544 original, now shifted)
# and the sortedScreenerData useMemo (lines ~560-587)
start_effect = None
end_effect = None
start_memo = None
end_memo = None

for i, l in enumerate(lines):
    if 'useEffect' in l and start_effect is None:
        # Check next few lines for screener context
        chunk = ''.join(lines[i:i+5])
        if 'screener' in chunk.lower() or 'screenerData' in chunk:
            start_effect = i
    if start_effect and end_effect is None and i > start_effect:
        # Look for closing of this effect
        if l.strip() == '}, [activeTab]);' or l.strip() == '  }, [activeTab]);':
            end_effect = i
            break

print(f"Effect block: {start_effect+1 if start_effect else 'NOT FOUND'} to {end_effect+1 if end_effect else 'NOT FOUND'}")

for i, l in enumerate(lines):
    if 'useMemo' in l and start_memo is None:
        chunk = ''.join(lines[i:i+5])
        if 'screener' in chunk.lower():
            start_memo = i
    if start_memo and end_memo is None and i > start_memo:
        if '}, [screenerData' in l or '], [screener' in l:
            end_memo = i
            break

print(f"Memo block: {start_memo+1 if start_memo else 'NOT FOUND'} to {end_memo+1 if end_memo else 'NOT FOUND'}")

if start_memo is not None and end_memo is not None:
    # Remove memo first (higher), then effect
    new_lines = lines[:start_memo] + lines[end_memo+1:]
    if start_effect is not None and end_effect is not None:
        new_lines = new_lines[:start_effect] + new_lines[end_effect+1:]
    open(r'd:\FINPLUS PNL APP\src\App.jsx', 'w', encoding='utf-8').writelines(new_lines)
    print("Removed effect and memo blocks OK")
else:
    print("Could not find blocks - check manually")
