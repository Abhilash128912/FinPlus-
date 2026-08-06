import os, re

CLEAN = """async function triggerAppScan() {
  const overlay = document.getElementById('scanProgressOverlay');
  const btnText = document.getElementById('scanProgressText');
  const btnLog = document.getElementById('scanProgressLog');
  const barInner = document.getElementById('scanProgressBarInner');
  const isDesktop = (window.location.port === '5000' || window.location.port === '3000');
  if (!isDesktop) {
    const confirmed = confirm(
      '\\u26a1 Cloud Auto-Scan Active\\n\\n' +
      'GitHub Actions automatically runs the full Nifty 500 scan every weekday at 9:15 AM IST before market opens.\\n\\n' +
      'Tap OK to reload and fetch the latest scan report.'
    );
    if (confirmed) window.location.reload();
    return;
  }
  if (overlay) overlay.style.display = 'flex';
  if (btnText) btnText.textContent = 'Initializing live stock & commodity scan...';
  if (barInner) barInner.style.width = '20%';
  if (btnLog) btnLog.textContent = 'Connecting to local scan engine server...';
  const scanUrl = 'http://localhost:' + window.location.port + '/api/scan';
  try {
    if (barInner) barInner.style.width = '40%';
    if (btnLog) btnLog.textContent = 'Fetching Nifty 500 prices & scoring stocks...';
    const res = await fetch(scanUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    if (res.ok) {
      if (barInner) barInner.style.width = '100%';
      if (btnText) btnText.textContent = 'Scan complete! Reloading latest data...';
      if (btnLog) btnLog.textContent = 'Updating watchlist and daily picks...';
      setTimeout(() => { window.location.reload(); }, 800);
    } else {
      throw new Error('Server returned status ' + res.status);
    }
  } catch (err) {
    console.warn('Direct scan endpoint failed or offline:', err);
    if (overlay) overlay.style.display = 'none';
    alert('\\u26a1 Python Scan Server is not running.\\n\\nPlease launch "Run Screener.bat" on your PC to enable 1-click scanning.');
  }
}"""

files = [
    'index.html',
    'www/index.html',
    r'android/app/src/main/assets/public/index.html'
]

for p in files:
    if not os.path.exists(p):
        print(f"Skipping (not found): {p}")
        continue
    with open(p, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find every occurrence of async function triggerAppScan() and replace the entire function body
    count = 0
    idx = content.find('async function triggerAppScan()')
    while idx >= 0:
        brace_open = content.find('{', idx)
        if brace_open < 0:
            break
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
        
        content = content[:idx] + CLEAN + content[i+1:]
        count += 1
        idx = content.find('async function triggerAppScan()', idx + len(CLEAN))

    # Also clean any old alert text
    content = content.replace("to enable 1-click background scanning from the web app.", "to start the scan server.")
    content = content.replace("https://finplus-g0b5.onrender.com/api/scan", "http://localhost:5000/api/scan")

    with open(p, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Updated {p}: {count} functions replaced")
