"""Leitura dos totais do PNI publicados pelo projeto na release de dados do GitHub.

O workflow pni-dados.yml lê os arquivos mensais nacionais do Ministério da Saúde
(de 1,4 a 4,3 GB cada) e publica, na release pni-dados-AAAA, um ZIP por UF e mês
com um JSON por município, mais o manifesto do ano. Aqui o TabulaSUS baixa só o
manifesto e, de cada ZIP, só o trecho do município escolhido (pedidos HTTP por
faixa de bytes), conferindo o CRC32 de cada arquivo lido.
"""
from __future__ import annotations

import json
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
import zlib

REPOSITORY = "lisandro12matheus-cmd/SPPtab"
GITHUB_HOST = "github.com"
ASSET_HOSTS = {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}
USER_AGENT = "TabulaSUS-PNI/1.0"
TIMEOUT = 60
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_DIRECTORY_BYTES = 4 * 1024 * 1024
FORMAT = 1


class PniSourceError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _checked(url: str, hosts: set[str]) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise PniSourceError("A release de dados tentou redirecionar para um destino não permitido.")
    return url


def release_tag(year: int) -> str:
    return f"pni-dados-{year}"


def _asset_url(year: int, name: str) -> str:
    if not re.fullmatch(r"pni_\d{4}(_\d{2}_[A-Z]{2}\.zip|_manifest\.json)", name):
        raise PniSourceError("Nome de arquivo de dados inválido.")
    return f"https://{GITHUB_HOST}/{REPOSITORY}/releases/download/{release_tag(year)}/{name}"


def _resolve(year: int, name: str) -> str | None:
    """URL assinada do arquivo na release (None quando o arquivo não existe)."""
    opener = urllib.request.build_opener(_NoRedirect())
    request = urllib.request.Request(_asset_url(year, name), method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=TIMEOUT):
            raise PniSourceError("A release de dados respondeu sem redirecionar para o arquivo.")
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            location = exc.headers.get("Location") or ""
            return _checked(urllib.parse.urljoin(_asset_url(year, name), location), ASSET_HOSTS)
        if exc.code == 404:
            return None
        raise PniSourceError(f"A release de dados respondeu com HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise PniSourceError(f"Não foi possível acessar a release de dados no GitHub: {exc.reason}") from exc


def _get(url: str, start: int | None = None, end: int | None = None, limit: int = MAX_MANIFEST_BYTES) -> tuple[bytes, int | None]:
    """Baixa o arquivo inteiro ou a faixa [start, end]; devolve os bytes e o tamanho total."""
    headers = {"User-Agent": USER_AGENT}
    if start is not None:
        headers["Range"] = f"bytes={start}-{end}"
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(urllib.request.Request(_checked(url, ASSET_HOSTS), headers=headers), timeout=TIMEOUT) as response:
            total = None
            if start is not None:
                if response.status != 206:
                    raise PniSourceError("O GitHub não aceitou a leitura parcial do arquivo de dados.")
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", "").strip())
                if not match or int(match.group(1)) != start:
                    raise PniSourceError("O GitHub devolveu uma faixa de bytes inesperada.")
                total = int(match.group(3))
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise PniSourceError(f"A release de dados respondeu com HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise PniSourceError(f"Não foi possível baixar da release de dados: {exc.reason}") from exc
    if len(data) > limit:
        raise PniSourceError("O arquivo de dados ultrapassa o tamanho esperado.")
    return data, total


def fetch_manifest(year: int) -> dict | None:
    """Manifesto do ano, ou None quando a release ainda não existe."""
    url = _resolve(year, f"pni_{year}_manifest.json")
    if url is None:
        return None
    data, _ = _get(url)
    try:
        manifest = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PniSourceError("O manifesto dos dados do PNI está corrompido.") from exc
    if not isinstance(manifest, dict) or manifest.get("formato") != FORMAT or not isinstance(manifest.get("meses"), dict):
        raise PniSourceError("O manifesto dos dados do PNI tem um formato que esta versão do TabulaSUS não reconhece. Atualize o programa.")
    return manifest


def _central_directory(url: str) -> tuple[bytes, int]:
    """Lê o diretório central do ZIP a partir do fim do arquivo."""
    _, total = _get(url, 0, 0, limit=1)
    if not total or total < 22:
        raise PniSourceError("O arquivo de dados da UF está vazio ou incompleto.")
    tail_start = max(0, total - 66000)
    tail, _ = _get(url, tail_start, total - 1, limit=66000)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or position + 22 > len(tail):
        raise PniSourceError("O arquivo de dados da UF não tem o índice do ZIP.")
    _sig, _disk, _start_disk, _here, _entries, size, offset, _comment = struct.unpack("<IHHHHIIH", tail[position:position + 22])
    if offset == 0xFFFFFFFF or size > MAX_DIRECTORY_BYTES or offset + size > total:
        raise PniSourceError("O índice do arquivo de dados da UF é inválido.")
    if offset >= tail_start:
        return tail[offset - tail_start:offset - tail_start + size], total
    directory, _ = _get(url, offset, offset + size - 1, limit=size)
    return directory, total


def _find_entry(directory: bytes, wanted: str) -> dict | None:
    position = 0
    while position + 46 <= len(directory):
        (signature, _made, _need, flag, method, _time, _date, crc, csize, usize,
         name_size, extra_size, comment_size, _disk, _internal, _external, offset) = struct.unpack("<IHHHHHHIIIHHHHHII", directory[position:position + 46])
        if signature != 0x02014B50:
            raise PniSourceError("O índice do arquivo de dados da UF está corrompido.")
        name = directory[position + 46:position + 46 + name_size].decode("utf-8", "replace")
        if name == wanted:
            if flag & 0x1 or method not in (0, 8) or usize > MAX_MEMBER_BYTES:
                raise PniSourceError("O arquivo do município tem um formato inesperado.")
            return {"crc": crc, "csize": csize, "usize": usize, "method": method, "offset": offset}
        position += 46 + name_size + extra_size + comment_size
    return None


def fetch_members(year: int, asset: str, names: list[str]) -> dict[str, bytes | None]:
    """Lê do ZIP da UF só os arquivos pedidos (None quando o arquivo não existe no ZIP)."""
    url = _resolve(year, asset)
    if url is None:
        raise PniSourceError("O arquivo de dados desta UF ainda não está na release.")
    directory, total = _central_directory(url)
    result: dict[str, bytes | None] = {}
    for name in names:
        entry = _find_entry(directory, name)
        if entry is None:
            result[name] = None
            continue
        start = entry["offset"]
        end = min(total - 1, start + 30 + 1024 + entry["csize"] - 1)
        chunk, _ = _get(url, start, end, limit=end - start + 1)
        if len(chunk) < 30 or chunk[:4] != b"PK\x03\x04":
            raise PniSourceError("O arquivo do município está corrompido na release.")
        name_size, extra_size = struct.unpack("<HH", chunk[26:30])
        data_start = 30 + name_size + extra_size
        compressed = chunk[data_start:data_start + entry["csize"]]
        if len(compressed) != entry["csize"]:
            raise PniSourceError("O arquivo do município veio incompleto.")
        raw = compressed if entry["method"] == 0 else zlib.decompress(compressed, -15)
        if len(raw) != entry["usize"] or zlib.crc32(raw) != entry["crc"]:
            raise PniSourceError("O arquivo do município não confere com o CRC do ZIP.")
        result[name] = raw
    return result


def fetch_municipality(year: int, month: int, uf: str, municipality: str) -> tuple[dict | None, dict]:
    """Totais de um município num mês e os dicionários de códigos daquele mês."""
    if not re.fullmatch(r"\d{6}", municipality) or not re.fullmatch(r"[A-Z]{2}", uf) or not 1 <= month <= 12:
        raise PniSourceError("Município, UF ou mês inválido.")
    asset = f"pni_{year}_{month:02d}_{uf}.zip"
    members = fetch_members(year, asset, [f"{municipality}.json", "_dicionarios.json"])
    try:
        dictionaries = json.loads((members.get("_dicionarios.json") or b"{}").decode("utf-8"))
        data = json.loads(members[f"{municipality}.json"].decode("utf-8")) if members.get(f"{municipality}.json") else None
    except (UnicodeDecodeError, ValueError) as exc:
        raise PniSourceError("O arquivo do município está em um formato inválido.") from exc
    if data is not None and (data.get("formato") != FORMAT or data.get("municipio") != municipality):
        raise PniSourceError("O arquivo do município não corresponde ao pedido.")
    return data, dictionaries
