#!/usr/bin/env python3
"""Teste: lê em fluxo o CSV mensal de doses aplicadas do PNI e gera os totais de um município.

O arquivo oficial é um ZIP nacional de 1,4 a 4,3 GB com um CSV de 5 a 17 GB, com
todos os municípios misturados. Por isso o arquivo inteiro sempre é lido, mas só
as doses do município escolhido são somadas: as de quem mora nele (cobertura) e
as aplicadas nos estabelecimentos dele (produção e qualidade). O script não grava
o ZIP nem o CSV; grava só os totais (um SQLite compactado) e um manifesto.

Uso:
  python -I tools/pni/pni_totais.py --ano 2026 --mes jan --municipio 1501402 --saida saida-pni
  python -I tools/pni/pni_totais.py --ano 2026 --mes jan --municipio 150140 --limite-mb 50 --saida saida-pni

--municipio aceita o código IBGE com 6 ou 7 dígitos (o PNI usa 6).

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
import zlib
from pathlib import Path

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
USER_AGENT = "TabulaSUS-PNI-teste/0.1"

COLUNAS = [
    "sg_uf_paciente", "co_municipio_paciente", "no_municipio_paciente", "nu_idade_paciente",
    "tp_sexo_paciente", "co_raca_cor_paciente", "co_condicao_maternal",
    "sg_uf_estabelecimento", "co_municipio_estabelecimento", "no_municipio_estabelecimento",
    "co_cnes_estabelecimento",
    "co_vacina", "sg_imunobiologico", "ds_nome", "co_dose_vacina", "ds_tipo_dose",
    "co_estrategia_vacinacao", "no_estrategia", "co_origem_registro", "ds_origem_registro",
    "co_sistema_origem", "ds_sistema_origem",
    "dt_vacina", "dt_entrada_rnds", "dt_deletado_rnds", "co_troca_documento",
]


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


def abrir(url: str, metodo: str = "GET"):
    pedido = urllib.request.Request(url, method=metodo, headers={"User-Agent": USER_AGENT})
    resposta = urllib.request.urlopen(pedido, timeout=TIMEOUT)
    final = urllib.parse.urlsplit(resposta.geturl())
    if final.scheme != "https" or final.hostname != HOST:
        resposta.close()
        raise ErroFonte(f"redirecionamento inesperado para {final.scheme}://{final.hostname}")
    return resposta


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
    def __init__(self, mes: int, municipio: str):
        self.mes = mes
        self.municipio = municipio
        self.nome_municipio = ""
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
            "linhas": 0, "malformadas": 0, "do_municipio": 0, "deletadas": 0,
            "residentes": 0, "aplicadas_no_municipio": 0,
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
        uf_p, mun_p, idade_p, sexo_p = x["sg_uf_paciente"], x["co_municipio_paciente"], x["nu_idade_paciente"], x["tp_sexo_paciente"]
        nome_p, nome_e = x["no_municipio_paciente"], x["no_municipio_estabelecimento"]
        raca_p, cond_p = x["co_raca_cor_paciente"], x["co_condicao_maternal"]
        uf_e, mun_e, cnes_e = x["sg_uf_estabelecimento"], x["co_municipio_estabelecimento"], x["co_cnes_estabelecimento"]
        municipio = self.municipio
        vac, sig, nome = x["co_vacina"], x["sg_imunobiologico"], x["ds_nome"]
        dose, dose_ds = x["co_dose_vacina"], x["ds_tipo_dose"]
        estr, estr_ds = x["co_estrategia_vacinacao"], x["no_estrategia"]
        orig, orig_ds = x["co_origem_registro"], x["ds_origem_registro"]
        sist, sist_ds = x["co_sistema_origem"], x["ds_sistema_origem"]
        dvac, dent, ddel, troca = x["dt_vacina"], x["dt_entrada_rnds"], x["dt_deletado_rnds"], x["co_troca_documento"]
        ncols = self.ncols
        prefixo_mes = f"-{self.mes:02d}-"
        cob, prod, qual = self.cobertura, self.producao, self.qualidade
        cob_get, prod_get, qual_get = cob.get, prod.get, qual.get
        idades = self._idade
        c = self.contagem

        for r in csv.reader(linhas, delimiter=";"):
            c["linhas"] += 1
            if len(r) != ncols:
                c["malformadas"] += 1
                continue
            residente = r[mun_p] == municipio
            aplicada_aqui = r[mun_e] == municipio
            if not (residente or aplicada_aqui):
                continue
            c["do_municipio"] += 1
            if not self.nome_municipio:
                self.nome_municipio = r[nome_p] if residente else r[nome_e]
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

            if residente:
                # Cobertura: por residência; guarda onde foi aplicada para ver vacinação fora do município.
                k = (r[uf_p], r[mun_p], r[mun_e], v, d, idades.get(r[idade_p], "ign"), r[sexo_p], r[cond_p])
                cob[k] = cob_get(k, 0) + 1
                c["residentes"] += 1
            if aplicada_aqui:
                # Produção e qualidade: pelo estabelecimento que aplicou.
                k = (r[uf_e], r[mun_e], r[cnes_e], r[mun_p], v, d, e)
                prod[k] = prod_get(k, 0) + 1
                raca = r[raca_p]
                k = (r[uf_e], r[mun_e], r[cnes_e], s, o,
                     0 if raca in ("", "99") else 1, self.atraso(data_vacina, r[dent][:10]))
                qual[k] = qual_get(k, 0) + 1
                c["aplicadas_no_municipio"] += 1


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
                mb = lido / 1e6
                print(f"  {mb:,.0f} MB lidos, {totais.contagem['linhas']:,} linhas, "
                      f"{mb / (agora - inicio):,.1f} MB/s", flush=True)
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


def gravar(totais: Totais, fonte: dict, pasta: Path) -> dict:
    caminho = pasta / f"pni_{fonte['ano']}_{fonte['mes']:02d}_{totais.municipio}.sqlite"
    caminho.unlink(missing_ok=True)
    db = sqlite3.connect(caminho)
    try:
        db.executescript("""
            PRAGMA journal_mode = OFF;
            CREATE TABLE fonte (chave TEXT PRIMARY KEY, valor TEXT);
            CREATE TABLE cobertura (mes INTEGER, uf TEXT, municipio TEXT, municipio_aplicacao TEXT,
                vacina TEXT, dose TEXT, idade TEXT, sexo TEXT, condicao_maternal TEXT, doses INTEGER);
            CREATE TABLE producao (mes INTEGER, uf TEXT, municipio TEXT, cnes TEXT, municipio_residencia TEXT,
                vacina TEXT, dose TEXT, estrategia TEXT, doses INTEGER);
            CREATE TABLE qualidade (mes INTEGER, uf TEXT, municipio TEXT, cnes TEXT, sistema_origem TEXT,
                origem_registro TEXT, raca_informada INTEGER, atraso_dias TEXT, doses INTEGER);
            CREATE TABLE dic_vacina (codigo TEXT PRIMARY KEY, sigla TEXT, nome TEXT);
            CREATE TABLE dic_dose (codigo TEXT PRIMARY KEY, descricao TEXT);
            CREATE TABLE dic_estrategia (codigo TEXT PRIMARY KEY, descricao TEXT);
            CREATE TABLE dic_origem_registro (codigo TEXT PRIMARY KEY, descricao TEXT);
            CREATE TABLE dic_sistema_origem (codigo TEXT PRIMARY KEY, descricao TEXT);
        """)
        m = totais.mes
        cob = [(m, *k, n) for k, n in totais.cobertura.items()]
        prod = [(m, *k, n) for k, n in totais.producao.items()]
        qual = [(m, *k, n) for k, n in totais.qualidade.items()]
        db.executemany("INSERT INTO cobertura VALUES (?,?,?,?,?,?,?,?,?,?)", cob)
        db.executemany("INSERT INTO producao VALUES (?,?,?,?,?,?,?,?,?)", prod)
        db.executemany("INSERT INTO qualidade VALUES (?,?,?,?,?,?,?,?,?)", qual)
        db.executemany("INSERT INTO dic_vacina VALUES (?,?,?)", [(k, *v) for k, v in totais.dic_vacina.items()])
        db.executemany("INSERT INTO dic_dose VALUES (?,?)", list(totais.dic_dose.items()))
        db.executemany("INSERT INTO dic_estrategia VALUES (?,?)", list(totais.dic_estrategia.items()))
        db.executemany("INSERT INTO dic_origem_registro VALUES (?,?)", list(totais.dic_origem.items()))
        db.executemany("INSERT INTO dic_sistema_origem VALUES (?,?)", list(totais.dic_sistema.items()))
        db.executemany("INSERT INTO fonte VALUES (?,?)", [(k, str(v)) for k, v in fonte.items()])
        db.commit()
    finally:
        db.close()

    compactado = caminho.with_suffix(".sqlite.gz")
    with caminho.open("rb") as origem, gzip.open(compactado, "wb", compresslevel=9) as destino:
        shutil.copyfileobj(origem, destino, CHUNK)
    tamanho = caminho.stat().st_size
    caminho.unlink()
    return {
        "arquivo": compactado.name,
        "linhas_cobertura": len(cob),
        "linhas_producao": len(prod),
        "linhas_qualidade": len(qual),
        "sqlite_bytes": tamanho,
        "gz_bytes": compactado.stat().st_size,
        "sha256": hashlib.sha256(compactado.read_bytes()).hexdigest(),
    }


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
    u, mun = manifesto["arquivo"], manifesto["municipio"]
    velocidade = z["bytes_compactados_lidos"] / 1e6 / z["segundos"] if z["segundos"] else 0
    linhas = [
        f"## PNI {f['ano']}/{f['mes']:02d}: {mun['nome'] or 'município'} ({mun['codigo']}/{mun['uf']})",
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
        f"| Linhas do município / deletadas | {c['do_municipio']:,} / {c['deletadas']:,} |",
        f"| Doses de residentes (cobertura) | {c['residentes']:,} |",
        f"| Doses aplicadas no município (produção) | {c['aplicadas_no_municipio']:,} |",
        f"| Com troca de documento | {c['com_troca_documento']:,} |",
        f"| Data da vacina fora do mês | {c['fora_do_mes']:,} |",
        f"| Combinações | cobertura {u['linhas_cobertura']:,}, produção {u['linhas_producao']:,}, "
        f"qualidade {u['linhas_qualidade']:,} |",
        f"| Arquivo gerado | `{u['arquivo']}`: {mb(u['sqlite_bytes'])} SQLite, **{mb(u['gz_bytes'])}** compactado |",
        "",
    ]
    if not c["do_municipio"]:
        linhas += ["**Nenhuma dose encontrada para este código de município.**", ""]
    return "\n".join(linhas)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano", required=True)
    p.add_argument("--mes", required=True, choices=MESES)
    p.add_argument("--municipio", required=True, help="código IBGE do município (6 ou 7 dígitos)")
    p.add_argument("--limite-mb", type=int, default=0, help="lê só os primeiros N MB compactados (0 = tudo)")
    p.add_argument("--saida", required=True)
    p.add_argument("--resumo", default="", help="arquivo onde acrescentar o resumo em Markdown")
    a = p.parse_args()

    if not re.fullmatch(r"20[2-9]\d", a.ano):
        p.error("ano inválido")
    codigo = a.municipio.strip()
    if not re.fullmatch(r"\d{6,7}", codigo) or codigo[:2] not in UF_IBGE:
        p.error("código de município inválido: use o código IBGE com 6 ou 7 dígitos")
    municipio, uf = codigo[:6], UF_IBGE[codigo[:2]]
    if a.limite_mb < 0:
        p.error("limite inválido")

    ano, mes = int(a.ano), MESES.index(a.mes) + 1
    url = f"{BASE}vacinacao_{a.mes}_{ano}_csv.zip"
    pasta = Path(a.saida)
    pasta.mkdir(parents=True, exist_ok=True)

    print(f"Consultando {url}", flush=True)
    try:
        cabeca = abrir(url, "HEAD")
    except urllib.error.HTTPError as erro:
        print(f"Arquivo indisponível na fonte (HTTP {erro.code}).", file=sys.stderr)
        return 2
    with cabeca:
        fonte = {
            "ano": ano, "mes": mes, "url": url,
            "etag": cabeca.headers.get("ETag", "").strip('"'),
            "last_modified": cabeca.headers.get("Last-Modified", ""),
            "content_length": int(cabeca.headers.get("Content-Length") or 0) or None,
        }
    print(f"  {mb(fonte['content_length'])}, publicado em {fonte['last_modified']}", flush=True)

    print(f"  somando só o município {municipio} ({uf}); o arquivo nacional é lido inteiro", flush=True)
    totais = Totais(mes, municipio)
    try:
        leitura = processar(url, totais, a.limite_mb * 1024 * 1024)
    except (ErroFonte, OSError, zlib.error) as erro:
        print(f"Falha ao ler a fonte: {erro}", file=sys.stderr)
        return 1
    print(f"Leitura concluída em {leitura['segundos']} s: {totais.contagem['linhas']:,} linhas", flush=True)

    inicio = time.perf_counter()
    dados_municipio = {"codigo": municipio, "uf": uf, "nome": totais.nome_municipio}
    fonte_gravada = {**fonte, "municipio": municipio, "uf": uf, "nome_municipio": totais.nome_municipio,
                     "parcial": leitura["parcial"], "conferencia": leitura["conferencia"],
                     "processado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    arquivo = gravar(totais, fonte_gravada, pasta)

    manifesto = {
        "fonte": fonte,
        "municipio": dados_municipio,
        "leitura": leitura,
        "contagem": totais.contagem,
        "segundos_gravacao": round(time.perf_counter() - inicio, 1),
        "memoria_pico_mb": memoria_pico_mb(),
        "arquivo": arquivo,
    }
    (pasta / "manifest.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    texto = resumo_markdown(manifesto)
    print(texto)
    if a.resumo:
        with open(a.resumo, "a", encoding="utf-8") as saida:
            saida.write(texto + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
