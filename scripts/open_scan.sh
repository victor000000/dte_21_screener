#!/bin/bash
# open_scan.sh — market-open status scan for the Nov 20 strangle plan
# Answers at a glance: underlying vs ref/close, leg bid/ask + top sizes, session vol, OI
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
declare -A REF=( [META]=718.10 [CRWD]=259.27 [ILMN]=272.98 [SWKS]=88.10 [TLT]=78.69 [EWZ]=36.21 )
declare -A AC=(  [META]=stocks [CRWD]=stocks [ILMN]=stocks [SWKS]=stocks [TLT]=etf [EWZ]=etf )

echo "===== UNDERLYINGS   consolidated pre-mkt | info last | vs 03:44 ref ====="
for s in META CRWD ILMN SWKS TLT EWZ; do
  ext=$(curl -s --max-time 15 -H "User-Agent: $UA" -H "Accept: application/json" "https://api.nasdaq.com/api/quote/$s/extended-trading?assetclass=${AC[$s]}&markettype=pre")
  j=$(curl -s --max-time 15 -H "User-Agent: $UA" -H "Accept: application/json" "https://api.nasdaq.com/api/quote/$s/info?assetclass=${AC[$s]}")
  cons=$(echo "$ext" | grep -o '"consolidated":"\$[^"]*"' | head -1 | sed 's/.*:"\$//; s/"$//')
  cpx=$(echo "$cons" | sed 's/ .*//')
  ipx=$(echo "$j" | grep -o '"lastSalePrice":"[^"]*"' | head -1 | sed 's/.*:"\$//; s/"//')
  mst=$(echo "$j" | grep -o '"marketStatus":"[^"]*"' | head -1 | sed 's/.*:"//; s/"//')
  px=$cpx; [ -z "$px" ] && px=$ipx
  awk -v s=$s -v px="$px" -v cons="$cons" -v ipx="$ipx" -v m="$mst" -v ref="${REF[$s]}" 'BEGIN{
    if (px=="") { printf "%-5s  NO DATA | %s\n", s, m }
    else printf "%-5s %9.2f | pre: %-26s | info: %9s | %+6.2f%% vs ref | %s\n", s, px, cons, ipx, (px-ref)/ref*100, m }'
done

echo
echo "===== PLAN LEGS   CALL bid/ask xsize, vol, oi  ||  PUT bid/ask xsize, vol, oi ====="
rowspull() {
  sym=$1; shift
  curl -s --max-time 25 -H "User-Agent: $UA" -H "Accept: application/json" \
    "https://api.nasdaq.com/api/quote/$sym/option-chain?assetclass=${AC[$sym]}&fromdate=2026-11-20&todate=2026-11-20&limit=10000&excode=oprac&callput=callput&money=all&type=all" -o /tmp/scan_$sym.json
  echo "-- $sym"
  for k in "$@"; do
    r=$(sed 's/}, *{/}\n{/g' /tmp/scan_$sym.json | grep -F "\"strike\":\"$k\"" | head -1)
    if [ -z "$r" ]; then printf "  K%-8s NO ROW\n" "$k"; continue; fi
    g() { echo "$r" | grep -o "\"$1\":\"[^\"]*\"" | head -1 | sed 's/.*:"//; s/"$//'; }
    printf "  K%-8s CALL %s/%s  vol %s  oi %s  ||  PUT %s/%s  vol %s  oi %s\n" \
      "$k" "$(g c_Bid)" "$(g c_Ask)" "$(g c_Volume)" "$(g c_Openinterest)" \
           "$(g p_Bid)" "$(g p_Ask)" "$(g p_Volume)" "$(g p_Openinterest)"
  done
}
rowspull META 650.00 630.00 850.00
rowspull CRWD 230.00 220.00 330.00
rowspull ILMN 240.00 230.00 340.00
rowspull SWKS 75.00 115.00
rowspull EWZ  32.00 43.00
rowspull TLT  74.00 83.00
