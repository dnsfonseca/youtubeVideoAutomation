import json
from pathlib import Path

p = Path(r"C:\Users\danie\Documents\Projetos\Canais Youtube\Crime Blackline Archive\REAL_PROJECT_05_TEST_LilyandJackSullivan\plano_edicao.json")

data = json.loads(p.read_text(encoding="utf-8"))
clipes = data.get("clipes_planejados", [])

print(f"Total clipes no plano: {len(clipes)}")
print()

# Fonte 01 ordenado por tempo
print("=" * 60)
print("Clipes do fonte01 ordenados por inicio:")
print("=" * 60)
fonte01 = sorted(
    [c for c in clipes if c.get("fonte") == "fonte01"],
    key=lambda x: x.get("inicio_fonte_s", 0),
)
for c in fonte01[:20]:
    inicio = c.get("inicio_fonte_s", 0)
    duracao = c.get("duracao_s", 0)
    cena_id = c.get("cena_id", "?")
    print(f"  {cena_id} | inicio={inicio:7.1f}s | duracao={duracao:5.1f}s")

print()
print("=" * 60)
print("Clipes do fonte02 ordenados por inicio:")
print("=" * 60)
fonte02 = sorted(
    [c for c in clipes if c.get("fonte") == "fonte02"],
    key=lambda x: x.get("inicio_fonte_s", 0),
)
for c in fonte02[:20]:
    inicio = c.get("inicio_fonte_s", 0)
    duracao = c.get("duracao_s", 0)
    cena_id = c.get("cena_id", "?")
    print(f"  {cena_id} | inicio={inicio:7.1f}s | duracao={duracao:5.1f}s")

# Analise de gaps
print()
print("=" * 60)
print("Analise de gaps entre clipes consecutivos (fonte01):")
print("=" * 60)
for i in range(1, min(len(fonte01), 20)):
    anterior = fonte01[i-1]
    atual = fonte01[i]
    fim_anterior = anterior.get("inicio_fonte_s", 0) + anterior.get("duracao_s", 0)
    inicio_atual = atual.get("inicio_fonte_s", 0)
    gap = inicio_atual - fim_anterior
    marca = " <- CONTIGUO" if abs(gap) < 1 else ""
    print(f"  gap={gap:6.1f}s (entre {anterior.get('cena_id')} e {atual.get('cena_id')}){marca}")