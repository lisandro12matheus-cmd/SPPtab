"""Local, competence-specific explorer for the official SIGTAP fixed-width exports.

The public DATASUS FTP publishes one ZIP per competence. The application checks
its directory while open, imports selected versions once, and queries SQLite.
No third-party mirror or undocumented web service is used.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from ftplib import FTP
from pathlib import Path
from typing import Any

from storage_lock import interprocess_lock


DATA_ROOT = Path(os.environ.get("TABWIN2_DATA_DIR", Path(__file__).resolve().parents[1] / "uploads")).expanduser().resolve()
STORE = DATA_ROOT / ".cache" / "sigtap"
FTP_HOST = "ftp2.datasus.gov.br"
FTP_DIRECTORY = "/pub/sistemas/tup/downloads"
FILE_PATTERN = re.compile(r"\ATabelaUnificada_(20\d{4})_v(\d{10,14})\.zip\Z", re.I)
COMP_PATTERN = re.compile(r"\A20\d{4}\Z")
CATALOG_TTL = 6 * 3600
MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_UNPACKED_BYTES = 128 * 1024 * 1024

DOMAIN_FILES = {
    "group": ("tb_grupo", ("CO_GRUPO",), "NO_GRUPO"),
    "subgroup": ("tb_sub_grupo", ("CO_GRUPO", "CO_SUB_GRUPO"), "NO_SUB_GRUPO"),
    "form": ("tb_forma_organizacao", ("CO_GRUPO", "CO_SUB_GRUPO", "CO_FORMA_ORGANIZACAO"), "NO_FORMA_ORGANIZACAO"),
    "financing": ("tb_financiamento", ("CO_FINANCIAMENTO",), "NO_FINANCIAMENTO"),
    "modality": ("tb_modalidade", ("CO_MODALIDADE",), "NO_MODALIDADE"),
    "registration": ("tb_registro", ("CO_REGISTRO",), "NO_REGISTRO"),
    "cbo": ("tb_ocupacao", ("CO_OCUPACAO",), "NO_OCUPACAO"),
    "cid": ("tb_cid", ("CO_CID",), "NO_CID"),
    "service": ("tb_servico", ("CO_SERVICO",), "NO_SERVICO"),
    "service_class": ("tb_servico_classificacao", ("CO_SERVICO", "CO_CLASSIFICACAO"), "NO_CLASSIFICACAO"),
    "habilitation": ("tb_habilitacao", ("CO_HABILITACAO",), "NO_HABILITACAO"),
    "detail": ("tb_detalhe", ("CO_DETALHE",), "NO_DETALHE"),
    "bed": ("tb_tipo_leito", ("CO_TIPO_LEITO",), "NO_TIPO_LEITO"),
    "rule": ("tb_regra_condicionada", ("CO_REGRA_CONDICIONADA",), "NO_REGRA_CONDICIONADA"),
    "rubric": ("tb_rubrica", ("CO_RUBRICA",), "NO_RUBRICA"),
}
RELATION_FILES = {
    "modality": ("rl_procedimento_modalidade", ("CO_MODALIDADE",)),
    "registration": ("rl_procedimento_registro", ("CO_REGISTRO",)),
    "cbo": ("rl_procedimento_ocupacao", ("CO_OCUPACAO",)),
    "cid": ("rl_procedimento_cid", ("CO_CID",)),
    "service_class": ("rl_procedimento_servico", ("CO_SERVICO", "CO_CLASSIFICACAO")),
    "habilitation": ("rl_procedimento_habilitacao", ("CO_HABILITACAO",)),
    "detail": ("rl_procedimento_detalhe", ("CO_DETALHE",)),
    "bed": ("rl_procedimento_leito", ("CO_TIPO_LEITO",)),
    "rule": ("rl_procedimento_regra_cond", ("CO_REGRA_CONDICIONADA",)),
    "compatible": ("rl_procedimento_compativel", ("CO_PROCEDIMENTO_COMPATIVEL",)),
    "increment": ("rl_procedimento_incremento", ("CO_HABILITACAO",)),
}
FILTER_FIELDS = {
    "group": "p.group_code", "subgroup": "p.subgroup_code", "form": "p.form_code",
    "complexity": "p.complexity", "financing": "p.financing", "sex": "p.sex",
}
RELATION_FILTERS = {"modality", "registration", "cbo", "cid", "service_class", "habilitation", "bed", "detail", "rule"}
COLUMN_FIELDS = {"code": "p.code", "name": "p.name", "group": "p.group_code", "complexity": "p.complexity",
                 "financing": "p.financing", "sa": "p.sa_cents", "sh": "p.sh_cents", "sp": "p.sp_cents"}
COMPLEXITY_LABELS = {"0": "Não se aplica", "1": "Atenção básica", "2": "Média complexidade", "3": "Alta complexidade"}
SEX_LABELS = {"M": "Masculino", "F": "Feminino", "I": "Indiferente", "N": "Não se aplica"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalized(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(char))


def _catalog_path() -> Path:
    return STORE / "catalog.json"


def _read_catalog() -> dict[str, Any]:
    try:
        data = json.loads(_catalog_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else {}
    except (OSError, ValueError):
        return {}


def _write_catalog(data: dict[str, Any]) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix="catalog-", suffix=".json", dir=STORE)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(name, _catalog_path())
    finally:
        Path(name).unlink(missing_ok=True)


def discover(force: bool = False) -> dict[str, Any]:
    STORE.mkdir(parents=True, exist_ok=True)
    with interprocess_lock(STORE / "catalog.lock"):
        cached = _read_catalog()
        if not force and cached and time.time() - float(cached.get("checkedEpoch", 0)) < CATALOG_TTL:
            return {**cached, "online": True}
        try:
            ftp = FTP()
            ftp.connect(FTP_HOST, 21, timeout=12)
            try:
                ftp.login()
                names = ftp.nlst(FTP_DIRECTORY)
            finally:
                try: ftp.quit()
                except OSError: ftp.close()
            files: dict[str, str] = {}
            for path in names:
                name = Path(path).name
                match = FILE_PATTERN.fullmatch(name)
                if not match:
                    continue
                competence = match.group(1)
                if not 1 <= int(competence[4:]) <= 12:
                    continue
                if name > files.get(competence, ""):
                    files[competence] = name
            if not files:
                raise RuntimeError("A listagem oficial do SIGTAP não trouxe competências válidas.")
            catalog = {"files": files, "checkedAt": _now(), "checkedEpoch": time.time(), "source": f"ftp://{FTP_HOST}{FTP_DIRECTORY}/"}
            _write_catalog(catalog)
            return {**catalog, "online": True}
        except (OSError, TimeoutError, ValueError, RuntimeError) as exc:
            if cached:
                return {**cached, "online": False, "warning": f"Fonte oficial indisponível: {exc}"}
            raise RuntimeError(f"Não foi possível consultar o FTP oficial do SIGTAP: {exc}") from exc


def _valid_competence(value: Any) -> str:
    competence = str(value or "")
    if not COMP_PATTERN.fullmatch(competence) or not 1 <= int(competence[4:]) <= 12:
        raise ValueError("Competência SIGTAP inválida.")
    return competence


def _db_path(competence: str) -> Path:
    return STORE / f"{competence}.sqlite3"


def _connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _metadata(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        with _connection(path) as connection:
            return {row[0]: row[1] for row in connection.execute("SELECT key,value FROM metadata")}
    except sqlite3.Error:
        return {}


def catalog() -> dict[str, Any]:
    cached = {path.stem: _metadata(path) for path in STORE.glob("20????.sqlite3")}
    try:
        listing = discover()
    except RuntimeError as exc:
        valid = {key: meta["filename"] for key, meta in cached.items() if meta.get("complete") == "1"}
        if not valid: raise
        listing = {"files": valid, "source": f"ftp://{FTP_HOST}{FTP_DIRECTORY}/", "checkedAt": _now(),
                   "online": False, "warning": f"Fonte oficial indisponível: {exc}. Exibindo o histórico local válido."}
    competencies = sorted(set(listing["files"]) | {key for key, meta in cached.items() if meta.get("complete") == "1"}, reverse=True)
    return {"ok": True, "source": listing["source"], "checkedAt": listing["checkedAt"], "online": listing["online"],
            "warning": listing.get("warning", ""), "competencies": [
                {"competence": key, "cached": cached.get(key, {}).get("complete") == "1",
                 "version": listing["files"].get(key, cached.get(key, {}).get("filename", "")),
                 "loadedAt": cached.get(key, {}).get("loadedAt", ""),
                 "current": listing["files"].get(key, "") == cached.get(key, {}).get("filename", "")}
                for key in competencies]}


def _layout(archive: zipfile.ZipFile, base: str) -> list[tuple[str, int, int]]:
    name = f"{base}_layout.txt"
    if name not in archive.namelist():
        raise ValueError(f"O pacote SIGTAP não contém o layout de {base}.")
    reader = csv.DictReader(io.StringIO(archive.read(name).decode("cp1252")))
    fields = [(str(row["Coluna"]).strip(), int(row["Inicio"]) - 1, int(row["Fim"])) for row in reader]
    if not fields or any(not key or start < 0 or end <= start or end > 10000 for key, start, end in fields):
        raise ValueError(f"O layout de {base} é inválido.")
    return fields


def _rows(archive: zipfile.ZipFile, base: str, competence: str):
    name = f"{base}.txt"
    if name not in archive.namelist():
        raise ValueError(f"O pacote SIGTAP não contém {name}.")
    layout = _layout(archive, base)
    width = max(end for _, _, end in layout)
    with archive.open(name) as stream:
        for raw in stream:
            raw = raw.rstrip(b"\r\n")
            if not raw:
                continue
            if len(raw) < width:
                raise ValueError(f"O arquivo {name} contém uma linha menor que o layout oficial.")
            row = {key: raw[start:end].decode("cp1252").strip() for key, start, end in layout}
            if row.get("DT_COMPETENCIA") and row["DT_COMPETENCIA"] != competence:
                raise ValueError(f"O arquivo {name} contém outra competência.")
            yield row


def _download(filename: str, destination: Path) -> str:
    if not FILE_PATTERN.fullmatch(filename):
        raise ValueError("Nome de arquivo SIGTAP inválido.")
    digest = hashlib.sha256()
    ftp = FTP()
    ftp.connect(FTP_HOST, 21, timeout=30)
    try:
        ftp.login()
        with destination.open("wb") as stream:
            def write(chunk: bytes) -> None:
                if stream.tell() + len(chunk) > MAX_ZIP_BYTES:
                    raise ValueError("O pacote SIGTAP excede o limite permitido.")
                digest.update(chunk)
                stream.write(chunk)
            ftp.retrbinary(f"RETR {FTP_DIRECTORY}/{filename}", write, blocksize=1024 * 1024)
    finally:
        try: ftp.quit()
        except OSError: ftp.close()
    if destination.stat().st_size < 100_000:
        raise ValueError("O pacote SIGTAP chegou incompleto.")
    return digest.hexdigest()


def _validate_archive(archive: zipfile.ZipFile, competence: str) -> None:
    entries = archive.infolist()
    if len(entries) > 120 or sum(item.file_size for item in entries) > MAX_UNPACKED_BYTES:
        raise ValueError("O pacote SIGTAP excede os limites de segurança.")
    if len({item.filename for item in entries}) != len(entries):
        raise ValueError("O pacote SIGTAP contém nomes de arquivo repetidos.")
    for item in entries:
        if item.is_dir() or "/" in item.filename or "\\" in item.filename or item.file_size > 32 * 1024 * 1024:
            raise ValueError("O pacote SIGTAP contém um item inesperado.")
    core = {"tb_procedimento", "tb_descricao", "tb_grupo", "tb_sub_grupo", "tb_forma_organizacao", "tb_financiamento",
            "rl_procedimento_modalidade", "rl_procedimento_registro", "rl_procedimento_ocupacao", "rl_procedimento_cid",
            "rl_procedimento_servico", "rl_procedimento_habilitacao"}
    required = {f"{base}{suffix}" for base in core for suffix in (".txt", "_layout.txt")}
    if not required.issubset(archive.namelist()) or archive.testzip() is not None:
        raise ValueError("O pacote SIGTAP está incompleto ou corrompido.")
    if not any(True for _ in _rows(archive, "tb_procedimento", competence)):
        raise ValueError("O pacote SIGTAP não contém procedimentos.")


def _number(raw: str) -> int | None:
    return int(raw) if raw and raw.isdigit() else None


def _import_archive(archive: zipfile.ZipFile, path: Path, competence: str, filename: str, digest: str) -> None:
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.executescript("""
            PRAGMA journal_mode=DELETE;
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE procedures(code TEXT PRIMARY KEY,name TEXT NOT NULL,name_search TEXT NOT NULL,description TEXT,
              group_code TEXT NOT NULL,subgroup_code TEXT NOT NULL,form_code TEXT NOT NULL,complexity TEXT,sex TEXT,
              financing TEXT,sh_cents INTEGER,sa_cents INTEGER,sp_cents INTEGER,age_min TEXT,age_max TEXT,raw_json TEXT NOT NULL);
            CREATE TABLE domains(kind TEXT NOT NULL,code TEXT NOT NULL,label TEXT NOT NULL,description TEXT,PRIMARY KEY(kind,code));
            CREATE TABLE relations(kind TEXT NOT NULL,procedure_code TEXT NOT NULL,target_code TEXT NOT NULL,attributes_json TEXT NOT NULL,
              PRIMARY KEY(kind,procedure_code,target_code,attributes_json));
            CREATE INDEX idx_procedures_name ON procedures(name_search);
            CREATE INDEX idx_procedures_group ON procedures(group_code,subgroup_code,form_code);
            CREATE INDEX idx_procedures_finance ON procedures(financing);
            CREATE INDEX idx_relations_filter ON relations(kind,target_code,procedure_code);
            CREATE INDEX idx_relations_procedure ON relations(procedure_code,kind);
        """)
        descriptions = {row["CO_PROCEDIMENTO"]: row.get("DS_PROCEDIMENTO", "") for row in _rows(archive, "tb_descricao", competence)}
        procedures = []
        for row in _rows(archive, "tb_procedimento", competence):
            code = row["CO_PROCEDIMENTO"]
            if not re.fullmatch(r"\d{10}", code):
                raise ValueError("O pacote SIGTAP contém um código de procedimento inválido.")
            procedures.append((code, row["NO_PROCEDIMENTO"], _normalized(row["NO_PROCEDIMENTO"]), descriptions.get(code),
                code[:2], code[:4], code[:6], row.get("TP_COMPLEXIDADE"), row.get("TP_SEXO"), row.get("CO_FINANCIAMENTO"),
                _number(row.get("VL_SH", "")), _number(row.get("VL_SA", "")), _number(row.get("VL_SP", "")),
                row.get("VL_IDADE_MINIMA"), row.get("VL_IDADE_MAXIMA"), json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        if len(procedures) < 1000:
            raise ValueError("O pacote SIGTAP contém poucos procedimentos para uma tabela completa.")
        connection.executemany("INSERT INTO procedures VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", procedures)
        for kind, (base, keys, name_field) in DOMAIN_FILES.items():
            if f"{base}.txt" not in archive.namelist():
                continue
            domain_rows = []
            for row in _rows(archive, base, competence):
                code = "".join(row.get(key, "") for key in keys)
                if code:
                    domain_rows.append((kind, code, row.get(name_field, ""), row.get("DS_REGRA_CONDICIONADA") or row.get("DS_GRUPO_HABILITACAO")))
            connection.executemany("INSERT OR REPLACE INTO domains VALUES(?,?,?,?)", domain_rows)
        for kind, (base, keys) in RELATION_FILES.items():
            if f"{base}.txt" not in archive.namelist():
                continue
            relation_rows = []
            for row in _rows(archive, base, competence):
                code = row.get("CO_PROCEDIMENTO") or row.get("CO_PROCEDIMENTO_PRINCIPAL") or ""
                target = "".join(row.get(key, "") for key in keys)
                if code and target:
                    relation_rows.append((kind, code, target, json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
                if len(relation_rows) >= 5000:
                    connection.executemany("INSERT OR IGNORE INTO relations VALUES(?,?,?,?)", relation_rows)
                    relation_rows.clear()
            if relation_rows:
                connection.executemany("INSERT OR IGNORE INTO relations VALUES(?,?,?,?)", relation_rows)
        count = connection.execute("SELECT COUNT(*) FROM procedures").fetchone()[0]
        linked = connection.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        if count < 1000 or linked < 1000:
            raise ValueError("As tabelas de procedimentos ou relacionamentos estão incompletas.")
        metadata = {"complete": "1", "competence": competence, "filename": filename, "sha256": digest,
                    "loadedAt": _now(), "source": f"ftp://{FTP_HOST}{FTP_DIRECTORY}/{filename}",
                    "procedureCount": str(count), "relationCount": str(linked)}
        connection.executemany("INSERT INTO metadata VALUES(?,?)", metadata.items())
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("O banco SIGTAP importado não passou na verificação de integridade.")
    finally:
        connection.close()


def ensure_dataset(value: Any) -> tuple[Path, dict[str, str], str]:
    competence = _valid_competence(value)
    path = _db_path(competence)
    current = _metadata(path)
    try:
        listing = discover()
    except RuntimeError as exc:
        if current.get("complete") == "1":
            return path, current, f"Fonte oficial indisponível: {exc}. Exibindo a última tabela válida local."
        raise
    filename = listing["files"].get(competence)
    if current.get("complete") == "1" and (not filename or current.get("filename") == filename):
        return path, current, listing.get("warning", "")
    if not filename:
        raise ValueError("Esta competência não está no catálogo oficial nem no histórico válido deste computador.")
    with interprocess_lock(STORE / f"{competence}.lock"):
        current = _metadata(path)
        if current.get("complete") == "1" and current.get("filename") == filename:
            return path, current, listing.get("warning", "")
        archive_handle, archive_name = tempfile.mkstemp(prefix=f"{competence}-", suffix=".zip", dir=STORE)
        os.close(archive_handle)
        db_handle, db_name = tempfile.mkstemp(prefix=f"{competence}-", suffix=".sqlite3", dir=STORE)
        os.close(db_handle)
        try:
            archive_path, new_db = Path(archive_name), Path(db_name)
            digest = _download(filename, archive_path)
            with zipfile.ZipFile(archive_path) as archive:
                _validate_archive(archive, competence)
                _import_archive(archive, new_db, competence, filename, digest)
            os.replace(new_db, path)
            return path, _metadata(path), listing.get("warning", "")
        except (OSError, ValueError, RuntimeError, sqlite3.Error, zipfile.BadZipFile) as exc:
            if current.get("complete") == "1":
                return path, current, f"Nova publicação {filename} não validada: {exc}. Exibindo a última versão íntegra local."
            raise RuntimeError(f"Não foi possível preparar a competência {competence}: {exc}") from exc
        finally:
            Path(archive_name).unlink(missing_ok=True)
            Path(db_name).unlink(missing_ok=True)


def prepare_zip(payload: dict[str, Any]) -> dict[str, Any]:
    competence = _valid_competence(payload.get("competence"))
    listing = discover()
    filename = listing["files"].get(competence)
    if not filename or not FILE_PATTERN.fullmatch(filename):
        raise ValueError("O ZIP desta competência não está no catálogo oficial disponível.")
    destination = STORE / filename
    with interprocess_lock(STORE / f"{competence}-zip.lock"):
        valid = False
        if destination.is_file():
            try:
                with zipfile.ZipFile(destination) as archive:
                    _validate_archive(archive, competence)
                valid = True
            except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
                destination.unlink(missing_ok=True)
        if not valid:
            handle, temporary_name = tempfile.mkstemp(prefix=f"{competence}-download-", suffix=".zip", dir=STORE)
            os.close(handle)
            temporary = Path(temporary_name)
            try:
                _download(filename, temporary)
                with zipfile.ZipFile(temporary) as archive:
                    _validate_archive(archive, competence)
                os.replace(temporary, destination)
            except Exception as exc:
                raise RuntimeError(f"Não foi possível obter o ZIP oficial da competência {competence}: {exc}") from exc
            finally:
                temporary.unlink(missing_ok=True)
    return {"ok": True, "filename": filename, "url": f"sigtap-zip.php?arquivo={filename}"}


def _domain_map(connection: sqlite3.Connection) -> dict[str, dict[str, dict[str, str]]]:
    domains: dict[str, dict[str, dict[str, str]]] = {}
    for row in connection.execute("SELECT kind,code,label,description FROM domains"):
        domains.setdefault(row["kind"], {})[row["code"]] = {"code": row["code"], "label": row["label"], "description": row["description"] or ""}
    return domains


def _label(domains: dict, kind: str, code: str | None) -> dict[str, str] | None:
    if code is None or code == "":
        return None
    return domains.get(kind, {}).get(code) or {"code": code, "label": "Descrição não publicada nesta competência", "description": ""}


def _procedure(row: sqlite3.Row, domains: dict, compact: bool = False) -> dict[str, Any]:
    result = {"code": row["code"], "name": row["name"], "group": _label(domains, "group", row["group_code"]),
              "subgroup": _label(domains, "subgroup", row["subgroup_code"]),
              "form": _label(domains, "form", row["form_code"]),
              "complexity": {"code": row["complexity"], "label": COMPLEXITY_LABELS.get(row["complexity"], "Não informado na tabela")},
              "financing": _label(domains, "financing", row["financing"]),
              "values": {"sh": row["sh_cents"], "sa": row["sa_cents"], "sp": row["sp_cents"]}}
    if not compact:
        raw = json.loads(row["raw_json"])
        result.update({"description": row["description"] or None,
                       "sex": {"code": row["sex"] or "", "label": SEX_LABELS.get(row["sex"], row["sex"] or "Não informado")},
                       "ageMin": row["age_min"], "ageMax": row["age_max"],
                       "attributes": raw, "rubric": _label(domains, "rubric", raw.get("CO_RUBRICA"))})
    return result


def _parse_filters(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("filters") or {}
    if not isinstance(raw, dict) or len(raw) > 20:
        raise ValueError("Filtros SIGTAP inválidos.")
    filters: dict[str, Any] = {}
    for key, value in raw.items():
        if key in FILTER_FIELDS or key in RELATION_FILTERS:
            if not isinstance(value, str) or len(value) > 20 or not re.fullmatch(r"[\w.]+", value, re.ASCII):
                raise ValueError(f"Filtro {key} inválido.")
            if value:
                filters[key] = value
        elif key in {"minValue", "maxValue"}:
            if not isinstance(value, int) or value < 0 or value > 10**12:
                raise ValueError("O valor informado para o filtro não é válido.")
            filters[key] = value
        elif key == "ageYears":
            if not isinstance(value, int) or value < 0 or value > 130:
                raise ValueError("Idade fora do intervalo disponível.")
            filters[key] = value
        elif key == "valueComponent":
            if value not in {"sh", "sa", "sp"}:
                raise ValueError("Componente de valor inválido.")
            filters[key] = value
        elif key == "query":
            if not isinstance(value, str) or len(value) > 120:
                raise ValueError("A pesquisa é longa demais.")
            filters[key] = value.strip()
        else:
            raise ValueError(f"Filtro SIGTAP não reconhecido: {key}.")
    return filters


def _where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    terms = []
    values: list[Any] = []
    for key, field in FILTER_FIELDS.items():
        if key in filters:
            terms.append(f"{field}=?")
            values.append(filters[key])
    for key in RELATION_FILTERS:
        if key in filters:
            terms.append("EXISTS(SELECT 1 FROM relations r WHERE r.procedure_code=p.code AND r.kind=? AND r.target_code=?)")
            values.extend((key, filters[key]))
    query = filters.get("query", "")
    if query:
        query_code = re.sub(r"\D", "", query) if re.fullmatch(r"[\d.\s-]+", query) else ""
        escaped = _normalized(query).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        terms.append("(p.name_search LIKE ? ESCAPE '\\' OR p.code LIKE ?)")
        values.extend((f"%{escaped}%", f"%{query_code}%" if query_code else ""))
    component = filters.get("valueComponent", "sa")
    field = {"sh": "p.sh_cents", "sa": "p.sa_cents", "sp": "p.sp_cents"}[component]
    if "minValue" in filters:
        terms.append(f"{field}>=?")
        values.append(filters["minValue"])
    if "maxValue" in filters:
        terms.append(f"{field}<=?")
        values.append(filters["maxValue"])
    if "ageYears" in filters:
        terms.append("((CAST(p.age_min AS INTEGER)<=? AND CAST(p.age_max AS INTEGER)>=?) OR (p.age_min='9999' AND p.age_max='9999'))")
        values.extend((filters["ageYears"] * 12, filters["ageYears"] * 12))
    return (" WHERE " + " AND ".join(terms) if terms else ""), values


def _column_where(payload: dict[str, Any], omitted: str = "") -> tuple[list[str], list[Any]]:
    raw = payload.get("columnFilters") or {}
    if not isinstance(raw, dict) or len(raw) > len(COLUMN_FIELDS):
        raise ValueError("Filtros das colunas inválidos.")
    clauses: list[str] = []
    params: list[Any] = []
    for key, spec in raw.items():
        if key not in COLUMN_FIELDS or not isinstance(spec, dict) or set(spec) != {"mode", "values"}:
            raise ValueError("Filtro de coluna inválido.")
        mode, values = spec["mode"], spec["values"]
        if mode not in {"include", "exclude"} or not isinstance(values, list) or len(values) > 6000:
            raise ValueError("Seleção da coluna inválida.")
        if any(not isinstance(value, str) or len(value) > 160 for value in values):
            raise ValueError("Valor da coluna inválido.")
        if key == omitted:
            continue
        if not values:
            if mode == "include": clauses.append("0=1")
            continue
        field = COLUMN_FIELDS[key]
        sql_values: list[Any] = []
        null_selected = False
        for value in values:
            if value == "":
                null_selected = True
                continue
            if key in {"sa", "sh", "sp"}:
                if not re.fullmatch(r"-?\d{1,15}", value):
                    raise ValueError("Valor monetário da coluna inválido.")
                sql_values.append(int(value))
            else:
                sql_values.append(value)
        parts = [f"{field} {'IN' if mode == 'include' else 'NOT IN'} (SELECT value FROM json_each(?))"] if sql_values else []
        if mode == "include":
            if null_selected: parts.append(f"{field} IS NULL")
            clauses.append("(" + " OR ".join(parts) + ")")
        else:
            if null_selected: parts.append(f"{field} IS NOT NULL")
            elif sql_values: parts.append(f"{field} IS NULL")
            clauses.append("(" + (" AND " if null_selected else " OR ").join(parts) + ")")
        if sql_values: params.append(json.dumps(sql_values, ensure_ascii=False))
    return clauses, params


def _combined_where(payload: dict[str, Any], omitted: str = "") -> tuple[str, list[Any]]:
    where, params = _where(_parse_filters(payload))
    clauses, extra = _column_where(payload, omitted)
    if clauses:
        where += (" AND " if where else " WHERE ") + " AND ".join(clauses)
    return where, [*params, *extra]


def _source_status(meta: dict[str, str], warning: str) -> dict[str, str]:
    return {"competence": meta["competence"], "loadedAt": meta["loadedAt"], "filename": meta["filename"],
            "sha256": meta["sha256"], "source": meta["source"], "warning": warning}


def search(payload: dict[str, Any]) -> dict[str, Any]:
    path, meta, warning = ensure_dataset(payload.get("competence"))
    filters = _parse_filters(payload)
    where, params = _combined_where(payload)
    export_all = payload.get("exportAll") is True
    page = 1 if export_all else max(1, min(int(payload.get("page") or 1), 100000))
    page_size = max(10, min(int(payload.get("pageSize") or 50), 100))
    sort = str(payload.get("sort") or "code")
    ordering = {"code": "p.code", "name": "p.name_search",
                "group": "COALESCE((SELECT label FROM domains WHERE kind='group' AND code=p.group_code),p.group_code) COLLATE NOCASE",
                "complexity": "CASE p.complexity WHEN '0' THEN 'Não se aplica' WHEN '1' THEN 'Atenção básica' WHEN '2' THEN 'Média complexidade' WHEN '3' THEN 'Alta complexidade' ELSE p.complexity END COLLATE NOCASE",
                "financing": "COALESCE((SELECT label FROM domains WHERE kind='financing' AND code=p.financing),p.financing) COLLATE NOCASE", "value_sa": "p.sa_cents",
                "value_sh": "p.sh_cents", "value_sp": "p.sp_cents"}.get(sort)
    if ordering is None:
        raise ValueError("Ordenação inválida.")
    direction = "DESC" if payload.get("direction") == "desc" else "ASC"
    with _connection(path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM procedures p" + where, params).fetchone()[0]
        if export_all:
            if count > 10000:
                raise ValueError("O recorte excede o limite de 10.000 linhas para CSV.")
            page_size = max(1, count)
        rows = connection.execute(f"SELECT p.* FROM procedures p{where} ORDER BY {ordering} {direction},p.code {direction} LIMIT ? OFFSET ?",
                                  [*params, page_size, (page - 1) * page_size]).fetchall()
        domains = _domain_map(connection)
    return {"ok": True, "source": _source_status(meta, warning), "count": count, "page": page,
            "pageSize": page_size, "rows": [_procedure(row, domains, True) for row in rows], "filters": filters}


def column_values(payload: dict[str, Any]) -> dict[str, Any]:
    path, meta, warning = ensure_dataset(payload.get("competence"))
    column = str(payload.get("column") or "")
    if column not in COLUMN_FIELDS:
        raise ValueError("Coluna SIGTAP inválida.")
    where, params = _combined_where(payload, column)
    field = COLUMN_FIELDS[column]
    with _connection(path) as connection:
        rows = connection.execute(f"SELECT DISTINCT {field} value FROM procedures p{where} ORDER BY value", params).fetchall()
        domains = _domain_map(connection) if column in {"group", "financing"} else {}
    values = []
    for row in rows:
        value = row["value"]
        code = "" if value is None else str(value)
        label = (_label(domains, column, code) or {}).get("label", code) if column in {"group", "financing"} else COMPLEXITY_LABELS.get(code, code) if column == "complexity" else code
        values.append({"value": code, "label": label or "Não informado"})
    return {"ok": True, "source": _source_status(meta, warning), "column": column, "values": values}


def options(payload: dict[str, Any]) -> dict[str, Any]:
    path, meta, warning = ensure_dataset(payload.get("competence"))
    kind = str(payload.get("kind") or "")
    if kind not in DOMAIN_FILES:
        raise ValueError("Tipo de relacionamento inválido.")
    term = str(payload.get("query") or "").strip()[:80]
    with _connection(path) as connection:
        rows = connection.execute("SELECT code,label FROM domains WHERE kind=? ORDER BY code", (kind,)).fetchall()
    normalized = _normalized(term)
    matched = [{"code": row["code"], "label": row["label"]} for row in rows
               if not term or normalized in _normalized(row["label"]) or term.casefold() in row["code"].casefold()]
    return {"ok": True, "source": _source_status(meta, warning), "options": matched[:200],
            "totalOptions": len(matched), "truncated": len(matched) > 200}


def detail(payload: dict[str, Any]) -> dict[str, Any]:
    path, meta, warning = ensure_dataset(payload.get("competence"))
    code = str(payload.get("code") or "")
    if not re.fullmatch(r"\d{10}", code):
        raise ValueError("Código SIGTAP inválido.")
    with _connection(path) as connection:
        row = connection.execute("SELECT * FROM procedures WHERE code=?", (code,)).fetchone()
        if row is None:
            raise ValueError("Procedimento não encontrado nesta competência.")
        domains = _domain_map(connection)
        relations: dict[str, list[dict[str, Any]]] = {}
        linked_rows = connection.execute("SELECT kind,target_code,attributes_json FROM relations WHERE procedure_code=? ORDER BY kind,target_code", (code,)).fetchall()
        for linked in linked_rows:
            kind = linked["kind"]
            target = linked["target_code"]
            if kind == "compatible":
                linked_procedure = connection.execute("SELECT name FROM procedures WHERE code=?", (target,)).fetchone()
                label = linked_procedure[0] if linked_procedure else "Procedimento não encontrado nesta competência"
                info = {"code": target, "label": label, "attributes": json.loads(linked["attributes_json"])}
            else:
                domain = _label(domains, kind, target)
                info = {**(domain or {"code": target, "label": "Descrição não publicada nesta competência"}),
                        "attributes": json.loads(linked["attributes_json"])}
            relations.setdefault(kind, []).append(info)
    return {"ok": True, "source": _source_status(meta, warning), "procedure": _procedure(row, domains), "relations": relations,
            "notice": "Relacionamento cadastral não garante autorização, produção, faturamento ou pagamento."}


def aggregates(payload: dict[str, Any]) -> dict[str, Any]:
    path, meta, warning = ensure_dataset(payload.get("competence"))
    filters = _parse_filters(payload)
    where, params = _where(filters)
    dimensions = ("group", "subgroup", "form", "complexity", "financing", "modality", "registration")
    with _connection(path) as connection:
        domains = _domain_map(connection)
        total = connection.execute("SELECT COUNT(*) FROM procedures p" + where, params).fetchone()[0]
        result = {}
        value_stats = {}
        for component, field in (("sa", "p.sa_cents"), ("sh", "p.sh_cents"), ("sp", "p.sp_cents")):
            row = connection.execute(f"SELECT COUNT(*) total,COUNT(CASE WHEN {field}>0 THEN 1 END) positive,MIN(CASE WHEN {field}>0 THEN {field} END) minimum,MAX({field}) maximum FROM procedures p{where}", params).fetchone()
            value_stats[component] = {"total": row["total"], "positive": row["positive"], "minimum": row["minimum"], "maximum": row["maximum"]}
        for kind in dimensions:
            if kind in FILTER_FIELDS:
                expression = FILTER_FIELDS[kind]
                rows = connection.execute(f"SELECT {expression} code,COUNT(*) amount FROM procedures p{where} GROUP BY {expression} ORDER BY amount DESC,code", params).fetchall()
            else:
                rows = connection.execute(f"SELECT r.target_code code,COUNT(DISTINCT p.code) amount FROM procedures p JOIN relations r ON r.procedure_code=p.code AND r.kind=?{where} GROUP BY r.target_code ORDER BY amount DESC,code", [kind, *params]).fetchall()
            result[kind] = [{"code": row["code"],
                             "label": COMPLEXITY_LABELS.get(row["code"], row["code"] or "Não informado") if kind == "complexity" else (_label(domains, kind, row["code"]) or {}).get("label", "Não informado"),
                             "count": row["amount"]} for row in rows]
    return {"ok": True, "source": _source_status(meta, warning), "total": total, "dimensions": result, "valueStats": value_stats,
            "notice": "Um procedimento pode ter vários relacionamentos; as categorias dessas distribuições podem se sobrepor."}


def compare(payload: dict[str, Any]) -> dict[str, Any]:
    before = _valid_competence(payload.get("before"))
    after = _valid_competence(payload.get("after"))
    if before == after:
        raise ValueError("Escolha duas competências diferentes.")
    before_path, before_meta, before_warning = ensure_dataset(before)
    after_path, after_meta, after_warning = ensure_dataset(after)
    if before_meta.get("complete") != "1" or after_meta.get("complete") != "1":
        raise RuntimeError("Uma das competências não está íntegra para comparação.")
    def signatures(path: Path):
        with _connection(path) as connection:
            procedures = {row["code"]: {"name": row["name"], "fields": {key: value for key, value in json.loads(row["raw_json"]).items() if key != "DT_COMPETENCIA"},
                                         "description": row["description"] or ""} for row in connection.execute("SELECT * FROM procedures")}
            for row in connection.execute("SELECT kind,procedure_code,target_code,attributes_json FROM relations ORDER BY kind,procedure_code,target_code,attributes_json"):
                if row["procedure_code"] in procedures:
                    attributes = {key: value for key, value in json.loads(row["attributes_json"]).items() if key != "DT_COMPETENCIA"}
                    procedures[row["procedure_code"]].setdefault("relations", []).append((row["kind"], row["target_code"], tuple(sorted(attributes.items()))))
            return procedures
    left, right = signatures(before_path), signatures(after_path)
    keys = sorted(set(left) | set(right))
    changes = []
    counts = {"added": 0, "removed": 0, "changed": 0}
    for code in keys:
        if code not in left:
            status = "added"
        elif code not in right:
            status = "removed"
        elif left[code] != right[code]:
            status = "changed"
        else:
            continue
        counts[status] += 1
        changes.append({"code": code, "status": status, "beforeName": left.get(code, {}).get("name"),
                        "afterName": right.get(code, {}).get("name"),
                        "fieldsChanged": sorted(key for key in set(left.get(code, {}).get("fields", {})) | set(right.get(code, {}).get("fields", {}))
                                                if left.get(code, {}).get("fields", {}).get(key) != right.get(code, {}).get("fields", {}).get(key)) if status == "changed" else [],
                        "relationsChanged": left.get(code, {}).get("relations", []) != right.get(code, {}).get("relations", []) if status == "changed" else False})
    export_all = payload.get("exportAll") is True
    if export_all and len(changes) > 10000:
        raise ValueError("A comparação excede o limite de 10.000 linhas para CSV.")
    page = 1 if export_all else max(1, min(int(payload.get("page") or 1), 100000))
    size = max(1, len(changes)) if export_all else 50
    return {"ok": True, "before": _source_status(before_meta, before_warning), "after": _source_status(after_meta, after_warning),
            "counts": counts, "count": len(changes), "page": page, "pageSize": size,
            "rows": changes[(page - 1) * size:page * size],
            "warning": "Uma publicação mais recente não pôde ser validada; a comparação usa uma versão local anterior." if before_warning or after_warning else ""}


def matching_codes(competence: str, filters: dict[str, Any]) -> tuple[set[str], dict[str, str]]:
    """Unique procedure codes for DATASUS joins; one-to-many relations never multiply production."""
    path, meta, warning = ensure_dataset(competence)
    checked = _parse_filters({"filters": filters})
    where, params = _where(checked)
    with _connection(path) as connection:
        codes = {row[0] for row in connection.execute("SELECT p.code FROM procedures p" + where, params)}
    return codes, _source_status(meta, warning)


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action")
    return {
        "sigtap_catalog": catalog,
        "sigtap_zip_prepare": lambda: prepare_zip(payload),
        "sigtap_search": lambda: search(payload),
        "sigtap_column_values": lambda: column_values(payload),
        "sigtap_options": lambda: options(payload),
        "sigtap_detail": lambda: detail(payload),
        "sigtap_aggregates": lambda: aggregates(payload),
        "sigtap_compare": lambda: compare(payload),
    }[action]()


if __name__ == "__main__":
    import sys
    try:
        request = json.load(sys.stdin)
        sys.stdout.write(json.dumps(handle(request), ensure_ascii=True))
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError) as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
        raise SystemExit(2)
