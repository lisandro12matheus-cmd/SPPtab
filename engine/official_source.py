"""Acesso HTTPS ao serviço público de transferência de arquivos do DATASUS."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import zipfile
import tempfile
import os
import shutil
from pathlib import Path


PORTAL = "https://datasus.saude.gov.br/wp-content/"
FTP_HOST = "ftp.datasus.gov.br"
DATA_KINDS = {
    "sia": ("AB", "ABO", "ACF", "AD", "AM", "AMP", "AN", "AQ", "AR", "ATD", "BI", "PA", "PS", "SAD"),
    "sih": ("CH", "CM", "ER", "RD", "RJ", "SP"),
}
VALID_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}
MAX_PORTAL_JSON_BYTES = 5 * 1024 * 1024
def _size_limit(name: str, default: int) -> int:
    try:
        configured = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        configured = default
    return max(64 * 1024 * 1024, min(configured, 16 * 1024 * 1024 * 1024))


MAX_ARCHIVE_BYTES = _size_limit("TABWIN2_MAX_ARCHIVE_BYTES", 2 * 1024 * 1024 * 1024)
MAX_DBC_BYTES = _size_limit("TABWIN2_MAX_DBC_BYTES", 4 * 1024 * 1024 * 1024)


class _VerifiedHTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_host: str):
        super().__init__()
        self.allowed_host = allowed_host.lower()

    def redirect_request(self, request, response, code, message, headers, new_url):
        target = urllib.parse.urljoin(request.full_url, new_url)
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme != "https" or parsed.hostname != self.allowed_host or parsed.port not in (None, 443) or parsed.username or parsed.password:
            raise ValueError("O serviço oficial tentou redirecionar a conexão para um destino não permitido.")
        return super().redirect_request(request, response, code, message, headers, target)


def open_verified_https(request, allowed_host: str, timeout: int):
    source = urllib.parse.urlparse(request.full_url)
    if source.scheme != "https" or source.hostname != allowed_host.lower() or source.port not in (None, 443) or source.username or source.password:
        raise ValueError("O endereço HTTPS solicitado não corresponde à fonte oficial esperada.")
    opener = urllib.request.build_opener(_VerifiedHTTPSRedirect(allowed_host))
    return opener.open(request, timeout=timeout)


def _post_json(endpoint: str, fields: list[tuple[str, str]], timeout: int) -> object:
    encoded = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(
        PORTAL + endpoint,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "SPPtab/1.0"},
        method="POST",
    )
    with open_verified_https(request, "datasus.saude.gov.br", timeout) as response:
        body = response.read(MAX_PORTAL_JSON_BYTES + 1)
        if len(body) > MAX_PORTAL_JSON_BYTES:
            raise ValueError("O serviço oficial retornou uma resposta grande demais.")
        return json.loads(body.decode("utf-8"))


def list_files(system: str, year: int, month: int | None, uf: str = "PA") -> list[str]:
    """Lista arquivos estaduais pelo formulário HTTPS oficial, sem exigir a porta FTP."""
    uf = uf.upper()
    if uf not in VALID_UFS:
        raise ValueError("Unidade da Federação inválida.")
    fields = [("tipo_arquivo[]", kind) for kind in DATA_KINDS[system]]
    fields += [("modalidade[]", "1"), ("fonte[]", "SIASUS" if system == "sia" else "SIHSUS"), ("ano[]", str(year))]
    fields += [("mes[]", f"{value:02d}") for value in ([month] if month else range(1, 13))]
    fields.append(("uf[]", uf))
    response = _post_json("ftp.php", fields, 25)
    if not isinstance(response, list):
        raise ValueError("O DATASUS não retornou uma lista de arquivos válida.")
    return [item["arquivo"] for item in response if isinstance(item, dict) and isinstance(item.get("arquivo"), str)]


def download_file(remote: str, expected_name: str, destination: Path, progress=None) -> None:
    """Pede ao DATASUS um ZIP por HTTPS e extrai apenas o arquivo solicitado."""
    if not remote.startswith("/dissemin/publicos/") or Path(remote).name.lower() != expected_name.lower():
        raise ValueError("O caminho do arquivo oficial é inválido.")
    source = "ftp://" + FTP_HOST + remote
    result = _post_json("download.php", [
        ("dados[0][arquivo]", expected_name),
        ("dados[0][link]", source),
    ], 120)
    if not isinstance(result, list) or not result or not isinstance(result[0], list) or not result[0]:
        raise ValueError("O DATASUS não preparou o arquivo para download.")
    url = result[0][0]
    parsed = urllib.parse.urlparse(url) if isinstance(url, str) else None
    if not parsed or parsed.scheme != "https" or parsed.hostname != "datasus.saude.gov.br" or not parsed.path.startswith("/wp-content/zipupload/") or not parsed.path.endswith("/arquivo.zip"):
        raise ValueError("O DATASUS retornou um endereço de download inesperado.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, archive_name = tempfile.mkstemp(prefix="spptab-portal-", suffix=".zip.part", dir=str(destination.parent))
    os.close(fd)
    archive_path = Path(archive_name)
    output_path = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "SPPtab/1.0"})
        with open_verified_https(request, "datasus.saude.gov.br", 120) as response, archive_path.open("wb") as output:
            total_size = int(response.headers.get("Content-Length") or 0)
            if total_size > MAX_ARCHIVE_BYTES:
                raise ValueError("O pacote oficial ultrapassa o limite configurado para download.")
            if shutil.disk_usage(destination.parent).free < total_size + 32 * 1024 * 1024:
                raise ValueError("Não há espaço livre suficiente para receber o arquivo DATASUS.")
            downloaded = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                if downloaded + len(chunk) > MAX_ARCHIVE_BYTES:
                    raise ValueError("O pacote oficial ultrapassou o limite configurado durante o download.")
                output.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total_size or None)
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > 50000:
                raise ValueError("O pacote oficial contém itens demais.")
            candidates = [entry for entry in infos if not entry.is_dir() and _zip_basename(entry.filename).lower() == expected_name.lower()]
            if len(candidates) != 1 or candidates[0].file_size < 32 or candidates[0].file_size > MAX_DBC_BYTES:
                raise ValueError("O pacote oficial não contém o arquivo solicitado ou está incompleto.")
            if shutil.disk_usage(destination.parent).free < candidates[0].file_size + 16 * 1024 * 1024:
                raise ValueError("Não há espaço livre suficiente para extrair o arquivo DATASUS.")
            fd, output_name = tempfile.mkstemp(prefix="spptab-dbc-", suffix=".part", dir=str(destination.parent))
            output_path = Path(output_name)
            written = 0
            try:
                with os.fdopen(fd, "wb") as output, archive.open(candidates[0]) as source_file:
                    while True:
                        chunk = source_file.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_DBC_BYTES or written > candidates[0].file_size:
                            raise ValueError("O arquivo extraído ultrapassou o limite declarado no pacote.")
                        output.write(chunk)
                if written != candidates[0].file_size:
                    raise ValueError("O arquivo extraído está incompleto.")
                os.replace(output_path, destination)
                output_path = None
            finally:
                if output_path is not None:
                    output_path.unlink(missing_ok=True)
    finally:
        archive_path.unlink(missing_ok=True)


def _zip_basename(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]
