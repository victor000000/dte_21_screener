import json
from pathlib import Path

def inputs():
    folder=Path(__file__).resolve().parents[2]/'fixtures/analysis'
    d=json.loads((folder/'vol_render.json').read_text())
    return folder,d,{r['day']:r for r in d['daily']},{(r['day'],r['underlying']):r for r in d['rv']}
