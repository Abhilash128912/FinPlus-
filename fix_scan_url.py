"""
Targeted patch: replace full triggerAppScan bodies in APK assets index.html
Uses character-level search to find and replace both function bodies.
"""
path = r'D:\STOCK SCREENER APP\android\app\src\main\assets\public\index.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
print(f"Loaded: {len(content)} bytes")

MOBILE_GUARD = """  // Scan only runs on desktop PC - show info on mobile
  const isDesktop = window.location.port === '5000' || window.location.port === '3000';
  if (!isDesktop) {
    const ok = confirm(
      'Scan runs on Desktop PC\\n\\n' +
      'The Nifty 500 scan (10-12 min) runs from your PC only.\\n' +
      'Run \\'Run Screener.bat\\' on your PC to update data.\\n\\n' +
      'Tap OK to reload latest available data.'
    );
    if (ok) window.location.reload();
    return;
  }"""

# Find both function start markers and patch them
count = 0
for func_marker in ['async function triggerAppScan()']:
    idx = content.find(func_marker)
    while idx >= 0:
        # Find the body opening brace
        brace_open = content.find('{', idx)
        if brace_open < 0:
            break
        
        # Find matching closing brace (simple depth counter)
        depth = 0
        i = brace_open
        while i < len(content):
            if content[i] == '{':
                depth += 1
            elif content[i] == '}':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        
        func_body_end = i  # position of closing }
        func_full = content[idx:func_body_end+1]
        
        # Check if this function already has the mobile guard
        if 'isDesktop' in func_full:
            print(f"SKIP at {idx}: already has mobile guard")
            idx = content.find(func_marker, idx + 1)
            continue
        
        # Check if it has Render URL (bad) 
        has_render = 'onrender.com/api/scan' in func_full
        has_wakeup = 'Waking up' in func_full or 'progressTimer' in func_full
        print(f"Found at {idx}: has_render={has_render}, has_wakeup={has_wakeup}, len={len(func_full)}")
        
        # Extract the header (const overlay... lines before the main logic)
        # Find where the main logic starts after element queries
        header_end = func_full.find('\n\n  if (overlay)')
        if header_end < 0:
            header_end = func_full.find('\n\n  let ')
        if header_end < 0:
            header_end = func_full.find('\n\n  // Animate')
        
        if header_end < 0:
            print(f"  Could not find header end, skipping")
            idx = content.find(func_marker, idx + 1)
            continue
        
        # Build replacement: keep variable declarations, add mobile guard, add desktop-only logic
        func_header = func_full[:header_end]  # "async function triggerAppScan() {\n  const overlay = ..."
        
        new_func = func_header + '\n\n' + MOBILE_GUARD + """

  // Desktop only: call local scan server
  if (overlay) overlay.style.display = 'flex';
  if (typeof txt !== 'undefined' && txt) txt.textContent = 'Triggering Full Market Scan...';
  if (typeof btnText !== 'undefined' && btnText) btnText.textContent = 'Triggering Full Market Scan...';
  if (typeof logEl !== 'undefined' && logEl) logEl.textContent = 'Connecting to scanner server...';
  if (typeof btnLog !== 'undefined' && btnLog) btnLog.textContent = 'Connecting to scanner server...';
  if (typeof bar !== 'undefined' && bar) bar.style.width = '20%';
  if (typeof barInner !== 'undefined' && barInner) barInner.style.width = '20%';

  const _scanUrl = 'http://localhost:' + window.location.port + '/api/scan';
  try {
    const _res = await fetch(_scanUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    if (_res.ok) {
      if (typeof bar !== 'undefined' && bar) bar.style.width = '100%';
      if (typeof barInner !== 'undefined' && barInner) barInner.style.width = '100%';
      if (typeof txt !== 'undefined' && txt) txt.textContent = 'Scan Complete!';
      if (typeof btnText !== 'undefined' && btnText) btnText.textContent = 'Scan Complete!';
      setTimeout(() => { window.location.reload(); }, 800);
    } else {
      throw new Error('Server error ' + _res.status);
    }
  } catch (_err) {
    if (overlay) overlay.style.display = 'none';
    alert('Run \\'Run Screener.bat\\' on your PC to trigger a scan.');
  }
}"""
        
        content = content[:idx] + new_func + content[func_body_end+1:]
        count += 1
        print(f"  PATCHED (#{count})")
        
        # Continue searching from after this function
        idx = content.find(func_marker, idx + len(new_func))

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print(f"\nSAVED - {count} functions patched")

# Verify
remaining = content.count("onrender.com/api/scan")
guards = content.count("isDesktop")
print(f"Remaining Render scan URLs in triggerAppScan: {remaining}")
print(f"Mobile guard blocks: {guards}")
