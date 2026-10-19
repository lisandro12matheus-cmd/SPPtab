"""Tabulação local de arquivos DATASUS usando definições oficiais do TabWin."""
from __future__ import annotations

import json, os, re, subprocess, tempfile, zipfile, secrets, threading, time, sys, mmap, hashlib, stat
from contextlib import contextmanager
from ftplib import FTP
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from itertools import product
from pathlib import Path, PurePosixPath
from typing import Any

from official_source import download_file as portal_download_file

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
FILENAME = re.compile(r"^(?P<kind>[A-Z]{2,4}?)(?P<uf>[A-Z]{2})(?P<yy>\d{2})(?P<mm>\d{2})(?:[A-Z])?\.DBC$", re.I)
SP_EXTRA_DIMENSIONS = (("SP_NAIH","AIH"),("SP_PF_DOC","CNS do profissional"))
JOB_WRITE_LOCK = threading.Lock()
ATOMIC_JOB_WRITE_LOCK = threading.RLock()
SLOW_FALLBACK_LIMIT = 8 * 1024 * 1024
# Bases DBC estaduais podem levar vários minutos para decodificar. O limite
# anterior de dois minutos encerrava conversões válidas no Windows.
NATIVE_TIMEOUT_SECONDS = 3600

def dbf_reader():
    import sys
    sys.path.insert(0, str(VENDOR))
    from dbfread import DBF
    return DBF

def safe_file(relative: str) -> Path:
    if not isinstance(relative, str) or "\x00" in relative:
        raise ValueError("Arquivo inválido.")
    path = (UPLOADS / relative.replace("\\", "/")).resolve()
    if not path.is_relative_to(UPLOADS) or path.suffix.lower() != ".dbc" or not path.is_file():
        raise ValueError("O arquivo não existe na biblioteca ou o caminho é inválido.")
    return path

def safe_dbf(relative: str) -> Path:
    if not isinstance(relative,str) or "\x00" in relative: raise ValueError("Arquivo DBF inválido.")
    path=(UPLOADS/relative.replace("\\","/")).resolve()
    if not path.is_relative_to(UPLOADS) or path.suffix.lower()!=".dbf" or not path.is_file() or "CONVERTIDOS" not in path.parts:
        raise ValueError("O DBF convertido não existe na biblioteca.")
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

def iter_dbf_fields(path: Path, names: list[str], with_index: bool=False, pre_filter: tuple[str,str] | None=None, processed_counter: list[int] | None=None, scan_callback=None):
    count,header_len,record_len,fields=dbf_layout(path)
    ordered=list(dict.fromkeys(name.upper() for name in names))
    missing=[name for name in ordered if name not in fields]
    if missing: raise ValueError("Campo não encontrado no DBF: "+", ".join(missing))
    slices=[(fields[name]["offset"],fields[name]["length"]) for name in ordered]
    filter_slice=None
    filter_value=b""
    if pre_filter:
        filter_name,filter_text=pre_filter
        if filter_name.upper() not in fields: raise ValueError("Campo de filtro não encontrado no DBF.")
        filter_slice=(fields[filter_name.upper()]["offset"],fields[filter_name.upper()]["length"])
        filter_value=filter_text.encode("ascii")
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
                if filter_slice is not None:
                    offset,length=filter_slice
                    if mapped[start+offset:start+offset+length].strip(b" \x00").lstrip(b"0")!=filter_value: continue
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
    files=[]; manifest={}; active_jobs={}
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
                if source and source not in active_jobs and state.get("status") in {"queued","running"} and time.time()-statefile.stat().st_mtime < 20:
                    active_jobs[source]={"id":state.get("id"),"status":state.get("status"),"progress":state.get("progress",1),"stage":state.get("stage","Leitura em andamento"),"bytes_written":state.get("bytes_written",0),"temporary_path":state.get("temporary_path"),"converter":state.get("converter")}
            except Exception: pass
    for p in UPLOADS.glob("**/*.dbc"):
        try:
            sysname,kind,m=meta(p); rel=p.relative_to(UPLOADS).as_posix(); info=manifest.get(rel,{})
            converted=converted_relative(rel)
            dbf=UPLOADS/converted
            dbf_exists=dbf.is_file(); dbf_stat=dbf.stat() if dbf_exists else None
            source_stat=p.stat()
            files.append({"path":rel,"name":p.name,"system":sysname,"kind":kind,"uf":m.group("uf").upper(),"year":2000+int(m.group("yy")),"month":int(m.group("mm")),"size":source_stat.st_size,"mtime_ns":source_stat.st_mtime_ns,"downloaded_at":info.get("downloaded_at"),"converted":dbf_exists,"dbf_path":converted if dbf_exists else None,"dbf_size":dbf_stat.st_size if dbf_stat else None,"dbf_mtime_ns":dbf_stat.st_mtime_ns if dbf_stat else None,"conversion":active_jobs.get(rel)})
        except Exception: continue
    files.sort(key=lambda x:(x["system"],-x["year"],-x["month"],x["name"]))
    return {"ok":True,"files":files,"library_root":str(UPLOADS)}

def delete_library_file(payload: dict[str,Any]):
    source=safe_file(payload.get("path",""))
    relative=source.relative_to(UPLOADS).as_posix()
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
                if state.get("source_path")==relative and state.get("status") in {"queued","running"} and time.time()-statefile.stat().st_mtime<20:
                    raise ValueError("Este arquivo está sendo preparado para leitura. Aguarde a conclusão antes de removê-lo.")
        tabulation_jobs=jobs/"tabulations"
        if tabulation_jobs.is_dir():
            for statefile in tabulation_jobs.glob("*.json"):
                try:
                    state=read_job_state(statefile)
                except Exception:
                    pass
                else:
                    if state.get("status") not in {"queued","running"} or time.time()-statefile.stat().st_mtime>=300:
                        continue
                    data=state.get("payload") or {}
                    selected={str(data.get("path") or "").replace("\\","/")}
                    selected.update(str(item.get("path") or "").replace("\\","/") for item in data.get("sources",[]) if isinstance(item,dict))
                    if relative in selected:
                        raise ValueError("Este arquivo está sendo usado por uma tabulação em andamento. Aguarde a conclusão antes de removê-lo.")

    converted=UPLOADS/converted_relative(relative)
    if not converted.resolve().is_relative_to(UPLOADS):
        raise ValueError("O caminho do arquivo convertido é inválido.")
    source.unlink()
    converted.unlink(missing_ok=True)
    for partial in converted.parent.glob(converted.name+".*.part"):
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass

    manifest=UPLOADS/"manifest.json"
    try:
        items=json.loads(manifest.read_text(encoding="utf-8"))
        if isinstance(items,list):
            retained=[item for item in items if not isinstance(item,dict) or str(item.get("path") or "").replace("\\","/")!=relative]
            if len(retained)!=len(items):
                fd,temporary=tempfile.mkstemp(prefix="manifest-",suffix=".json.part",dir=str(UPLOADS))
                try:
                    with os.fdopen(fd,"w",encoding="utf-8") as stream:
                        stream.write(json.dumps(retained,ensure_ascii=False,indent=2)+"\n")
                    os.replace(temporary,manifest)
                finally:
                    Path(temporary).unlink(missing_ok=True)
    except (OSError,json.JSONDecodeError):
        pass

    # The client already has the current library list and removes this item locally.
    # Rebuilding the catalog here recursively walks every DBC and stats every DBF,
    # making a simple file deletion wait on unrelated bases.
    return {"ok":True,"deleted":{"path":relative,"name":source.name}}

def converted_relative(source_relative: str) -> str:
    rel=Path(source_relative)
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
    source=safe_file(source_relative); system,kind,_=meta(source); fields,records=dbc_header(source)
    expected=32+32*len(fields)+1+records*(1+sum(f["length"] for f in fields))+1
    target=UPLOADS/converted_relative(source_relative); target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_file() and target.stat().st_size==expected:
        return {"ok":True,"done":True,"progress":100,"dbf_path":target.relative_to(UPLOADS).as_posix(),"dbfIdentity":cache_file_identity(target),"message":"A leitura desta base já está preparada."}
    jobs=UPLOADS/".jobs"
    if jobs.exists():
        for statefile in jobs.glob("*.json"):
            try:
                active=read_job_state(statefile)
                if active.get("source_path")==source_relative and active.get("status") in {"queued","running"}:
                    if time.time()-statefile.stat().st_mtime < 20:
                        return {"ok":True,"done":False,"job_id":active["id"],"progress":active.get("progress",1),"stage":active.get("stage","Conversão em andamento")}
                    active.update(status="error",stage="Leitura interrompida",message="A leitura anterior parou de atualizar. Inicie novamente para continuar.")
                    write_job(active["id"],active)
            except Exception: pass
    job_id=secrets.token_hex(16)
    dbf_relative=converted_relative(source_relative)
    temporary_relative=dbf_relative+f".{job_id}.part"
    write_job(job_id,{"id":job_id,"status":"queued","progress":1,"stage":"Preparando a leitura","message":"A base entrou na fila de leitura.","source_path":source_relative,"expected_size":expected,"dbf_path":dbf_relative,"temporary_path":temporary_relative})
    command=[sys.executable,str(Path(__file__).resolve()),"--worker",job_id]
    flags=getattr(subprocess,"DETACHED_PROCESS",0x00000008)|getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0x00000200) if os.name=="nt" else 0
    subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags,start_new_session=os.name!="nt",cwd=str(ROOT))
    return {"ok":True,"done":False,"job_id":job_id,"progress":1,"stage":"Preparando a leitura"}

def conversion_status(job_id: str):
    path=jobfile(job_id)
    if not path.is_file(): raise ValueError("Conversão não encontrada.")
    state=read_job_state(path)
    if state.get("status") in {"queued","running"} and time.time()-path.stat().st_mtime >= 20:
        state.update(status="error",stage="Leitura interrompida",message="A preparação da leitura parou de atualizar. Tente iniciar novamente.")
        write_job(job_id,state)
    return {"ok":True,**state}

def run_conversion_worker(job_id: str):
    state=read_job_state(jobfile(job_id)); source_rel=state["source_path"]
    source=safe_file(source_rel); target=UPLOADS/converted_relative(source_rel); target.parent.mkdir(parents=True,exist_ok=True)
    temporary_output=target.with_name(target.name+f".{job_id}.part")
    try:
        state.update(status="running",stage="Preparando a leitura do DBC",progress=2,message="A leitura da base está em andamento."); write_job(job_id,state)
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
    if len(json.dumps(payload,ensure_ascii=True))>100000: raise ValueError("A configuração da tabulação é grande demais.")
    request_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=True,separators=(",",":")).encode("utf-8")).hexdigest()
    folder=UPLOADS/".jobs"/"tabulations"
    folder.mkdir(parents=True,exist_ok=True)
    for existing in folder.glob("*.json"):
        try:
            state=read_job_state(existing)
            if state.get("request_hash")!=request_hash or state.get("status") not in {"queued","running"}:
                continue
            if time.time()-existing.stat().st_mtime<300:
                return {"ok":True,"job_id":state["id"],"status":state["status"],"progress":state.get("progress",1),"stage":state.get("stage","Tabulação em andamento"),"reused":True}
        except (OSError,ValueError,TypeError,KeyError):
            continue
    job_id=secrets.token_hex(16)
    write_tabulation_job(job_id,{"id":job_id,"request_hash":request_hash,"status":"queued","progress":1,"stage":"Preparando tabulação","payload":payload})
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
    if state.get("status") in {"queued","running"} and time.time()-path.stat().st_mtime>300:
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
    path=tabulation_jobfile(job_id)
    state=read_job_state(path)
    payload=state.pop("payload")
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

def relation_mapping(system: str, option):
    relation=(option or {}).get("relation","")
    if not relation: return {}
    rel=PurePosixPath(relation.replace("\\","/"))
    if rel.is_absolute() or ".." in rel.parts: return {}
    archive=UPLOADS/"DEFINICOES"/"originais"/f"TAB_{system}.zip"
    target=cache_target("relation-mappings",{"archive":cache_file_identity(archive),"relation":relation.lower(),"descField":(option or {}).get("descField","")})
    cached=cache_read(target)
    if isinstance(cached,dict) and isinstance(cached.get("mapping"),dict): return cached["mapping"]
    with zipfile.ZipFile(archive) as z:
        member=next((n for n in z.namelist() if PurePosixPath(n).as_posix().lower()==rel.as_posix().lower()),None)
        if member is None: member=next((n for n in z.namelist() if PurePosixPath(n).name.lower()==rel.name.lower()),None)
        if member is None: return {}
        if PurePosixPath(member).is_absolute() or ".." in PurePosixPath(member).parts: return {}
        raw=z.read(member)
    out=UPLOADS/"DEFINICOES"/system/"referencias"/Path(*PurePosixPath(member).parts)
    out.parent.mkdir(parents=True,exist_ok=True)
    if not out.is_file() or out.stat().st_size!=len(raw): out.write_bytes(raw)
    if rel.suffix.lower()==".cnv":
        mapping=cnv_values(raw)
        cache_write(target,{"mapping":mapping},max_bytes=20_000_000)
        return mapping
    if rel.suffix.lower()==".dbf":
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
    path=safe_file(relative); system,kind,filename_match=meta(path); fields,records=dbc_header(path)
    converted=UPLOADS/converted_relative(relative)
    dbf_identity=cache_file_identity(converted) if converted.is_file() else None
    defname,definition=archive_def(system,kind)
    if definition is None: raise RuntimeError(f"A definição {defname or 'do arquivo'} não foi encontrada no pacote oficial {system}.")
    rows,cols,selections,increments,group=parse_def(definition,fields)
    add_sp_identifier_options(kind,[f["name"] for f in fields],rows)
    relationFiles={item.get("relation", "").lower() for collection in (rows,cols,selections,increments) for item in collection if item.get("relation", "").lower().endswith(".cnv")}
    fieldnames={f["name"].upper() for f in fields}
    municipality=municipality_field(system,fieldnames)
    return {"ok":True,"file":{"path":relative,"name":path.name,"system":system,"kind":kind,"uf":filename_match.group("uf").upper()},"dbfPath":dbf_identity["path"] if dbf_identity else None,"dbfIdentity":dbf_identity,"sourceIdentity":cache_file_identity(path),"definition":{"name":defname,"archive":f"uploads/DEFINICOES/originais/TAB_{system}.zip","size":len(definition),"relationFiles":len(relationFiles)},"fields":fields,"lineOptions":rows,"columnOptions":cols,"selectionOptions":selections,"increments":increments,"groupField":group,"municipalityField":municipality,"recordCount":records}

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
        if changed:
            try: write_preset_store(data)
            except OSError: pass
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
        path=safe_dbf(entry.get("dbfPath") or converted_relative(relative))
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

def tabulate(payload, progress=None):
    if progress: progress(2,"Conferindo os arquivos e as opções")
    raw_sources=payload.get("sources")
    if not isinstance(raw_sources,list) or not raw_sources:
        relative=payload.get("path",""); raw_sources=[{"path":relative,"dbfPath":payload.get("dbfPath") or converted_relative(relative)}]
    if len(raw_sources)>50: raise ValueError("É possível tabular até 50 arquivos na mesma execução.")
    sources=[]
    for item in raw_sources:
        if not isinstance(item,dict): raise ValueError("A lista de arquivos é inválida.")
        source=safe_file(item.get("path","")); system,kind,filename_match=meta(source); uf=filename_match.group("uf").upper(); dbf=safe_dbf(item.get("dbfPath") or converted_relative(item.get("path","")))
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
