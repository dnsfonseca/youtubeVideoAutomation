import json
from pathlib import Path
from collections import Counter

p = Path(r"C:\Users\danie\Documents\Projetos\Canais Youtube\Crime Blackline Archive\REAL_PROJECT_05_TEST_LilyandJackSullivan\clipes\indice.json")
data = json.loads(p.read_text(encoding="utf-8"))
clipes = data.get("clipes", [])

print(f"Total clipes: {len(clipes)}")
print()

if clipes:
    print("Campos disponíveis no primeiro clipe:")
    for k, v in clipes[0].items():
        print(f"  {k}: {v}")