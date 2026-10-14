"""Verifica se o servidor Flask do Broll Foundry esta no ar numa porta e
abre o navegador automaticamente quando ele responder de verdade.

Chamado por iniciar.bat em dois momentos (CLAUDE.md secao 18.3, melhoria
do fluxo do atalho da area de trabalho):

1. "checar-porta" - ANTES de subir o servidor, pra nao iniciar uma
   segunda instancia se o Broll Foundry ja estiver rodando, e pra avisar
   claramente se a porta estiver ocupada por outro processo qualquer.
2. "aguardar-e-abrir" - DEPOIS de disparar "python server.py" (em
   segundo plano, dentro da mesma sessao de console - nunca um processo
   desacoplado do terminal), fazendo polling ate o Flask responder de
   verdade antes de abrir o navegador. Nunca usa espera fixa: o tempo de
   boot varia por maquina (carregamento de libs, antivirus, etc).

Autocontido de proposito (CLAUDE.md secao 9) e so' usa biblioteca
padrao (alem do "dotenv" opcional, que so serve pra ler PORTA do .env
quando a variavel nao esta no ambiente do processo) - assim funciona
mesmo se o restante do venv estiver com "pip install" incompleto.

Identifica "e' o Broll Foundry mesmo" reusando a rota /verificar_atualizacao
que ja existe no server.py (CLAUDE.md secao 16) em vez de criar uma rota
nova so pra isso - ela devolve um JSON com formato estavel e uma
mensagem que nenhum outro servico teria por coincidencia.
"""
import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import webbrowser

MARCADOR_MENSAGEM = "verificacao de atualizacoes"
TIMEOUT_PADRAO_S = 90.0
INTERVALO_PADRAO_S = 1.0


def _porta_padrao():
    porta_env = os.environ.get("PORTA")
    if porta_env:
        return porta_env
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    return os.environ.get("PORTA", "5000")


def _porta_aberta(host, porta, timeout=2.0):
    try:
        with socket.create_connection((host, int(porta)), timeout=timeout):
            return True
    except OSError:
        return False


def checar_status_porta(host, porta, timeout=2.0):
    """Retorna "livre", "broll_foundry" ou "outro_servico".

    So tenta identificar via HTTP depois de confirmar que algo esta
    escutando na porta via TCP puro - evita depender de texto de
    mensagem de excecao (fragil e dependente de plataforma/idioma) pra
    distinguir "porta livre" de "porta ocupada".
    """
    if not _porta_aberta(host, porta, timeout=timeout):
        return "livre"

    url = f"http://{host}:{porta}/verificar_atualizacao"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resposta:
            corpo = resposta.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return "outro_servico"

    try:
        dados = json.loads(corpo)
    except ValueError:
        return "outro_servico"

    if "versao_local" in dados and MARCADOR_MENSAGEM in str(dados.get("mensagem", "")):
        return "broll_foundry"
    return "outro_servico"


def aguardar_pronto(host, porta, timeout_total=TIMEOUT_PADRAO_S, intervalo=INTERVALO_PADRAO_S):
    prazo = time.monotonic() + timeout_total
    while True:
        if checar_status_porta(host, porta, timeout=min(intervalo, 3.0)) == "broll_foundry":
            return True
        if time.monotonic() >= prazo:
            return False
        time.sleep(intervalo)


def abrir_navegador(host, porta):
    webbrowser.open(f"http://{host}:{porta}/")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "modo", choices=["checar-porta", "aguardar-e-abrir", "abrir-navegador"]
    )
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--porta", default=None)
    parser.add_argument("--timeout", type=float, default=TIMEOUT_PADRAO_S)
    parser.add_argument("--intervalo", type=float, default=INTERVALO_PADRAO_S)
    args = parser.parse_args(argv)

    porta = args.porta or _porta_padrao()

    if args.modo == "checar-porta":
        status = checar_status_porta(args.host, porta)
        if status == "livre":
            return 0
        if status == "broll_foundry":
            print(f"Broll Foundry ja esta rodando em http://{args.host}:{porta}")
            return 2
        print(
            f"AVISO: a porta {porta} ja esta em uso por outro processo "
            "que nao parece ser o Broll Foundry."
        )
        return 3

    if args.modo == "aguardar-e-abrir":
        pronto = aguardar_pronto(args.host, porta, args.timeout, args.intervalo)
        if not pronto:
            print(
                f"ERRO: o servidor nao respondeu em http://{args.host}:{porta} "
                f"apos {args.timeout:.0f}s. Verifique as mensagens acima no "
                "terminal para identificar o que travou a inicializacao."
            )
            return 1
        abrir_navegador(args.host, porta)
        return 0

    if args.modo == "abrir-navegador":
        abrir_navegador(args.host, porta)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
