"""Tabulação local de arquivos DATASUS usando definições oficiais do TabWin."""
from __future__ import annotations

import json, os, re, subprocess, tempfile, zipfile, secrets, threading, time, sys, mmap, hashlib, stat, calendar, csv, io, shutil, gzip, unicodedata
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
import urllib.request, urllib.error, urllib.parse, xml.etree.ElementTree as ET, sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack, contextmanager
from ftplib import FTP
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from itertools import product
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from official_source import download_file as portal_download_file, open_verified_https
from storage_lock import interprocess_lock
from sigtap import matching_codes as sigtap_matching_codes

ROOT = Path(__file__).resolve().parents[1]
UPLOADS = Path(os.environ.get("TABWIN2_DATA_DIR", ROOT / "uploads")).expanduser().resolve()
UPLOADS.mkdir(parents=True, exist_ok=True)
VENDOR = Path(__file__).resolve().parent / "vendor"
FTP_BASE = "https://ftp.datasus.gov.br/dissemin/publicos"
AUX = {"SIA": f"{FTP_BASE}/SIASUS/200801_/Auxiliar/TAB_SIA.zip", "SIH": f"{FTP_BASE}/SIHSUS/200801_/Auxiliar/TAB_SIH.zip"}
DEF_MAP = {
 "PA":"Producao_Ambulatorial.DEF", "BI":"Producao_Ambulatorial.DEF", "AB":"APAC_Cirurgia_Bariatica.DEF",
 "ABO":"APAC_Pos_Cirurgia_Bariatica.def", "ACF":"APAC_Confeccao_de_Fistula.DEF", "AD":"APAC_Laudos_Diversos.DEF",
 "AM":"APAC_Medicamentos.DEF", "AMP":"APAC_Dados_Comuns.DEF", "AN":"APAC_Nefrologia.DEF", "AQ":"APAC_Quimioterapia.DEF",
 "AR":"APAC_Radioterapia.DEF", "ATD":"APAC_Tratamento_Dialitico.DEF", "PS":"RAAS_Psicossocial.def", "SAD":"Atencao_Domiciliar.def",
 "RD":"RD2008.DEF", "RJ":"RJ2008.DEF", "SP":"SP2008.DEF", "ER":"Motivo_de_Erro.DEF", "CH":"RD2008.DEF", "CM":"RD2008.DEF"
}
PREDEFINED_UF_CODES = {"RO":"11", "AC":"12", "AM":"13", "RR":"14", "PA":"15", "AP":"16", "TO":"17", "MA":"21", "PI":"22", "CE":"23", "RN":"24", "PB":"25", "PE":"26", "AL":"27", "SE":"28", "BA":"29", "MG":"31", "ES":"32", "RJ":"33", "SP":"35", "PR":"41", "SC":"42", "RS":"43", "MS":"50", "MT":"51", "GO":"52", "DF":"53"}
PREDEFINED_UF_NAMES = {"RO":"Rondônia", "AC":"Acre", "AM":"Amazonas", "RR":"Roraima", "PA":"Pará", "AP":"Amapá", "TO":"Tocantins", "MA":"Maranhão", "PI":"Piauí", "CE":"Ceará", "RN":"Rio Grande do Norte", "PB":"Paraíba", "PE":"Pernambuco", "AL":"Alagoas", "SE":"Sergipe", "BA":"Bahia", "MG":"Minas Gerais", "ES":"Espírito Santo", "RJ":"Rio de Janeiro", "SP":"São Paulo", "PR":"Paraná", "SC":"Santa Catarina", "RS":"Rio Grande do Sul", "MS":"Mato Grosso do Sul", "MT":"Mato Grosso", "GO":"Goiás", "DF":"Distrito Federal"}
PREDEFINED_FILTER_SPECS = (
    {"key":"manager","code":"managerCode","name":"managerName","label":"Gestor da produção","field":"PA_GESTAO","relation":"CNV/br_municgestor.CNV","width":6,"allLabel":"Todos os gestores","response":"managers","url":"gestor","stateScoped":True},
    {"key":"legalNature","code":"legalNatureCode","name":"legalNatureName","label":"Natureza jurídica","field":"PA_NAT_JUR","relation":"CNV/NATJUR.CNV","width":4,"allLabel":"Todas as naturezas jurídicas","response":"legalNatures","url":"natureza"},
    {"key":"managementType","code":"managementTypeCode","name":"managementTypeName","label":"Tipo de gestão","field":"PA_CONDIC","relation":"CNV/TP_GESTAO.CNV","width":2,"allLabel":"Todos os tipos de gestão","response":"managementTypes","url":"tipo_gestao"},
    {"key":"providerType","code":"providerTypeCode","name":"providerTypeName","label":"Tipo do prestador (público, privado etc.)","field":"PA_TIPPRE","relation":"CNV/TIPOPRES.CNV","width":2,"allLabel":"Todos os tipos de prestador","response":"providerTypes","url":"tipo_prestador"},
    {"key":"complexity","code":"complexityCode","name":"complexityName","label":"Complexidade do procedimento","field":"PA_NIVCPL","relation":"CNV/COMPLEX.CNV","width":1,"allLabel":"Todas as complexidades","response":"complexities","url":"complexidade"},
    {"key":"financing","code":"financingCode","name":"financingName","label":"Financiamento (MAC/FAEC)","field":"PA_TPFIN","relation":"CNV/FINANC.CNV","width":2,"allLabel":"Todos os financiamentos","response":"financings","url":"financiamento","auxiliaryRelation":True},
)
PREDEFINED_SIH_FILTER_SPECS = (
    {"key":"manager","label":"Gestor da produção","field":"UF_ZI","relation":"CNV/br_municgestor.cnv","width":6,"response":"managers","url":"gestor","stateScoped":True},
    {"key":"financing","label":"Financiamento (MAC/FAEC)","field":"FINANC","relation":"CNV/FINANC.CNV","width":2,"response":"financings","url":"financiamento"},
    {"key":"faecType","label":"Subtipo do FAEC","field":"FAEC_TP","relation":"CNV/TP_FINAN.CNV","width":6,"response":"faecTypes","url":"faec"},
    {"key":"complexity","label":"Complexidade","field":"COMPLEX","relation":"CNV/COMPLEX2.CNV","width":2,"response":"complexities","url":"complexidade"},
    {"key":"legalNature","label":"Natureza jurídica","field":"NAT_JUR","relation":"CNV/NATJUR.CNV","width":4,"response":"legalNatures","url":"natureza"},
    {"key":"providerNature","label":"Natureza do prestador","field":"NATUREZA","relation":"CNV/NATUREZA.CNV","width":2,"response":"providerNatures","url":"natureza_prestador"},
    {"key":"management","label":"Tipo de gestão","field":"GESTAO","relation":"CNV/GESTAO.CNV","width":1,"response":"managementTypes","url":"gestao"},
    {"key":"admissionType","label":"Caráter de atendimento","field":"CAR_INT","relation":"CNV/CARATEND.CNV","width":2,"response":"admissionTypes","url":"carater"},
)
PREDEFINED_SIH_OCCUPANCY_FILTER_SPECS = PREDEFINED_SIH_FILTER_SPECS + (
    {"key":"specialty","label":"Tipo de leito","field":"ESPEC","relation":"CNV/LEITOS.CNV","width":2,"response":"specialties","url":"especialidade"},
)
PREDEFINED_SIH_SP_FILTER_SPECS = (
    {"key":"manager","label":"Gestor da produção","field":"SP_GESTOR","relation":"CNV/br_municgestor.cnv","width":6,"response":"managers","url":"gestor","stateScoped":True},
    {"key":"professionalCbo","label":"CBO do profissional","field":"SP_PF_CBO","relation":"DBF/CBO.DBF","width":6,"response":"professionalCbos","url":"cbo"},
)
PREDEFINED_SIH_SP_CNES_FILTERS = (
    {"key":"cnesManagement","payload":"cnesManagementCode","name":"cnesManagementName","label":"Tipo de gestão · CNES","response":"cnesManagementTypes","source":"competence"},
    {"key":"cnesNatureGroup","payload":"cnesNatureGroupCode","name":"cnesNatureGroupName","label":"Natureza jurídica · grupo CNES","response":"cnesNatureGroups","source":"competence"},
    {"key":"cnesLegalNature","payload":"cnesLegalNatureCode","name":"cnesLegalNatureName","label":"Natureza jurídica detalhada · CNES","response":"cnesLegalNatures","source":"competence"},
    {"key":"cnesHospitalSUS","payload":"cnesHospitalSUSCode","name":"cnesHospitalSUSName","label":"Atendimento hospitalar SUS · CNES atual","response":"cnesHospitalSUS","source":"current"},
)
CNES_OPEN_DATA_HOST = "apidadosabertos.saude.gov.br"
CNES_ESTABLISHMENT_CACHE = UPLOADS/".cache"/"cnes-establishment-classifications.sqlite3"
CNES_ESTABLISHMENT_CACHE_LOCK = threading.RLock()
FILENAME = re.compile(r"^(?P<kind>[A-Z]{2,4}?)(?P<uf>[A-Z]{2})(?P<yy>\d{2})(?P<mm>\d{2})(?:[A-Z])?\.DBC$", re.I)
SP_EXTRA_DIMENSIONS = (("SP_NAIH","AIH"),("SP_PF_DOC","CNS do profissional"))
JOB_WRITE_LOCK = threading.Lock()
ATOMIC_JOB_WRITE_LOCK = threading.RLock()
SLOW_FALLBACK_LIMIT = 8 * 1024 * 1024
# Bases DBC estaduais podem levar vários minutos para decodificar. O limite
# anterior de dois minutos encerrava conversões válidas no Windows.
NATIVE_TIMEOUT_SECONDS = 3600
ALLOW_FTP_FALLBACK = os.environ.get("TABWIN2_ALLOW_FTP_FALLBACK", "1").strip().lower() not in {"0", "false", "no", "off"}
try:
    MAX_HEAVY_JOBS = max(1, min(int(os.environ.get("TABWIN2_MAX_HEAVY_JOBS", "2")), 8))
except ValueError:
    MAX_HEAVY_JOBS = 2

def dbf_reader():
    import sys
    sys.path.insert(0, str(VENDOR))
    from dbfread import DBF
    return DBF

def safe_upload_relative(relative: str, suffix: str) -> tuple[Path, str]:
    if not isinstance(relative, str) or not relative or len(relative) > 600 or "\x00" in relative:
        raise ValueError("Arquivo inválido.")
    normalized=relative.replace("\\", "/")
    posix=PurePosixPath(normalized); windows=PureWindowsPath(relative)
    parts=normalized.split("/")
    if posix.is_absolute() or windows.is_absolute() or windows.drive or any(part in {"", ".", ".."} or ":" in part for part in parts):
        raise ValueError("O caminho do arquivo é inválido.")
    path=(UPLOADS.joinpath(*parts)).resolve()
    if not path.is_relative_to(UPLOADS) or path.suffix.lower()!=suffix.lower() or not path.is_file():
        raise ValueError("O arquivo não existe na biblioteca ou o caminho é inválido.")
    return path,path.relative_to(UPLOADS).as_posix()

def safe_file(relative: str) -> Path:
    path,_=safe_upload_relative(relative,".dbc")
    return path

def safe_converted_path(source_relative: str, create_parent: bool = False) -> Path:
    relative=converted_relative(source_relative)
    target=UPLOADS/relative
    parent=target.parent.resolve()
    if not parent.is_relative_to(UPLOADS):
        raise ValueError("O destino convertido está fora da biblioteca.")
    if create_parent:
        parent.mkdir(parents=True,exist_ok=True)
        parent=target.parent.resolve()
        if not parent.is_relative_to(UPLOADS): raise ValueError("O destino convertido está fora da biblioteca.")
    return parent/target.name

def safe_dbf(relative: str, source_relative: str) -> Path:
    path,canonical=safe_upload_relative(relative,".dbf")
    expected=safe_converted_path(source_relative)
    if "CONVERTIDOS" not in path.relative_to(UPLOADS).parts or os.path.normcase(str(path))!=os.path.normcase(str(expected)):
        raise ValueError("O DBF convertido não corresponde ao DBC selecionado.")
    if canonical != path.relative_to(UPLOADS).as_posix():
        raise ValueError("O caminho do DBF convertido é inválido.")
    return path

def dbf_layout(path: Path):
    with path.open("rb") as stream:
        header=stream.read(32)
        if len(header)<32: raise ValueError("Cabeçalho DBF incompleto.")
        count=int.from_bytes(header[4:8],"little")
        header_len=int.from_bytes(header[8:10],"little")
        record_len=int.from_bytes(header[10:12],"little")
        if header_len<33 or record_len<2: raise ValueError("Estrutura DBF inválida.")
        stream.seek(0); raw=stream.read(header_len)
    fields={}; offset=1; pos=32
    while pos+32<=len(raw) and raw[pos]!=0x0D:
        desc=raw[pos:pos+32]
        name=desc[:11].split(b"\0",1)[0].decode("ascii","replace").strip().upper()
        length=desc[16]
        if not name or length<1: break
        fields[name]={"offset":offset,"length":length,"type":chr(desc[11]),"decimals":desc[17]}
        offset+=length; pos+=32
    if not fields or offset>record_len: raise ValueError("Campos DBF incompatíveis com o tamanho dos registros.")
    if header_len+count*record_len>path.stat().st_size: raise ValueError("O DBF está incompleto.")
    return count,header_len,record_len,fields

def iter_dbf_fields(path: Path, names: list[str], with_index: bool=False, pre_filter: tuple[str,str | list[str]] | list[tuple[str,str | list[str]]] | None=None, processed_counter: list[int] | None=None, scan_callback=None):
    count,header_len,record_len,fields=dbf_layout(path)
    ordered=list(dict.fromkeys(name.upper() for name in names))
    missing=[name for name in ordered if name not in fields]
    if missing: raise ValueError("Campo não encontrado no DBF: "+", ".join(missing))
    slices=[(fields[name]["offset"],fields[name]["length"]) for name in ordered]
    filter_slices=[]
    if pre_filter:
        requested_filters=pre_filter if isinstance(pre_filter,list) else [pre_filter]
        for filter_name,raw_filter_values in requested_filters:
            if not filter_name or not raw_filter_values: continue
            if filter_name.upper() not in fields: raise ValueError("Campo de filtro não encontrado no DBF.")
            filter_values=raw_filter_values if isinstance(raw_filter_values,(list,tuple,set)) else [raw_filter_values]
            expected={str(value).encode("ascii").lstrip(b"0") for value in filter_values if str(value)}
            if expected: filter_slices.append(((fields[filter_name.upper()]["offset"],fields[filter_name.upper()]["length"]),expected))
    with path.open("rb") as stream:
        mapped=mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ)
        try:
            next_report=50000
            for index in range(count):
                start=header_len+index*record_len
                if mapped[start]==0x2A: continue
                if processed_counter is not None:
                    processed_counter[0]+=1
                    if scan_callback is not None and processed_counter[0]>=next_report:
                        scan_callback(processed_counter[0],count)
                        next_report+=50000
                if filter_slices and any(mapped[start+offset:start+offset+length].strip(b" \x00").lstrip(b"0") not in expected for (offset,length),expected in filter_slices): continue
                values=tuple(mapped[start+offset:start+offset+length].decode("latin1").strip() for offset,length in slices)
                yield (index,values) if with_index else values
        finally:
            mapped.close()

def cache_target(namespace: str, identity: dict[str,Any]):
    digest=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=True,separators=(",",":")).encode("utf-8")).hexdigest()
    folder=UPLOADS/".cache"/namespace
    folder.mkdir(parents=True,exist_ok=True)
    return folder/(digest+".json")

def cache_read(target: Path):
    try: return json.loads(target.read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError): return None

def cache_write(target: Path, value: dict[str,Any], max_bytes: int|None=None, keep: int=50):
    raw=json.dumps(value,ensure_ascii=True,separators=(",",":"))
    if max_bytes is not None and len(raw.encode("utf-8"))>max_bytes: return
    fd,tmp=tempfile.mkstemp(prefix="cache-",suffix=".part",dir=str(target.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream: stream.write(raw)
        Path(tmp).replace(target)
    finally: Path(tmp).unlink(missing_ok=True)
    cached=sorted(target.parent.glob("*.json"),key=lambda p:p.stat().st_mtime,reverse=True)
    for old in cached[keep:]: old.unlink(missing_ok=True)

def cache_file_identity(path: Path):
    stat=path.stat()
    return {"path":path.relative_to(UPLOADS).as_posix(),"size":stat.st_size,"mtime":stat.st_mtime_ns}

def scaled_integer(value: str, decimals: int) -> int:
    value=value.strip()
    if not value: return 0
    try:
        if "e" in value.lower(): return int(Decimal(value)*Decimal(10**decimals))
        negative=value.startswith("-")
        unsigned=value[1:] if value[:1] in {"-","+"} else value
        whole,sep,fraction=unsigned.partition(".")
        digits=(whole or "0")+(fraction[:decimals].ljust(decimals,"0") if decimals else "")
        result=int(digits or "0")
        return -result if negative else result
    except (ValueError,InvalidOperation): return 0

def scaled_text(value: int, decimals: int) -> str:
    return str(value) if decimals==0 else format(Decimal(value).scaleb(-decimals),"f")

def decompress(path: Path, progress=None, expected_size=0, output_path: Path | None = None, method_callback=None):
    exe = VENDOR / "dbc_reader" / "bin" / ("blast-dbf.exe" if os.name == "nt" else "blast-dbf-linux")
    if not exe.exists(): raise RuntimeError("O descompactador DBC não está disponível.")
    if output_path is None:
        fd, tmp = tempfile.mkstemp(suffix=".dbf", prefix="tabwin2-"); os.close(fd)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(output_path)
        Path(tmp).unlink(missing_ok=True)
    stop=threading.Event()
    def watch():
        while not stop.wait(.35):
            try:
                size=Path(tmp).stat().st_size
                pct=min(94,max(3,int(size*90/max(1,expected_size))))
                if progress: progress(pct,size)
            except OSError: pass
    monitor=threading.Thread(target=watch,daemon=True); monitor.start()
    try:
        if method_callback: method_callback("rápido", "Usando o conversor rápido incluído no aplicativo.")
        native_error = None
        try:
            # blast-dbf seeks within the DBC header, so it must open the source
            # by filename. Feeding it through stdin makes it fail and triggers
            # the much slower pure-Python fallback.
            creationflags = 0
            if os.name == "nt":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            proc = subprocess.run([str(exe), str(path), tmp], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=NATIVE_TIMEOUT_SECONDS, creationflags=creationflags)
            output_size = Path(tmp).stat().st_size if Path(tmp).exists() else 0
            if proc.returncode or output_size < 32:
                detail = proc.stderr.decode("latin1", "replace").strip()[:300]
                exit_code = proc.returncode & 0xFFFFFFFF
                if exit_code == 0xC000013A:
                    native_error = "o Windows interrompeu o conversor (CTRL+C)"
                else:
                    native_error = detail or f"o conversor rápido encerrou com o código {proc.returncode}"
        except subprocess.TimeoutExpired:
            native_error = f"o conversor rápido excedeu o limite de {NATIVE_TIMEOUT_SECONDS} segundos"
        except OSError as exc:
            native_error = str(exc)

        if native_error:
            if path.stat().st_size > SLOW_FALLBACK_LIMIT:
                raise RuntimeError(
                    "O conversor rápido não conseguiu abrir este arquivo. "
                    "Para evitar uma espera de vários minutos, o modo lento não foi iniciado. "
                    f"Detalhe: {native_error}"
                )
            if method_callback: method_callback("compatibilidade", "Usando o modo de compatibilidade para um arquivo pequeno.")
            import sys
            sys.path.insert(0, str(VENDOR))
            from dbctodbf import DBCDecompress
            DBCDecompress().decompressFile(str(path), tmp)
        if Path(tmp).stat().st_size < 32:
            raise RuntimeError("O arquivo não produziu um DBF válido ao descompactar.")
        stop.set(); monitor.join(timeout=1)
        if progress: progress(96,Path(tmp).stat().st_size)
        return tmp
    except Exception:
        stop.set(); monitor.join(timeout=1)
        Path(tmp).unlink(missing_ok=True); raise

def open_dbf(path: Path):
    tmp = decompress(path)
    try:
        DBF = dbf_reader()
        table = DBF(tmp, load=False, encoding="latin1", char_decode_errors="replace", ignore_missing_memofile=True)
        fields = [{"name":f.name, "type":f.type, "length":f.length, "decimals":f.decimal_count} for f in table.fields]
        return tmp, table, fields
    except Exception:
        Path(tmp).unlink(missing_ok=True); raise

def dbc_header(path: Path):
    # O cabeçalho DBF (incluindo os campos) é preservado sem compressão no DBC.
    with path.open("rb") as stream:
        head=stream.read(32)
        if len(head)<32: raise ValueError("Cabeçalho DBC incompleto.")
        records=int.from_bytes(head[4:8],"little")
        header_len=int.from_bytes(head[8:10],"little")
        if header_len<33 or header_len>65535: raise ValueError("Cabeçalho DBF inválido dentro do DBC.")
        stream.seek(0); raw=stream.read(header_len)
    fields=[]; offset=32
    while offset+32<=len(raw) and raw[offset]!=0x0D:
        desc=raw[offset:offset+32]
        name=desc[:11].split(b"\0",1)[0].decode("ascii","replace").strip()
        if not name: break
        fields.append({"name":name,"type":chr(desc[11]),"length":desc[16],"decimals":desc[17]})
        offset+=32
    if not fields: raise ValueError("O DBC não contém descritores de campos DBF válidos.")
    return fields,records

def meta(path: Path):
    match = FILENAME.match(path.name)
    if not match: raise ValueError("Nome de arquivo DBC fora do padrão esperado.")
    rel = path.relative_to(UPLOADS)
    system = rel.parts[0].upper()
    kind = match.group("kind").upper()
    return system, kind, match

def municipality_field(system: str, fieldnames):
    """Return the known service-location field only when this report has it."""
    available={str(name).upper() for name in fieldnames}
    candidates={"SIA":("PA_UFMUN",),"SIH":("MUNIC_MOV",)}.get(system,())
    return next((name for name in candidates if name in available),"")

def municipality_code(payload, fieldnames, field):
    code=str(payload.get("municipalityCode") or "").strip()
    # Some report layouts do not carry a municipal field. In that case, do not
    # apply a different field with another meaning or block the tabulation.
    if not code or not field or field.upper() not in {str(name).upper() for name in fieldnames}: return ""
    if not re.fullmatch(r"\d{6}",code): raise ValueError("O código do município deve ter seis dígitos.")
    return code

def catalog():
    files=[]; manifest={}; active_jobs={}; definition_identities={}
    for system in ("SIA","SIH"):
        archive=UPLOADS/"DEFINICOES"/"originais"/f"TAB_{system}.zip"
        try:
            if archive.is_file(): definition_identities[system]=cache_file_identity(archive)
        except OSError: pass
    try:
        items=json.loads((UPLOADS/"manifest.json").read_text(encoding="utf-8"))
        if isinstance(items,list): manifest={x.get("path"):x for x in items if isinstance(x,dict)}
    except Exception: pass
    jobs=UPLOADS/".jobs"
    if jobs.is_dir():
        for statefile in sorted(jobs.glob("*.json"),key=lambda p:p.stat().st_mtime,reverse=True):
            try:
                state=read_job_state(statefile)
                source=state.get("source_path")
                if source and source not in active_jobs and state.get("status") in {"queued","running"} and job_worker_alive(state,statefile):
                    active_jobs[source]={"id":state.get("id"),"status":state.get("status"),"progress":state.get("progress",1),"stage":state.get("stage","Leitura em andamento"),"bytes_written":state.get("bytes_written",0),"temporary_path":state.get("temporary_path"),"converter":state.get("converter")}
            except Exception: pass
    for p in UPLOADS.glob("**/*.dbc"):
        try:
            sysname,kind,m=meta(p); rel=p.relative_to(UPLOADS).as_posix(); info=manifest.get(rel,{})
            converted=converted_relative(rel)
            dbf=safe_converted_path(rel)
            dbf_exists=dbf.is_file(); dbf_stat=dbf.stat() if dbf_exists else None
            source_stat=p.stat()
            files.append({"path":rel,"name":p.name,"system":sysname,"kind":kind,"uf":m.group("uf").upper(),"year":2000+int(m.group("yy")),"month":int(m.group("mm")),"size":source_stat.st_size,"mtime_ns":source_stat.st_mtime_ns,"downloaded_at":info.get("downloaded_at"),"converted":dbf_exists,"dbf_path":converted if dbf_exists else None,"dbf_size":dbf_stat.st_size if dbf_stat else None,"dbf_mtime_ns":dbf_stat.st_mtime_ns if dbf_stat else None,"conversion":active_jobs.get(rel)})
        except Exception: continue
    files.sort(key=lambda x:(x["system"],-x["year"],-x["month"],x["name"]))
    return {"ok":True,"files":files,"library_root":str(UPLOADS),"definitionIdentities":definition_identities}

def delete_library_file(payload: dict[str,Any]):
    source=safe_file(payload.get("path",""))
    relative=source.relative_to(UPLOADS).as_posix()
    with source_use_locks([relative],blocking=False):
        return _delete_library_file_locked(payload,source,relative)

def _delete_library_file_locked(payload: dict[str,Any], source: Path, relative: str):
    system,_,_=meta(source)
    if system not in {"SIA","SIH"}:
        raise ValueError("Somente arquivos ambulatoriais e hospitalares importados podem ser removidos daqui.")

    jobs=UPLOADS/".jobs"
    if jobs.is_dir():
        for statefile in jobs.glob("*.json"):
            try:
                state=read_job_state(statefile)
            except Exception:
                pass
            else:
                if state.get("source_path")==relative and state.get("status") in {"queued","running"} and job_worker_alive(state,statefile):
                    raise ValueError("Este arquivo está sendo preparado para leitura. Aguarde a conclusão antes de removê-lo.")
        tabulation_jobs=jobs/"tabulations"
        if tabulation_jobs.is_dir():
            for statefile in tabulation_jobs.glob("*.json"):
                try:
                    state=read_job_state(statefile)
                except Exception:
                    pass
                else:
                    if state.get("status") not in {"queued","running"}:
                        continue
                    selected={str(value).replace("\\","/") for value in state.get("active_sources",[])}
                    data=state.get("payload") or {}
                    selected.add(str(data.get("path") or "").replace("\\","/"))
                    selected.update(str(item.get("path") or "").replace("\\","/") for item in data.get("sources",[]) if isinstance(item,dict))
                    if relative in selected and job_worker_alive(state,statefile):
                        raise ValueError("Este arquivo está sendo usado por uma tabulação em andamento. Aguarde a conclusão antes de removê-lo.")

    converted=safe_converted_path(relative)
    source.unlink()
    converted.unlink(missing_ok=True)
    for partial in converted.parent.glob(converted.name+".*.part"):
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass

    remove_manifest_entry(relative)

    # The client already has the current library list and removes this item locally.
    # Rebuilding the catalog here recursively walks every DBC and stats every DBF,
    # making a simple file deletion wait on unrelated bases.
    return {"ok":True,"deleted":{"path":relative,"name":source.name}}

def remove_manifest_entry(relative: str):
    manifest=UPLOADS/"manifest.json"
    try:
        with interprocess_lock(UPLOADS/".jobs"/"storage.lock"):
            items=json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(items,list): return
            retained=[item for item in items if not isinstance(item,dict) or str(item.get("path") or "").replace("\\","/")!=relative]
            if len(retained)==len(items): return
            fd,temporary=tempfile.mkstemp(prefix=f"manifest-{os.getpid()}-",suffix=".json.part",dir=str(UPLOADS))
            try:
                with os.fdopen(fd,"w",encoding="utf-8") as stream:
                    stream.write(json.dumps(retained,ensure_ascii=False,indent=2)+"\n")
                os.replace(temporary,manifest)
            finally:
                Path(temporary).unlink(missing_ok=True)
    except (OSError,json.JSONDecodeError):
        pass

def converted_relative(source_relative: str) -> str:
    source=safe_file(source_relative)
    rel=source.relative_to(UPLOADS)
    return (Path("CONVERTIDOS")/rel.parent/(rel.stem+".dbf")).as_posix()

def jobfile(job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}",str(job_id)): raise ValueError("Identificador de conversão inválido.")
    folder=UPLOADS/".jobs"; folder.mkdir(parents=True,exist_ok=True)
    return folder/(job_id+".json")

@contextmanager
def _job_directory_lock(folder: Path):
    """Serialize job status replacements across the web process and workers."""
    lock_path=folder/".job-write.lock"
    with interprocess_lock(lock_path):
        yield

@contextmanager
def source_use_locks(relative_paths, blocking=True):
    """Cross-process locks shared by readers/converters and library deletion."""
    lock_folder=UPLOADS/".jobs"/"file-locks"
    lock_folder.mkdir(parents=True,exist_ok=True)
    try:
        identities=sorted({str(path).replace("\\","/").casefold() for path in relative_paths})
        with ExitStack() as stack:
            for identity in identities:
                lock_path=lock_folder/(hashlib.sha256(identity.encode("utf-8")).hexdigest()+".lock")
                stack.enter_context(interprocess_lock(lock_path,blocking=blocking))
            yield
    except TimeoutError as exc:
        if not blocking:
            raise ValueError("Este arquivo está em uso por uma conversão, tabulação ou exportação. Aguarde e tente novamente.") from exc
        raise
    except (OSError,BlockingIOError) as exc:
        if not blocking:
            raise ValueError("Este arquivo está em uso por uma conversão, tabulação ou exportação. Aguarde e tente novamente.") from exc
        raise

def job_worker_alive(state: dict[str,Any], statefile: Path) -> bool:
    pid=state.get("worker_pid")
    if isinstance(pid,int) and pid>0:
        try:
            os.kill(pid,0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False
    try: return time.time()-statefile.stat().st_mtime<300
    except OSError: return False

def job_status_grace_elapsed(statefile: Path, seconds: float = 15) -> bool:
    """Avoid reporting a worker as interrupted during its final atomic write."""
    try: return time.time()-statefile.stat().st_mtime>=seconds
    except OSError: return True

@contextmanager
def reserve_heavy_job_slot():
    with interprocess_lock(UPLOADS/".jobs"/"heavy-jobs.lock"):
        active=0
        root=UPLOADS/".jobs"
        for folder in (root,root/"tabulations"):
            if not folder.is_dir(): continue
            for statefile in folder.glob("*.json"):
                if statefile.name.endswith(".result.json"): continue
                try:
                    state=read_job_state(statefile)
                    if state.get("status") in {"queued","running"} and job_worker_alive(state,statefile):
                        active+=1
                except (OSError,ValueError,TypeError):
                    continue
        if active>=MAX_HEAVY_JOBS:
            raise ValueError(f"Há {active} processos pesados em andamento. Aguarde uma vaga antes de iniciar outra conversão ou tabulação.")
        yield

def atomic_job_write(target: Path, data: dict[str,Any]):
    target.parent.mkdir(parents=True,exist_ok=True)
    with ATOMIC_JOB_WRITE_LOCK, _job_directory_lock(target.parent):
        descriptor,temp_name=tempfile.mkstemp(prefix=f".{target.stem}.{os.getpid()}.{threading.get_ident()}.",suffix=".part",dir=str(target.parent))
        temporary=Path(temp_name)
        try:
            with os.fdopen(descriptor,"w",encoding="utf-8") as stream:
                stream.write(json.dumps(data,ensure_ascii=True))
                stream.flush()
            for attempt in range(80):
                try:
                    os.replace(temporary,target)
                    return
                except PermissionError:
                    if os.name=="nt" and attempt==0 and target.exists():
                        try: os.chmod(target,target.stat().st_mode|stat.S_IWRITE)
                        except OSError: pass
                    if attempt==79: raise
                    time.sleep(min(.12,.025*(attempt+1)))
        finally:
            temporary.unlink(missing_ok=True)

def read_job_state(target: Path) -> dict[str,Any]:
    """Read a job snapshot without racing its atomic replacement on Windows."""
    with ATOMIC_JOB_WRITE_LOCK, _job_directory_lock(target.parent):
        for attempt in range(6):
            try:
                return json.loads(target.read_text(encoding="utf-8"))
            except PermissionError:
                if attempt == 5: raise
                time.sleep(.04 * (attempt + 1))

def write_job(job_id: str, data: dict[str,Any]):
    target=jobfile(job_id)
    with JOB_WRITE_LOCK:
        atomic_job_write(target,data)

def start_conversion(source_relative: str):
    source=safe_file(source_relative); canonical=source.relative_to(UPLOADS).as_posix()
    with source_use_locks([canonical]):
        return _start_conversion_locked(canonical)

def _start_conversion_locked(source_relative: str):
    source=safe_file(source_relative); source_relative=source.relative_to(UPLOADS).as_posix(); system,kind,_=meta(source); fields,records=dbc_header(source)
    expected=32+32*len(fields)+1+records*(1+sum(f["length"] for f in fields))+1
    target=safe_converted_path(source_relative,create_parent=True)
    if target.is_file() and target.stat().st_size==expected:
        return {"ok":True,"done":True,"progress":100,"dbf_path":target.relative_to(UPLOADS).as_posix(),"dbfIdentity":cache_file_identity(target),"message":"A leitura desta base já está preparada."}
    jobs=UPLOADS/".jobs"
    if jobs.exists():
        for statefile in jobs.glob("*.json"):
            try:
                active=read_job_state(statefile)
                if active.get("source_path")==source_relative and active.get("status") in {"queued","running"}:
                    if job_worker_alive(active,statefile):
                        return {"ok":True,"done":False,"job_id":active["id"],"progress":active.get("progress",1),"stage":active.get("stage","Conversão em andamento")}
                    active.update(status="error",stage="Leitura interrompida",message="A leitura anterior parou de atualizar. Inicie novamente para continuar.")
                    write_job(active["id"],active)
            except Exception: pass
    with reserve_heavy_job_slot():
        job_id=secrets.token_hex(16)
        dbf_relative=converted_relative(source_relative)
        temporary_relative=dbf_relative+f".{job_id}.part"
        write_job(job_id,{"id":job_id,"status":"queued","progress":1,"stage":"Preparando a leitura","message":"A base entrou na fila de leitura.","source_path":source_relative,"expected_size":expected,"dbf_path":dbf_relative,"temporary_path":temporary_relative})
        command=[sys.executable,str(Path(__file__).resolve()),"--worker",job_id]
        flags=getattr(subprocess,"DETACHED_PROCESS",0x00000008)|getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0x00000200) if os.name=="nt" else 0
        try:
            subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags,start_new_session=os.name!="nt",cwd=str(ROOT))
        except Exception as exc:
            failed=read_job_state(jobfile(job_id)); failed.update(status="error",stage="Não foi possível iniciar",message="A preparação não iniciou. Tente novamente.")
            write_job(job_id,failed)
            raise RuntimeError("Não foi possível iniciar a preparação do arquivo.") from exc
    return {"ok":True,"done":False,"job_id":job_id,"progress":1,"stage":"Preparando a leitura"}

def conversion_status(job_id: str):
    path=jobfile(job_id)
    if not path.is_file(): raise ValueError("Conversão não encontrada.")
    state=read_job_state(path)
    if state.get("status") in {"queued","running"} and not job_worker_alive(state,path) and job_status_grace_elapsed(path):
        state.update(status="error",stage="Leitura interrompida",message="A preparação da leitura parou de atualizar. Tente iniciar novamente.")
        write_job(job_id,state)
    return {"ok":True,**state}

def run_conversion_worker(job_id: str):
    state=read_job_state(jobfile(job_id)); source=safe_file(state["source_path"]); relative=source.relative_to(UPLOADS).as_posix()
    with source_use_locks([relative]):
        return _run_conversion_worker_locked(job_id)

def _run_conversion_worker_locked(job_id: str):
    state=read_job_state(jobfile(job_id)); source_rel=state["source_path"]
    source=safe_file(source_rel); source_rel=source.relative_to(UPLOADS).as_posix(); target=safe_converted_path(source_rel,create_parent=True)
    temporary_output=target.with_name(target.name+f".{job_id}.part")
    try:
        state.update(status="running",stage="Preparando a leitura do DBC",progress=2,message="A leitura da base está em andamento.",worker_pid=os.getpid()); write_job(job_id,state)
        def progress(pct,size):
            state.update(progress=pct,bytes_written=size,stage="Lendo dados da base",status="running"); write_job(job_id,state)
        def method_changed(method,message):
            state.update(converter=method,message=message); write_job(job_id,state)
        dbc_header_info,records=dbc_header(source)
        expected=32+32*len(dbc_header_info)+1+records*(1+sum(f["length"] for f in dbc_header_info))+1
        decompressed=decompress(source,progress,expected,temporary_output,method_changed)
        state.update(stage="Finalizando a leitura",progress=98); write_job(job_id,state)
        os.replace(decompressed,target)
        state.update(status="done",stage="Leitura preparada",progress=100,dbf_path=target.relative_to(UPLOADS).as_posix(),dbfIdentity=cache_file_identity(target),bytes_written=target.stat().st_size,message="A base está pronta para tabulação."); write_job(job_id,state)
    except Exception as exc:
        temporary_output.unlink(missing_ok=True)
        state.update(status="error",stage="Não foi possível preparar a leitura",message=str(exc)); write_job(job_id,state)

def tabulation_jobfile(job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}",str(job_id)): raise ValueError("Identificador de tabulação inválido.")
    folder=UPLOADS/".jobs"/"tabulations"; folder.mkdir(parents=True,exist_ok=True)
    return folder/(job_id+".json")

def write_tabulation_job(job_id: str, state: dict[str,Any]):
    target=tabulation_jobfile(job_id)
    with JOB_WRITE_LOCK:
        atomic_job_write(target,state)

def start_tabulation(payload: dict[str,Any]):
    payload=json.loads(json.dumps(payload))
    if payload.get("predefinedReport") in {"sinan-dengue","sinan-chikungunya","sinan-zika","sim-mortalidade","sim-mortalidade-infantil","srag-semanal","sinasc-maternidades","sisagua-residual-desinfetante","pqavs-obitos-arboviroses","pqavs-contatos-hanseniase","pqavs-contatos-tuberculose","pqavs-sifilis-congenita","pqavs-violencia-raca-cor"}:
        year=payload.get("year")
        month=payload.get("month")
        uf=str(payload.get("uf") or "").upper()
        municipality=str(payload.get("municipalityCode") or "")
        if not isinstance(year,int) or year<2000 or year>date.today().year:
            raise ValueError("Selecione um ano entre 2000 e o ano atual.")
        if not isinstance(month,int) or month<1 or month>12:
            raise ValueError("Selecione uma competência válida.")
        if uf not in PREDEFINED_UF_CODES or not re.fullmatch(r"\d{6}",municipality) or municipality[:2]!=PREDEFINED_UF_CODES[uf]:
            raise ValueError("Selecione um município válido da unidade da Federação escolhida.")
        if payload.get("predefinedReport")=="sinasc-maternidades":
            if year<2010 or payload.get("view") not in {"full","detail"}:
                raise ValueError("Selecione um ano e uma visão válidos para o SINASC.")
            if payload["view"]=="detail" and not re.fullmatch(r"\d{7}",str(payload.get("establishmentCode") or "")):
                raise ValueError("Selecione um estabelecimento válido para detalhar.")
        return _start_tabulation_locked(payload,[])
    raw_sources=payload.get("sources")
    has_multiple=isinstance(raw_sources,list) and len(raw_sources)>0
    entries=raw_sources if has_multiple else [{"path":payload.get("path",""),"dbfPath":payload.get("dbfPath")}]
    if not isinstance(entries,list) or not 1<=len(entries)<=50:
        raise ValueError("A lista de arquivos da tabulação é inválida.")
    canonical_sources=[]; normalized_entries=[]
    for entry in entries:
        if not isinstance(entry,dict): raise ValueError("A lista de arquivos da tabulação é inválida.")
        source=safe_file(entry.get("path",""))
        canonical=source.relative_to(UPLOADS).as_posix()
        dbf_path=entry.get("dbfPath")
        if dbf_path:
            safe_dbf(str(dbf_path),canonical)
            dbf_path=converted_relative(canonical)
        normalized_entries.append({**entry,"path":canonical,**({"dbfPath":dbf_path} if dbf_path else {})})
        canonical_sources.append(canonical)
    if has_multiple:
        payload["sources"]=normalized_entries
    else:
        payload["path"]=canonical_sources[0]
        if normalized_entries[0].get("dbfPath"): payload["dbfPath"]=normalized_entries[0]["dbfPath"]
    with source_use_locks(canonical_sources):
        return _start_tabulation_locked(payload,canonical_sources)

def _start_tabulation_locked(payload: dict[str,Any], active_sources: list[str]):
    if len(json.dumps(payload,ensure_ascii=True))>100000: raise ValueError("A configuração da tabulação é grande demais.")
    request_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=True,separators=(",",":")).encode("utf-8")).hexdigest()
    folder=UPLOADS/".jobs"/"tabulations"
    folder.mkdir(parents=True,exist_ok=True)
    for existing in folder.glob("*.json"):
        if existing.name.endswith(".result.json"): continue
        try:
            state=read_job_state(existing)
            if state.get("request_hash")!=request_hash or state.get("status") not in {"queued","running"}:
                continue
            if job_worker_alive(state,existing):
                return {"ok":True,"job_id":state["id"],"status":state["status"],"progress":state.get("progress",1),"stage":state.get("stage","Tabulação em andamento"),"reused":True}
        except (OSError,ValueError,TypeError,KeyError):
            continue
    with reserve_heavy_job_slot():
        job_id=secrets.token_hex(16)
        write_tabulation_job(job_id,{"id":job_id,"request_hash":request_hash,"status":"queued","progress":1,"stage":"Preparando tabulação","payload":payload,"active_sources":active_sources})
        command=[sys.executable,str(Path(__file__).resolve()),"--tabulate-worker",job_id]
        flags=getattr(subprocess,"DETACHED_PROCESS",0x00000008)|getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0x00000200) if os.name=="nt" else 0
        try:
            subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags,start_new_session=os.name!="nt",cwd=str(ROOT))
        except Exception:
            tabulation_jobfile(job_id).unlink(missing_ok=True)
            raise
    return {"ok":True,"job_id":job_id,"status":"queued","progress":1,"stage":"Preparando tabulação"}

def tabulation_status(job_id: str):
    path=tabulation_jobfile(job_id)
    if not path.is_file(): raise ValueError("Tabulação não encontrada.")
    state=read_job_state(path)
    if state.get("status") in {"queued","running"} and not job_worker_alive(state,path) and job_status_grace_elapsed(path):
        state.update(status="error",stage="Tabulação interrompida",message="A leitura parou de atualizar. Inicie a tabulação novamente.")
        state.pop("payload",None)
        write_tabulation_job(job_id,state)
    output={key:state.get(key) for key in ("id","status","progress","stage","message")}
    if state.get("status")=="done":
        result_path=path.with_suffix(".result.json")
        if not result_path.is_file(): raise ValueError("O resultado da tabulação não foi encontrado.")
        output["result"]=json.loads(result_path.read_text(encoding="utf-8"))
    return {"ok":True,**output}

def run_tabulation_worker(job_id: str):
    queued=read_job_state(tabulation_jobfile(job_id))
    sources=queued.get("active_sources") or []
    if not sources:
        data=queued.get("payload") or {}
        sources=[str(data.get("path") or "")]
        sources.extend(str(item.get("path") or "") for item in data.get("sources",[]) if isinstance(item,dict))
    sources=[safe_file(item).relative_to(UPLOADS).as_posix() for item in sources if item]
    with source_use_locks(sources):
        return _run_tabulation_worker_locked(job_id)

def _run_tabulation_worker_locked(job_id: str):
    path=tabulation_jobfile(job_id)
    state=read_job_state(path)
    payload=state.pop("payload")
    state["worker_pid"]=os.getpid()
    state["status"]="running"
    write_tabulation_job(job_id,state)
    try:
        def progress(pct,stage):
            state.update(status="running",progress=pct,stage=stage)
            write_tabulation_job(job_id,state)
        result=tabulate(payload,progress)
        result_path=path.with_suffix(".result.json")
        temporary=result_path.with_suffix(".json.part")
        try:
            temporary.write_text(json.dumps(result,ensure_ascii=True,default=str),encoding="utf-8")
            os.replace(temporary,result_path)
        finally:
            temporary.unlink(missing_ok=True)
        state.update(status="done",progress=100,stage="Tabulação concluída",message="Resultado pronto.")
        write_tabulation_job(job_id,state)
    except Exception as exc:
        state.update(status="error",stage="Não foi possível tabular",message=str(exc))
        write_tabulation_job(job_id,state)

def ensure_archive(system: str) -> Path:
    folder=UPLOADS/"DEFINICOES"/"originais"; folder.mkdir(parents=True,exist_ok=True)
    path=folder/f"TAB_{system}.zip"
    with interprocess_lock(folder/f"TAB_{system}.lock"):
        if not path.exists() or not 1000 <= path.stat().st_size <= 512*1024*1024:
            tmp=path.with_suffix(".zip.part")
            remote=f"/dissemin/publicos/{'SIASUS' if system=='SIA' else 'SIHSUS'}/200801_/Auxiliar/TAB_{system}.zip"
            try:
                try:
                    portal_download_file(remote, f"TAB_{system}.zip", tmp)
                except Exception as https_error:
                    if not ALLOW_FTP_FALLBACK:
                        raise RuntimeError(f"Não foi possível baixar as definições oficiais por HTTPS. O fallback FTP está desativado. Detalhe: {https_error}") from https_error
                    try:
                        ftp=FTP("ftp.datasus.gov.br",timeout=12); ftp.login(); ftp.set_pasv(True)
                        try:
                            written=0
                            with tmp.open("wb") as out:
                                def write_chunk(chunk):
                                    nonlocal written
                                    written+=len(chunk)
                                    if written>512*1024*1024: raise RuntimeError("O pacote de definições ultrapassou o limite permitido.")
                                    out.write(chunk)
                                ftp.retrbinary(f"RETR {remote}",write_chunk,blocksize=1024*1024)
                        finally:
                            try: ftp.quit()
                            except Exception: ftp.close()
                    except Exception as ftp_error:
                        raise RuntimeError(f"Não foi possível baixar as definições oficiais por HTTPS nem FTP. HTTPS: {https_error}; FTP: {ftp_error}") from ftp_error
                if not 1000 <= tmp.stat().st_size <= 512*1024*1024: raise RuntimeError("O pacote oficial de definições chegou incompleto ou excedeu o limite permitido.")
                with zipfile.ZipFile(tmp) as archive:
                    if len(archive.infolist())>50000: raise RuntimeError("O pacote de definições contém itens demais.")
                tmp.replace(path)
            finally:
                tmp.unlink(missing_ok=True)
    return path

def archive_def(system: str, kind: str):
    name=DEF_MAP.get(kind)
    if not name: return None,None
    archive=ensure_archive(system)
    with zipfile.ZipFile(archive) as z:
        matches=[item for item in z.infolist() if PurePosixPath(item.filename).name.lower()==name.lower()]
        if not matches: return name,None
        if len(matches)!=1 or matches[0].file_size>16*1024*1024: raise RuntimeError("A definição oficial contém um item inválido ou grande demais.")
        data=z.read(matches[0])
    dest=UPLOADS/"DEFINICOES"/system/name
    dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists() or dest.stat().st_size!=len(data): dest.write_bytes(data)
    return name,data

def parse_def(data: bytes, fields: list[dict[str,Any]]):
    text=data.decode("cp1252","replace")
    names={f["name"].upper() for f in fields}; rows=[]; increments=[]; selections=[]; group=None
    import csv, io
    for line_no,row in enumerate(csv.reader(io.StringIO(text), delimiter=",")):
        if not row: continue
        head=row[0].strip().lstrip("\ufeff")
        if not head or head.startswith((";","?","/")) or head.upper().startswith("ADADOS"): continue
        cmd=head[:1].upper(); label=head[1:].strip().strip('"')
        if len(row)==1 and cmd=="G":
            field=head[1:].strip().strip('"').upper()
            if field in names: group={"id":field,"label":field,"field":field,"command":"G"}
            continue
        if len(row)<2: continue
        field=row[1].strip().strip('"').upper()
        if cmd not in {"L","C","S","D","T","I","G"} or not field or field not in names: continue
        item={"id":f"{cmd}:{line_no}","label":label or field,"field":field,"command":cmd,"descField":row[2].strip().strip('"') if len(row)>2 else "","relation":row[3].strip().strip('"') if len(row)>3 else ""}
        if cmd in {"L","D","T"}: rows.append(item)
        if cmd=="I": increments.append(item)
        if cmd=="S": selections.append(item)
        if cmd=="G": group=item
    # Column definitions are C and T (T also line); increment fields are I.
    cols=[]
    for line_no,row in enumerate(csv.reader(io.StringIO(text), delimiter=",")):
        if row and row[0].strip() and row[0].strip()[:1].upper() in {"C","T"} and len(row)>=2:
            field=row[1].strip().strip('"').upper()
            if field in names: cols.append({"id":f"{row[0].strip()[:1].upper()}:{line_no}","label":row[0].strip()[1:].strip().strip('"') or field,"field":field,"command":row[0].strip()[:1].upper(),"descField":row[2].strip().strip('"') if len(row)>2 else "","relation":row[3].strip().strip('"') if len(row)>3 else ""})
    return rows,cols,selections,increments,group

def add_sp_identifier_options(kind: str, fields, rows):
    """Expose high-cardinality SP identifiers as row dimensions only."""
    if kind.upper()!="SP": return
    available={str(name).upper() for name in fields}
    for field,label in SP_EXTRA_DIMENSIONS:
        if field not in available: continue
        if any(item.get("field","").upper()==field for item in rows): continue
        rows.append({"id":f"EXTRA:{field}","label":label,"field":field,"command":"L","descField":"","relation":""})

def cnv_values(raw: bytes) -> dict[str,str]:
    lines=raw.decode("cp1252","replace").splitlines()
    result={}; ranges=[]
    for line in lines[1:]:
        if not line.strip(): continue
        label=line[9:59].strip() if len(line)>9 else ""
        codepart=line[60:].strip() if len(line)>60 else ""
        codes=[part.strip() for part in re.split(r"[,;]",codepart) if part.strip()]
        if not codes:
            tokens=line.split()
            codes=tokens[2:] if len(tokens)>2 else []
            label=" ".join(tokens[1:2]) if not label and len(tokens)>1 else label
        for code in codes:
            code=code.strip()
            match=re.fullmatch(r"([A-Za-z0-9]+)\s*-\s*([A-Za-z0-9]+)",code)
            if match:
                ranges.append((match.group(1),match.group(2),label or code)); continue
            result.setdefault(code,label or code)
            if len(code)>1: result.setdefault(code[:1],label or code)
    result["\x00ranges"]=ranges
    return result

def cnv_label(mapping: dict[str,Any], code: str):
    if code in mapping: return mapping[code]
    for start,end,label in mapping.get("\x00ranges",[]):
        try:
            if int(start)<=int(code)<=int(end): return label
        except ValueError:
            if len(start)==len(end)==len(code) and start<=code<=end: return label
    return code

def safe_archive_name(name: str):
    if not isinstance(name,str) or not name or len(name)>600 or "\x00" in name:
        return None
    normalized=name.replace("\\","/")
    posix=PurePosixPath(normalized); windows=PureWindowsPath(name)
    parts=normalized.split("/")
    if posix.is_absolute() or windows.is_absolute() or windows.drive or any(part in {"", ".", ".."} or ":" in part for part in parts):
        return None
    return normalized,parts

def relation_mapping(system: str, option):
    relation=(option or {}).get("relation","")
    safe_relation=safe_archive_name(relation)
    if safe_relation is None: return {}
    normalized_relation,relation_parts=safe_relation
    rel=PurePosixPath(normalized_relation)
    extension=rel.suffix.lower()
    if extension not in {".cnv",".dbf"}: return {}
    archive=UPLOADS/"DEFINICOES"/"originais"/f"TAB_{system}.zip"
    if not archive.is_file() or archive.stat().st_size>512*1024*1024: return {}
    target=cache_target("relation-mappings",{"archive":cache_file_identity(archive),"relation":relation.lower(),"descField":(option or {}).get("descField","")})
    cached=cache_read(target)
    if isinstance(cached,dict) and isinstance(cached.get("mapping"),dict): return cached["mapping"]
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        if len(infos)>50000: return {}
        normalized_infos=[]
        for info in infos:
            safe_name=safe_archive_name(info.filename)
            if safe_name is None or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16): continue
            normalized_infos.append((info,*safe_name))
        matches=[entry for entry in normalized_infos if entry[1].lower()==normalized_relation.lower()]
        if not matches:
            matches=[entry for entry in normalized_infos if PurePosixPath(entry[1]).name.lower()==rel.name.lower()]
        if len(matches)!=1: return {}
        info,member,member_parts=matches[0]
        if PurePosixPath(member).suffix.lower()!=extension: return {}
        maximum_size=64*1024*1024 if extension==".cnv" else 256*1024*1024
        if info.file_size>maximum_size or (info.compress_size>0 and info.file_size>max(info.compress_size*2000, 64*1024*1024)): return {}
        raw=z.read(info)
    reference_root=(UPLOADS/"DEFINICOES"/system/"referencias").resolve()
    out=reference_root.joinpath(*member_parts).resolve()
    if not out.is_relative_to(reference_root): return {}
    out.parent.mkdir(parents=True,exist_ok=True)
    if not out.is_file() or out.stat().st_size!=len(raw):
        fd,temporary=tempfile.mkstemp(prefix="relation-",suffix=".part",dir=str(out.parent))
        try:
            with os.fdopen(fd,"wb") as stream: stream.write(raw)
            os.replace(temporary,out)
        finally: Path(temporary).unlink(missing_ok=True)
    if extension==".cnv":
        mapping=cnv_values(raw)
        cache_write(target,{"mapping":mapping},max_bytes=20_000_000)
        return mapping
    if extension==".dbf":
        try:
            DBF=dbf_reader(); lookup=DBF(str(out),load=False,encoding="latin1",char_decode_errors="replace",ignore_missing_memofile=True)
            if not lookup.fields: return {}
            keyfield=lookup.fields[0].name
            desc=option.get("descField") or (lookup.fields[1].name if len(lookup.fields)>1 else keyfield)
            if desc.upper() not in {f.name.upper() for f in lookup.fields}: return {}
            mapping={str(row.get(keyfield) or "").strip():str(row.get(desc) or "").strip() for row in lookup}
            cache_write(target,{"mapping":mapping},max_bytes=20_000_000)
            return mapping
        except Exception: return {}
    return {}

def schema(relative: str):
    path=safe_file(relative); relative=path.relative_to(UPLOADS).as_posix(); system,kind,filename_match=meta(path)
    converted=safe_converted_path(relative)
    dbf_identity=cache_file_identity(converted) if converted.is_file() else None
    source_identity=cache_file_identity(path)
    archive=ensure_archive(system)
    definition_identity=cache_file_identity(archive)
    identity={"cacheVersion":1,"parser":"official-def-schema-v1","source":source_identity,"dbf":dbf_identity,"definition":definition_identity,"kind":kind,"system":system}
    target=cache_target("schemas",identity)
    with interprocess_lock(target.with_suffix(".lock")):
        cached=cache_read(target)
        cached_definition=cached.get("definition") if isinstance(cached,dict) else None
        if isinstance(cached,dict) and isinstance(cached_definition,dict) and cached.get("ok") is True and cached.get("sourceIdentity")==source_identity and cached_definition.get("identity")==definition_identity:
            return cached
        fields,records=dbc_header(path)
        defname,definition=archive_def(system,kind)
        if definition is None: raise RuntimeError(f"A definição {defname or 'do arquivo'} não foi encontrada no pacote oficial {system}.")
        rows,cols,selections,increments,group=parse_def(definition,fields)
        add_sp_identifier_options(kind,[f["name"] for f in fields],rows)
        relationFiles={item.get("relation", "").lower() for collection in (rows,cols,selections,increments) for item in collection if item.get("relation", "").lower().endswith(".cnv")}
        fieldnames={f["name"].upper() for f in fields}
        municipality=municipality_field(system,fieldnames)
        result={"ok":True,"file":{"path":relative,"name":path.name,"system":system,"kind":kind,"uf":filename_match.group("uf").upper()},"dbfPath":dbf_identity["path"] if dbf_identity else None,"dbfIdentity":dbf_identity,"sourceIdentity":source_identity,"definition":{"name":defname,"archive":f"uploads/DEFINICOES/originais/TAB_{system}.zip","size":len(definition),"identity":definition_identity,"relationFiles":len(relationFiles)},"fields":fields,"lineOptions":rows,"columnOptions":cols,"selectionOptions":selections,"increments":increments,"groupField":group,"municipalityField":municipality,"recordCount":records}
        cache_write(target,result,max_bytes=12_000_000,keep=100)
        return result

def preset_context(relative: str):
    path=safe_file(relative); system,kind,match=meta(path); fields,_=dbc_header(path)
    defname,definition=archive_def(system,kind)
    if definition is None: raise RuntimeError("A definição oficial deste arquivo não está disponível.")
    stable_fields=sorted(({key:str(field.get(key,"")) for key in ("name","type","length","decimals")} for field in fields),key=lambda field:field["name"].upper())
    uf=match.group("uf").upper()
    signature_data={"system":system,"kind":kind,"uf":uf,"definition":hashlib.sha256(definition).hexdigest(),"fields":stable_fields}
    signature=hashlib.sha256(json.dumps(signature_data,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()
    return {"signature":signature,"system":system,"kind":kind,"uf":uf,"definition":defname,"fields":fields,"file":{"path":relative,"name":path.name,"system":system,"kind":kind,"uf":uf}}

def preset_store_path():
    target=UPLOADS/".cache"/"saved-tabulations.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    return target

def repair_mojibake_text(value):
    if not isinstance(value,str) or not any(marker in value for marker in ("Ã","Â","â€","ðŸ")): return value
    try: candidate=value.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError,UnicodeDecodeError): return value
    markers=("Ã","Â","â€","ðŸ")
    if sum(candidate.count(marker) for marker in markers)<sum(value.count(marker) for marker in markers): return candidate
    return value

def read_preset_store():
    try:
        data=json.loads(preset_store_path().read_text(encoding="utf-8"))
        if not isinstance(data,dict) or not isinstance(data.get("items"),list): return {"version":1,"items":[]}
        changed=False
        for item in data["items"]:
            if not isinstance(item,dict): continue
            name=repair_mojibake_text(item.get("name"))
            if name!=item.get("name"):
                item["name"]=name
                changed=True
        return data
    except (OSError,ValueError,TypeError): return {"version":1,"items":[]}

def write_preset_store(data):
    target=preset_store_path(); raw=json.dumps(data,ensure_ascii=True,separators=(",",":"))
    fd,tmp=tempfile.mkstemp(prefix="saved-tabulations-",suffix=".part",dir=str(target.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream: stream.write(raw)
        Path(tmp).replace(target)
    finally: Path(tmp).unlink(missing_ok=True)

def validated_preset_options(relative: str, supplied):
    if not isinstance(supplied,dict): raise ValueError("A combinação não contém opções válidas.")
    context=preset_context(relative)
    defname,definition=archive_def(context["system"],context["kind"])
    rows,columns,selections,increments,group=parse_def(definition,context["fields"])
    add_sp_identifier_options(context["kind"],[field["name"] for field in context["fields"]],rows)
    row_ids={item["id"] for item in rows}; column_ids={item["id"] for item in columns}; selection_ids={item["id"] for item in selections}
    metric_ids={"FREQ","RECORDS",*(item["field"] for item in increments)}
    row=str(supplied.get("row") or "")
    column=str(supplied.get("column") or "")
    if row not in row_ids: raise ValueError("A linha escolhida não existe na definição atual.")
    if column and column not in column_ids: raise ValueError("A coluna escolhida não existe na definição atual.")
    metrics=supplied.get("metrics")
    if not isinstance(metrics,list) or not metrics or len(metrics)>50 or any(not isinstance(item,str) or item not in metric_ids for item in metrics): raise ValueError("As medidas salvas não são compatíveis com esta definição.")
    if len(set(metrics))>1 and column: raise ValueError("Para salvar mais de uma medida, deixe Colunas como Não ativa.")
    filters=supplied.get("filters",[])
    if not isinstance(filters,list) or len(filters)>300: raise ValueError("A combinação excede o limite de categorias selecionadas.")
    clean_filters=[]
    for item in filters:
        if not isinstance(item,dict): raise ValueError("Uma seleção salva está inválida.")
        option=str(item.get("option") or ""); value=str(item.get("value") or ""); mode=str(item.get("mode") or "")
        if option not in selection_ids or not value or len(value)>120 or mode not in {"include","exclude"}: raise ValueError("Uma seleção salva não é compatível com esta definição.")
        clean_filters.append({"option":option,"value":value,"mode":mode})
    column_filter=supplied.get("columnFilter")
    clean_column_filter=None
    if column_filter:
        if not isinstance(column_filter,dict): raise ValueError("O filtro de coluna salvo está inválido.")
        option=str(column_filter.get("option") or ""); value=str(column_filter.get("value") or "")
        if option!=column or option not in column_ids or not value or len(value)>120: raise ValueError("O filtro de coluna não é compatível com esta definição.")
        clean_column_filter={"option":option,"value":value}
    unclassified=str(supplied.get("unclassified") or "ignore")
    if unclassified not in {"ignore","include","discriminate"}: unclassified="ignore"
    sigtap_filters=supplied.get("sigtapFilters") or {}
    if not isinstance(sigtap_filters,dict) or len(sigtap_filters)>12 or any(not isinstance(key,str) or not isinstance(value,str) or len(key)>30 or len(value)>20 for key,value in sigtap_filters.items()):
        raise ValueError("O filtro SIGTAP da combinação é inválido.")
    clean={"row":row,"column":column,"metrics":list(dict.fromkeys(metrics)),"filters":clean_filters,"columnFilter":clean_column_filter,"suppressRows":bool(supplied.get("suppressRows",True)),"suppressColumns":bool(supplied.get("suppressColumns",True)),"testCrc":bool(supplied.get("testCrc",False)),"saveRecords":bool(supplied.get("saveRecords",False)),"unclassified":unclassified,"municipalityFilter":bool(supplied.get("municipalityFilter",False)),"sigtapFilters":sigtap_filters}
    option_by_id={item["id"]:item for group_items in (rows,columns,selections) for item in group_items}
    metric_labels={"FREQ":f"Frequência · {group.get('field') if group else 'registros'}","RECORDS":"Número de registros"}
    metric_labels.update({item["field"]:item["label"] for item in increments})
    return context,clean,{"rowLabel":option_by_id[row]["label"],"columnLabel":option_by_id[column]["label"] if column else "Não ativa","metricLabels":[metric_labels.get(item,item) for item in clean["metrics"]],"filterCount":len(clean_filters)}

def saved_presets(relative: str):
    context=preset_context(relative)
    items=[item for item in read_preset_store()["items"] if isinstance(item,dict) and item.get("signature")==context["signature"]]
    items.sort(key=lambda item:float(item.get("updatedAt",item.get("createdAt",0)) or 0),reverse=True)
    return {"ok":True,"file":context["file"],"system":context["system"],"kind":context["kind"],"uf":context["uf"],"definition":context["definition"],"presets":items[:250]}

def save_preset(payload):
    relative=str(payload.get("path") or ""); name=" ".join(repair_mojibake_text(str(payload.get("name") or "")).split())
    if not name or len(name)>80: raise ValueError("Dê um nome com até 80 caracteres para a combinação.")
    context,options,summary=validated_preset_options(relative,payload.get("options"))
    with interprocess_lock(UPLOADS/".jobs"/"storage.lock"):
        store=read_preset_store(); items=[item for item in store["items"] if isinstance(item,dict)]
        if len(items)>=250: raise ValueError("O limite de 250 combinações salvas foi atingido.")
        now=time.time()
        item={"id":secrets.token_hex(12),"name":name,"createdAt":now,"updatedAt":now,"signature":context["signature"],"system":context["system"],"kind":context["kind"],"uf":context["uf"],"definition":context["definition"],"options":options,**summary}
        items.append(item); write_preset_store({"version":1,"items":items})
    return {"ok":True,"preset":item}

def get_preset(payload):
    context=preset_context(str(payload.get("path") or "")); preset_id=str(payload.get("preset_id") or "")
    item=next((entry for entry in read_preset_store()["items"] if isinstance(entry,dict) and entry.get("id")==preset_id and entry.get("signature")==context["signature"]),None)
    if not item: raise ValueError("Esta combinação não é compatível com o arquivo selecionado ou foi removida.")
    _,options,_=validated_preset_options(str(payload.get("path") or ""),item.get("options"))
    return {"ok":True,"preset":{"id":item["id"],"name":item["name"],"options":options}}

def delete_preset(payload):
    context=preset_context(str(payload.get("path") or "")); preset_id=str(payload.get("preset_id") or "")
    with interprocess_lock(UPLOADS/".jobs"/"storage.lock"):
        store=read_preset_store(); items=[item for item in store["items"] if isinstance(item,dict)]
        kept=[item for item in items if not (item.get("id")==preset_id and item.get("signature")==context["signature"])]
        if len(kept)==len(items): raise ValueError("A combinação não foi encontrada para este tipo de arquivo.")
        write_preset_store({"version":1,"items":kept})
    return {"ok":True,"deleted":1}

def category_values(payload):
    raw_sources=payload.get("sources")
    if raw_sources is None: raw_sources=[{"path":payload.get("path",""),"dbfPath":payload.get("dbfPath")}]
    if not isinstance(raw_sources,list) or not 1<=len(raw_sources)<=100: raise ValueError("A lista de bases para carregar filtros é inválida.")
    sources=[]
    for entry in raw_sources:
        if not isinstance(entry,dict): raise ValueError("Uma das bases selecionadas é inválida.")
        relative=str(entry.get("path") or ""); source=safe_file(relative); current_system,current_kind,filename_match=meta(source); current_uf=filename_match.group("uf").upper()
        if sources and (current_system,current_kind,current_uf)!=(sources[0]["system"],sources[0]["kind"],sources[0]["uf"]): raise ValueError("Os filtros precisam pertencer à mesma família de arquivos.")
        canonical_relative=source.relative_to(UPLOADS).as_posix()
        path=safe_dbf(entry.get("dbfPath") or converted_relative(canonical_relative),canonical_relative)
        _,_,_,current_fields=dbf_layout(path)
        if sources and (set(current_fields)!=set(sources[0]["fields"]) or any((current_fields[name]["type"],current_fields[name]["length"],current_fields[name]["decimals"])!=(info["type"],info["length"],info["decimals"]) for name,info in sources[0]["fields"].items())): raise ValueError(f"O arquivo {source.name} possui campos diferentes dos demais selecionados.")
        sources.append({"source":source,"path":path,"system":current_system,"kind":current_kind,"uf":current_uf,"fields":current_fields})
    system,kind=sources[0]["system"],sources[0]["kind"]
    fields=sources[0]["fields"]
    defname,definition=archive_def(system,kind)
    if definition is None: raise RuntimeError("Definição oficial indisponível para este arquivo.")
    lines,columns,selections,_,_=parse_def(definition,[{"name":name,**info} for name,info in fields.items()])
    add_sp_identifier_options(kind,fields.keys(),lines)
    groups={"line":lines,"column":columns,"selection":selections}
    option_type=str(payload.get("optionType","column"))
    if option_type not in groups: raise ValueError("Tipo de categoria inválido.")
    option=next((item for item in groups[option_type] if item["id"]==payload.get("option")),None)
    if not option: raise ValueError("Escolha uma variável disponível na definição.")
    field=option["field"]
    munfield=municipality_field(system,fields)
    municipality=municipality_code(payload,fields,munfield)
    usemun=bool(municipality)
    archive=UPLOADS/"DEFINICOES"/"originais"/f"TAB_{system}.zip"
    identity={"cacheVersion":8,"dbfs":[cache_file_identity(item["path"]) for item in sources],"option":option["id"],"type":option_type,"municipalityCode":municipality,"definition":cache_file_identity(archive) if archive.is_file() else defname}
    target=cache_target("category-values",identity)
    with interprocess_lock(target.with_suffix(".lock")):
        cached=cache_read(target)
        if cached is not None: return cached
        names=[field]
        values=set(); truncated=False
        for item in sources:
            for record in iter_dbf_fields(item["path"],names,pre_filter=(munfield,municipality) if usemun else None):
                value=record[0]
                if not value: continue
                if value not in values:
                    if len(values)>=5000: truncated=True
                    else: values.add(value)
        mapping=relation_mapping(system,option)
        ordered=sorted(values,key=lambda value:(cnv_label(mapping,value).casefold(),value))
        result={"ok":True,"option":option["id"],"optionType":option_type,"field":field,"values":[{"value":value,"label":cnv_label(mapping,value)} for value in ordered],"truncated":truncated}
        cache_write(target,result)
        return result

def column_values(payload):
    payload={**payload,"optionType":"column"}
    return category_values(payload)

def category_is_classified(mapping: dict[str,Any], code: str) -> bool:
    if not mapping: return True
    if code in mapping: return True
    for start,end,_label in mapping.get("\x00ranges",[]):
        try:
            if int(start)<=int(code)<=int(end): return True
        except ValueError:
            if len(start)==len(end)==len(code) and start<=code<=end: return True
    return False

def verify_dbc_against_dbf(source: Path, dbf: Path):
    """Re-expand a DBC and compare the DBF records to the converted copy."""
    import hashlib
    expanded=Path(decompress(source))
    try:
        _,head_a,record_a,_=dbf_layout(expanded)
        _,head_b,record_b,_=dbf_layout(dbf)
        if head_a!=head_b or record_a!=record_b: raise ValueError(f"A verificação de integridade falhou para {source.name}: estrutura DBF diferente.")
        def digest(path,offset):
            value=hashlib.sha256()
            with path.open("rb") as stream:
                stream.seek(offset)
                for chunk in iter(lambda:stream.read(1024*1024),b""): value.update(chunk)
            return value.digest()
        if digest(expanded,head_a)!=digest(dbf,head_b): raise ValueError(f"A verificação de integridade falhou para {source.name}: os registros do DBC não correspondem ao DBF convertido.")
    finally: expanded.unlink(missing_ok=True)

def save_dbf_records(source_dbfs: list[Path], indexes_by_file: list[list[int]], token: str):
    target=UPLOADS/"RESULTADOS"/(token+".dbf")
    target.parent.mkdir(parents=True,exist_ok=True)
    total_records=sum(map(len,indexes_by_file))
    with source_dbfs[0].open("rb") as inp:
        header=bytearray(inp.read(32))
        header_len=int.from_bytes(header[8:10],"little")
        record_len=int.from_bytes(header[10:12],"little")
        inp.seek(0); full_header=bytearray(inp.read(header_len))
        full_header[4:8]=total_records.to_bytes(4,"little")
        with target.open("wb") as out:
            out.write(full_header)
            for dbf,indexes in zip(source_dbfs,indexes_by_file):
                with dbf.open("rb") as current:
                    _,current_header,current_record,_=dbf_layout(dbf)
                    if current_header!=header_len or current_record!=record_len: raise ValueError("Os DBFs selecionados não têm a mesma estrutura.")
                    for index in indexes:
                        current.seek(header_len+index*record_len)
                        record=current.read(record_len)
                        if len(record)!=record_len: raise ValueError("Não foi possível salvar todos os registros selecionados.")
                        out.write(record)
            out.write(b"\x1a")
    return target

def _report_code(value: str, width: int) -> str:
    digits=re.sub(r"\D", "", str(value or ""))
    return digits.zfill(width)[-width:] if digits else ""

def _report_relation_index(mapping: dict[str,Any], width: int) -> dict[str,str]:
    result={}
    for code,label in mapping.items():
        if not isinstance(code,str) or code.startswith("\x00"):
            continue
        normalized=_report_code(code,width)
        if normalized:
            result.setdefault(normalized,str(label or "").strip())
    return result

def _report_exact_relation_index(mapping: dict[str,Any], width: int) -> dict[str,str]:
    """Use official fixed-width alphanumeric codes, excluding CNV prefix aliases."""
    result={}
    pattern=re.compile(rf"\A[A-Za-z0-9]{{{width}}}\Z")
    for code,label in mapping.items():
        if isinstance(code,str) and pattern.fullmatch(code):
            result.setdefault(code,str(label or "").strip())
    return result

def _report_definition_options(definition: bytes) -> list[dict[str,str]]:
    import csv, io
    result=[]
    for row in csv.reader(io.StringIO(definition.decode("cp1252","replace")),delimiter=","):
        if len(row)<4: continue
        field=row[1].strip().strip('"').upper()
        relation=row[3].strip().strip('"').replace("\\","/")
        if field and relation:
            result.append({"field":field,"descField":row[2].strip().strip('"'),"relation":relation})
    return result

def _report_filter_categories(mapping: dict[str,Any], width: int) -> list[dict[str,str]]:
    categories=[{"value":code,"label":_report_label(label)} for code,label in _report_exact_relation_index(mapping,width).items() if _report_label(label)]
    seen={item["value"] for item in categories}
    for start,end,label in mapping.get("\x00ranges",[]):
        start=str(start).strip().upper().zfill(width); end=str(end).strip().upper().zfill(width)
        if not re.fullmatch(rf"\d{{{width}}}",start) or not re.fullmatch(rf"\d{{{width}}}",end) or int(start)>int(end): continue
        value=f"__RANGE__:{start}:{end}"
        clean=_report_label(label)
        if value not in seen and clean:
            seen.add(value); categories.append({"value":value,"label":clean})
    categories.sort(key=lambda item:(item["label"].casefold(),item["value"]))
    return categories

def _report_expand_filter_values(raw_values, spec: dict[str,Any], mapping: dict[str,Any]) -> list[str]:
    if isinstance(raw_values,(str,int,float)): raw_values=[raw_values]
    if not isinstance(raw_values,(list,tuple)) or len(raw_values)>500:
        raise ValueError(f"O filtro {spec['label'].lower()} é inválido.")
    width=int(spec["width"]); valid_exact=_report_exact_relation_index(mapping,width); selected=set()
    pattern=re.compile(rf"\A[A-Za-z0-9]{{1,{width}}}\Z")
    for raw_value in raw_values:
        raw=str(raw_value or "").strip().upper()
        if not raw: continue
        if raw.startswith("__RANGE__:"):
            match=re.fullmatch(rf"__RANGE__:(\d{{{width}}}):(\d{{{width}}})",raw)
            if not match: raise ValueError(f"O filtro {spec['label'].lower()} é inválido.")
            start,end=match.groups()
            official_ranges={(str(a).zfill(width),str(b).zfill(width)) for a,b,_ in mapping.get("\x00ranges",[])}
            if (start,end) not in official_ranges or int(end)-int(start)>20000:
                raise ValueError(f"A categoria selecionada em {spec['label'].lower()} não consta na definição oficial.")
            for number in range(int(start),int(end)+1):
                code=str(number).zfill(width)
                if code not in valid_exact: selected.add(code)
        else:
            if not pattern.fullmatch(raw): raise ValueError(f"O filtro {spec['label'].lower()} é inválido.")
            code=raw.zfill(width)
            if not category_is_classified(mapping,code):
                raise ValueError(f"Uma das categorias de {spec['label'].lower()} não consta na definição oficial desta base.")
            selected.add(code)
        if len(selected)>20000: raise ValueError(f"A seleção de {spec['label'].lower()} ficou ampla demais. Escolha menos categorias.")
    return sorted(selected)

def _report_label(value: Any) -> str:
    """Clean a few legacy DATASUS relation-table encoding artifacts for display."""
    label=repair_mojibake_text(str(value or "")).strip()
    label=label.replace("\u00b6\u00dd","ª").replace("¦","ª").replace("\ufffd","ª")
    label=label.replace("Jo\u0084o","João").replace("JO\u0084O","JOÃO").replace("Jo\ufffdo","João")
    label=re.sub(r"\s*\?\s*(?=\d+\s*ª?\s+LINHA)"," – ",label,flags=re.I)
    label=re.sub(r"(\d+)[\u00b6\u00dd¦\ufffd]+(?=\s+LINHA)",r"\1ª",label,flags=re.I)
    label=re.sub(r"[\x00-\x1f\x7f-\x9f]+"," ",label)
    return re.sub(r"\s+"," ",label).strip()

def predefined_filter_options(payload: dict[str,Any]):
    """Return optional filters backed by official categories in the SIA definition."""
    if payload.get("report") in {"sinan-dengue","sinan-chikungunya","sinan-zika"}:
        return {"ok":True,"uf":"PA",
            "cnesManagementTypes":[
                {"value":"MUNICIPAL","label":"Gestão municipal"},
                {"value":"ESTADUAL","label":"Gestão estadual"},
                {"value":"DUPLA","label":"Dupla gestão"},
                {"value":"NAO_INFORMADA","label":"Gestão não identificada"},
            ],
            "cnesNatureGroups":[
                {"value":"PUBLICO","label":"Natureza pública"},
                {"value":"PRIVADO","label":"Natureza privada"},
                {"value":"SEM_FINS_LUCRATIVOS","label":"Sem fins lucrativos"},
                {"value":"PESSOA_FISICA","label":"Pessoa física"},
                {"value":"OUTROS","label":"Outras naturezas"},
                {"value":"NAO_INFORMADA","label":"Natureza não identificada"},
            ]}
    if payload.get("report")=="sih-rd-producao":
        return predefined_sih_filter_options(payload)
    if payload.get("report")=="sih-rd-rejeicoes":
        return predefined_sih_filter_options(payload)
    if payload.get("report")=="sih-rd-fluxo":
        return predefined_sih_filter_options(payload)
    if payload.get("report")=="sih-rd-ocupacao":
        return predefined_sih_occupancy_filter_options(payload)
    if payload.get("report")=="sih-sp-profissionais":
        return predefined_sih_sp_filter_options(payload)
    if payload.get("report")=="sim-mortalidade-infantil":
        causes=_sim_cid_names()
        sim_causes=[{"value":code,"label":f"{code} · {name}"} for code,name in sorted(causes.items()) if re.fullmatch(r"[A-Z]\d{2}",str(code)) and str(name).strip()]
        sim_causes.append({"value":"NI","label":"Não informada · sem código CID-10"})
        return {"ok":True,"simCauses":sim_causes}
    uf=str(payload.get("uf") or "").strip().upper()
    if uf not in PREDEFINED_UF_CODES:
        raise ValueError("Selecione uma unidade da Federação válida.")
    archive_path=ensure_archive("SIA")
    cache=cache_target("predefined-filter-options",{"version":4,"archive":cache_file_identity(archive_path),"uf":uf})
    cached=cache_read(cache)
    if isinstance(cached,dict) and cached.get("ok") is True:
        return cached
    _,definition=archive_def("SIA","PA")
    if definition is None:
        raise RuntimeError("A definição oficial da produção ambulatorial não está disponível.")
    fields=[{"name":spec["field"]} for spec in PREDEFINED_FILTER_SPECS]
    rows,columns,selections,_,_=parse_def(definition,fields)
    options=rows+columns+selections
    result={"ok":True,"uf":uf}
    for spec in PREDEFINED_FILTER_SPECS:
        option=next((item for item in options if item.get("field")==spec["field"] and item.get("relation","").lower()==spec["relation"].lower()),None)
        if option is None and spec.get("auxiliaryRelation"):
            # PA_TPFIN is marked as an auxiliary field in the official DEF,
            # so its relation must be resolved directly from the official CNV.
            option={"field":spec["field"],"relation":spec["relation"]}
        mapping=relation_mapping("SIA",option) if option else {}
        exact=_report_exact_relation_index(mapping,spec["width"])
        prefix=PREDEFINED_UF_CODES[uf]
        categories=[]
        for code,label in exact.items():
            if not label or (spec.get("stateScoped") and not code.startswith(prefix)): continue
            clean_label=_report_label(label)
            if spec.get("stateScoped") and not clean_label.startswith(code):
                clean_label=re.sub(r"^\d{6}\s*[·-]?\s*","",clean_label)
                clean_label=f"{code} · {clean_label}"
            categories.append({"value":code,"label":clean_label})
        categories.sort(key=lambda item:(item["label"].casefold(),item["value"]))
        result[spec["response"]]=categories
    cache_write(cache,result,max_bytes=5_000_000,keep=32)
    return result

def predefined_sih_filter_options(payload: dict[str,Any]):
    """Return optional hospital report filters from the official RD definition."""
    uf=str(payload.get("uf") or "").strip().upper()
    if uf not in PREDEFINED_UF_CODES:
        raise ValueError("Selecione uma unidade da Federação válida.")
    archive_path=ensure_archive("SIH")
    cache=cache_target("predefined-sih-filter-options",{"version":2,"archive":cache_file_identity(archive_path),"uf":uf})
    cached=cache_read(cache)
    if isinstance(cached,dict) and cached.get("ok") is True:
        return cached
    _,definition=archive_def("SIH","RD")
    if definition is None:
        raise RuntimeError("A definição oficial de AIH reduzida não está disponível.")
    options=_report_definition_options(definition)
    result={"ok":True,"uf":uf}
    prefix=PREDEFINED_UF_CODES[uf]
    for spec in PREDEFINED_SIH_FILTER_SPECS:
        option=next((item for item in options if item.get("field")==spec["field"] and item.get("relation","").lower()==spec["relation"].lower()),None)
        mapping=relation_mapping("SIH",option) if option else {}
        categories=_report_filter_categories(mapping,spec["width"])
        if spec.get("stateScoped"):
            categories=[item for item in categories if item["value"].startswith(prefix)]
        result[spec["response"]]=categories
    cache_write(cache,result,max_bytes=5_000_000,keep=32)
    return result

def predefined_sih_occupancy_filter_options(payload: dict[str,Any]):
    """Expose the hospital-definition filters plus the official bed specialty."""
    uf=str(payload.get("uf") or "").strip().upper()
    if uf not in PREDEFINED_UF_CODES:
        raise ValueError("Selecione uma unidade da Federação válida.")
    archive_path=ensure_archive("SIH")
    cache=cache_target("predefined-sih-occupancy-filter-options",{"version":4,"archive":cache_file_identity(archive_path),"uf":uf})
    cached=cache_read(cache)
    if isinstance(cached,dict) and cached.get("ok") is True:
        return cached
    _,definition=archive_def("SIH","RD")
    if definition is None:
        raise RuntimeError("A definição oficial de AIH reduzida não está disponível.")
    options=_report_definition_options(definition)
    result={"ok":True,"uf":uf}
    prefix=PREDEFINED_UF_CODES[uf]
    for spec in PREDEFINED_SIH_OCCUPANCY_FILTER_SPECS:
        option=next((item for item in options if item.get("field")==spec["field"] and item.get("relation","").lower()==spec["relation"].lower()),None)
        mapping=relation_mapping("SIH",option) if option else {}
        categories=_report_filter_categories(mapping,spec["width"])
        if spec.get("stateScoped"):
            categories=[item for item in categories if item["value"].startswith(prefix)]
        result[spec["response"]]=categories
    cache_write(cache,result,max_bytes=5_000_000,keep=32)
    return result

def predefined_sih_sp_filter_options(payload: dict[str,Any]):
    """Return SIH/SP filters plus CNES dimensions missing from the SP file."""
    uf=str(payload.get("uf") or "").strip().upper()
    if uf not in PREDEFINED_UF_CODES:
        raise ValueError("Selecione uma unidade da Federação válida.")
    archive_path=ensure_archive("SIH")
    cache=cache_target("predefined-sih-sp-filter-options",{"version":7,"archive":cache_file_identity(archive_path),"uf":uf})
    cached=cache_read(cache)
    if isinstance(cached,dict) and cached.get("ok") is True:
        return cached
    _,definition=archive_def("SIH","SP")
    if definition is None:
        raise RuntimeError("A definição oficial dos serviços profissionais (SP) não está disponível.")
    options=_report_definition_options(definition)
    result={"ok":True,"uf":uf}
    prefix=PREDEFINED_UF_CODES[uf]
    for spec in PREDEFINED_SIH_SP_FILTER_SPECS:
        option=next((item for item in options if item.get("field")==spec["field"] and item.get("relation","").lower()==spec["relation"].lower()),None)
        mapping=relation_mapping("SIH",option) if option else {}
        categories=_report_filter_categories(mapping,spec["width"])
        if spec["key"]=="professionalCbo":
            unique={}
            for item in categories:
                code=re.sub(r"\D","",item["value"])
                if not re.fullmatch(r"\d{6}",code) or code in unique: continue
                unique[code]={"value":code,"label":item["label"]}
            categories=sorted(unique.values(),key=lambda item:(item["label"].casefold(),item["value"]))
        if spec.get("stateScoped"):
            categories=[item for item in categories if item["value"].startswith(prefix)]
        result[spec["response"]]=categories
    result["cnesManagementTypes"]=[
        {"value":"MUNICIPAL","label":"Municipal"},
        {"value":"ESTADUAL","label":"Estadual"},
        {"value":"DUPLA","label":"Dupla"},
        {"value":"NAO_INFORMADA","label":"Não informada no CNES"},
    ]
    result["cnesNatureGroups"]=[
        {"value":"PUBLICO","label":"Público"},
        {"value":"PRIVADO","label":"Privado"},
        {"value":"SEM_FINS_LUCRATIVOS","label":"Sem fins lucrativos"},
        {"value":"PESSOA_FISICA","label":"Pessoa física"},
        {"value":"OUTROS","label":"Outros tipos de natureza jurídica"},
        {"value":"NAO_INFORMADA","label":"Não informada no CNES"},
    ]
    _,rd_definition=archive_def("SIH","RD")
    rd_options=_report_definition_options(rd_definition) if rd_definition else []
    nature_option=next((item for item in rd_options if item.get("field")=="NAT_JUR" and item.get("relation","").lower()=="cnv/natjur.cnv"),None)
    nature_mapping=relation_mapping("SIH",nature_option) if nature_option else {}
    result["cnesLegalNatures"]=_report_filter_categories(nature_mapping,4)
    result["cnesHospitalSUS"]=[
        {"value":"SIM","label":"Sim · possui atendimento hospitalar SUS"},
        {"value":"NAO","label":"Não · sem atendimento hospitalar SUS"},
        {"value":"NAO_INFORMADO","label":"Sem informação no CNES atual"},
    ]
    cache_write(cache,result,max_bytes=5_000_000,keep=32)
    return result

def _sigtap_unmatched_codes(dbf: Path, field: str, competence: str, version: str) -> dict[str,Any]:
    """Audit distinct source codes against the complete SIGTAP table, not the chosen subset."""
    target=cache_target("sigtap-unmatched",{"dbf":cache_file_identity(dbf),"field":field,"competence":competence,"version":version})
    cached=cache_read(target)
    if isinstance(cached,dict) and "count" in cached: return cached
    published,_=sigtap_matching_codes(competence,{})
    missing=set()
    for (raw,) in iter_dbf_fields(dbf,[field]):
        code=_report_code(raw,10)
        if code and code not in published: missing.add(code)
    result={"count":len(missing),"codes":sorted(missing)[:30],"truncated":len(missing)>30}
    cache_write(target,result,max_bytes=5000,keep=100)
    return result


def _sigtap_procedure_filter(payload: dict[str,Any], year: int, month: int, fields: set[str] | dict, field: str, dbf: Path | None=None):
    """Return an exact-competence DBF prefilter; codes are unique before scanning."""
    selected=payload.get("sigtapFilters") or {}
    if not isinstance(selected,dict): raise ValueError("O filtro SIGTAP é inválido.")
    if not selected: return None,None
    if field not in fields: raise ValueError(f"Esta base não possui {field} para cruzar com o SIGTAP.")
    if len(selected)>12: raise ValueError("Selecione menos atributos SIGTAP.")
    competence=f"{year:04d}{month:02d}"
    try:
        codes,status=sigtap_matching_codes(competence,selected)
    except Exception as exc:
        raise ValueError(f"Não foi possível obter o SIGTAP da competência {month:02d}/{year} para o cruzamento: {exc}") from exc
    if dbf is not None:
        status={**status,"unmatched":_sigtap_unmatched_codes(dbf,field,competence,status["sha256"]),"unmatchedSource":dbf.name}
    return (field,sorted(codes) if codes else ["!"]),{**status,"matchingCodes":len(codes)}


def _attach_sigtap_source(result: dict[str,Any], status: dict[str,Any] | None):
    if not status: return
    result["sigtapSource"]=status
    month=status["competence"]
    message=f"Filtro SIGTAP: {status['matchingCodes']:,} código(s) elegível(is) na competência {month[4:6]}/{month[:4]}; tabela carregada em {status['loadedAt']}.".replace(",",".")
    unmatched=status.get("unmatched") or {}
    if unmatched.get("count"):
        message+=f" A base {status.get('unmatchedSource','consultada')} contém {unmatched['count']} código(s) de procedimento sem correspondência nessa competência: {', '.join(unmatched['codes'])}{' e outros' if unmatched.get('truncated') else ''}. Esses registros não entraram no recorte SIGTAP."
    elif unmatched:
        message+=" Todos os códigos de procedimento dessa base têm correspondência no SIGTAP da competência."
    other=status.get("unmatchedOther") or {}
    if other.get("count"):
        message+=f" A base {status.get('unmatchedOtherSource','adicional')} contém {other['count']} código(s) sem correspondência: {', '.join(other['codes'])}{' e outros' if other.get('truncated') else ''}."
    if status.get("warning"): message+=f" {status['warning']}"
    result.setdefault("notes",[]).append(message)


def _sinan_code(value: Any) -> str:
    raw=str(value or "").strip().lower()
    if raw in {"", "nan", "none", "null", "na"}: return ""
    return raw[:-2] if re.fullmatch(r"\d+\.0",raw) else raw

SINAN_DENGUE_ARCHIVE_HOST="s3.sa-east-1.amazonaws.com"
SINAN_DENGUE_ARCHIVE_MAX_BYTES=512*1024*1024
SINAN_DENGUE_CSV_MAX_BYTES=2*1024*1024*1024
SINAN_AGRAVOS={
    "sinan-dengue":{"folder":"Dengue","prefix":"DENG","icd":"a90","label":"dengue"},
    "sinan-chikungunya":{"folder":"Chikungunya","prefix":"CHIK","icd":"a920","label":"chikungunya"},
    "sinan-zika":{"folder":"Zikavirus","prefix":"ZIKA","icd":"a928","label":"Zika"},
}

def _sinan_dengue_archive(year: int, report_id: str="sinan-dengue", progress=None):
    """Download an approved annual public-health bundle from its fixed HTTPS source."""
    year_code=f"{year % 100:02d}"
    source_name="SIM" if report_id=="sim-mortalidade" else "SINAN"
    config=SINAN_AGRAVOS.get(report_id)
    if report_id=="sim-mortalidade":
        filename=f"Mortalidade_Geral_{year}_csv.zip"
        member_name=f"Mortalidade_Geral_{year}.csv"
        url=f"https://{SINAN_DENGUE_ARCHIVE_HOST}/ckan.saude.gov.br/SIM/csv/{filename}"
    else:
        if config is None: raise ValueError("Fonte oficial não reconhecida.")
        filename=f"{config['prefix']}BR{year_code}.csv.zip"
        member_name=f"{config['prefix']}BR{year_code}.csv"
        url=f"https://{SINAN_DENGUE_ARCHIVE_HOST}/ckan.saude.gov.br/SINAN/{config['folder']}/csv/{filename}"
    folder=UPLOADS/".cache"/"sinan-source"
    folder.mkdir(parents=True,exist_ok=True)
    for old in folder.glob("sinan-*.zip.part"):
        try:
            if time.time()-old.stat().st_mtime>86400: old.unlink(missing_ok=True)
        except OSError: pass

    def archive_date(headers):
        raw=headers.get("Last-Modified")
        if raw:
            try: return parsedate_to_datetime(raw).date().isoformat()
            except (TypeError,ValueError,OverflowError): pass
        return date.today().isoformat()

    expected_size=0
    fd,temp_name=tempfile.mkstemp(prefix="sinan-",suffix=".zip.part",dir=str(folder))
    os.close(fd)
    temp_path=Path(temp_name)
    try:
        request=urllib.request.Request(url,headers={"User-Agent":"TabulaSUS/1.0","Accept":"application/zip"})
        downloaded=0
        with open_verified_https(request,SINAN_DENGUE_ARCHIVE_HOST,120) as response, temp_path.open("wb") as output:
            expected_size=int(response.headers.get("Content-Length") or 0)
            updated_at=archive_date(response.headers)
            if expected_size>SINAN_DENGUE_ARCHIVE_MAX_BYTES: raise ValueError(f"O arquivo anual do {source_name} ultrapassa o limite seguro de download.")
            if shutil.disk_usage(folder).free<(expected_size or 32*1024*1024)+16*1024*1024:
                raise ValueError(f"Não há espaço livre suficiente para baixar o arquivo anual do {source_name}.")
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                downloaded+=len(chunk)
                if downloaded>SINAN_DENGUE_ARCHIVE_MAX_BYTES or (expected_size and downloaded>expected_size):
                    raise ValueError(f"O arquivo anual do {source_name} ultrapassou o tamanho informado pelo servidor.")
                output.write(chunk)
                if progress:
                    percent=10+int(20*downloaded/expected_size) if expected_size else 10
                    size_label=f"{downloaded/1024/1024:.1f} MB"+(f" de {expected_size/1024/1024:.1f} MB" if expected_size else "")
                    progress(min(30,percent),f"Baixando arquivo anual do {source_name} · {size_label}")
        if expected_size and downloaded!=expected_size: raise ValueError(f"O download do {source_name} terminou antes de o arquivo ser recebido por completo.")
        with zipfile.ZipFile(temp_path) as bundle:
            if len(bundle.infolist())>1000: raise ValueError(f"O pacote oficial do {source_name} contém itens demais.")
            members=[entry for entry in bundle.infolist() if not entry.is_dir() and entry.filename.replace("\\","/").rsplit("/",1)[-1].casefold()==member_name.casefold()]
            if len(members)!=1 or not 0<members[0].file_size<=SINAN_DENGUE_CSV_MAX_BYTES:
                raise ValueError(f"O pacote oficial do {source_name} está incompleto ou não contém o CSV esperado para este ano.")
        return temp_path,updated_at
    except urllib.error.HTTPError as exc:
        temp_path.unlink(missing_ok=True)
        if exc.code==404: raise ValueError(f"O arquivo anual oficial de {config['label'] if config else 'mortalidade'} do {source_name} ainda não está disponível para {year}.") from exc
        raise ValueError(f"O servidor oficial do {source_name} respondeu com erro HTTP {exc.code}.") from exc
    except (OSError,TimeoutError,urllib.error.URLError) as exc:
        temp_path.unlink(missing_ok=True)
        raise ValueError(f"Não foi possível baixar o arquivo anual oficial do {source_name}. {exc}") from exc
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

def _sinan_json_request(url: str, host: str, timeout: int=35, max_bytes: int=16*1024*1024):
    request=urllib.request.Request(url,headers={"User-Agent":"TabulaSUS/1.0","Accept":"application/json"})
    with open_verified_https(request,host,timeout) as response:
        body=response.read(max_bytes+1)
        if len(body)>max_bytes: raise ValueError("A fonte oficial retornou uma resposta maior que o limite seguro.")
        encoding=str(response.headers.get("Content-Encoding") or "").strip().lower()
    if "gzip" in encoding:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                body=compressed.read(max_bytes+1)
            if len(body)>max_bytes: raise ValueError("A fonte oficial retornou uma resposta descompactada maior que o limite seguro.")
        except (OSError,EOFError) as exc: raise ValueError("A fonte oficial retornou um pacote gzip inválido.") from exc
    elif encoding and encoding not in {"identity"}:
        raise ValueError("A fonte oficial retornou uma compactação não reconhecida.")
    try: return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError,ValueError) as exc: raise ValueError("A fonte oficial respondeu em um formato inesperado.") from exc

def _sinan_ibge_municipalities():
    target=cache_target("sinan_ibge_municipalities",{"version":2})
    cached=cache_read(target)
    names={}
    local_folder=UPLOADS/".cache"/"municipalities"
    local_paths=local_folder.glob("*.json") if local_folder.is_dir() else ()
    for local_path in local_paths:
        local=cache_read(local_path)
        options=local.get("municipalities") if isinstance(local,dict) else None
        if not isinstance(options,list): continue
        for item in options:
            if not isinstance(item,dict): continue
            raw_code=str(item.get("code") or item.get("ibge_id") or "")
            code=re.sub(r"\D","",raw_code)
            name=_report_label(item.get("name") or "")
            if len(code)==7: code=code[:6]
            if len(code)==6 and name: names[code]=name
    if isinstance(cached,dict) and isinstance(cached.get("municipalities"),dict):
        names.update({str(code):_report_label(name) for code,name in cached["municipalities"].items() if re.fullmatch(r"\d{6}",str(code)) and _report_label(name)})
        if time.time()-float(cached.get("fetched_at",0))<30*86400:
            return names
    if len(names)>=5000:
        return names
    url="https://servicodados.ibge.gov.br/api/v1/localidades/municipios?orderBy=nome"
    try:
        data=_sinan_json_request(url,"servicodados.ibge.gov.br",timeout=25,max_bytes=16*1024*1024)
    except Exception:
        if names: return names
        raise
    if not isinstance(data,list):
        if names: return names
        raise ValueError("O IBGE não retornou a lista de municípios esperada.")
    ibge_names={}
    for item in data:
        if not isinstance(item,dict): continue
        code=str(item.get("id") or "")
        name=_report_label(item.get("nome") or "")
        if len(code)==7 and code[:6].isdigit() and name: ibge_names[code[:6]]=name
    names.update(ibge_names)
    if not names: raise ValueError("O IBGE não retornou nomes de municípios válidos.")
    cache_write(target,{"fetched_at":time.time(),"municipalities":names},max_bytes=8_000_000,keep=4)
    return names

def _sinan_dengue_source_rows(year: int, municipality: str, report_id: str="sinan-dengue", progress=None):
    config=SINAN_AGRAVOS[report_id]
    identity={"version":8,"year":year,"notifyingMunicipality":municipality} if report_id=="sinan-dengue" else {"version":11,"report":report_id,"year":year,"notifyingMunicipality":municipality}
    target=cache_target("sinan_dengue",identity)
    with interprocess_lock(target.with_suffix(".lock")):
        cached=cache_read(target)
        cache_lifetime=24*3600 if year==date.today().year else 30*86400
        if isinstance(cached,dict) and isinstance(cached.get("rows"),list) and isinstance(cached.get("units"),list) and isinstance(cached.get("details"),list) and time.time()-float(cached.get("fetched_at",0))<cache_lifetime:
            if progress: progress(90,"Usando os totais agregados do SINAN em cache local")
            return cached["rows"],cached["units"],cached["details"],"totais agregados em cache local",cached.get("updatedAt"),int(cached.get("invalidOnset",0)),bool(cached.get("hasUnitField"))
        aggregates={}; unit_aggregates={}; detail_aggregates={}; invalid_onset=0; matched=0; scanned=0; maximum=500_000; has_unit_field=False
        expected_member=f"{config['prefix']}BR{year % 100:02d}.csv"
        archive,updated_at=_sinan_dengue_archive(year,report_id,progress)
        try:
            with zipfile.ZipFile(archive) as bundle:
                entries=[entry for entry in bundle.infolist() if not entry.is_dir() and entry.filename.replace("\\","/").rsplit("/",1)[-1].casefold()==expected_member.casefold()]
                if len(entries)!=1 or entries[0].file_size>SINAN_DENGUE_CSV_MAX_BYTES:
                    raise ValueError("O CSV anual do SINAN não corresponde ao ano selecionado ou excede o limite de leitura.")
                info=entries[0]
                with bundle.open(info) as binary, io.TextIOWrapper(binary,encoding="latin1",newline="") as text_stream:
                    reader=csv.reader(text_stream,delimiter=",")
                    header=next(reader,[])
                    headers={str(name or "").lstrip("\ufeff").strip().upper():index for index,name in enumerate(header)}
                    required=("ID_AGRAVO","NU_ANO","ID_MUNICIP","DT_SIN_PRI","SEM_PRI","ID_MN_RESI","CLASSI_FIN","CRITERIO","EVOLUCAO")
                    missing=[name for name in required if name not in headers]
                    if missing: raise ValueError("O CSV oficial do SINAN não contém os campos esperados: "+", ".join(missing)+".")
                    has_unit_field="ID_UNIDADE" in headers
                    max_required_index=max(headers[name] for name in required)
                    if max_required_index>=len(header): raise ValueError("O cabeçalho do CSV oficial do SINAN está incompleto.")
                    if progress: progress(32,f"Lendo registros do arquivo oficial do SINAN · {year}")
                    for item in reader:
                        scanned+=1
                        if progress and scanned%25000==0:
                            read_bytes=min(info.file_size,binary.tell())
                            percent=32+int(54*read_bytes/max(1,info.file_size))
                            progress(min(86,percent),f"Analisando SINAN · {read_bytes/1024/1024:.0f} de {info.file_size/1024/1024:.0f} MB · {scanned:,} registros".replace(",","."))
                        if len(item)<=max_required_index: continue
                        if str(item[headers["NU_ANO"]] or "").strip()!=str(year): continue
                        if re.sub(r"\D","",str(item[headers["ID_MUNICIP"]] or ""))!=municipality: continue
                        if re.sub(r"[^a-z0-9]","",_sinan_code(item[headers["ID_AGRAVO"]]))!=config["icd"]: continue
                        onset=str(item[headers["DT_SIN_PRI"]] or "").strip()
                        parsed=re.match(r"^(\d{4})-(\d{2})-(\d{2})",onset)
                        if parsed: onset_year,onset_month,onset_day=int(parsed.group(1)),int(parsed.group(2)),int(parsed.group(3))
                        else:
                            parsed=re.match(r"^(\d{2})/(\d{2})/(\d{4})$",onset)
                            if parsed: onset_year,onset_month,onset_day=int(parsed.group(3)),int(parsed.group(2)),int(parsed.group(1))
                            else:
                                compact=re.match(r"^(\d{4})(\d{2})(\d{2})$",onset)
                                if compact: onset_year,onset_month,onset_day=int(compact.group(1)),int(compact.group(2)),int(compact.group(3))
                                else: invalid_onset+=1; continue
                        try: date(onset_year,onset_month,onset_day)
                        except ValueError: invalid_onset+=1; continue
                        if onset_year!=year: continue
                        raw_week=re.sub(r"\D","",str(item[headers["SEM_PRI"]] or ""))
                        week=int(raw_week[-2:]) if len(raw_week)>=2 else 0
                        if not 1<=week<=53: invalid_onset+=1; continue
                        matched+=1
                        if matched>maximum: raise ValueError("Este município ultrapassa 500 mil notificações no ano selecionado; o recorte foi interrompido para proteger o desempenho.")
                        residence=re.sub(r"\D", "", _sinan_code(item[headers["ID_MN_RESI"]]))
                        if len(residence)!=6 or residence=="000000": residence=""
                        code=residence or "000000"
                        metrics={"notifications":0,"probable":0,"confirmed":0,"severe":0,"dengueDeaths":0,"discarded":0,"hospitalizations":0,"pregnant":0,"diseaseDeaths":0,"pending":0}
                        row=aggregates.setdefault((onset_month,code),{"month":onset_month,"residenceCode":residence,**metrics})
                        unit_index=headers.get("ID_UNIDADE")
                        unit_value=item[unit_index] if unit_index is not None and unit_index<len(item) else ""
                        unit_code=re.sub(r"\D","",_sinan_code(unit_value))
                        unit_code=unit_code.zfill(7) if 0<len(unit_code)<=7 else ""
                        if unit_code=="0000000": unit_code=""
                        unit_row=unit_aggregates.setdefault((onset_month,week,unit_code),{"month":onset_month,"week":week,"unitCode":unit_code,**metrics})
                        detail_row=detail_aggregates.setdefault((onset_month,week,unit_code,code),{"month":onset_month,"week":week,"unitCode":unit_code,"residenceCode":residence,**metrics})
                        classification=_sinan_code(item[headers["CLASSI_FIN"]]); criterion=_sinan_code(item[headers["CRITERIO"]]); evolution=_sinan_code(item[headers["EVOLUCAO"]])
                        confirmed=(classification in {"1","2","3","4","10","11","12"} and criterion in {"1","2"}) if report_id=="sinan-dengue" else classification==("13" if report_id=="sinan-chikungunya" else "1")
                        discarded=classification==("2" if report_id=="sinan-zika" else "5")
                        pending=classification in {"","0","8","9"}
                        hospital_index=headers.get("HOSPITALIZ")
                        hospitalized=report_id=="sinan-chikungunya" and hospital_index is not None and hospital_index<len(item) and _sinan_code(item[hospital_index])=="1"
                        pregnant_index=headers.get("CS_GESTANT")
                        pregnant=report_id=="sinan-zika" and pregnant_index is not None and pregnant_index<len(item) and _sinan_code(item[pregnant_index]) in {"1","2","3","4"}
                        for group in (row,unit_row,detail_row):
                            group["notifications"]+=1
                            if not discarded: group["probable"]+=1
                            if confirmed: group["confirmed"]+=1
                            if discarded: group["discarded"]+=1
                            if report_id=="sinan-dengue":
                                if confirmed and classification in {"2","3","4","11","12"}: group["severe"]+=1
                                if confirmed and evolution=="2": group["dengueDeaths"]+=1
                            else:
                                if pending: group["pending"]+=1
                                if hospitalized: group["hospitalizations"]+=1
                                if pregnant: group["pregnant"]+=1
                                if confirmed and evolution=="2": group["diseaseDeaths"]+=1
        except (csv.Error,UnicodeError,zipfile.BadZipFile,EOFError) as exc:
            raise ValueError("Não foi possível ler o CSV do pacote oficial do SINAN; tente novamente para baixar uma cópia íntegra.") from exc
        finally:
            archive.unlink(missing_ok=True)
        fetched_at=time.time()
        grouped_rows=list(aggregates.values())
        grouped_units=list(unit_aggregates.values())
        grouped_details=list(detail_aggregates.values())
        cache_write(target,{"fetched_at":fetched_at,"updatedAt":updated_at,"invalidOnset":invalid_onset,"hasUnitField":has_unit_field,"rows":grouped_rows,"units":grouped_units,"details":grouped_details,"sourceMode":"CSV oficial"},max_bytes=64_000_000,keep=20)
        return grouped_rows,grouped_units,grouped_details,"CSV oficial",updated_at,invalid_onset,has_unit_field

SIM_CID_CHAPTERS=(("A00","B99","Infecciosas e parasitárias"),("C00","D48","Neoplasias"),("D50","D89","Doenças do sangue"),("E00","E90","Endócrinas e metabólicas"),("F00","F99","Transtornos mentais"),("G00","G99","Sistema nervoso"),("H00","H59","Olhos"),("H60","H95","Ouvidos"),("I00","I99","Aparelho circulatório"),("J00","J99","Aparelho respiratório"),("K00","K93","Aparelho digestivo"),("L00","L99","Pele"),("M00","M99","Sistema osteomuscular"),("N00","N99","Aparelho geniturinário"),("O00","O99","Gravidez, parto e puerpério"),("P00","P96","Condições perinatais"),("Q00","Q99","Malformações congênitas"),("R00","R99","Sinais e causas mal definidas"),("S00","T98","Lesões e envenenamentos"),("V01","Y98","Causas externas"),("Z00","Z99","Fatores de saúde"),("U00","U99","Códigos especiais"))

SINASC_METRIC_KEYS=("births","vaginal","cesarean","deliveryKnown","prenatal7","prenatal0to3","prenatalKnown","earlyPrenatal","premature","gestationKnown","lowWeight","weightKnown","teenMothers","mothers35","lowApgar5","apgarKnown","anomalies","localResidence","outsideResidence","unknownResidence")

def _sinasc_archive_download(year: int, progress=None):
    """Fetch one fixed annual CSV package from the official SINASC open-data host."""
    folder=UPLOADS/".cache"/"sinasc-source"
    folder.mkdir(parents=True,exist_ok=True)
    for old in folder.glob("sinasc-*.part"):
        try:
            if time.time()-old.stat().st_mtime>86400: old.unlink(missing_ok=True)
        except OSError: pass
    expected_member=f"SINASC_{year}.csv"
    def valid_archive(path):
        try:
            with zipfile.ZipFile(path) as bundle:
                entries=bundle.infolist()
                matches=[item for item in entries if not item.is_dir() and item.filename.replace("\\","/").rsplit("/",1)[-1].casefold()==expected_member.casefold()]
                return len(entries)<=10 and len(matches)==1 and 0<matches[0].file_size<=2*1024*1024*1024
        except (OSError,zipfile.BadZipFile,ValueError): return False
    url=f"https://{SINAN_DENGUE_ARCHIVE_HOST}/ckan.saude.gov.br/SINASC/csv/SINASC_{year}_csv.zip"
    request=urllib.request.Request(url,headers={"User-Agent":"TabulaSUS/1.0","Accept":"application/zip"})
    fd,name=tempfile.mkstemp(prefix="sinasc-",suffix=".part",dir=str(folder)); os.close(fd)
    temp=Path(name)
    try:
        with open_verified_https(request,SINAN_DENGUE_ARCHIVE_HOST,120) as response, temp.open("wb") as output:
            size=int(response.headers.get("Content-Length") or 0)
            modified=response.headers.get("Last-Modified")
            try: updated_at=parsedate_to_datetime(modified).date().isoformat() if modified else date.today().isoformat()
            except (TypeError,ValueError,OverflowError): updated_at=date.today().isoformat()
            if size>256*1024*1024: raise ValueError("O arquivo anual do SINASC ultrapassa o limite seguro de download.")
            if shutil.disk_usage(folder).free<(size or 128*1024*1024)+32*1024*1024: raise ValueError("Espaço insuficiente para baixar o SINASC.")
            received=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                received+=len(chunk)
                if received>256*1024*1024 or (size and received>size): raise ValueError("O download do SINASC excedeu o tamanho esperado.")
                output.write(chunk)
                if progress: progress(min(35,5+int(30*received/max(size,received))),f"Baixando SINASC {year} · {received/1048576:.1f} MB"+(f" de {size/1048576:.1f} MB" if size else ""))
        if size and received!=size: raise ValueError("O download do SINASC terminou incompleto.")
        if not valid_archive(temp): raise ValueError("O pacote oficial do SINASC não contém o CSV esperado.")
        result=temp
        temp=None
        return result,updated_at
    except urllib.error.HTTPError as exc:
        if exc.code==404: raise ValueError(f"O arquivo oficial do SINASC de {year} ainda não foi publicado.") from exc
        raise ValueError(f"O servidor oficial do SINASC respondeu com HTTP {exc.code}.") from exc
    except (OSError,TimeoutError,urllib.error.URLError) as exc:
        raise ValueError(f"Não foi possível baixar o arquivo oficial do SINASC: {exc}") from exc
    finally:
        if temp is not None: temp.unlink(missing_ok=True)

def _sinasc_archive(year: int, progress=None):
    folder=UPLOADS/".cache"/"sinasc-source"
    folder.mkdir(parents=True,exist_ok=True)
    archive=folder/f"SINASC_{year}_csv.zip"
    metadata=folder/f"SINASC_{year}_csv.json"
    lifetime=24*3600 if year==date.today().year else 30*86400
    with interprocess_lock(archive.with_suffix(".lock")):
        stored=cache_read(metadata)
        if archive.is_file() and zipfile.is_zipfile(archive) and time.time()-float((stored or {}).get("fetched_at",archive.stat().st_mtime))<lifetime:
            if progress: progress(35,f"Usando o pacote oficial do SINASC {year} salvo neste computador")
            return archive,str((stored or {}).get("updatedAt") or date.fromtimestamp(archive.stat().st_mtime).isoformat())
        try: downloaded,updated_at=_sinasc_archive_download(year,progress)
        except (OSError,ValueError,TimeoutError):
            if not archive.is_file() or not zipfile.is_zipfile(archive): raise
            if progress: progress(35,f"Usando a última cópia disponível do SINASC {year}")
            return archive,str((stored or {}).get("updatedAt") or date.fromtimestamp(archive.stat().st_mtime).isoformat())
        try:
            os.replace(downloaded,archive)
        except OSError:
            if not archive.is_file() or not zipfile.is_zipfile(archive): raise
            downloaded.unlink(missing_ok=True)
            return archive,str((stored or {}).get("updatedAt") or date.fromtimestamp(archive.stat().st_mtime).isoformat())
        cache_write(metadata,{"fetched_at":time.time(),"updatedAt":updated_at},max_bytes=10_000,keep=2)
        return archive,updated_at

def _sinasc_source(year: int, uf: str, progress=None):
    target=cache_target("sinasc_maternity",{"version":5,"year":year,"uf":uf})
    detail_target=target.with_suffix(".sqlite3")
    with interprocess_lock(target.with_suffix(".lock")):
        cached=cache_read(target)
        lifetime=24*3600 if year==date.today().year else 30*86400
        if isinstance(cached,dict) and isinstance(cached.get("groups"),list) and detail_target.is_file() and time.time()-float(cached.get("fetched_at",0))<lifetime:
            if progress: progress(92,"Usando o resumo anual do SINASC salvo neste computador")
            return cached
        archive,updated_at=_sinasc_archive(year,progress)
        groups={}; scanned=0; included=0; unassigned=0
        detail_fd,detail_name=tempfile.mkstemp(prefix="sinasc-detail-",suffix=".sqlite3",dir=str(target.parent)); os.close(detail_fd)
        detail_temp=Path(detail_name)
        detail_db=None
        try:
            detail_db=sqlite3.connect(str(detail_temp))
            detail_db.execute("CREATE TABLE births (month INTEGER, occurrence TEXT, cnes TEXT, birth_date TEXT, residence TEXT, sex TEXT, maternal_age TEXT, delivery TEXT, prenatal TEXT, prenatal_start TEXT, gestation TEXT, weight TEXT, apgar1 TEXT, apgar5 TEXT, anomaly TEXT, anomaly_code TEXT, education TEXT, race TEXT, pregnancy TEXT, metrics TEXT)")
            with zipfile.ZipFile(archive) as bundle:
                member=next(item for item in bundle.infolist() if item.filename.replace("\\","/").rsplit("/",1)[-1].casefold()==f"SINASC_{year}.csv".casefold())
                with bundle.open(member) as binary, io.TextIOWrapper(binary,encoding="latin1",newline="") as stream:
                    reader=csv.reader(stream,delimiter=";")
                    fields={name.lstrip("\ufeff").strip().upper():index for index,name in enumerate(next(reader))}
                    required={"CODESTAB","CODMUNNASC","CODMUNRES","DTNASC","LOCNASC","PARTO","PESO","IDADEMAE"}
                    if not required.issubset(fields): raise ValueError("O CSV oficial do SINASC não contém os campos essenciais do relatório.")
                    def field(row,key):
                        pos=fields.get(key)
                        return row[pos].strip() if pos is not None and pos<len(row) else ""
                    for row in reader:
                        scanned+=1
                        if progress and scanned%100000==0: progress(min(89,36+int(52*binary.tell()/max(1,member.file_size))),f"Lendo SINASC {year} · {scanned:,} registros".replace(",","."))
                        occurrence=re.sub(r"\D","",field(row,"CODMUNNASC"))[:6]
                        if not re.fullmatch(r"\d{6}",occurrence) or occurrence[:2]!=PREDEFINED_UF_CODES[uf]: continue
                        if field(row,"LOCNASC") not in {"1","2"}: continue
                        raw_date=field(row,"DTNASC")
                        if not re.fullmatch(r"\d{8}",raw_date): continue
                        try: birth_date=date(int(raw_date[4:]),int(raw_date[2:4]),int(raw_date[:2]))
                        except ValueError: continue
                        if birth_date.year!=year: continue
                        code=re.sub(r"\D","",field(row,"CODESTAB"))
                        if not re.fullmatch(r"\d{7}",code): code="0000000"; unassigned+=1
                        key=(birth_date.month,occurrence,code)
                        item=groups.setdefault(key,{"month":birth_date.month,"occurrenceCode":occurrence,"cnes":code,**{metric:0 for metric in SINASC_METRIC_KEYS}})
                        previous={metric:item[metric] for metric in SINASC_METRIC_KEYS}
                        item["births"]+=1; included+=1
                        delivery=field(row,"PARTO")
                        if delivery in {"1","2"}:
                            item["deliveryKnown"]+=1; item["vaginal" if delivery=="1" else "cesarean"]+=1
                        prenatal=field(row,"CONSPRENAT")
                        count=int(prenatal) if re.fullmatch(r"\d{1,2}",prenatal) and int(prenatal)<=60 else None
                        category=field(row,"CONSULTAS")
                        if count is not None:
                            item["prenatalKnown"]+=1
                            if count>=7: item["prenatal7"]+=1
                            if count<=3: item["prenatal0to3"]+=1
                        elif category in {"1","2","3","4"}:
                            item["prenatalKnown"]+=1
                            if category=="4": item["prenatal7"]+=1
                            if category in {"1","2"}: item["prenatal0to3"]+=1
                        prenatal_month=field(row,"MESPRENAT")
                        if re.fullmatch(r"\d{1,2}",prenatal_month) and 1<=int(prenatal_month)<=3: item["earlyPrenatal"]+=1
                        weeks=field(row,"SEMAGESTAC")
                        gestation=int(weeks) if re.fullmatch(r"\d{1,2}",weeks) and 18<=int(weeks)<=45 else None
                        if gestation is not None:
                            item["gestationKnown"]+=1
                            if gestation<37: item["premature"]+=1
                        elif field(row,"GESTACAO") in {"1","2","3","4","5","6"}:
                            item["gestationKnown"]+=1
                            if field(row,"GESTACAO") in {"1","2","3","4"}: item["premature"]+=1
                        weight=field(row,"PESO")
                        if re.fullmatch(r"\d{3,4}",weight) and 100<=int(weight)<=8000:
                            item["weightKnown"]+=1
                            if int(weight)<2500: item["lowWeight"]+=1
                        age=field(row,"IDADEMAE")
                        if re.fullmatch(r"\d{1,2}",age):
                            age_value=int(age)
                            if 10<=age_value<20: item["teenMothers"]+=1
                            if 35<=age_value<=60: item["mothers35"]+=1
                        apgar=field(row,"APGAR5")
                        if re.fullmatch(r"\d{1,2}",apgar) and int(apgar)<=10:
                            item["apgarKnown"]+=1
                            if int(apgar)<7: item["lowApgar5"]+=1
                        if field(row,"IDANOMAL")=="1": item["anomalies"]+=1
                        residence=re.sub(r"\D","",field(row,"CODMUNRES"))[:6]
                        residence_known=bool(re.fullmatch(r"\d{6}",residence) and residence[:2] in PREDEFINED_UF_CODES.values())
                        item["localResidence" if residence==occurrence else "outsideResidence" if residence_known else "unknownResidence"]+=1
                        metrics=json.dumps({metric:item[metric]-previous[metric] for metric in SINASC_METRIC_KEYS if item[metric]!=previous[metric]},separators=(",",":"))
                        detail_db.execute("INSERT INTO births VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(birth_date.month,occurrence,code,birth_date.isoformat(),residence,field(row,"SEXO"),field(row,"IDADEMAE"),delivery,prenatal if count is not None else f"faixa:{category}",prenatal_month,weeks if gestation is not None else f"faixa:{field(row,'GESTACAO')}",weight,field(row,"APGAR1"),field(row,"APGAR5"),field(row,"IDANOMAL"),field(row,"CODANOMAL")[:40],field(row,"ESCMAE2010"),field(row,"RACACORMAE"),field(row,"GRAVIDEZ"),metrics))
            detail_db.execute("CREATE INDEX births_scope ON births(month,occurrence,cnes)")
            detail_db.commit(); detail_db.close(); detail_db=None
            os.replace(detail_temp,detail_target)
        finally:
            if detail_db is not None: detail_db.close()
            if detail_temp.exists(): detail_temp.unlink(missing_ok=True)
        data={"fetched_at":time.time(),"updatedAt":updated_at,"groups":list(groups.values()),"scanned":scanned,"included":included,"unassigned":unassigned}
        cache_write(target,data,max_bytes=100_000_000,keep=8)
        return data

SINASC_FILTER_VALUES={
    "residenceOrigin":{"local","outside","unknown"},
    "delivery":{"1","2","unknown"},
    "prenatalBand":{"0","1-3","4-6","7+","unknown"},
    "prenatalStart":{"1-3","4-6","7-9","unknown"},
    "gestation":{"under22","22-27","28-31","32-36","37-41","42+","unknown"},
    "weight":{"under1500","1500-2499","2500+","unknown"},
    "maternalAge":{"under20","20-34","35+","unknown"},
    "maternalEducation":{"0","1","2","3","4","5","unknown"},
    "maternalRace":{"1","2","3","4","5","unknown"},
    "apgar1":{"0-3","4-6","7-10","unknown"},
    "apgar5":{"0-3","4-6","7-10","unknown"},
    "anomaly":{"1","2","unknown"}
}

def _sinasc_selected_filters(payload):
    submitted=payload.get("sinascFilters") or {}
    if not isinstance(submitted,dict) or set(submitted)-set(SINASC_FILTER_VALUES)-{"residenceMunicipality"}:
        raise ValueError("Os filtros do SINASC são inválidos.")
    selected={}
    for key,values in submitted.items():
        if not isinstance(values,list) or len(values)>30 or any(not isinstance(value,str) for value in values):
            raise ValueError("Os filtros do SINASC são inválidos.")
        allowed=SINASC_FILTER_VALUES.get(key)
        distinct=sorted(set(values))
        if any(not (re.fullmatch(r"\d{6}",value) if key=="residenceMunicipality" else value in allowed) for value in distinct):
            raise ValueError("Uma categoria selecionada não existe no SINASC.")
        if distinct: selected[key]=set(distinct)
    return selected

def _sinasc_birth_categories(birth):
    def number(key,minimum,maximum):
        value=str(birth[key] or "")
        return int(value) if value.isdigit() and minimum<=int(value)<=maximum else None
    residence=str(birth["residence"] or "")
    occurrence=str(birth["occurrence"] or "")
    prenatal=str(birth["prenatal"] or "")
    if prenatal.startswith("faixa:"):
        prenatal_band={"1":"0","2":"1-3","3":"4-6","4":"7+"}.get(prenatal[6:],"unknown")
    else:
        count=number("prenatal",0,60)
        prenatal_band="unknown" if count is None else "0" if count==0 else "1-3" if count<=3 else "4-6" if count<=6 else "7+"
    start=number("prenatal_start",1,9)
    gestation=str(birth["gestation"] or "")
    if gestation.startswith("faixa:"):
        gestation_band={"1":"under22","2":"22-27","3":"28-31","4":"32-36","5":"37-41","6":"42+"}.get(gestation[6:],"unknown")
    else:
        weeks=number("gestation",18,45)
        gestation_band="unknown" if weeks is None else "under22" if weeks<22 else "22-27" if weeks<28 else "28-31" if weeks<32 else "32-36" if weeks<37 else "37-41" if weeks<42 else "42+"
    weight=number("weight",100,8000)
    age=number("maternal_age",10,60)
    def apgar_band(key):
        value=number(key,0,10)
        return "unknown" if value is None else "0-3" if value<=3 else "4-6" if value<=6 else "7-10"
    return {
        "residenceOrigin":"local" if residence==occurrence else "outside" if re.fullmatch(r"\d{6}",residence) and residence[:2] in PREDEFINED_UF_CODES.values() else "unknown",
        "residenceMunicipality":residence,
        "delivery":birth["delivery"] if birth["delivery"] in {"1","2"} else "unknown",
        "prenatalBand":prenatal_band,
        "prenatalStart":"unknown" if start is None else "1-3" if start<=3 else "4-6" if start<=6 else "7-9",
        "gestation":gestation_band,
        "weight":"unknown" if weight is None else "under1500" if weight<1500 else "1500-2499" if weight<2500 else "2500+",
        "maternalAge":"unknown" if age is None else "under20" if age<20 else "20-34" if age<35 else "35+",
        "maternalEducation":birth["education"] if birth["education"] in {"0","1","2","3","4","5"} else "unknown",
        "maternalRace":birth["race"] if birth["race"] in {"1","2","3","4","5"} else "unknown",
        "apgar1":apgar_band("apgar1"),"apgar5":apgar_band("apgar5"),
        "anomaly":birth["anomaly"] if birth["anomaly"] in {"1","2"} else "unknown"
    }

def _sinasc_matches_filters(birth,selected):
    if not selected: return True
    categories=_sinasc_birth_categories(birth)
    return all(categories[key] in values for key,values in selected.items())

def _sinasc_maternity_names(codes: list[str]):
    valid=sorted({code for code in codes if re.fullmatch(r"\d{7}",code) and code!="0000000"})
    if not valid: return {},0
    target=cache_target("sinasc_maternity_names",{"version":1})
    now=time.time(); names={}; missing=[]; failed=0
    with interprocess_lock(target.with_suffix(".lock")):
        cached=cache_read(target)
        entries=cached.get("names",{}) if isinstance(cached,dict) and isinstance(cached.get("names"),dict) else {}
        for code in valid:
            entry=entries.get(code,{})
            if now-float(entry.get("checkedAt",0))<(30*86400 if entry.get("name") else 86400): names[code]=entry.get("name") or ""
            else: missing.append(code)
        def lookup(code):
            data,ok=_cnes_open_data_json(f"/cnes/estabelecimentos/{code}")
            if not ok: return code,"",False
            if not isinstance(data,dict): return code,"",True
            returned=re.sub(r"\D","",str(data.get("codigo_cnes") or data.get("co_cnes") or "")).zfill(7)
            if returned!=code: return code,"",True
            name=_report_label(data.get("nome_fantasia") or data.get("nome_razao_social") or "")[:180]
            return code,name,True
        if missing:
            with ThreadPoolExecutor(max_workers=min(8,len(missing)),thread_name_prefix="sinasc-cnes") as executor:
                for future in as_completed([executor.submit(lookup,code) for code in missing]):
                    try: code,name,ok=future.result()
                    except Exception: failed+=1; continue
                    if not ok: failed+=1; continue
                    entries[code]={"name":name,"checkedAt":now}; names[code]=name
            cache_write(target,{"names":entries},max_bytes=2_000_000,keep=2)
    return names,failed

def predefined_sinasc_maternity(payload: dict[str,Any], progress=None):
    year=payload.get("year"); month=payload.get("month"); uf=str(payload.get("uf") or "").upper(); municipality=str(payload.get("municipalityCode") or "")
    if not isinstance(year,int) or not 2010<=year<=date.today().year or not isinstance(month,int) or not 1<=month<=12: raise ValueError("Selecione um período válido para o SINASC, a partir de 2010.")
    if uf not in PREDEFINED_UF_CODES or not re.fullmatch(r"\d{6}",municipality) or municipality[:2]!=PREDEFINED_UF_CODES[uf]: raise ValueError("Selecione o município onde ocorreram os nascimentos.")
    if str(payload.get("view") or "full")!="full": raise ValueError("Selecione uma visão válida do relatório do SINASC.")
    selected_filters=_sinasc_selected_filters(payload)
    data=_sinasc_source(year,uf,progress)
    if selected_filters:
        filtered={}
        detail_target=cache_target("sinasc_maternity",{"version":5,"year":year,"uf":uf}).with_suffix(".sqlite3")
        with sqlite3.connect(str(detail_target)) as db:
            db.row_factory=sqlite3.Row
            for birth in db.execute("SELECT * FROM births WHERE month=? AND occurrence=?",(month,municipality)):
                if not _sinasc_matches_filters(birth,selected_filters): continue
                code=birth["cnes"]
                item=filtered.setdefault(code,{"month":month,"occurrenceCode":municipality,"cnes":code,**{metric:0 for metric in SINASC_METRIC_KEYS}})
                for metric,increment in json.loads(birth["metrics"]).items(): item[metric]+=increment
        selected=list(filtered.values())
    else:
        selected=[dict(row) for row in data["groups"] if row["month"]==month and row["occurrenceCode"]==municipality]
    if progress: progress(93,"Identificando os estabelecimentos no CNES")
    names,lookup_failures=_sinasc_maternity_names([row["cnes"] for row in selected])
    for row in selected:
        row["name"]=names.get(row["cnes"]) or ("Estabelecimento sem CNES informado" if row["cnes"]=="0000000" else f"CNES {row['cnes']}")
        for result,numerator,denominator in (("cesareanPct","cesarean","deliveryKnown"),("prenatal7Pct","prenatal7","prenatalKnown"),("prematurePct","premature","gestationKnown"),("lowWeightPct","lowWeight","weightKnown")):
            row[result]=round(100*row[numerator]/row[denominator],1) if row[denominator] else None
    selected.sort(key=lambda row:(-row["births"],row["name"].casefold()))
    totals={key:sum(row[key] for row in selected) for key in SINASC_METRIC_KEYS}
    columns=[{"id":"maternity","label":"ESTABELECIMENTO DO NASCIMENTO","kind":"primary","primaryField":"name","secondaryField":"cnes","secondaryPrefix":"CNES ","filterFields":["name","cnes"],"sortField":"name","type":"text","sticky":True}]
    for field,label in (("births","NASCIDOS VIVOS"),("cesarean","NASCIDOS POR CESÁREA"),("cesareanPct","CESÁREA %"),("vaginal","NASCIDOS POR PARTO VAGINAL"),("prenatal7","PRÉ-NATAL · 7+ CONSULTAS"),("prenatal7Pct","PRÉ-NATAL 7+ %"),("prenatal0to3","PRÉ-NATAL · 0 A 3"),("earlyPrenatal","INÍCIO ATÉ O 3º MÊS"),("premature","PREMATUROS"),("prematurePct","PREMATURIDADE %"),("lowWeight","BAIXO PESO"),("lowWeightPct","BAIXO PESO %"),("teenMothers","NASCIDOS DE MÃES < 20"),("mothers35","NASCIDOS DE MÃES ≥ 35"),("lowApgar5","APGAR 5º MIN < 7"),("anomalies","ANOMALIAS REGISTRADAS"),("localResidence","RESIDENTES DO MUNICÍPIO"),("outsideResidence","RESIDENTES DE FORA")):
        columns.append({"id":field,"label":label,"field":field,"metricId":field if not field.endswith("Pct") else None,"type":"percent" if field.endswith("Pct") else "number","decimals":1 if field.endswith("Pct") else 0})
    columns.append({"id":"detail","label":"DETALHAMENTO","kind":"action","actionLabel":"Detalhar →"})
    metrics=[{"id":column["metricId"],"label":column["label"],"decimals":0} for column in columns if column.get("metricId")]
    municipality_name=_report_label(payload.get("municipalityName") or "") or f"Município {municipality}"
    notes=[f"Fonte: SINASC, CSV anual oficial {year}, atualizado em {data['updatedAt']}. Município de ocorrência do nascimento: {municipality_name} ({municipality}).",
        "Cada registro representa um nascido vivo, não um parto. Incluídos nascimentos em hospital ou outro estabelecimento de saúde; nascimentos domiciliares e outros locais ficam fora deste relatório por estabelecimento.",
        "Percentuais usam somente registros com a informação correspondente preenchida: tipo de parto, consultas de pré-natal, idade gestacional ou peso. Pré-natal de 7+ consultas não mede sozinho a qualidade do cuidado. Quando o número exato de consultas não está disponível, utiliza-se a faixa registrada no SINASC.",
        "Prematuridade: menos de 37 semanas. Baixo peso: menos de 2.500 g. Baixo Apgar: menos de 7 no 5º minuto. Nome do estabelecimento consultado no CNES atual; os demais dados são do SINASC no ano selecionado.",
        *( [f"{totals['unknownResidence']} registro(s) não tinham município de residência identificável e não entram nas duas colunas de residência."] if totals["unknownResidence"] else [] ),
        *( [f"O CNES não respondeu para {lookup_failures} estabelecimento(s); seus códigos e indicadores foram preservados."] if lookup_failures else [] ),
        *( ["Este arquivo é uma prévia e os dados ainda podem ser revistos pela fonte oficial."] if year>=date.today().year-1 else [] )]
    if selected_filters: notes.insert(1,f"{len(selected_filters)} filtro(s) opcional(is) aplicado(s) aos registros antes de calcular os totais.")
    empty_message="Nenhum nascimento corresponde aos filtros selecionados neste período. Ajuste ou remova um filtro para ampliar o recorte." if selected_filters else f"O arquivo oficial do SINASC de {year} ainda não apresenta nascimentos em estabelecimentos de {municipality_name} em {month:02d}/{year}. Isso pode refletir atraso de atualização; não confirma ausência de nascimentos."
    if progress: progress(98,"Concluindo o perfil materno-infantil")
    return {"ok":True,"report":"sinasc-maternidades","view":"full","flatTable":True,"file":"SINASC · CSV oficial","year":year,"month":month,"uf":uf,"state":PREDEFINED_UF_NAMES[uf],"municipality":municipality_name,"municipalityCode":municipality,"updatedAt":data["updatedAt"],"rows":selected,"records":totals["births"],"columns":columns,"metrics":metrics,"kpis":[{"label":"NASCIDOS VIVOS","value":{"value":totals["births"]}},{"label":"UNIDADES COM REGISTROS","value":{"value":len(selected)}},{"label":"NASCIDOS POR CESÁREA · TIPO INFORMADO","value":{"value":round(100*totals["cesarean"]/totals["deliveryKnown"],1),"decimals":1,"suffix":"%"} if totals["deliveryKnown"] else {"text":"—"}},{"label":"BAIXO PESO · PESOS INFORMADOS","value":{"value":round(100*totals["lowWeight"]/totals["weightKnown"],1),"decimals":1,"suffix":"%"} if totals["weightKnown"] else {"text":"—"}}],"notes":notes,"emptyStateMessage":empty_message,"cachedAt":time.time()}

def predefined_sinasc_maternity_detail(payload: dict[str,Any], progress=None):
    source=predefined_sinasc_maternity({**payload,"view":"full"},progress)
    cnes=re.sub(r"\D","",str(payload.get("establishmentCode") or ""))
    if not re.fullmatch(r"\d{7}",cnes): raise ValueError("Selecione um estabelecimento válido para detalhar.")
    selected=next((row for row in source["rows"] if row["cnes"]==cnes),None)
    if not selected: raise ValueError("Este estabelecimento não tem nascimentos no período selecionado.")
    year=source["year"]; month=source["month"]; municipality=source["municipalityCode"]
    target=cache_target("sinasc_maternity",{"version":5,"year":year,"uf":source["uf"]}).with_suffix(".sqlite3")
    selected_filters=_sinasc_selected_filters(payload)
    if progress: progress(94,"Preparando os registros do estabelecimento")
    with sqlite3.connect(str(target)) as db:
        db.row_factory=sqlite3.Row
        records=[record for record in db.execute("SELECT * FROM births WHERE month=? AND occurrence=? AND cnes=? ORDER BY birth_date,rowid",(month,municipality,cnes)) if _sinasc_matches_filters(record,selected_filters)]
    try: residence_names=_sinan_ibge_municipalities()
    except (OSError,ValueError,TimeoutError,urllib.error.URLError): residence_names={}
    gestation_bands={"1":"Menos de 22","2":"22 a 27","3":"28 a 31","4":"32 a 36","5":"37 a 41","6":"42 ou mais"}
    prenatal_bands={"1":"Nenhuma","2":"1 a 3","3":"4 a 6","4":"7 ou mais"}
    education_labels={"0":"Sem escolaridade","1":"Fundamental I","2":"Fundamental II","3":"Ensino médio","4":"Superior incompleto","5":"Superior completo"}
    race_labels={"1":"Branca","2":"Preta","3":"Amarela","4":"Parda","5":"Indígena"}
    pregnancy_labels={"1":"Única","2":"Dupla","3":"Tripla ou mais"}
    rows=[]
    for index,birth in enumerate(records,1):
        birth_date=birth["birth_date"]; residence=birth["residence"]; sex=birth["sex"]; age=birth["maternal_age"]; delivery=birth["delivery"]
        prenatal=birth["prenatal"]; start=birth["prenatal_start"]; gestation=birth["gestation"]; weight=birth["weight"]
        apgar1=birth["apgar1"]; apgar5=birth["apgar5"]; anomaly=birth["anomaly"]
        residence_valid=bool(re.fullmatch(r"\d{6}",residence or "") and residence[:2] in PREDEFINED_UF_CODES.values())
        gestation_label=gestation_bands.get(gestation[6:],"Não informado")+" semanas (faixa)" if gestation.startswith("faixa:") else f"{gestation} semanas" if gestation.isdigit() else "Não informado"
        prenatal_label=prenatal_bands.get(prenatal[6:],"Não informado")+" (faixa)" if prenatal.startswith("faixa:") else str(int(prenatal)) if prenatal.isdigit() else "Não informado"
        birth_metrics=json.loads(birth["metrics"])
        rows.append({"sequence":index,"birthDate":date.fromisoformat(birth_date).strftime("%d/%m/%Y"),"birthDateSort":birth_date,"residenceCode":residence if residence_valid else "","residenceName":residence_names.get(residence,f"Município {residence}") if residence_valid else "Não informado","sex":{"1":"Masculino","2":"Feminino"}.get(sex,"Não informado"),"maternalAge":int(age) if age.isdigit() and 10<=int(age)<=60 else None,"maternalEducation":education_labels.get(birth["education"],"Não informado"),"maternalRace":race_labels.get(birth["race"],"Não informado"),"pregnancy":pregnancy_labels.get(birth["pregnancy"],"Não informado"),"delivery":{"1":"Vaginal","2":"Cesárea"}.get(delivery,"Não informado"),"prenatal":prenatal_label,"prenatalStart":f"{int(start)}º mês" if start.isdigit() and 1<=int(start)<=9 else "Não informado","gestation":gestation_label,"weight":int(weight) if weight.isdigit() and 100<=int(weight)<=8000 else None,"apgar1":int(apgar1) if apgar1.isdigit() and 0<=int(apgar1)<=10 else None,"apgar5":int(apgar5) if apgar5.isdigit() and 0<=int(apgar5)<=10 else None,"anomaly":{"1":"Sim","2":"Não"}.get(anomaly,"Não informado"),"anomalyCode":birth["anomaly_code"] or "Não informado","isPremature":birth_metrics.get("premature",0),"isLowWeight":birth_metrics.get("lowWeight",0)})
    columns=[{"id":"sequence","label":"REGISTRO","field":"sequence","type":"number","decimals":0,"sticky":True},
        {"id":"birthDate","label":"DATA DO NASCIMENTO","field":"birthDate","sortField":"birthDateSort","type":"text"},
        {"id":"residence","label":"MUNICÍPIO DE RESIDÊNCIA","primaryField":"residenceName","secondaryField":"residenceCode","type":"text","filterFields":["residenceName","residenceCode"]},
        {"id":"sex","label":"SEXO DO NASCIDO VIVO","field":"sex","type":"text"},
        {"id":"maternalAge","label":"IDADE DA MÃE · ANOS","field":"maternalAge","type":"number","decimals":0},
        {"id":"maternalEducation","label":"ESCOLARIDADE DA MÃE","field":"maternalEducation","type":"text"},
        {"id":"maternalRace","label":"RAÇA/COR DA MÃE","field":"maternalRace","type":"text"},
        {"id":"pregnancy","label":"TIPO DE GESTAÇÃO","field":"pregnancy","type":"text"},
        {"id":"delivery","label":"TIPO DE PARTO","field":"delivery","type":"text"},
        {"id":"prenatal","label":"CONSULTAS DE PRÉ-NATAL","field":"prenatal","type":"text"},
        {"id":"prenatalStart","label":"INÍCIO DO PRÉ-NATAL","field":"prenatalStart","type":"text"},
        {"id":"gestation","label":"IDADE GESTACIONAL","field":"gestation","type":"text"},
        {"id":"weight","label":"PESO AO NASCER · G","field":"weight","type":"number","decimals":0},
        {"id":"apgar1","label":"APGAR · 1º MINUTO","field":"apgar1","type":"number","decimals":0},
        {"id":"apgar5","label":"APGAR · 5º MINUTO","field":"apgar5","type":"number","decimals":0},
        {"id":"anomaly","label":"ANOMALIA REGISTRADA","field":"anomaly","type":"text"},
        {"id":"anomalyCode","label":"CÓDIGO DA ANOMALIA · CID-10","field":"anomalyCode","type":"text"}]
    result={**source,"view":"detail","rows":rows,"records":len(rows),"columns":columns,"metrics":[],"establishmentCode":cnes,"establishmentName":selected["name"],"kpis":[{"label":"NASCIDOS VIVOS","value":{"value":len(rows)}},{"label":"NASCIDOS POR CESÁREA","value":{"value":sum(row["delivery"]=="Cesárea" for row in rows)}},{"label":"PREMATUROS","value":{"value":selected["premature"]}},{"label":"BAIXO PESO","value":{"value":selected["lowWeight"]}}],"notes":["Cada linha representa um nascido vivo no arquivo público do SINASC. Não são exibidos nomes, CPF, CNS ou outros identificadores pessoais.","Campos ausentes ou ignorados aparecem como não informados. Quando apenas a faixa de pré-natal ou gestação está disponível, ela é identificada na célula.",source["notes"][0],*(["Este arquivo é uma prévia e os dados ainda podem ser revistos pela fonte oficial."] if year>=date.today().year-1 else [])]}
    if progress: progress(98,"Concluindo o detalhamento dos nascimentos")
    return result

def _sim_cid_names():
    # Descrições de três caracteres da tabela CID distribuída no TAB_SIA oficial.
    path=Path(__file__).parent/"data"/"cid10-three.json"
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError): return {}

def _public_health_date(raw: Any):
    value=str(raw or "").strip()
    try:
        if re.fullmatch(r"\d{8}",value): return date(int(value[4:]),int(value[2:4]),int(value[:2]))
        return date.fromisoformat(value[:10])
    except (ValueError,TypeError): return None

def _sim_infant_source(year: int, progress=None):
    """One annual resident-based summary, shared by every municipality and month."""
    target=cache_target("sim_infant",{"version":3,"year":year})
    lifetime=24*3600 if year==date.today().year else 30*86400
    with interprocess_lock(target.with_suffix(".lock")):
        cached=cache_read(target)
        if isinstance(cached,dict) and isinstance(cached.get("groups"),list) and time.time()-float(cached.get("fetched_at",0))<lifetime:
            if progress: progress(48,f"Usando o resumo anual de mortalidade infantil {year}")
            return cached
        if progress: progress(3,f"Consultando óbitos infantis do SIM {year}")
        archive,updated_at=_sinan_dengue_archive(year,"sim-mortalidade",progress)
        groups=[]; scanned=0; ignored_age=0
        try:
            with zipfile.ZipFile(archive) as bundle:
                expected=f"Mortalidade_Geral_{year}.csv"
                matches=[item for item in bundle.infolist() if not item.is_dir() and item.filename.replace("\\","/").rsplit("/",1)[-1].casefold()==expected.casefold()]
                if len(matches)!=1 or not 0<matches[0].file_size<=SINAN_DENGUE_CSV_MAX_BYTES: raise ValueError("O pacote do SIM não contém o CSV esperado.")
                with bundle.open(matches[0]) as binary, io.TextIOWrapper(binary,encoding="latin1",newline="") as stream:
                    reader=csv.reader(stream,delimiter=";")
                    fields={name.lstrip("\ufeff").strip().upper():index for index,name in enumerate(next(reader))}
                    if not {"DTOBITO","DTNASC","CODMUNRES","CAUSABAS","TIPOBITO"}.issubset(fields): raise ValueError("O CSV do SIM não contém os campos necessários à mortalidade infantil.")
                    def field(row,key):
                        pos=fields.get(key)
                        return row[pos].strip() if pos is not None and pos<len(row) else ""
                    for row in reader:
                        scanned+=1
                        if progress and scanned%50000==0: progress(min(48,31+int(17*binary.tell()/max(1,matches[0].file_size))),f"Lendo SIM {year} · {scanned:,} registros".replace(",","."))
                        if field(row,"TIPOBITO")!="2": continue
                        death=_public_health_date(field(row,"DTOBITO"))
                        birth=_public_health_date(field(row,"DTNASC"))
                        if death is None or death.year!=year: continue
                        age=(death-birth).days if birth else None
                        if age is None: ignored_age+=1; continue
                        if age is None or not 0<=age<=364: continue
                        residence=re.sub(r"\D","",field(row,"CODMUNRES"))[:6]
                        if not re.fullmatch(r"\d{6}",residence): continue
                        cid=re.sub(r"[^A-Z0-9]","",field(row,"CAUSABAS").upper())[:4] or "NI"
                        sex_raw=field(row,"SEXO").upper(); sex_code="male" if sex_raw in {"1","M"} else "female" if sex_raw in {"2","F"} else "unknown"
                        sex={"male":"Masculino","female":"Feminino"}.get(sex_code,"Não informado")
                        race_raw=field(row,"RACACOR"); race_code=race_raw if race_raw in {"1","2","3","4","5"} else "unknown"
                        race={"1":"Branca","2":"Preta","3":"Amarela","4":"Parda","5":"Indígena"}.get(race_code,"Não informada")
                        place_raw=field(row,"LOCOCOR"); place_code=place_raw if place_raw in {"1","2","3","4","5","6"} else "unknown"
                        place={"1":"Hospital","2":"Outro estabelecimento de saúde","3":"Domicílio","4":"Via pública","5":"Outro local","6":"Aldeia indígena"}.get(place_code,"Não informado")
                        delivery_raw=field(row,"PARTO"); delivery_code=delivery_raw if delivery_raw in {"1","2"} else "unknown"
                        delivery={"1":"Vaginal","2":"Cesáreo"}.get(delivery_code,"Não informado")
                        care_raw=field(row,"ASSISTMED"); care_code=care_raw if care_raw in {"1","2"} else "unknown"
                        care={"1":"Sim","2":"Não"}.get(care_code,"Não informado")
                        weight=field(row,"PESO"); weight=int(weight) if weight.isdigit() and 200<=int(weight)<=8000 else None
                        gestation=field(row,"SEMAGESTAC"); gestation=int(gestation) if gestation.isdigit() and 18<=int(gestation)<=45 else None
                        mother_age=field(row,"IDADEMAE"); mother_age=int(mother_age) if mother_age.isdigit() and 10<=int(mother_age)<=60 else None
                        age_band="early" if age<=6 else "late" if age<=27 else "post"
                        weight_band="unknown" if weight is None else "under1500" if weight<1500 else "1500-2499" if weight<2500 else "2500+"
                        gestation_band="unknown" if gestation is None else "under28" if gestation<28 else "28-31" if gestation<=31 else "32-36" if gestation<=36 else "37-41" if gestation<=41 else "42+"
                        maternal_age_band="unknown" if mother_age is None else "under20" if mother_age<20 else "20-34" if mother_age<35 else "35+"
                        establishment=re.sub(r"\D","",field(row,"CODESTAB"))[:7]
                        occurrence=re.sub(r"\D","",field(row,"CODMUNOCOR"))[:6]
                        groups.append({"municipalityCode":residence,"month":death.month,"causeCode":cid,"causeGroup":cid[:3] if re.fullmatch(r"[A-Z]\d{2}[A-Z0-9]?",cid) else "NI","deaths":1,"early":int(age<=6),"late":int(7<=age<=27),"post":int(age>=28),"ageDays":age,"ageBand":age_band,"ageGroup":"0 a 6 dias" if age<=6 else "7 a 27 dias" if age<=27 else "28 a 364 dias","sex":sex,"sexCode":sex_code,"race":race,"raceCode":race_code,"place":place,"placeCode":place_code,"delivery":delivery,"deliveryCode":delivery_code,"medicalCare":care,"medicalCareCode":care_code,"birthWeight":weight,"birthWeightBand":weight_band,"gestationWeeks":gestation,"gestationBand":gestation_band,"maternalAge":mother_age,"maternalAgeBand":maternal_age_band,"establishmentCode":establishment if len(establishment)==7 else "","occurrenceCode":occurrence if len(occurrence)==6 else ""})
        finally: archive.unlink(missing_ok=True)
        result={"fetched_at":time.time(),"updatedAt":updated_at,"groups":groups,"ignoredAge":ignored_age}
        cache_write(target,result,max_bytes=80_000_000,keep=8)
        return result

def _sinasc_resident_births(year: int, progress=None):
    target=cache_target("sinasc_resident_births",{"version":1,"year":year})
    lifetime=24*3600 if year==date.today().year else 30*86400
    with interprocess_lock(target.with_suffix(".lock")):
        cached=cache_read(target)
        if isinstance(cached,dict) and isinstance(cached.get("groups"),list) and time.time()-float(cached.get("fetched_at",0))<lifetime:
            if progress: progress(90,f"Usando nascimentos por residência de {year}")
            return cached
        archive,updated_at=_sinasc_archive(year,progress)
        groups={}; scanned=0
        with zipfile.ZipFile(archive) as bundle:
            expected=f"SINASC_{year}.csv"
            matches=[item for item in bundle.infolist() if not item.is_dir() and item.filename.replace("\\","/").rsplit("/",1)[-1].casefold()==expected.casefold()]
            if len(matches)!=1 or not 0<matches[0].file_size<=2*1024*1024*1024: raise ValueError("O pacote do SINASC não contém o CSV esperado.")
            with bundle.open(matches[0]) as binary, io.TextIOWrapper(binary,encoding="latin1",newline="") as stream:
                reader=csv.reader(stream,delimiter=";")
                fields={name.lstrip("\ufeff").strip().upper():index for index,name in enumerate(next(reader))}
                if not {"CODMUNRES","DTNASC"}.issubset(fields): raise ValueError("O CSV do SINASC não contém residência e data do nascimento.")
                residence_index=fields["CODMUNRES"]; birth_index=fields["DTNASC"]
                for row in reader:
                    scanned+=1
                    if progress and scanned%100000==0: progress(min(90,49+int(41*binary.tell()/max(1,matches[0].file_size))),f"Lendo SINASC {year} · {scanned:,} nascimentos".replace(",","."))
                    if max(residence_index,birth_index)>=len(row): continue
                    birth=_public_health_date(row[birth_index]); residence=re.sub(r"\D","",row[residence_index])[:6]
                    if birth is None or birth.year!=year or not re.fullmatch(r"\d{6}",residence): continue
                    key=(residence,birth.month)
                    groups[key]=groups.get(key,0)+1
        result={"fetched_at":time.time(),"updatedAt":updated_at,"groups":[{"municipalityCode":municipality,"month":month,"births":count} for (municipality,month),count in groups.items()]}
        cache_write(target,result,max_bytes=5_000_000,keep=8)
        return result

def _sim_infant_selected_filters(payload: dict[str,Any]) -> dict[str,set[str]]:
    allowed={
        "ageBand":{"early","late","post"},"sex":{"male","female","unknown"},
        "race":{"1","2","3","4","5","unknown"},"causeGroup":set(_sim_cid_names())|{"NI"},
        "birthWeightBand":{"under1500","1500-2499","2500+","unknown"},
        "gestationBand":{"under28","28-31","32-36","37-41","42+","unknown"},
        "maternalAgeBand":{"under20","20-34","35+","unknown"},"delivery":{"1","2","unknown"},
        "deathPlace":{"1","2","3","4","5","6","unknown"},"medicalCare":{"1","2","unknown"},
        "occurrenceMunicipality":set(),
    }
    raw=payload.get("simInfantFilters") or {}
    if not isinstance(raw,dict) or len(raw)>len(allowed): raise ValueError("Os filtros de mortalidade infantil são inválidos.")
    selected={}
    for key,values in raw.items():
        if key not in allowed or not isinstance(values,list) or len(values)>6000: raise ValueError("A seleção de filtros da mortalidade infantil é inválida ou extensa demais.")
        clean={str(value).strip() for value in values if str(value).strip()}
        if key in {"occurrenceMunicipality"}:
            if any(not re.fullmatch(r"\d{6}",value) for value in clean): raise ValueError("Selecione municípios válidos para o local do óbito.")
        elif not clean.issubset(allowed[key]): raise ValueError("A seleção contém uma categoria inválida da mortalidade infantil.")
        if clean: selected[key]=clean
    return selected

def predefined_sim_infant_mortality(payload: dict[str,Any], progress=None):
    year=payload.get("year"); month=payload.get("month"); uf=str(payload.get("uf") or "").upper(); municipality=str(payload.get("municipalityCode") or "")
    if not isinstance(year,int) or not 2010<=year<=date.today().year or not isinstance(month,int) or not 1<=month<=12: raise ValueError("Selecione ano e mês válidos a partir de 2010.")
    if uf not in PREDEFINED_UF_CODES or not re.fullmatch(r"\d{6}",municipality) or municipality[:2]!=PREDEFINED_UF_CODES[uf]: raise ValueError("Selecione um município de residência válido.")
    if str(payload.get("view") or "full")!="full": raise ValueError("Selecione uma visão válida do relatório.")
    selected_filters=_sim_infant_selected_filters(payload)
    sim=_sim_infant_source(year,progress)
    sinasc=_sinasc_resident_births(year,progress)
    cid_names=_sim_cid_names(); rows=[]
    try: municipality_names=_sinan_ibge_municipalities()
    except Exception: municipality_names={}
    def matches(item):
        values={"ageBand":item.get("ageBand","unknown"),"sex":item.get("sexCode","unknown"),"race":item.get("raceCode","unknown"),"causeGroup":item.get("causeGroup","NI"),"birthWeightBand":item.get("birthWeightBand","unknown"),"gestationBand":item.get("gestationBand","unknown"),"maternalAgeBand":item.get("maternalAgeBand","unknown"),"delivery":item.get("deliveryCode","unknown"),"deathPlace":item.get("placeCode","unknown"),"medicalCare":item.get("medicalCareCode","unknown"),"occurrenceMunicipality":item.get("occurrenceCode","")}
        return all(values[key] in values_selected for key,values_selected in selected_filters.items())
    for item in sim["groups"]:
        if item["municipalityCode"]!=municipality or item["month"]!=month or not matches(item): continue
        cid=item["causeCode"]; cid3=cid[:3]
        chapter=next((label for start,end,label in SIM_CID_CHAPTERS if start<=cid3<=end),"Não classificado")
        occurrence=item.get("occurrenceCode") or ""
        rows.append({**item,"causeName":cid_names.get(cid,cid_names.get(cid3,"Descrição CID não disponível")),"chapterName":chapter,"occurrenceName":municipality_names.get(occurrence,f"Município {occurrence}" if occurrence else "Não informado")})
    rows.sort(key=lambda item:(item["ageDays"],item["causeCode"]))
    births=sum(item["births"] for item in sinasc["groups"] if item["municipalityCode"]==municipality and item["month"]==month)
    if progress: progress(98,"Preparando mortalidade infantil e nascidos vivos")
    municipality_name=str(payload.get("municipalityName") or municipality)[:120]
    filter_labels={"ageBand":"Faixa etária do óbito","sex":"Sexo da criança","race":"Raça/cor da criança","causeGroup":"Causa básica · CID-10","birthWeightBand":"Peso ao nascer","gestationBand":"Semanas de gestação","maternalAgeBand":"Idade da mãe","delivery":"Tipo de parto","deathPlace":"Local do óbito","medicalCare":"Assistência médica","occurrenceMunicipality":"Município de ocorrência"}
    filter_values={"ageBand":{"early":"0 a 6 dias","late":"7 a 27 dias","post":"28 a 364 dias"},"sex":{"male":"Masculino","female":"Feminino","unknown":"Ignorado / não informado"},"race":{"1":"Branca","2":"Preta","3":"Amarela","4":"Parda","5":"Indígena","unknown":"Ignorada / não informada"},"birthWeightBand":{"under1500":"Menos de 1.500 g","1500-2499":"1.500 a 2.499 g","2500+":"2.500 g ou mais","unknown":"Não informado"},"gestationBand":{"under28":"Menos de 28 semanas","28-31":"28 a 31 semanas","32-36":"32 a 36 semanas","37-41":"37 a 41 semanas","42+":"42 semanas ou mais","unknown":"Não informada"},"maternalAgeBand":{"under20":"Menos de 20 anos","20-34":"20 a 34 anos","35+":"35 anos ou mais","unknown":"Não informada"},"delivery":{"1":"Vaginal","2":"Cesáreo","unknown":"Não informado"},"deathPlace":{"1":"Hospital","2":"Outro estabelecimento de saúde","3":"Domicílio","4":"Via pública","5":"Outro local","6":"Aldeia indígena","unknown":"Ignorado / não informado"},"medicalCare":{"1":"Sim","2":"Não","unknown":"Ignorada / não informada"}}
    applied_filters=[]
    for key,values in selected_filters.items():
        labels=[]
        for value in sorted(values):
            if key=="causeGroup": labels.append(f"{value} · {cid_names.get(value,'Não informada')}")
            elif key=="occurrenceMunicipality": labels.append(municipality_names.get(value,f"Município {value}"))
            else: labels.append(filter_values.get(key,{}).get(value,value))
        applied_filters.append({"label":filter_labels[key],"value":", ".join(labels)})
    return {"ok":True,"report":"sim-mortalidade-infantil","view":"full","flatTable":True,"file":"SIM · SINASC · CSV oficial","year":year,"month":month,"uf":uf,"state":PREDEFINED_UF_NAMES.get(uf,uf),"municipality":municipality_name,"municipalityCode":municipality,"rows":rows,"records":sum(item["deaths"] for item in rows),"births":births,"emptyStateMessage":f"Não há óbitos de menores de 1 ano com residência em {municipality_name} no mês {month:02d}/{year}.",
        "columns":[{"id":"cause","label":"CAUSA BÁSICA · CID-10","kind":"primary","primaryField":"causeName","secondaryField":"causeCode","filterFields":["causeName","causeCode"],"sortField":"causeName","type":"text","sticky":True},{"id":"chapter","label":"CAPÍTULO","field":"chapterName","type":"text"},{"id":"ageGroup","label":"FAIXA ETÁRIA","field":"ageGroup","type":"text"},{"id":"ageDays","label":"IDADE EM DIAS","field":"ageDays","type":"number"},{"id":"sex","label":"SEXO","field":"sex","type":"text"},{"id":"race","label":"RAÇA/COR","field":"race","type":"text"},{"id":"birthWeight","label":"PESO AO NASCER · G","field":"birthWeight","type":"number"},{"id":"gestationWeeks","label":"GESTAÇÃO · SEMANAS","field":"gestationWeeks","type":"number"},{"id":"maternalAge","label":"IDADE DA MÃE","field":"maternalAge","type":"number"},{"id":"delivery","label":"TIPO DE PARTO","field":"delivery","type":"text"},{"id":"place","label":"LOCAL DO ÓBITO","field":"place","type":"text"},{"id":"occurrence","label":"MUNICÍPIO DO ÓBITO","field":"occurrenceName","type":"text"},{"id":"establishment","label":"CNES DO ÓBITO","field":"establishmentCode","type":"text"},{"id":"medicalCare","label":"ASSISTÊNCIA MÉDICA","field":"medicalCare","type":"text"},{"id":"deaths","label":"ÓBITOS","metricId":"deaths","type":"number","decimals":0}],
        "metrics":[{"id":"deaths","label":"Óbitos < 1 ano","decimals":0}],
        "hasFilters":bool(selected_filters),"filters":applied_filters,
        "notes":[f"SIM atualizado em {sim.get('updatedAt') or 'data não informada'}; SINASC atualizado em {sinasc.get('updatedAt') or 'data não informada'}. Óbitos pela residência da criança e nascidos vivos pela residência da mãe, independentemente do local de ocorrência.","Cada linha da tabela é um registro público não fetal do SIM, sem nome, documento ou datas exatas. Os campos de peso, gestação, idade da mãe, parto, local e assistência aparecem somente quando informados. A faixa etária usa a diferença entre data de nascimento e data do óbito; registros sem as duas datas válidas não entram no numerador.","A taxa anual bruta por mil nascidos vivos só é mostrada para um ano completo anterior ao atual e sem filtros de mortalidade. A contagem de nascidos vivos é da população residente no município e período, mesmo quando filtros de perfil do óbito são aplicados. Dados recentes podem ser preliminares e revistos pelas fontes oficiais."],"cachedAt":time.time()}

def _sim_mortality_age_group(value: Any) -> str:
    raw=re.sub(r"\D","",str(value or ""))
    if len(raw)!=3 or raw[0]=="9": return "unknown"
    unit=int(raw[0]); amount=int(raw[1:])
    if unit in {1,2,3}: return "under1"
    if unit==5: return "60+"
    if unit!=4: return "unknown"
    if amount<1: return "under1"
    if amount<=17: return "1-17"
    if amount<=29: return "18-29"
    if amount<=59: return "30-59"
    return "60+"

def _sim_mortality_selected_filters(payload: dict[str,Any]) -> dict[str,set[str]]:
    allowed={
        "residenceOrigin":{"local","outside","unknown"},"residenceMunicipality":set(),"naturalityMunicipality":set(),
        "ageGroup":{"under1","1-17","18-29","30-59","60+","unknown"},"sex":{"1","2","unknown"},
        "race":{"1","2","3","4","5","unknown"},"education":{"0","1","2","3","4","5","unknown"},
        "maritalStatus":{"1","2","3","4","5","unknown"},"deathPlace":{"1","2","3","4","5","6","unknown"},
        "medicalAssistance":{"1","2","unknown"},"necropsy":{"1","2","unknown"},"certifier":{"1","2","3","4","5","unknown"}}
    raw=payload.get("simFilters") or {}
    if not isinstance(raw,dict) or len(raw)>len(allowed): raise ValueError("Os filtros do SIM são inválidos.")
    selected={}
    for key,values in raw.items():
        if key not in allowed or not isinstance(values,list) or len(values)>6000: raise ValueError("A seleção de filtros do SIM é inválida ou extensa demais.")
        clean={str(value).strip() for value in values if str(value).strip()}
        if key in {"residenceMunicipality","naturalityMunicipality"}:
            if any(not re.fullmatch(r"\d{6}",value) for value in clean): raise ValueError("Selecione códigos válidos de município de residência.")
        elif not clean.issubset(allowed[key]): raise ValueError("A seleção contém uma categoria SIM inválida.")
        if clean: selected[key]=clean
    return selected

def _sim_mortality_category(value: Any, choices: set[str], aliases: dict[str,str] | None = None) -> str:
    raw=str(value or "").strip().upper()
    if aliases and raw in aliases: raw=aliases[raw]
    return raw if raw in choices else "unknown"

def predefined_sim_mortality(payload: dict[str,Any], progress=None):
    """Aggregate public SIM deaths by week/cause, with optional grouped profile details."""
    year=payload.get("year"); month=payload.get("month")
    if not isinstance(year,int) or not 2000<=year<=date.today().year or not isinstance(month,int) or not 1<=month<=12: raise ValueError("Selecione um ano e um mês válidos para o SIM.")
    if str(payload.get("uf") or "").upper()!="PA" or str(payload.get("municipalityCode") or "")!="150140": raise ValueError("O relatório de mortalidade considera óbitos ocorridos em Belém.")
    view=str(payload.get("view") or "full")
    if view not in {"summary","detail","full"}: raise ValueError("Selecione uma visão válida do relatório de mortalidade.")
    week_index=payload.get("weekIndex") if view=="detail" else None
    if view=="detail" and (not isinstance(week_index,int) or not 1<=week_index<=53): raise ValueError("Selecione uma semana válida para detalhar.")
    cause_code=str(payload.get("causeCode") or "").strip().upper()
    if cause_code in {"NÃO INFORMADO","NOINFORMADO"}: cause_code="NI"
    if view=="detail" and cause_code and cause_code!="NI" and not re.fullmatch(r"[A-Z]\d{2}",cause_code): raise ValueError("A causa básica selecionada para detalhamento é inválida.")
    selected_filters=_sim_mortality_selected_filters(payload)
    target=cache_target("sim_mortality",{"version":6,"year":year,"municipality":"150140"})
    with interprocess_lock(target.with_suffix(".lock")):
        cached=cache_read(target)
        cache_lifetime=24*3600 if year==date.today().year else 30*86400
        if isinstance(cached,dict) and isinstance(cached.get("profiles"),list) and time.time()-float(cached.get("fetched_at",0))<cache_lifetime:
            profiles=cached["profiles"]; updated_at=cached.get("updatedAt")
        else:
            if progress: progress(5,"Baixando declarações públicas do SIM")
            archive,updated_at=_sinan_dengue_archive(year,"sim-mortalidade",progress)
            grouped={}
            jan_four=date(year,1,4); first_sunday=jan_four-timedelta(days=(jan_four.weekday()+1)%7)
            previous_first_sunday=(date(year-1,1,4)-timedelta(days=(date(year-1,1,4).weekday()+1)%7))
            next_first_sunday=(date(year+1,1,4)-timedelta(days=(date(year+1,1,4).weekday()+1)%7))
            try:
                with zipfile.ZipFile(archive) as bundle:
                    expected=f"Mortalidade_Geral_{year}.csv"
                    matches=[item for item in bundle.infolist() if not item.is_dir() and item.filename.replace("\\","/").rsplit("/",1)[-1].casefold()==expected.casefold()]
                    if len(matches)!=1 or not 0<matches[0].file_size<=SINAN_DENGUE_CSV_MAX_BYTES: raise ValueError("O pacote SIM não contém o CSV anual esperado.")
                    with bundle.open(matches[0]) as binary, io.TextIOWrapper(binary,encoding="latin1",newline="") as stream:
                        reader=csv.DictReader(stream,delimiter=";")
                        field_names={str(name or "").lstrip("\ufeff").strip().upper():name for name in (reader.fieldnames or [])}
                        required={"DTOBITO","CODMUNOCOR","CODMUNRES","CAUSABAS","TIPOBITO"}
                        if not required.issubset(field_names): raise ValueError("O CSV do SIM não contém os campos necessários ao relatório.")
                        def field(item,key):
                            actual=field_names.get(key)
                            return str(item.get(actual) or "").strip() if actual else ""
                        for number,item in enumerate(reader,1):
                            if progress and number%50000==0: progress(min(88,32+int(54*binary.tell()/max(1,matches[0].file_size))),f"Lendo óbitos do SIM · {number:,} registros".replace(",","."))
                            if re.sub(r"\D","",field(item,"CODMUNOCOR"))[:6]!="150140": continue
                            raw=field(item,"DTOBITO")
                            if re.fullmatch(r"\d{8}",raw): day,mo,yr=int(raw[:2]),int(raw[2:4]),int(raw[4:])
                            else:
                                try: parsed=date.fromisoformat(raw[:10]); day,mo,yr=parsed.day,parsed.month,parsed.year
                                except ValueError: continue
                            try: death_date=date(yr,mo,day)
                            except ValueError: continue
                            if yr!=year or field(item,"TIPOBITO")!="2": continue
                            cause=re.sub(r"[^A-Z0-9]","",field(item,"CAUSABAS").upper())[:3] or "NI"
                            chapter=next(((start,end,label) for start,end,label in SIM_CID_CHAPTERS if start<=cause<=end),None)
                            chapter_index=SIM_CID_CHAPTERS.index(chapter)+1 if chapter else len(SIM_CID_CHAPTERS)+1
                            week_anchor=previous_first_sunday if death_date<first_sunday else next_first_sunday if death_date>=next_first_sunday else first_sunday
                            week_year=year-1 if death_date<first_sunday else year+1 if death_date>=next_first_sunday else year
                            week=(death_date-week_anchor).days//7+1
                            if not 1<=week<=53: continue
                            residence=re.sub(r"\D","",field(item,"CODMUNRES")); residence=residence[:6] if len(residence)>=6 else ""
                            if residence in {"000000","999999"}: residence=""
                            naturality=re.sub(r"\D","",field(item,"CODMUNNATU")); naturality=naturality[:6] if len(naturality)>=6 and naturality[:6] not in {"000000","999999"} else ""
                            establishment_raw=re.sub(r"\D","",field(item,"CODESTAB"))
                            establishment=establishment_raw if len(establishment_raw) in {7,8} else ""
                            sex=_sim_mortality_category(field(item,"SEXO"),{"1","2"},{"M":"1","F":"2","0":"unknown","9":"unknown","I":"unknown"})
                            race=_sim_mortality_category(field(item,"RACACOR"),{"1","2","3","4","5"})
                            education=_sim_mortality_category(field(item,"ESC2010"),{"0","1","2","3","4","5"})
                            marital=_sim_mortality_category(field(item,"ESTCIV"),{"1","2","3","4","5"})
                            death_place=_sim_mortality_category(field(item,"LOCOCOR"),{"1","2","3","4","5","6"})
                            assistance=_sim_mortality_category(field(item,"ASSISTMED"),{"1","2"})
                            necropsy=_sim_mortality_category(field(item,"NECROPSIA"),{"1","2"})
                            certifier=_sim_mortality_category(field(item,"ATESTANTE"),{"1","2","3","4","5"})
                            age_group=_sim_mortality_age_group(field(item,"IDADE"))
                            occupation=re.sub(r"\D","",field(item,"OCUP")); occupation=occupation if len(occupation)==6 and occupation not in {"000000","999999"} else ""
                            key=(mo,week,week_year,cause,chapter_index,residence,naturality,age_group,sex,race,education,marital,death_place,establishment,assistance,necropsy,certifier,occupation)
                            grouped[key]=grouped.get(key,0)+1
            finally: archive.unlink(missing_ok=True)
            fields=("month","week","weekYear","causeCode","chapterIndex","residenceCode","naturalityCode","ageGroup","sexCode","raceCode","educationCode","maritalCode","deathPlaceCode","establishmentCode","medicalAssistanceCode","necropsyCode","certifierCode","occupationCode")
            profiles=[{**dict(zip(fields,key)),"deaths":count} for key,count in grouped.items()]
            cache_write(target,{"fetched_at":time.time(),"updatedAt":updated_at,"profiles":profiles},max_bytes=48_000_000,keep=10)

    def matches(profile):
        values={"residenceOrigin":"local" if profile["residenceCode"]=="150140" else "outside" if profile["residenceCode"] else "unknown","residenceMunicipality":profile["residenceCode"],"naturalityMunicipality":profile["naturalityCode"],"ageGroup":profile["ageGroup"],"sex":profile["sexCode"],"race":profile["raceCode"],"education":profile["educationCode"],"maritalStatus":profile["maritalCode"],"deathPlace":profile["deathPlaceCode"],"medicalAssistance":profile["medicalAssistanceCode"],"necropsy":profile["necropsyCode"],"certifier":profile["certifierCode"]}
        return all(values[key] in selected for key,selected in selected_filters.items())
    selected=[profile for profile in profiles if profile["month"]==month and matches(profile)]
    if view=="detail":
        selected=[profile for profile in selected if profile["week"]==week_index and (not cause_code or profile["causeCode"]==cause_code)]
        detail_fields=("month","week","weekYear","causeCode","chapterIndex","residenceCode","naturalityCode","ageGroup","sexCode","raceCode","educationCode","maritalCode","deathPlaceCode","establishmentCode","medicalAssistanceCode","necropsyCode","certifierCode","occupationCode")
        detail_rows={}
        for profile in selected:
            key=tuple(profile[field] for field in detail_fields); detail_rows[key]=detail_rows.get(key,0)+profile["deaths"]
        selected=[{**dict(zip(detail_fields,key)),"deaths":count} for key,count in detail_rows.items()]
    elif view in {"summary","full"}:
        grouped={}
        for profile in selected:
            key=(profile["month"],profile["week"],profile["weekYear"])+( (profile["causeCode"],profile["chapterIndex"]) if view=="full" else ())
            row=grouped.setdefault(key,{"month":key[0],"week":key[1],"weekYear":key[2],"deaths":0,"residents":0,"otherResidents":0,"unknownResidence":0})
            if view=="full": row.update({"causeCode":key[3],"chapterIndex":key[4]})
            row["deaths"]+=profile["deaths"]
            residence_key="residents" if profile["residenceCode"]=="150140" else "otherResidents" if profile["residenceCode"] else "unknownResidence"
            row[residence_key]+=profile["deaths"]
        selected=list(grouped.values())

    cid_names=_sim_cid_names() if view in {"detail","full"} else {}
    rows=[]
    if view in {"summary","full"}:
        for item in selected:
            cause=item.get("causeCode","")
            chapter=next((label for start,end,label in SIM_CID_CHAPTERS if start<=cause<=end),"Causa básica não classificada") if cause and cause!="NI" else "Causa básica não classificada"
            row={**item,"code":str(item["week"]),"weekName":f"Semana {item['week']:02d}"+(f" · {item['weekYear']}" if item["weekYear"]!=year else "")}
            if view=="full": row.update({"causeCode":"Não informado" if cause=="NI" else cause,"causeName":cid_names.get(cause,"Descrição não disponível na tabela CID local"),"chapterName":chapter})
            rows.append(row)
        rows.sort(key=lambda row:(row["weekYear"],row["week"],-row["deaths"],row.get("causeCode","")))
    else:
        try: municipalities=_sinan_ibge_municipalities()
        except Exception: municipalities={}
        establishment_lookup={item["establishmentCode"]:(item["establishmentCode"] if len(item["establishmentCode"])==7 else item["establishmentCode"][1:] if len(item["establishmentCode"])==8 and item["establishmentCode"].startswith("0") else "") for item in selected if item["establishmentCode"]}
        establishment_codes=sorted({code for code in establishment_lookup.values() if code})
        if progress: progress(92,"Completando nomes de municípios e unidades do CNES")
        try: establishment_names,_=_sinasc_maternity_names(establishment_codes)
        except Exception: establishment_names={}
        labels={
            "ageGroup":{"under1":"Menor de 1 ano","1-17":"1 a 17 anos","18-29":"18 a 29 anos","30-59":"30 a 59 anos","60+":"60 anos ou mais","unknown":"Não informado"},
            "sexCode":{"1":"Masculino","2":"Feminino","unknown":"Ignorado / não informado"},"raceCode":{"1":"Branca","2":"Preta","3":"Amarela","4":"Parda","5":"Indígena","unknown":"Ignorada / não informada"},
            "educationCode":{"0":"Sem escolaridade","1":"Fundamental I","2":"Fundamental II","3":"Ensino médio","4":"Superior incompleto","5":"Superior completo","unknown":"Ignorada / não informada"},
            "maritalCode":{"1":"Solteiro(a)","2":"Casado(a)","3":"Viúvo(a)","4":"Separado(a) / divorciado(a)","5":"União estável","unknown":"Ignorada / não informada"},
            "deathPlaceCode":{"1":"Hospital","2":"Outro estabelecimento de saúde","3":"Domicílio","4":"Via pública","5":"Outro local","6":"Aldeia indígena","unknown":"Ignorado / não informado"},
            "medicalAssistanceCode":{"1":"Sim","2":"Não","unknown":"Ignorada / não informada"},"necropsyCode":{"1":"Sim","2":"Não","unknown":"Ignorada / não informada"},
            "certifierCode":{"1":"Médico assistente","2":"Médico substituto","3":"IML","4":"SVO","5":"Outro médico","unknown":"Ignorado / não informado"}}
        for item in selected:
            residence=item["residenceCode"]; naturality=item["naturalityCode"]; establishment=item["establishmentCode"]; cause=item["causeCode"]
            chapter=next((label for start,end,label in SIM_CID_CHAPTERS if start<=cause<=end),"Causa básica não classificada") if cause!="NI" else "Causa básica não classificada"
            rows.append({**item,"causeName":cid_names.get(cause,"Descrição não disponível na tabela CID local"),"causeCode":"Não informado" if cause=="NI" else cause,"chapterName":chapter,
                "residenceName":municipalities.get(residence,"Residência não informada" if not residence else f"Município {residence}"),"naturalityName":municipalities.get(naturality,"Não informado" if not naturality else f"Município {naturality}"),
                "ageGroupName":labels["ageGroup"].get(item["ageGroup"],"Não informado"),"sexName":labels["sexCode"].get(item["sexCode"],"Ignorado / não informado"),"raceName":labels["raceCode"].get(item["raceCode"],"Ignorada / não informada"),
                "educationName":labels["educationCode"].get(item["educationCode"],"Ignorada / não informada"),"maritalStatusName":labels["maritalCode"].get(item["maritalCode"],"Ignorada / não informada"),
                "deathPlaceName":labels["deathPlaceCode"].get(item["deathPlaceCode"],"Ignorado / não informado"),"establishmentName":establishment_names.get(establishment_lookup.get(establishment,"")) or (f"CNES {establishment}" if establishment else "Não informado"),
                "medicalAssistanceName":labels["medicalAssistanceCode"].get(item["medicalAssistanceCode"],"Ignorada / não informada"),"necropsyName":labels["necropsyCode"].get(item["necropsyCode"],"Ignorada / não informada"),
                "certifierName":labels["certifierCode"].get(item["certifierCode"],"Ignorado / não informado"),"occupationName":f"CBO {item['occupationCode']}" if item["occupationCode"] else "Não informado"})
        rows.sort(key=lambda row:(row["residenceName"].casefold(),row["ageGroupName"],row["sexName"],row["causeCode"]))

    if view=="detail":
        for row in rows:
            row["weekName"]=f"Semana {row['week']:02d}"
            row["residents"]=row["deaths"] if row["residenceCode"]=="150140" else 0
            row["otherResidents"]=row["deaths"] if row["residenceCode"] and row["residenceCode"]!="150140" else 0
            row["unknownResidence"]=row["deaths"] if not row["residenceCode"] else 0
    total=sum(row["deaths"] for row in rows)
    resident_total=sum(row.get("residents",0) for row in rows); other_total=sum(row.get("otherResidents",0) for row in rows); unknown_total=sum(row.get("unknownResidence",0) for row in rows)
    if progress: progress(98,"Preparando o painel de mortalidade")
    week_label=f"Semana {week_index:02d}"+(f" · {cause_code}" if cause_code and cause_code!="NI" else "") if view=="detail" else None
    if view=="detail":
        columns=[{"id":"cause","label":"CAUSA BÁSICA · CID-10","kind":"primary","primaryField":"causeName","secondaryField":"causeCode","filterFields":["causeName","causeCode"],"sortField":"causeName","type":"text","sticky":True},{"id":"residence","label":"MUNICÍPIO DE RESIDÊNCIA","kind":"primary","primaryField":"residenceName","secondaryField":"residenceCode","secondaryPrefix":"IBGE ","filterFields":["residenceName","residenceCode"],"sortField":"residenceName","type":"text"}]
        columns.extend([{"id":"naturality","label":"MUNICÍPIO DE NASCIMENTO","field":"naturalityName","type":"text"},{"id":"ageGroup","label":"FAIXA ETÁRIA","field":"ageGroupName","type":"text"},{"id":"sex","label":"SEXO","field":"sexName","type":"text"},{"id":"race","label":"RAÇA/COR","field":"raceName","type":"text"},{"id":"education","label":"ESCOLARIDADE","field":"educationName","type":"text"},{"id":"maritalStatus","label":"SITUAÇÃO CONJUGAL","field":"maritalStatusName","type":"text"},{"id":"deathPlace","label":"LOCAL DO ÓBITO","field":"deathPlaceName","type":"text"},{"id":"establishment","label":"ESTABELECIMENTO DE OCORRÊNCIA","kind":"primary","primaryField":"establishmentName","secondaryField":"establishmentCode","secondaryPrefix":"CNES ","filterFields":["establishmentName","establishmentCode"],"type":"text"},{"id":"medicalAssistance","label":"ASSISTÊNCIA MÉDICA","field":"medicalAssistanceName","type":"text"},{"id":"necropsy","label":"NECROPSIA","field":"necropsyName","type":"text"},{"id":"certifier","label":"MÉDICO ATESTANTE","field":"certifierName","type":"text"},{"id":"occupation","label":"OCUPAÇÃO · CBO","field":"occupationName","type":"text"},{"id":"deaths","label":"ÓBITOS","metricId":"deaths","type":"number","decimals":0}])
    else:
        columns=[{"id":"week","label":"SEMANA","kind":"primary","primaryField":"weekName","filterFields":["weekName","week"],"sortField":"week","type":"text","sticky":True}]
        if view=="full": columns.extend([{"id":"cause","label":"CAUSA BÁSICA · CID-10","kind":"primary","primaryField":"causeName","secondaryField":"causeCode","filterFields":["causeName","causeCode"],"sortField":"causeName","type":"text"},{"id":"chapter","label":"CAPÍTULO · CID-10","field":"chapterName","type":"text"}])
        columns.extend([{"id":"deaths","label":"ÓBITOS NÃO FETAIS","metricId":"deaths","type":"number","decimals":0},{"id":"residents","label":"RESIDENTES EM BELÉM","metricId":"residents","type":"number","decimals":0},{"id":"otherResidents","label":"RESIDENTES DE OUTROS MUNICÍPIOS","metricId":"otherResidents","type":"number","decimals":0},{"id":"unknownResidence","label":"RESIDÊNCIA NÃO INFORMADA","metricId":"unknownResidence","type":"number","decimals":0},{"id":"detail","label":"DETALHAMENTO","kind":"action","actionType":"sim-detail","actionLabel":"Detalhar →"}])
    metric_labels=(("deaths","Óbitos não fetais"),("residents","Residentes em Belém"),("otherResidents","Residentes de outros municípios"),("unknownResidence","Residência não informada"))
    filter_labels={"residenceOrigin":"Origem da residência","residenceMunicipality":"Município de residência","naturalityMunicipality":"Município de nascimento","ageGroup":"Faixa etária","sex":"Sexo","race":"Raça/cor","education":"Escolaridade","maritalStatus":"Situação conjugal","deathPlace":"Local do óbito","medicalAssistance":"Assistência médica","necropsy":"Necropsia","certifier":"Tipo de atestante"}
    filter_value_labels={"residenceOrigin":{"local":"Residente em Belém","outside":"Residente em outro município","unknown":"Residência não informada"},"ageGroup":{"under1":"Menor de 1 ano","1-17":"1 a 17 anos","18-29":"18 a 29 anos","30-59":"30 a 59 anos","60+":"60 anos ou mais","unknown":"Não informado"},"sex":{"1":"Masculino","2":"Feminino","unknown":"Ignorado / não informado"},"race":{"1":"Branca","2":"Preta","3":"Amarela","4":"Parda","5":"Indígena","unknown":"Ignorada / não informada"},"education":{"0":"Sem escolaridade","1":"Fundamental I","2":"Fundamental II","3":"Ensino médio","4":"Superior incompleto","5":"Superior completo","unknown":"Ignorada / não informada"},"maritalStatus":{"1":"Solteiro(a)","2":"Casado(a)","3":"Viúvo(a)","4":"Separado(a) / divorciado(a)","5":"União estável","unknown":"Ignorada / não informada"},"deathPlace":{"1":"Hospital","2":"Outro estabelecimento de saúde","3":"Domicílio","4":"Via pública","5":"Outro local","6":"Aldeia indígena","unknown":"Ignorado / não informado"},"medicalAssistance":{"1":"Sim","2":"Não","unknown":"Ignorada / não informada"},"necropsy":{"1":"Sim","2":"Não","unknown":"Ignorada / não informada"},"certifier":{"1":"Médico assistente","2":"Médico substituto","3":"IML","4":"SVO","5":"Outro médico","unknown":"Ignorado / não informado"}}
    filters=[{"label":filter_labels[key],"value":", ".join(filter_value_labels.get(key,{}).get(value,f"Código IBGE {value}" if key in {"residenceMunicipality","naturalityMunicipality"} else value) for value in sorted(values))} for key,values in selected_filters.items()]
    notes=[f"Fonte: SIM, arquivo anual público atualizado em {updated_at or 'data não informada'}. Recorte por município de ocorrência; competência pelo mês da data do óbito.","A tabela principal conta óbitos não fetais (TIPOBITO = 2). A semana epidemiológica é calculada pela data do óbito, de domingo a sábado. Dados recentes podem ser preliminares e revistos.","O detalhamento apresenta contagens agrupadas por residência e características disponíveis na declaração. Não exibe nomes, documentos ou datas individuais; campos ausentes são identificados como não informados.","O estabelecimento é o local de ocorrência registrado no SIM (CODESTAB), com nome consultado no CNES atual. Não significa necessariamente a unidade notificadora, e o cadastro pode diferir do histórico.","Residência não informada não entra nas contagens de Belém ou de outros municípios."]
    return {"ok":True,"report":"sim-mortalidade","view":view,"flatTable":True,"file":"SIM · CSV oficial","year":year,"month":month,"uf":"PA","state":"Pará","municipality":"Belém","municipalityCode":"150140","establishmentCode":str(week_index) if week_index else None,"establishmentName":week_label,"rows":rows,"records":total,"columns":columns,"metrics":[{"id":key,"label":label,"decimals":0} for key,label in metric_labels],"kpis":[{"label":"ÓBITOS NÃO FETAIS","value":{"value":total}},{"label":"RESIDENTES EM BELÉM","value":{"value":resident_total}},{"label":"OUTROS MUNICÍPIOS","value":{"value":other_total}},{"label":"RESIDÊNCIA NÃO INFORMADA","value":{"value":unknown_total}}],"filters":filters,"emptyStateMessage":f"Não há óbitos não fetais em Belém em {month:02d}/{year} com os filtros selecionados. Os dados recentes podem ser preliminares.","notes":notes,"cachedAt":time.time()}

SRAG_METRICS=(
    ("cases","CASOS DE SRAG"),("influenza","INFLUENZA"),("covid","COVID-19"),
    ("vsr","VSR"),("otherViral","OUTROS VÍRUS"),("otherAgent","OUTROS AGENTES"),
    ("unspecified","SEM AGENTE DEFINIDO"),("icu","UTI"),("deaths","ÓBITOS"),
)
SRAG_AGE_GROUPS=(("lt1","Menor de 1 ano"),("1to4","1 a 4 anos"),("5to19","5 a 19 anos"),("20to39","20 a 39 anos"),("40to59","40 a 59 anos"),("60plus","60 anos ou mais"),("unknown","Idade não informada"))

def _srag_age_group(row, fields):
    unit=row[fields["TP_IDADE"]].strip()
    raw=row[fields["NU_IDADE_N"]].strip()
    if not raw.isdigit(): return "unknown"
    age=int(raw)
    if unit in {"1","2"}: return "lt1"
    if unit!="3": return "unknown"
    if age<1: return "lt1"
    if age<5: return "1to4"
    if age<20: return "5to19"
    if age<40: return "20to39"
    if age<60: return "40to59"
    return "60plus"

def _srag_source(year: int, municipality: str, progress=None):
    """Read one official annual SIVEP-Gripe CSV as a stream; cache only municipal aggregates."""
    target=cache_target("srag_weekly",{"version":1,"year":year,"municipality":municipality})
    with interprocess_lock(target.with_suffix(".lock")):
        cached=cache_read(target)
        ttl=12*3600 if year==date.today().year else 30*86400
        if isinstance(cached,dict) and isinstance(cached.get("weeks"),list) and time.time()-float(cached.get("fetched_at",0))<ttl:
            return cached
        if progress: progress(5,"Localizando o banco público do SIVEP-Gripe")
        catalog_url="https://dadosabertos.saude.gov.br/dataset/srag-2019-a-2026"
        request=urllib.request.Request(catalog_url,headers={"User-Agent":"TabulaSUS/1.0","Accept":"text/html"})
        with open_verified_https(request,"dadosabertos.saude.gov.br",35) as response:
            catalog=response.read(8*1024*1024+1)
        if len(catalog)>8*1024*1024: raise ValueError("O catálogo oficial da SRAG excedeu o limite de leitura.")
        pattern=rf"https://s3\.sa-east-1\.amazonaws\.com/ckan\.saude\.gov\.br/SRAG/{year}/INFLUD{year%100:02d}-\d{{2}}-\d{{2}}-\d{{4}}\.csv"
        links=set(re.findall(pattern,catalog.decode("utf-8","replace"),flags=re.I))
        if not links: raise ValueError(f"O catálogo oficial ainda não oferece o arquivo CSV de SRAG para {year}.")
        def source_date(url):
            match=re.search(r"-(\d{2})-(\d{2})-(\d{4})\.csv$",url)
            return (int(match[3]),int(match[2]),int(match[1])) if match else (0,0,0)
        url=max(links,key=source_date)
        updated_at="-".join(str(part).zfill(2 if index else 4) for index,part in enumerate(source_date(url)))
        if isinstance(cached,dict) and isinstance(cached.get("weeks"),list) and cached.get("sourceUrl")==url:
            cached["fetched_at"]=time.time()
            cache_write(target,cached,max_bytes=20_000_000,keep=8)
            return cached
        if progress: progress(10,"Lendo o arquivo anual de SRAG · primeira consulta pode levar alguns minutos")
        request=urllib.request.Request(url,headers={"User-Agent":"TabulaSUS/1.0","Accept":"text/csv"})
        grouped={}; age_grouped={}; read_count=0
        with open_verified_https(request,SINAN_DENGUE_ARCHIVE_HOST,120) as response:
            size=int(response.headers.get("Content-Length") or 0)
            if not 0<size<=700*1024*1024: raise ValueError("O tamanho do arquivo oficial de SRAG não está dentro do limite seguro.")
            with io.TextIOWrapper(response,encoding="utf-8-sig",errors="replace",newline="") as stream:
                reader=csv.reader(stream,delimiter=";")
                headers={name.strip().strip('"'):index for index,name in enumerate(next(reader,[]))}
                needed={"DT_SIN_PRI","SEM_PRI","CO_MUN_RES","CLASSI_FIN","PCR_VSR","AN_VSR","UTI","EVOLUCAO","TP_IDADE","NU_IDADE_N"}
                if not needed.issubset(headers): raise ValueError("O arquivo oficial de SRAG não contém os campos necessários ao relatório.")
                for row in reader:
                    read_count+=1
                    if read_count%10000==0 and progress:
                        remaining=getattr(response,"length",None)
                        percent=12+int(75*(size-remaining)/size) if isinstance(remaining,int) else 12
                        progress(min(87,percent),f"Lendo notificações de SRAG · {read_count:,} registros".replace(",","."))
                    if len(row)<len(headers) or row[headers["CO_MUN_RES"]].strip()!=municipality: continue
                    raw_date=row[headers["DT_SIN_PRI"]].strip()[:10]
                    try: onset=date.fromisoformat(raw_date)
                    except ValueError: continue
                    if onset.year!=year: continue
                    raw_week=row[headers["SEM_PRI"]].strip()
                    if not raw_week.isdigit() or not 1<=int(raw_week)<=53: continue
                    week=int(raw_week); month=onset.month
                    classification=row[headers["CLASSI_FIN"]].strip()
                    if classification=="1": agent="influenza"
                    elif classification=="5": agent="covid"
                    elif classification=="2": agent="vsr" if row[headers["PCR_VSR"]].strip()=="1" or row[headers["AN_VSR"]].strip()=="1" else "otherViral"
                    elif classification=="3": agent="otherAgent"
                    else: agent="unspecified"
                    base={key:0 for key,_ in SRAG_METRICS}
                    weekly=grouped.setdefault((month,week),{"month":month,"week":week,"code":str(week),"weekName":f"Semana epidemiológica {week:02d}",**base})
                    age=_srag_age_group(row,headers)
                    age_item=age_grouped.setdefault((month,week,age),{"month":month,"week":week,"ageCode":age,"ageName":dict(SRAG_AGE_GROUPS)[age],**base})
                    for item in (weekly,age_item):
                        item["cases"]+=1; item[agent]+=1
                        if row[headers["UTI"]].strip()=="1": item["icu"]+=1
                        if row[headers["EVOLUCAO"]].strip()=="2": item["deaths"]+=1
        result={"fetched_at":time.time(),"updatedAt":updated_at,"sourceUrl":url,"weeks":list(grouped.values()),"ages":list(age_grouped.values()),"scanned":read_count}
        cache_write(target,result,max_bytes=20_000_000,keep=8)
        return result

def predefined_srag_weekly(payload: dict[str,Any], progress=None):
    if progress is None: return _predefined_srag_weekly_impl(payload,None)
    stop=threading.Event(); progress_lock=threading.Lock()
    latest={"percent":5,"stage":"Preparando o arquivo oficial do SIVEP-Gripe"}
    def publish(percent,stage):
        with progress_lock:
            latest["percent"]=percent; latest["stage"]=stage
            progress(percent,stage)
    def heartbeat():
        while not stop.wait(4):
            try:
                with progress_lock: progress(latest["percent"],latest["stage"])
            except Exception: pass
    thread=threading.Thread(target=heartbeat,name="srag-progress-heartbeat",daemon=True)
    thread.start()
    try: return _predefined_srag_weekly_impl(payload,publish)
    finally:
        stop.set(); thread.join(timeout=1)

def _predefined_srag_weekly_impl(payload: dict[str,Any], progress=None):
    year=payload.get("year"); month=payload.get("month"); municipality=str(payload.get("municipalityCode") or "")
    uf=str(payload.get("uf") or "").upper(); view=str(payload.get("view") or "summary")
    if not isinstance(year,int) or not 2025<=year<=date.today().year or not isinstance(month,int) or not 1<=month<=12:
        raise ValueError("Selecione um mês de 2025 em diante para o relatório de SRAG.")
    if uf not in PREDEFINED_UF_CODES or not re.fullmatch(r"\d{6}",municipality) or municipality[:2]!=PREDEFINED_UF_CODES[uf]:
        raise ValueError("Selecione um município de residência válido para o relatório de SRAG.")
    if view not in {"summary","detail","full"}: raise ValueError("Selecione uma visão válida do relatório de SRAG.")
    week=payload.get("weekIndex") if view=="detail" else None
    if view=="detail" and (not isinstance(week,int) or not 1<=week<=53): raise ValueError("Selecione uma semana epidemiológica para detalhar.")
    data=_srag_source(year,municipality,progress)
    if progress: progress(95,"Preparando a evolução semanal da SRAG")
    source=data["ages"] if view in {"detail","full"} else data["weeks"]
    rows=[{**item,"weekName":f"Semana epidemiológica {item['week']:02d}"} for item in source if item["month"]==month and (view!="detail" or item["week"]==week)]
    rows.sort(key=(lambda item:(item["week"],next((index for index,(code,_) in enumerate(SRAG_AGE_GROUPS) if code==item["ageCode"]),99))) if view=="full" else (lambda item:next((index for index,(code,_) in enumerate(SRAG_AGE_GROUPS) if code==item["ageCode"]),99)) if view=="detail" else (lambda item:item["week"]))
    totals={key:sum(item[key] for item in rows) for key,_ in SRAG_METRICS}
    primary={"id":"age" if view=="detail" else "week","label":"FAIXA ETÁRIA" if view=="detail" else "SEMANA EPIDEMIOLÓGICA","kind":"primary","primaryField":"ageName" if view=="detail" else "weekName","sortField":"ageName" if view=="detail" else "week","type":"text","sticky":True}
    columns=[primary,*([{"id":"age","label":"FAIXA ETÁRIA","field":"ageName","sortField":"ageName","type":"text"}] if view=="full" else []),*({"id":key,"label":label,"metricId":key,"type":"number","decimals":0} for key,label in SRAG_METRICS)]
    if view=="summary": columns.append({"id":"detail","label":"DETALHAR","kind":"action","actionLabel":"Detalhar →"})
    municipality_name=_report_label(payload.get("municipalityName") or "")[:100] or f"Município {municipality}"
    notes=[f"Fonte: SIVEP-Gripe, banco público anual de {year}, publicado em {data['updatedAt']}. Recorte por município de residência ({municipality_name}, {uf}); mês e semana do início dos sintomas.",
           "As categorias de agente usam a classificação final do registro. VSR é separado dos outros vírus quando o exame PCR ou antígeno está positivo; coinfecções permanecem no grupo da classificação final. Sem agente definido inclui casos pendentes e não especificados.",
           "UTI e óbitos são contados entre os casos da tabela. Dados recentes podem ser incompletos e são revistos; números não equivalem a internações faturadas no SIH."]
    return {"ok":True,"report":"srag-semanal","view":view,"flatTable":True,"file":"SIVEP-Gripe · CSV oficial","year":year,"month":month,"uf":uf,"state":PREDEFINED_UF_NAMES[uf],"municipality":municipality_name,"municipalityCode":municipality,"updatedAt":data["updatedAt"],"establishmentCode":str(week) if week else None,"establishmentName":f"Semana epidemiológica {week:02d}" if week else None,"rows":rows,"records":totals["cases"],"columns":columns,"metrics":[{"id":key,"label":label.title(),"decimals":0} for key,label in SRAG_METRICS],"kpis":[{"label":"CASOS DE SRAG","value":{"value":totals["cases"]}},{"label":"PASSARAM POR UTI","value":{"value":totals["icu"]}},{"label":"ÓBITOS REGISTRADOS","value":{"value":totals["deaths"]}}],"notes":notes,"emptyStateMessage":f"Não há registros de SRAG com início dos sintomas em {month:02d}/{year} para {municipality_name} na base publicada em {data['updatedAt']}. Isso não confirma ausência de casos.","cachedAt":time.time()}

SISAGUA_FIRST_YEAR=2014
SISAGUA_RAD_PARAMETERS=(("cloro residual livre","freeChlorine","CLORO RESIDUAL LIVRE"),("cloro residual combinado","combinedChlorine","CLORO RESIDUAL COMBINADO"),("dioxido de cloro","chlorineDioxide","DIÓXIDO DE CLORO"))
SISAGUA_SUPPLY_TYPES=(("SAA","saa","SAA · SISTEMA"),("SAC","sac","SAC · SOLUÇÃO COLETIVA"),("SAI","sai","SAI · SOLUÇÃO INDIVIDUAL"),("CARRO-PIPA","truck","CARRO-PIPA"))
SISAGUA_EXCLUDED_MOTIVES={"surto","desastre"}
SISAGUA_COUNT_KEYS=("rad","freeChlorine","combinedChlorine","chlorineDioxide","saa","sac","sai","truck","otherSupply","excluded")

def sisagua_rad_minimum(population: int) -> int:
    """Monthly minimum of RAD analyses (Diretriz Nacional do Plano de Amostragem, 2016, Tabela 1).

    The fractional increments are rounded up: Vitória/ES (355.875 hab.) gives
    20 + 355.875/20.000 = 37,8 → 38 per month, the value printed by the SISAGUA
    report "Cumprimento da Diretriz Nacional - Parâmetros Básicos".
    """
    population=max(0,int(population))
    def ceil_div(value,step): return -(-value//step)
    if population<=5000: return 6
    if population<=10000: return 9
    if population<=50000: return 8+ceil_div(population,7500)
    if population<=200000: return 10+ceil_div(population,10000)
    if population<=500000: return 20+ceil_div(population,20000)
    return 35+ceil_div(population,50000)

def _sisagua_fold(value: Any) -> str:
    text=unicodedata.normalize("NFD",str(value or "")).encode("ascii","ignore").decode("ascii")
    return re.sub(r"\s+"," ",text).strip().casefold()

def _sisagua_archive_download(year: int, progress=None):
    """Fetch the annual SISAGUA vigilância (parâmetros básicos) CSV package from the official open-data host."""
    folder=UPLOADS/".cache"/"sisagua-source"
    folder.mkdir(parents=True,exist_ok=True)
    for old in folder.glob("sisagua-*.part"):
        try:
            if time.time()-old.stat().st_mtime>86400: old.unlink(missing_ok=True)
        except OSError: pass
    url=f"https://{SINAN_DENGUE_ARCHIVE_HOST}/ckan.saude.gov.br/SISAGUA/vigilancia_parametros_basicos_{year}_csv.zip"
    request=urllib.request.Request(url,headers={"User-Agent":"TabulaSUS/1.0","Accept":"application/zip"})
    fd,name=tempfile.mkstemp(prefix="sisagua-",suffix=".part",dir=str(folder)); os.close(fd)
    temp=Path(name)
    limit=768*1024*1024
    try:
        with open_verified_https(request,SINAN_DENGUE_ARCHIVE_HOST,120) as response, temp.open("wb") as output:
            size=int(response.headers.get("Content-Length") or 0)
            modified=response.headers.get("Last-Modified")
            try: updated_at=parsedate_to_datetime(modified).date().isoformat() if modified else date.today().isoformat()
            except (TypeError,ValueError,OverflowError): updated_at=date.today().isoformat()
            if size>limit: raise ValueError("O arquivo anual do SISAGUA ultrapassa o limite seguro de download.")
            if shutil.disk_usage(folder).free<(size or 256*1024*1024)*6+64*1024*1024: raise ValueError("Espaço insuficiente para baixar e ler o SISAGUA.")
            received=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                received+=len(chunk)
                if received>limit or (size and received>size): raise ValueError("O download do SISAGUA excedeu o tamanho esperado.")
                output.write(chunk)
                if progress: progress(min(40,5+int(35*received/max(size,received))),f"Baixando SISAGUA {year} · {received/1048576:.0f} MB"+(f" de {size/1048576:.0f} MB" if size else ""))
        if size and received!=size: raise ValueError("O download do SISAGUA terminou incompleto.")
        result=temp
        temp=None
        return result,updated_at
    except urllib.error.HTTPError as exc:
        if exc.code in {403,404}: raise ValueError(f"O arquivo oficial do SISAGUA de {year} ainda não foi publicado.") from exc
        raise ValueError(f"O servidor oficial do SISAGUA respondeu com HTTP {exc.code}.") from exc
    except (OSError,TimeoutError,urllib.error.URLError) as exc:
        raise ValueError(f"Não foi possível baixar o arquivo oficial do SISAGUA: {exc}") from exc
    finally:
        if temp is not None: temp.unlink(missing_ok=True)

def _sisagua_cache(year: int, uf: str):
    return cache_target("sisagua_rad",{"version":1,"year":year,"uf":uf})

def _sisagua_source(year: int, uf: str, progress=None):
    """Aggregate RAD analyses of one annual SISAGUA file by municipality, month and supply solution.

    The national file (≈1 GB of CSV) is read once; aggregates for every UF are
    cached so other states and municipalities open instantly afterwards.
    """
    ttl=24*3600 if year>=date.today().year-1 else 30*86400
    target=_sisagua_cache(year,uf)
    cached=cache_read(target)
    if isinstance(cached,dict) and isinstance(cached.get("municipalities"),dict) and time.time()-float(cached.get("fetched_at",0))<ttl:
        return cached
    folder=UPLOADS/".cache"/"sisagua-source"
    folder.mkdir(parents=True,exist_ok=True)
    with interprocess_lock(folder/f"sisagua-{year}.lock"):
        cached=cache_read(target)
        if isinstance(cached,dict) and isinstance(cached.get("municipalities"),dict) and time.time()-float(cached.get("fetched_at",0))<ttl:
            return cached
        if progress: progress(5,f"Baixando o arquivo anual de vigilância do SISAGUA {year}")
        try: archive,updated_at=_sisagua_archive_download(year,progress)
        except (OSError,ValueError,TimeoutError):
            if isinstance(cached,dict) and isinstance(cached.get("municipalities"),dict):
                cached["stale"]=True
                return cached
            raise
        try:
            by_uf: dict[str,dict[str,Any]]={}
            parameters={folded:key for folded,key,_ in SISAGUA_RAD_PARAMETERS}
            supplies={code:key for code,key,_ in SISAGUA_SUPPLY_TYPES}
            try: bundle=zipfile.ZipFile(archive)
            except zipfile.BadZipFile as exc: raise ValueError("O pacote oficial do SISAGUA está corrompido.") from exc
            with bundle:
                members=[item for item in bundle.infolist() if not item.is_dir() and item.filename.lower().endswith(".csv")]
                if len(members)!=1 or not 0<members[0].file_size<=6*1024*1024*1024: raise ValueError("O pacote oficial do SISAGUA não contém o CSV esperado.")
                member=members[0]
                with bundle.open(member) as raw:
                    stream=io.TextIOWrapper(raw,encoding="latin-1",errors="replace",newline="")
                    reader=csv.reader(stream,delimiter=";")
                    headers={name.strip().strip('"').upper():index for index,name in enumerate(next(reader,[]))}
                    needed={"SG_UF","CO_MUNICIPIO_IBGE","NO_MUNICIPIO","NU_MES","TP_MOTIVO_COLETA","TP_ABASTECIMENTO","NU_SOLUCAO_ABASTECIMENTO","NO_SOLUCAO_ABASTECIMENTO","PARAMETRO"}
                    if not needed.issubset(headers): raise ValueError("O arquivo oficial do SISAGUA não contém os campos necessários ao relatório.")
                    width=max(headers[name] for name in needed)+1
                    position={name:headers[name] for name in needed}
                    read_count=0; parameter_cache: dict[str,str|None]={}; motive_cache: dict[str,bool]={}
                    for row in reader:
                        read_count+=1
                        if read_count%50000==0 and progress:
                            try: done=raw.tell()
                            except (OSError,ValueError): done=0
                            percent=40+int(52*min(1,done/member.file_size)) if done else 40
                            progress(min(92,percent),f"Lendo análises do SISAGUA · {read_count:,} registros".replace(",","."))
                        if len(row)<width: continue
                        raw_parameter=row[position["PARAMETRO"]]
                        if raw_parameter not in parameter_cache: parameter_cache[raw_parameter]=parameters.get(_sisagua_fold(raw_parameter).split(" (")[0])
                        parameter=parameter_cache[raw_parameter]
                        if not parameter: continue
                        row_uf=row[position["SG_UF"]].strip().upper()
                        municipality=re.sub(r"\D","",row[position["CO_MUNICIPIO_IBGE"]])[:6]
                        raw_month=row[position["NU_MES"]].strip()
                        if row_uf not in PREDEFINED_UF_CODES or len(municipality)!=6 or not raw_month.isdigit() or not 1<=int(raw_month)<=12: continue
                        month=str(int(raw_month))
                        state=by_uf.setdefault(row_uf,{})
                        place=state.setdefault(municipality,{"name":_report_label(row[position["NO_MUNICIPIO"]]),"months":{}})
                        monthly=place["months"].setdefault(month,{"counts":{key:0 for key in SISAGUA_COUNT_KEYS},"solutions":{}})
                        supply_code=row[position["TP_ABASTECIMENTO"]].strip().upper()
                        solution_code=row[position["NU_SOLUCAO_ABASTECIMENTO"]].strip()[:40] or "—"
                        solution_key=f"{supply_code}|{solution_code}"
                        solution=monthly["solutions"].setdefault(solution_key,{"supply":supply_code or "NÃO INFORMADO","code":solution_code,"name":_report_label(row[position["NO_SOLUCAO_ABASTECIMENTO"]])[:160] or "Solução não informada",**{key:0 for key in ("rad","freeChlorine","combinedChlorine","chlorineDioxide","excluded")}})
                        raw_motive=row[position["TP_MOTIVO_COLETA"]]
                        if raw_motive not in motive_cache: motive_cache[raw_motive]=_sisagua_fold(raw_motive) in SISAGUA_EXCLUDED_MOTIVES
                        if motive_cache[raw_motive]:
                            monthly["counts"]["excluded"]+=1; solution["excluded"]+=1
                            continue
                        counts=monthly["counts"]
                        for item in (counts,solution):
                            item["rad"]+=1; item[parameter]+=1
                        counts[supplies.get(supply_code,"otherSupply")]+=1
            fetched_at=time.time()
            if progress: progress(94,"Salvando os totais do SISAGUA neste computador")
            for state_code in PREDEFINED_UF_CODES:
                cache_write(_sisagua_cache(year,state_code),{"fetched_at":fetched_at,"updatedAt":updated_at,"year":year,"uf":state_code,"municipalities":by_uf.get(state_code,{}),"scanned":read_count},max_bytes=60_000_000,keep=200)
        finally:
            archive.unlink(missing_ok=True)
        result=cache_read(target)
        if not isinstance(result,dict): raise ValueError("Não foi possível salvar os totais do SISAGUA neste computador.")
        return result

def _sisagua_population(uf: str, year: int):
    """Resident population (IBGE) of every municipality of a UF, picking the latest year up to the report year."""
    target=cache_target("sisagua_population",{"version":1,"uf":uf})
    cached=cache_read(target)
    if not (isinstance(cached,dict) and isinstance(cached.get("series"),dict) and time.time()-float(cached.get("fetched_at",0))<30*86400):
        state=PREDEFINED_UF_CODES[uf]
        series: dict[str,dict[str,int]]={}
        def collect(data, source):
            for block in data if isinstance(data,list) else []:
                for result in block.get("resultados") or []:
                    for item in result.get("series") or []:
                        code=str((item.get("localidade") or {}).get("id") or "")[:6]
                        if not re.fullmatch(r"\d{6}",code): continue
                        for period,value in (item.get("serie") or {}).items():
                            if str(value).isdigit() and str(period).isdigit(): series.setdefault(code,{})[str(period)]=int(value)
        try:
            periods=_sinan_json_request("https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos","servicodados.ibge.gov.br",timeout=25,max_bytes=1_000_000)
            wanted=[str(item.get("id")) for item in periods if isinstance(item,dict) and str(item.get("id","")).isdigit() and int(item["id"])>=SISAGUA_FIRST_YEAR-1]
            if wanted:
                collect(_sinan_json_request(f"https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/{'|'.join(wanted)}/variaveis/9324?localidades=N6[N3[{state}]]","servicodados.ibge.gov.br",timeout=35,max_bytes=16_000_000),"estimate")
            census=_sinan_json_request(f"https://servicodados.ibge.gov.br/api/v3/agregados/4709/periodos/2022/variaveis/93?localidades=N6[N3[{state}]]","servicodados.ibge.gov.br",timeout=35,max_bytes=8_000_000)
            for block in census if isinstance(census,list) else []:
                for result in block.get("resultados") or []:
                    for item in result.get("series") or []:
                        code=str((item.get("localidade") or {}).get("id") or "")[:6]
                        value=str((item.get("serie") or {}).get("2022") or "")
                        if re.fullmatch(r"\d{6}",code) and value.isdigit(): series.setdefault(code,{})["2022"]=int(value)
        except Exception:
            if isinstance(cached,dict) and isinstance(cached.get("series"),dict): series=cached["series"]
            else: raise ValueError("Não foi possível consultar a população do IBGE para calcular o mínimo da diretriz.")
        if not series: raise ValueError("O IBGE não retornou a população dos municípios desta UF.")
        cached={"fetched_at":time.time(),"series":series}
        cache_write(target,cached,max_bytes=4_000_000,keep=40)
    return cached["series"]

def _sisagua_population_for(series: dict[str,dict[str,int]], municipality: str, year: int):
    values=series.get(municipality) or {}
    eligible=[int(period) for period in values if int(period)<=year]
    chosen=max(eligible) if eligible else (min(int(period) for period in values) if values else None)
    if chosen is None: return None,None,""
    return values[str(chosen)],chosen,("Censo 2022" if chosen==2022 else f"estimativa {chosen}")

def predefined_sisagua_rad(payload: dict[str,Any], progress=None):
    if progress is None: return _predefined_sisagua_rad_impl(payload,None)
    stop=threading.Event(); progress_lock=threading.Lock()
    latest={"percent":5,"stage":"Preparando o arquivo oficial do SISAGUA"}
    def publish(percent,stage):
        with progress_lock:
            latest["percent"]=percent; latest["stage"]=stage
            progress(percent,stage)
    def heartbeat():
        while not stop.wait(4):
            try:
                with progress_lock: progress(latest["percent"],latest["stage"])
            except Exception: pass
    thread=threading.Thread(target=heartbeat,name="sisagua-progress-heartbeat",daemon=True)
    thread.start()
    try: return _predefined_sisagua_rad_impl(payload,publish)
    finally:
        stop.set(); thread.join(timeout=1)

def _predefined_sisagua_rad_impl(payload: dict[str,Any], progress=None):
    """PQA-VS indicator: RAD analyses by the water-quality surveillance over the national-guideline minimum."""
    year=payload.get("year"); month=payload.get("month"); municipality=str(payload.get("municipalityCode") or "")
    uf=str(payload.get("uf") or "").upper(); view=str(payload.get("view") or "summary")
    if not isinstance(year,int) or not SISAGUA_FIRST_YEAR<=year<=date.today().year or not isinstance(month,int) or not 1<=month<=12:
        raise ValueError(f"Selecione um mês de {SISAGUA_FIRST_YEAR} em diante para o relatório do SISAGUA.")
    if uf not in PREDEFINED_UF_CODES or not re.fullmatch(r"\d{6}",municipality) or municipality[:2]!=PREDEFINED_UF_CODES[uf]:
        raise ValueError("Selecione um município válido para o relatório do SISAGUA.")
    if view not in {"summary","detail"}: raise ValueError("Selecione uma visão válida do relatório do SISAGUA.")
    data=_sisagua_source(year,uf,progress)
    if progress: progress(96,"Calculando o mínimo da Diretriz Nacional")
    place=(data.get("municipalities") or {}).get(municipality) or {}
    municipality_name=_report_label(payload.get("municipalityName") or "")[:100] or _report_label(place.get("name") or "") or f"Município {municipality}"
    population,population_year,population_source=_sisagua_population_for(_sisagua_population(uf,year),municipality,year)
    if population is None: raise ValueError(f"O IBGE não informou a população de {municipality_name}; o mínimo da diretriz não pode ser calculado.")
    minimum=sisagua_rad_minimum(population)
    monthly=(place.get("months") or {}).get(str(month)) or {"counts":{},"solutions":{}}
    counts={key:int((monthly.get("counts") or {}).get(key) or 0) for key in SISAGUA_COUNT_KEYS}
    compliance=round(100*counts["rad"]/minimum,1) if minimum else None
    period=f"{month:02d}/{year}"
    common_notes=[
        f"Fonte: SISAGUA · Vigilância · Parâmetros básicos, arquivo público anual de {year} publicado em {data.get('updatedAt') or 'data não informada'} no Portal de Dados Abertos do SUS.",
        "Numerador: análises de residual de agente desinfetante (RAD) registradas pela vigilância — soma de cloro residual livre, cloro residual combinado e dióxido de cloro —, pelo município e mês da coleta, nas formas SAA, SAC, SAI e carro-pipa. Coletas com motivo surto ou desastre não entram na contagem, como no relatório oficial do SISAGUA.",
        f"Denominador: mínimo mensal da Diretriz Nacional do Plano de Amostragem da Vigilância da Qualidade da Água (2016, Tabela 1), calculado com a população total do IBGE ({population_source}: {population:,} hab.) e com arredondamento para cima. Fator de multiplicação: 100.".replace(",","."),
        "Dados recentes podem mudar enquanto os municípios ainda registram análises no SISAGUA. Para o resultado anual, selecione os 12 meses: o percentual do período usa o total analisado sobre a soma dos mínimos mensais."
    ]
    if data.get("stale"): common_notes.append("Não foi possível atualizar o arquivo oficial agora; o relatório usa a última leitura salva neste computador.")
    kpis=[{"label":"ANÁLISES RAD","value":{"value":counts["rad"]}},{"label":"MÍNIMO DA DIRETRIZ","value":{"value":minimum}},{"label":"% DO MÍNIMO","value":{"value":compliance,"decimals":1,"suffix":"%"} if compliance is not None else {"text":"—"}},{"label":f"POPULAÇÃO · {population_source.upper()}","value":{"value":population}}]
    base={"ok":True,"report":"sisagua-residual-desinfetante","flatTable":True,"file":"SISAGUA · CSV oficial","year":year,"month":month,"uf":uf,"state":PREDEFINED_UF_NAMES[uf],"municipality":municipality_name,"municipalityCode":municipality,"updatedAt":data.get("updatedAt"),"population":population,"populationYear":population_year,"populationSource":population_source,"minimum":minimum,"kpis":kpis,"cachedAt":time.time()}
    if view=="detail":
        rows=[]
        for solution in (monthly.get("solutions") or {}).values():
            if not solution.get("rad") and not solution.get("excluded"): continue
            supply=str(solution.get("supply") or "")
            rows.append({"code":str(month),"supply":next((label for code,_,label in SISAGUA_SUPPLY_TYPES if code==supply),supply or "Não informado"),"solutionCode":solution.get("code") or "—","solutionName":solution.get("name") or "Solução não informada",**{key:int(solution.get(key) or 0) for key in ("rad","freeChlorine","combinedChlorine","chlorineDioxide","excluded")}})
        rows.sort(key=lambda item:(-item["rad"],item["supply"],item["solutionName"]))
        metric_items=[("rad","ANÁLISES RAD"),*((key,label) for _,key,label in SISAGUA_RAD_PARAMETERS),("excluded","SURTO/DESASTRE · FORA DA CONTA")]
        columns=[{"id":"solution","label":"SOLUÇÃO DE ABASTECIMENTO","kind":"primary","primaryField":"solutionName","secondaryField":"solutionCode","filterFields":["solutionName","solutionCode"],"sortField":"solutionName","type":"text","sticky":True},{"id":"supply","label":"FORMA DE ABASTECIMENTO","field":"supply","type":"text"},*({"id":key,"label":label,"metricId":key,"type":"number","decimals":0} for key,label in metric_items)]
        return {**base,"view":"detail","establishmentCode":str(month),"establishmentName":period,"rows":rows,"records":counts["rad"],"columns":columns,"metrics":[{"id":key,"label":label.title(),"decimals":0} for key,label in metric_items],"notes":[f"Detalhe de {period}: cada linha é um sistema ou solução alternativa de abastecimento com análise RAD registrada pela vigilância.",*common_notes],"emptyStateMessage":f"Não há análises RAD da vigilância registradas para {municipality_name} em {period} no arquivo publicado em {data.get('updatedAt')}."}
    month_names=("Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro")
    row={"code":str(month),"monthName":month_names[month-1],"period":period,"municipalityName":municipality_name,"municipalityCode":municipality,"population":population,"minimum":minimum,"compliance":compliance,**counts}
    metric_items=[("minimum","MÍNIMO DA DIRETRIZ"),("rad","ANÁLISES RAD"),*((key,label) for _,key,label in SISAGUA_RAD_PARAMETERS),*((key,label) for _,key,label in SISAGUA_SUPPLY_TYPES),("excluded","SURTO/DESASTRE · FORA DA CONTA")]
    columns=[{"id":"month","label":"MÊS DA COLETA","kind":"primary","primaryField":"monthName","secondaryField":"period","filterFields":["monthName","period"],"sortField":"code","type":"text","sticky":True},{"id":"population","label":f"POPULAÇÃO · {population_source.upper()}","field":"population","type":"number","decimals":0},*({"id":key,"label":label,"metricId":key,"type":"number","decimals":0} for key,label in metric_items[:2]),{"id":"compliance","label":"% DO MÍNIMO","field":"compliance","type":"percent","decimals":1},*({"id":key,"label":label,"metricId":key,"type":"number","decimals":0} for key,label in metric_items[2:]),{"id":"detail","label":"DETALHAR","kind":"action","actionLabel":"Sistemas →"}]
    if counts["otherSupply"]: common_notes.append(f"{counts['otherSupply']} análise(s) com forma de abastecimento não reconhecida entram no total RAD, mas não nas colunas por forma.")
    return {**base,"view":"summary","rows":[row],"records":counts["rad"],"columns":columns,"metrics":[{"id":key,"label":label.title(),"decimals":0} for key,label in metric_items],"notes":common_notes,"emptyStateMessage":""}

# ---------------------------------------------------------------------------
# PQA-VS · indicadores calculados com as bases públicas do SINAN
# Regras: Portaria GM/MS nº 6.878/2025, Anexo II (fichas de qualificação).
# ---------------------------------------------------------------------------
SINAN_DBC_DIR="/dissemin/publicos/SINAN/DADOS"
PQAVS_FIRST_YEAR=2017
PQAVS_REPORTS={
    "pqavs-obitos-arboviroses":{"number":8,"label":"óbitos suspeitos de dengue e chikungunya encerrados em até 60 dias","goal":"75%","goalValue":75},
    "pqavs-contatos-hanseniase":{"number":9,"label":"contatos examinados de casos novos de hanseníase","goal":"≥ 82%","goalValue":82},
    "pqavs-contatos-tuberculose":{"number":10,"label":"contatos examinados de casos novos de TB pulmonar com confirmação laboratorial","goal":"70%","goalValue":70},
    "pqavs-sifilis-congenita":{"number":11,"label":"sífilis congênita em relação à sífilis em gestantes","goal":"redução de 1 ponto percentual sobre o ano base (ou manter 0%)","goalValue":None},
    "pqavs-violencia-raca-cor":{"number":14,"label":"notificações de violência com raça/cor válida","goal":"95%","goalValue":95},
}
PQAVS_MONTHS=("Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro")

def _pqavs_date(value: Any):
    raw=re.sub(r"\D","",str(value or ""))[:8]
    if len(raw)!=8: return None
    try: return date(int(raw[:4]),int(raw[4:6]),int(raw[6:8]))
    except ValueError: return None

def _pqavs_municipality(value: Any) -> str:
    code=re.sub(r"\D","",_sinan_code(value))[:6]
    return code if len(code)==6 and code[:2] in PREDEFINED_UF_CODES.values() else ""

def _pqavs_int(value: Any) -> int:
    raw=re.sub(r"\D","",_sinan_code(value))
    return min(int(raw),999) if raw else 0

def _pqavs_year(value: Any) -> int:
    raw=re.sub(r"\D","",_sinan_code(value))[:4]
    return int(raw) if len(raw)==4 else 0

def _sinan_ftp_download(remote: str, destination: Path) -> bool:
    """FTP fallback for networks where the HTTPS portal is unavailable. Returns False when the file does not exist."""
    from ftplib import error_perm
    ftp=FTP("ftp.datasus.gov.br",timeout=30)
    try:
        ftp.login(); ftp.set_pasv(True)
        try: size=ftp.size(remote)
        except error_perm: return False
        if size is None or not 0<size<=1024*1024*1024: raise ValueError("O arquivo do SINAN no FTP tem tamanho inválido.")
        with destination.open("wb") as output: ftp.retrbinary("RETR "+remote,output.write,blocksize=1024*1024)
        if destination.stat().st_size!=size: raise ValueError("O arquivo do SINAN chegou incompleto pelo FTP.")
        return True
    finally:
        try: ftp.close()
        except OSError: pass

def _sinan_dbc_download(prefix: str, year: int, progress=None):
    """Download the national SINAN DBC of one disease and year, preferring the closed (FINAIS) base."""
    name=f"{prefix}BR{year%100:02d}.dbc"
    folder=UPLOADS/".cache"/"sinan-dbc"
    folder.mkdir(parents=True,exist_ok=True)
    for old in folder.glob("sinan-*.part"):
        try:
            if time.time()-old.stat().st_mtime>86400: old.unlink(missing_ok=True)
        except OSError: pass
    failures=[]
    for stage in ("FINAIS","PRELIM"):
        remote=f"{SINAN_DBC_DIR}/{stage}/{name}"
        fd,temp_name=tempfile.mkstemp(prefix="sinan-",suffix=".part",dir=str(folder)); os.close(fd)
        temp=Path(temp_name)
        def report(done,total):
            if progress: progress(8,f"Baixando {name} ({'base final' if stage=='FINAIS' else 'base preliminar'}) · {done/1048576:.1f} MB"+(f" de {total/1048576:.1f} MB" if total else ""))
        try:
            portal_download_file(remote,name,temp,report)
            return temp,stage
        except urllib.error.HTTPError as exc:
            temp.unlink(missing_ok=True)
            if exc.code==404: continue
            failures.append(exc)
        except Exception as exc:
            temp.unlink(missing_ok=True)
            failures.append(exc)
        try:
            if progress: progress(8,f"Baixando {name} pelo FTP do DATASUS")
            if _sinan_ftp_download(remote,temp): return temp,stage
            temp.unlink(missing_ok=True)
        except Exception as exc:
            temp.unlink(missing_ok=True)
            failures.append(exc)
    if failures: raise ValueError(f"Não foi possível baixar {name} do DATASUS: {failures[-1]}")
    return None,None

def _pqavs_collect_arbo(prefix: str, file_year: int):
    valid_classes={"10","11","12","5"} if prefix=="DENG" else {"13","5"}
    fields=("SEM_NOT","NU_ANO","DT_NOTIFIC","ID_MUNICIP","ID_MN_RESI","CLASSI_FIN","EVOLUCAO","DT_ENCERRA")
    def collect(values):
        sem,nu_ano,raw_notification,notifying,resident,classification,evolution,raw_closing=values
        if _sinan_code(evolution) not in {"2","3","4"}: return ()
        week=re.sub(r"\D","",str(sem or ""))
        reference_year=int(week[:4]) if len(week)>=6 else _pqavs_year(nu_ano)
        if reference_year!=file_year: return ()
        notification=_pqavs_date(raw_notification)
        if notification is None: return ()
        month=notification.month if notification.year==file_year else (1 if notification.year<file_year else 12)
        closing=_pqavs_date(raw_closing)
        on_time=bool(closing and _sinan_code(classification) in valid_classes and 0<=(closing-notification).days<=60)
        increments={"deaths":1,"onTime":int(on_time),"closed":int(closing is not None)}
        output=[]
        for basis,raw in (("n",notifying),("r",resident)):
            municipality=_pqavs_municipality(raw)
            if municipality: output.append((municipality,f"{basis}|{month}",increments,None if closing else notification.isoformat()))
        return output
    return fields,collect

def _pqavs_collect_congenital(_file_year: int):
    fields=("NU_IDADE_N","DT_DIAG","DT_NOTIFIC","ID_MN_RESI","EVO_DIAG_N")
    def collect(values):
        raw_age,raw_diagnosis,raw_notification,resident,final=values
        # Same rule as the DATHI panel used by PQA-VS (checked against Belém
        # 2022: 372 recente + 19 aborto + 10 natimorto = 401): count diagnóstico
        # final 1 (recente), 3 (aborto) and 4 (natimorto); leave out 2 (tardia)
        # and 5 (descartado). TabNet labels code 4 differently; the panel prevails.
        final=_sinan_code(final)
        if final not in {"1","3","4"}: return ()
        reference=_pqavs_date(raw_diagnosis) or _pqavs_date(raw_notification)
        municipality=_pqavs_municipality(resident)
        if reference is None or not municipality: return ()
        return ((municipality,f"{reference.year}|{reference.month}",{"congenital":1},None),)
    return fields,collect

def _pqavs_collect_pregnant(_file_year: int):
    fields=("DT_DIAG","DT_NOTIFIC","ID_MN_RESI")
    def collect(values):
        raw_diagnosis,raw_notification,resident=values
        reference=_pqavs_date(raw_diagnosis) or _pqavs_date(raw_notification)
        municipality=_pqavs_municipality(resident)
        if reference is None or not municipality: return ()
        return ((municipality,f"{reference.year}|{reference.month}",{"pregnant":1},None),)
    return fields,collect

def _pqavs_collect_violence(file_year: int):
    fields=("NU_ANO","DT_NOTIFIC","ID_MUNICIP","CS_RACA")
    def collect(values):
        nu_ano,raw_notification,notifying,race=values
        if _pqavs_year(nu_ano)!=file_year: return ()
        notification=_pqavs_date(raw_notification)
        municipality=_pqavs_municipality(notifying)
        if notification is None or not municipality: return ()
        race=_sinan_code(race)
        month=notification.month if notification.year==file_year else (1 if notification.year<file_year else 12)
        return ((municipality,str(month),{"total":1,"valid":int(race in {"1","2","3","4","5"}),"ignored":int(race=="9"),"blank":int(race not in {"1","2","3","4","5","9"})},None),)
    return fields,collect

def _pqavs_collect_leprosy(_file_year: int):
    fields=("DT_DIAG","MODOENTR","TPALTA_N","CLASSATUAL","ESQ_ATU_N","MUNIRESAT","ID_MN_RESI","CONTREG","CONTEXAM")
    def collect(values):
        raw_diagnosis,entry,exit_type,current_class,current_scheme,current_residence,resident,registered,examined=values
        if _sinan_code(entry)!="1" or _sinan_code(exit_type) in {"3","4","5","8","9"}: return ()
        current_class=_sinan_code(current_class); current_scheme=_sinan_code(current_scheme)
        group="pb" if current_class=="1" and current_scheme=="1" else "mb" if current_class=="2" and current_scheme=="2" else ""
        diagnosis=_pqavs_date(raw_diagnosis)
        municipality=_pqavs_municipality(current_residence) or _pqavs_municipality(resident)
        if not group or diagnosis is None or not municipality: return ()
        return ((municipality,f"{diagnosis.year}|{diagnosis.month}|{group}",{"cases":1,"registered":_pqavs_int(registered),"examined":_pqavs_int(examined)},None),)
    return fields,collect

def _pqavs_collect_tuberculosis(_file_year: int):
    fields=("DT_DIAG","TRATAMENTO","FORMA","SITUA_ENCE","BACILOSC_E","BACILOS_E2","CULTURA_ES","TEST_MOLEC","ID_MN_RESI","NU_CONTATO","NU_COMU_EX","ID_MUNICIP","ID_MUNIC_A")
    def collect(values):
        raw_diagnosis,entry,form,closing,smear,smear2,culture,molecular,resident,identified,examined,notifying,current_unit=values
        if _sinan_code(entry) not in {"1","4","6"} or _sinan_code(form) not in {"1","3"} or _sinan_code(closing)=="6": return ()
        diagnosis=_pqavs_date(raw_diagnosis)
        if diagnosis is None: return ()
        confirmed=_sinan_code(smear)=="1" or _sinan_code(smear2)=="1" or _sinan_code(culture)=="1" or _sinan_code(molecular) in {"1","2"}
        increments={"pulmonaryCases":1,"cases":int(confirmed),"identified":_pqavs_int(identified) if confirmed else 0,"examined":_pqavs_int(examined) if confirmed else 0}
        notifying=_pqavs_municipality(notifying)
        # Residence at notification (default), current follow-up municipality
        # (after transfers; falls back to the notifying one) and notifying municipality.
        bases=(("r",_pqavs_municipality(resident)),("u",_pqavs_municipality(current_unit) or notifying),("n",notifying))
        return tuple((municipality,f"{basis}|{diagnosis.year}|{diagnosis.month}",increments,None) for basis,municipality in bases if municipality)
    return fields,collect

PQAVS_SOURCES={
    "DENG":("csv",lambda year:_pqavs_collect_arbo("DENG",year)),
    "CHIK":("csv",lambda year:_pqavs_collect_arbo("CHIK",year)),
    "SIFC":("dbc",_pqavs_collect_congenital),
    "SIFG":("dbc",_pqavs_collect_pregnant),
    "VIOL":("dbc",_pqavs_collect_violence),
    "HANS":("dbc",_pqavs_collect_leprosy),
    "TUBE":("dbc",_pqavs_collect_tuberculosis),
}

PQAVS_COLLECTOR_VERSIONS={"SIFC":3,"TUBE":2}

def _pqavs_source_target(prefix: str, year: int, uf: str):
    identity={"version":2,"prefix":prefix,"year":year,"uf":uf}
    if prefix in PQAVS_COLLECTOR_VERSIONS: identity["collector"]=PQAVS_COLLECTOR_VERSIONS[prefix]
    return cache_target("pqavs_sinan",identity)

def _pqavs_source(prefix: str, year: int, uf: str, progress=None):
    """Per-UF aggregates of one national SINAN file. The national file is read once and every UF is cached."""
    if year>date.today().year: return {"missing":True,"future":True,"municipalities":{},"year":year,"prefix":prefix}
    target=_pqavs_source_target(prefix,year,uf)
    def fresh(item):
        if not isinstance(item,dict) or not isinstance(item.get("municipalities"),dict): return False
        lifetime=86400 if item.get("missing") else 7*86400 if item.get("stage")!="FINAIS" else 60*86400
        return time.time()-float(item.get("fetched_at",0))<lifetime
    cached=cache_read(target)
    if fresh(cached): return cached
    folder=UPLOADS/".cache"/"sinan-dbc"
    folder.mkdir(parents=True,exist_ok=True)
    with interprocess_lock(folder/f"{prefix}-{year}.lock"):
        cached=cache_read(target)
        if fresh(cached): return cached
        kind,factory=PQAVS_SOURCES[prefix]
        fields,collect=factory(year)
        by_uf: dict[str,dict[str,dict[str,dict[str,Any]]]]={}
        scanned=0
        def add(entries):
            for municipality,key,increments,open_date in entries:
                state=next((code for code,prefix_code in PREDEFINED_UF_CODES.items() if prefix_code==municipality[:2]),None)
                if state is None: continue
                bucket=by_uf.setdefault(state,{}).setdefault(municipality,{}).setdefault(key,{})
                for name,value in increments.items(): bucket[name]=bucket.get(name,0)+value
                if open_date: bucket.setdefault("open",[]).append(open_date)
        stage=None; updated_at=date.today().isoformat()
        try:
            if kind=="csv":
                report_id="sinan-dengue" if prefix=="DENG" else "sinan-chikungunya"
                try: archive,updated_at=_sinan_dengue_archive(year,report_id,progress)
                except ValueError as exc:
                    if "ainda não está disponível" not in str(exc): raise
                    archive=None
                if archive is None: missing=True
                else:
                    missing=False; stage="CSV"
                    try:
                        expected=f"{prefix}BR{year%100:02d}.csv"
                        with zipfile.ZipFile(archive) as bundle:
                            info=next(entry for entry in bundle.infolist() if entry.filename.replace("\\","/").rsplit("/",1)[-1].casefold()==expected.casefold())
                            with bundle.open(info) as binary, io.TextIOWrapper(binary,encoding="latin1",newline="") as stream:
                                reader=csv.reader(stream,delimiter=",")
                                headers={str(name or "").lstrip("\ufeff").strip().upper():index for index,name in enumerate(next(reader,[]))}
                                missing_fields=[name for name in fields if name not in headers]
                                if missing_fields: raise ValueError("O CSV oficial do SINAN não contém os campos: "+", ".join(missing_fields))
                                positions=[headers[name] for name in fields]; width=max(positions)+1
                                for row in reader:
                                    scanned+=1
                                    if progress and scanned%50000==0:
                                        done=min(info.file_size,binary.tell())
                                        progress(min(88,32+int(56*done/max(1,info.file_size))),f"Lendo {prefix} {year} · {scanned:,} registros".replace(",","."))
                                    if len(row)<width: continue
                                    add(collect(tuple(row[index] for index in positions)))
                    finally:
                        archive.unlink(missing_ok=True)
            else:
                dbc,stage=_sinan_dbc_download(prefix,year,progress)
                missing=dbc is None
                if dbc is not None:
                    dbf=None
                    try:
                        if progress: progress(30,f"Descompactando {prefix}BR{year%100:02d}.dbc")
                        dbf=Path(decompress(dbc))
                        _,_,_,layout=dbf_layout(dbf)
                        available=[name for name in fields if name in layout]
                        if len(available)!=len(fields): raise ValueError(f"A base {prefix} {year} não contém os campos: "+", ".join(name for name in fields if name not in layout))
                        processed=[0]
                        def scan(done,total):
                            if progress: progress(min(88,35+int(53*done/max(1,total))),f"Lendo {prefix} {year} · {done:,} de {total:,} registros".replace(",","."))
                        for values in iter_dbf_fields(dbf,list(fields),processed_counter=processed,scan_callback=scan):
                            add(collect(values))
                        scanned=processed[0]
                    finally:
                        dbc.unlink(missing_ok=True)
                        if dbf is not None: dbf.unlink(missing_ok=True)
        except (OSError,ValueError,TimeoutError):
            if isinstance(cached,dict) and isinstance(cached.get("municipalities"),dict):
                cached["stale"]=True
                return cached
            raise
        fetched_at=time.time()
        for state in PREDEFINED_UF_CODES:
            cache_write(_pqavs_source_target(prefix,year,state),{"fetched_at":fetched_at,"prefix":prefix,"year":year,"uf":state,"stage":stage,"missing":missing,"updatedAt":updated_at,"scanned":scanned,"municipalities":by_uf.get(state,{})},max_bytes=40_000_000,keep=400)
        result=cache_read(target)
        if not isinstance(result,dict): raise ValueError("Não foi possível salvar os totais do SINAN neste computador.")
        return result

def _pqavs_bucket(source: dict[str,Any], municipality: str, key: str) -> dict[str,Any]:
    return ((source.get("municipalities") or {}).get(municipality) or {}).get(key) or {}

def _pqavs_source_label(sources: list[dict[str,Any]]) -> str:
    parts=[]
    for item in sources:
        name=f"{item.get('prefix')}BR{int(item.get('year',0))%100:02d}"
        if item.get("future"): continue
        if item.get("missing"): parts.append(f"{name} (ainda não publicado)")
        else: parts.append(f"{name} · {'base final' if item.get('stage')=='FINAIS' else 'CSV do Portal de Dados Abertos' if item.get('stage')=='CSV' else 'base preliminar'}"+(" · última leitura salva" if item.get("stale") else ""))
    return "; ".join(parts)

def predefined_pqavs(payload: dict[str,Any], progress=None):
    if progress is None: return _predefined_pqavs_impl(payload,None)
    stop=threading.Event(); progress_lock=threading.Lock()
    latest={"percent":5,"stage":"Preparando as bases do SINAN"}
    def publish(percent,stage):
        with progress_lock:
            latest["percent"]=percent; latest["stage"]=stage
            progress(percent,stage)
    def heartbeat():
        while not stop.wait(4):
            try:
                with progress_lock: progress(latest["percent"],latest["stage"])
            except Exception: pass
    thread=threading.Thread(target=heartbeat,name="pqavs-progress-heartbeat",daemon=True)
    thread.start()
    try: return _predefined_pqavs_impl(payload,publish)
    finally:
        stop.set(); thread.join(timeout=1)

def _pqavs_percent(numerator: int, denominator: int):
    return round(100*numerator/denominator,1) if denominator else None

def _predefined_pqavs_impl(payload: dict[str,Any], progress=None):
    report_id=str(payload.get("predefinedReport") or "")
    spec=PQAVS_REPORTS.get(report_id)
    if spec is None: raise ValueError("Indicador PQA-VS não reconhecido.")
    year=payload.get("year"); month=payload.get("month"); municipality=str(payload.get("municipalityCode") or "")
    uf=str(payload.get("uf") or "").upper()
    if not isinstance(year,int) or not PQAVS_FIRST_YEAR<=year<=date.today().year or not isinstance(month,int) or not 1<=month<=12:
        raise ValueError(f"Selecione um mês de {PQAVS_FIRST_YEAR} em diante.")
    if uf not in PREDEFINED_UF_CODES or not re.fullmatch(r"\d{6}",municipality) or municipality[:2]!=PREDEFINED_UF_CODES[uf]:
        raise ValueError("Selecione um município válido.")
    if str(payload.get("view") or "summary")!="summary": raise ValueError("Este indicador tem apenas a visão mensal.")
    municipality_name=_report_label(payload.get("municipalityName") or "")[:100] or f"Município {municipality}"
    filters=payload.get("reportFilters") if isinstance(payload.get("reportFilters"),dict) else {}
    month_name=PQAVS_MONTHS[month-1]
    row={"code":str(month),"monthName":month_name,"period":f"{month:02d}/{year}"}
    primary={"id":"month","label":"MÊS","kind":"primary","primaryField":"monthName","secondaryField":"period","filterFields":["monthName","period"],"sortField":"code","type":"text","sticky":True}
    notes=[]; extra_kpi=None; filter_summary=[]
    def metric(key,label): return {"id":key,"label":label,"metricId":key,"type":"number","decimals":0}
    percent_column={"id":"percent","label":"% DO INDICADOR","field":"percent","type":"percent","decimals":1}
    if report_id=="pqavs-obitos-arboviroses":
        basis_values=[str(item) for item in (filters.get("basis") or []) if str(item) in {"notification","residence"}]
        basis="r" if basis_values[:1]==["residence"] else "n"
        filter_summary.append({"label":"Município considerado","value":"residência" if basis=="r" else "notificação"})
        if progress: progress(5,"Preparando dengue e chikungunya do SINAN")
        dengue=_pqavs_source("DENG",year,uf,progress); chik=_pqavs_source("CHIK",year,uf,progress)
        today=date.today()
        values={}
        for prefix,source in (("dengue",dengue),("chik",chik)):
            bucket=_pqavs_bucket(source,municipality,f"{basis}|{month}")
            open_dates=[_pqavs_date(item) for item in bucket.get("open") or []]
            open_window=sum(1 for item in open_dates if item and (today-item).days<=60)
            values[prefix]={"deaths":int(bucket.get("deaths") or 0),"onTime":int(bucket.get("onTime") or 0),"openWindow":open_window,"openLate":len(open_dates)-open_window}
        numerator=values["dengue"]["onTime"]+values["chik"]["onTime"]
        denominator=sum(item["deaths"]-item["openWindow"] for item in values.values())
        row.update({"dengueDeaths":values["dengue"]["deaths"],"dengueOnTime":values["dengue"]["onTime"],"chikDeaths":values["chik"]["deaths"],"chikOnTime":values["chik"]["onTime"],"openWindow":values["dengue"]["openWindow"]+values["chik"]["openWindow"],"openLate":values["dengue"]["openLate"]+values["chik"]["openLate"],"numerator":numerator,"denominator":denominator})
        primary["label"]="MÊS DA NOTIFICAÇÃO"
        metric_items=[("dengueDeaths","ÓBITOS SUSPEITOS · DENGUE"),("dengueOnTime","ENCERRADOS ≤ 60 DIAS · DENGUE"),("chikDeaths","ÓBITOS SUSPEITOS · CHIKUNGUNYA"),("chikOnTime","ENCERRADOS ≤ 60 DIAS · CHIKUNGUNYA"),("openWindow","EM ABERTO AINDA NO PRAZO"),("openLate","EM ABERTO HÁ MAIS DE 60 DIAS"),("numerator","NUMERADOR"),("denominator","DENOMINADOR")]
        sources=[dengue,chik]
        labels=("ÓBITOS ENCERRADOS ≤ 60 DIAS","ÓBITOS NO DENOMINADOR")
        extra_kpi={"label":"EM ABERTO HÁ MAIS DE 60 DIAS","value":{"value":row["openLate"]},"kind":"sum"}
        notes+=[
            "Numerador: óbitos (evolução 2, 3 ou 4) com classificação final dengue (10, 11, 12) ou descartado (5) — chikungunya (13) ou descartado (5) — encerrados em até 60 dias da notificação.",
            f"Denominador: todos os óbitos suspeitos notificados, de qualquer classificação, menos os ainda não encerrados que estão dentro dos 60 dias em {today.strftime('%d/%m/%Y')} (data desta análise).",
            "Período: semana epidemiológica da notificação no ano selecionado; o mês usa a data de notificação. Para o resultado anual, selecione os 12 meses.",
            f"Município considerado: {'residência' if basis=='r' else 'notificação'} (troque em Alterar recorte). A ficha não define o município de agregação. Municípios sem óbitos suspeitos não pontuam no PQA-VS.",
        ]
    elif report_id=="pqavs-sifilis-congenita":
        if progress: progress(5,"Preparando sífilis congênita e em gestantes do SINAN")
        sources=[]; congenital=0; pregnant=0
        for file_year in (year,year+1):
            for prefix in ("SIFC","SIFG"):
                source=_pqavs_source(prefix,file_year,uf,progress); sources.append(source)
                bucket=_pqavs_bucket(source,municipality,f"{year}|{month}")
                congenital+=int(bucket.get("congenital") or 0); pregnant+=int(bucket.get("pregnant") or 0)
        numerator,denominator=congenital,pregnant
        row.update({"congenital":congenital,"pregnant":pregnant,"numerator":numerator,"denominator":denominator})
        primary["label"]="MÊS DO DIAGNÓSTICO"
        metric_items=[("congenital","A · SÍFILIS CONGÊNITA < 1 ANO"),("pregnant","B · SÍFILIS EM GESTANTES")]
        labels=("A · SÍFILIS CONGÊNITA < 1 ANO","B · SÍFILIS EM GESTANTES")
        notes+=[
            "Indicador = A ÷ B × 100, pelo município de residência e ano de diagnóstico. A: casos de sífilis congênita recente, aborto e natimorto por sífilis (exclui tardia e descartados), como no painel do DATHI. B: casos de sífilis em gestantes.",
            f"São somadas as bases de notificação de {year} e {year+1}, porque casos diagnosticados no fim do ano podem ser notificados no ano seguinte. Notificações feitas depois disso não entram.",
            "No PQA-VS o Ministério usa o dado consolidado pelo DATHI no penúltimo ano completo (painel indicadoressifilis.aids.gov.br); este cálculo com a base do SINAN serve para acompanhamento e pode diferir do painel.",
        ]
    elif report_id=="pqavs-violencia-raca-cor":
        if progress: progress(5,"Preparando as notificações de violência do SINAN")
        source=_pqavs_source("VIOL",year,uf,progress); sources=[source]
        bucket=_pqavs_bucket(source,municipality,str(month))
        total=int(bucket.get("total") or 0); valid=int(bucket.get("valid") or 0)
        numerator,denominator=valid,total
        row.update({"total":total,"valid":valid,"ignored":int(bucket.get("ignored") or 0),"blank":int(bucket.get("blank") or 0),"numerator":numerator,"denominator":denominator})
        primary["label"]="MÊS DA NOTIFICAÇÃO"
        metric_items=[("total","NOTIFICAÇÕES DE VIOLÊNCIA"),("valid","RAÇA/COR VÁLIDA"),("ignored","RAÇA/COR IGNORADA"),("blank","RAÇA/COR EM BRANCO")]
        labels=("RAÇA/COR VÁLIDA","NOTIFICAÇÕES")
        extra_kpi={"label":"IGNORADA OU EM BRANCO","value":{"value":row["ignored"]+row["blank"]},"kind":"sum"}
        notes+=[
            "Numerador: notificações de violência interpessoal e autoprovocada com raça/cor Branca, Preta, Amarela, Parda ou Indígena. Denominador: todas as notificações. Ignorado ou em branco é informação não válida.",
            "Recorte pelo município de notificação e ano da notificação; o mês usa a data de notificação. Municípios sem notificação de violência não pontuam no PQA-VS.",
        ]
    elif report_id=="pqavs-contatos-hanseniase":
        if progress: progress(5,"Preparando as coortes de hanseníase do SINAN")
        pb_year,mb_year=year-1,year-2
        sources=[]; totals={"pb":{"cases":0,"registered":0,"examined":0},"mb":{"cases":0,"registered":0,"examined":0}}
        for group,diagnosis_year in (("pb",pb_year),("mb",mb_year)):
            for file_year in (diagnosis_year,diagnosis_year+1):
                source=_pqavs_source("HANS",file_year,uf,progress)
                if source not in sources: sources.append(source)
                bucket=_pqavs_bucket(source,municipality,f"{diagnosis_year}|{month}|{group}")
                for key in totals[group]: totals[group][key]+=int(bucket.get(key) or 0)
        numerator=totals["pb"]["examined"]+totals["mb"]["examined"]
        denominator=totals["pb"]["registered"]+totals["mb"]["registered"]
        row.update({"pbCases":totals["pb"]["cases"],"pbRegistered":totals["pb"]["registered"],"pbExamined":totals["pb"]["examined"],"mbCases":totals["mb"]["cases"],"mbRegistered":totals["mb"]["registered"],"mbExamined":totals["mb"]["examined"],"numerator":numerator,"denominator":denominator,"period":f"PB {month:02d}/{pb_year} · MB {month:02d}/{mb_year}"})
        primary["label"]="MÊS DO DIAGNÓSTICO"
        metric_items=[("pbCases",f"CASOS NOVOS PB · {pb_year}"),("pbRegistered","CONTATOS REGISTRADOS PB"),("pbExamined","CONTATOS EXAMINADOS PB"),("mbCases",f"CASOS NOVOS MB · {mb_year}"),("mbRegistered","CONTATOS REGISTRADOS MB"),("mbExamined","CONTATOS EXAMINADOS MB")]
        labels=("CONTATOS EXAMINADOS PB+MB","CONTATOS REGISTRADOS PB+MB")
        extra_kpi={"label":"CASOS NOVOS NAS COORTES","value":{"value":totals["pb"]["cases"]+totals["mb"]["cases"]},"kind":"sum"}
        notes+=[
            f"Coortes da avaliação {year}: casos novos paucibacilares diagnosticados em {pb_year} (classificação atual PB e esquema PQT/PB/6 doses) e multibacilares diagnosticados em {mb_year} (MB e PQT/MB/12 doses).",
            "Modo de entrada: caso novo. Saem da conta erro diagnóstico e transferências para outro município, estado ou país (avaliação municipal). Município de residência atual; contatos registrados e examinados conforme o último acompanhamento enviado à base nacional.",
            "Para o resultado da avaliação, selecione os 12 meses. Municípios com casos novos e sem contatos registrados não cumprem a meta; sem casos novos nas coortes, não pontuam.",
        ]
    elif report_id=="pqavs-contatos-tuberculose":
        basis_values=[str(item) for item in (filters.get("basis") or []) if str(item) in {"residence","current","notification"}]
        basis=basis_values[0] if basis_values else "residence"
        basis_key={"residence":"r","current":"u","notification":"n"}[basis]
        basis_label={"residence":"residência na notificação","current":"município atual do acompanhamento","notification":"município de notificação"}[basis]
        filter_summary.append({"label":"Município considerado","value":basis_label})
        if progress: progress(5,"Preparando os casos de tuberculose do SINAN")
        sources=[]; totals={"cases":0,"identified":0,"examined":0,"pulmonaryCases":0}
        for file_year in (year,year+1):
            source=_pqavs_source("TUBE",file_year,uf,progress); sources.append(source)
            bucket=_pqavs_bucket(source,municipality,f"{basis_key}|{year}|{month}")
            for key in totals: totals[key]+=int(bucket.get(key) or 0)
        numerator,denominator=totals["examined"],totals["identified"]
        row.update({**totals,"numerator":numerator,"denominator":denominator})
        primary["label"]="MÊS DO DIAGNÓSTICO"
        metric_items=[("pulmonaryCases","CASOS NOVOS PULMONARES"),("cases","COM CONFIRMAÇÃO LABORATORIAL"),("identified","CONTATOS IDENTIFICADOS"),("examined","CONTATOS EXAMINADOS")]
        labels=("CONTATOS EXAMINADOS","CONTATOS IDENTIFICADOS")
        extra_kpi={"label":"CASOS NOVOS PULMONARES CONFIRMADOS","value":{"value":totals["cases"]},"kind":"sum"}
        notes+=[
            "Casos novos (tipo de entrada caso novo, não sabe ou pós-óbito), forma pulmonar ou pulmonar + extrapulmonar, exceto mudança de diagnóstico, com confirmação laboratorial: baciloscopia, cultura ou teste rápido molecular positivo.",
            f"Município considerado: {basis_label} (troque em Alterar recorte). A ficha manda usar a linha \"Mun Res BR2\" do TabWin sem dizer o campo; o padrão é a residência informada na notificação (ID_MN_RESI). Ano de diagnóstico; são somadas as bases de notificação de {year} e {year+1}. Os contatos são os registrados no último acompanhamento enviado à base nacional.",
        ]
    else:
        raise ValueError("Indicador PQA-VS não implementado.")
    percent=_pqavs_percent(numerator,denominator)
    row["percent"]=percent
    if report_id in {"pqavs-contatos-hanseniase","pqavs-contatos-tuberculose"} and numerator>denominator:
        notes.append("Há mais contatos examinados que registrados em algum mês: isso vem da própria base do SINAN (contatos registrados não atualizados no acompanhamento) e o cálculo oficial também não limita o resultado a 100%.")
    columns=[primary,*(metric(key,label) for key,label in metric_items),percent_column]
    goal=spec["goal"]
    kpis=[{"label":labels[0],"value":{"value":numerator},"kind":"sum"},{"label":labels[1],"value":{"value":denominator},"kind":"sum"},{"label":f"RESULTADO · META {goal.upper()}" if spec["goalValue"] is not None else "RESULTADO","value":{"value":percent,"decimals":1,"suffix":"%"} if percent is not None else {"text":"—"},"kind":"percent"}]
    if extra_kpi: kpis.append(extra_kpi)
    stage_note=f"Fonte: SINAN, bases públicas nacionais do DATASUS — {_pqavs_source_label(sources)}. Bases preliminares mudam a cada atualização."
    notes=[f"PQA-VS 2025 · indicador {spec['number']} ({spec['label']}). Meta: {goal}. Regras da Portaria GM/MS nº 6.878/2025, Anexo II.",*notes,stage_note]
    if any(item.get("stale") for item in sources): notes.append("Não foi possível atualizar alguma base agora; o resultado usa a última leitura salva neste computador.")
    return {"ok":True,"report":report_id,"view":"summary","flatTable":True,"file":"SINAN · bases públicas","year":year,"month":month,"uf":uf,"state":PREDEFINED_UF_NAMES[uf],"municipality":municipality_name,"municipalityCode":municipality,"filters":filter_summary,"numerator":numerator,"denominator":denominator,"rows":[row],"records":denominator,"columns":columns,"metrics":[{"id":key,"label":label.title(),"decimals":0} for key,label in metric_items],"kpis":kpis,"notes":notes,"emptyStateMessage":"","cachedAt":time.time()}

def _sinan_cnes_unit_metadata(codes: list[str], year: int, month: int, progress=None):
    """Resolve current unit identity and competence-aware management/legal-nature classifications."""
    valid=sorted({re.sub(r"\D","",str(code or "")) for code in codes if re.fullmatch(r"\d{7}",re.sub(r"\D","",str(code or "")))})
    if not valid: return {},0,0
    competence=f"{year:04d}{month:02d}"
    # Reuse the app's competence-aware CNES lookup for management and legal nature.
    # The direct current record below is only a fallback for those classifications.
    history_progress=(lambda percent,stage: progress(min(91,89+int(max(0,percent-80)*0.2)),stage)) if progress else None
    historical,_,_=_cnes_establishment_classifications(valid,year,month,need_sus=False,progress=history_progress)
    target=cache_target("sinan_cnes_units",{"version":3})
    metadata={}; missing=[]; failed=0; now=time.time(); ttl=30*86400
    with interprocess_lock(target.with_suffix(".lock")):
        cached=cache_read(target)
        entries=cached.get("units",{}) if isinstance(cached,dict) and isinstance(cached.get("units"),dict) else {}
        for code in valid:
            entry=entries.get(code)
            try: fresh=isinstance(entry,dict) and now-float(entry.get("checkedAt",0))<ttl
            except (TypeError,ValueError,OverflowError): fresh=False
            if fresh:
                metadata[code]={key:entry.get(key) for key in ("name","municipalityCode","currentManagement","currentNatureGroup","currentNatureCode","neighborhood")}
            else: missing.append(code)
        if missing:
            if progress: progress(92,f"Consultando dados cadastrais das unidades no CNES · {len(missing)} unidade(s)")
            def lookup(code):
                data,ok=_cnes_open_data_json(f"/cnes/estabelecimentos/{code}")
                if not ok: return code,None,False
                if not isinstance(data,dict): return code,"",True
                returned=re.sub(r"\D","",str(data.get("codigo_cnes") or data.get("co_cnes") or "")).zfill(7)
                if returned!=code: return code,{},True
                name=next((_report_label(data.get(key) or "")[:180] for key in ("nome_fantasia","nome_razao_social") if _report_label(data.get(key) or "")),"")
                municipality=re.sub(r"\D","",str(data.get("codigo_municipio") or ""))
                nature_code=_cnes_nature_code(data.get("descricao_natureza_juridica_estabelecimento"))
                management=_normalize_cnes_management(data.get("tipo_gestao") or data.get("descricao_esfera_administrativa"))
                nature_group=_normalize_cnes_nature_group("",nature_code)
                neighborhood=_report_label(data.get("bairro_estabelecimento") or "")[:120]
                return code,{"name":name,"municipalityCode":municipality if re.fullmatch(r"\d{6}",municipality) else "","currentManagement":management,"currentNatureGroup":nature_group,"currentNatureCode":nature_code,"neighborhood":neighborhood},True
            with ThreadPoolExecutor(max_workers=min(8,len(missing)),thread_name_prefix="sinan-cnes") as executor:
                futures=[executor.submit(lookup,code) for code in missing]
                for future in as_completed(futures):
                    try: code,record,ok=future.result()
                    except Exception: failed+=1; continue
                    if not ok: failed+=1; continue
                    entries[code]={**(record if isinstance(record,dict) else {}),"checkedAt":now}
                    metadata[code]=record if isinstance(record,dict) else {}
            cache_write(target,{"fetched_at":now,"units":entries},max_bytes=2_000_000,keep=2)
    for code in valid:
        record=metadata.setdefault(code,{})
        historical_record=historical.get(code) if isinstance(historical,dict) else None
        if isinstance(historical_record,dict) and historical_record.get("source")=="competence":
            record.update({"management":historical_record.get("management") or "NAO_INFORMADA","natureGroup":historical_record.get("natureGroup") or "NAO_INFORMADA","natureCode":historical_record.get("legalNature") or "","classificationSource":"competence"})
        else:
            record.update({"management":record.get("currentManagement") or "NAO_INFORMADA","natureGroup":record.get("currentNatureGroup") or "NAO_INFORMADA","natureCode":record.get("currentNatureCode") or "","classificationSource":"current" if record.get("currentManagement") or record.get("currentNatureGroup") else "unavailable"})
    unresolved=sum(1 for code in valid if not metadata.get(code,{}).get("municipalityCode"))
    return metadata,unresolved,failed

def predefined_sinan_dengue(payload: dict[str,Any], progress=None):
    if progress is None: return _predefined_sinan_dengue_impl(payload,None)
    stop=threading.Event(); progress_lock=threading.Lock()
    latest={"percent":5,"stage":"Preparando o arquivo oficial do SINAN"}
    def publish(percent,stage):
        with progress_lock:
            latest["percent"]=percent; latest["stage"]=stage
            progress(percent,stage)
    def heartbeat():
        while not stop.wait(4):
            try:
                with progress_lock: progress(latest["percent"],latest["stage"])
            except Exception: pass
    thread=threading.Thread(target=heartbeat,name="sinan-progress-heartbeat",daemon=True)
    thread.start()
    try: return _predefined_sinan_dengue_impl(payload,publish)
    finally:
        stop.set(); thread.join(timeout=1)

def _predefined_sinan_dengue_impl(payload: dict[str,Any], progress=None):
    """Show weekly SINAN notifications, then the units and residences behind a week."""
    report_id=str(payload.get("predefinedReport") or "sinan-dengue")
    if report_id not in SINAN_AGRAVOS: raise ValueError("Agravo SINAN não disponível neste relatório.")
    agravo=SINAN_AGRAVOS[report_id]["label"]
    year=payload.get("year")
    month=payload.get("month")
    uf=str(payload.get("uf") or "").upper()
    municipality=str(payload.get("municipalityCode") or "")
    municipality_name=_report_label(payload.get("municipalityName") or "")[:100]
    view=str(payload.get("view") or "summary")
    if view not in {"summary","detail","full"}: raise ValueError("Selecione um agrupamento válido para o relatório do SINAN.")
    if not isinstance(year,int) or year<2000 or year>date.today().year: raise ValueError("Selecione um ano entre 2000 e o ano atual.")
    if not isinstance(month,int) or month<1 or month>12: raise ValueError("Selecione uma competência válida.")
    if uf!="PA" or municipality!="150140": raise ValueError("Este relatório mostra notificações registradas em unidades de Belém, no Pará.")
    week_index=payload.get("weekIndex") if view=="detail" else None
    if view=="detail" and (not isinstance(week_index,int) or not 1<=week_index<=53):
        raise ValueError("Selecione uma semana epidemiológica válida para detalhar.")
    if progress: progress(5,"Preparando o arquivo oficial do SINAN")
    source_rows,source_units,source_details,source_mode,updated_at,invalid_onset,has_unit_field=_sinan_dengue_source_rows(year,municipality,report_id,progress)
    if progress: progress(89,"Associando unidades e filtros cadastrais do CNES")
    municipality_names={}
    try: municipality_names=_sinan_ibge_municipalities()
    except Exception: municipality_names={}
    rows=[]
    unit_unresolved=0; unit_lookup_failures=0; out_of_bel_em_notifications=0; filtered_notifications=0
    valid_management={"MUNICIPAL","ESTADUAL","DUPLA","NAO_INFORMADA"}
    valid_nature={"PUBLICO","PRIVADO","SEM_FINS_LUCRATIVOS","PESSOA_FISICA","OUTROS","NAO_INFORMADA"}
    def selected_codes(key,allowed):
        raw=payload.get(key) or []
        if isinstance(raw,(str,int,float)): raw=[raw]
        if not isinstance(raw,(list,tuple)) or len(raw)>20: raise ValueError("Os filtros CNES selecionados são inválidos.")
        values={str(item or "").strip().upper() for item in raw if str(item or "").strip()}
        if not values.issubset(allowed): raise ValueError("Os filtros CNES selecionados contêm uma categoria desconhecida.")
        return values
    selected_management=selected_codes("cnesManagementCode",valid_management)
    selected_nature=selected_codes("cnesNatureGroupCode",valid_nature)
    management_labels={"MUNICIPAL":"Gestão municipal","ESTADUAL":"Gestão estadual","DUPLA":"Dupla gestão","NAO_INFORMADA":"Gestão não identificada"}
    nature_labels={"PUBLICO":"Natureza pública","PRIVADO":"Natureza privada","SEM_FINS_LUCRATIVOS":"Sem fins lucrativos","PESSOA_FISICA":"Pessoa física","OUTROS":"Outras naturezas","NAO_INFORMADA":"Natureza não identificada"}
    selected_units=[dict(item) for item in source_units if int(item.get("month",0))==month]
    selected_details=[dict(item) for item in source_details if int(item.get("month",0))==month and (view=="full" or int(item.get("week",0))==week_index)] if view in {"detail","full"} else []
    cnes_codes=[str(item.get("unitCode") or "") for item in selected_units]
    unit_metadata,unit_unresolved,unit_lookup_failures=_sinan_cnes_unit_metadata(cnes_codes,year,month,progress)
    historical_classification_units=set(); current_classification_units=set()
    eligible_units={}
    for unit in selected_units:
        code=str(unit.get("unitCode") or "")
        metadata=unit_metadata.get(code,{})
        if not code or metadata.get("municipalityCode")!="150140":
            out_of_bel_em_notifications+=int(unit.get("notifications",0)); continue
        management=str(metadata.get("management") or "NAO_INFORMADA")
        nature=str(metadata.get("natureGroup") or "NAO_INFORMADA")
        if metadata.get("classificationSource")=="competence": historical_classification_units.add(code)
        elif metadata.get("classificationSource")=="current": current_classification_units.add(code)
        if selected_management and management not in selected_management:
            filtered_notifications+=int(unit.get("notifications",0)); continue
        if selected_nature and nature not in selected_nature:
            filtered_notifications+=int(unit.get("notifications",0)); continue
        eligible_units[code]={
            "unitName":metadata.get("name") or f"Unidade CNES {code}","unitCode":code,
            "managementName":management_labels.get(management,"Gestão não identificada"),
            "natureGroupName":nature_labels.get(nature,"Natureza não identificada"),
            "neighborhood":metadata.get("neighborhood") or "Não informado",
        }
    metric_keys=("notifications","probable","confirmed","severe","dengueDeaths","discarded","hospitalizations","pregnant","diseaseDeaths","pending")
    if view=="summary":
        weekly={}
        for unit in selected_units:
            if str(unit.get("unitCode") or "") not in eligible_units: continue
            week=int(unit["week"])
            row=weekly.setdefault(week,{"code":str(week),"week":week,"weekName":f"Semana epidemiológica {week:02d}",**{key:0 for key in metric_keys}})
            for key in metric_keys: row[key]+=int(unit.get(key,0))
        rows=sorted(weekly.values(),key=lambda item:item["week"])
    else:
        for item in selected_details:
            code=str(item.get("unitCode") or "")
            unit=eligible_units.get(code)
            if unit is None: continue
            residence=str(item.get("residenceCode") or "")
            residence_name="Residência ignorada ou exterior" if residence=="999999" else municipality_names.get(residence,"Município de residência não identificado") if residence else "Residência não informada"
            rows.append({**item,**unit,"weekName":f"Semana epidemiológica {int(item['week']):02d}","residenceName":residence_name})
        rows.sort(key=lambda item:(item["week"],-item["notifications"],item["unitName"].casefold(),item["residenceName"].casefold()))
    month_names=("","janeiro","fevereiro","março","abril","maio","junho","julho","agosto","setembro","outubro","novembro","dezembro")
    monthly_counts=defaultdict(int)
    for item in source_rows: monthly_counts[int(item.get("month",0))]+=int(item.get("notifications",0))
    available_month=max((value for value,count in monthly_counts.items() if 1<=value<=12 and count>0),default=0)
    empty_state_message=""
    if not rows and view=="summary" and out_of_bel_em_notifications:
        empty_state_message=(f"Não foi possível confirmar no cadastro atual do CNES que as unidades responsáveis por {out_of_bel_em_notifications:,} notificação(ões) estão localizadas em Belém. Esses registros foram mantidos fora da tabela para preservar o recorte municipal.".replace(",","."))
    elif not rows and view=="summary" and filtered_notifications:
        empty_state_message="Há notificações de unidades de Belém neste mês, mas nenhuma atende aos filtros CNES selecionados. Remova ou ajuste os filtros de gestão e natureza jurídica."
    elif not rows and view=="detail":
        empty_state_message=f"A semana epidemiológica {week_index:02d} não tem notificações das unidades de Belém compatíveis com o recorte selecionado."
    elif not rows:
        if available_month:
            empty_state_message=(f"O arquivo oficial do SINAN, atualizado em {updated_at or 'data não informada'}, ainda não traz notificações com início dos sintomas em {month_names[month]} de {year} para {municipality_name or municipality}. "
                f"O mês mais recente com registros neste arquivo é {month_names[available_month]} de {year} ({format(monthly_counts[available_month], ',').replace(',', '.')} notificações). A ausência de registros pode refletir atraso de notificação ou atualização e não confirma ausência de casos.")
        else:
            empty_state_message=(f"O arquivo oficial do SINAN, atualizado em {updated_at or 'data não informada'}, não traz notificações com início dos sintomas para {municipality_name or municipality} em {year}. "
                "A ausência de registros pode refletir atraso de notificação ou atualização e não confirma ausência de casos.")
    totals={key:sum(int(row.get(key,0)) for row in rows) for key in metric_keys}
    total_month_records=totals["notifications"]
    additional_metrics=(
        [("probable","PROVÁVEIS · NÃO DESCARTADAS"),("confirmed","DENGUE CONFIRMADA"),("severe","CASOS GRAVES"),("dengueDeaths","ÓBITOS POR DENGUE"),("discarded","DESCARTADAS")]
        if report_id=="sinan-dengue" else
        [("probable","PROVÁVEIS · NÃO DESCARTADAS"),("confirmed","CHIKUNGUNYA CONFIRMADA"),("hospitalizations","NOTIFICAÇÕES COM INTERNAÇÃO"),("diseaseDeaths","ÓBITOS POR CHIKUNGUNYA"),("discarded","DESCARTADAS"),("pending","SEM CONCLUSÃO")]
        if report_id=="sinan-chikungunya" else
        [("probable","PROVÁVEIS · NÃO DESCARTADAS"),("confirmed","ZIKA CONFIRMADA"),("pregnant","GESTANTES NOTIFICADAS"),("diseaseDeaths","ÓBITOS POR ZIKA"),("discarded","DESCARTADAS"),("pending","SEM CONCLUSÃO")]
    )
    disease_name="Chikungunya" if report_id=="sinan-chikungunya" else "Zika"
    summary_kpis=(
        [{"label":"DENGUE CONFIRMADA","value":{"value":totals["confirmed"]}},{"label":"CASOS GRAVES","value":{"value":totals["severe"]}},{"label":"ÓBITOS POR DENGUE","value":{"value":totals["dengueDeaths"]}}]
        if report_id=="sinan-dengue" else
        [{"label":f"{disease_name.upper()} CONFIRMADA","value":{"value":totals["confirmed"]}},{"label":"NOTIFICAÇÕES COM INTERNAÇÃO" if report_id=="sinan-chikungunya" else "GESTANTES NOTIFICADAS","value":{"value":totals["hospitalizations" if report_id=="sinan-chikungunya" else "pregnant"]}},{"label":f"ÓBITOS POR {disease_name.upper()}","value":{"value":totals["diseaseDeaths"]}}]
    )
    result={
        "ok":True,"report":report_id,"view":view,"flatTable":True,"file":"SINAN · CSV oficial",
        "year":year,"month":month,"uf":uf,"state":PREDEFINED_UF_NAMES[uf],"municipality":"Belém","municipalityCode":municipality,"updatedAt":updated_at,"establishmentCode":str(week_index) if week_index else None,"establishmentName":f"Semana epidemiológica {week_index:02d}" if week_index else None,"emptyStateMessage":empty_state_message,
        "columns":[
            {"id":"week" if view!="detail" else "unit","label":"SEMANA EPIDEMIOLÓGICA" if view!="detail" else "UNIDADE NOTIFICADORA","kind":"primary","primaryField":"weekName" if view!="detail" else "unitName","secondaryField":"unitCode" if view=="detail" else None,"secondaryPrefix":"CNES " if view=="detail" else "","filterFields":["weekName","week"] if view!="detail" else ["unitName","unitCode"],"sortField":"week" if view!="detail" else "unitName","type":"text","sticky":True},
            *([{"id":"unit","label":"UNIDADE NOTIFICADORA","kind":"primary","primaryField":"unitName","secondaryField":"unitCode","secondaryPrefix":"CNES ","filterFields":["unitName","unitCode"],"sortField":"unitName","type":"text"}] if view=="full" else []),
            *([{"id":"residence","label":"MUNICÍPIO DE RESIDÊNCIA","field":"residenceName","type":"text","filterFields":["residenceName","residenceCode"]}] if view in {"detail","full"} else []),
            {"id":"notifications","label":"NOTIFICAÇÕES","metricId":"notifications","type":"number","decimals":0},
            *({"id":key,"label":label,"metricId":key,"type":"number","decimals":0} for key,label in additional_metrics),
            *([{"id":"neighborhood","label":"BAIRRO DA UNIDADE","field":"neighborhood","type":"text"},{"id":"management","label":"TIPO DE GESTÃO · CNES","field":"managementName","type":"text"},{"id":"nature","label":"NATUREZA JURÍDICA · CNES","field":"natureGroupName","type":"text"}] if view in {"detail","full"} else []),
            *([{"id":"detail","label":"DETALHAR","kind":"action","actionLabel":"Detalhar →"}] if view=="summary" else []),
        ],
        "metrics":[
            {"id":"notifications","label":"Notificações","decimals":0},
            *({"id":key,"label":label.title(),"decimals":0} for key,label in additional_metrics),
        ],
        "kpis":[
            {"label":"NOTIFICAÇÕES","value":{"value":totals["notifications"]}},
            *summary_kpis,
        ],
        "records":total_month_records,"rows":rows,"notes":[
            f"Fonte: arquivo CSV anual oficial do SINAN · {source_mode}. Município notificante: {municipality_name or municipality} ({municipality}). Arquivo atualizado em {updated_at or 'data não informada'}.",
            "Mês definido pela data de início dos sintomas (DT_SIN_PRI); semana epidemiológica informada no campo SEM_PRI do SINAN. A tabela detalhada reúne semana, unidade notificadora e município de residência. Semanas que atravessam dois meses aparecem em cada recorte com apenas os dias daquele mês.",
            "Nome, município cadastral e bairro da unidade vêm do CNES atual. Gestão e natureza jurídica usam primeiro o CNES da competência; quando não há registro histórico, o cadastro atual complementa a informação.",
            *( [f"A gestão e a natureza jurídica foram confirmadas no CNES da competência {year:04d}{month:02d} para {len(historical_classification_units)} unidade(s).".replace(",",".")] if historical_classification_units else [] ),
            *( [f"Gestão e natureza jurídica vieram do cadastro atual do CNES para {len(current_classification_units)} unidade(s), sem classificação histórica disponível para {year:04d}{month:02d}.".replace(",",".")] if current_classification_units else [] ),
            *(["Prováveis · não descartadas segue a definição do Portal de Dados Abertos do SUS: notificações suspeitas, exceto as descartadas. Dengue confirmada exige classificação final de dengue (1–4, 10–12) e critério laboratorial ou clínico-epidemiológico. Casos graves usam as classificações 2, 3, 4, 11 e 12 com critério confirmado; óbitos exigem evolução ‘óbito pelo agravo’ (código 2)."] if report_id=="sinan-dengue" else [
                f"Para {agravo}, prováveis são notificações não descartadas; confirmadas exigem classificação final {'13' if report_id=='sinan-chikungunya' else '1'}, descartadas usam {'5' if report_id=='sinan-chikungunya' else '2'}, e sem conclusão reúne classificação vazia, 0, 8 ou 9. Óbitos pelo agravo exigem caso confirmado e evolução 2.",
                "Internação registrada (HOSPITALIZ = 1) conta notificações, inclusive as ainda não confirmadas; não representa internações causadas por chikungunya." if report_id=="sinan-chikungunya" else "Gestantes notificadas (CS_GESTANT = 1 a 4) contam notificações de gestantes, inclusive as não confirmadas; não representam gestantes com Zika confirmada."
            ]),
            "Os totais contam notificações publicadas, sem deduplicação de pessoas. O SINAN é atualizado e revisado; para incidência, use município de residência e a população oficial como denominador.",
            *([empty_state_message] if empty_state_message else []),
            *( [f"{invalid_onset:,} registro(s) consultado(s) não tinham data de início dos sintomas ou semana epidemiológica válida e ficaram fora da série.".replace(",",".")] if invalid_onset else [] ),
            *( ["Alguns códigos de município de residência não foram encontrados no cadastro do IBGE; nesses casos o código foi preservado e o nome ficou não identificado."] if view=="detail" and any(row["residenceCode"] and row["residenceName"].startswith("Município de residência não") for row in rows) else [] ),
            *( [f"{out_of_bel_em_notifications:,} notificação(ões) foram omitidas porque o CNES não confirmou município Belém para a unidade ou o código não pôde ser associado.".replace(",",".")] if out_of_bel_em_notifications else [] ),
            *( [f"{filtered_notifications:,} notificação(ões) de unidades em Belém ficaram fora por não corresponderem aos filtros CNES selecionados.".replace(",",".")] if filtered_notifications else [] ),
            *( ["O serviço do CNES não respondeu para algumas unidades; os registros sem município confirmado ficaram fora do recorte Belém e podem ser consultados novamente ao atualizar o relatório."] if unit_lookup_failures else [] ),
            *( ["O CSV anual não contém o campo ID_UNIDADE; não foi possível associar notificações a unidades do CNES."] if not has_unit_field else [] ),
        ],"cachedAt":time.time(),"filters":[{"label":"Município notificante","value":"Belém"}]+([{"label":"Gestão CNES","value":", ".join(management_labels[value] for value in sorted(selected_management))}] if selected_management else [])+([{"label":"Natureza jurídica CNES","value":", ".join(nature_labels[value] for value in sorted(selected_nature))}] if selected_nature else []),
    }
    if progress: progress(98,"Preparando a tabela e os indicadores do mês")
    return result

def predefined_sia_pa_production(payload: dict[str,Any], progress=None):
    """Monthly state-level SIA production, with optional municipal and classification filters."""
    if progress: progress(2,"Conferindo a base ambulatorial")
    source=safe_file(payload.get("path",""))
    relative=source.relative_to(UPLOADS).as_posix()
    system,kind,filename_match=meta(source)
    uf=str(payload.get("uf") or "PA").strip().upper()
    if uf not in PREDEFINED_UF_CODES:
        raise ValueError("Selecione uma unidade da Federação válida.")
    if system!="SIA" or kind!="PA" or filename_match.group("uf").upper()!=uf:
        raise ValueError(f"Selecione um arquivo de Produção Ambulatorial (PA) de {uf}.")
    dbf=safe_dbf(str(payload.get("dbfPath") or converted_relative(relative)),relative)
    view=str(payload.get("predefinedView") or "summary")
    if view not in {"summary","detail"}:
        raise ValueError("A visualização solicitada não existe.")
    establishment=_report_code(str(payload.get("establishmentCode") or ""),7) if view=="detail" else ""
    if view=="detail" and (not establishment or len(re.sub(r"\D","",str(payload.get("establishmentCode") or "")))>7):
        raise ValueError("Selecione um estabelecimento válido para detalhar.")

    municipality=str(payload.get("municipalityCode") or "").strip()
    selected_filter_codes={}
    state_prefix=PREDEFINED_UF_CODES[uf]
    if municipality and (not municipality.isdigit() or len(municipality)!=6 or municipality[:2]!=state_prefix):
        raise ValueError("O município selecionado não pertence à unidade da Federação escolhida.")
    for spec in PREDEFINED_FILTER_SPECS:
        raw_values=payload.get(spec["code"]) or []
        if isinstance(raw_values,(str,int,float)): raw_values=[raw_values]
        if not isinstance(raw_values,(list,tuple)):
            raise ValueError(f"O filtro {spec['label'].lower()} é inválido.")
        if len(raw_values)>500:
            raise ValueError(f"Selecione no máximo 500 categorias em {spec['label'].lower()}.")
        codes=[]
        for raw_value in raw_values:
            raw=str(raw_value or "").strip()
            if not raw: continue
            if not re.fullmatch(rf"[A-Za-z0-9]{{1,{spec['width']}}}",raw):
                raise ValueError(f"O filtro {spec['label'].lower()} é inválido.")
            code=raw.upper().zfill(spec["width"])
            if spec.get("stateScoped") and not code.startswith(state_prefix):
                raise ValueError("O gestor selecionado não pertence à unidade da Federação escolhida.")
            codes.append(code)
        if codes: selected_filter_codes[spec["field"]]=sorted(set(codes))

    total_records,_,_,fieldinfo=dbf_layout(dbf)
    required=["PA_UFMUN","PA_CODUNI","PA_PROC_ID","PA_QTDAPR","PA_QTDPRO","PA_VALAPR","PA_VALPRO"]
    required.extend(selected_filter_codes)
    missing=[field for field in required if field not in fieldinfo]
    if missing:
        raise ValueError("Esta competência não contém todos os campos necessários ao relatório: "+", ".join(missing))

    if progress: progress(5,"Carregando as descrições oficiais de CNES e SIGTAP")
    defname,definition=archive_def("SIA","PA")
    if definition is None:
        raise RuntimeError("A definição oficial da produção ambulatorial não está disponível.")
    definition_rows,definition_columns,definition_selections,_,_=parse_def(
        definition,[{"name":name,**info} for name,info in fieldinfo.items()]
    )
    all_options=definition_rows+definition_columns+definition_selections
    # The official SIA definition contains one CADGER relation per UF. Selecting
    # the first PA_CODUNI relation would always resolve against AC, regardless
    # of the state being tabulated. Match the state-specific CNES reference.
    establishment_relation=f"cadger{uf.lower()}.dbf"
    establishment_option=next((item for item in all_options if item.get("field")=="PA_CODUNI" and PurePosixPath(str(item.get("relation") or "").replace("\\","/")).name.lower()==establishment_relation),None)
    procedure_option=next((item for item in all_options if item.get("field")=="PA_PROC_ID" and item.get("relation")),None)
    complexity_option=next((item for item in all_options if item.get("field")=="PA_NIVCPL" and item.get("relation")),None)
    # PA_TPFIN is marked as an auxiliary field (X) in the official DEF, so it
    # is not returned by parse_def's line/column options. Its official CNV is
    # still the correct label source for showing MAC/FAEC in the detail table.
    financing_option={"field":"PA_TPFIN","relation":"CNV/FINANC.CNV"} if "PA_TPFIN" in fieldinfo else None
    selected_filter_names={}
    for spec in PREDEFINED_FILTER_SPECS:
        option=next((item for item in all_options if item.get("field")==spec["field"] and item.get("relation","").lower()==spec["relation"].lower()),None)
        if option is None and spec.get("auxiliaryRelation"):
            option={"field":spec["field"],"relation":spec["relation"]}
        selected_codes=selected_filter_codes.get(spec["field"],[])
        if not selected_codes: continue
        valid=_report_exact_relation_index(relation_mapping("SIA",option),spec["width"]) if option else {}
        if any(selected_code not in valid for selected_code in selected_codes):
            raise ValueError(f"Uma das categorias de {spec['label'].lower()} não consta na definição oficial desta base.")
        selected_filter_names[spec["key"]]=[_report_label(valid[selected_code]) for selected_code in selected_codes]
    establishment_labels=_report_relation_index(relation_mapping("SIA",establishment_option),7) if establishment_option else {}
    establishment_legal_labels=_report_relation_index(relation_mapping("SIA",{**establishment_option,"descField":"RAZ_SOCI"}),7) if establishment_option else {}
    def establishment_label(code):
        return _report_label(establishment_labels.get(code) or establishment_legal_labels.get(code) or f"CNES {code}")
    procedure_labels=_report_relation_index(relation_mapping("SIA",procedure_option),10) if procedure_option else {}
    complexity_labels=relation_mapping("SIA",complexity_option) if view=="detail" and complexity_option else {}

    sigtap_filter,sigtap_source=_sigtap_procedure_filter(payload,2000+int(filename_match.group("yy")),int(filename_match.group("mm")),fieldinfo,"PA_PROC_ID",dbf)
    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIA.zip"
    identity={"report":"sia-pa-production-v6","source":cache_file_identity(source),"dbf":cache_file_identity(dbf),"definition":cache_file_identity(archive),"view":view,"establishment":establishment,"uf":uf,"municipality":municipality,"filters":selected_filter_codes,"sigtap":payload.get("sigtapFilters"),"sigtapVersion":sigtap_source.get("sha256") if sigtap_source else None,"sigtapAuditVersion":1}
    target=cache_target("predefined-reports",identity)
    cached=cache_read(target)
    if isinstance(cached,dict) and cached.get("ok") is True:
        if progress: progress(98,"Abrindo o relatório salvo neste computador")
        return cached

    filters=[]
    if municipality: filters.append(("PA_UFMUN",municipality))
    filters.extend(selected_filter_codes.items())
    if sigtap_filter: filters.append(sigtap_filter)
    municipality_name=str(payload.get("municipalityName") or "").strip()[:80] if municipality else "Todos os municípios"
    for spec in PREDEFINED_FILTER_SPECS:
        if spec["key"] not in selected_filter_names: continue
        selected_filter_names[spec["key"]]=[value[:100] for value in selected_filter_names[spec["key"]]]
    def filter_name_summary(names):
        if len(names)<=3: return ", ".join(names)
        return ", ".join(names[:2])+f" e mais {len(names)-2}"
    manager_codes=selected_filter_codes.get("PA_GESTAO",[])
    legal_nature_codes=selected_filter_codes.get("PA_NAT_JUR",[])
    manager_names=selected_filter_names.get("manager",[])
    legal_nature_names=selected_filter_names.get("legalNature",[])
    manager_name=filter_name_summary(manager_names) if manager_names else "Todos os gestores"
    legal_nature_name=filter_name_summary(legal_nature_names) if legal_nature_names else "Todas as naturezas jurídicas"
    filter_summary=[{"label":spec["label"],"value":filter_name_summary(selected_filter_names[spec["key"]])} for spec in PREDEFINED_FILTER_SPECS if spec["key"] in selected_filter_names]
    if progress: progress(12,"Somando a produção do recorte selecionado")
    group_field="PA_CODUNI" if view=="summary" else "PA_PROC_ID"
    names=list(dict.fromkeys([group_field,"PA_CODUNI","PA_QTDAPR","PA_QTDPRO","PA_VALAPR","PA_VALPRO"]))
    has_complexity=view=="detail" and "PA_NIVCPL" in fieldinfo
    has_financing=view=="detail" and financing_option is not None
    if has_complexity: names.append("PA_NIVCPL")
    if has_financing: names.append("PA_TPFIN")
    positions={name:index for index,name in enumerate(names)}
    decimals={name:int(fieldinfo[name]["decimals"]) for name in ("PA_QTDAPR","PA_QTDPRO","PA_VALAPR","PA_VALPRO")}
    sums=defaultdict(lambda:[0,0,0,0,0,0,0,0,0,0,0])
    processed=[0]
    scope=" · ".join(part for part in (municipality_name if municipality else PREDEFINED_UF_NAMES[uf],*(filter_name_summary(selected_filter_names[spec["key"]]) for spec in PREDEFINED_FILTER_SPECS if spec["key"] in selected_filter_names)) if part)
    def scan_progress(done,_total):
        if progress and total_records:
            progress(min(94,12+int(82*done/total_records)),f"Lendo registros · {done:,} de {total_records:,} · {scope}".replace(",","."))
    for _,record in iter_dbf_fields(
        dbf,names,with_index=True,pre_filter=filters or None,processed_counter=processed,scan_callback=scan_progress if progress else None
    ):
        cnes=_report_code(record[positions["PA_CODUNI"]],7)
        if not cnes or (view=="detail" and cnes!=establishment):
            continue
        code=_report_code(record[positions[group_field]],7 if view=="summary" else 10)
        if not code:
            continue
        q_presented=scaled_integer(record[positions["PA_QTDPRO"]],decimals["PA_QTDPRO"])
        q_approved=scaled_integer(record[positions["PA_QTDAPR"]],decimals["PA_QTDAPR"])
        v_presented=scaled_integer(record[positions["PA_VALPRO"]],decimals["PA_VALPRO"])
        v_approved=scaled_integer(record[positions["PA_VALAPR"]],decimals["PA_VALAPR"])
        complexity_code=record[positions["PA_NIVCPL"]].strip() if has_complexity else ""
        financing_code=_report_code(record[positions["PA_TPFIN"]],2) if has_financing else ""
        if view=="detail":
            group_key=(code,complexity_code,financing_code)
        else:
            group_key=code
        row=sums[group_key]
        row[0]+=q_approved
        row[1]+=q_presented
        row[2]+=v_approved
        row[3]+=v_presented
        row[4]+=max(0,q_presented-q_approved)
        row[5]+=max(0,v_presented-v_approved)
        row[6]+=int(q_presented>0 and q_approved==0)
        row[7]+=1
    metrics=[
        {"id":"qtd_aprovada","label":"Quantidade aprovada","decimals":decimals["PA_QTDAPR"]},
        {"id":"qtd_apresentada","label":"Quantidade apresentada","decimals":decimals["PA_QTDPRO"]},
        {"id":"valor_aprovado","label":"Valor aprovado","decimals":decimals["PA_VALAPR"]},
        {"id":"valor_apresentado","label":"Valor apresentado","decimals":decimals["PA_VALPRO"]},
        {"id":"qtd_glosada","label":"Glosa de quantidade","decimals":max(decimals["PA_QTDPRO"],decimals["PA_QTDAPR"])},
        {"id":"valor_glosado","label":"Glosa de valor","decimals":max(decimals["PA_VALPRO"],decimals["PA_VALAPR"])},
        {"id":"sem_aprovacao","label":"Rejeições¹","decimals":0},
    ]
    metric_indexes=(0,1,2,3,4,5,6)
    totals=[sum(values[index] for values in sums.values()) for index in metric_indexes]
    rows=[]
    sortable_rows=[]
    financing_labels=relation_mapping("SIA",financing_option) if has_financing else {}
    for group_key,values in sums.items():
        if view=="detail":
            code,complexity_code,financing_code=group_key
            complexity_label=_report_label(str(cnv_label(complexity_labels,complexity_code) or "").strip()) if complexity_code else "Não informado"
            financing_label=(_report_label(str(cnv_label(financing_labels,financing_code) or "").strip()) if financing_code else "Não informado") if has_financing else "Não disponível na base"
        else:
            code=group_key
            complexity_label="Complexidade não disponível" if view=="detail" else ""
            financing_label="Financiamento não disponível" if view=="detail" else ""
        label=establishment_label(code) if view=="summary" else _report_label(procedure_labels.get(code) or "Descrição indisponível na referência oficial")
        row={"code":code,"label":label,"values":[scaled_text(values[index],metric["decimals"]) for index,metric in zip(metric_indexes,metrics)],"records":values[7]}
        if view=="detail": row.update({"complexity":complexity_label,"financing":financing_label})
        sort_measure=values[2]
        sortable_rows.append((-int(sort_measure),label.casefold(),code,(complexity_label.casefold(),financing_label.casefold()),row))
    sortable_rows.sort(key=lambda item:item[:4])
    rows=[item[4] for item in sortable_rows]
    total_values=[scaled_text(value,metric["decimals"]) for value,metric in zip(totals,metrics)]
    result={
        "ok":True,"report":"sia-pa-producao","view":view,"file":source.name,"path":relative,
        "year":2000+int(filename_match.group("yy")),"month":int(filename_match.group("mm")),"uf":uf,"state":PREDEFINED_UF_NAMES[uf],
        "municipality":municipality_name,"municipalityCode":municipality or None,"manager":manager_name,"managerCode":manager_codes[0] if len(manager_codes)==1 else None,
        "managerCodes":manager_codes,"legalNature":legal_nature_name,"legalNatureCode":legal_nature_codes[0] if len(legal_nature_codes)==1 else None,"legalNatureCodes":legal_nature_codes,"establishmentCode":establishment or None,
        "filters":filter_summary,
        "establishmentName":establishment_label(establishment) if establishment else None,
        "dimensionLabel":"Estabelecimento" if view=="summary" else "Código SIGTAP · Procedimento",
        "detailDimensions":[{"id":"complexity","label":"Complexidade"},{"id":"financing","label":"Financiamento (MAC/FAEC)"}] if view=="detail" else [],
        "metrics":metrics,"totals":total_values,"records":sum(values[7] for values in sums.values()),"rows":rows,
        "notes":["No detalhamento, um mesmo procedimento pode aparecer em mais de uma linha quando houver diferenças de complexidade ou financiamento (MAC/FAEC).","Glosas são calculadas pela diferença positiva entre o apresentado e o aprovado.","¹ A base PA não tem um campo separado de rejeição. O indicador conta as linhas com quantidade apresentada maior que zero e quantidade aprovada igual a zero; não representa um total oficial de registros rejeitados."],
    }
    _attach_sigtap_source(result,sigtap_source)
    if progress: progress(97,"Finalizando totais e descrições")
    cache_write(target,result,max_bytes=25_000_000,keep=30)
    return result

def predefined_sih_rd_production(payload: dict[str,Any], progress=None):
    """Monthly SIH/RD production by hospital, with official optional filters."""
    if progress: progress(2,"Conferindo a base de AIHs")
    source=safe_file(payload.get("path",""))
    relative=source.relative_to(UPLOADS).as_posix()
    system,kind,filename_match=meta(source)
    uf=str(payload.get("uf") or "PA").strip().upper()
    if uf not in PREDEFINED_UF_CODES:
        raise ValueError("Selecione uma unidade da Federação válida.")
    if system!="SIH" or kind!="RD" or filename_match.group("uf").upper()!=uf:
        raise ValueError(f"Selecione um arquivo de AIH reduzida (RD) de {uf}.")
    dbf=safe_dbf(str(payload.get("dbfPath") or converted_relative(relative)),relative)
    view=str(payload.get("predefinedView") or "summary")
    if view not in {"summary","detail"}:
        raise ValueError("A visualização solicitada não existe.")
    establishment=_report_code(str(payload.get("establishmentCode") or ""),7) if view=="detail" else ""
    if view=="detail" and (not establishment or len(re.sub(r"\D","",str(payload.get("establishmentCode") or "")))>7):
        raise ValueError("Selecione um estabelecimento válido para detalhar.")

    municipality=str(payload.get("municipalityCode") or "").strip()
    if municipality and (not municipality.isdigit() or len(municipality)!=6 or municipality[:2]!=PREDEFINED_UF_CODES[uf]):
        raise ValueError("O município selecionado não pertence à unidade da Federação escolhida.")

    total_records,_,_,fieldinfo=dbf_layout(dbf)
    defname,definition=archive_def("SIH","RD")
    if definition is None:
        raise RuntimeError("A definição oficial de AIH reduzida não está disponível.")
    definition_options=_report_definition_options(definition)
    def exact_option(field, relation):
        return next((item for item in definition_options if item.get("field")==field and item.get("relation","").lower()==relation.lower()),None)
    cnes_relation=f"DBF/TCNES{uf}.DBF"
    cnes_option=next((item for item in definition_options if item.get("field")=="CNES" and PurePosixPath(item.get("relation","")).name.lower()==PurePosixPath(cnes_relation).name.lower()),None)
    procedure_option=exact_option("PROC_REA","DBF/TB_SIGTAW.DBF")
    if not cnes_option or not procedure_option:
        raise RuntimeError("A definição oficial não contém as referências de hospitais e procedimentos necessárias ao relatório.")

    selected_filter_codes={}
    selected_filter_names={}
    for spec in PREDEFINED_SIH_FILTER_SPECS:
        raw_values=payload.get(spec["field"]) or []
        if not raw_values: continue
        option=exact_option(spec["field"],spec["relation"])
        if not option:
            raise ValueError(f"O filtro {spec['label'].lower()} não existe na definição oficial desta base.")
        mapping=relation_mapping("SIH",option)
        codes=_report_expand_filter_values(raw_values,spec,mapping)
        if codes:
            selected_filter_codes[spec["field"]]=codes
            selected_names=sorted({_report_label(cnv_label(mapping,code)) for code in codes if cnv_label(mapping,code)})
            selected_filter_names[spec["key"]]=selected_names

    required=["CNES","N_AIH","PROC_REA","VAL_TOT","VAL_SH","VAL_SP"]
    if municipality: required.append("MUNIC_MOV")
    required.extend(selected_filter_codes)
    missing=[field for field in required if field not in fieldinfo]
    if missing:
        raise ValueError("Esta competência não contém os campos necessários ao relatório: "+", ".join(missing))

    if progress: progress(6,"Carregando nomes de hospitais e procedimentos SIGTAP")
    cnes_labels=_report_relation_index(relation_mapping("SIH",cnes_option),7)
    procedure_labels=_report_relation_index(relation_mapping("SIH",procedure_option),10)
    filter_mappings={}
    for spec in PREDEFINED_SIH_FILTER_SPECS:
        option=exact_option(spec["field"],spec["relation"])
        filter_mappings[spec["field"]]=relation_mapping("SIH",option) if option else {}
    def hospital_label(code):
        return _report_label(cnes_labels.get(code) or f"CNES {code}")

    sigtap_filter,sigtap_source=_sigtap_procedure_filter(payload,2000+int(filename_match.group("yy")),int(filename_match.group("mm")),fieldinfo,"PROC_REA",dbf)
    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIH.zip"
    identity={"report":"sih-rd-production-v1","source":cache_file_identity(source),"dbf":cache_file_identity(dbf),"definition":cache_file_identity(archive),"view":view,"establishment":establishment,"uf":uf,"municipality":municipality,"filters":selected_filter_codes,"sigtap":payload.get("sigtapFilters"),"sigtapVersion":sigtap_source.get("sha256") if sigtap_source else None,"sigtapAuditVersion":1}
    target=cache_target("predefined-reports",identity)
    cached=cache_read(target)
    if isinstance(cached,dict) and cached.get("ok") is True:
        if progress: progress(98,"Abrindo o relatório salvo neste computador")
        return cached

    for spec in PREDEFINED_SIH_FILTER_SPECS:
        if spec["key"] in selected_filter_names:
            selected_filter_names[spec["key"]]=[value[:120] for value in selected_filter_names[spec["key"]]]
    def filter_name_summary(names):
        if len(names)<=3: return ", ".join(names)
        return ", ".join(names[:2])+f" e mais {len(names)-2}"
    filter_summary=[{"label":spec["label"],"value":filter_name_summary(selected_filter_names[spec["key"]])} for spec in PREDEFINED_SIH_FILTER_SPECS if spec["key"] in selected_filter_names]
    municipality_name=str(payload.get("municipalityName") or "").strip()[:80] if municipality else "Todos os municípios"
    filters=[]
    if municipality: filters.append(("MUNIC_MOV",municipality))
    filters.extend(selected_filter_codes.items())
    if sigtap_filter: filters.append(sigtap_filter)
    if progress: progress(12,"Somando AIHs e valores do recorte selecionado")

    group_field="CNES" if view=="summary" else "PROC_REA"
    names=list(dict.fromkeys([group_field,"CNES","N_AIH","PROC_REA","VAL_TOT","VAL_SH","VAL_SP",*("COMPLEX","FINANC","FAEC_TP")]))
    names=[name for name in names if name in fieldinfo]
    positions={name:index for index,name in enumerate(names)}
    decimals={name:int(fieldinfo[name]["decimals"]) for name in ("VAL_TOT","VAL_SH","VAL_SP")}
    sums=defaultdict(lambda:[0,0,0,0])
    processed=[0]
    selected_names=[name for spec in PREDEFINED_SIH_FILTER_SPECS if spec["key"] in selected_filter_names for name in selected_filter_names[spec["key"]]]
    scope=" · ".join(part for part in (municipality_name if municipality else PREDEFINED_UF_NAMES[uf],*selected_names[:3]) if part)
    def scan_progress(done,_total):
        if progress and total_records:
            percent=min(94,12+int(82*done/total_records))
            progress(percent,f"Lendo registros de AIH · {done:,} de {total_records:,} · {scope}".replace(",","."))

    for _,record in iter_dbf_fields(dbf,names,with_index=True,pre_filter=filters or None,processed_counter=processed,scan_callback=scan_progress if progress else None):
        cnes=_report_code(record[positions["CNES"]],7)
        if not cnes or (view=="detail" and cnes!=establishment): continue
        if not str(record[positions["N_AIH"]] or "").strip(): continue
        procedure=_report_code(record[positions["PROC_REA"]],10)
        complexity=_report_code(record[positions["COMPLEX"]],2) if "COMPLEX" in positions else ""
        financing=_report_code(record[positions["FINANC"]],2) if "FINANC" in positions else ""
        faec_type=_report_code(record[positions["FAEC_TP"]],6) if "FAEC_TP" in positions else ""
        group_key=cnes if view=="summary" else (procedure,complexity,financing,faec_type)
        values=sums[group_key]
        values[0]+=1
        values[1]+=scaled_integer(record[positions["VAL_TOT"]],decimals["VAL_TOT"])
        values[2]+=scaled_integer(record[positions["VAL_SH"]],decimals["VAL_SH"])
        values[3]+=scaled_integer(record[positions["VAL_SP"]],decimals["VAL_SP"])

    metrics=[
        {"id":"qtd_aih","label":"AIHs processadas","decimals":0},
        {"id":"valor_total","label":"Valor total AIH","decimals":decimals["VAL_TOT"]},
        {"id":"valor_sh","label":"Serviços hospitalares","decimals":decimals["VAL_SH"]},
        {"id":"valor_sp","label":"Serviços profissionais","decimals":decimals["VAL_SP"]},
    ]
    totals=[sum(values[index] for values in sums.values()) for index in range(4)]
    complexity_labels=filter_mappings.get("COMPLEX",{})
    financing_labels=filter_mappings.get("FINANC",{})
    faec_labels=filter_mappings.get("FAEC_TP",{})
    sortable_rows=[]
    for group_key,values in sums.items():
        if view=="summary":
            code=group_key
            label=hospital_label(code)
            dimension_values={}
        else:
            procedure,complexity,financing,faec_type=group_key
            code=procedure
            label=_report_label(procedure_labels.get(code) or "Procedimento principal sem descrição oficial") if code else "Procedimento principal não informado"
            dimension_values={
                "complexity":_report_label(cnv_label(complexity_labels,complexity)) if complexity else "Não informado",
                "financing":_report_label(cnv_label(financing_labels,financing)) if financing else "Não informado",
                "faecType":_report_label(cnv_label(faec_labels,faec_type)) if faec_type else "Não se aplica / não informado",
            }
        row={"code":code,"label":label,"values":[scaled_text(values[index],metric["decimals"]) for index,metric in enumerate(metrics)],"records":values[0],**dimension_values}
        sortable_rows.append((-values[1],label.casefold(),code,tuple(dimension_values.values()),row))
    sortable_rows.sort(key=lambda item:item[:4])
    rows=[item[4] for item in sortable_rows]
    result={
        "ok":True,"report":"sih-rd-producao","view":view,"file":source.name,"path":relative,
        "year":2000+int(filename_match.group("yy")),"month":int(filename_match.group("mm")),"uf":uf,"state":PREDEFINED_UF_NAMES[uf],
        "municipality":municipality_name,"municipalityCode":municipality or None,"establishmentCode":establishment or None,
        "establishmentName":hospital_label(establishment) if establishment else None,"filters":filter_summary,
        "dimensionLabel":"Estabelecimento hospitalar" if view=="summary" else "Procedimento principal · SIGTAP",
        "detailDimensions":[{"id":"complexity","label":"Complexidade"},{"id":"financing","label":"Financiamento"},{"id":"faecType","label":"Subtipo FAEC"}],
        "metrics":metrics,"totals":[scaled_text(value,metric["decimals"]) for value,metric in zip(totals,metrics)],
        "records":sum(values[0] for values in sums.values()),"rows":rows,
        "notes":[
            "Este relatório usa o SIH/RD: cada registro representa uma AIH processada na competência e no local de internação. AIHs de continuidade podem ser renovadas em competências sucessivas; por isso, o total mensal não equivale necessariamente a internações únicas.",
            "O filtro de município usa o campo MUNIC_MOV (município da internação), não o município de residência do paciente.",
            "O detalhamento apresenta o procedimento principal da AIH. Procedimentos especiais e secundários não são abertos como itens independentes nesta versão.",
            "Os valores hospitalares e profissionais aparecem também separados para consulta. O valor total é o montante da AIH; não some novamente as parcelas ao total.",
            "Arquivos de AIH rejeitada ou com erro (RJ/ER) não entram nesta soma; esta tabulação não calcula glosas ou rejeições.",
        ],
    }
    _attach_sigtap_source(result,sigtap_source)
    if progress: progress(97,"Finalizando totais e descrições oficiais")
    cache_write(target,result,max_bytes=25_000_000,keep=30)
    return result

def predefined_sih_admission_flow(payload: dict[str,Any], progress=None):
    """Aggregate processed SIH/RD admissions by residence, destination and hospital."""
    if progress: progress(2,"Conferindo a base de AIHs processadas")
    source=safe_file(payload.get("path",""))
    relative=source.relative_to(UPLOADS).as_posix()
    system,kind,filename_match=meta(source)
    view=str(payload.get("predefinedView") or "summary")
    if view not in {"summary","detail"}:
        raise ValueError("A visualização solicitada não existe.")
    uf=str(payload.get("uf") or "PA").strip().upper()
    if uf not in PREDEFINED_UF_CODES:
        raise ValueError("Selecione uma unidade da Federação válida.")
    if system!="SIH" or kind!="RD" or filename_match.group("uf").upper()!=uf:
        raise ValueError(f"Selecione um arquivo de AIH reduzida (RD) de {uf}.")
    dbf=safe_dbf(str(payload.get("dbfPath") or converted_relative(relative)),relative)
    municipality=str(payload.get("municipalityCode") or "").strip()
    if municipality and (not municipality.isdigit() or len(municipality)!=6 or municipality[:2]!=PREDEFINED_UF_CODES[uf]):
        raise ValueError("O município de internação selecionado não pertence à unidade da Federação escolhida.")
    origin_code=destination_code=establishment=""
    if view=="detail":
        origin_raw=re.sub(r"\D","",str(payload.get("originMunicipalityCode") or ""))
        destination_raw=re.sub(r"\D","",str(payload.get("destinationMunicipalityCode") or ""))
        establishment_raw=re.sub(r"\D","",str(payload.get("establishmentCode") or ""))
        if len(origin_raw)!=6 or len(destination_raw)!=6 or not 1<=len(establishment_raw)<=7:
            raise ValueError("A origem, o destino e o estabelecimento desta rota precisam ser informados para detalhar.")
        origin_code=origin_raw
        destination_code=destination_raw
        establishment=establishment_raw.zfill(7)
        if destination_code[:2]!=PREDEFINED_UF_CODES[uf]:
            raise ValueError("O município de destino não pertence à unidade da Federação escolhida.")
        if municipality and municipality!=destination_code:
            raise ValueError("O destino desta rota não corresponde ao município selecionado.")

    total_records,_,_,fieldinfo=dbf_layout(dbf)
    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIH.zip"
    _,definition=archive_def("SIH","RD")
    if definition is None:
        raise RuntimeError("A definição oficial de AIH reduzida não está disponível.")
    options=_report_definition_options(definition)
    def exact_option(field,relation):
        return next((item for item in options if item.get("field")==field and item.get("relation","").lower()==relation.lower()),None)
    cnes_relation=f"TCNES{uf}.DBF"
    cnes_option=next((item for item in options if item.get("field")=="CNES" and PurePosixPath(item.get("relation","").replace("\\","/")).name.lower()==cnes_relation.lower()),None)
    residence_option=exact_option("MUNIC_RES","CNV/br_municip.cnv")
    destination_option=exact_option("MUNIC_MOV","CNV/br_municip.cnv")
    if not cnes_option or not residence_option or not destination_option:
        raise RuntimeError("A definição oficial do SIH não contém as referências de município de residência, município de internação e CNES necessárias ao fluxo.")

    selected_filter_codes={}
    selected_filter_names={}
    for spec in PREDEFINED_SIH_FILTER_SPECS:
        raw_values=payload.get(spec["field"]) or []
        if not raw_values: continue
        option=exact_option(spec["field"],spec["relation"])
        if not option:
            raise ValueError(f"O filtro {spec['label'].lower()} não existe na definição oficial desta base.")
        mapping=relation_mapping("SIH",option)
        codes=_report_expand_filter_values(raw_values,spec,mapping)
        if codes:
            selected_filter_codes[spec["field"]]=codes
            selected_filter_names[spec["key"]]=sorted({_report_label(cnv_label(mapping,code)) for code in codes if cnv_label(mapping,code)})

    required={"CNES","N_AIH","MUNIC_RES","MUNIC_MOV","VAL_TOT",*selected_filter_codes}
    missing=sorted(required-fieldinfo.keys())
    if missing:
        raise ValueError("Esta competência não contém os campos necessários ao fluxo de internações: "+", ".join(missing))

    detail_fields={"DT_INTER","DT_SAIDA","PROC_REA"}
    if view=="detail":
        missing_detail=sorted(detail_fields-fieldinfo.keys())
        if missing_detail:
            raise ValueError("Esta competência não contém os campos necessários ao detalhamento da AIH: "+", ".join(missing_detail))

    if progress: progress(6,"Carregando nomes de estabelecimentos e municípios")
    cnes_labels=_report_relation_index(relation_mapping("SIH",cnes_option),7)
    municipality_mapping=relation_mapping("SIH",residence_option)
    municipality_labels=_report_relation_index(municipality_mapping,6)
    procedure_labels={}
    specialty_labels={}
    exit_labels={}
    mortality_labels={}
    if view=="detail":
        procedure_option=exact_option("PROC_REA","DBF/TB_SIGTAW.DBF")
        specialty_option=exact_option("ESPEC","CNV/LEITOS.CNV")
        exit_option=exact_option("COBRANCA","CNV/SAIDAPERM.CNV")
        mortality_option=exact_option("MORTE","CNV/MORTES.CNV")
        procedure_labels=_report_relation_index(relation_mapping("SIH",procedure_option),10) if procedure_option else {}
        specialty_labels=relation_mapping("SIH",specialty_option) if specialty_option else {}
        exit_labels=relation_mapping("SIH",exit_option) if exit_option else {}
        mortality_labels=relation_mapping("SIH",mortality_option) if mortality_option else {}
    filters=[]
    if municipality: filters.append(("MUNIC_MOV",municipality))
    filters.extend(selected_filter_codes.items())
    filter_summary=[]
    for spec in PREDEFINED_SIH_FILTER_SPECS:
        names=selected_filter_names.get(spec["key"],[])
        if names:
            value=", ".join(names[:3])+(f" e mais {len(names)-3}" if len(names)>3 else "")
            filter_summary.append({"label":spec["label"],"value":value})
    municipality_name=str(payload.get("municipalityName") or "").strip()[:80] if municipality else "Todos os municípios"
    def city_name(code):
        if not code: return "Município de residência não informado"
        label=_report_label(cnv_label(municipality_mapping,code) or municipality_labels.get(code) or "")
        label=re.sub(rf"^{re.escape(code)}\s*(?:[·–—:-]\s*)?","",label).strip()
        if "IGNORADO" in label.upper() or "EXTERIOR" in label.upper(): return "Ignorado ou exterior"
        if not label or label==code: return f"Município {code}"
        return label
    identity={"report":"sih-rd-admission-flow-v2","source":cache_file_identity(source),"dbf":cache_file_identity(dbf),"definition":cache_file_identity(archive),"view":view,"uf":uf,"municipality":municipality,"filters":selected_filter_codes,"origin":origin_code,"destination":destination_code,"establishment":establishment}
    target=cache_target("predefined-reports",identity)
    cached=cache_read(target)
    if isinstance(cached,dict) and cached.get("ok") is True:
        if progress: progress(98,"Abrindo o fluxo salvo neste computador")
        return cached

    if view=="detail":
        if progress: progress(8,"Localizando as AIHs desta rota")
        detail_names=["CNES","N_AIH","MUNIC_RES","MUNIC_MOV","DT_INTER","DT_SAIDA","PROC_REA","VAL_TOT",*selected_filter_codes]
        for optional_field in ("DIAS_PERM","ESPEC","COBRANCA","MORTE"):
            if optional_field in fieldinfo: detail_names.append(optional_field)
        detail_names=list(dict.fromkeys(detail_names))
        positions={name:index for index,name in enumerate(detail_names)}
        detail_filters=[("MUNIC_RES",origin_code),("MUNIC_MOV",destination_code),("CNES",establishment)]
        detail_filters.extend((field,codes) for field,codes in selected_filter_codes.items())
        unique={}
        processed=[0]
        def detail_progress(done,_total):
            if progress and total_records:
                percent=min(94,10+int(84*done/total_records))
                progress(percent,f"Lendo AIHs da rota · {done:,} de {total_records:,}".replace(",","."))
        for _,record in iter_dbf_fields(dbf,detail_names,with_index=True,pre_filter=detail_filters,processed_counter=processed,scan_callback=detail_progress if progress else None):
            aih=re.sub(r"\D","",str(record[positions["N_AIH"]] or ""))
            cnes=_report_code(record[positions["CNES"]],7)
            if not aih or cnes!=establishment: continue
            key=(cnes,aih)
            if key in unique: continue
            admission_raw=record[positions["DT_INTER"]]
            discharge_raw=record[positions["DT_SAIDA"]]
            admission_date=_sih_calendar_date(admission_raw)
            discharge_date=_sih_calendar_date(discharge_raw)
            admission_label=admission_date.strftime("%d/%m/%Y") if admission_date else ""
            discharge_label=discharge_date.strftime("%d/%m/%Y") if discharge_date else ""
            procedure_code=_report_code(record[positions["PROC_REA"]],10)
            specialty_code=_report_code(record[positions["ESPEC"]],2) if "ESPEC" in positions else ""
            exit_code=str(record[positions["COBRANCA"]] or "").strip() if "COBRANCA" in positions else ""
            death_code=str(record[positions["MORTE"]] or "").strip() if "MORTE" in positions else ""
            unique[key]={
                "aih":aih,"admission":admission_label,"discharge":discharge_label,
                "rawAdmission":admission_date.isoformat() if admission_date else "","rawDischarge":discharge_date.isoformat() if discharge_date else "",
                "procedureCode":procedure_code,
                "procedureName":_report_label(procedure_labels.get(procedure_code) or "Procedimento sem descrição na referência oficial"),
                "specialtyCode":specialty_code,
                "specialty":_report_label(cnv_label(specialty_labels,specialty_code) or "Tipo de leito não informado") if specialty_code else "Tipo de leito não informado",
                "stayDays":_sih_record_number(record,positions,"DIAS_PERM",fieldinfo) if "DIAS_PERM" in positions else None,
                "exitCode":exit_code,
                "exitReason":_report_label(cnv_label(exit_labels,exit_code) or f"Código {exit_code}") if exit_code else "Motivo não informado",
                "deathCode":death_code,
                "deathStatus":_report_label(cnv_label(mortality_labels,death_code) or ("Com óbito" if death_code=="1" else "Sem óbito")) if death_code else "Não informado",
                "totalValue":scaled_text(scaled_integer(record[positions["VAL_TOT"]],int(fieldinfo["VAL_TOT"]["decimals"])),int(fieldinfo["VAL_TOT"]["decimals"])),
            }
        rows=list(unique.values())
        rows.sort(key=lambda row:(row["rawAdmission"],row["aih"]))
        value_decimals=int(fieldinfo["VAL_TOT"]["decimals"])
        value_total=sum(scaled_integer(row["totalValue"],value_decimals) for row in rows)
        stay_total=sum(float(row["stayDays"] or 0) for row in rows if row["stayDays"] is not None)
        exits=sum(1 for row in rows if row["discharge"])
        deaths=sum(1 for row in rows if row["deathCode"]=="1")
        columns=[
            {"id":"aih","label":"AIH","kind":"primary","primaryField":"aih","filterFields":["aih"],"sortField":"aih","type":"text"},
            {"id":"admission","label":"ENTRADA","field":"admission","type":"text","sortField":"rawAdmission"},
            {"id":"discharge","label":"SAÍDA","field":"discharge","type":"text","sortField":"rawDischarge"},
            {"id":"exitReason","label":"MOTIVO DA SAÍDA","field":"exitReason","type":"text","sortField":"exitReason","filterFields":["exitReason","exitCode"]},
            {"id":"procedure","label":"PROCEDIMENTO PRINCIPAL · SIGTAP","kind":"primary","primaryField":"procedureName","secondaryField":"procedureCode","sortField":"procedureName","filterFields":["procedureName","procedureCode"],"type":"text"},
            {"id":"specialty","label":"TIPO DE LEITO","field":"specialty","type":"text","sortField":"specialty","filterFields":["specialty","specialtyCode"]},
            {"id":"stayDays","label":"PERMANÊNCIA (DIAS)","field":"stayDays","type":"number","metricId":"stayDays","decimals":0},
            {"id":"deathStatus","label":"ÓBITO REGISTRADO","field":"deathStatus","type":"text","sortField":"deathStatus"},
            {"id":"totalValue","label":"VALOR DA AIH","field":"totalValue","type":"currency","metricId":"totalValue","decimals":value_decimals},
        ]
        destination_name=city_name(destination_code)
        origin_name=city_name(origin_code)
        hospital_name=_report_label(cnes_labels.get(establishment) or f"CNES {establishment}")
        result={"ok":True,"report":"sih-rd-fluxo","view":"detail","file":source.name,"path":relative,"year":2000+int(filename_match.group("yy")),"month":int(filename_match.group("mm")),"uf":uf,"state":PREDEFINED_UF_NAMES[uf],"municipality":municipality_name,"municipalityCode":municipality or None,"originCode":origin_code,"origin":origin_name,"destinationCode":destination_code,"destination":destination_name,"establishmentCode":establishment,"establishmentName":hospital_name,"detailTitle":f"AIHs · {origin_name} → {destination_name}","detailSubtitle":hospital_name,"filters":filter_summary,"columns":columns,"metrics":[{"id":"stayDays","label":"Permanência (dias)","decimals":0},{"id":"totalValue","label":"Valor total das AIHs","decimals":value_decimals}],"totals":[scaled_text(int(stay_total),0),scaled_text(value_total,value_decimals)],"kpis":[{"label":"AIHs da rota","value":{"value":len(rows)}},{"label":"Saídas registradas","value":{"value":exits}},{"label":"Óbitos registrados","value":{"value":deaths}},{"label":"Permanência acumulada","value":{"value":stay_total,"decimals":0,"suffix":" dias"}}],"records":len(rows),"rows":rows,"notes":[
            "Cada linha representa uma AIH processada no SIH/RD para esta origem, destino e estabelecimento. O número da AIH identifica o registro administrativo; não identifica uma pessoa nesta tela.",
            "A saída e seu motivo vêm dos campos DT_SAIDA e COBRANCA da base. AIHs sem data ou motivo informado permanecem visíveis como não informadas.",
            "O procedimento é o realizado (PROC_REA), descrito pela referência oficial associada ao SIH. A permanência e o valor são os registrados na AIH.",
        ],"cachedAt":time.time()}
        cache_write(target,result,max_bytes=50_000_000,keep=30)
        if progress: progress(97,"Concluindo o detalhamento das AIHs")
        return result

    decimals=int(fieldinfo["VAL_TOT"]["decimals"])
    names=["CNES","N_AIH","MUNIC_RES","MUNIC_MOV","VAL_TOT",*selected_filter_codes]
    names=list(dict.fromkeys(names))
    positions={name:index for index,name in enumerate(names)}
    flow=defaultdict(lambda:{"count":0,"value":0})
    seen_aihs=set()
    processed=[0]
    scope=municipality_name if municipality else PREDEFINED_UF_NAMES[uf]
    def scan_progress(done,_total):
        if progress and total_records:
            percent=min(94,10+int(84*done/total_records))
            progress(percent,f"Lendo AIHs processadas · {done:,} de {total_records:,} · {scope}".replace(",","."))
    for _,record in iter_dbf_fields(dbf,names,with_index=True,pre_filter=filters or None,processed_counter=processed,scan_callback=scan_progress if progress else None):
        cnes=_report_code(record[positions["CNES"]],7)
        aih=re.sub(r"\D","",str(record[positions["N_AIH"]] or ""))
        residence=_report_code(record[positions["MUNIC_RES"]],6)
        destination=_report_code(record[positions["MUNIC_MOV"]],6)
        if not cnes or not aih or not destination or (municipality and destination!=municipality): continue
        unique_key=(cnes,aih)
        if unique_key in seen_aihs: continue
        seen_aihs.add(unique_key)
        key=(residence,destination,cnes)
        row=flow[key]
        row["count"]+=1
        row["value"]+=scaled_integer(record[positions["VAL_TOT"]],decimals)

    uf_by_code={code:state for state,code in PREDEFINED_UF_CODES.items()}
    def flow_type(residence,destination):
        label=city_name(residence).upper()
        if not residence or residence in {"000000","999999"} or "IGNORADO" in label or "EXTERIOR" in label or "NÃO INFORMADO" in label:
            return "Residência ignorada ou exterior",False
        if residence==destination:
            return "Do próprio município",False
        origin_state=uf_by_code.get(residence[:2])
        if residence[:2]==PREDEFINED_UF_CODES[uf]:
            return f"De outro município · {uf}",True
        if origin_state:
            return f"De outro estado · {origin_state}",True
        return "Origem não classificada",False

    total_aihs=sum(item["count"] for item in flow.values())
    total_value=sum(item["value"] for item in flow.values())
    rows=[]
    for (residence,destination,cnes),values in flow.items():
        destination_label=city_name(destination)
        origin_label=city_name(residence)
        category,outside=flow_type(residence,destination)
        share_tenths=(values["count"]*1000+total_aihs//2)//total_aihs if total_aihs else 0
        rows.append({
            "origin":origin_label,"originCode":residence or "","originState":uf_by_code.get(residence[:2],""),"originStateName":PREDEFINED_UF_NAMES.get(uf_by_code.get(residence[:2],""),""),
            "destination":destination_label,"destinationCode":destination,"destinationState":uf_by_code.get(destination[:2],uf),
            "establishment":_report_label(cnes_labels.get(cnes) or f"CNES {cnes}"),"cnes":cnes,
            "flowType":category,"outsideDestination":outside,
            "aihCount":str(values["count"]),"totalValue":scaled_text(values["value"],decimals),
            "share":scaled_text(share_tenths,1),
        })
    rows.sort(key=lambda row:(-int(row["aihCount"]),row["origin"].casefold(),row["destination"].casefold(),row["establishment"].casefold()))
    metrics=[{"id":"aihCount","label":"AIHs processadas","decimals":0},{"id":"totalValue","label":"Valor total AIH","decimals":decimals}]
    columns=[
        {"id":"origin","label":"Município de residência","kind":"primary","primaryField":"origin","secondaryField":"originCode","secondaryPrefix":"Código ","type":"text","sortField":"origin","filterFields":["origin","originCode","originState"]},
        {"id":"originState","label":"UF de residência","field":"originStateName","type":"text","sortField":"originStateName"},
        {"id":"destination","label":"Município da internação","kind":"primary","primaryField":"destination","secondaryField":"destinationCode","type":"text","sortField":"destination","filterFields":["destination","destinationCode","destinationState"]},
        {"id":"establishment","label":"Estabelecimento de destino","kind":"primary","primaryField":"establishment","secondaryField":"cnes","secondaryPrefix":"CNES ","type":"text","sortField":"establishment","filterFields":["establishment","cnes"]},
        {"id":"flowType","label":"Tipo de fluxo","field":"flowType","type":"text","sortField":"flowType"},
        {"id":"aihCount","label":"AIHs","field":"aihCount","type":"number","metricId":"aihCount","decimals":0},
        {"id":"totalValue","label":"Valor total das AIHs","field":"totalValue","type":"currency","metricId":"totalValue","decimals":decimals},
        {"id":"share","label":"Participação","field":"share","type":"percent","decimals":1,"sortField":"share"},
        {"id":"action","label":"Detalhamento","kind":"action","actionType":"flow-detail","actionLabel":"Detalhar →"},
    ]
    result={"ok":True,"report":"sih-rd-fluxo","view":"summary","flatTable":True,"file":source.name,"path":relative,"year":2000+int(filename_match.group("yy")),"month":int(filename_match.group("mm")),"uf":uf,"state":PREDEFINED_UF_NAMES[uf],"municipality":municipality_name,"municipalityCode":municipality or None,"filters":filter_summary,"columns":columns,"metrics":metrics,"totals":[scaled_text(total_aihs,0),scaled_text(total_value,decimals)],"records":total_aihs,"rows":rows,"notes":[
        "Fonte: arquivo SIH/RD e definição oficial do TabWin. MUNIC_RES identifica o município informado como residência; MUNIC_MOV identifica o município de internação; os nomes dos hospitais vêm da relação oficial do CNES usada pelo SIH.",
        "A unidade de contagem é a AIH processada, não a pessoa. Uma pessoa pode ter mais de uma AIH, e internações prolongadas podem aparecer em competências sucessivas.",
        "O código de residência 000000 é descrito pela relação do DATASUS como 'ignorado ou exterior'; a base não permite separar esses dois casos.",
    ],"cachedAt":time.time()}
    cache_write(target,result,max_bytes=50_000_000,keep=30)
    if progress: progress(97,"Concluindo o fluxo de internações")
    return result

def predefined_sih_rd_rejections(payload: dict[str,Any], progress=None):
    """Summarize only RJ rejected AIHs, with optional ER criticality descriptions."""
    if progress: progress(2,"Conferindo as bases hospitalares")
    uf=str(payload.get("uf") or "PA").strip().upper()
    if uf not in PREDEFINED_UF_CODES:
        raise ValueError("Selecione uma unidade da Federação válida.")
    view=str(payload.get("predefinedView") or "summary")
    if view not in {"summary","detail"}:
        raise ValueError("A visualização solicitada não existe.")
    establishment=_report_code(str(payload.get("establishmentCode") or ""),7) if view=="detail" else ""
    if view=="detail" and (not establishment or len(re.sub(r"\D","",str(payload.get("establishmentCode") or "")))>7):
        raise ValueError("Selecione um estabelecimento válido para detalhar.")

    def source_component(path_key,dbf_key,expected_kind,optional=False):
        raw_path=payload.get(path_key)
        if not raw_path:
            if optional: return None
            raise ValueError(f"O arquivo {expected_kind} desta competência não foi informado.")
        source=safe_file(raw_path)
        relative=source.relative_to(UPLOADS).as_posix()
        system,kind,file_match=meta(source)
        if system!="SIH" or kind!=expected_kind:
            raise ValueError(f"Selecione um arquivo SIH/{expected_kind} válido.")
        if file_match.group("uf").upper()!=uf:
            raise ValueError("Os arquivos selecionados precisam pertencer à unidade da Federação escolhida.")
        year=2000+int(file_match.group("yy")); month=int(file_match.group("mm"))
        dbf=safe_dbf(str(payload.get(dbf_key) or converted_relative(relative)),relative)
        return {"source":source,"relative":relative,"dbf":dbf,"match":file_match,"year":year,"month":month,"kind":kind}

    rejected_path_key="rejectedPath" if payload.get("rejectedPath") else "path"
    rejected_dbf_key="rejectedDbfPath" if payload.get("rejectedDbfPath") else "dbfPath"
    rejected=source_component(rejected_path_key,rejected_dbf_key,"RJ")
    errors=source_component("errorPath","errorDbfPath","ER",optional=True)
    year,month=rejected["year"],rejected["month"]
    for component in (errors,):
        if component and (component["year"],component["month"])!=(year,month):
            raise ValueError("Os arquivos precisam ser da mesma competência.")

    municipality=str(payload.get("municipalityCode") or "").strip()
    if municipality and (not municipality.isdigit() or len(municipality)!=6 or municipality[:2]!=PREDEFINED_UF_CODES[uf]):
        raise ValueError("O município selecionado não pertence à unidade da Federação escolhida.")

    _,_,_,rejected_fields=dbf_layout(rejected["dbf"])
    error_fields={}
    if errors:
        _,_,_,error_fields=dbf_layout(errors["dbf"])

    _,definition=archive_def("SIH","RD")
    if definition is None:
        raise RuntimeError("A definição oficial de AIH reduzida não está disponível.")
    definition_options=_report_definition_options(definition)
    def exact_option(field,relation):
        return next((item for item in definition_options if item.get("field")==field and item.get("relation","" ).lower()==relation.lower()),None)
    cnes_option=next((item for item in definition_options if item.get("field")=="CNES" and PurePosixPath(item.get("relation","" )).name.lower()==f"tcnes{uf.lower()}.dbf"),None)
    procedure_option=exact_option("PROC_REA","DBF/TB_SIGTAW.DBF")
    if not cnes_option or not procedure_option:
        raise RuntimeError("A definição oficial não contém as referências de hospitais e procedimentos necessárias ao relatório.")

    selected_filter_codes={}
    selected_filter_names={}
    filter_options={}
    for spec in PREDEFINED_SIH_FILTER_SPECS:
        option=exact_option(spec["field"],spec["relation"])
        mapping=relation_mapping("SIH",option) if option else {}
        filter_options[spec["field"]]=mapping
        raw_values=payload.get(spec["field"]) or []
        if not raw_values: continue
        if not option:
            raise ValueError(f"O filtro {spec['label'].lower()} não existe na definição oficial desta base.")
        codes=_report_expand_filter_values(raw_values,spec,mapping)
        if codes:
            selected_filter_codes[spec["field"]]=codes
            labels=sorted({_report_label(cnv_label(mapping,code)) for code in codes if cnv_label(mapping,code)})
            selected_filter_names[spec["key"]]=labels

    rejected_required=["CNES","N_AIH","PROC_REA","VAL_TOT","VAL_SH","VAL_SP"]
    if municipality:
        rejected_required.append("MUNIC_MOV")
    rejected_required.extend(selected_filter_codes)
    missing_rejected=[field for field in rejected_required if field not in rejected_fields]
    if missing_rejected:
        raise ValueError("Esta competência não contém os campos necessários no SIH/RJ ("+", ".join(missing_rejected)+").")
    if errors and not {"CNES","AIH","CO_ERRO"}.issubset(error_fields):
        errors=None

    if progress: progress(7,"Carregando nomes oficiais de hospitais, procedimentos e críticas")
    cnes_labels=_report_relation_index(relation_mapping("SIH",cnes_option),7)
    procedure_labels=_report_relation_index(relation_mapping("SIH",procedure_option),10)
    error_labels={}
    if errors:
        _,error_definition=archive_def("SIH","ER")
        error_options=_report_definition_options(error_definition) if error_definition else []
        error_option=next((item for item in error_options if item.get("field")=="CO_ERRO" and item.get("relation","" ).lower().endswith("moterro.dbf")),None)
        error_labels=relation_mapping("SIH",error_option) if error_option else {}
        if not error_labels: errors=None
    def hospital_label(code):
        return _report_label(cnes_labels.get(code) or f"CNES {code}")

    sigtap_filter,sigtap_source=_sigtap_procedure_filter(payload,year,month,rejected_fields,"PROC_REA",rejected["dbf"])
    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIH.zip"
    identity={"report":"sih-rj-rejeicoes-v3","sources":[cache_file_identity(item["source"])|{"dbf":cache_file_identity(item["dbf"])} for item in (rejected,*([errors] if errors else []))],"definition":cache_file_identity(archive),"view":view,"establishment":establishment,"uf":uf,"municipality":municipality,"filters":selected_filter_codes,"sigtap":payload.get("sigtapFilters"),"sigtapVersion":sigtap_source.get("sha256") if sigtap_source else None,"sigtapAuditVersion":1}
    target=cache_target("predefined-reports",identity)
    cached=cache_read(target)
    if isinstance(cached,dict) and cached.get("ok") is True:
        if progress: progress(98,"Abrindo o relatório salvo neste computador")
        return cached

    for spec in PREDEFINED_SIH_FILTER_SPECS:
        if spec["key"] in selected_filter_names:
            selected_filter_names[spec["key"]]=[value[:120] for value in selected_filter_names[spec["key"]]]
    def filter_name_summary(names):
        if len(names)<=3: return ", ".join(names)
        return ", ".join(names[:2])+f" e mais {len(names)-2}"
    filter_summary=[{"label":spec["label"],"value":filter_name_summary(selected_filter_names[spec["key"]])} for spec in PREDEFINED_SIH_FILTER_SPECS if spec["key"] in selected_filter_names]
    municipality_name=str(payload.get("municipalityName") or "").strip()[:80] if municipality else "Todos os municípios"
    filters=[]
    if municipality: filters.append(("MUNIC_MOV",municipality))
    filters.extend(selected_filter_codes.items())
    if sigtap_filter: filters.append(sigtap_filter)
    dimension_fields=["COMPLEX","FINANC","FAEC_TP"]
    rejected_names=list(dict.fromkeys(["CNES","N_AIH","PROC_REA",*dimension_fields,"VAL_TOT","VAL_SH","VAL_SP",*selected_filter_codes]))
    rejected_names=[name for name in rejected_names if name in rejected_fields]
    rejected_pos={name:index for index,name in enumerate(rejected_names)}
    rejected_decimals={name:int(rejected_fields[name]["decimals"]) for name in ("VAL_TOT","VAL_SH","VAL_SP")}
    sums=defaultdict(lambda:[0,0,0,0])
    municipality_filter=municipality_name if municipality else PREDEFINED_UF_NAMES[uf]
    selected_names=[name for spec in PREDEFINED_SIH_FILTER_SPECS if spec["key"] in selected_filter_names for name in selected_filter_names[spec["key"]]]
    scope=" · ".join((municipality_filter,*selected_names[:3]))

    def detail_key(record,positions):
        procedure=_report_code(record[positions["PROC_REA"]],10)
        complexity=_report_code(record[positions["COMPLEX"]],2) if "COMPLEX" in positions else ""
        financing=_report_code(record[positions["FINANC"]],2) if "FINANC" in positions else ""
        faec_type=_report_code(record[positions["FAEC_TP"]],6) if "FAEC_TP" in positions else ""
        return (procedure,complexity,financing,faec_type)

    def report_progress(start,end,done,total,stage):
        if progress and total:
            percent=min(end,start+int((end-start)*done/total))
            progress(percent,f"{stage} · {done:,} de {total:,} · {scope}".replace(",","."))

    if progress: progress(12,"Contando AIHs rejeitadas e os valores associados")
    rejected_aihs={}
    seen_rejected=set()
    rejected_processed=[0]
    for _,record in iter_dbf_fields(rejected["dbf"],rejected_names,with_index=True,pre_filter=filters or None,processed_counter=rejected_processed,scan_callback=lambda done,total:report_progress(12,72,done,total,"Lendo AIHs rejeitadas") if progress else None):
        cnes=_report_code(record[rejected_pos["CNES"]],7)
        aih=str(record[rejected_pos["N_AIH"]] or "").strip()
        if not cnes or not aih or (view=="detail" and cnes!=establishment): continue
        rejected_key=(cnes,aih)
        if rejected_key in seen_rejected: continue
        seen_rejected.add(rejected_key)
        group_key=cnes if view=="summary" else detail_key(record,rejected_pos)
        rejected_aihs[rejected_key]=group_key
        values=sums[group_key]
        values[0]+=1
        values[1]+=scaled_integer(record[rejected_pos["VAL_TOT"]],rejected_decimals["VAL_TOT"])
        values[2]+=scaled_integer(record[rejected_pos["VAL_SH"]],rejected_decimals["VAL_SH"])
        values[3]+=scaled_integer(record[rejected_pos["VAL_SP"]],rejected_decimals["VAL_SP"])

    rejection_reason_counts=defaultdict(lambda:defaultdict(set))
    if errors and rejected_aihs and view=="detail":
        if progress: progress(75,"Associando cada AIH às críticas oficiais do processamento")
        error_processed=[0]
        for _,record in iter_dbf_fields(errors["dbf"],["CNES","AIH","CO_ERRO"],with_index=True,processed_counter=error_processed,scan_callback=lambda done,total:report_progress(75,93,done,total,"Lendo motivos da rejeição") if progress else None):
            key=(_report_code(record[0],7),str(record[1] or "").strip())
            group_key=rejected_aihs.get(key)
            code=str(record[2] or "").strip().upper()
            if group_key is None or not code: continue
            rejection_reason_counts[group_key][code].add(key)

    metrics=[
        {"id":"qtd_aih_rejeitada","label":"AIHs rejeitadas","decimals":0},
        {"id":"valor_rejeitado","label":"Valor total associado às AIHs rejeitadas","decimals":rejected_decimals["VAL_TOT"]},
        {"id":"valor_sh_rejeitado","label":"Serviços hospitalares rejeitados","decimals":rejected_decimals["VAL_SH"]},
        {"id":"valor_sp_rejeitado","label":"Serviços profissionais rejeitados","decimals":rejected_decimals["VAL_SP"]},
    ]
    totals=[sum(values[index] for values in sums.values()) for index in range(len(metrics))]
    complexity_labels=filter_options.get("COMPLEX",{})
    financing_labels=filter_options.get("FINANC",{})
    faec_labels=filter_options.get("FAEC_TP",{})
    def reason_items(group_key):
        items=[]
        for code,aih_keys in rejection_reason_counts.get(group_key,{}).items():
            label=_report_label(str(cnv_label(error_labels,code) or "").strip())
            items.append((-len(aih_keys),label.casefold(),code,label,len(aih_keys)))
        items.sort()
        return [f"{code} — {label} ({count:,} AIH{'s' if count!=1 else ''})".replace(",",".") for _,_,code,label,count in items]

    sortable_rows=[]
    for group_key,values in sums.items():
        if view=="summary":
            code=group_key
            label=hospital_label(code)
            dimension_values={}
        else:
            procedure,complexity,financing,faec_type=group_key
            code=procedure
            label=_report_label(procedure_labels.get(code) or "Procedimento principal sem descrição oficial") if code else "Procedimento principal não informado"
            reasons=reason_items(group_key)
            reason_text=" · ".join(reasons) if reasons else "Motivo não disponível no SIH/ER"
            dimension_values={
                "complexity":_report_label(cnv_label(complexity_labels,complexity)) if complexity else "Não informado",
                "financing":_report_label(cnv_label(financing_labels,financing)) if financing else "Não informado",
                "faecType":_report_label(cnv_label(faec_labels,faec_type)) if faec_type else "Não se aplica / não informado",
                "rejectionReason":reason_text,
            }
        row={"code":code,"label":label,"values":[scaled_text(values[index],metric["decimals"]) for index,metric in enumerate(metrics)],"records":values[0],**dimension_values}
        if view=="detail": row["rejectionReasonItems"]=reasons or ["Motivo não disponível no SIH/ER"]
        sortable_rows.append((-values[1],-values[0],label.casefold(),code,tuple(dimension_values.values()),row))
    sortable_rows.sort(key=lambda item:item[:5])
    rows=[item[-1] for item in sortable_rows]
    names=[item["source"].name for item in (rejected,*([errors] if errors else []))]
    result={
        "ok":True,"report":"sih-rj-rejeicoes","view":view,"file":" · ".join(names),"files":names,
        "path":rejected["relative"],"year":year,"month":month,"uf":uf,"state":PREDEFINED_UF_NAMES[uf],
        "municipality":municipality_name,"municipalityCode":municipality or None,"establishmentCode":establishment or None,
        "establishmentName":hospital_label(establishment) if establishment else None,"filters":filter_summary,
        "dimensionLabel":"Estabelecimento hospitalar" if view=="summary" else "Procedimento principal · SIGTAP",
        "detailDimensions":[{"id":"complexity","label":"Complexidade"},{"id":"financing","label":"Financiamento"},{"id":"faecType","label":"Subtipo FAEC"},{"id":"rejectionReason","label":"Motivo da rejeição"}],
        "metrics":metrics,"totals":[scaled_text(value,metric["decimals"]) for value,metric in zip(totals,metrics)],
        "records":sum(values[0] for values in sums.values()),"rows":rows,
        "notes":[
            "Este relatório usa somente o SIH/RJ, arquivo de AIHs rejeitadas. AIHs de continuidade podem aparecer em competências sucessivas; o total mensal não equivale necessariamente a internações únicas.",
            "O SIH/RJ informa os valores associados às próprias AIHs rejeitadas (VAL_TOT, VAL_SH e VAL_SP).",
            "Os motivos vêm dos códigos de crítica do SIH/ER, associados pelo CNES e número da AIH. Uma AIH pode ter mais de um motivo; por isso, a coluna mostra as críticas associadas sem duplicar a contagem ou os valores da AIH.",
            "A quantidade exibida ao lado de cada motivo corresponde a AIHs distintas com aquela crítica; como uma AIH pode ter várias críticas, essas frequências podem se sobrepor.",
            "O filtro de município usa MUNIC_MOV (município da internação), e os filtros adicionais são aplicados às AIHs rejeitadas.",
            *( ["O arquivo ou a referência oficial dos códigos SIH/ER não está disponível para esta competência; os valores de rejeição foram preservados, mas os motivos não puderam ser identificados."] if not errors else [] ),
        ],
    }
    _attach_sigtap_source(result,sigtap_source)
    if progress: progress(97,"Finalizando valores, totais e motivos oficiais")
    cache_write(target,result,max_bytes=100_000_000,keep=30)
    return result

def _read_cnes_establishment_cache(cnes: str, competence: str, allow_stale: bool=False):
    connection=None
    try:
        with CNES_ESTABLISHMENT_CACHE_LOCK:
            CNES_ESTABLISHMENT_CACHE.parent.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(str(CNES_ESTABLISHMENT_CACHE),timeout=8)
            connection.execute("CREATE TABLE IF NOT EXISTS establishment_classifications (cnes TEXT NOT NULL, competence TEXT NOT NULL, data_json TEXT NOT NULL, fetched_at REAL NOT NULL, PRIMARY KEY(cnes,competence))")
            connection.commit()
            row=connection.execute("SELECT data_json,fetched_at FROM establishment_classifications WHERE cnes=? AND competence=?",(cnes,competence)).fetchone()
        if not row: return None
        data=json.loads(row[0])
        if not isinstance(data,dict) or data.get("schemaVersion")!=2: return None
        age=time.time()-float(row[1])
        if age>=7*86400 and not allow_stale: return None
        data["cachedAt"]=float(row[1])
        if age>=7*86400: data["stale"]=True
        return data
    except (OSError,sqlite3.Error,ValueError,TypeError):
        return None
    finally:
        if connection is not None: connection.close()

def _write_cnes_establishment_cache(cnes: str, competence: str, data: dict[str,Any]):
    connection=None
    try:
        with CNES_ESTABLISHMENT_CACHE_LOCK:
            CNES_ESTABLISHMENT_CACHE.parent.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(str(CNES_ESTABLISHMENT_CACHE),timeout=8)
            connection.execute("CREATE TABLE IF NOT EXISTS establishment_classifications (cnes TEXT NOT NULL, competence TEXT NOT NULL, data_json TEXT NOT NULL, fetched_at REAL NOT NULL, PRIMARY KEY(cnes,competence))")
            data["schemaVersion"]=2
            connection.execute("INSERT OR REPLACE INTO establishment_classifications(cnes,competence,data_json,fetched_at) VALUES(?,?,?,?)",(cnes,competence,json.dumps(data,ensure_ascii=True,separators=(",",":")),time.time()))
            connection.commit()
    except (OSError,sqlite3.Error,ValueError,TypeError):
        pass
    finally:
        if connection is not None: connection.close()

def _cnes_open_data_json(path: str, params: dict[str,str] | None = None):
    query=urllib.parse.urlencode(params or {})
    url=f"https://{CNES_OPEN_DATA_HOST}{path}"+(f"?{query}" if query else "")
    request=urllib.request.Request(url,headers={"User-Agent":"SPPtab/1.0","Accept":"application/json"})
    try:
        with open_verified_https(request,CNES_OPEN_DATA_HOST,10) as response:
            raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024: return None,False
    except urllib.error.HTTPError as exc:
        if exc.code==404: return None,True
        return None,False
    except (OSError,TimeoutError,ValueError,urllib.error.URLError):
        return None,False
    try:
        data=json.loads(raw.decode("utf-8"))
        return (data if isinstance(data,dict) else None),True
    except (UnicodeDecodeError,ValueError,TypeError):
        return None,False

def _normalize_cnes_management(value: Any) -> str:
    raw=str(value or "").strip().upper()
    if raw in {"M","MUNICIPAL","MUNICIPAL PLENA","MUNICIPAL PLENO"}: return "MUNICIPAL"
    if raw in {"E","ESTADUAL","ESTADUAL PLENA","ESTADUAL PLENO"}: return "ESTADUAL"
    if raw in {"D","DUPLA","DUPLA GESTAO","GESTAO DUPLA"}: return "DUPLA"
    return "NAO_INFORMADA"

def _normalize_cnes_nature_group(value: Any, nature_code: str="") -> str:
    raw=repair_mojibake_text(str(value or "")).strip().upper()
    normalized=re.sub(r"[^A-Z0-9]+"," ",raw).strip()
    if "PUBLIC" in normalized or "ADMINISTRACAO PUBLICA" in normalized: return "PUBLICO"
    if "SEM FINS" in normalized or "SEM FIM" in normalized: return "SEM_FINS_LUCRATIVOS"
    if "PESSOA FISICA" in normalized or str(nature_code or "").startswith("4"): return "PESSOA_FISICA"
    if any(term in normalized for term in ("PRIVADO","PRIVADA","EMPRESARIAL")): return "PRIVADO"
    if normalized and normalized not in {"NAO INFORMADO","IGNORADO","N A"}: return "OUTROS"
    prefix=str(nature_code or "")[:1]
    return {"1":"PUBLICO","2":"PRIVADO","3":"SEM_FINS_LUCRATIVOS","4":"PESSOA_FISICA"}.get(prefix,"OUTROS" if prefix else "NAO_INFORMADA")

def _cnes_nature_code(value: Any) -> str:
    match=re.search(r"(?<!\d)(\d{4})(?!\d)",str(value or ""))
    return match.group(1) if match else ""

def _normalize_cnes_sus(value: Any) -> str:
    raw=repair_mojibake_text(str(value or "")).strip().upper()
    if raw in {"S","SIM","1","TRUE","YES"}: return "SIM"
    if raw in {"N","NAO","NÃO","0","FALSE","NO"}: return "NAO"
    return "NAO_INFORMADO"

def _cnes_establishment_classification(cnes: str, year: int, month: int, need_sus: bool=False, check_cache: bool=True):
    """Use the CNES open-data API only for facility fields absent from SIH/SP."""
    digits=re.sub(r"\D","",str(cnes or ""))
    if not re.fullmatch(r"\d{7}",digits): return None,False
    competence=f"{year:04d}{month:02d}"
    cached=_read_cnes_establishment_cache(digits,competence) if check_cache else None
    stale=_read_cnes_establishment_cache(digits,competence,allow_stale=True) if check_cache and cached is None else None
    if cached is not None and (not need_sus or cached.get("attendanceChecked")):
        return cached,True

    data=dict(cached or {})
    service_available=False
    if not data.get("competenceChecked"):
        monthly,ok=_cnes_open_data_json("/assistencia-a-saude/cnes-estabelecimentos",{"nu_comp":competence,"co_cnes":digits,"limit":"20","offset":"0"})
        service_available=service_available or ok
        rows=monthly.get("cnes_estabelecimentos",[]) if isinstance(monthly,dict) else []
        row=next((item for item in rows if isinstance(item,dict) and re.sub(r"\D","",str(item.get("co_cnes") or ""))==digits and str(item.get("nu_comp") or "")==competence),None)
        if row:
            nature_code=_cnes_nature_code(row.get("ds_natureza_juridica"))
            data.update({
                "management":_normalize_cnes_management(row.get("tp_gestao")),
                "natureGroup":_normalize_cnes_nature_group(row.get("no_grupo_nat_jur"),nature_code),
                "legalNature":nature_code,
                "source":"competence",
                "sourceCompetence":competence,
            })
        data["competenceChecked"]=bool(ok)

    # Current CNES records cannot silently supply historical classification.
    needs_current=need_sus
    if needs_current and not data.get("currentChecked"):
        current,ok=_cnes_open_data_json(f"/cnes/estabelecimentos/{digits}")
        service_available=service_available or ok
        if isinstance(current,dict) and str(current.get("codigo_cnes") or "").zfill(7)==digits:
            legal_code=_cnes_nature_code(current.get("descricao_natureza_juridica_estabelecimento"))
            data["currentLegalNature"] = legal_code
            if need_sus:
                attendance=current.get("estabelecimento_faz_atendimento_hospitalar_sus")
                if attendance is None: attendance=current.get("estabelecimento_possui_atendimento_hospitalar")
                data["hospitalSUS"]=_normalize_cnes_sus(attendance)
            data["currentUpdatedAt"]=_report_label(current.get("data_atualizacao") or "")[:20]
            if data.get("source")!="competence": data["source"]="current-attendance-only"
        data["currentChecked"]=bool(ok)
        if need_sus: data["attendanceChecked"]=bool(ok)

    if stale and stale.get("source")=="competence" and data.get("source")!="competence":
        return stale,service_available
    if stale and not service_available:
        return stale,False
    if data:
        if not data.get("management"): data["management"]="NAO_INFORMADA"
        if not data.get("natureGroup"): data["natureGroup"]="NAO_INFORMADA"
        if not data.get("legalNature"): data["legalNature"]=""
        if need_sus and not data.get("hospitalSUS"): data["hospitalSUS"]="NAO_INFORMADO"
        _write_cnes_establishment_cache(digits,competence,data)
        return data,service_available
    return None,service_available

def _cnes_establishment_classifications(cnes_codes: list[str], year: int, month: int, need_sus: bool=False, progress=None):
    codes=sorted({re.sub(r"\D","",str(code or "")) for code in cnes_codes if re.fullmatch(r"\d{7}",re.sub(r"\D","",str(code or "")))})
    competence=f"{year:04d}{month:02d}"
    result={}; missing=[]
    for code in codes:
        cached=_read_cnes_establishment_cache(code,competence)
        if cached is not None and (not need_sus or cached.get("attendanceChecked")):
            result[code]=cached
        else: missing.append(code)
    if not missing: return result,0,sum(1 for code in codes if not result.get(code,{}).get("source"))
    failures=0; completed=0
    if progress: progress(80,f"Consultando classificações cadastrais do CNES · {len(missing):,} estabelecimento(s)".replace(",","."))
    with ThreadPoolExecutor(max_workers=16,thread_name_prefix="cnes-estab") as executor:
        futures={executor.submit(_cnes_establishment_classification,code,year,month,need_sus,True):code for code in missing}
        for future in as_completed(futures):
            code=futures[future]
            try:
                data,available=future.result()
                if data is not None: result[code]=data
                if not available and not (data or {}).get("stale"): failures+=1
            except Exception:
                failures+=1
            completed+=1
            if progress and (completed%20==0 or completed==len(missing)):
                progress(min(88,80+int(8*completed/max(1,len(missing)))),f"Lendo o CNES · {completed:,} de {len(missing):,} estabelecimento(s)".replace(",","."))
    return result,failures,sum(1 for code in codes if not result.get(code,{}).get("source"))

CNES_PROFESSIONAL_SERVICE = "https://servicos.saude.gov.br/cnes/ProfissionalSaudeService/v1r0"
CNES_SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
CNES_PROFESSIONAL_NS = "http://servicos.saude.gov.br/cnes/v1r0/profissionalsaudeservice"
CNES_PROFESSIONAL_FILTER_NS = "http://servicos.saude.gov.br/wsdl/mensageria/v1r0/filtropesquisaprofissionalsaude"
CNES_CNS_NS = "http://servicos.saude.gov.br/schema/cadsus/v5r0/cns"
CNES_WSSE_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
CNES_LOOKUP_CACHE = UPLOADS/".cache"/"cnes-professional-names.sqlite3"
CNES_LOOKUP_CACHE_LOCK = threading.RLock()

def _read_cnes_professional_cache(cns_hash: str):
    connection=None
    try:
        with CNES_LOOKUP_CACHE_LOCK:
            CNES_LOOKUP_CACHE.parent.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(str(CNES_LOOKUP_CACHE),timeout=8)
            connection.execute("CREATE TABLE IF NOT EXISTS professional_names (cns_hash TEXT PRIMARY KEY, name TEXT NOT NULL, cbos_json TEXT NOT NULL, fetched_at REAL NOT NULL)")
            connection.commit()
            row=connection.execute("SELECT name, cbos_json, fetched_at FROM professional_names WHERE cns_hash=?",(cns_hash,)).fetchone()
        if not row or time.time()-float(row[2])>=7*86400: return None
        cbos=json.loads(row[1])
        return {"name":str(row[0] or ""),"cbos":cbos if isinstance(cbos,list) else []}
    except (OSError,sqlite3.Error,ValueError,TypeError):
        return None
    finally:
        if connection is not None: connection.close()

def _write_cnes_professional_cache(cns_hash: str, profile: dict[str,Any]):
    connection=None
    try:
        with CNES_LOOKUP_CACHE_LOCK:
            CNES_LOOKUP_CACHE.parent.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(str(CNES_LOOKUP_CACHE),timeout=8)
            connection.execute("CREATE TABLE IF NOT EXISTS professional_names (cns_hash TEXT PRIMARY KEY, name TEXT NOT NULL, cbos_json TEXT NOT NULL, fetched_at REAL NOT NULL)")
            connection.execute("INSERT OR REPLACE INTO professional_names(cns_hash,name,cbos_json,fetched_at) VALUES(?,?,?,?)",(cns_hash,str(profile.get("name") or ""),json.dumps(profile.get("cbos") or [],ensure_ascii=True,separators=(",",":")),time.time()))
            connection.commit()
    except (OSError,sqlite3.Error,ValueError,TypeError):
        pass
    finally:
        if connection is not None: connection.close()

def _xml_local_name(element):
    return element.tag.rsplit("}",1)[-1] if isinstance(element.tag,str) else ""

def _xml_first_text(element, name):
    for child in element.iter():
        if _xml_local_name(child)==name and (child.text or "").strip():
            return (child.text or "").strip()
    return ""

def cnes_professional_by_cns(cns: str, check_cache: bool = True):
    """Consult the official CNES SOAP service using CNS; keep only name/CBO data."""
    digits=re.sub(r"\D", "", str(cns or ""))
    if not re.fullmatch(r"\d{15}",digits):
        return None,False
    cns_hash=hashlib.sha256(digits.encode("ascii")).hexdigest()
    if check_cache:
        cached=_read_cnes_professional_cache(cns_hash)
        if cached is not None: return cached,True
    envelope=ET.Element(f"{{{CNES_SOAP_NS}}}Envelope")
    header=ET.SubElement(envelope,f"{{{CNES_SOAP_NS}}}Header")
    security=ET.SubElement(header,f"{{{CNES_WSSE_NS}}}Security",{f"{{{CNES_SOAP_NS}}}mustUnderstand":"true"})
    token=ET.SubElement(security,f"{{{CNES_WSSE_NS}}}UsernameToken")
    ET.SubElement(token,f"{{{CNES_WSSE_NS}}}Username").text="CNES.PUBLICO"
    password=ET.SubElement(token,f"{{{CNES_WSSE_NS}}}Password",{"Type":"http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText"})
    password.text="cnes#2015public"
    body=ET.SubElement(envelope,f"{{{CNES_SOAP_NS}}}Body")
    request=ET.SubElement(body,f"{{{CNES_PROFESSIONAL_NS}}}requestConsultarProfissionalSaude")
    filters=ET.SubElement(request,f"{{{CNES_PROFESSIONAL_FILTER_NS}}}FiltroPesquisaProfissionalSaude")
    cns_element=ET.SubElement(filters,f"{{{CNES_CNS_NS}}}CNS")
    ET.SubElement(cns_element,f"{{{CNES_CNS_NS}}}numeroCNS").text=digits
    data=ET.tostring(envelope,encoding="utf-8",xml_declaration=True)
    request_obj=urllib.request.Request(
        CNES_PROFESSIONAL_SERVICE,
        data=data,
        headers={"Content-Type":"application/soap+xml; charset=utf-8","Accept":"application/soap+xml, text/xml"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj,timeout=3.5) as response:
            raw=response.read(4*1024*1024+1)
            if len(raw)>4*1024*1024: return None,False
    except urllib.error.HTTPError as exc:
        try: raw=exc.read(4*1024*1024+1)
        except Exception: return None,False
        if len(raw)>4*1024*1024: return None,False
    except (OSError,TimeoutError,urllib.error.URLError):
        return None,False
    try:
        root=ET.fromstring(raw)
    except (ET.ParseError,ValueError):
        return None,False
    if any(_xml_local_name(node)=="Fault" for node in root.iter()):
        return None,False
    returned=[]
    for professional in (node for node in root.iter() if _xml_local_name(node)=="ProfissionalSaude"):
        returned_cns={re.sub(r"\D","",node.text or "") for node in professional.iter() if _xml_local_name(node)=="numeroCNS" and node.text}
        if returned_cns and digits not in returned_cns: continue
        name=_xml_first_text(professional,"Nome")
        cbos=[]
        for cbo in (node for node in professional.iter() if _xml_local_name(node)=="CBO"):
            code=_xml_first_text(cbo,"codigoCBO")
            description=_xml_first_text(cbo,"descricaoCBO")
            if code and re.fullmatch(r"\d{4,6}",re.sub(r"\D","",code)):
                cbos.append({"code":re.sub(r"\D","",code),"label":_report_label(description)[:160]})
        returned.append({"name":_report_label(name)[:255],"cbos":cbos})
    profile=next((item for item in returned if item.get("name")),{"name":"","cbos":[]})
    _write_cnes_professional_cache(cns_hash,profile)
    return profile,True

def _read_cnes_professional_cache_many(cns_hashes: list[str]):
    if not cns_hashes: return {}
    connection=None
    try:
        result={}
        with CNES_LOOKUP_CACHE_LOCK:
            CNES_LOOKUP_CACHE.parent.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(str(CNES_LOOKUP_CACHE),timeout=8)
            connection.execute("CREATE TABLE IF NOT EXISTS professional_names (cns_hash TEXT PRIMARY KEY, name TEXT NOT NULL, cbos_json TEXT NOT NULL, fetched_at REAL NOT NULL)")
            connection.commit()
            for start in range(0,len(cns_hashes),500):
                batch=cns_hashes[start:start+500]
                placeholders=",".join("?" for _ in batch)
                for cns_hash,name,cbos_json,fetched_at in connection.execute(f"SELECT cns_hash,name,cbos_json,fetched_at FROM professional_names WHERE cns_hash IN ({placeholders})",batch):
                    if time.time()-float(fetched_at)>=7*86400: continue
                    try: cbos=json.loads(cbos_json)
                    except (ValueError,TypeError): cbos=[]
                    result[cns_hash]={"name":str(name or ""),"cbos":cbos if isinstance(cbos,list) else []}
        return result
    except (OSError,sqlite3.Error,ValueError,TypeError):
        return {}
    finally:
        if connection is not None: connection.close()

def _report_date(value):
    raw=str(value or "").strip()
    digits=re.sub(r"\D","",raw)
    if len(digits)==8:
        if digits.startswith(("19","20")):
            return f"{digits[6:8]}/{digits[4:6]}/{digits[:4]}"
        return f"{digits[:2]}/{digits[2:4]}/{digits[4:8]}"
    if len(digits)==6 and digits.startswith(("19","20")):
        return f"{digits[4:6]}/{digits[2:4]}/{digits[:4]}"
    return raw[:20]

def predefined_sih_sp_professionals(payload: dict[str,Any], progress=None):
    """Monthly SIH/SP act table, enriched by CNS lookup in the official CNES service."""
    if progress: progress(2,"Conferindo o arquivo de serviços profissionais")
    source=safe_file(payload.get("path",""))
    relative=source.relative_to(UPLOADS).as_posix()
    system,kind,filename_match=meta(source)
    uf=str(payload.get("uf") or "PA").strip().upper()
    if uf not in PREDEFINED_UF_CODES:
        raise ValueError("Selecione uma unidade da Federação válida.")
    if system!="SIH" or kind!="SP" or filename_match.group("uf").upper()!=uf:
        raise ValueError(f"Selecione um arquivo de serviços profissionais (SP) de {uf}.")
    dbf=safe_dbf(str(payload.get("dbfPath") or converted_relative(relative)),relative)
    municipality=str(payload.get("municipalityCode") or "").strip()
    if municipality and (not municipality.isdigit() or len(municipality)!=6 or municipality[:2]!=PREDEFINED_UF_CODES[uf]):
        raise ValueError("O município selecionado não pertence à unidade da Federação escolhida.")

    total_records,_,_,fieldinfo=dbf_layout(dbf)
    _,definition=archive_def("SIH","SP")
    if definition is None:
        raise RuntimeError("A definição oficial dos serviços profissionais (SP) não está disponível.")
    definition_options=_report_definition_options(definition)
    def option_for(field, relation=None, basename=None):
        for item in definition_options:
            if item.get("field")!=field: continue
            if relation is not None and item.get("relation","").replace("\\","/").lower()!=relation.replace("\\","/").lower(): continue
            if basename is not None and PurePosixPath(item.get("relation","").replace("\\","/")).name.lower()!=basename.lower(): continue
            return item
        return None

    aliases={
        "aih":next((name for name in ("SP_NAIH","SP_AIH","N_AIH") if name in fieldinfo),None),
        "cns":next((name for name in ("SP_PF_DOC","SP_PF_CNS","SP_CNS") if name in fieldinfo),None),
        "admission":next((name for name in ("SP_DTINTER","DT_INTER") if name in fieldinfo),None),
        "discharge":next((name for name in ("SP_DTSAIDA","DT_SAIDA") if name in fieldinfo),None),
    }
    required={"CNES":"SP_CNES","procedimento":"SP_ATOPROF","CBO":"SP_PF_CBO","atos":"SP_QTD_ATO","valor":"SP_VALATO","tipo de valor":"IN_TP_VAL"}
    if municipality and "SP_M_HOSP" not in fieldinfo: required["município"]="SP_M_HOSP"
    missing=[label for label,name in required.items() if name not in fieldinfo]
    missing.extend(label for label,name in (("AIH",aliases["aih"]),("CNS do profissional",aliases["cns"])) if not name)
    if missing:
        raise ValueError("Esta competência não contém os campos necessários ao relatório: "+", ".join(missing))
    municipality_field="SP_M_HOSP"
    manager_codes={}
    manager_names={}
    manager_spec=PREDEFINED_SIH_SP_FILTER_SPECS[0]
    manager_option=option_for(manager_spec["field"],manager_spec["relation"])
    manager_mapping=relation_mapping("SIH",manager_option) if manager_option else {}
    raw_manager=payload.get(manager_spec["field"]) or []
    selected_filter_codes={}
    selected_filter_names={}
    if raw_manager:
        if not manager_option: raise ValueError("O filtro de gestor não consta na definição oficial desta base.")
        if manager_spec["field"] not in fieldinfo: raise ValueError("Esta competência não contém o campo de gestor necessário a esse filtro.")
        manager_codes[manager_spec["field"]]=_report_expand_filter_values(raw_manager,manager_spec,manager_mapping)
        manager_names[manager_spec["field"]]=sorted({_report_label(cnv_label(manager_mapping,code)) for code in manager_codes[manager_spec["field"]]})
        selected_filter_codes[manager_spec["field"]]=manager_codes[manager_spec["field"]]
        selected_filter_names[manager_spec["key"]]=manager_names[manager_spec["field"]]

    cbo_spec=PREDEFINED_SIH_SP_FILTER_SPECS[1]
    cbo_option=option_for(cbo_spec["field"],basename="CBO.DBF")
    cbo_mapping=relation_mapping("SIH",cbo_option) if cbo_option else {}
    raw_cbo=payload.get("professionalCboCode") or []
    if raw_cbo:
        if not cbo_option: raise ValueError("O filtro de CBO não consta na definição oficial desta base.")
        if cbo_spec["field"] not in fieldinfo: raise ValueError("Esta competência não contém o campo CBO necessário a esse filtro.")
        cbo_codes=_report_expand_filter_values(raw_cbo,cbo_spec,cbo_mapping)
        selected_filter_codes[cbo_spec["field"]]=cbo_codes
        selected_filter_names[cbo_spec["key"]]=sorted({_report_label(cnv_label(cbo_mapping,code)) for code in cbo_codes})

    _,rd_definition=archive_def("SIH","RD")
    rd_options=_report_definition_options(rd_definition) if rd_definition else []
    legal_nature_option=next((item for item in rd_options if item.get("field")=="NAT_JUR" and item.get("relation","").lower()=="cnv/natjur.cnv"),None)
    cnes_legal_nature_mapping=relation_mapping("SIH",legal_nature_option) if legal_nature_option else {}
    legal_nature_spec=next(spec for spec in PREDEFINED_SIH_FILTER_SPECS if spec["key"]=="legalNature")
    selected_cnes_filters={}
    selected_filter_names={**selected_filter_names}
    cnes_filter_allowed={
        "cnesManagementCode":{
            "MUNICIPAL":"Municipal","ESTADUAL":"Estadual","DUPLA":"Dupla","NAO_INFORMADA":"Não informada no CNES"
        },
        "cnesNatureGroupCode":{
            "PUBLICO":"Público","PRIVADO":"Privado","SEM_FINS_LUCRATIVOS":"Sem fins lucrativos","PESSOA_FISICA":"Pessoa física","OUTROS":"Outros tipos de natureza jurídica","NAO_INFORMADA":"Não informada no CNES"
        },
        "cnesHospitalSUSCode":{
            "SIM":"Sim · possui atendimento hospitalar SUS","NAO":"Não · sem atendimento hospitalar SUS","NAO_INFORMADO":"Sem informação no CNES atual"
        },
    }
    for payload_key,filter_spec in (("cnesManagementCode",PREDEFINED_SIH_SP_CNES_FILTERS[0]),("cnesNatureGroupCode",PREDEFINED_SIH_SP_CNES_FILTERS[1]),("cnesLegalNatureCode",PREDEFINED_SIH_SP_CNES_FILTERS[2]),("cnesHospitalSUSCode",PREDEFINED_SIH_SP_CNES_FILTERS[3])):
        raw_values=payload.get(payload_key) or []
        if isinstance(raw_values,(str,int,float)): raw_values=[raw_values]
        if not isinstance(raw_values,(list,tuple)) or len(raw_values)>500:
            raise ValueError(f"O filtro {filter_spec['label'].lower()} é inválido.")
        if not raw_values: continue
        if payload_key=="cnesLegalNatureCode":
            if not legal_nature_option: raise ValueError("A definição oficial de natureza jurídica do SIH não está disponível.")
            codes=_report_expand_filter_values(raw_values,legal_nature_spec,cnes_legal_nature_mapping)
            labels=sorted({_report_label(cnv_label(cnes_legal_nature_mapping,code)) for code in codes if cnv_label(cnes_legal_nature_mapping,code)})
        else:
            allowed=cnes_filter_allowed[payload_key]
            codes=sorted({str(value or "").strip().upper() for value in raw_values if str(value or "").strip()})
            invalid=[code for code in codes if code not in allowed]
            if invalid: raise ValueError(f"Uma categoria selecionada em {filter_spec['label'].lower()} não é válida.")
            labels=sorted({allowed[code] for code in codes})
        if codes:
            selected_cnes_filters[payload_key]=codes
            selected_filter_codes[payload_key]=codes
            selected_filter_names[filter_spec["key"]]=labels

    value_option=option_for("IN_TP_VAL","CNV/TP_VAL.CNV")
    value_mapping=relation_mapping("SIH",value_option) if value_option else {}
    value_labels=_report_exact_relation_index(value_mapping,1)
    professional_value_codes={code for code,label in value_labels.items() if re.search(r"\bSP\b",str(label),re.I) and not re.search(r"\bSH\b",str(label),re.I)}
    if not professional_value_codes:
        professional_value_codes={"2","4","6"}
    professional_value_codes={_report_code(code,1) for code in professional_value_codes}
    professional_value_codes.discard("")

    filter_summary=[]
    if manager_spec["key"] in selected_filter_names:
        names_for_filter=selected_filter_names[manager_spec["key"]]
        value=", ".join(names_for_filter[:3])+(f" e mais {len(names_for_filter)-3}" if len(names_for_filter)>3 else "")
        filter_summary.append({"label":manager_spec["label"],"value":value,"source":"SIH/SP"})
    names_for_filter=selected_filter_names.get(cbo_spec["key"],[])
    if names_for_filter:
        value=", ".join(names_for_filter[:3])+(f" e mais {len(names_for_filter)-3}" if len(names_for_filter)>3 else "")
        filter_summary.append({"label":cbo_spec["label"],"value":value,"source":"SIH/SP"})
    for filter_spec in PREDEFINED_SIH_SP_CNES_FILTERS:
        names_for_filter=selected_filter_names.get(filter_spec["key"],[])
        if not names_for_filter: continue
        value=", ".join(names_for_filter[:3])+(f" e mais {len(names_for_filter)-3}" if len(names_for_filter)>3 else "")
        source_label="CNES · competência do relatório" if filter_spec["source"]=="competence" else "CNES · cadastro atual"
        filter_summary.append({"label":filter_spec["label"],"value":value,"source":source_label})
    if progress: progress(6,"Carregando nomes oficiais de hospitais, procedimentos e ocupações")
    cnes_option=option_for("SP_CNES",basename=f"TCNES{uf}.DBF") or option_for("SP_CNES",basename="TCNESBR.DBF")
    procedure_option=option_for("SP_ATOPROF",basename="TB_SIGTAW.DBF")
    cbo_option=option_for("SP_PF_CBO",basename="CBO.DBF")
    if not cnes_option or not procedure_option or not cbo_option:
        raise RuntimeError("A definição oficial do SIH/SP não contém as referências necessárias para descrever hospitais, procedimentos e ocupações.")
    cnes_labels=_report_relation_index(relation_mapping("SIH",cnes_option),7)
    procedure_labels=_report_relation_index(relation_mapping("SIH",procedure_option),10)
    cbo_labels=_report_relation_index(relation_mapping("SIH",cbo_option),6)
    manager_labels=_report_relation_index(manager_mapping,manager_spec["width"])

    sigtap_filter,sigtap_source=_sigtap_procedure_filter(payload,2000+int(filename_match.group("yy")),int(filename_match.group("mm")),fieldinfo,"SP_ATOPROF",dbf)
    source_identity=cache_file_identity(source); dbf_identity=cache_file_identity(dbf)
    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIH.zip"
    identity={"report":"sih-sp-profissionais-v7","source":source_identity,"dbf":dbf_identity,"definition":cache_file_identity(archive),"uf":uf,"municipality":municipality,"filters":selected_filter_codes,"sigtap":payload.get("sigtapFilters"),"sigtapVersion":sigtap_source.get("sha256") if sigtap_source else None,"sigtapAuditVersion":1}
    target=cache_target("predefined-reports",identity)
    cached=cache_read(target)
    if isinstance(cached,dict) and cached.get("ok") is True and time.time()-float(cached.get("cachedAt",0) or 0)<7*86400:
        if progress: progress(98,"Abrindo o relatório salvo neste computador")
        return cached

    field_names=[aliases["aih"],aliases["cns"],"SP_CNES","SP_ATOPROF","SP_PF_CBO","SP_QTD_ATO","SP_VALATO","IN_TP_VAL",municipality_field,"SP_GESTOR",aliases["admission"],aliases["discharge"]]
    names=list(dict.fromkeys(name for name in field_names if name and name in fieldinfo))
    positions={name:index for index,name in enumerate(names)}
    decimals={name:int(fieldinfo[name]["decimals"]) for name in names}
    filters=[]
    if municipality: filters.append((municipality_field,municipality))
    if manager_spec["field"] in selected_filter_codes: filters.append((manager_spec["field"],selected_filter_codes[manager_spec["field"]]))
    if cbo_spec["field"] in selected_filter_codes: filters.append((cbo_spec["field"],selected_filter_codes[cbo_spec["field"]]))
    filters.append(("IN_TP_VAL",sorted(professional_value_codes)))
    if sigtap_filter: filters.append(sigtap_filter)
    grouped={}
    cns_frequency=defaultdict(int)
    processed=[0]
    municipality_name=str(payload.get("municipalityName") or "").strip()[:80] if municipality else "Todos os municípios"
    def scan_progress(done,_total):
        if progress and total_records:
            percent=min(78,10+int(68*done/total_records))
            progress(percent,f"Lendo serviços profissionais · {done:,} de {total_records:,} · {municipality_name if municipality else PREDEFINED_UF_NAMES[uf]}".replace(",","."))
    act_decimals=decimals["SP_QTD_ATO"]
    value_decimals=decimals["SP_VALATO"]
    for _,record in iter_dbf_fields(dbf,names,with_index=True,pre_filter=filters or None,processed_counter=processed,scan_callback=scan_progress if progress else None):
        aih=re.sub(r"\D","",str(record[positions[aliases["aih"]]] or ""))
        cns=re.sub(r"\D","",str(record[positions[aliases["cns"]]] or ""))
        cnes=_report_code(record[positions["SP_CNES"]],7)
        procedure=_report_code(record[positions["SP_ATOPROF"]],10)
        cbo=_report_code(record[positions["SP_PF_CBO"]],6)
        if not aih or not cnes: continue
        admission=_report_date(record[positions[aliases["admission"]]]) if aliases["admission"] and aliases["admission"] in positions else ""
        discharge=_report_date(record[positions[aliases["discharge"]]]) if aliases["discharge"] and aliases["discharge"] in positions else ""
        period=" – ".join(value for value in (admission,discharge) if value) or f"Competência {filename_match.group('mm')}/{2000+int(filename_match.group('yy'))}"
        key=(aih,admission,discharge,cnes,procedure,cns,cbo)
        item=grouped.get(key)
        acts=scaled_integer(record[positions["SP_QTD_ATO"]],act_decimals)
        amount=scaled_integer(record[positions["SP_VALATO"]],value_decimals)
        if item is None: grouped[key]=[acts,amount,1]
        else:
            item[0]=max(item[0],acts)
            item[1]+=amount
            item[2]+=1
        if len(cns)==15 and set(cns)!={"0"}: cns_frequency[cns]+=1

    cnes_filter_notes=[]
    if selected_cnes_filters:
        cnes_codes=sorted({key[3] for key in grouped})
        need_sus="cnesHospitalSUSCode" in selected_cnes_filters
        cnes_classifications,cnes_failures,cnes_unclassified=_cnes_establishment_classifications(
            cnes_codes,2000+int(filename_match.group("yy")),int(filename_match.group("mm")),need_sus,
            progress=lambda percent,message: progress(percent,message) if progress else None,
        )
        if cnes_failures:
            raise RuntimeError("Não foi possível consultar o CNES para todos os estabelecimentos. Tente novamente quando a conexão com os serviços públicos estiver estável.")
        if need_sus and any(not data.get("attendanceChecked") for data in cnes_classifications.values()):
            raise RuntimeError("O CNES não confirmou o atendimento hospitalar SUS de todos os estabelecimentos. Tente novamente quando a consulta cadastral estiver disponível.")
        selected_key_to_data={
            "cnesManagementCode":"management",
            "cnesNatureGroupCode":"natureGroup",
            "cnesLegalNatureCode":"legalNature",
            "cnesHospitalSUSCode":"hospitalSUS",
        }
        filtered_grouped={}
        for key,values in grouped.items():
            classification=cnes_classifications.get(key[3],{})
            if not classification.get("source"): continue
            matches=True
            for filter_key,codes in selected_cnes_filters.items():
                if str(classification.get(selected_key_to_data[filter_key]) or "") not in codes:
                    matches=False
                    break
            if matches: filtered_grouped[key]=values
        grouped=filtered_grouped
        source_competence_count=sum(1 for data in cnes_classifications.values() if data.get("source")=="competence")
        source_current_count=sum(1 for data in cnes_classifications.values() if data.get("source")=="current-attendance-only")
        cnes_filter_notes.append("Tipo de gestão e natureza jurídica do CNES usam apenas a competência do relatório. Quando o cadastro histórico não está disponível, esses campos ficam sem classificação.")
        stale_classifications=[data for data in cnes_classifications.values() if data.get("stale")]
        if stale_classifications:
            latest=max(float(data.get("cachedAt") or 0) for data in stale_classifications)
            cnes_filter_notes.append(f"O CNES não respondeu para {len(stale_classifications):,} cadastro(s); usada a última cópia válida da competência {filename_match.group('mm')}/{2000+int(filename_match.group('yy'))}, consultada em {time.strftime('%d/%m/%Y',time.localtime(latest))}.".replace(",","."))
        if need_sus:
            cnes_filter_notes.append("O filtro de atendimento hospitalar SUS consulta a situação atual do CNES e pode diferir da situação do estabelecimento na competência histórica.")
        if source_current_count:
            cnes_filter_notes.append(f"A situação atual de atendimento SUS foi consultada para {source_current_count:,} estabelecimento(s) sem classificação histórica disponível; ela não substitui gestão ou natureza jurídica da competência.".replace(",","."))
        if cnes_unclassified:
            cnes_filter_notes.append(f"{cnes_unclassified:,} estabelecimento(s) não tiveram classificação localizada no CNES e foram excluídos pelo filtro selecionado.".replace(",","."))
        allowed_cns={key[5] for key in grouped if key[5]}
        cns_frequency=defaultdict(int,{cns:count for cns,count in cns_frequency.items() if cns in allowed_cns})

    lookup_candidates=sorted(cns_frequency,key=lambda code:(-cns_frequency[code],code))
    max_lookup=3000
    if len(lookup_candidates)>max_lookup:
        lookup_candidates=lookup_candidates[:max_lookup]
        skipped_lookups=len(cns_frequency)-max_lookup
    else: skipped_lookups=0
    cns_hashes={cns:hashlib.sha256(cns.encode("ascii")).hexdigest() for cns in lookup_candidates}
    cached_by_hash=_read_cnes_professional_cache_many(list(cns_hashes.values()))
    cached_profiles={cns:cached_by_hash[cns_hash] for cns,cns_hash in cns_hashes.items() if cns_hash in cached_by_hash}
    missing_cns=[cns for cns in lookup_candidates if cns not in cached_profiles]

    lookup_error=False
    if missing_cns:
        professional_start=89 if selected_cnes_filters else 80
        if progress: progress(professional_start,f"Consultando o CNS de {len(missing_cns):,} profissional(is) no CNES".replace(",","."))
        first_profile,service_available=cnes_professional_by_cns(missing_cns[0],check_cache=False)
        if service_available:
            if first_profile is not None: cached_profiles[missing_cns[0]]=first_profile
            remaining=missing_cns[1:]
            completed=1
            with ThreadPoolExecutor(max_workers=12,thread_name_prefix="cnes-cns") as executor:
                futures={executor.submit(cnes_professional_by_cns,cns,False):cns for cns in remaining}
                for future in as_completed(futures):
                    cns=futures[future]
                    try:
                        profile,ok=future.result()
                        if ok and profile is not None: cached_profiles[cns]=profile
                        elif not ok: lookup_error=True
                    except Exception:
                        lookup_error=True
                    completed+=1
                    if progress and (completed%25==0 or completed==len(missing_cns)):
                        progress(min(96,professional_start+int((96-professional_start)*completed/max(1,len(missing_cns)))),f"Consultando profissionais no CNES · {completed:,} de {len(missing_cns):,}".replace(",","."))
        else:
            lookup_error=True
            if first_profile is not None: cached_profiles[missing_cns[0]]=first_profile

    rows=[]
    total_acts=0; total_value=0
    for key,values in grouped.items():
        aih,admission,discharge,cnes,procedure,cns,cbo=key
        profile=cached_profiles.get(cns,{})
        professional_name=_report_label(profile.get("name") or "") or ("CNS não informado" if not cns else "Nome não localizado no CNES")
        cnes_cbo=next((item for item in profile.get("cbos",[]) if _report_code(item.get("code"),6)==cbo),None) if cbo else None
        cbo_label=_report_label(cbo_labels.get(cbo) or (cnes_cbo.get("label") if cnes_cbo else "") or "Ocupação não informada")
        cnes_name=_report_label(cnes_labels.get(cnes) or f"CNES {cnes}")
        procedure_name=_report_label(procedure_labels.get(procedure) or "Procedimento sem descrição SIGTAP")
        period=" – ".join(value for value in (_report_date(admission),_report_date(discharge)) if value) or f"Competência {filename_match.group('mm')}/{2000+int(filename_match.group('yy'))}"
        total_acts+=values[0]; total_value+=values[1]
        rows.append({
            "aih":aih,"period":period,"establishment":cnes_name,"cnes":cnes,
            "procedureCode":procedure,"procedureName":procedure_name,
            "cns":cns,"professionalName":professional_name,"cbo":cbo,"cboName":cbo_label,
            "acts":scaled_text(values[0],act_decimals),"value":scaled_text(values[1],value_decimals),
            "records":values[2],
        })
    rows.sort(key=lambda row:(-scaled_integer(row["value"],value_decimals),row["establishment"].casefold(),row["aih"],row["procedureCode"],row["cns"]))
    total_aihs=len({row["aih"] for row in rows})
    notes=[
        "Fonte: arquivo detalhado SIH/SP da competência. Cada linha agrupa o mesmo AIH, período, hospital, procedimento, CNS e CBO.",
        "A consulta considera os componentes de valor profissional identificados na definição oficial do SIH (Valor SP e complementos SP). A quantidade de atos é contada uma vez por combinação para não repetir atos quando a base traz mais de um tipo de valor.",
        "O nome é consultado pelo CNS no serviço oficial do CNES. O cadastro é a situação disponível na consulta atual e pode diferir do vínculo existente na competência histórica; quando não localizado, a tabela mantém o CNS e o CBO do arquivo SIH/SP.",
    ]
    if lookup_error: notes.append("O CNES não respondeu nesta consulta. Os dados de produção foram carregados e os nomes serão consultados novamente quando o serviço estiver disponível.")
    notes.extend(cnes_filter_notes)
    if skipped_lookups: notes.append(f"Por segurança de tempo, o enriquecimento foi limitado aos {max_lookup:,} CNS mais frequentes nesta consulta; os demais continuam identificados pelo CNS.".replace(",","."))
    metrics=[{"id":"acts","label":"Atos","decimals":act_decimals},{"id":"value","label":"Valor do ato","decimals":value_decimals}]
    columns=[
        {"id":"aih","label":"AIH / período","field":"aih","primaryField":"aih","secondaryField":"period","type":"text","sortField":"aih"},
        {"id":"establishment","label":"Estabelecimento","field":"establishment","primaryField":"establishment","secondaryField":"cnes","secondaryPrefix":"CNES ","type":"text","sortField":"establishment"},
        {"id":"procedure","label":"Procedimento do ato","field":"procedureCode","primaryField":"procedureCode","secondaryField":"procedureName","type":"text","sortField":"procedureCode"},
        {"id":"professional","label":"Profissional executor · CNS","field":"professionalName","primaryField":"professionalName","secondaryField":"cns","secondaryPrefix":"CNS ","type":"text","sortField":"professionalName"},
        {"id":"cbo","label":"CBO do profissional","field":"cboName","primaryField":"cboName","secondaryField":"cbo","secondaryPrefix":"CBO ","type":"text","sortField":"cboName"},
        {"id":"acts","label":"Atos","field":"acts","type":"number","metricId":"acts","decimals":act_decimals},
        {"id":"value","label":"Valor do ato","field":"value","type":"currency","metricId":"value","decimals":value_decimals},
    ]
    result={
        "ok":True,"report":"sih-sp-profissionais","view":"summary","flatTable":True,
        "file":source.name,"path":relative,"year":2000+int(filename_match.group("yy")),"month":int(filename_match.group("mm")),
        "uf":uf,"state":PREDEFINED_UF_NAMES[uf],"municipality":municipality_name,"municipalityCode":municipality or None,
        "filters":filter_summary,"columns":columns,"metrics":metrics,
        "totals":[scaled_text(total_acts,act_decimals),scaled_text(total_value,value_decimals)],
        "records":sum(row["records"] for row in rows),"totalAIHs":total_aihs,"rows":rows,
        "notes":notes,"cachedAt":time.time(),"professionalLookups":len(cached_profiles),"professionalLookupCandidates":len(cns_frequency),
    }
    _attach_sigtap_source(result,sigtap_source)
    if progress: progress(97,"Finalizando a tabela de produção profissional")
    if not lookup_error: cache_write(target,result,max_bytes=100_000_000,keep=30)
    return result

CNES_LEITO_SERVICE = "https://servicos.saude.gov.br/cnes/LeitoService/v1r0"
CNES_LEITO_NS = "http://servicos.saude.gov.br/cnes/v1r0/leitoservice"
CNES_LEITO_DATA_NS = "http://servicos.saude.gov.br/schema/cnes/v1r0/leito"
CNES_CODE_NS = "http://servicos.saude.gov.br/schema/cnes/v1r0/codigocnes"
CNES_BED_CACHE = UPLOADS/".cache"/"cnes-bed-counts.sqlite3"
CNES_BED_CACHE_LOCK = threading.RLock()

def _read_cnes_bed_cache(cnes: str, allow_stale: bool=False):
    connection=None
    try:
        with CNES_BED_CACHE_LOCK:
            CNES_BED_CACHE.parent.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(str(CNES_BED_CACHE),timeout=8)
            connection.execute("CREATE TABLE IF NOT EXISTS bed_counts (cnes TEXT PRIMARY KEY, data_json TEXT NOT NULL, fetched_at REAL NOT NULL)")
            connection.commit()
            row=connection.execute("SELECT data_json,fetched_at FROM bed_counts WHERE cnes=?",(cnes,)).fetchone()
        if not row: return None
        data=json.loads(row[0])
        if not isinstance(data,dict): return None
        age=time.time()-float(row[1])
        if age>=7*86400 and not allow_stale: return None
        data["cachedAt"]=float(row[1])
        if age>=7*86400: data["stale"]=True
        return data
    except (OSError,sqlite3.Error,ValueError,TypeError):
        return None
    finally:
        if connection is not None: connection.close()

def _write_cnes_bed_cache(cnes: str, data: dict[str,Any]):
    connection=None
    try:
        with CNES_BED_CACHE_LOCK:
            CNES_BED_CACHE.parent.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(str(CNES_BED_CACHE),timeout=8)
            connection.execute("CREATE TABLE IF NOT EXISTS bed_counts (cnes TEXT PRIMARY KEY, data_json TEXT NOT NULL, fetched_at REAL NOT NULL)")
            connection.execute("INSERT OR REPLACE INTO bed_counts(cnes,data_json,fetched_at) VALUES(?,?,?)",(cnes,json.dumps(data,ensure_ascii=True,separators=(",",":")),time.time()))
            connection.commit()
    except (OSError,sqlite3.Error,ValueError,TypeError):
        pass
    finally:
        if connection is not None: connection.close()

def cnes_bed_counts_by_code(cnes: str, check_cache: bool=True):
    """Read SUS bed totals from the official CNES service and cache the public response."""
    digits=re.sub(r"\D","",str(cnes or ""))
    if not re.fullmatch(r"\d{7}",digits): return None,False
    if check_cache:
        cached=_read_cnes_bed_cache(digits)
        if cached is not None: return cached,True
    envelope=ET.Element(f"{{{CNES_SOAP_NS}}}Envelope")
    header=ET.SubElement(envelope,f"{{{CNES_SOAP_NS}}}Header")
    security=ET.SubElement(header,f"{{{CNES_WSSE_NS}}}Security",{f"{{{CNES_SOAP_NS}}}mustUnderstand":"true"})
    token=ET.SubElement(security,f"{{{CNES_WSSE_NS}}}UsernameToken")
    ET.SubElement(token,f"{{{CNES_WSSE_NS}}}Username").text="CNES.PUBLICO"
    password=ET.SubElement(token,f"{{{CNES_WSSE_NS}}}Password",{"Type":"http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText"})
    password.text="cnes#2015public"
    body=ET.SubElement(envelope,f"{{{CNES_SOAP_NS}}}Body")
    request=ET.SubElement(body,f"{{{CNES_LEITO_NS}}}requestConsultarLeitosCNES")
    code=ET.SubElement(request,f"{{{CNES_CODE_NS}}}CodigoCNES")
    ET.SubElement(code,f"{{{CNES_CODE_NS}}}codigo").text=digits
    request_obj=urllib.request.Request(
        CNES_LEITO_SERVICE,
        data=ET.tostring(envelope,encoding="utf-8",xml_declaration=True),
        headers={"Content-Type":"application/soap+xml; charset=utf-8","Accept":"application/soap+xml, text/xml"},
        method="POST",
    )
    try:
        with open_verified_https(request_obj,"servicos.saude.gov.br",7) as response:
            raw=response.read(4*1024*1024+1)
            if len(raw)>4*1024*1024: return None,False
    except (OSError,TimeoutError,ValueError,urllib.error.URLError):
        return None,False
    try:
        root=ET.fromstring(raw)
    except (ET.ParseError,ValueError):
        return None,False
    if any(_xml_local_name(node)=="Fault" for node in root.iter()): return None,False
    categories=[]
    updated=[]
    beds_sus=0
    uti_beds=0
    for item in (node for node in root.iter() if _xml_local_name(node)=="leito"):
        description=_report_label(_xml_first_text(item,"descricao"))[:160]
        raw_sus=_xml_first_text(item,"quantidadeLeitoSUS")
        try: amount=max(0,int(Decimal(raw_sus or "0")))
        except (InvalidOperation,ValueError,TypeError): amount=0
        if not description: continue
        beds_sus+=amount
        if "UTI" in description.upper(): uti_beds+=amount
        updated_value=_xml_first_text(item,"dataAtualizacao")
        if updated_value: updated.append(updated_value[:10])
        categories.append({"label":description,"bedsSus":amount})
    data={"bedsSus":beds_sus,"utiBeds":uti_beds,"updatedAt":max(updated) if updated else "","categories":categories}
    _write_cnes_bed_cache(digits,data)
    return data,True

def _sih_calendar_date(value):
    digits=re.sub(r"\D","",str(value or ""))
    try:
        if len(digits)==8 and digits.startswith(("19","20")):
            return date(int(digits[:4]),int(digits[4:6]),int(digits[6:8]))
        if len(digits)==8:
            return date(int(digits[4:8]),int(digits[2:4]),int(digits[:2]))
    except (ValueError,OverflowError):
        return None
    return None

def _sih_days_in_month(admission, discharge, year: int, month: int, fallback=0):
    first=date(year,month,1)
    next_month=date(year+1,1,1) if month==12 else date(year,month+1,1)
    start=_sih_calendar_date(admission)
    end=_sih_calendar_date(discharge)
    try: fallback_days=max(0,int(Decimal(str(fallback or 0))))
    except (InvalidOperation,ValueError,TypeError): fallback_days=0
    if start and end and end>=start:
        span=max(0,(min(end,next_month)-max(start,first)).days)
        if span==0 and start==end and first<=start<next_month:
            return min(1,max(1,fallback_days))
        return span
    return fallback_days

def _sih_record_number(record, positions, field, fieldinfo, default=0):
    if field not in positions: return default
    try:
        decimals=int(fieldinfo[field]["decimals"])
        raw=scaled_integer(record[positions[field]],decimals)
        return float(Decimal(raw).scaleb(-decimals))
    except (InvalidOperation,ValueError,TypeError,IndexError):
        return default

def _sih_bed_component(payload, path_key, dbf_key, expected_kind, uf, optional=False):
    raw_path=payload.get(path_key)
    if not raw_path:
        if optional: return None
        raise ValueError(f"O arquivo SIH/{expected_kind} desta competência não foi informado.")
    source=safe_file(raw_path)
    relative=source.relative_to(UPLOADS).as_posix()
    system,kind,match=meta(source)
    if system!="SIH" or kind!=expected_kind or match.group("uf").upper()!=uf:
        raise ValueError(f"Selecione um arquivo SIH/{expected_kind} válido para {uf}.")
    dbf=safe_dbf(str(payload.get(dbf_key) or converted_relative(relative)),relative)
    return {"source":source,"relative":relative,"dbf":dbf,"match":match,"kind":kind,"year":2000+int(match.group("yy")),"month":int(match.group("mm"))}

def predefined_sih_bed_occupancy(payload: dict[str,Any], progress=None):
    """Summarize monthly AIH bed-days, CNES SUS capacity and related SP services."""
    view=str(payload.get("predefinedView") or "summary")
    if view not in {"summary","detail","services"}:
        raise ValueError("A visualização solicitada não existe.")
    uf=str(payload.get("uf") or "PA").strip().upper()
    if uf not in PREDEFINED_UF_CODES:
        raise ValueError("Selecione uma unidade da Federação válida.")
    if progress: progress(2,"Conferindo as AIHs processadas e rejeitadas")

    if view=="services":
        return _predefined_sih_occupancy_services(payload,uf,progress)

    establishment=_report_code(str(payload.get("establishmentCode") or ""),7) if view=="detail" else ""
    if view=="detail" and (not establishment or len(re.sub(r"\D","",str(payload.get("establishmentCode") or "")))>7):
        raise ValueError("Selecione um estabelecimento válido para detalhar.")
    rd=_sih_bed_component(payload,"path","dbfPath","RD",uf)
    rj=_sih_bed_component(payload,"rejectedPath","rejectedDbfPath","RJ",uf)
    er=_sih_bed_component(payload,"errorPath","errorDbfPath","ER",uf,optional=True) if view=="detail" else None
    year,month=rd["year"],rd["month"]
    for item in (rj,er):
        if item and (item["year"],item["month"])!=(year,month):
            raise ValueError("RD, RJ e ER precisam pertencer à mesma competência.")
    _,_,_,rd_fields=dbf_layout(rd["dbf"])
    _,_,_,rj_fields=dbf_layout(rj["dbf"])
    er_fields=dbf_layout(er["dbf"])[3] if er else {}
    municipality=str(payload.get("municipalityCode") or "").strip()
    if municipality and (not municipality.isdigit() or len(municipality)!=6 or municipality[:2]!=PREDEFINED_UF_CODES[uf]):
        raise ValueError("O município selecionado não pertence à unidade da Federação escolhida.")

    _,definition=archive_def("SIH","RD")
    if definition is None: raise RuntimeError("A definição oficial de AIH reduzida não está disponível.")
    options=_report_definition_options(definition)
    def exact_option(field,relation):
        return next((item for item in options if item.get("field")==field and item.get("relation","").lower()==relation.lower()),None)
    selected_codes={}
    selected_names={}
    filter_mappings={}
    for spec in PREDEFINED_SIH_OCCUPANCY_FILTER_SPECS:
        option=exact_option(spec["field"],spec["relation"])
        mapping=relation_mapping("SIH",option) if option else {}
        filter_mappings[spec["field"]]=mapping
        raw_values=payload.get(spec["field"]) or []
        if raw_values:
            if not option: raise ValueError(f"O filtro {spec['label'].lower()} não existe na definição oficial.")
            codes=_report_expand_filter_values(raw_values,spec,mapping)
            if codes:
                selected_codes[spec["field"]]=codes
                selected_names[spec["key"]]=sorted({_report_label(cnv_label(mapping,code)) for code in codes if cnv_label(mapping,code)})

    required_common={"CNES","N_AIH","PROC_REA","ESPEC","DT_INTER","DT_SAIDA"}
    optional_common={"QT_DIARIAS","DIAS_PERM","UTI_MES_TO","UTI_INT_TO","COBRANCA"}
    for label,fields in (("SIH/RD",rd_fields),("SIH/RJ",rj_fields)):
        missing=sorted(required_common-fields.keys())
        if missing: raise ValueError(f"A base {label} não contém campos necessários: {', '.join(missing)}.")
        if municipality and "MUNIC_MOV" not in fields: raise ValueError(f"A base {label} não permite filtrar o município da internação.")
        missing_filters=[name for name in selected_codes if name not in fields]
        if missing_filters: raise ValueError(f"A base {label} não contém campos de filtro: {', '.join(missing_filters)}.")

    relation_options={
        "cnes":next((item for item in options if item.get("field")=="CNES" and PurePosixPath(item.get("relation","").replace("\\","/")).name.lower()==f"tcnes{uf.lower()}.dbf"),None),
        "procedure":exact_option("PROC_REA","DBF/TB_SIGTAW.DBF"),
        "specialty":exact_option("ESPEC","CNV/LEITOS.CNV"),
        "exit":exact_option("COBRANCA","CNV/SAIDAPERM.CNV"),
    }
    if not relation_options["cnes"] or not relation_options["procedure"] or not relation_options["specialty"]:
        raise RuntimeError("A definição oficial do SIH não contém as referências de estabelecimentos, procedimentos e leitos necessárias.")
    cnes_labels=_report_relation_index(relation_mapping("SIH",relation_options["cnes"]),7)
    procedure_labels=_report_relation_index(relation_mapping("SIH",relation_options["procedure"]),10)
    specialty_labels=relation_mapping("SIH",relation_options["specialty"])
    exit_labels=relation_mapping("SIH",relation_options["exit"]) if relation_options["exit"] else {}
    error_labels={}
    if er:
        if not {"CNES","AIH","CO_ERRO"}.issubset(er_fields): er=None
        else:
            _,error_definition=archive_def("SIH","ER")
            error_options=_report_definition_options(error_definition) if error_definition else []
            error_option=next((item for item in error_options if item.get("field")=="CO_ERRO" and item.get("relation","").replace("\\","/").lower().endswith("moterro.dbf")),None)
            error_labels=relation_mapping("SIH",error_option) if error_option else {}
            if not error_labels: er=None

    sigtap_filter,sigtap_source=_sigtap_procedure_filter(payload,year,month,rd_fields,"PROC_REA",rd["dbf"])
    if sigtap_source and "PROC_REA" in rj_fields:
        sigtap_source={**sigtap_source,"unmatchedOther":_sigtap_unmatched_codes(rj["dbf"],"PROC_REA",f"{year:04d}{month:02d}",sigtap_source["sha256"]),"unmatchedOtherSource":rj["dbf"].name}
    source_items=[rd,rj,*([er] if er else [])]
    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIH.zip"
    identity={"report":"sih-bed-occupancy-v3","sources":[cache_file_identity(item["source"])|{"dbf":cache_file_identity(item["dbf"])} for item in source_items],"definition":cache_file_identity(archive),"view":view,"establishment":establishment,"uf":uf,"municipality":municipality,"filters":selected_codes,"sigtap":payload.get("sigtapFilters"),"sigtapVersion":sigtap_source.get("sha256") if sigtap_source else None,"sigtapAuditVersion":1}
    target=cache_target("predefined-reports",identity)
    cached=cache_read(target)
    if isinstance(cached,dict) and cached.get("ok") is True and time.time()-float(cached.get("cachedAt",0) or 0)<7*86400:
        if progress: progress(98,"Abrindo o relatório salvo neste computador")
        return cached

    month_days=calendar.monthrange(year,month)[1]
    municipality_name=str(payload.get("municipalityName") or "").strip()[:80] if municipality else "Todos os municípios"
    filter_summary=[]
    for spec in PREDEFINED_SIH_OCCUPANCY_FILTER_SPECS:
        names=selected_names.get(spec["key"],[])
        if names: filter_summary.append({"label":spec["label"],"value":", ".join(names[:3])+(f" e mais {len(names)-3}" if len(names)>3 else "")})
    base_filters=[]
    if municipality: base_filters.append(("MUNIC_MOV",municipality))
    base_filters.extend(selected_codes.items())

    def scan_ais(component,fields,tag,start_pct,end_pct,day_bucket,want_detail=False):
        fields_to_read=["CNES","N_AIH","PROC_REA","ESPEC","DT_INTER","DT_SAIDA",*optional_common,*selected_codes]
        names=list(dict.fromkeys(name for name in fields_to_read if name in fields))
        positions={name:index for index,name in enumerate(names)}
        decimals={name:int(fields[name]["decimals"]) for name in names}
        required_filter=[]
        for name,value in base_filters:
            if name not in fields: raise ValueError(f"O campo {name} não existe na base {component['kind']}.")
            required_filter.append((name,value))
        if sigtap_filter: required_filter.append(sigtap_filter)
        count=dbf_layout(component["dbf"])[0]
        processed=[0]
        unique={}
        def scan_progress(done,total):
            if progress and count:
                pct=min(end_pct,start_pct+int((end_pct-start_pct)*done/count))
                progress(pct,f"Lendo AIHs {tag} · {done:,} de {count:,} · {municipality_name if municipality else PREDEFINED_UF_NAMES[uf]}".replace(",","."))
        for _,record in iter_dbf_fields(component["dbf"],names,with_index=True,pre_filter=required_filter or None,processed_counter=processed,scan_callback=scan_progress if progress else None):
            cnes=_report_code(record[positions["CNES"]],7)
            aih=re.sub(r"\D","",str(record[positions["N_AIH"]] or ""))
            if not cnes or not aih or (view=="detail" and cnes!=establishment): continue
            key=(cnes,aih)
            if key in unique: continue
            admission_raw=record[positions["DT_INTER"]]
            discharge_raw=record[positions["DT_SAIDA"]]
            fallback=_sih_record_number(record,positions,"QT_DIARIAS",fields) or _sih_record_number(record,positions,"DIAS_PERM",fields)
            stay_days=_sih_days_in_month(admission_raw,discharge_raw,year,month,fallback)
            permanence_days=_sih_record_number(record,positions,"DIAS_PERM",fields) or stay_days
            procedure=_report_code(record[positions["PROC_REA"]],10)
            # ESPEC is stored as a one-digit numeric field in some SIH DBFs,
            # but the official LEITOS.CNV relation uses two-digit codes (02,
            # 03, ...). Pad before looking up the official description.
            specialty=_report_code(record[positions["ESPEC"]],2)
            uti_days=_sih_record_number(record,positions,"UTI_MES_TO",fields)
            uci_days=_sih_record_number(record,positions,"UTI_INT_TO",fields)
            exit_code=str(record[positions["COBRANCA"]] or "").strip() if "COBRANCA" in positions else ""
            item={"cnes":cnes,"aih":aih,"procedureCode":procedure,
                  "procedureName":_report_label(procedure_labels.get(procedure) or "Procedimento sem descrição SIGTAP"),
                  "specialtyCode":specialty,"specialty":_report_label(cnv_label(specialty_labels,specialty) or "Especialidade não informada"),
                  "admission":_report_date(admission_raw),"discharge":_report_date(discharge_raw),
                  "stayDays":stay_days,"dailyCount":stay_days,"permanenceDays":permanence_days,"utiDays":uti_days,"uciDays":uci_days,
                  "exitCode":exit_code,"occurrence":_report_label(cnv_label(exit_labels,exit_code) or "") if exit_code else "",
                  "rawAdmission":str(admission_raw or ""),"rawDischarge":str(discharge_raw or "")}
            unique[key]=item
            totals=day_bucket[cnes]
            totals["days"]+=stay_days
            totals["utiDays"]+=uti_days
            totals["uciDays"]+=uci_days
            totals["aihSet"].add(aih)
            totals["specialties"][specialty]+=stay_days
            if want_detail: totals["details"].append(item)
        return unique

    if progress: progress(9,"Calculando diárias e internações por estabelecimento")
    accepted=defaultdict(lambda:{"days":0,"utiDays":0,"uciDays":0,"aihSet":set(),"specialties":defaultdict(float),"details":[]})
    rejected=defaultdict(lambda:{"days":0,"utiDays":0,"uciDays":0,"aihSet":set(),"specialties":defaultdict(float),"details":[]})
    accepted_items=scan_ais(rd,rd_fields,"processadas",10,52,accepted,view=="detail")
    rejected_items=scan_ais(rj,rj_fields,"rejeitadas",53,72,rejected,view=="detail")
    errors_by_aih=defaultdict(set)
    if er and view=="detail" and rejected_items:
        if progress: progress(75,"Associando críticas de processamento às AIHs rejeitadas")
        error_count=dbf_layout(er["dbf"])[0]
        error_processed=[0]
        def error_progress(done,total):
            if progress and error_count:
                progress(min(85,75+int(10*done/error_count)),f"Lendo ocorrências · {done:,} de {error_count:,}".replace(",","."))
        for _,record in iter_dbf_fields(er["dbf"],["CNES","AIH","CO_ERRO"],with_index=True,processed_counter=error_processed,scan_callback=error_progress if progress else None):
            key=(_report_code(record[0],7),re.sub(r"\D","",str(record[1] or "")))
            if key in rejected_items:
                code=str(record[2] or "").strip().upper()
                if code: errors_by_aih[key].add(code)

    codes=sorted(set(accepted)|set(rejected))
    beds_by_cnes={}
    lookup_errors=0
    missing_beds=[]
    if view=="summary":
        for code in codes:
            cached_beds=_read_cnes_bed_cache(code)
            if cached_beds is not None: beds_by_cnes[code]=cached_beds
            else: missing_beds.append(code)
    if missing_beds:
        if progress: progress(86,f"Consultando a quantidade de leitos SUS no CNES · 0 de {len(missing_beds)}")
        completed=0
        with ThreadPoolExecutor(max_workers=min(12,max(1,len(missing_beds))),thread_name_prefix="cnes-leitos") as executor:
            futures={executor.submit(cnes_bed_counts_by_code,code,False):code for code in missing_beds}
            for future in as_completed(futures):
                code=futures[future]
                try:
                    value,ok=future.result()
                    if ok and value is not None: beds_by_cnes[code]=value
                    else:
                        stale=_read_cnes_bed_cache(code,allow_stale=True)
                        if stale is not None: beds_by_cnes[code]=stale
                        else: lookup_errors+=1
                except Exception:
                    stale=_read_cnes_bed_cache(code,allow_stale=True)
                    if stale is not None: beds_by_cnes[code]=stale
                    else: lookup_errors+=1
                completed+=1
                if progress and (completed%5==0 or completed==len(missing_beds)):
                    progress(min(96,86+int(10*completed/max(1,len(missing_beds)))),f"Consultando leitos SUS no CNES · {completed} de {len(missing_beds)}")

    details_by_cnes=defaultdict(list)
    if view=="detail":
        for key,item in accepted_items.items():
            item["status"]="Processada"
            item["rejectionReasonItems"]=[]
            item["occurrence"]=item.get("occurrence") or "—"
            item["rejectionReason"]=item["occurrence"]
            details_by_cnes[key[0]].append(item)
        for key,item in rejected_items.items():
            codes_for_ai=sorted(errors_by_aih.get(key,set()))
            reasons=[f"{code} — {_report_label(cnv_label(error_labels,code) or 'Crítica sem descrição oficial')}" for code in codes_for_ai]
            item["status"]="Rejeitada"
            item["rejectionReasonItems"]=reasons or ["Motivo não disponível no SIH/ER"]
            item["occurrence"]="; ".join(reasons) if reasons else "Motivo não disponível no SIH/ER"
            item["rejectionReason"]=item["occurrence"]
            details_by_cnes[key[0]].append(item)

    def hospital_label(code): return _report_label(cnes_labels.get(code) or f"CNES {code}")
    rows=[]
    if view=="summary":
        for code in codes:
            actual=accepted[code]
            denied=rejected[code]
            beds=beds_by_cnes.get(code)
            beds_value=int(beds.get("bedsSus",0)) if beds else None
            uti_value=int(beds.get("utiBeds",0)) if beds else None
            avg=actual["days"]/month_days
            occupancy=avg/beds_value*100 if beds_value is not None and beds_value>0 else None
            potential_balance=beds_value-(actual["days"]+denied["days"])/month_days if beds_value is not None else None
            aih_count=len(actual["aihSet"])
            rejected_count=len(denied["aihSet"])
            rejection_rate=rejected_count/(aih_count+rejected_count)*100 if aih_count+rejected_count else 0
            specialty_code=max(actual["specialties"],key=actual["specialties"].get,default="")
            specialty_name=_report_label(cnv_label(specialty_labels,specialty_code) or "Não informada") if specialty_code else "Não informada"
            if beds is None: status="Leitos não informados no CNES"
            elif beds_value==0: status="Sem leitos SUS cadastrados"
            elif occupancy is None: status="Ocupação não calculável"
            elif occupancy>100: status="Acima da capacidade SUS"
            elif occupancy>=85: status="Alta ocupação registrada"
            elif occupancy>=60: status="Ocupação intermediária"
            else: status="Ocupação registrada menor"
            rows.append({"code":code,"label":hospital_label(code),"bedsSus":beds_value,"utiBeds":uti_value,
                "aihCount":aih_count,"dailyCount":actual["days"],"averageDaily":round(avg,1),"occupancyRate":round(occupancy,1) if occupancy is not None else None,
                "mainSpecialty":specialty_name,"mainSpecialtyDays":actual["specialties"].get(specialty_code,0),
                "potentialBalance":round(potential_balance,1) if potential_balance is not None else None,"status":status,
                "rejectionRate":round(rejection_rate,1),"rejectedCount":rejected_count,"rejectedDays":denied["days"]})
        rows.sort(key=lambda row:(-(row["occupancyRate"] if row["occupancyRate"] is not None else -1),-row["dailyCount"],row["label"].casefold(),row["code"]))
        known_bed_rows=[row for row in rows if row["bedsSus"] is not None]
        total_beds=sum(row["bedsSus"] or 0 for row in known_bed_rows)
        total_actual=sum(row["dailyCount"] for row in rows)
        total_rejected=sum(row["rejectedCount"] for row in rows)
        total_aih=sum(row["aihCount"] for row in rows)
        known_actual=sum(row["dailyCount"] for row in known_bed_rows)
        overall_occupancy=known_actual/month_days/total_beds*100 if total_beds and len(known_bed_rows)==len(rows) else None
        occupancy_kpi={"value":round(overall_occupancy,1),"decimals":1,"suffix":"%"} if overall_occupancy is not None else {"text":"—"}
        kpis=[{"label":"Estabelecimentos", "value":{"value":len(rows)}},{"label":"AIHs processadas", "value":{"value":total_aih}},{"label":"Diárias SIH", "value":{"value":total_actual}},{"label":"Ocupação média", "value":occupancy_kpi}]
        columns=[
            {"id":"provider","label":"Prestador","kind":"primary","field":"label","primaryField":"label","secondaryField":"code","secondaryPrefix":"CNES ","filterFields":["label","code"],"sortField":"label","type":"text"},
            {"id":"beds","label":"Leitos SUS","field":"bedsSus","filterFields":["bedsSus","utiBeds"],"type":"number","decimals":0,"totalField":"bedsSus","secondaryField":"utiBeds","secondaryPrefix":"UTI "},
            {"id":"aihs","label":"AIHs","field":"aihCount","type":"number","decimals":0,"totalField":"aihCount"},
            {"id":"daily","label":"Diárias SIH","field":"dailyCount","type":"number","decimals":0,"totalField":"dailyCount"},
            {"id":"average","label":"Média diária","field":"averageDaily","type":"number","decimals":1,"totalField":"averageDaily"},
            {"id":"occupancy","label":"Ocupação registrada","field":"occupancyRate","type":"percent","decimals":1,"totalField":"occupancyRate"},
            {"id":"specialty","label":"Tipo de leito com mais diárias","field":"mainSpecialty","type":"text","sortField":"mainSpecialty"},
            {"id":"balance","label":"Saldo potencial","field":"potentialBalance","type":"number","decimals":1,"totalField":"potentialBalance"},
            {"id":"status","label":"Situação","field":"status","type":"text","sortField":"status"},
            {"id":"rejectionRate","label":"Rejeição (%)","field":"rejectionRate","type":"percent","decimals":1,"totalField":"rejectionRate"},
            {"id":"rejected","label":"AIHs rejeitadas","field":"rejectedCount","type":"number","decimals":0,"totalField":"rejectedCount"},
            {"id":"detail","label":"Detalhar","kind":"action","actionType":"detail"},
        ]
        notes=[
            f"As diárias do SIH são calculadas pelo intervalo entre entrada e saída, limitadas aos {month_days} dias da competência. Quando as datas não estão válidas, o relatório usa QT_DIARIAS ou DIAS_PERM.",
            "Ocupação registrada = diárias das AIHs processadas ÷ dias da competência ÷ leitos SUS do CNES. A consulta de leitos usa os dados atuais retornados pelo CNES, e não uma fotografia histórica da competência.",
            "Saldo potencial = leitos SUS menos a média diária processada e a média diária de permanência informada nas AIHs rejeitadas. Rejeições são uma possibilidade estimada, não uma internação confirmada.",
            "O tipo de leito em destaque é a categoria ESPEC da definição oficial SIH/TabWin com mais diárias processadas. UTI e UCI são campos separados no SIH; as AIHs abertas mostram as respectivas diárias.",
            "A taxa de rejeição é calculada como AIHs no RJ ÷ (AIHs no RD + AIHs no RJ). As faixas de situação são referências visuais do TabulaSUS, não uma classificação oficial do CNES/SIH.",
            *( [f"A última atualização de leitos informada pelo CNES nesta consulta é {max((str(value.get('updatedAt') or '') for value in beds_by_cnes.values()),default='')}." ] if any(value.get("updatedAt") for value in beds_by_cnes.values()) else [] ),
            *([f"O CNES não respondeu para {lookup_errors} estabelecimento(s); a ocupação e o saldo desses locais ficam sem cálculo até uma próxima consulta."] if lookup_errors else []),
            *([f"O CNES está indisponível para {sum(1 for item in beds_by_cnes.values() if item.get('stale'))} estabelecimento(s); seus leitos usam a última cópia válida, consultada em {time.strftime('%d/%m/%Y',time.localtime(max(float(item.get('cachedAt') or 0) for item in beds_by_cnes.values() if item.get('stale'))))}."] if any(item.get('stale') for item in beds_by_cnes.values()) else []),
        ]
    else:
        rows=[]
        for item in details_by_cnes.get(establishment,[]):
            row={**item,"label":item["aih"],"code":item["aih"],"period":f"{item['admission'] or 'Entrada não informada'} – {item['discharge'] or 'saída não informada'}"}
            rows.append(row)
        rows.sort(key=lambda row:(row["admission"] or "",row["aih"],row["status"]))
        processed_count=sum(1 for row in rows if row["status"]=="Processada")
        rejected_count=sum(1 for row in rows if row["status"]=="Rejeitada")
        day_total=sum(row["stayDays"] for row in rows if row["status"]=="Processada")
        kpis=[{"label":"AIHs nesta unidade","value":{"value":len(rows)}},{"label":"Processadas","value":{"value":processed_count}},{"label":"Rejeitadas","value":{"value":rejected_count}},{"label":"Diárias no mês","value":{"value":day_total}}]
        columns=[
            {"id":"aih","label":"AIH","kind":"primary","field":"aih","primaryField":"aih","secondaryField":"period","filterFields":["aih","period"],"sortField":"aih","type":"text"},
            {"id":"status","label":"Situação","field":"status","type":"text","sortField":"status"},
            {"id":"entry","label":"Entrada","field":"admission","type":"text","sortField":"rawAdmission"},
            {"id":"exit","label":"Saída","field":"discharge","type":"text","sortField":"rawDischarge"},
            {"id":"specialty","label":"Tipo de leito","field":"specialty","type":"text","sortField":"specialty"},
            {"id":"procedure","label":"Procedimento SIGTAP","field":"procedureName","primaryField":"procedureName","secondaryField":"procedureCode","sortField":"procedureName","type":"text"},
            {"id":"permanence","label":"Permanência","field":"permanenceDays","type":"number","decimals":0,"totalField":"permanenceDays"},
            {"id":"stayDays","label":"Diárias no mês","field":"stayDays","type":"number","decimals":0,"totalField":"stayDays"},
            {"id":"uti","label":"Diárias UTI","field":"utiDays","type":"number","decimals":0,"totalField":"utiDays"},
            {"id":"uci","label":"Diárias UCI","field":"uciDays","type":"number","decimals":0,"totalField":"uciDays"},
            {"id":"occurrence","label":"Ocorrências","field":"rejectionReason","type":"text","sortField":"occurrence","filterFields":["occurrence"]},
            {"id":"services","label":"Serviços profissionais","kind":"action","actionType":"services","actionLabel":"Serviços →"},
        ]
        notes=[
            "Cada linha representa uma AIH processada ou rejeitada associada ao estabelecimento selecionado. O botão Serviços consulta o SIH/SP para a mesma AIH.",
            "O intervalo de permanência é contado dentro da competência selecionada. As AIHs rejeitadas continuam identificadas como rejeitadas; sua permanência não é somada às diárias registradas.",
            *(["As críticas foram relacionadas pelo CNES e número da AIH ao arquivo SIH/ER. Quando o ER não está disponível, os motivos aparecem como não disponíveis."] if not er else []),
        ]
    bed_reference_date=max((str(value.get("updatedAt") or "") for value in beds_by_cnes.values()),default="")
    result={"ok":True,"report":"sih-rd-ocupacao","view":view,"file":" · ".join(item["source"].name for item in source_items),"files":[item["source"].name for item in source_items],"path":rd["relative"],"year":year,"month":month,"daysInMonth":month_days,"bedReferenceDate":bed_reference_date,"uf":uf,"state":PREDEFINED_UF_NAMES[uf],"municipality":municipality_name,"municipalityCode":municipality or None,"establishmentCode":establishment or None,"establishmentName":hospital_label(establishment) if establishment else None,"filters":filter_summary,"columns":columns,"metrics":[],"kpis":kpis,"rows":rows,"records":len(rows),"notes":notes,"cachedAt":time.time()}
    _attach_sigtap_source(result,sigtap_source)
    if progress: progress(97,"Finalizando totais, nomes oficiais e ocupação")
    cache_write(target,result,max_bytes=100_000_000,keep=30)
    return result

def _predefined_sih_occupancy_services(payload: dict[str,Any], uf: str, progress=None):
    if progress: progress(4,"Conferindo os serviços profissionais desta AIH")
    establishment=_report_code(str(payload.get("establishmentCode") or ""),7)
    aih=re.sub(r"\D","",str(payload.get("aih") or ""))
    if not establishment or len(re.sub(r"\D","",str(payload.get("establishmentCode") or "")))>7 or not aih or len(aih)>13:
        raise ValueError("A unidade e a AIH precisam estar identificadas para consultar os serviços profissionais.")
    sp=_sih_bed_component(payload,"professionalPath" if payload.get("professionalPath") else "path","professionalDbfPath" if payload.get("professionalDbfPath") else "dbfPath","SP",uf)
    year,month=sp["year"],sp["month"]
    count,_,_,fieldinfo=dbf_layout(sp["dbf"])
    _,definition=archive_def("SIH","SP")
    if definition is None: raise RuntimeError("A definição oficial dos serviços profissionais (SP) não está disponível.")
    options=_report_definition_options(definition)
    def option_for(field,basename=None):
        return next((item for item in options if item.get("field")==field and (basename is None or PurePosixPath(item.get("relation","").replace("\\","/")).name.lower()==basename.lower())),None)
    aliases={"aih":next((name for name in ("SP_NAIH","SP_AIH","N_AIH") if name in fieldinfo),None),"cns":next((name for name in ("SP_PF_DOC","SP_PF_CNS","SP_CNS") if name in fieldinfo),None),"admission":next((name for name in ("SP_DTINTER","DT_INTER") if name in fieldinfo),None),"discharge":next((name for name in ("SP_DTSAIDA","DT_SAIDA") if name in fieldinfo),None)}
    required={"SP_CNES":"SP_CNES","procedimento":"SP_ATOPROF","CBO":"SP_PF_CBO","quantidade":"SP_QTD_ATO","valor":"SP_VALATO","tipo de valor":"IN_TP_VAL"}
    missing=[label for label,field in required.items() if field not in fieldinfo]
    missing.extend(label for label,field in (("AIH",aliases["aih"]),("CNS do profissional",aliases["cns"])) if not field)
    if missing: raise ValueError("Esta competência não contém os campos necessários ao detalhamento profissional: "+", ".join(missing)+".")
    procedure_option=option_for("SP_ATOPROF","TB_SIGTAW.DBF")
    cbo_option=option_for("SP_PF_CBO","CBO.DBF")
    cnes_option=option_for("SP_CNES",f"TCNES{uf}.DBF") or option_for("SP_CNES","TCNESBR.DBF")
    value_option=option_for("IN_TP_VAL","TP_VAL.CNV")
    if not procedure_option or not cbo_option or not cnes_option: raise RuntimeError("A definição oficial do SIH/SP não contém as referências de hospitais, procedimentos e ocupações necessárias.")
    procedure_labels=_report_relation_index(relation_mapping("SIH",procedure_option),10)
    cbo_labels=_report_relation_index(relation_mapping("SIH",cbo_option),6)
    cnes_labels=_report_relation_index(relation_mapping("SIH",cnes_option),7)
    value_mapping=relation_mapping("SIH",value_option) if value_option else {}
    value_labels=_report_exact_relation_index(value_mapping,1)
    professional_codes={code for code,label in value_labels.items() if re.search(r"\bSP\b",str(label),re.I) and not re.search(r"\bSH\b",str(label),re.I)} or {"2","4","6"}
    professional_codes={_report_code(code,1) for code in professional_codes}
    professional_codes.discard("")
    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIH.zip"
    result_cache=cache_target("predefined-reports",{"report":"sih-bed-services-v2","source":cache_file_identity(sp["source"]),"dbf":cache_file_identity(sp["dbf"]),"definition":cache_file_identity(archive),"uf":uf,"cnes":establishment,"aih":aih})
    cached_result=cache_read(result_cache)
    if isinstance(cached_result,dict) and cached_result.get("ok") is True and time.time()-float(cached_result.get("cachedAt",0) or 0)<7*86400:
        if progress: progress(98,"Abrindo os serviços profissionais salvos neste computador")
        return cached_result
    fields=list(dict.fromkeys(name for name in (aliases["aih"],aliases["cns"],"SP_CNES","SP_ATOPROF","SP_PF_CBO","SP_QTD_ATO","SP_VALATO","IN_TP_VAL",aliases["admission"],aliases["discharge"]) if name and name in fieldinfo))
    positions={name:index for index,name in enumerate(fields)}
    pre_filter=[(aliases["aih"],aih),("SP_CNES",establishment),("IN_TP_VAL",sorted(professional_codes))]
    grouped={}
    processed=[0]
    def scan_progress(done,_total):
        if progress and count: progress(min(75,10+int(65*done/count)),f"Filtrando serviços da AIH · {done:,} de {count:,}".replace(",","."))
    act_decimals=int(fieldinfo["SP_QTD_ATO"]["decimals"])
    value_decimals=int(fieldinfo["SP_VALATO"]["decimals"])
    for record in iter_dbf_fields(sp["dbf"],fields,pre_filter=pre_filter,processed_counter=processed,scan_callback=scan_progress if progress else None):
        row_aih=re.sub(r"\D","",str(record[positions[aliases["aih"]]] or ""))
        if row_aih!=aih: continue
        cns=re.sub(r"\D","",str(record[positions[aliases["cns"]]] or ""))
        cnes=_report_code(record[positions["SP_CNES"]],7)
        procedure=_report_code(record[positions["SP_ATOPROF"]],10)
        cbo=_report_code(record[positions["SP_PF_CBO"]],6)
        admission=_report_date(record[positions[aliases["admission"]]]) if aliases["admission"] and aliases["admission"] in positions else ""
        discharge=_report_date(record[positions[aliases["discharge"]]]) if aliases["discharge"] and aliases["discharge"] in positions else ""
        period=" – ".join(value for value in (admission,discharge) if value) or f"Competência {month:02d}/{year}"
        acts=scaled_integer(record[positions["SP_QTD_ATO"]],act_decimals)
        value=scaled_integer(record[positions["SP_VALATO"]],value_decimals)
        key=(cnes,procedure,cns,cbo)
        current=grouped.get(key)
        if current is None: grouped[key]=[acts,value,1,period]
        else: current[0]=max(current[0],acts); current[1]+=value; current[2]+=1
    cns_list=sorted({key[2] for key in grouped if len(key[2])==15 and set(key[2])!={"0"}})
    cns_hashes={cns:hashlib.sha256(cns.encode("ascii")).hexdigest() for cns in cns_list}
    profiles_by_hash=_read_cnes_professional_cache_many(list(cns_hashes.values()))
    profiles={cns:profiles_by_hash[cns_hash] for cns,cns_hash in cns_hashes.items() if cns_hash in profiles_by_hash}
    pending=[cns for cns in cns_list if cns not in profiles]
    lookup_error=False
    if pending:
        if progress: progress(78,f"Consultando {len(pending)} CNS no cadastro oficial do CNES")
        first,available=cnes_professional_by_cns(pending[0],check_cache=False)
        if available:
            if first is not None: profiles[pending[0]]=first
            with ThreadPoolExecutor(max_workers=min(8,max(1,len(pending)-1)),thread_name_prefix="cnes-cns-aih") as executor:
                futures={executor.submit(cnes_professional_by_cns,cns,False):cns for cns in pending[1:]}
                for future in as_completed(futures):
                    cns=futures[future]
                    try:
                        profile,ok=future.result()
                        if ok and profile is not None: profiles[cns]=profile
                        elif not ok: lookup_error=True
                    except Exception: lookup_error=True
        else: lookup_error=True
    rows=[]
    total_acts=0
    total_value=0
    for (cnes,procedure,cns,cbo),(acts,value,records,period) in grouped.items():
        profile=profiles.get(cns,{})
        name=_report_label(profile.get("name") or "") or ("CNS não informado" if not cns else "Nome não localizado no CNES")
        cnes_cbo=next((item for item in profile.get("cbos",[]) if _report_code(item.get("code"),6)==cbo),None) if cbo else None
        cbo_name=_report_label(cbo_labels.get(cbo) or (cnes_cbo.get("label") if cnes_cbo else "") or "Ocupação não informada")
        procedure_name=_report_label(procedure_labels.get(procedure) or "Procedimento sem descrição SIGTAP")
        acts_value=float(Decimal(acts).scaleb(-act_decimals))
        money=float(Decimal(value).scaleb(-value_decimals))
        total_acts+=acts; total_value+=value
        rows.append({"aih":aih,"label":aih,"code":aih,"period":period,"establishment":_report_label(cnes_labels.get(cnes) or f"CNES {cnes}"),"cnes":cnes,
            "procedureCode":procedure,"procedureName":procedure_name,"professionalName":name,"cns":cns,"cbo":cbo,"cboName":cbo_name,
            "acts":acts_value,"value":money,"records":records})
    rows.sort(key=lambda row:(-row["value"],row["professionalName"].casefold(),row["procedureCode"],row["cns"]))
    columns=[
        {"id":"aih","label":"AIH / período","field":"aih","primaryField":"aih","secondaryField":"period","filterFields":["aih","period"],"sortField":"aih","type":"text"},
        {"id":"establishment","label":"Estabelecimento","field":"establishment","primaryField":"establishment","secondaryField":"cnes","secondaryPrefix":"CNES ","filterFields":["establishment","cnes"],"sortField":"establishment","type":"text"},
        {"id":"professional","label":"Profissional executor · CNS","field":"professionalName","primaryField":"professionalName","secondaryField":"cns","secondaryPrefix":"CNS ","sortField":"professionalName","type":"text"},
        {"id":"cbo","label":"CBO do profissional","field":"cboName","primaryField":"cboName","secondaryField":"cbo","secondaryPrefix":"CBO ","sortField":"cboName","type":"text"},
        {"id":"procedure","label":"Procedimento do ato","field":"procedureCode","primaryField":"procedureCode","secondaryField":"procedureName","sortField":"procedureCode","type":"text"},
        {"id":"acts","label":"Atos","field":"acts","type":"number","decimals":act_decimals,"totalField":"acts"},
        {"id":"value","label":"Valor do ato","field":"value","type":"currency","decimals":value_decimals,"totalField":"value"},
    ]
    result={"ok":True,"report":"sih-rd-ocupacao","view":"services","file":sp["source"].name,"path":sp["relative"],"year":year,"month":month,"uf":uf,"state":PREDEFINED_UF_NAMES[uf],"municipality":"","establishmentCode":establishment,"establishmentName":_report_label(cnes_labels.get(establishment) or f"CNES {establishment}"),"aih":aih,"columns":columns,"metrics":[],"kpis":[{"label":"Profissionais","value":{"value":len({row['cns'] for row in rows if row['cns']})}},{"label":"Procedimentos profissionais","value":{"value":len(rows)}},{"label":"Atos","value":{"value":float(Decimal(total_acts).scaleb(-act_decimals)),"decimals":act_decimals}},{"label":"Valor dos serviços","value":{"value":float(Decimal(total_value).scaleb(-value_decimals)),"decimals":value_decimals,"prefix":"R$ "}}],"rows":rows,"records":sum(row["records"] for row in rows),"notes":[
        "Fonte: SIH/SP da competência selecionada, filtrada pelo CNES do hospital e pelo número da AIH. Os atos são agrupados por procedimento, CNS e CBO.",
        "O nome do profissional e as ocupações são consultados no serviço oficial do CNES pelo CNS e mantidos em cache local. Os dados de vínculo refletem o cadastro disponível na consulta atual.",
        *(["O serviço do CNES não respondeu para todos os CNS. Os procedimentos, valores e identificadores do SIH/SP foram preservados."] if lookup_error else []),
        *( ["Esta AIH não possui lançamentos profissionais identificáveis no arquivo SIH/SP desta competência."] if not rows else [] ),
    ],"cachedAt":time.time()}
    if progress: progress(97,"Concluindo os serviços profissionais da AIH")
    cache_write(result_cache,result,max_bytes=20_000_000,keep=100)
    return result

def tabulate(payload, progress=None):
    if payload.get("predefinedReport")=="sinasc-maternidades":
        return predefined_sinasc_maternity_detail(payload,progress) if payload.get("view")=="detail" else predefined_sinasc_maternity(payload,progress)
    if payload.get("predefinedReport")=="srag-semanal":
        return predefined_srag_weekly(payload,progress)
    if payload.get("predefinedReport")=="sisagua-residual-desinfetante":
        return predefined_sisagua_rad(payload,progress)
    if payload.get("predefinedReport") in PQAVS_REPORTS:
        return predefined_pqavs(payload,progress)
    if payload.get("predefinedReport")=="sim-mortalidade":
        return predefined_sim_mortality(payload,progress)
    if payload.get("predefinedReport")=="sim-mortalidade-infantil":
        return predefined_sim_infant_mortality(payload,progress)
    if payload.get("predefinedReport") in SINAN_AGRAVOS:
        return predefined_sinan_dengue(payload,progress)
    if payload.get("predefinedReport") in {"sia-pa-producao","sia-pa-belem"}:
        return predefined_sia_pa_production(payload,progress)
    if payload.get("predefinedReport")=="sih-rd-producao":
        return predefined_sih_rd_production(payload,progress)
    if payload.get("predefinedReport")=="sih-rd-rejeicoes":
        return predefined_sih_rd_rejections(payload,progress)
    if payload.get("predefinedReport")=="sih-rd-fluxo":
        return predefined_sih_admission_flow(payload,progress)
    if payload.get("predefinedReport")=="sih-rd-ocupacao":
        return predefined_sih_bed_occupancy(payload,progress)
    if payload.get("predefinedReport")=="sih-sp-profissionais":
        return predefined_sih_sp_professionals(payload,progress)
    if progress: progress(2,"Conferindo os arquivos e as opções")
    raw_sources=payload.get("sources")
    if not isinstance(raw_sources,list) or not raw_sources:
        relative=payload.get("path",""); raw_sources=[{"path":relative,"dbfPath":payload.get("dbfPath") or converted_relative(relative)}]
    if len(raw_sources)>50: raise ValueError("É possível tabular até 50 arquivos na mesma execução.")
    sources=[]
    for item in raw_sources:
        if not isinstance(item,dict): raise ValueError("A lista de arquivos é inválida.")
        source=safe_file(item.get("path","")); canonical_relative=source.relative_to(UPLOADS).as_posix(); system,kind,filename_match=meta(source); uf=filename_match.group("uf").upper(); dbf=safe_dbf(item.get("dbfPath") or converted_relative(canonical_relative),canonical_relative)
        if sources and (system,kind,uf)!=(sources[0]["system"],sources[0]["kind"],sources[0]["uf"]): raise ValueError("Todos os arquivos precisam pertencer à mesma família, tipo de base e unidade da Federação.")
        sources.append({"source":source,"dbf":dbf,"system":system,"kind":kind,"uf":uf,"year":2000+int(filename_match.group("yy")),"month":int(filename_match.group("mm"))})
    system,kind=sources[0]["system"],sources[0]["kind"]
    _,_,_,fieldinfo=dbf_layout(sources[0]["dbf"])
    fieldset=set(fieldinfo)
    sigtap_field=next((name for name in ("PA_PROC_ID","PROC_REA","SP_ATOPROF") if name in fieldset),None)
    if payload.get("sigtapFilters") and not sigtap_field:
        raise ValueError("Esta base não possui um código de procedimento compatível com o filtro SIGTAP.")
    sigtap_by_file={item["source"].name:_sigtap_procedure_filter(payload,item["year"],item["month"],fieldset,sigtap_field or "",item["dbf"]) for item in sources} if payload.get("sigtapFilters") else {}
    for item in sources[1:]:
        _,_,_,other=dbf_layout(item["dbf"])
        if set(other)!=fieldset or any((other[n]["type"],other[n]["length"],other[n]["decimals"])!=(v["type"],v["length"],v["decimals"]) for n,v in fieldinfo.items()):
            raise ValueError(f"O arquivo {item['source'].name} possui campos diferentes dos demais selecionados.")
    fields=[{"name":name,"type":info["type"],"length":info["length"],"decimals":info["decimals"]} for name,info in fieldinfo.items()]
    defname,definition=archive_def(system,kind)
    if definition is None: raise RuntimeError("Definição oficial indisponível para este arquivo.")
    rows,cols,selections,increments,group=parse_def(definition,fields)
    add_sp_identifier_options(kind,fieldset,rows)
    rowoption=next((item for item in rows if item["id"]==payload.get("row")),None)
    coloption=next((item for item in cols if item["id"]==payload.get("column")),None) if payload.get("column") else None
    if not rowoption: raise ValueError("Escolha uma linha disponível na definição.")
    if payload.get("column") and not coloption: raise ValueError("Escolha uma coluna disponível na definição.")
    raw_additional=payload.get("additionalColumns",[])
    if not isinstance(raw_additional,list) or len(raw_additional)>2: raise ValueError("Adicione no máximo duas dimensões extras ao resultado.")
    available_column_options={item["id"]:item for item in cols}
    additional_ids=list(dict.fromkeys(str(value) for value in raw_additional))
    if coloption and coloption["id"] in additional_ids: raise ValueError("A coluna principal já está incluída no resultado.")
    if any(option_id not in available_column_options for option_id in additional_ids): raise ValueError("Uma coluna adicional não pertence à definição deste arquivo.")
    additional_options=[available_column_options[option_id] for option_id in additional_ids]
    column_options=([coloption] if coloption else [])+additional_options
    rowfield=rowoption["field"]; colfield=coloption["field"] if coloption else ""
    raw_metrics=payload.get("metrics") or [payload.get("metric","FREQ")]
    if not isinstance(raw_metrics,list) or not 1<=len(raw_metrics)<=50: raise ValueError("Selecione de 1 a 50 incrementos.")
    metrics=list(dict.fromkeys(str(value).upper() for value in raw_metrics))
    valid_metrics={"FREQ","RECORDS",*(item["field"] for item in increments)}
    if any(metric not in valid_metrics for metric in metrics): raise ValueError("Um incremento escolhido não pertence à definição deste arquivo.")
    groupfield=(group or {}).get("field")
    metric_details=[]
    increment_labels={item["field"]:item["label"] for item in increments}
    for metric in metrics:
        numeric=groupfield if metric=="FREQ" and groupfield else metric if metric not in {"FREQ","RECORDS"} else ""
        if numeric and numeric not in fieldinfo: raise ValueError("Um campo numérico da definição não existe no DBF.")
        metric_details.append({"id":metric,"field":numeric,"decimals":fieldinfo[numeric]["decimals"] if numeric else 0,"label":(f"Frequência · {groupfield}" if metric=="FREQ" and groupfield else "Frequência de registros" if metric=="FREQ" else "Número de registros" if metric=="RECORDS" else increment_labels.get(metric,metric))})
    raw_filters=payload.get("filters",[])
    if not isinstance(raw_filters,list) or len(raw_filters)>300: raise ValueError("A lista de categorias selecionadas é inválida ou excede o limite de 300.")
    filter_option_groups={"selection":selections,"column":cols,"line":rows}
    available_filter_options={kind_name:{item["id"]:item for item in options} for kind_name,options in filter_option_groups.items()}
    filters=defaultdict(lambda:{"include":set(),"exclude":set()})
    for condition in raw_filters:
        option_type=str(condition.get("optionType") or "selection") if isinstance(condition,dict) else ""
        option_id=condition.get("option") if isinstance(condition,dict) else None
        if option_type not in available_filter_options or option_id not in available_filter_options[option_type]: raise ValueError("Um filtro não pertence à definição deste arquivo.")
        value=str(condition.get("value","" )).strip(); mode=str(condition.get("mode","include")).lower()
        if not value or len(value)>80 or mode not in {"include","exclude"}: raise ValueError("Uma categoria selecionada é inválida.")
        filters[(option_type,option_id)][mode].add(value)
    filter_specs=[(available_filter_options[option_type][option_id]["field"],conditions) for (option_type,option_id),conditions in filters.items()]
    excluded_filter_fields={rowoption["field"],*(item["field"] for item in column_options),*(available_filter_options[option_type][option_id]["field"] for option_type,option_id in filters)}
    result_filter_options=[]; seen_filter_fields=set()
    for option_type,options in filter_option_groups.items():
        for item in options:
            if item["field"] in excluded_filter_fields or item["field"] in seen_filter_fields: continue
            result_filter_options.append({"id":item["id"],"label":item["label"],"field":item["field"],"optionType":option_type}); seen_filter_fields.add(item["field"])
    column_filter=payload.get("columnFilter"); column_value=""
    if column_filter:
        if not isinstance(column_filter,dict) or not coloption or column_filter.get("option")!=coloption["id"]: raise ValueError("O valor selecionado não corresponde à coluna atual.")
        column_value=str(column_filter.get("value","" )).strip()
        if len(column_value)>80: raise ValueError("O valor da coluna excede 80 caracteres.")
    munfield=municipality_field(system,fieldset)
    requested_municipality=bool(str(payload.get("municipalityCode") or "").strip())
    municipality=municipality_code(payload,fieldset,munfield)
    usemun=bool(municipality)
    municipality_skipped=requested_municipality and not usemun and not munfield
    municipality_name=str(payload.get("municipalityName") or "").strip()[:80] if usemun else ""
    rowlabels=relation_mapping(system,rowoption); column_labels=[relation_mapping(system,item) for item in column_options]
    unclassified_mode=str(payload.get("unclassified","ignore")).lower()
    if unclassified_mode not in {"ignore","include","discriminate"}: raise ValueError("Tratamento de não classificados inválido.")
    suppress_rows=bool(payload.get("suppressRows",True)); suppress_columns=bool(payload.get("suppressColumns",True))
    save_records=bool(payload.get("saveRecords",False)); test_crc=bool(payload.get("testCrc",False))
    archive=UPLOADS/"DEFINICOES"/"originais"/f"TAB_{system}.zip"
    identity={"cacheVersion":9,"dbfs":[cache_file_identity(x["dbf"]) for x in sources],"definition":cache_file_identity(archive) if archive.is_file() else defname,"row":rowoption["id"],"columns":[item["id"] for item in column_options],"metrics":metrics,"municipalityCode":municipality,"municipalitySkipped":municipality_skipped,"filters":[[key,mode,sorted(values)] for key,state in filters.items() for mode,values in state.items()],"sigtap":payload.get("sigtapFilters"),"sigtapVersions":[pair[1].get("sha256") for pair in sigtap_by_file.values()],"columnFilter":{"option":coloption["id"],"value":column_value} if column_value and coloption else None,"unclassified":unclassified_mode,"suppressRows":suppress_rows,"suppressColumns":suppress_columns}
    target=cache_target("tabulations",identity)
    if not save_records and not test_crc:
        cached=cache_read(target)
        if cached is not None:
            if progress: progress(98,"Abrindo tabulação já calculada")
            return cached
    column_fields=[item["field"] for item in column_options]
    requested=[rowfield]+column_fields+[detail["field"] for detail in metric_details if detail["field"]]+[field for field,_ in filter_specs]
    names=list(dict.fromkeys(requested)); positions={name:index for index,name in enumerate(names)}
    row_index=positions[rowfield]; col_indices=[positions[field] for field in column_fields]; col_index=positions[colfield] if colfield else None
    filter_indexes=[(positions[field],conditions) for field,conditions in filter_specs]
    metric_indexes=[positions[detail["field"]] if detail["field"] else None for detail in metric_details]
    agg=defaultdict(int); rowtot=defaultdict(int); coltot=defaultdict(int); rowset=set(); colset=set(); totals=[0 for _ in metrics]
    records=0; excluded_unclassified=0; processed=0; indexes_by_file=[]; classified_cache={}
    total_to_scan=sum(dbf_layout(item["dbf"])[0] for item in sources)
    if progress: progress(5,"Lendo os registros")
    for item in sources:
        if test_crc: verify_dbc_against_dbf(item["source"],item["dbf"])
        sigtap_filter,sigtap_source=sigtap_by_file.get(item["source"].name,(None,None))
        selected_indexes=[] if save_records else None
        processed_file=[0]
        def scan_update(file_processed,_file_total):
            if progress and total_to_scan:
                progress(min(94,5+int(89*(processed+file_processed)/total_to_scan)),f"Lendo os registros · {processed+file_processed:,} de {total_to_scan:,}".replace(",","."))
        prefilters=([(munfield,municipality)] if usemun else [])+([sigtap_filter] if sigtap_filter else [])
        for record_index,record in iter_dbf_fields(item["dbf"],names,with_index=True,pre_filter=prefilters or None,processed_counter=processed_file,scan_callback=scan_update if progress else None):
            passed=True
            for index,condition in filter_indexes:
                value=record[index]
                if condition["include"] and value not in condition["include"]: passed=False; break
                if value in condition["exclude"]: passed=False; break
            if not passed: continue
            if column_value and record[col_index]!=column_value: continue
            raw_key=record[row_index] or "(vazio)"
            classified=classified_cache.get(raw_key)
            if classified is None:
                classified=category_is_classified(rowlabels,raw_key)
                classified_cache[raw_key]=classified
            if not classified and unclassified_mode=="ignore":
                excluded_unclassified+=1; continue
            key="\x00UNCLASSIFIED" if not classified and unclassified_mode=="include" else raw_key
            col=tuple(record[index] or "(vazio)" for index in col_indices) if col_indices else ("Total",)
            values=[]
            for detail,index in zip(metric_details,metric_indexes):
                if detail["id"]=="RECORDS" or (detail["id"]=="FREQ" and not groupfield): value=1
                else: value=scaled_integer(record[index],detail["decimals"])
                values.append(value)
            rowset.add(key); colset.add(col)
            if selected_indexes is not None: selected_indexes.append(record_index)
            records+=1
            for metric_index,value in enumerate(values):
                metric=metrics[metric_index]
                cell=(key,col,metric)
                if cell not in agg and len(agg)>=500000: raise ValueError("A combinação cria mais de 500 mil células. Escolha menos categorias ou remova a coluna.")
                agg[cell]+=value; rowtot[(key,metric)]+=value; coltot[(col,metric)]+=value; totals[metric_index]+=value
            if len(rowset)>50000 or len(colset)>250: raise ValueError("A tabulação ultrapassou o limite prático de linhas ou colunas. Escolha outra combinação.")
        processed+=processed_file[0]
        if selected_indexes is not None: indexes_by_file.append(selected_indexes)
        if progress and total_to_scan: progress(min(94,5+int(89*processed/total_to_scan)),f"Lendo os registros · {processed:,} de {total_to_scan:,}".replace(",","."))
    if progress: progress(95,"Montando a tabela e os totais")
    def ordered_codes(mapping,observed,suppress):
        values=set(observed)
        if not suppress and mapping: values.update(code for code in mapping.keys() if code!="\x00ranges")
        order={code:index for index,code in enumerate(code for code in mapping if code!="\x00ranges")}
        return sorted(values,key=lambda code:(order.get(code,1000000000),code))
    raw_rows=ordered_codes(rowlabels,rowset,suppress_rows)
    if column_options:
        dimension_codes=[ordered_codes(mapping,{key[index] for key in colset},suppress_columns) for index,mapping in enumerate(column_labels)]
        if suppress_columns:
            orders=[{code:index for index,code in enumerate(codes)} for codes in dimension_codes]
            raw_columns=sorted(colset,key=lambda values:tuple((orders[index].get(code,1000000000),code) for index,code in enumerate(values)))
        else:
            combinations=1
            for values in dimension_codes: combinations*=len(values)
            if combinations>250: raise ValueError("As dimensões escolhidas geram mais de 250 colunas. Ative Suprimir colunas zeradas ou escolha menos dimensões.")
            raw_columns=list(product(*dimension_codes))
    else: raw_columns=[("Total",)]
    if suppress_rows:
        raw_rows=[key for key in raw_rows if any(rowtot[(key,metric)]!=0 for metric in metrics)]
    if column_options and suppress_columns:
        raw_columns=[codes for codes in raw_columns if any(coltot[(codes,metric)]!=0 for metric in metrics)]
    output_column_count=len(raw_columns)*len(metrics) if column_options else len(metrics)
    if output_column_count>250: raise ValueError("As categorias e medidas gerariam mais de 250 colunas. Escolha menos dimensões ou medidas.")
    dimension_names=[(" · ".join(f"{option['label']}: {cnv_label(mapping,code)}" for option,mapping,code in zip(column_options,column_labels,codes)) if len(column_options)>1 else cnv_label(column_labels[0],codes[0])) for codes in raw_columns] if column_options else []
    display_columns=[f"{name} · {detail['label']}" for name in dimension_names for detail in metric_details] if column_options and len(metrics)>1 else dimension_names if column_options else ([detail["label"] for detail in metric_details] if len(metrics)>1 else ["Total"])
    result_rows=[]
    for key in raw_rows[:5000]:
        if key=="\x00UNCLASSIFIED": label="Não classificados"
        else: label=cnv_label(rowlabels,key)
        if column_options and len(metrics)>1:
            values=[scaled_text(agg[(key,col,metric)],detail["decimals"]) for col in raw_columns for metric,detail in zip(metrics,metric_details)]
        elif column_options:
            values=[scaled_text(agg[(key,col,metrics[0])],metric_details[0]["decimals"]) for col in raw_columns]
        elif len(metrics)>1:
            values=[scaled_text(rowtot[(key,metric)],detail["decimals"]) for metric,detail in zip(metrics,metric_details)]
        else: values=[scaled_text(rowtot[(key,metrics[0])],metric_details[0]["decimals"])]
        item={"key":"" if key=="\x00UNCLASSIFIED" else key,"label":label,"values":values,"unclassified":key=="\x00UNCLASSIFIED"}
        if len(metrics)==1: item["total"]=scaled_text(rowtot[(key,metrics[0])],metric_details[0]["decimals"])
        result_rows.append(item)
    if column_options and len(metrics)>1:
        column_totals=[scaled_text(coltot[(col,metric)],detail["decimals"]) for col in raw_columns for metric,detail in zip(metrics,metric_details)]
        total=None
    elif column_options:
        column_totals=[scaled_text(coltot[(col,metrics[0])],metric_details[0]["decimals"]) for col in raw_columns]
        total=scaled_text(totals[0],metric_details[0]["decimals"])
    elif len(metrics)>1:
        column_totals=[scaled_text(value,detail["decimals"]) for value,detail in zip(totals,metric_details)]
        total=None
    else:
        column_totals=[scaled_text(totals[0],metric_details[0]["decimals"])]; total=scaled_text(totals[0],metric_details[0]["decimals"])
    result={"ok":True,"definition":defname,"uf":sources[0]["uf"],"rowDimension":{"id":rowoption["id"],"label":rowoption["label"],"field":rowfield},"column":coloption["id"] if coloption else None,"metrics":[{"id":m["id"],"label":m["label"]} for m in metric_details],"metric":metric_details[0]["label"] if len(metrics)==1 else f"{len(metrics)} incrementos","records":records,"processedRecords":processed,"excludedUnclassified":excluded_unclassified,"total":total,"totalsByMetric":[scaled_text(value,detail["decimals"]) for value,detail in zip(totals,metric_details)],"columnTotals":column_totals,"municipalityApplied":usemun,"municipalitySkipped":municipality_skipped,"municipalityCode":municipality or None,"municipalityName":municipality_name or None,"municipalityField":munfield if usemun else None,"appliedFilters":sum(len(state["include"])+len(state["exclude"]) for state in filters.values())+(1 if column_value else 0)+len(payload.get("sigtapFilters") or {}),"columns":display_columns,"columnDimensions":[{"id":item["id"],"label":item["label"],"field":item["field"]} for item in column_options],"filterOptions":result_filter_options,"availableColumns":[{"id":item["id"],"label":item["label"],"field":item["field"]} for item in cols],"additionalColumns":additional_ids,"rows":result_rows,"totalCategories":len(raw_rows),"truncated":len(raw_rows)>5000,"files":[x["source"].name for x in sources],"unclassifiedMode":unclassified_mode,"suppressRows":suppress_rows,"suppressColumns":suppress_columns,"crcTested":test_crc}
    if sigtap_by_file: result["sigtapSources"]=[status for _,status in sigtap_by_file.values()]
    if save_records:
        if progress: progress(97,"Salvando os registros selecionados")
        token=secrets.token_hex(16)
        saved=save_dbf_records([x["dbf"] for x in sources],indexes_by_file,token)
        result["savedRecords"]={"url":"download.php?token="+token,"name":saved.name,"count":records}
    if not save_records and not test_crc: cache_write(target,result,max_bytes=10_000_000)
    if progress: progress(99,"Preparando o resultado")
    return result

def tabwin_handle(payload):
    action=payload.get("action")
    if action=="catalog": return catalog()
    if action=="delete_file": return delete_library_file(payload)
    if action=="schema": return schema(payload.get("path",""))
    if action=="preset_list": return saved_presets(payload.get("path",""))
    if action=="preset_save": return save_preset(payload)
    if action=="preset_get": return get_preset(payload)
    if action=="preset_delete": return delete_preset(payload)
    if action=="column_values": return column_values(payload)
    if action=="category_values": return category_values(payload)
    if action=="predefined_filter_options": return predefined_filter_options(payload)
    if action=="tabulate": return tabulate(payload)
    if action=="tabulate_start": return start_tabulation(payload)
    if action=="tabulate_status": return tabulation_status(payload.get("job_id",""))
    if action=="convert_start": return start_conversion(payload.get("path",""))
    if action=="convert_status": return conversion_status(payload.get("job_id",""))
    raise ValueError("Ação de tabulação inválida.")

if __name__ == "__main__":
    import sys
    if len(sys.argv)>2 and sys.argv[1]=="--worker":
        run_conversion_worker(sys.argv[2]); raise SystemExit(0)
    if len(sys.argv)>2 and sys.argv[1]=="--tabulate-worker":
        run_tabulation_worker(sys.argv[2]); raise SystemExit(0)
    try:
        if hasattr(sys.stdin,"reconfigure"): sys.stdin.reconfigure(encoding="utf-8")
        request=json.load(sys.stdin)
        result=tabwin_handle(request)
        sys.stdout.write(json.dumps(result,ensure_ascii=True,default=str))
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok":False,"error":str(exc)},ensure_ascii=True))
        raise SystemExit(2)
