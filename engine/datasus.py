#!/usr/bin/env python3
"""Busca e baixa arquivos DBC públicos do DATASUS para o SPPtab."""

from __future__ import annotations

import json
import gzip
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from ftplib import FTP
from pathlib import Path
from typing import Any

from official_source import download_file as portal_download_file, list_files as portal_list_files

HOST = "ftp.datasus.gov.br"
REMOTE = {
    "sia": "/dissemin/publicos/SIASUS/200801_/Dados",
    "sih": "/dissemin/publicos/SIHSUS/200801_/Dados",
}
ROOT = Path(__file__).resolve().parents[1]
UPLOADS = Path(os.environ.get("TABWIN2_DATA_DIR", ROOT / "uploads")).expanduser().resolve()
UPLOADS.mkdir(parents=True, exist_ok=True)
FILENAME_PATTERN = re.compile(r"^(?P<kind>[A-Z]{2,4}?)(?P<uf>[A-Z]{2})(?P<yy>\d{2})(?P<mm>0[1-9]|1[0-2])(?P<suffix>[A-Z])?\.DBC$", re.I)
SIH_KINDS = {"CH", "CM", "ER", "RD", "RJ", "SP"}
VALID_UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}
IBGE_UF_IDS = {"RO":"11", "AC":"12", "AM":"13", "RR":"14", "PA":"15", "AP":"16", "TO":"17", "MA":"21", "PI":"22", "CE":"23", "RN":"24", "PB":"25", "PE":"26", "AL":"27", "SE":"28", "BA":"29", "MG":"31", "ES":"32", "RJ":"33", "SP":"35", "PR":"41", "SC":"42", "RS":"43", "MS":"50", "MT":"51", "GO":"52", "DF":"53"}

SIA_LABELS = {
    "AB": "APAC · cirurgia bariátrica",
    "ABO": "Acompanhamento pós-cirurgia bariátrica",
    "ACF": "APAC · confecção de fístula",
    "AD": "APAC · laudos diversos",
    "AM": "APAC · medicamentos",
    "AMP": "APAC · acompanhamento multiprofissional",
    "AN": "APAC · nefrologia",
    "AQ": "APAC · quimioterapia",
    "AR": "APAC · radioterapia",
    "ATD": "APAC · tratamento dialítico",
    "BI": "Boletim de Produção Ambulatorial individualizado",
    "PA": "Produção Ambulatorial",
    "PS": "Registro de ações psicossociais (RAAS)",
    "SAD": "Serviço de Atenção Domiciliar",
}
SIH_LABELS = {
    "CH": "Arquivo hospitalar · CH",
    "CM": "Arquivo hospitalar · CM",
    "ER": "AIH rejeitada com código de erro",
    "RD": "AIH reduzida · internações",
    "RJ": "AIH rejeitada",
    "SP": "Serviços profissionais hospitalares",
}


class SourceError(Exception):
    pass


def connect() -> FTP:
    ftp = FTP(HOST, timeout=8)
    ftp.login()
    ftp.set_pasv(True)
    return ftp


def source_cache(system: str, year: int, uf: str = "PA") -> Path:
    folder = UPLOADS / ".cache" / "source-files"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{system}-{uf.lower()}-{year}.json"


def cached_source(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("names"), list) and all(isinstance(name, str) and FILENAME_PATTERN.fullmatch(name) for name in data["names"]) and isinstance(data.get("fetched_at"), (int, float)):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return None


def select_files(system: str, year: int, month: int | None = None, uf: str = "PA") -> list[dict[str, Any]]:
    uf = uf.upper()
    if uf not in VALID_UFS:
        raise SourceError("Unidade da Federação inválida.")
    directory = REMOTE[system]
    ftp = None
    cache_path = source_cache(system, year, uf)
    cached = cached_source(cache_path)
    freshness = 600 if year == datetime.now().year else 86400
    if cached and time.time() - cached["fetched_at"] < freshness:
        names = [directory + "/" + name for name in cached["names"]]
        source_mode = "cache"
    else:
        source_mode = "https"
        try:
            names = [directory + "/" + name for name in portal_list_files(system, year, None, uf) if name == name.rsplit("/", 1)[-1] and FILENAME_PATTERN.fullmatch(name)]
            temporary_cache = cache_path.with_suffix(".json.part")
            try:
                temporary_cache.write_text(json.dumps({"fetched_at": time.time(), "names": [name.rsplit("/", 1)[-1] for name in names]}), encoding="utf-8")
                os.replace(temporary_cache, cache_path)
            except OSError:
                temporary_cache.unlink(missing_ok=True)
        except Exception as https_error:
            if cached:
                names = [directory + "/" + name for name in cached["names"]]
                source_mode = "stale-cache"
            else:
                try:
                    ftp = connect()
                    names = ftp.nlst(directory)
                    source_mode = "ftp"
                    temporary_cache = cache_path.with_suffix(".json.part")
                    try:
                        temporary_cache.write_text(json.dumps({"fetched_at": time.time(), "names": [name.rsplit("/", 1)[-1] for name in names if FILENAME_PATTERN.fullmatch(name.rsplit("/", 1)[-1])]}), encoding="utf-8")
                        os.replace(temporary_cache, cache_path)
                    except OSError:
                        temporary_cache.unlink(missing_ok=True)
                except Exception as ftp_error:
                    if ftp is not None:
                        ftp.close()
                        ftp = None
                    local_root = UPLOADS / system.upper() / str(year)
                    local_names = [path.name for path in local_root.rglob("*") if path.is_file() and path.suffix.lower() == ".dbc"] if local_root.is_dir() else []
                    if not local_names:
                        raise SourceError(
                            "Não foi possível consultar o DATASUS por HTTPS nem FTP. "
                            "Confira a conexão com a internet ou tente outra rede. "
                            f"HTTPS: {https_error}; FTP: {ftp_error}"
                        ) from ftp_error
                    names = [directory + "/" + name for name in local_names]
                    source_mode = "local"

    try:
        found: list[dict[str, Any]] = []
        yy = f"{year % 100:02d}"
        for remote_path in names:
            filename = remote_path.rsplit("/", 1)[-1]
            match = FILENAME_PATTERN.fullmatch(filename)
            if not match or match.group("yy") != yy or match.group("uf").upper() != uf:
                continue
            if system == "sih" and match.group("kind").upper() not in SIH_KINDS:
                continue
            if month is not None and int(match.group("mm")) != month:
                continue
            kind = match.group("kind").upper()
            size = None
            modified = None
            found.append({
                "name": filename,
                "kind": kind,
                "uf": uf,
                "label": (SIA_LABELS if system == "sia" else SIH_LABELS).get(kind, f"Arquivo {kind}"),
                "month": int(match.group("mm")),
                "size": size,
                "modified": modified,
                "remote": remote_path,
                "source_mode": source_mode,
            })
            local = UPLOADS / relative_folder(system, year, int(match.group("mm")), kind) / filename
            found[-1]["local_path"] = str(local.relative_to(UPLOADS)).replace("\\", "/")
            found[-1]["downloaded"] = local.is_file() and local.stat().st_size > 0 and (size is None or local.stat().st_size == size)
            found[-1]["incomplete"] = local.is_file() and not found[-1]["downloaded"]
            if size is None and found[-1]["downloaded"]:
                found[-1]["size"] = local.stat().st_size
        return sorted(found, key=lambda item: (item["kind"], item["name"].lower()))
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                ftp.close()


def relative_folder(system: str, year: int, month: int, kind: str) -> Path:
    return Path(system.upper()) / str(year) / f"{month:02d}" / kind


def library_folder(system: str, year: int, month: int) -> str:
    """Return a stable, user-facing path independent of the app install folder."""
    return f"uploads/{relative_folder(system, year, month, '').as_posix()}"


def safe_size(size: int | None) -> str:
    if size is None:
        return "Tamanho não informado"
    units = ("B", "KB", "MB", "GB")
    amount = float(size)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    return f"{amount:.1f} {unit}"


def list_municipalities(uf: str) -> dict[str, Any]:
    uf = uf.upper()
    if uf not in IBGE_UF_IDS:
        raise SourceError("Unidade da Federação inválida.")
    cache_folder = UPLOADS / ".cache" / "municipalities"
    cache_folder.mkdir(parents=True, exist_ok=True)
    cache_path = cache_folder / f"{uf.lower()}.json"
    cached = None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(cached, dict) or not isinstance(cached.get("municipalities"), list):
            cached = None
    except (OSError, ValueError, TypeError):
        cached = None
    if cached and time.time() - float(cached.get("fetched_at", 0)) < 30 * 86400:
        return {"ok": True, "uf": uf, "municipalities": cached["municipalities"], "source_mode": "cache"}

    url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{IBGE_UF_IDS[uf]}/municipios?orderBy=nome"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "SPPtab/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            if urllib.parse.urlparse(response.geturl()).hostname != "servicodados.ibge.gov.br":
                raise ValueError("A consulta do IBGE foi redirecionada para outro domínio.")
            body = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip" or body.startswith(b"\x1f\x8b"):
                body = gzip.decompress(body)
            data = json.loads(body.decode("utf-8"))
        if not isinstance(data, list):
            raise ValueError("O IBGE não retornou a lista de municípios esperada.")
        municipalities = []
        for item in data:
            if not isinstance(item, dict):
                continue
            ibge_id = str(item.get("id", ""))
            name = item.get("nome")
            if len(ibge_id) == 7 and ibge_id.isdigit() and isinstance(name, str):
                municipalities.append({"code": ibge_id[:6], "ibge_id": ibge_id, "name": name})
        if not municipalities:
            raise ValueError("O IBGE não retornou municípios válidos para esta UF.")
        temporary = cache_path.with_suffix(".json.part")
        try:
            temporary.write_text(json.dumps({"fetched_at": time.time(), "municipalities": municipalities}, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, cache_path)
        except OSError:
            temporary.unlink(missing_ok=True)
        return {"ok": True, "uf": uf, "municipalities": municipalities, "source_mode": "ibge"}
    except Exception as exc:
        if cached:
            return {"ok": True, "uf": uf, "municipalities": cached["municipalities"], "source_mode": "stale-cache"}
        raise SourceError(f"Não foi possível carregar os municípios do IBGE: {exc}") from exc


def download_selected(system: str, year: int, month: int, requested_names: list[str], available: list[dict[str, Any]] | None = None, uf: str = "PA") -> dict[str, Any]:
    if available is None:
        available = select_files(system, year, month, uf)
    allowed = {item["name"].upper(): item for item in available}
    names = list(dict.fromkeys(name.upper() for name in requested_names))
    if not names or any(name not in allowed for name in names):
        raise SourceError("A seleção contém arquivo que não existe na competência escolhida.")

    results = []
    for name in names:
        item = allowed[name]
        folder = UPLOADS / relative_folder(system, year, month, item["kind"])
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / item["name"]
        if target.exists() and target.stat().st_size > 0 and (item["size"] is None or target.stat().st_size == item["size"]):
            results.append({"name": item["name"], "path": str(target.relative_to(UPLOADS)).replace("\\", "/"), "size": target.stat().st_size, "already_present": True})
            continue

        fd, temporary = tempfile.mkstemp(prefix=f".{item['name']}.", suffix=".part", dir=folder)
        os.close(fd)
        written = 0
        try:
            try:
                portal_download_file(item["remote"], item["name"], Path(temporary))
                written = Path(temporary).stat().st_size
            except Exception as https_error:
                try:
                    ftp = connect()
                    try:
                        with open(temporary, "wb") as stream:
                            def write_chunk(chunk: bytes) -> None:
                                nonlocal written
                                stream.write(chunk)
                                written += len(chunk)
                            ftp.retrbinary(f"RETR {item['remote']}", write_chunk, blocksize=1024 * 128)
                    finally:
                        try:
                            ftp.quit()
                        except Exception:
                            ftp.close()
                except Exception as ftp_error:
                    raise SourceError(
                        f"Não foi possível baixar {item['name']} por HTTPS nem FTP. "
                        f"HTTPS: {https_error}; FTP: {ftp_error}"
                    ) from ftp_error
            if item["size"] is not None and written != item["size"]:
                raise SourceError(f"O arquivo {item['name']} chegou incompleto ({written} de {item['size']} bytes).")
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        results.append({"name": item["name"], "path": str(target.relative_to(UPLOADS)).replace("\\", "/"), "size": written, "already_present": False})

    manifest_path = UPLOADS / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except (OSError, json.JSONDecodeError):
            existing = []
    by_path = {entry.get("path"): entry for entry in existing if isinstance(entry, dict) and entry.get("path")}
    for result in results:
        item = allowed[result["name"].upper()]
        by_path[result["path"]] = {
            "path": result["path"], "filename": result["name"], "system": system.upper(),
            "type": item["kind"], "year": year, "month": month,
            "source": f"ftp://{HOST}{item['remote']}", "source_size_bytes": item["size"],
            "downloaded_size_bytes": result["size"], "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_manifest = manifest_path.with_suffix(".json.part")
    temporary_manifest.write_text(json.dumps(list(by_path.values()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest_path)
    return {"files": results, "folder": library_folder(system, year, month)}


def main() -> int:
    try:
        request = json.load(sys.stdin)
        action = request.get("action")
        if action == "municipalities":
            output = list_municipalities(str(request.get("uf", "")).upper())
            sys.stdout.write(json.dumps(output, ensure_ascii=True))
            return 0
        system = request.get("system")
        year = int(request.get("year"))
        month = int(request["month"]) if "month" in request else None
        uf = str(request.get("uf", "PA")).upper()
        if system not in REMOTE or year < 2008 or year > datetime.now().year:
            raise SourceError("Base ou ano inválido.")
        if uf not in VALID_UFS:
            raise SourceError("Unidade da Federação inválida.")

        if action in {"competencies", "files", "download"}:
            files = select_files(system, year, month if action != "competencies" else None, uf)
        else:
            raise SourceError("Ação não reconhecida.")

        if action == "competencies":
            months = sorted({item["month"] for item in files})
            for item in files:
                item["size_label"] = safe_size(item["size"])
            output: dict[str, Any] = {"ok": True, "system": system, "year": year, "uf": uf, "months": months, "files_count": len(files), "files": files, "source_mode": files[0]["source_mode"] if files else "https"}
        elif action == "files":
            for item in files:
                item["size_label"] = safe_size(item["size"])
            output = {"ok": True, "system": system, "year": year, "month": month, "uf": uf, "files": files, "count": len(files), "source_mode": files[0]["source_mode"] if files else "https"}
        else:
            downloaded = download_selected(system, year, month or 0, request.get("names", []), files, uf)
            output = {"ok": True, "system": system, "year": year, "month": month, "uf": uf, **downloaded}

        # Escaped Unicode keeps stdout valid even when Apache starts Python with a legacy Windows code page.
        sys.stdout.write(json.dumps(output, ensure_ascii=True))
        return 0
    except SourceError as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
        return 2
    except (OSError, ValueError, KeyError, TypeError, TimeoutError) as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": f"Falha na comunicação ou gravação: {exc}"}, ensure_ascii=True))
        return 2
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": f"Não foi possível concluir: {exc}"}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
