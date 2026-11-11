#!/usr/bin/env python3
"""Lê em fluxo o CSV mensal de doses aplicadas do PNI e gera totais por município.

O arquivo oficial é um ZIP nacional de 1,4 a 4,3 GB com um CSV de 5 a 17 GB, com
todos os municípios misturados. Por isso o arquivo inteiro sempre é lido. O script
não grava o ZIP nem o CSV: baixa, descompacta, lê e soma ao mesmo tempo.

Dois modos:

  Teste, um município (gera um SQLite para conferir):
    python -I tools/pni/pni_totais.py --ano 2026 --mes jan --municipio 1501402 --saida saida-pni

  Produção, todos os municípios (gera um ZIP por UF com um JSON por município,
  que o TabulaSUS lê por faixa de bytes, sem baixar a UF inteira):
    python -I tools/pni/pni_totais.py --ano 2026 --mes jan --todos --saida saida-pni

Cada dose entra na cobertura do município onde a pessoa mora e na produção e
qualidade do município do estabelecimento que aplicou.

--limite-mb lê só o começo do arquivo compactado (teste rápido; o resultado fica
marcado como parcial e a conferência de CRC não é feita).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import re
import shutil
import sqlite3
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from pathlib import Path

FORMATO = 1
HOST = "s3.sa-east-1.amazonaws.com"
BASE = f"https://{HOST}/ckan.saude.gov.br/PNI/csv/"
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
UF_IBGE = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}
CHUNK = 1 << 20
TIMEOUT = 120
USER_AGENT = "TabulaSUS-PNI/1.0"

COLUNAS = [
    "co_municipio_paciente", "no_municipio_paciente", "nu_idade_paciente",
    "tp_sexo_paciente", "co_raca_cor_paciente", "co_condicao_maternal",
    "co_municipio_estabelecimento", "no_municipio_estabelecimento", "co_cnes_estabelecimento",
    "co_vacina", "sg_imunobiologico", "ds_nome", "co_dose_vacina", "ds_tipo_dose",
    "co_estrategia_vacinacao", "no_estrategia", "co_origem_registro", "ds_origem_registro",
    "co_sistema_origem", "ds_sistema_origem",
    "dt_vacina", "dt_entrada_rnds", "dt_deletado_rnds", "co_troca_documento",
]

# Colunas de cada tabela de totais (a contagem de doses é sempre a última).
TABELAS = {
    "cobertura": ["vacina", "dose", "idade", "sexo", "condicao_maternal", "aplicada_fora", "doses"],
    "producao": ["cnes", "vacina", "dose", "estrategia", "residente", "doses"],
    "qualidade": ["cnes", "sistema_origem", "origem_registro", "raca_informada", "atraso_dias", "doses"],
}


class ErroFonte(Exception):
    pass


def faixa_idade(texto: str) -> str:
    if not texto.isdigit():
        return "ign"
    idade = int(texto)
    if idade > 130:
        return "ign"
    if idade <= 19:
        return str(idade)
    if idade >= 80:
        return "80+"
    inicio = idade // 10 * 10
    return f"{inicio}-{inicio + 9}"


def faixa_atraso(dias: int) -> str:
    if dias < 0:
        return "negativo"
    if dias <= 7:
        return "0-7"
    if dias <= 30:
        return "8-30"
    if dias <= 60:
        return "31-60"
    return "61+"


def url_do_mes(ano: int, mes: int) -> str:
    return f"{BASE}vacinacao_{MESES[mes - 1]}_{ano}_csv.zip"


def abrir(url: str, metodo: str = "GET"):
    pedido = urllib.request.Request(url, method=metodo, headers={"User-Agent": USER_AGENT})
    resposta = urllib.request.urlopen(pedido, timeout=TIMEOUT)
    final = urllib.parse.urlsplit(resposta.geturl())
    if final.scheme != "https" or final.hostname != HOST:
        resposta.close()
        raise ErroFonte(f"redirecionamento inesperado para {final.scheme}://{final.hostname}")
    return resposta


def consultar_fonte(ano: int, mes: int) -> dict | None:
    """Cabeçalhos do arquivo do mês; None quando o Ministério ainda não publicou."""
    url = url_do_mes(ano, mes)
    try:
        cabeca = abrir(url, "HEAD")
    except urllib.error.HTTPError as erro:
        if erro.code in (403, 404):
            return None
        raise
    with cabeca:
        return {
            "ano": ano, "mes": mes, "url": url,
            "etag": cabeca.headers.get("ETag", "").strip('"'),
            "last_modified": cabeca.headers.get("Last-Modified", ""),
            "content_length": int(cabeca.headers.get("Content-Length") or 0) or None,
        }


def ler_exato(resposta, n: int) -> bytes:
    dados = resposta.read(n)
    if len(dados) != n:
        raise ErroFonte("arquivo terminou antes do esperado")
    return dados


def ler_cabecalho_zip(resposta) -> dict:
    """Lê o cabeçalho local da primeira entrada do ZIP (com suporte a ZIP64)."""
    fixo = ler_exato(resposta, 30)
    (assinatura, _versao, flag, metodo, _hora, _data, crc, csize, usize,
     tam_nome, tam_extra) = struct.unpack("<IHHHHHIIIHH", fixo)
    if assinatura != 0x04034B50:
        raise ErroFonte("o arquivo não começa com um cabeçalho ZIP")
    if flag & 0x1:
        raise ErroFonte("ZIP criptografado")
    if metodo != 8:
        raise ErroFonte(f"método de compressão {metodo} não suportado (esperado deflate)")
    nome = ler_exato(resposta, tam_nome).decode("cp437")
    extra = ler_exato(resposta, tam_extra)
    i = 0
    while i + 4 <= len(extra):
        cabeca, tamanho = struct.unpack("<HH", extra[i:i + 4])
        if cabeca == 0x0001:
            valores = list(struct.unpack("<" + "Q" * (tamanho // 8), extra[i + 4:i + 4 + tamanho]))
            if usize == 0xFFFFFFFF and valores:
                usize = valores.pop(0)
            if csize == 0xFFFFFFFF and valores:
                csize = valores.pop(0)
        i += 4 + tamanho
    descritor = bool(flag & 0x8)
    return {
        "entrada": nome,
        "crc32": None if descritor else crc,
        "compactado": None if descritor else csize,
        "descompactado": None if descritor else usize,
    }


class Totais:
    """Soma as doses por município. municipio=None soma todos os municípios."""

    def __init__(self, mes: int, municipio: str | None):
        self.mes = mes
        self.municipio = municipio
        self.nomes: dict[str, str] = {}
        self.cobertura: dict[tuple, int] = {}
        self.producao: dict[tuple, int] = {}
        self.qualidade: dict[tuple, int] = {}
        self.dic_vacina: dict[str, tuple[str, str]] = {}
        self.dic_dose: dict[str, str] = {}
        self.dic_estrategia: dict[str, str] = {}
        self.dic_origem: dict[str, str] = {}
        self.dic_sistema: dict[str, str] = {}
        self._idade = {str(i): faixa_idade(str(i)) for i in range(0, 131)}
        self._atraso: dict[tuple[str, str], str] = {}
        self.contagem = {
            "linhas": 0, "malformadas": 0, "consideradas": 0, "deletadas": 0,
            "residentes": 0, "aplicadas": 0, "sem_municipio_residencia": 0,
            "com_troca_documento": 0, "fora_do_mes": 0,
        }
        self.idx: dict[str, int] = {}
        self.ncols = 0

    def definir_cabecalho(self, linha: str) -> None:
        nomes = next(csv.reader([linha], delimiter=";"))
        faltando = [c for c in COLUNAS if c not in nomes]
        if faltando:
            raise ErroFonte("colunas ausentes no CSV: " + ", ".join(faltando))
        self.idx = {c: nomes.index(c) for c in COLUNAS}
        self.ncols = len(nomes)

    def atraso(self, vacina: str, entrada: str) -> str:
        chave = (vacina, entrada)
        valor = self._atraso.get(chave)
        if valor is None:
            try:
                dias = (dt.date.fromisoformat(entrada) - dt.date.fromisoformat(vacina)).days
                valor = faixa_atraso(dias)
            except ValueError:
                valor = "ign"
            self._atraso[chave] = valor
        return valor

    def somar(self, linhas: list[str]) -> None:
        x = self.idx
        mun_p, nome_p, idade_p, sexo_p = x["co_municipio_paciente"], x["no_municipio_paciente"], x["nu_idade_paciente"], x["tp_sexo_paciente"]
        raca_p, cond_p = x["co_raca_cor_paciente"], x["co_condicao_maternal"]
        mun_e, nome_e, cnes_e = x["co_municipio_estabelecimento"], x["no_municipio_estabelecimento"], x["co_cnes_estabelecimento"]
        vac, sig, nome = x["co_vacina"], x["sg_imunobiologico"], x["ds_nome"]
        dose, dose_ds = x["co_dose_vacina"], x["ds_tipo_dose"]
        estr, estr_ds = x["co_estrategia_vacinacao"], x["no_estrategia"]
        orig, orig_ds = x["co_origem_registro"], x["ds_origem_registro"]
        sist, sist_ds = x["co_sistema_origem"], x["ds_sistema_origem"]
        dvac, dent, ddel, troca = x["dt_vacina"], x["dt_entrada_rnds"], x["dt_deletado_rnds"], x["co_troca_documento"]
        ncols = self.ncols
        alvo = self.municipio
        prefixo_mes = f"-{self.mes:02d}-"
        cob, prod, qual = self.cobertura, self.producao, self.qualidade
        cob_get, prod_get, qual_get = cob.get, prod.get, qual.get
        idades = self._idade
        nomes = self.nomes
        c = self.contagem
        valido = re.compile(r"\d{6}").fullmatch

        for r in csv.reader(linhas, delimiter=";"):
            c["linhas"] += 1
            if len(r) != ncols:
                c["malformadas"] += 1
                continue
            mp, me = r[mun_p], r[mun_e]
            if alvo is None:
                conta_residencia = bool(valido(mp)) and mp[:2] in UF_IBGE
                conta_aplicacao = bool(valido(me)) and me[:2] in UF_IBGE
                if not conta_residencia:
                    c["sem_municipio_residencia"] += 1
            else:
                conta_residencia = mp == alvo
                conta_aplicacao = me == alvo
                if not (conta_residencia or conta_aplicacao):
                    continue
            c["consideradas"] += 1
            if r[ddel]:
                c["deletadas"] += 1
                continue
            if r[troca]:
                c["com_troca_documento"] += 1
            data_vacina = r[dvac][:10]
            if data_vacina[4:8] != prefixo_mes:
                c["fora_do_mes"] += 1
            v, d, e, o, s = r[vac], r[dose], r[estr], r[orig], r[sist]
            if v not in self.dic_vacina:
                self.dic_vacina[v] = (r[sig], r[nome])
            if d not in self.dic_dose:
                self.dic_dose[d] = r[dose_ds]
            if e not in self.dic_estrategia:
                self.dic_estrategia[e] = r[estr_ds]
            if o not in self.dic_origem:
                self.dic_origem[o] = r[orig_ds]
            if s not in self.dic_sistema:
                self.dic_sistema[s] = r[sist_ds]
            mesmo = mp == me

            if conta_residencia:
                if mp not in nomes:
                    nomes[mp] = r[nome_p]
                k = (mp, v, d, idades.get(r[idade_p], "ign"), r[sexo_p], r[cond_p], 0 if mesmo else 1)
                cob[k] = cob_get(k, 0) + 1
                c["residentes"] += 1
            if conta_aplicacao:
                if me not in nomes:
                    nomes[me] = r[nome_e]
                k = (me, r[cnes_e], v, d, e, 1 if mesmo else 0)
                prod[k] = prod_get(k, 0) + 1
                raca = r[raca_p]
                k = (me, r[cnes_e], s, o, 0 if raca in ("", "99") else 1, self.atraso(data_vacina, r[dent][:10]))
                qual[k] = qual_get(k, 0) + 1
                c["aplicadas"] += 1

    def dicionarios(self) -> dict:
        return {
            "vacina": {k: {"sigla": s, "nome": n} for k, (s, n) in sorted(self.dic_vacina.items())},
            "dose": dict(sorted(self.dic_dose.items())),
            "estrategia": dict(sorted(self.dic_estrategia.items())),
            "origem_registro": dict(sorted(self.dic_origem.items())),
            "sistema_origem": dict(sorted(self.dic_sistema.items())),
        }

    def por_municipio(self) -> dict[str, dict[str, list]]:
        """{municipio: {tabela: [linhas]}} sem o código do município nas linhas."""
        saida: dict[str, dict[str, list]] = {}
        for tabela, dados in (("cobertura", self.cobertura), ("producao", self.producao), ("qualidade", self.qualidade)):
            for chave, doses in dados.items():
                destino = saida.setdefault(chave[0], {"cobertura": [], "producao": [], "qualidade": []})
                destino[tabela].append([*chave[1:], doses])
        return saida


def processar(url: str, totais: Totais, limite_bytes: int) -> dict:
    inicio = time.perf_counter()
    resposta = abrir(url)
    try:
        info = ler_cabecalho_zip(resposta)
        z = zlib.decompressobj(-15)
        crc = 0
        descompactado = 0
        lido = 0
        resto = b""
        cabecalho_lido = False
        parcial = False
        ultimo_aviso = time.perf_counter()

        def consumir(bloco: bytes, final: bool = False) -> None:
            nonlocal resto, cabecalho_lido
            dados = resto + bloco
            if final:
                corte, resto = len(dados), b""
            else:
                corte = dados.rfind(b"\n")
                if corte < 0:
                    resto = dados
                    return
                resto = dados[corte + 1:]
            texto = dados[:corte].decode("latin-1")
            if not texto:
                return
            linhas = texto.split("\n")
            if not cabecalho_lido:
                totais.definir_cabecalho(linhas.pop(0).rstrip("\r"))
                cabecalho_lido = True
            if linhas:
                totais.somar(linhas)

        while not z.eof:
            if limite_bytes and lido >= limite_bytes:
                parcial = True
                break
            bloco = resposta.read(CHUNK)
            if not bloco:
                raise ErroFonte("download interrompido antes do fim do arquivo compactado")
            lido += len(bloco)
            saida = z.decompress(bloco)
            crc = zlib.crc32(saida, crc)
            descompactado += len(saida)
            consumir(saida)
            agora = time.perf_counter()
            if agora - ultimo_aviso >= 30:
                ultimo_aviso = agora
                mb_lidos = lido / 1e6
                print(f"  {mb_lidos:,.0f} MB lidos, {totais.contagem['linhas']:,} linhas, "
                      f"{mb_lidos / (agora - inicio):,.1f} MB/s, memória {memoria_pico_mb() or '?'} MB", flush=True)
        if not parcial:
            consumir(z.flush(), final=True)
            if resto:
                consumir(b"", final=True)
    finally:
        resposta.close()

    conferencia = "não feita (leitura parcial)" if parcial else "sem CRC no cabeçalho"
    if not parcial and info["crc32"] is not None:
        if crc != info["crc32"] or descompactado != info["descompactado"]:
            raise ErroFonte("CRC ou tamanho do CSV não confere com o ZIP: arquivo corrompido")
        conferencia = "CRC32 e tamanho conferem"
    return {
        **info,
        "parcial": parcial,
        "bytes_compactados_lidos": lido,
        "bytes_descompactados": descompactado,
        "conferencia": conferencia,
        "segundos": round(time.perf_counter() - inicio, 1),
    }


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(CHUNK), b""):
            h.update(bloco)
    return h.hexdigest()


def gravar_sqlite(municipio: str, linhas: dict[str, list], totais: Totais, fonte: dict, pasta: Path) -> dict:
    """Modo teste: um SQLite compactado de um município, para abrir e conferir."""
    caminho = pasta / f"pni_{fonte['ano']}_{fonte['mes']:02d}_{municipio}.sqlite"
    caminho.unlink(missing_ok=True)
    db = sqlite3.connect(caminho)
    try:
        db.execute("PRAGMA journal_mode = OFF")
        db.execute("CREATE TABLE fonte (chave TEXT PRIMARY KEY, valor TEXT)")
        for tabela, colunas in TABELAS.items():
            definicao = ", ".join(f"{c} {'INTEGER' if c in ('doses', 'aplicada_fora', 'residente', 'raca_informada') else 'TEXT'}" for c in colunas)
            db.execute(f"CREATE TABLE {tabela} ({definicao})")
            db.executemany(f"INSERT INTO {tabela} VALUES ({','.join('?' * len(colunas))})", linhas.get(tabela, []))
        db.execute("CREATE TABLE dic_vacina (codigo TEXT PRIMARY KEY, sigla TEXT, nome TEXT)")
        db.executemany("INSERT INTO dic_vacina VALUES (?,?,?)", [(k, *v) for k, v in totais.dic_vacina.items()])
        for nome, dados in (("dose", totais.dic_dose), ("estrategia", totais.dic_estrategia),
                            ("origem_registro", totais.dic_origem), ("sistema_origem", totais.dic_sistema)):
            db.execute(f"CREATE TABLE dic_{nome} (codigo TEXT PRIMARY KEY, descricao TEXT)")
            db.executemany(f"INSERT INTO dic_{nome} VALUES (?,?)", list(dados.items()))
        db.executemany("INSERT INTO fonte VALUES (?,?)", [(k, str(v)) for k, v in fonte.items()])
        db.commit()
    finally:
        db.close()
    compactado = caminho.with_suffix(".sqlite.gz")
    with caminho.open("rb") as origem, gzip.open(compactado, "wb", compresslevel=9) as destino:
        shutil.copyfileobj(origem, destino, CHUNK)
    tamanho = caminho.stat().st_size
    caminho.unlink()
    return {"arquivo": compactado.name, "bytes": compactado.stat().st_size, "sqlite_bytes": tamanho,
            "sha256": sha256_arquivo(compactado), **{f"linhas_{t}": len(linhas.get(t, [])) for t in TABELAS}}


def gravar_zips_uf(totais: Totais, fonte: dict, pasta: Path) -> dict[str, dict]:
    """Modo produção: um ZIP por UF, com um JSON por município e um _dicionarios.json."""
    grupos: dict[str, dict[str, dict[str, list]]] = {}
    for municipio, linhas in totais.por_municipio().items():
        grupos.setdefault(UF_IBGE[municipio[:2]], {})[municipio] = linhas
    dicionarios = json.dumps({"formato": FORMATO, **totais.dicionarios()}, ensure_ascii=False, separators=(",", ":"))
    resultado = {}
    for uf in sorted(set(UF_IBGE.values())):
        municipios = grupos.get(uf, {})
        caminho = pasta / f"pni_{fonte['ano']}_{fonte['mes']:02d}_{uf}.zip"
        caminho.unlink(missing_ok=True)
        with zipfile.ZipFile(caminho, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as pacote:
            pacote.writestr("_dicionarios.json", dicionarios)
            for municipio in sorted(municipios):
                conteudo = {
                    "formato": FORMATO, "ano": fonte["ano"], "mes": fonte["mes"],
                    "municipio": municipio, "uf": uf, "nome": totais.nomes.get(municipio, ""),
                    "colunas": TABELAS, **municipios[municipio],
                }
                pacote.writestr(f"{municipio}.json", json.dumps(conteudo, ensure_ascii=False, separators=(",", ":")))
        resultado[uf] = {"arquivo": caminho.name, "bytes": caminho.stat().st_size,
                         "sha256": sha256_arquivo(caminho), "municipios": len(municipios)}
    return resultado


def memoria_pico_mb() -> float | None:
    try:
        import resource
    except ImportError:
        return _memoria_pico_windows_mb()
    pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(pico / 1024 if sys.platform != "darwin" else pico / 1024 / 1024, 1)


def _memoria_pico_windows_mb() -> float | None:
    try:
        import ctypes
        from ctypes import wintypes

        class Contadores(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        contadores = Contadores()
        contadores.cb = ctypes.sizeof(contadores)
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Contadores), wintypes.DWORD]
        kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        if not kernel32.K32GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(contadores), contadores.cb):
            return None
        return round(contadores.PeakWorkingSetSize / 1024 / 1024, 1)
    except (AttributeError, OSError):
        return None


def mb(n: int | None) -> str:
    return "—" if n is None else f"{n / 1e6:,.1f} MB"


def resumo_markdown(manifesto: dict) -> str:
    f, z, c = manifesto["fonte"], manifesto["leitura"], manifesto["contagem"]
    velocidade = z["bytes_compactados_lidos"] / 1e6 / z["segundos"] if z["segundos"] else 0
    alvo = manifesto.get("municipio")
    titulo = f"{alvo['nome'] or 'município'} ({alvo['codigo']}/{alvo['uf']})" if alvo else "todos os municípios"
    linhas = [
        f"## PNI {f['ano']}/{f['mes']:02d}: {titulo}",
        "",
        "| Item | Valor |",
        "|---|---|",
        f"| Arquivo | `{f['url']}` |",
        f"| Publicado em | {f['last_modified']} |",
        f"| ZIP / CSV | {mb(f['content_length'])} / {mb(z['descompactado'])} |",
        f"| Lido | {mb(z['bytes_compactados_lidos'])} compactado, {mb(z['bytes_descompactados'])} de CSV"
        + (" (**parcial**)" if z["parcial"] else "") + " |",
        f"| Conferência | {z['conferencia']} |",
        f"| Tempo de leitura | {z['segundos']:,.0f} s ({velocidade:,.1f} MB/s compactado) |",
        f"| Tempo de gravação | {manifesto['segundos_gravacao']:,.0f} s |",
        f"| Memória (pico) | {manifesto['memoria_pico_mb'] or '—'} MB |",
        f"| Linhas lidas (Brasil) / malformadas | {c['linhas']:,} / {c['malformadas']:,} |",
        f"| Linhas consideradas / deletadas | {c['consideradas']:,} / {c['deletadas']:,} |",
        f"| Doses por residência (cobertura) | {c['residentes']:,} |",
        f"| Doses por local de aplicação (produção) | {c['aplicadas']:,} |",
        f"| Sem município de residência válido | {c['sem_municipio_residencia']:,} |",
        f"| Com troca de documento | {c['com_troca_documento']:,} |",
        f"| Data da vacina fora do mês | {c['fora_do_mes']:,} |",
    ]
    arquivos = manifesto["arquivos"]
    if alvo:
        a = next(iter(arquivos.values()))
        linhas.append(f"| Arquivo gerado | `{a['arquivo']}`: **{mb(a['bytes'])}** compactado |")
        if not c["consideradas"]:
            linhas += ["", "**Nenhuma dose encontrada para este código de município.**"]
    else:
        linhas += ["", "| UF | Municípios | ZIP |", "|---|---:|---:|"]
        for uf, a in arquivos.items():
            linhas.append(f"| {uf} | {a['municipios']:,} | {mb(a['bytes'])} |")
        linhas.append(f"| **Total** | {sum(a['municipios'] for a in arquivos.values()):,} | "
                      f"**{mb(sum(a['bytes'] for a in arquivos.values()))}** |")
    return "\n".join(linhas + [""])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", required=True)
    p.add_argument("--mes", required=True, choices=MESES)
    alvo = p.add_mutually_exclusive_group(required=True)
    alvo.add_argument("--municipio", help="código IBGE do município (6 ou 7 dígitos): modo teste")
    alvo.add_argument("--todos", action="store_true", help="todos os municípios: modo produção")
    p.add_argument("--limite-mb", type=int, default=0, help="lê só os primeiros N MB compactados (0 = tudo)")
    p.add_argument("--saida", required=True)
    p.add_argument("--resumo", default="", help="arquivo onde acrescentar o resumo em Markdown")
    a = p.parse_args()

    if not re.fullmatch(r"20[2-9]\d", a.ano):
        p.error("ano inválido")
    municipio = uf = None
    if a.municipio is not None:
        codigo = a.municipio.strip()
        if not re.fullmatch(r"\d{6,7}", codigo) or codigo[:2] not in UF_IBGE:
            p.error("código de município inválido: use o código IBGE com 6 ou 7 dígitos")
        municipio, uf = codigo[:6], UF_IBGE[codigo[:2]]
    if a.limite_mb < 0:
        p.error("limite inválido")

    ano, mes = int(a.ano), MESES.index(a.mes) + 1
    pasta = Path(a.saida)
    pasta.mkdir(parents=True, exist_ok=True)

    print(f"Consultando {url_do_mes(ano, mes)}", flush=True)
    fonte = consultar_fonte(ano, mes)
    if fonte is None:
        print("Arquivo ainda não publicado pelo Ministério da Saúde.", file=sys.stderr)
        return 2
    print(f"  {mb(fonte['content_length'])}, publicado em {fonte['last_modified']}", flush=True)
    print(f"  somando {'o município ' + municipio + ' (' + uf + ')' if municipio else 'todos os municípios'}; "
          "o arquivo nacional é lido inteiro", flush=True)

    totais = Totais(mes, municipio)
    try:
        leitura = processar(fonte["url"], totais, a.limite_mb * 1024 * 1024)
    except (ErroFonte, OSError, zlib.error) as erro:
        print(f"Falha ao ler a fonte: {erro}", file=sys.stderr)
        return 1
    print(f"Leitura concluída em {leitura['segundos']} s: {totais.contagem['linhas']:,} linhas", flush=True)

    inicio = time.perf_counter()
    processado_em = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if municipio:
        linhas = totais.por_municipio().get(municipio, {})
        fonte_gravada = {**fonte, "municipio": municipio, "uf": uf, "nome_municipio": totais.nomes.get(municipio, ""),
                         "parcial": leitura["parcial"], "conferencia": leitura["conferencia"], "processado_em": processado_em}
        arquivos = {municipio: gravar_sqlite(municipio, linhas, totais, fonte_gravada, pasta)}
    else:
        arquivos = gravar_zips_uf(totais, fonte, pasta)

    manifesto = {
        "formato": FORMATO,
        "fonte": fonte,
        "processado_em": processado_em,
        "leitura": leitura,
        "contagem": totais.contagem,
        "segundos_gravacao": round(time.perf_counter() - inicio, 1),
        "memoria_pico_mb": memoria_pico_mb(),
        "arquivos": arquivos,
    }
    if municipio:
        manifesto["municipio"] = {"codigo": municipio, "uf": uf, "nome": totais.nomes.get(municipio, "")}
    (pasta / f"manifest_{ano}_{mes:02d}.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    texto = resumo_markdown(manifesto)
    print(texto)
    if a.resumo:
        with open(a.resumo, "a", encoding="utf-8") as saida:
            saida.write(texto + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
