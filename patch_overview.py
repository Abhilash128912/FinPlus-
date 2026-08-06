content = open(r'd:\FINPLUS PNL APP\src\App.jsx', encoding='utf-8').read()

old = "display: 'flex', flexDirection: 'column', gap: '24px' }}"
new = "display: 'flex', flexDirection: 'column', gap: '24px', paddingBottom: '120px' }}"

# Only replace the one inside the overview tab (after activeTab === 'overview')
overview_idx = content.find("activeTab === 'overview'")
if overview_idx == -1:
    print("ERROR: overview tab marker not found")
else:
    old_idx = content.find(old, overview_idx)
    if old_idx == -1:
        print("ERROR: target string not found after overview marker")
    else:
        content = content[:old_idx] + new + content[old_idx + len(old):]
        open(r'd:\FINPLUS PNL APP\src\App.jsx', 'w', encoding='utf-8').write(content)
        print(f"REPLACED at position {old_idx}")
