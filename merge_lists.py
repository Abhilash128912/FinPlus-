# merge_lists.py
# Merges the 150 midcap stocks from CSV into D:\Nifty 500 stocks.xlsx

import pandas as pd
import os

xlsx_path = r"D:\Nifty 500 stocks.xlsx"
csv_path = r"C:\Users\AbhilashBabu\OneDrive - Prospera Advisors\Documents\Downloads\ind_niftymidcap150list.csv"

print(f"Reading main Excel file: {xlsx_path}")
df_main = pd.read_excel(xlsx_path)
print(f"  Loaded {len(df_main)} rows.")

print(f"Reading CSV file: {csv_path}")
df_csv = pd.read_csv(csv_path)
print(f"  Loaded {len(df_csv)} rows.")

# Extract existing symbols (set for O(1) checks)
existing_symbols = set(df_main['Symbol'].dropna().astype(str).str.strip().str.upper())

new_rows = []
skipped_dupes = 0

for idx, row in df_csv.iterrows():
    sym = str(row['Symbol']).strip().upper()
    if sym in existing_symbols:
        skipped_dupes += 1
        continue
    
    # Create matching row structure
    new_row = {col: None for col in df_main.columns}
    new_row['Sr.'] = len(df_main) + len(new_rows) + 1
    new_row['Symbol'] = sym
    new_row['Stock Name'] = row['Company Name']
    new_rows.append(new_row)

if new_rows:
    df_new = pd.DataFrame(new_rows)
    df_merged = pd.concat([df_main, df_new], ignore_index=True)
    
    # Save back to main Excel
    df_merged.to_excel(xlsx_path, index=False)
    print(f"\nSuccessfully merged {len(new_rows)} new stocks into {xlsx_path}!")
    print(f"Skipped {skipped_dupes} duplicate symbols already in the list.")
    print(f"New total row count: {len(df_merged)}")
else:
    print("\nAll symbols from the CSV are already present in the Excel list. No new stocks added.")
