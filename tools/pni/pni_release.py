#!/usr/bin/env python3
"""Apoio ao workflow que publica os totais do PNI na release de dados do ano.

  planejar: compara os arquivos do Ministério com o manifesto publicado e lista
            os meses que precisam ser processados (novos ou alterados).
  juntar:   acrescenta ao manifesto do ano os meses processados nesta execução.

A release de dados se chama pni-dados-AAAA e é marcada como pré-lançamento,
para o atualizador do TabulaSUS nunca confundi-la com uma versão do programa.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pni_totais import FORMATO, MESES, consultar_fonte  # noqa: E402


def ler_json(caminho: str) -> dict | None:
    if not caminho or not Path(caminho).is_file():
        return None
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def escrever_saida(chave: str, valor: str) -> None:
    destino = os.environ.get("GITHUB_OUTPUT")
    if destino:
        with open(destino, "a", encoding="utf-8") as saida:
            saida.write(f"{chave}={valor}\n")
    print(f"{chave}={valor}")


def planejar(a) -> int:
    ano = int(a.ano)
    publicado = (ler_json(a.manifesto) or {}).get("meses", {})
    escolhidos = {int(m) for m in a.meses.split(",") if m.strip()} if a.meses.strip() else set(range(1, 13))
    hoje = dt.date.today()
    fila = []
    for mes in sorted(escolhidos):
        if not 1 <= mes <= 12 or (ano == hoje.year and mes > hoje.month):
            continue
        fonte = consultar_fonte(ano, mes)
        if fonte is None:
            print(f"{mes:02d}/{ano}: ainda não publicado pelo Ministério")
            continue
        anterior = publicado.get(str(mes)) or {}
        mudou = (anterior.get("fonte") or {}).get("etag") != fonte["etag"] or anterior.get("formato") != FORMATO
        if a.forcar or mudou:
            print(f"{mes:02d}/{ano}: processar ({'forçado' if not mudou else 'novo ou alterado'}, publicado em {fonte['last_modified']})")
            fila.append(MESES[mes - 1])
        else:
            print(f"{mes:02d}/{ano}: sem mudança desde {anterior.get('processado_em')}")
    escrever_saida("meses", json.dumps(fila))
    return 0


def juntar(a) -> int:
    ano = int(a.ano)
    manifesto = ler_json(a.anterior) or {}
    meses = dict(manifesto.get("meses") or {})
    novos = 0
    for caminho in sorted(Path(a.novos).glob(f"manifest_{ano}_*.json")):
        mes_manifesto = ler_json(str(caminho))
        if not mes_manifesto or mes_manifesto.get("leitura", {}).get("parcial"):
            continue
        mes = int(mes_manifesto["fonte"]["mes"])
        meses[str(mes)] = {
            "formato": mes_manifesto["formato"],
            "fonte": mes_manifesto["fonte"],
            "processado_em": mes_manifesto["processado_em"],
            "conferencia": mes_manifesto["leitura"]["conferencia"],
            "contagem": mes_manifesto["contagem"],
            "arquivos": mes_manifesto["arquivos"],
        }
        novos += 1
    saida = {
        "formato": FORMATO,
        "ano": ano,
        "atualizado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "meses": dict(sorted(meses.items(), key=lambda item: int(item[0]))),
    }
    Path(a.saida).write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Manifesto de {ano}: {novos} mês(es) atualizado(s), {len(meses)} no total.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    p_plan = sub.add_parser("planejar")
    p_plan.add_argument("--ano", required=True)
    p_plan.add_argument("--manifesto", default="")
    p_plan.add_argument("--meses", default="", help="lista como 1,2,3 (vazio = todos)")
    p_plan.add_argument("--forcar", action="store_true")
    p_junt = sub.add_parser("juntar")
    p_junt.add_argument("--ano", required=True)
    p_junt.add_argument("--anterior", default="")
    p_junt.add_argument("--novos", required=True)
    p_junt.add_argument("--saida", required=True)
    a = p.parse_args()
    if not a.ano.isdigit() or not 2020 <= int(a.ano) <= 2099:
        p.error("ano inválido")
    return planejar(a) if a.comando == "planejar" else juntar(a)


if __name__ == "__main__":
    sys.exit(main())
