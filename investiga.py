import json
from pathlib import Path

p = Path(r"C:\Users\danie\Documents\Projetos\Canais Youtube\Crime Blackline Archive\REAL_PROJECT_05_TEST_LilyandJackSullivan\plano_edicao.json")
data = json.loads(p.read_text(encoding="utf-8"))
clipes = data.get("clipes", [])

print("Primeiros 21 clipes:")
for i, c in enumerate(clipes[:21]):
    print(f"clipe_{i:04d}: cena={c.get('cena_id'):30s} inicio_fonte={c.get('inicio_fonte_s'):8.1f}s dur={c.get('duracao_s'):.1f}s")