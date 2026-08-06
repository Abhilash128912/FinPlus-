lines = open(r'd:\FINPLUS PNL APP\src\App.jsx', encoding='utf-8').read().splitlines()
keywords = ['screenerData', 'setScreenerData', 'screenerLoading', 'setScreenerLoading', 
            'screenerFilter', 'screenerSort', 'selectedScreenerStock', 'setSelectedScreenerStock', 
            'screenerSearch', 'setScreenerSearch', "activeTab === 'screener'", 
            'Stock Screener Tab', 'Screener Stock Detail Modal', 'pullbackLtp',
            'addToPullbackFromScreener', 'screenerSortCol']
seen = set()
for i, l in enumerate(lines):
    for k in keywords:
        if k in l and i+1 not in seen:
            print(i+1, k, '|', l[:100])
            seen.add(i+1)
            break
