import os

file_path = r'd:\FINPLUS PNL APP\src\App.jsx'

with open(file_path, 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Update ltFreeCashInput initialization to discard stale 367.58
target1 = "return localStorage.getItem(FREE_CASH_LT_KEY) || '';"
replacement1 = "const val = localStorage.getItem(FREE_CASH_LT_KEY);\n    return (val && val !== '367.58') ? val : '164.99';"

# 2. Update Quality Penny SIP broker header text
target2 = "<span>💎 QUALITY PENNY SIP</span>\n                <span style={{ fontSize: '10px', color: '#94a3b8' }}>Zerodha Kite</span>"
replacement2 = "<span>💎 QUALITY PENNY SIP</span>\n                <span style={{ fontSize: '10px', color: '#94a3b8' }}>INDmoney</span>"

# 3. Update Quality Penny SIP free cash label
target3 = "<span style={{ color: '#94a3b8' }}>1. Free Cash (Kite):</span>"
replacement3 = "<span style={{ color: '#94a3b8' }}>1. Free Cash (INDmoney):</span>"

# 4. Update tab label
target4 = "{ id: 'penny', label: '💎 Quality Penny SIP (Kite)', badge: positions.filter(p => p.segment === 'PENNY').length }"
replacement4 = "{ id: 'penny', label: '💎 Quality Penny SIP (INDmoney)', badge: positions.filter(p => p.segment === 'PENNY').length }"

code = code.replace(target1, replacement1)
code = code.replace(target2, replacement2)
code = code.replace(target3, replacement3)
code = code.replace(target4, replacement4)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(code)

print("SUCCESSFULLY_UPDATED_APP_JSX")
