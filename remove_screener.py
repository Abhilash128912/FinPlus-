import re

content = open(r'd:\FINPLUS PNL APP\src\App.jsx', encoding='utf-8').read()
lines = content.splitlines(keepends=True)

def remove_line_range(lines, start, end):
    """Remove lines from start to end inclusive (1-indexed)."""
    return lines[:start-1] + lines[end:]

# ── 1. Remove Screener state declarations (lines 140-147 area)
# We'll do it by content matching instead of line numbers for safety

removals = [
    # State variables
    "  const [screenerData, setScreenerData] = useState([]);\r\n",
    "  const [screenerLoading, setScreenerLoading] = useState(false);\r\n",
    "  const [screenerSearchQuery, setScreenerSearchQuery] = useState('');\r\n",
    "  const [screenerFilter, setScreenerFilter] = useState('all'); // 'all' | 'qualified'\r\n",
    "  const [screenerSortCol, setScreenerSortCol] = useState('total_score');\r\n",
    "  const [screenerSortAsc, setScreenerSortAsc] = useState(false);\r\n",
    "  const [selectedScreenerStock, setSelectedScreenerStock] = useState(null);\r\n",
]

for r in removals:
    content = content.replace(r, '')

print("State variables removed")

# ── 2. Remove Screener tab nav item
content = content.replace(
    "          { key: 'screener', label: 'Screener', icon: Search, color: '#ec4899' },\r\n",
    ""
)
print("Nav item removed")

open(r'd:\FINPLUS PNL APP\src\App.jsx', 'w', encoding='utf-8').write(content)
print("File saved for phase 1")

# ── 3. Remove Screener tab JSX block (lines ~4947-5229) and Modal (5231-5358)
# Re-read to get fresh line numbers
lines2 = open(r'd:\FINPLUS PNL APP\src\App.jsx', encoding='utf-8').readlines()

start_tab = None
end_tab = None
start_modal = None
end_modal = None

for i, l in enumerate(lines2):
    if '{/* Stock Screener Tab */}' in l and start_tab is None:
        start_tab = i
    if '{/* Screener Stock Detail Modal */}' in l and start_modal is None:
        start_modal = i

# Find end of screener tab block (ends just before the modal comment)
end_tab = start_modal - 2  # the blank line before modal comment

# Find end of modal block (ends at closing )} followed by blank line before Bottom Navigation)
for i in range(start_modal, len(lines2)):
    if 'Bottom Navigation Bar' in lines2[i]:
        end_modal = i - 2
        break

print(f"Screener tab: lines {start_tab+1} to {end_tab+1}")
print(f"Screener modal: lines {start_modal+1} to {end_modal+1}")

# Remove modal first (higher line numbers), then tab
new_lines = lines2[:start_modal] + lines2[end_modal+1:]
# Now recalculate start_tab position (unchanged since it's before modal)
new_lines = new_lines[:start_tab] + new_lines[end_tab+1:]

open(r'd:\FINPLUS PNL APP\src\App.jsx', 'w', encoding='utf-8').writelines(new_lines)
print("Screener tab and modal removed. Done!")
