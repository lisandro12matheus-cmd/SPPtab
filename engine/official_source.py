"""Acesso HTTPS ao serviço público de transferência de arquivos do DATASUS."""

from __future__ import annotations

import json
import shutil
import urllib.parse
import urllib.request
import zipfile
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


def _post_json(endpoint: str, fields: list[tuple[str, str]], timeout: int) -> object:
    encoded = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(
        PORTAL + endpoint,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "SPPtab/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if urllib.parse.urlparse(response.geturl()).hostname != "datasus.saude.gov.br":
            raise ValueError("O serviço oficial redirecionou a consulta para outro domínio.")
        return json.load(response)


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

    archive_path = destination.with_name(destination.name + ".zip.part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "SPPtab/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response, archive_path.open("wb") as output:
            if urllib.parse.urlparse(response.geturl()).hostname != "datasus.saude.gov.br":
                raise ValueError("O download foi redirecionado para outro domínio.")
            total_size = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total_size or None)
        with zipfile.ZipFile(archive_path) as archive:
            candidates = [entry for entry in archive.infolist() if not entry.is_dir() and Path(entry.filename).name.lower() == expected_name.lower()]
            if len(candidates) != 1 or candidates[0].file_size < 32:
                raise ValueError("O pacote oficial não contém o arquivo solicitado ou está incompleto.")
            with archive.open(candidates[0]) as source_file, destination.open("wb") as output:
                shutil.copyfileobj(source_file, output, length=1024 * 1024)
    finally:
        archive_path.unlink(missing_ok=True)
