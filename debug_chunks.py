"""
Investiga se o chunking gera chunks > 5000 bytes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))

from tts.google import _dividir_em_chunks

# AJUSTE O CAMINHO PRO PROJETO REAL
projeto_dir = Path(r"C:\Users\danie\Documents\Projetos\Canais Youtube\Crime Blackline Archive\REAL_PROJECT_05_TEST_LilyandJackSullivan")

roteiro_path = projeto_dir / "roteiro_aprovado.md"

if not roteiro_path.exists():
    print(f"ERRO: {roteiro_path} nao existe")
    print("Ajuste o caminho no script")
    exit(1)

texto = roteiro_path.read_text(encoding="utf-8")
print(f"Roteiro total: {len(texto)} chars, {len(texto.encode('utf-8'))} bytes\n")

chunks = _dividir_em_chunks(texto)
print(f"Chunks gerados: {len(chunks)}\n")

problema_encontrado = False
for i, chunk in enumerate(chunks, 1):
    chars = len(chunk)
    bytes_ = len(chunk.encode('utf-8'))
    diff = bytes_ - chars
    marca = "" if bytes_ <= 5000 else "  <-- ESTOURA LIMITE DE BYTES!"
    print(f"Chunk {i:3d}: {chars:5d} chars, {bytes_:5d} bytes (diff: +{diff}){marca}")
    if bytes_ > 5000:
        problema_encontrado = True
        print(f"   Prévia: {chunk[:100]!r}")

print()
if problema_encontrado:
    print("BUG CONFIRMADO: pelo menos um chunk tem > 5000 bytes.")
    print("A API Google TTS rejeita esses chunks com HTTP 400.")
else:
    print("Chunks estao todos <= 5000 bytes.")
    print("Bug deve estar em outra coisa - investigar payload real.")