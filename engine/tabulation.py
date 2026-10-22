"""Tabulação local de arquivos DATASUS usando definições oficiais do TabWin."""
from __future__ import annotations

import json, os, re, subprocess, tempfile, zipfile, secrets, threading, time, sys, mmap, hashlib, stat, calendar
from datetime import date
import urllib.request, urllib.error, urllib.parse, xml.etree.ElementTree as ET, sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from ftplib import FTP
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from itertools import product
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from official_source import download_file as portal_download_file, open_verified_https
from storage_lock import interprocess_lock

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
    with lock_path.open("a+b") as lock:
        if os.name=="nt":
            import msvcrt
            lock.seek(0,os.SEEK_END)
            if lock.tell()==0:
                lock.write(b"\0")
                lock.flush()
            acquired=False
            for _ in range(240):
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
                    acquired=True
                    break
                except OSError:
                    time.sleep(.05)
            if not acquired:
                raise TimeoutError("O status do processamento está sendo atualizado por outra tarefa.")
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(),fcntl.LOCK_UN)

@contextmanager
def source_use_locks(relative_paths, blocking=True):
    """Cross-process locks shared by readers/converters and library deletion."""
    lock_folder=UPLOADS/".jobs"/"file-locks"
    lock_folder.mkdir(parents=True,exist_ok=True)
    handles=[]; acquired=[]
    try:
        identities=sorted({str(path).replace("\\","/").casefold() for path in relative_paths})
        for identity in identities:
            lock_path=lock_folder/(hashlib.sha256(identity.encode("utf-8")).hexdigest()+".lock")
            handle=lock_path.open("a+b"); handles.append(handle)
            if os.name=="nt":
                import msvcrt
                handle.seek(0,os.SEEK_END)
                if handle.tell()==0:
                    handle.write(b"\0"); handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                flags=fcntl.LOCK_EX|(0 if blocking else fcntl.LOCK_NB)
                fcntl.flock(handle.fileno(),flags)
            acquired.append(handle)
        yield
    except (OSError,BlockingIOError) as exc:
        if not blocking:
            raise ValueError("Este arquivo está em uso por uma conversão, tabulação ou exportação. Aguarde e tente novamente.") from exc
        raise
    finally:
        for handle in reversed(acquired):
            try:
                if os.name=="nt":
                    import msvcrt
                    handle.seek(0); msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
            except OSError: pass
        for handle in handles:
            try: handle.close()
            except OSError: pass

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
    if not path.exists() or path.stat().st_size < 1000:
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
                        with tmp.open("wb") as out: ftp.retrbinary(f"RETR {remote}",out.write,blocksize=1024*1024)
                    finally:
                        try: ftp.quit()
                        except Exception: ftp.close()
                except Exception as ftp_error:
                    raise RuntimeError(f"Não foi possível baixar as definições oficiais por HTTPS nem FTP. HTTPS: {https_error}; FTP: {ftp_error}") from ftp_error
            if tmp.stat().st_size < 1000: raise RuntimeError("O pacote oficial de definições chegou incompleto.")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
    return path

def archive_def(system: str, kind: str):
    name=DEF_MAP.get(kind)
    if not name: return None,None
    archive=ensure_archive(system)
    with zipfile.ZipFile(archive) as z:
        matches=[n for n in z.namelist() if PurePosixPath(n).name.lower()==name.lower()]
        if not matches: return name,None
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
    clean={"row":row,"column":column,"metrics":list(dict.fromkeys(metrics)),"filters":clean_filters,"columnFilter":clean_column_filter,"suppressRows":bool(supplied.get("suppressRows",True)),"suppressColumns":bool(supplied.get("suppressColumns",True)),"testCrc":bool(supplied.get("testCrc",False)),"saveRecords":bool(supplied.get("saveRecords",False)),"unclassified":unclassified,"municipalityFilter":bool(supplied.get("municipalityFilter",False))}
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
    if payload.get("report")=="sih-rd-producao":
        return predefined_sih_filter_options(payload)
    if payload.get("report")=="sih-rd-rejeicoes":
        return predefined_sih_filter_options(payload)
    if payload.get("report")=="sih-rd-ocupacao":
        return predefined_sih_occupancy_filter_options(payload)
    if payload.get("report")=="sih-sp-profissionais":
        return predefined_sih_sp_filter_options(payload)
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

def predefined_sia_pa_production(payload: dict[str,Any], progress=None):
    """Monthly state-level SIA production, with optional municipal/profile filters."""
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

    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIA.zip"
    identity={"report":"sia-pa-production-v6","source":cache_file_identity(source),"dbf":cache_file_identity(dbf),"definition":cache_file_identity(archive),"view":view,"establishment":establishment,"uf":uf,"municipality":municipality,"filters":selected_filter_codes}
    target=cache_target("predefined-reports",identity)
    cached=cache_read(target)
    if isinstance(cached,dict) and cached.get("ok") is True:
        if progress: progress(98,"Abrindo o relatório salvo neste computador")
        return cached

    filters=[]
    if municipality: filters.append(("PA_UFMUN",municipality))
    filters.extend(selected_filter_codes.items())
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
    sums=defaultdict(lambda:[0,0,0,0,0,0,0,0])
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
        group_key=(code,complexity_code,financing_code) if view=="detail" else code
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
        sortable_rows.append((-int(values[2]),label.casefold(),code,(complexity_label.casefold(),financing_label.casefold()),row))
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

    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIH.zip"
    identity={"report":"sih-rd-production-v1","source":cache_file_identity(source),"dbf":cache_file_identity(dbf),"definition":cache_file_identity(archive),"view":view,"establishment":establishment,"uf":uf,"municipality":municipality,"filters":selected_filter_codes}
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
    if progress: progress(97,"Finalizando totais e descrições oficiais")
    cache_write(target,result,max_bytes=25_000_000,keep=30)
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

    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIH.zip"
    identity={"report":"sih-rj-rejeicoes-v3","sources":[cache_file_identity(item["source"])|{"dbf":cache_file_identity(item["dbf"])} for item in (rejected,*([errors] if errors else []))],"definition":cache_file_identity(archive),"view":view,"establishment":establishment,"uf":uf,"municipality":municipality,"filters":selected_filter_codes}
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
    if progress: progress(97,"Finalizando valores, totais e motivos oficiais")
    cache_write(target,result,max_bytes=100_000_000,keep=30)
    return result

def _read_cnes_establishment_cache(cnes: str, competence: str):
    connection=None
    try:
        with CNES_ESTABLISHMENT_CACHE_LOCK:
            CNES_ESTABLISHMENT_CACHE.parent.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(str(CNES_ESTABLISHMENT_CACHE),timeout=8)
            connection.execute("CREATE TABLE IF NOT EXISTS establishment_classifications (cnes TEXT NOT NULL, competence TEXT NOT NULL, data_json TEXT NOT NULL, fetched_at REAL NOT NULL, PRIMARY KEY(cnes,competence))")
            connection.commit()
            row=connection.execute("SELECT data_json,fetched_at FROM establishment_classifications WHERE cnes=? AND competence=?",(cnes,competence)).fetchone()
        if not row or time.time()-float(row[1])>=30*86400: return None
        data=json.loads(row[0])
        return data if isinstance(data,dict) else None
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

    needs_current=(
        need_sus
        or data.get("management") in {None,"","NAO_INFORMADA"}
        or not data.get("legalNature")
        or data.get("natureGroup") in {None,"","NAO_INFORMADA"}
    )
    if needs_current and not data.get("currentChecked"):
        current,ok=_cnes_open_data_json(f"/cnes/estabelecimentos/{digits}")
        service_available=service_available or ok
        if isinstance(current,dict) and str(current.get("codigo_cnes") or "").zfill(7)==digits:
            legal_code=_cnes_nature_code(current.get("descricao_natureza_juridica_estabelecimento"))
            if not data.get("management") or data.get("management")=="NAO_INFORMADA":
                data["management"]=_normalize_cnes_management(current.get("tipo_gestao") or current.get("descricao_esfera_administrativa"))
            if not data.get("legalNature"): data["legalNature"]=legal_code
            if data.get("natureGroup") in {None,"","NAO_INFORMADA"}: data["natureGroup"]=_normalize_cnes_nature_group("",legal_code)
            if need_sus:
                attendance=current.get("estabelecimento_faz_atendimento_hospitalar_sus")
                if attendance is None: attendance=current.get("estabelecimento_possui_atendimento_hospitalar")
                data["hospitalSUS"]=_normalize_cnes_sus(attendance)
            data["currentUpdatedAt"]=_report_label(current.get("data_atualizacao") or "")[:20]
            if data.get("source")!="competence": data["source"]="current"
        data["currentChecked"]=bool(ok)
        if need_sus: data["attendanceChecked"]=bool(ok)

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
                if not available: failures+=1
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
        if not row or time.time()-float(row[2])>=90*86400: return None
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
                    if time.time()-float(fetched_at)>=90*86400: continue
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

    source_identity=cache_file_identity(source); dbf_identity=cache_file_identity(dbf)
    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIH.zip"
    identity={"report":"sih-sp-profissionais-v6","source":source_identity,"dbf":dbf_identity,"definition":cache_file_identity(archive),"uf":uf,"municipality":municipality,"filters":selected_filter_codes}
    target=cache_target("predefined-reports",identity)
    cached=cache_read(target)
    if isinstance(cached,dict) and cached.get("ok") is True and time.time()-float(cached.get("cachedAt",0) or 0)<30*86400:
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
        source_current_count=sum(1 for data in cnes_classifications.values() if data.get("source")=="current")
        cnes_filter_notes.append("Tipo de gestão e natureza jurídica vêm do CNES quando não existem no arquivo SIH/SP. O sistema tenta primeiro a competência do relatório e usa o cadastro atual somente quando a competência não retorna registro.")
        if need_sus:
            cnes_filter_notes.append("O filtro de atendimento hospitalar SUS consulta a situação atual do CNES e pode diferir da situação do estabelecimento na competência histórica.")
        if source_current_count:
            cnes_filter_notes.append(f"O cadastro atual do CNES foi usado para {source_current_count:,} estabelecimento(s) sem classificação disponível na competência selecionada.".replace(",","."))
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
        {"id":"professional","label":"Profissional executor · CNS","field":"professionalName","primaryField":"professionalName","secondaryField":"cns","secondaryPrefix":"CNS ","tertiaryField":"cboName","tertiaryPrefix":"CBO ","tertiaryCodeField":"cbo","type":"text","sortField":"professionalName"},
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
    if progress: progress(97,"Finalizando a tabela de produção profissional")
    if not lookup_error: cache_write(target,result,max_bytes=100_000_000,keep=30)
    return result

CNES_LEITO_SERVICE = "https://servicos.saude.gov.br/cnes/LeitoService/v1r0"
CNES_LEITO_NS = "http://servicos.saude.gov.br/cnes/v1r0/leitoservice"
CNES_LEITO_DATA_NS = "http://servicos.saude.gov.br/schema/cnes/v1r0/leito"
CNES_CODE_NS = "http://servicos.saude.gov.br/schema/cnes/v1r0/codigocnes"
CNES_BED_CACHE = UPLOADS/".cache"/"cnes-bed-counts.sqlite3"
CNES_BED_CACHE_LOCK = threading.RLock()

def _read_cnes_bed_cache(cnes: str):
    connection=None
    try:
        with CNES_BED_CACHE_LOCK:
            CNES_BED_CACHE.parent.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(str(CNES_BED_CACHE),timeout=8)
            connection.execute("CREATE TABLE IF NOT EXISTS bed_counts (cnes TEXT PRIMARY KEY, data_json TEXT NOT NULL, fetched_at REAL NOT NULL)")
            connection.commit()
            row=connection.execute("SELECT data_json,fetched_at FROM bed_counts WHERE cnes=?",(cnes,)).fetchone()
        if not row or time.time()-float(row[1])>=7*86400: return None
        data=json.loads(row[0])
        return data if isinstance(data,dict) else None
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

    source_items=[rd,rj,*([er] if er else [])]
    archive=UPLOADS/"DEFINICOES"/"originais"/"TAB_SIH.zip"
    identity={"report":"sih-bed-occupancy-v3","sources":[cache_file_identity(item["source"])|{"dbf":cache_file_identity(item["dbf"])} for item in source_items],"definition":cache_file_identity(archive),"view":view,"establishment":establishment,"uf":uf,"municipality":municipality,"filters":selected_codes}
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
                    else: lookup_errors+=1
                except Exception: lookup_errors+=1
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
            "A taxa de rejeição é calculada como AIHs no RJ ÷ (AIHs no RD + AIHs no RJ). As faixas de situação são referências visuais do SPPtab, não uma classificação oficial do CNES/SIH.",
            *( [f"A última atualização de leitos informada pelo CNES nesta consulta é {max((str(value.get('updatedAt') or '') for value in beds_by_cnes.values()),default='')}." ] if any(value.get("updatedAt") for value in beds_by_cnes.values()) else [] ),
            *([f"O CNES não respondeu para {lookup_errors} estabelecimento(s); a ocupação e o saldo desses locais ficam sem cálculo até uma próxima consulta."] if lookup_errors else []),
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
    result_cache=cache_target("predefined-reports",{"report":"sih-bed-services-v1","source":cache_file_identity(sp["source"]),"dbf":cache_file_identity(sp["dbf"]),"definition":cache_file_identity(archive),"uf":uf,"cnes":establishment,"aih":aih})
    cached_result=cache_read(result_cache)
    if isinstance(cached_result,dict) and cached_result.get("ok") is True and time.time()-float(cached_result.get("cachedAt",0) or 0)<30*86400:
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
        {"id":"professional","label":"Profissional executor · CNS","field":"professionalName","primaryField":"professionalName","secondaryField":"cns","secondaryPrefix":"CNS ","tertiaryField":"cboName","tertiaryCodeField":"cbo","tertiaryPrefix":"CBO ","sortField":"professionalName","type":"text"},
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
    if payload.get("predefinedReport") in {"sia-pa-producao","sia-pa-belem"}:
        return predefined_sia_pa_production(payload,progress)
    if payload.get("predefinedReport")=="sih-rd-producao":
        return predefined_sih_rd_production(payload,progress)
    if payload.get("predefinedReport")=="sih-rd-rejeicoes":
        return predefined_sih_rd_rejections(payload,progress)
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
        sources.append({"source":source,"dbf":dbf,"system":system,"kind":kind,"uf":uf})
    system,kind=sources[0]["system"],sources[0]["kind"]
    _,_,_,fieldinfo=dbf_layout(sources[0]["dbf"])
    fieldset=set(fieldinfo)
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
    identity={"cacheVersion":8,"dbfs":[cache_file_identity(x["dbf"]) for x in sources],"definition":cache_file_identity(archive) if archive.is_file() else defname,"row":rowoption["id"],"columns":[item["id"] for item in column_options],"metrics":metrics,"municipalityCode":municipality,"municipalitySkipped":municipality_skipped,"filters":[[key,mode,sorted(values)] for key,state in filters.items() for mode,values in state.items()],"columnFilter":{"option":coloption["id"],"value":column_value} if column_value and coloption else None,"unclassified":unclassified_mode,"suppressRows":suppress_rows,"suppressColumns":suppress_columns}
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
        selected_indexes=[] if save_records else None
        processed_file=[0]
        def scan_update(file_processed,_file_total):
            if progress and total_to_scan:
                progress(min(94,5+int(89*(processed+file_processed)/total_to_scan)),f"Lendo os registros · {processed+file_processed:,} de {total_to_scan:,}".replace(",","."))
        for record_index,record in iter_dbf_fields(item["dbf"],names,with_index=True,pre_filter=(munfield,municipality) if usemun else None,processed_counter=processed_file,scan_callback=scan_update if progress else None):
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
    result={"ok":True,"definition":defname,"uf":sources[0]["uf"],"rowDimension":{"id":rowoption["id"],"label":rowoption["label"],"field":rowfield},"column":coloption["id"] if coloption else None,"metrics":[{"id":m["id"],"label":m["label"]} for m in metric_details],"metric":metric_details[0]["label"] if len(metrics)==1 else f"{len(metrics)} incrementos","records":records,"processedRecords":processed,"excludedUnclassified":excluded_unclassified,"total":total,"totalsByMetric":[scaled_text(value,detail["decimals"]) for value,detail in zip(totals,metric_details)],"columnTotals":column_totals,"municipalityApplied":usemun,"municipalitySkipped":municipality_skipped,"municipalityCode":municipality or None,"municipalityName":municipality_name or None,"municipalityField":munfield if usemun else None,"appliedFilters":sum(len(state["include"])+len(state["exclude"]) for state in filters.values())+(1 if column_value else 0),"columns":display_columns,"columnDimensions":[{"id":item["id"],"label":item["label"],"field":item["field"]} for item in column_options],"filterOptions":result_filter_options,"availableColumns":[{"id":item["id"],"label":item["label"],"field":item["field"]} for item in cols],"additionalColumns":additional_ids,"rows":result_rows,"totalCategories":len(raw_rows),"truncated":len(raw_rows)>5000,"files":[x["source"].name for x in sources],"unclassifiedMode":unclassified_mode,"suppressRows":suppress_rows,"suppressColumns":suppress_columns,"crcTested":test_crc}
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
