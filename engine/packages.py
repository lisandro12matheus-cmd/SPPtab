"""Baixa pacotes oficiais do CNES/SIGTAP e cruza tabelas locais com uma tabulação."""
from __future__ import annotations

import ftplib
import csv
import io
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import zipfile
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any

import tabulation
from official_source import download_file as portal_download_file

ROOT = Path(__file__).resolve().parents[1]
UPLOADS = Path(os.environ.get("TABWIN2_DATA_DIR", ROOT / "uploads")).expanduser().resolve()
CNES_DATA = "/dissemin/publicos/CNES/200508_/Dados"
FTP_HOST = "ftp.datasus.gov.br"
SIGTAP_HOST = "ftp2.datasus.gov.br"
SIGTAP_DOWNLOADS = "/pub/sistemas/tup/downloads"
VALID_UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}
MODULES = {
    "ST": {"label": "Estabelecimentos", "description": "Identificação e dados básicos dos serviços de saúde.", "relationship": "CNES", "priority": 1},
    "DC": {"label": "Dados complementares", "description": "Caracterização, gestão, natureza e outros dados do estabelecimento.", "relationship": "CNES", "priority": 2},
    "PF": {"label": "Profissionais", "description": "Profissionais, CNS, CBO e vínculos por estabelecimento.", "relationship": "CNES ou CNS", "priority": 3},
    "LT": {"label": "Leitos", "description": "Tipos e quantidades de leitos por estabelecimento.", "relationship": "CNES", "priority": 4},
    "EQ": {"label": "Equipamentos", "description": "Recursos e quantidades de equipamentos cadastrados no CNES.", "relationship": "CNES", "priority": 5},
    "EP": {"label": "Equipes", "description": "Equipes de saúde vinculadas aos estabelecimentos.", "relationship": "CNES", "priority": 6},
    "SR": {"label": "Serviços especializados", "description": "Serviços e classificações cadastrados para cada estabelecimento.", "relationship": "CNES", "priority": 7},
    "HB": {"label": "Habilitações", "description": "Habilitações vigentes informadas para o estabelecimento.", "relationship": "CNES", "priority": 8},
    "SIGTAP": {"label": "Procedimentos SIGTAP", "description": "Descrição, complexidade, valores e atributos por código de procedimento.", "relationship": "Código do procedimento", "priority": 9},
}
PACKAGE_ROOT = UPLOADS / "PACOTES" / "CNES"
SIGTAP_ROOT = UPLOADS / "PACOTES" / "SIGTAP"
JOB_ROOT = UPLOADS / ".jobs" / "packages"
JOB_ID = re.compile(r"^[a-f0-9]{32}$")


def _json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    temp.write_text(json.dumps(value, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, path)


def _job_path(job_id: str) -> Path:
    if not JOB_ID.fullmatch(str(job_id)):
        raise ValueError("Identificador do trabalho inválido.")
    return JOB_ROOT / f"{job_id}.json"


def _write_job(job_id: str, state: dict[str, Any]) -> None:
    _json_write(_job_path(job_id), state)


def _ftp(host: str = FTP_HOST) -> ftplib.FTP:
    ftp = ftplib.FTP(host, timeout=18)
    ftp.login()
    ftp.set_pasv(True)
    return ftp


def _month_from_name(name: str, module: str, uf: str) -> tuple[int, int] | None:
    match = re.fullmatch(rf"{re.escape(module)}{re.escape(uf)}(?P<yy>\d{{2}})(?P<mm>0[1-9]|1[0-2])\.dbc", Path(name).name, re.I)
    if not match:
        return None
    yy = int(match.group("yy"))
    return (2000 + yy if yy < 80 else 1900 + yy), int(match.group("mm"))


def _remote_cache(uf: str) -> Path:
    return UPLOADS / ".cache" / "cnes-catalog" / f"{uf.lower()}.json"


def _remote_catalog(uf: str, force: bool = False) -> dict[str, list[dict[str, Any]]]:
    cache_path = _remote_cache(uf)
    if not force:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("version") == 2 and cached.get("uf") == uf and time.time() - float(cached.get("fetched_at", 0)) < 1800 and isinstance(cached.get("files"), dict):
                return cached["files"]
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    ftp = None
    try:
        ftp = _ftp()
        catalog: dict[str, list[dict[str, Any]]] = {}
        for module, spec in MODULES.items():
            if module == "SIGTAP":
                continue
            directory = f"{CNES_DATA}/{module}"
            try:
                paths = ftp.nlst(directory)
            except ftplib.error_perm:
                catalog[module] = []
                continue
            found = []
            for path in paths:
                name = PurePosixPath(path).name
                date = _month_from_name(name, module, uf)
                if not date:
                    continue
                year, month = date
                found.append({"module": module, "name": name, "remote": f"{directory}/{name}", "year": year, "month": month, "size": None, "label": spec["label"]})
            catalog[module] = sorted(found, key=lambda item: (item["year"], item["month"]), reverse=True)
        catalog["SIGTAP"] = []
        _json_write(cache_path, {"version": 2, "uf": uf, "fetched_at": time.time(), "files": catalog})
        return catalog
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except ftplib.all_errors:
                ftp.close()


def _remote_sigtap_catalog(force: bool = False) -> list[dict[str, Any]]:
    cache_path = UPLOADS / ".cache" / "sigtap-catalog.json"
    if not force:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("version") == 1 and time.time() - float(cached.get("fetched_at", 0)) < 1800 and isinstance(cached.get("files"), list):
                return cached["files"]
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    ftp = _ftp(SIGTAP_HOST)
    try:
        chosen: dict[tuple[int, int], dict[str, Any]] = {}
        pattern = re.compile(r"^TabelaUnificada_(?P<year>20\d{2})(?P<month>0[1-9]|1[0-2])_(?P<version>v\d+)\.zip$", re.I)
        for remote in ftp.nlst(SIGTAP_DOWNLOADS):
            name = PurePosixPath(remote).name
            match = pattern.fullmatch(name)
            if not match:
                continue
            year, month = int(match.group("year")), int(match.group("month"))
            key = (year, month)
            current = chosen.get(key)
            if current and str(current["version"]) >= match.group("version"):
                continue
            chosen[key] = {"module": "SIGTAP", "name": name, "remote": f"{SIGTAP_DOWNLOADS}/{name}", "year": year, "month": month, "size": None, "version": match.group("version"), "label": MODULES["SIGTAP"]["label"]}
        result = sorted(chosen.values(), key=lambda item: (item["year"], item["month"]), reverse=True)
        _json_write(cache_path, {"version": 1, "fetched_at": time.time(), "files": result})
        return result
    finally:
        try:
            ftp.quit()
        except ftplib.all_errors:
            ftp.close()


def _populate_sizes(entries: list[dict[str, Any]], host: str) -> None:
    pending = [item for item in entries if item.get("remote") and item.get("size") is None]
    if not pending:
        return
    ftp = None
    try:
        ftp = _ftp(host)
        for item in pending:
            try:
                item["size"] = ftp.size(str(item["remote"]))
            except (ftplib.all_errors, OSError):
                item["size"] = None
    except (ftplib.all_errors, OSError, socket.timeout):
        return
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except ftplib.all_errors:
                ftp.close()
def _size_label(size: int | None) -> str:
    if size is None:
        return "Tamanho não informado"
    amount = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB"


def catalog(payload: dict[str, Any]) -> dict[str, Any]:
    uf = str(payload.get("uf", "PA")).upper()
    if uf not in VALID_UFS:
        raise ValueError("Selecione uma unidade da Federação válida.")
    errors = []
    try:
        files = _remote_catalog(uf, bool(payload.get("refresh")))
    except Exception as exc:
        files = {module: [] for module in MODULES if module != "SIGTAP"}
        errors.append(f"CNES: {exc}")
    try:
        sigtap_files = _remote_sigtap_catalog(bool(payload.get("refresh")))
    except Exception as exc:
        sigtap_files = []
        errors.append(f"SIGTAP: {exc}")
    competencies: dict[str, set[str]] = defaultdict(set)
    selected_year = int(payload.get("year") or 0)
    selected_month = int(payload.get("month") or 0)
    available = []
    for module, entries in files.items():
        for entry in entries:
            key = f"{entry['year']:04d}-{entry['month']:02d}"
            competencies[key].add(module)
            if selected_year and entry["year"] != selected_year:
                continue
            if selected_month and entry["month"] != selected_month:
                continue
            if not selected_year and not selected_month:
                continue
            if (selected_year or selected_month):
                item = dict(entry)
                local = _local_file_for(item)
                dbf = local.with_suffix(".dbf")
                item["saved"] = local.is_file() and local.stat().st_size > 0 and dbf.is_file() and dbf.stat().st_size > 32
                available.append(item)
    for entry in sigtap_files:
        key = f"{entry['year']:04d}-{entry['month']:02d}"
        competencies[key].add("SIGTAP")
    months = [{"key": key, "year": int(key[:4]), "month": int(key[5:]), "modules": sorted(mods, key=lambda item: MODULES[item]["priority"])} for key, mods in competencies.items()]
    months.sort(key=lambda item: (item["year"], item["month"]), reverse=True)
    if not payload.get("year") and not payload.get("month") and months:
        selected_year, selected_month = months[0]["year"], months[0]["month"]
        for module, entries in files.items():
            for entry in entries:
                if entry["year"] == selected_year and entry["month"] == selected_month:
                    item = dict(entry)
                    local = _local_file_for(item)
                    dbf = local.with_suffix(".dbf")
                    item["saved"] = local.is_file() and local.stat().st_size > 0 and dbf.is_file() and dbf.stat().st_size > 32
                    available.append(item)
    _populate_sizes(available, FTP_HOST)
    if available:
        for item in available:
            for entry in files.get(item["module"], []):
                if entry["name"] == item["name"]:
                    entry["size"] = item.get("size")
                    break
        _json_write(_remote_cache(uf), {"version": 2, "uf": uf, "fetched_at": time.time(), "files": files})
    sigtap_package = None
    if selected_year or selected_month:
        match = next((entry for entry in sigtap_files if (not selected_year or entry["year"] == selected_year) and (not selected_month or entry["month"] == selected_month)), None)
        if match:
            item = dict(match)
            _populate_sizes([item], SIGTAP_HOST)
            for entry in sigtap_files:
                if entry["name"] == item["name"]:
                    entry["size"] = item.get("size")
                    break
            _json_write(UPLOADS / ".cache" / "sigtap-catalog.json", {"version": 1, "fetched_at": time.time(), "files": sigtap_files})
            item["size_label"] = _size_label(item.get("size"))
            local_csv = SIGTAP_ROOT / f"{item['year']:04d}{item['month']:02d}" / "tb_procedimento.csv"
            local_zip = SIGTAP_ROOT / f"{item['year']:04d}{item['month']:02d}" / item["name"]
            item["csv_path"] = local_csv.relative_to(UPLOADS).as_posix()
            item["saved"] = local_csv.is_file() and local_csv.stat().st_size > 0 and local_zip.is_file()
            item["label"] = MODULES["SIGTAP"]["label"]
            item["description"] = MODULES["SIGTAP"]["description"]
            item["relationship"] = MODULES["SIGTAP"]["relationship"]
            sigtap_package = item
    for item in available:
        item["size_label"] = _size_label(item.get("size"))
        spec = MODULES[item["module"]]
        item["label"] = spec["label"]
        item["description"] = spec["description"]
        item["relationship"] = spec["relationship"]
    available.sort(key=lambda item: MODULES[item["module"]]["priority"])
    return {"ok": True, "uf": uf, "competencies": months, "year": selected_year or None, "month": selected_month or None, "files": available, "sigtapPackage": sigtap_package, "modules": MODULES, "source": "DATASUS / CNES e SIGTAP" , "sourceErrors": errors}


def _safe_package_dir(uf: str, year: int, month: int, module: str) -> Path:
    if uf not in VALID_UFS or module not in MODULES or year < 2005 or year > 2099 or month < 1 or month > 12:
        raise ValueError("Pacote CNES inválido.")
    target = PACKAGE_ROOT / uf / f"{year:04d}{month:02d}" / module
    target.mkdir(parents=True, exist_ok=True)
    return target


def _local_file_for(entry: dict[str, Any]) -> Path:
    name = str(entry["name"])
    uf = name[2:4].upper()
    if uf not in VALID_UFS:
        raise ValueError("O arquivo CNES não identifica uma UF válida.")
    return PACKAGE_ROOT / uf / f"{int(entry['year']):04d}{int(entry['month']):02d}" / str(entry["module"]) / (Path(name).stem + ".dbc")


def download_start(payload: dict[str, Any]) -> dict[str, Any]:
    uf = str(payload.get("uf", "PA")).upper()
    year = int(payload.get("year") or 0)
    month = int(payload.get("month") or 0)
    raw_modules = payload.get("modules")
    if not isinstance(raw_modules, list):
        raise ValueError("Escolha ao menos um pacote.")
    modules = list(dict.fromkeys(str(item).upper() for item in raw_modules))
    if not modules or len(modules) > len(MODULES) or any(item not in MODULES for item in modules):
        raise ValueError("A seleção de pacotes é inválida.")
    if uf not in VALID_UFS or year < 2005 or year > 2099 or month < 1 or month > 12:
        raise ValueError("Escolha uma unidade da Federação e uma competência válidas.")
    remote = _remote_catalog(uf) if any(module != "SIGTAP" for module in modules) else {}
    sigtap_remote = _remote_sigtap_catalog() if "SIGTAP" in modules else []
    chosen = []
    for module in modules:
        if module == "SIGTAP":
            item = next((entry for entry in sigtap_remote if entry["year"] == year and entry["month"] == month), None)
            if not item:
                raise ValueError(f"A competência SIGTAP {month:02d}/{year} não está publicada.")
            folder = SIGTAP_ROOT / f"{year:04d}{month:02d}"
            csv_path = folder / "tb_procedimento.csv"
            zip_path = folder / item["name"]
            if csv_path.is_file() and csv_path.stat().st_size > 0 and zip_path.is_file() and zip_path.stat().st_size > 0:
                continue
            chosen.append({"kind": "sigtap", "module": "SIGTAP", "name": item["name"], "remote": item["remote"], "size": item.get("size"), "year": year, "month": month, "zip_path": zip_path.relative_to(UPLOADS).as_posix(), "csv_path": csv_path.relative_to(UPLOADS).as_posix()})
            continue
        item = next((entry for entry in remote.get(module, []) if entry["year"] == year and entry["month"] == month), None)
        if not item:
            raise ValueError(f"O arquivo {MODULES[module]['label']} não está publicado para {month:02d}/{year}.")
        local = _local_file_for(item)
        dbf = local.with_suffix(".dbf")
        if local.is_file() and local.stat().st_size > 0 and dbf.is_file() and dbf.stat().st_size > 32:
            continue
        chosen.append({"kind": "cnes", "module": module, "name": item["name"], "remote": item["remote"], "size": item.get("size"), "year": year, "month": month, "dbc_path": local.relative_to(UPLOADS).as_posix(), "dbf_path": dbf.relative_to(UPLOADS).as_posix()})
    if not chosen:
        return {"ok": True, "done": True, "progress": 100, "message": "Os pacotes selecionados já estão baixados e convertidos.", "files": []}
    cnes_items = [item for item in chosen if item["kind"] == "cnes"]
    sigtap_items = [item for item in chosen if item["kind"] == "sigtap"]
    _populate_sizes(cnes_items, FTP_HOST)
    _populate_sizes(sigtap_items, SIGTAP_HOST)
    job_id = secrets.token_hex(16)
    total_bytes = sum(int(item.get("size") or 0) for item in chosen)
    state = {"id": job_id, "status": "queued", "progress": 1, "stage": "Preparando pacotes", "message": "A transferência foi colocada na fila.", "uf": uf, "year": year, "month": month, "items": chosen, "total_bytes": total_bytes, "bytes_downloaded": 0, "completed": []}
    _write_job(job_id, state)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", job_id]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200) if os.name == "nt" else 0
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt", cwd=str(ROOT))
    return {"ok": True, "done": False, "job_id": job_id, "status": "queued", "progress": 1, "stage": "Preparando pacotes"}


def _download_sigtap(item: dict[str, Any], ftp: ftplib.FTP, state: dict[str, Any], index: int, total_items: int, total_bytes: int, done_bytes: int, job_id: str) -> dict[str, Any]:
    expected_remote = f"{SIGTAP_DOWNLOADS}/{item['name']}"
    if item.get("remote") != expected_remote or not re.fullmatch(r"TabelaUnificada_20\d{4}_v\d+\.zip", item["name"], re.I):
        raise ValueError("O endereço do arquivo SIGTAP não corresponde à fonte oficial.")
    zip_path = (UPLOADS / item["zip_path"]).resolve()
    csv_path = (UPLOADS / item["csv_path"]).resolve()
    if not zip_path.is_relative_to(SIGTAP_ROOT.resolve()) or not csv_path.is_relative_to(SIGTAP_ROOT.resolve()):
        raise ValueError("O destino do pacote SIGTAP saiu da biblioteca local.")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    part = zip_path.with_name(zip_path.name + f".{job_id}.part")
    part.unlink(missing_ok=True)
    expected = int(item.get("size") or 0)
    current_size = 0
    last_write = 0.0
    state.update(stage="Baixando a tabela SIGTAP", module="SIGTAP", progress=max(3, int(5 + 55 * done_bytes / max(1, total_bytes))), bytes_written=0, message=f"Recebendo {item['name']} da fonte oficial.")
    _write_job(job_id, state)

    def receive(chunk: bytes) -> None:
        nonlocal current_size, last_write
        download_output.write(chunk)
        current_size += len(chunk)
        now = time.monotonic()
        if now - last_write >= 0.65 or (expected and current_size >= expected):
            last_write = now
            fraction = min(1, (done_bytes + current_size) / max(1, total_bytes))
            state.update(progress=min(62, int(5 + 55 * fraction)), bytes_written=current_size, stage="Baixando a tabela SIGTAP", file_progress=min(100, int(current_size / max(1, expected) * 100)))
            _write_job(job_id, state)

    try:
        with part.open("wb") as download_output:
            ftp.retrbinary(f"RETR {expected_remote}", receive, blocksize=256 * 1024)
    except (ftplib.all_errors, OSError, socket.timeout) as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Não foi possível receber o pacote SIGTAP: {exc}") from exc
    if current_size < 32 or (expected and current_size != expected):
        part.unlink(missing_ok=True)
        raise RuntimeError("O arquivo SIGTAP chegou incompleto.")
    os.replace(part, zip_path)
    state.update(stage="Preparando a tabela de procedimentos", progress=65, message="Validando o arquivo e organizando as colunas oficiais do SIGTAP.")
    _write_job(job_id, state)
    record_count, field_count = _build_sigtap_csv(zip_path, csv_path, state, index, total_items)
    return {"module": "SIGTAP", "name": item["name"], "zip_path": item["zip_path"], "path": item["csv_path"], "size": current_size, "records": record_count, "fields": field_count, "year": item["year"], "month": item["month"]}


def _build_sigtap_csv(zip_path: Path, csv_path: Path, state: dict[str, Any], index: int, total_items: int) -> tuple[int, int]:
    with zipfile.ZipFile(zip_path) as archive:
        entries = {PurePosixPath(name).name.lower(): name for name in archive.namelist() if not name.endswith("/")}
        data_name = entries.get("tb_procedimento.txt")
        layout_name = entries.get("tb_procedimento_layout.txt")
        if not data_name or not layout_name:
            raise ValueError("O pacote SIGTAP não contém a tabela de procedimentos e seu leiaute oficial.")
        layout_text = archive.read(layout_name).decode("latin1", "replace")
        layout_rows = list(csv.DictReader(io.StringIO(layout_text)))
        layout = []
        for row in layout_rows:
            try:
                name = row["Coluna"].strip().upper()
                start = int(row["Inicio"]) - 1
                end = int(row["Fim"])
            except (KeyError, TypeError, ValueError):
                continue
            if name and start >= 0 and end > start:
                layout.append({"name": name, "start": start, "end": end, "type": row.get("Tipo", "").upper()})
        if not layout or not any(item["name"] == "CO_PROCEDIMENTO" for item in layout):
            raise ValueError("O leiaute SIGTAP não possui o código do procedimento esperado.")
        source_info = archive.getinfo(data_name)
        estimated = max(1, source_info.file_size // max(1, max(item["end"] for item in layout)))
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        temp = csv_path.with_name(csv_path.name + ".part")
        record_count = 0
        try:
            with archive.open(data_name) as source, io.TextIOWrapper(source, encoding="latin1", errors="replace", newline="") as reader, temp.open("w", encoding="utf-8", newline="") as output:
                writer = csv.writer(output, delimiter=",", quoting=csv.QUOTE_MINIMAL)
                writer.writerow([item["name"] for item in layout])
                last_write = 0.0
                for line in reader:
                    line = line.rstrip("\r\n")
                    if not line:
                        continue
                    writer.writerow([line[item["start"]:item["end"]].strip() for item in layout])
                    record_count += 1
                    now = time.monotonic()
                    if record_count % 250 == 0 and now - last_write >= 0.35:
                        last_write = now
                        fraction = min(1, record_count / estimated)
                        state.update(progress=min(99, int(65 + 34 * (index + fraction) / total_items)), stage="Preparando a tabela de procedimentos", processed=record_count, total_records=estimated, message=f"Organizando os procedimentos da competência · {record_count:,}".replace(",", "."))
                        _write_job(str(state["id"]), state)
            os.replace(temp, csv_path)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        state.update(progress=min(99, int(65 + 34 * (index + 1) / total_items)), stage="Tabela SIGTAP pronta", message=f"{record_count:,} procedimentos e {len(layout)} campos preparados.".replace(",", "."))
        _write_job(str(state["id"]), state)
        return record_count, len(layout)


def run_worker(job_id: str) -> None:
    state = json.loads(_job_path(job_id).read_text(encoding="utf-8"))
    ftp = None
    ftp_host = None
    try:
        state.update(status="running", stage="Conectando ao DATASUS", progress=2, message="Consultando pacotes oficiais do CNES e do SIGTAP.")
        _write_job(job_id, state)
        items = state["items"]
        total = max(1, int(state.get("total_bytes") or 0))
        done_bytes = int(state.get("bytes_downloaded") or 0)

        def connect(host: str) -> ftplib.FTP:
            nonlocal ftp, ftp_host
            if ftp is not None and ftp_host == host:
                return ftp
            if ftp is not None:
                try:
                    ftp.quit()
                except ftplib.all_errors:
                    ftp.close()
            ftp = _ftp(host)
            ftp_host = host
            return ftp

        for index, item in enumerate(items):
            module = str(item["module"]).upper()
            item_kind = str(item.get("kind", "cnes"))
            if item_kind == "sigtap":
                completed = _download_sigtap(item, connect(SIGTAP_HOST), state, index, len(items), total, done_bytes, job_id)
                done_bytes += int(completed["size"])
                state["bytes_downloaded"] = done_bytes
                state.setdefault("completed", []).append(completed)
                _write_job(job_id, state)
                continue
            if module not in MODULES or _month_from_name(item["name"], module, state["uf"]) != (int(state["year"]), int(state["month"])):
                raise ValueError("A lista de pacotes mudou; atualize o catálogo e tente novamente.")
            remote_expected = f"{CNES_DATA}/{module}/{item['name']}"
            if item.get("remote") != remote_expected:
                raise ValueError("O caminho de origem do pacote não é oficial.")
            dbc_path = (UPLOADS / item["dbc_path"]).resolve()
            dbf_path = (UPLOADS / item["dbf_path"]).resolve()
            if not dbc_path.is_relative_to(PACKAGE_ROOT.resolve()) or not dbf_path.is_relative_to(PACKAGE_ROOT.resolve()):
                raise ValueError("O destino do pacote saiu da biblioteca CNES.")
            dbc_path.parent.mkdir(parents=True, exist_ok=True)
            part = dbc_path.with_name(dbc_path.name + f".{job_id}.part")
            state.update(stage=f"Baixando {MODULES[module]['label']}", module=module, progress=max(3, int(5 + 55 * done_bytes / total)), bytes_written=0, message=f"Acessando o serviço HTTPS oficial do DATASUS para receber {item['name']}.")
            _write_job(job_id, state)
            expected = int(item.get("size") or 0)
            last_write = 0.0
            current_size = 0

            def portal_progress(downloaded: int, response_size: int | None) -> None:
                nonlocal current_size, last_write
                current_size = downloaded
                now = time.monotonic()
                if now - last_write >= 0.65 or (response_size and downloaded >= response_size):
                    last_write = now
                    measured = response_size or expected
                    if measured:
                        estimate = min(expected, int(downloaded * expected / measured)) if expected and response_size else downloaded
                        fraction = min(1, (done_bytes + estimate) / total)
                        state.update(progress=min(62, int(5 + 55 * fraction)), file_progress=min(100, int(downloaded / measured * 100)))
                    state.update(stage=f"Baixando {MODULES[module]['label']} · HTTPS", bytes_written=downloaded, message="Transferindo pelo serviço oficial do DATASUS.")
                    _write_job(job_id, state)

            def receive(chunk: bytes) -> None:
                nonlocal current_size, last_write
                download_output.write(chunk)
                current_size += len(chunk)
                now = time.monotonic()
                if now - last_write >= 0.65 or (expected and current_size >= expected):
                    last_write = now
                    pct_file = current_size / max(1, expected)
                    state.update(progress=min(62, int(5 + 55 * min(1, (done_bytes + current_size) / total))), bytes_written=current_size, stage=f"Baixando {MODULES[module]['label']}")
                    state["file_progress"] = min(100, int(pct_file * 100))
                    _write_job(job_id, state)

            part.unlink(missing_ok=True)
            try:
                try:
                    portal_download_file(remote_expected, item["name"], part, portal_progress)
                except Exception as https_error:
                    part.unlink(missing_ok=True)
                    state.update(stage=f"Tentando outra rota · {MODULES[module]['label']}", progress=max(3, int(5 + 55 * done_bytes / total)), bytes_written=0, message="A rota HTTPS não concluiu a transferência; tentando o FTP público do DATASUS.")
                    _write_job(job_id, state)
                    try:
                        with part.open("wb") as download_output:
                            connect(FTP_HOST).retrbinary(f"RETR {remote_expected}", receive, blocksize=512 * 1024)
                    except (ftplib.all_errors, OSError, socket.timeout) as ftp_error:
                        part.unlink(missing_ok=True)
                        raise RuntimeError(f"A transferência HTTPS e o FTP público falharam. HTTPS: {https_error}; FTP: {ftp_error}") from ftp_error
                current_size = part.stat().st_size
            except OSError as exc:
                part.unlink(missing_ok=True)
                raise RuntimeError(f"Não foi possível gravar {item['name']} na biblioteca local: {exc}") from exc
            if current_size < 32 or (expected and current_size != expected):
                part.unlink(missing_ok=True)
                raise RuntimeError(f"O arquivo {item['name']} chegou incompleto.")
            os.replace(part, dbc_path)
            fields, records = tabulation.dbc_header(dbc_path)
            expected_dbf = 32 + 32 * len(fields) + 1 + records * (1 + sum(field["length"] for field in fields)) + 1
            state.update(stage=f"Preparando {MODULES[module]['label']}", progress=min(70, int(5 + 60 * (done_bytes + current_size) / total)), bytes_written=current_size, message="Convertendo o pacote para leitura e cruzamentos.")
            _write_job(job_id, state)

            def conversion_progress(percent: int, size: int) -> None:
                fraction = min(1, max(0, (percent - 3) / 93))
                base = (index / len(items)) + fraction / len(items)
                state.update(progress=min(99, int(65 + 34 * base)), stage=f"Convertendo {MODULES[module]['label']}", bytes_written=size, message="Preparando a base local para cruzamento.")
                _write_job(job_id, state)

            converted = tabulation.decompress(dbc_path, conversion_progress, expected_dbf, dbf_path.with_name(dbf_path.name + f".{job_id}.part"))
            os.replace(converted, dbf_path)
            done_bytes += current_size
            state["bytes_downloaded"] = done_bytes
            state.setdefault("completed", []).append({"module": module, "name": item["name"], "dbc_path": item["dbc_path"], "dbf_path": item["dbf_path"], "size": current_size, "records": records, "fields": len(fields)})
            state.update(stage=f"{MODULES[module]['label']} pronto", progress=min(99, int(65 + 34 * (index + 1) / len(items))), message=f"{records:,} registros preparados.".replace(",", "."))
            _write_job(job_id, state)
        labels = [MODULES.get(item.get("module"), {}).get("label", item.get("module", "pacote")) for item in state.get("completed", [])]
        summary = ", ".join(labels) if labels else "pacotes selecionados"
        state.update(status="done", progress=100, stage="Pacotes prontos", message=f"Pacotes prontos para cruzamento: {summary}.", files=state.get("completed", []))
        _write_job(job_id, state)
    except Exception as exc:
        state.update(status="error", stage="Não foi possível preparar os pacotes", message=str(exc))
        _write_job(job_id, state)
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except ftplib.all_errors:
                ftp.close()


def job_status(payload: dict[str, Any]) -> dict[str, Any]:
    path = _job_path(str(payload.get("job_id", "")))
    if not path.is_file():
        raise ValueError("Trabalho de pacotes não encontrado.")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("status") in {"queued", "running"} and time.time() - path.stat().st_mtime > 180:
        state.update(status="error", stage="Preparação interrompida", message="O serviço parou de atualizar o progresso. Confirme a conexão e tente novamente.")
        _write_job(str(payload.get("job_id")), state)
    return {"ok": True, **state}


def _package_table(relative: str) -> Path:
    value = PurePosixPath(str(relative).replace("\\", "/"))
    if value.is_absolute() or ".." in value.parts or len(value.parts) < 4 or value.parts[0] != "PACOTES":
        raise ValueError("Escolha uma tabela de um pacote oficial da biblioteca.")
    target = (UPLOADS / Path(*value.parts)).resolve()
    if value.parts[1] == "CNES" and value.suffix.lower() == ".dbf" and len(value.parts) == 6:
        uf, date, module = value.parts[2].upper(), value.parts[3], value.parts[4].upper()
        valid_date = re.fullmatch(r"20\d{4}", date)
        file_date = _month_from_name(target.stem + ".dbc", module, uf) if module in MODULES and module != "SIGTAP" and uf in VALID_UFS else None
        allowed = bool(valid_date and file_date == (int(date[:4]), int(date[4:])) and target.is_relative_to(PACKAGE_ROOT.resolve()))
    elif value.parts[1] == "SIGTAP" and value.suffix.lower() == ".csv" and value.name.lower() == "tb_procedimento.csv" and len(value.parts) == 4:
        valid_date = re.fullmatch(r"20\d{4}", value.parts[2])
        allowed = bool(valid_date and int(value.parts[2][4:]) in range(1, 13) and target.is_relative_to(SIGTAP_ROOT.resolve()))
    else:
        allowed = False
    if not allowed or not target.is_file():
        raise ValueError("A tabela escolhida não está na biblioteca local de pacotes.")
    return target


def _package_module(path: Path) -> str:
    return "SIGTAP" if path.suffix.lower() == ".csv" else path.parent.name.upper()


def _table_layout(path: Path) -> tuple[int, dict[str, dict[str, Any]]]:
    if path.suffix.lower() == ".dbf":
        count, _, _, fields = tabulation.dbf_layout(path)
        return count, fields
    if path.suffix.lower() != ".csv":
        raise ValueError("Formato de tabela do pacote não reconhecido.")
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        names = next(reader, [])
        if not names or "CO_PROCEDIMENTO" not in names:
            raise ValueError("A tabela SIGTAP não possui o cabeçalho de procedimento esperado.")
        count = max(0, sum(1 for _ in reader))
    numeric = {"QT_MAXIMA_EXECUCAO", "QT_DIAS_PERMANENCIA", "QT_PONTOS", "VL_IDADE_MINIMA", "VL_IDADE_MAXIMA", "VL_SH", "VL_SA", "VL_SP", "QT_TEMPO_PERMANENCIA"}
    fields = {name: {"offset": 0, "length": 0, "type": "N" if name in numeric else "C", "decimals": 0} for name in names}
    return count, fields


def _field_label(name: str, module: str) -> str:
    upper = name.upper()
    labels = {
        "CNES": "Código CNES", "CO_CNES": "Código CNES", "CNS_PROF": "CNS do profissional", "CO_CNS": "CNS", "NU_CNS": "CNS", "CO_PROFISSIONAL": "Código do profissional",
        "NOMEPROF": "Nome do profissional", "NO_PROFISSIONAL": "Nome do profissional", "CPF_PROF": "CPF do profissional", "NO_FANTASIA": "Nome fantasia", "NOME_FANT": "Nome fantasia", "NO_RAZAO_SOCIAL": "Razão social",
        "CO_CNPJ": "CNPJ", "CPF_CNPJ": "CNPJ do estabelecimento", "CNPJ_MAN": "CNPJ da mantenedora", "CBO": "Código CBO", "CBOUNICO": "Código CBO único", "CO_CBO": "CBO", "NO_CBO": "Ocupação (CBO)", "CODUFMUN": "Município · código IBGE", "CO_MUNICIPIO_GESTOR": "Município gestor",
        "CO_MUNICIPIO": "Município", "TP_UNIDADE": "Tipo de estabelecimento", "QT_EXIST": "Leitos existentes",
        "QT_SUS": "Leitos SUS", "QT_CONTR": "Leitos contratados", "TP_LEITO": "Tipo de leito", "DS_LEITO": "Descrição do leito",
        "CO_EQUIPAMENTO": "Código do equipamento", "TP_EQUIPAMENTO": "Tipo de equipamento", "QT_EQUIPAMENTO": "Quantidade de equipamentos",
        "CO_PROCEDIMENTO": "Código do procedimento", "NO_PROCEDIMENTO": "Descrição do procedimento", "TP_COMPLEXIDADE": "Complexidade",
        "TP_SEXO": "Sexo permitido", "QT_MAXIMA_EXECUCAO": "Quantidade máxima de execução", "QT_DIAS_PERMANENCIA": "Dias de permanência",
        "QT_PONTOS": "Pontos", "VL_IDADE_MINIMA": "Idade mínima", "VL_IDADE_MAXIMA": "Idade máxima", "VL_SH": "Valor hospitalar",
        "VL_SA": "Valor ambulatorial", "VL_SP": "Valor profissional", "CO_FINANCIAMENTO": "Código de financiamento",
        "CO_RUBRICA": "Código de rubrica", "QT_TEMPO_PERMANENCIA": "Tempo de permanência", "DT_COMPETENCIA": "Competência SIGTAP",
    }
    if upper in labels:
        return labels[upper]
    friendly = re.sub(r"^(CO|NO|NU|QT|TP|DS|DT|ST|IN)_", "", upper)
    friendly = friendly.replace("_", " ").strip().title()
    if upper.startswith("CO_") and "CNS" not in upper and "CBO" not in upper:
        friendly += " (código)"
    if module == "PF" and "PROF" in upper and "NOME" not in upper and "NO_" not in upper:
        friendly = "Profissional · " + friendly
    return friendly or upper


def local_packages(payload: dict[str, Any]) -> dict[str, Any]:
    uf = str(payload.get("uf", "")).upper()
    if uf and uf not in VALID_UFS:
        raise ValueError("Unidade da Federação inválida.")
    items = []
    if PACKAGE_ROOT.is_dir():
        for path in PACKAGE_ROOT.glob("*/*/*/*.dbf"):
            module = path.parent.name.upper()
            package_uf = path.parents[2].name.upper()
            if module not in MODULES or (uf and package_uf != uf):
                continue
            try:
                count, _, _, fields = tabulation.dbf_layout(path)
                relative = path.relative_to(UPLOADS).as_posix()
                date = path.parents[1].name
                items.append({"path": relative, "name": path.name, "module": module, "label": MODULES[module]["label"], "uf": package_uf, "year": int(date[:4]), "month": int(date[4:6]), "records": count, "fields_count": len(fields), "size": path.stat().st_size, "modified": int(path.stat().st_mtime)})
            except (OSError, ValueError, IndexError):
                continue
    if SIGTAP_ROOT.is_dir():
        for path in SIGTAP_ROOT.glob("*/tb_procedimento.csv"):
            try:
                count, fields = _table_layout(path)
                date = path.parent.name
                items.append({"path": path.relative_to(UPLOADS).as_posix(), "name": "tb_procedimento.csv", "module": "SIGTAP", "label": MODULES["SIGTAP"]["label"], "uf": "BR", "year": int(date[:4]), "month": int(date[4:6]), "records": count, "fields_count": len(fields), "size": path.stat().st_size, "modified": int(path.stat().st_mtime)})
            except (OSError, ValueError, IndexError):
                continue
    items.sort(key=lambda item: (item["year"], item["month"], MODULES[item["module"]]["priority"]), reverse=True)
    return {"ok": True, "packages": items}


def package_schema(payload: dict[str, Any]) -> dict[str, Any]:
    path = _package_table(str(payload.get("path", "")))
    count, fieldinfo = _table_layout(path)
    module = _package_module(path)
    date = path.parent.name if module == "SIGTAP" else path.parents[1].name
    fields = [{"name": name, "label": _field_label(name, module), "type": value["type"], "length": value["length"], "decimals": value["decimals"]} for name, value in fieldinfo.items()]
    return {"ok": True, "path": path.relative_to(UPLOADS).as_posix(), "name": path.name, "module": module, "module_label": MODULES[module]["label"], "uf": None if module == "SIGTAP" else path.parents[2].name, "year": int(date[:4]), "month": int(date[4:6]), "records": count, "fields": fields}


def delete_package(payload: dict[str, Any]) -> dict[str, Any]:
    package = _package_table(str(payload.get("path", "")))
    removed = 0
    targets = [package, package.with_suffix(".dbc")] if package.suffix.lower() == ".dbf" else [package, *package.parent.glob("*.zip")]
    for path in targets:
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    try:
        package.parent.rmdir()
    except OSError:
        pass
    return {"ok": True, "removed": removed, "name": package.name}


def _normalize_key(value: Any) -> str:
    return str(value or "").strip().upper()


def enrichment_start(payload: dict[str, Any]) -> dict[str, Any]:
    path = _package_table(str(payload.get("path", "")))
    join_field = str(payload.get("join_field", "")).upper()
    _, fields = _table_layout(path)
    if join_field not in fields:
        raise ValueError("Escolha um campo de relacionamento existente no pacote.")
    raw_keys = payload.get("keys")
    raw_fields = payload.get("fields")
    if not isinstance(raw_keys, list) or not isinstance(raw_fields, list) or len(raw_fields) > 8:
        raise ValueError("A configuração do cruzamento é inválida.")
    keys = list(dict.fromkeys(_normalize_key(value) for value in raw_keys if _normalize_key(value)))
    selected = list(dict.fromkeys(str(value).upper() for value in raw_fields))
    if not keys or len(keys) > 5000:
        raise ValueError("Escolha linhas com códigos e de uma a oito informações para adicionar.")
    module = _package_module(path)
    wants_professional_count = "__PROFESSIONAL_COUNT" in selected
    if wants_professional_count:
        has_professional_code = any(candidate in fields for candidate in ("CNS_PROF", "CO_CNS", "NU_CNS", "CPF_PROF", "CO_PROFISSIONAL", "CO_PROF"))
        if module != "PF" or join_field not in {"CNES", "CO_CNES"} or not has_professional_code:
            raise ValueError("A contagem de profissionais precisa do pacote PF relacionado pelo CNES do estabelecimento.")
        selected.remove("__PROFESSIONAL_COUNT")
    if any(field not in fields for field in selected):
        raise ValueError("Uma das informações não pertence ao pacote selecionado.")
    if join_field in selected:
        selected.remove(join_field)
    if not selected and not wants_professional_count:
        raise ValueError("Escolha pelo menos uma informação além do campo de relacionamento.")
    identity = {"path": path.relative_to(UPLOADS).as_posix(), "join_field": join_field, "fields": selected, "professional_count": wants_professional_count, "keys": keys}
    if len(json.dumps(identity, ensure_ascii=True)) > 100000:
        raise ValueError("A lista de chaves excede o limite do cruzamento.")
    job_id = secrets.token_hex(16)
    state = {"id": job_id, "status": "queued", "progress": 1, "stage": "Preparando cruzamento", "message": "A consulta foi colocada na fila.", "payload": identity}
    _write_job(job_id, state)
    command = [sys.executable, str(Path(__file__).resolve()), "--enrich-worker", job_id]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200) if os.name == "nt" else 0
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt", cwd=str(ROOT))
    return {"ok": True, "job_id": job_id, "status": "queued", "progress": 1, "stage": "Preparando cruzamento"}


def _aggregate_values(values: list[str], mode: str) -> str:
    values = [value for value in values if value != ""]
    if not values:
        return ""
    if mode == "sum":
        total = Decimal(0)
        for value in values:
            try:
                total += Decimal(value.replace(",", "."))
            except InvalidOperation:
                continue
        return format(total, "f")
    unique = list(dict.fromkeys(values))
    if mode == "count":
        return str(len(unique))
    if mode == "first":
        return unique[0]
    shown = unique[:4]
    extra = len(unique) - len(shown)
    return " · ".join(shown) + (f" · +{extra}" if extra else "")


def _is_quantity_field(name: str, module: str, info: dict[str, Any]) -> bool:
    upper = name.upper()
    quantity_name = upper.startswith(("QT_", "QTD_", "QUANT_")) or upper in {"QT_EXIST", "QT_SUS", "QT_CONTR"}
    return module in {"LT", "EQ"} and quantity_name and info.get("type") in {"N", "F", "I"}


def run_enrichment_worker(job_id: str) -> None:
    job = _job_path(job_id)
    state = json.loads(job.read_text(encoding="utf-8"))
    try:
        config = state["payload"]
        path = _package_table(config["path"])
        join_field = config["join_field"]
        output_fields = config["fields"]
        keys = set(config["keys"])
        count, fieldinfo = _table_layout(path)
        module = _package_module(path)
        professional_id = next((candidate for candidate in ("CNS_PROF", "CO_CNS", "NU_CNS", "CPF_PROF", "CO_PROFISSIONAL", "CO_PROF") if candidate in fieldinfo and candidate != join_field), None) if module == "PF" and join_field in {"CNES", "CO_CNES"} else None
        if config.get("professional_count") and not professional_id:
            raise ValueError("O pacote não possui um campo de CNS ou código profissional para contar vínculos.")
        names = list(dict.fromkeys([join_field, *output_fields, *([professional_id] if professional_id else [])]))
        positions = {name: index for index, name in enumerate(names)}
        sum_fields = {field for field in output_fields if _is_quantity_field(field, module, fieldinfo[field])}
        groups: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        sums: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
        professional_ids: dict[str, set[str]] = defaultdict(set)
        state.update(status="running", progress=2, stage="Lendo o pacote CNES", message="Localizando os códigos compatíveis com as linhas do resultado.")
        _write_job(job_id, state)
        last_update = 0.0

        def progress(done: int, total_records: int) -> None:
            nonlocal last_update
            now = time.monotonic()
            if now - last_update < 0.7 and done < total_records:
                return
            last_update = now
            state.update(progress=min(94, max(3, int(3 + 91 * done / max(1, total_records)))), stage="Lendo o pacote CNES", processed=done, total_records=total_records)
            _write_job(job_id, state)

        if path.suffix.lower() == ".dbf":
            rows = tabulation.iter_dbf_fields(path, names, processed_counter=[0], scan_callback=progress)
        else:
            def csv_rows():
                with path.open("r", encoding="utf-8", newline="") as stream:
                    reader = csv.DictReader(stream)
                    for row_index, row in enumerate(reader, start=1):
                        if row_index % 500 == 0 or row_index == count:
                            progress(row_index, count)
                        yield tuple(str(row.get(name, "") or "").strip() for name in names)
            rows = csv_rows()
        for record in rows:
            key = _normalize_key(record[0])
            if key not in keys:
                continue
            for field in output_fields:
                value = str(record[positions[field]] or "").strip()
                if value:
                    if field in sum_fields:
                        try:
                            sums[key][field] += Decimal(value.replace(",", "."))
                        except InvalidOperation:
                            pass
                    else:
                        bucket = groups[key][field]
                        if value not in bucket and len(bucket) < 5:
                            bucket.append(value)
            if professional_id:
                person = _normalize_key(record[positions[professional_id]])
                if person:
                    professional_ids[key].add(person)
        count_label = MODULES[module]["label"]
        output = {}
        for key in config["keys"]:
            record = groups.get(key, {})
            output[key] = {
                field: format(sums[key][field], "f") if field in sum_fields
                else _aggregate_values(record.get(field, []), "first" if module in {"ST", "DC"} else "distinct")
                for field in output_fields
            }
            if config.get("professional_count"):
                output[key]["__PROFESSIONAL_COUNT"] = str(len(professional_ids.get(key, set())))
        if config.get("professional_count"):
            output_fields = [*output_fields, "__PROFESSIONAL_COUNT"]
        state.update(status="done", progress=100, stage="Cruzamento concluído", message=f"{len(output)} linhas verificadas no pacote de {count_label}.", result={"fields": output_fields, "by_key": output, "matched": sum(1 for row in output.values() if any(row.values())), "rows": len(output), "professional_count": bool(config.get("professional_count"))})
        state.pop("payload", None)
        _write_job(job_id, state)
    except Exception as exc:
        state.pop("payload", None)
        state.update(status="error", stage="Falha no cruzamento", message=str(exc))
        _write_job(job_id, state)


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action")
    if action == "package_catalog":
        return catalog(payload)
    if action == "package_download_start":
        return download_start(payload)
    if action in {"package_status", "package_enrich_status"}:
        return job_status(payload)
    if action == "package_list":
        return local_packages(payload)
    if action == "package_schema":
        return package_schema(payload)
    if action == "package_delete":
        return delete_package(payload)
    if action == "package_enrich_start":
        return enrichment_start(payload)
    raise ValueError("Ação de pacotes inválida.")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        run_worker(sys.argv[2]); raise SystemExit(0)
    if len(sys.argv) > 2 and sys.argv[1] == "--enrich-worker":
        run_enrichment_worker(sys.argv[2]); raise SystemExit(0)
    try:
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8")
        request = json.load(sys.stdin)
        response = handle(request)
        sys.stdout.write(json.dumps(response, ensure_ascii=True, default=str))
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
        raise SystemExit(2)
