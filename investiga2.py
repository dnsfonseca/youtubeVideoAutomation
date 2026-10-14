import json
from pathlib import Path

p = Path(r"C:\Users\danie\Documents\Projetos\Canais Youtube\Crime Blackline Archive\REAL_PROJECT_05_TEST_LilyandJackSullivan\plano_edicao.json")
data = json.loads(p.read_text(encoding="utf-8"))
clipes = data.get("clipes", [])

print(f"Total de clipes: {len(clipes)}")
print()
for i in [29, 30]:
    if i < len(clipes):
        c = clipes[i]
        print(f"clipe_{i:04d}:")
        print(f"  cena_id: {c.get('cena_id')}")
        print(f"  fonte: {c.get('fonte')}")
        print(f"  inicio_fonte_s: {c.get('inicio_fonte_s')}")
        print(f"  duracao_s: {c.get('duracao_s')}")
        print()