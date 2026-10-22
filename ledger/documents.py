"""Bounded, read-only paper inspection. Never execute TeX or extract archives."""
import io
import posixpath
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path
from fastapi import HTTPException

MAX_TEXT = 8 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
TEXT_SUFFIXES = {'.tex','.bib','.md','.txt'}


def safe_member(name):
    name = name.replace('\\','/')
    if name.startswith('/') or '..' in name.split('/') or ':' in name:
        raise HTTPException(422, '压缩包包含不安全路径')
    return name


def sources(path, original):
    suffix = Path(original).suffix.lower()
    out = {}
    total = 0
    def add(name, size, read):
        nonlocal total
        safe_member(name)
        if Path(name).suffix.lower() not in TEXT_SUFFIXES:return
        if size>MAX_TEXT or total+size>MAX_TOTAL:raise HTTPException(413,'正文解压大小超过检查上限')
        data = read(MAX_TEXT+1)
        if len(data)>MAX_TEXT:raise HTTPException(413,'正文过大')
        total += len(data)
        try:out[name]=data.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:out[name]=data.decode('gb18030')
            except UnicodeDecodeError:raise HTTPException(422,'正文编码需 UTF-8 或 GB18030')
    if suffix in TEXT_SUFFIXES:
        with open(path,'rb') as f:add(original,Path(path).stat().st_size,f.read)
    elif suffix=='.zip':
        try:
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    safe_member(info.filename)
                    if info.is_dir():continue
                    if (info.external_attr >>16)&0o170000 == 0o120000:raise HTTPException(422,'压缩包不支持符号链接')
                    if Path(info.filename).suffix.lower() in TEXT_SUFFIXES:
                        with z.open(info) as f:add(info.filename,info.file_size,f.read)
        except (zipfile.BadZipFile,RuntimeError):raise HTTPException(422,'ZIP 损坏或加密，无法读取正文')
    elif suffix in ('.tar','.gz','.tgz','.bz2','.xz'):
        try:
            with tarfile.open(path) as t:
                for info in t:
                    safe_member(info.name)
                    if info.issym() or info.islnk():raise HTTPException(422,'压缩包不支持链接')
                    if info.isfile() and Path(info.name).suffix.lower() in TEXT_SUFFIXES:
                        with t.extractfile(info) as f:add(info.name,info.size,f.read)
        except tarfile.TarError:raise HTTPException(422,'TAR 压缩包无法读取')
    elif suffix=='.pdf':
        try:
            # Limit output pages; temporary stdout is bounded after conversion.
            r=subprocess.run(['pdftotext','-f','1','-l','200',str(path),'-'],capture_output=True,timeout=20)
        except (OSError,subprocess.TimeoutExpired):raise HTTPException(422,'PDF 转文字不可用或超时')
        if r.returncode:raise HTTPException(422,'PDF 无法转文字')
        add(original+'.txt',len(r.stdout),io.BytesIO(r.stdout).read)
    else:raise HTTPException(422,'正文检查支持 tex/txt/md/pdf/zip/tar.gz；7z 请先转 ZIP，原包仍可下载')
    if not out:raise HTTPException(422,'附件中未找到可读取正文')
    return out


def inspect(path, original, member='', all_text=False):
    docs=sources(path,original)
    if member and member not in docs:raise HTTPException(404,'没有该正文成员；使用 files text 查看 members')
    candidates=[n for n in docs if n.endswith('.tex')]
    main=member or next((n for n in candidates if '\\documentclass' in docs[n]),None) or next(iter(docs))
    visited=set(); missing=[]
    def resolve(n):
        if n in visited:return ''
        visited.add(n)
        text=docs[n]
        def include(m):
            target=posixpath.normpath(posixpath.join(posixpath.dirname(n),m.group(1)))
            if not target.endswith('.tex'):target+='.tex'
            if target not in docs:missing.append(target);return m.group(0)
            return '\n'+resolve(target)+'\n'
        return re.sub(r'\\(?:input|include)\s*\{([^}]+)\}',include,text)
    text='\n\n'.join('%% '+n+'\n'+t for n,t in docs.items()) if all_text else resolve(main)
    text=re.sub(r'(?<!\\)%[^\n]*','',text)
    cited={k.strip() for m in re.finditer(r'\\(?:cite\w*|[Cc]ite\w*)\*?(?:\[[^\]]*\])*\{([^}]+)\}',text) for k in m.group(1).split(',')}
    bib='\n'.join(docs.values())
    keys=set(re.findall(r'@\w+\s*\{\s*([^,\s]+)',bib))|set(re.findall(r'\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}',bib))
    labels=set(re.findall(r'\\label\{([^}]+)\}',text))
    refs=set(re.findall(r'\\(?:ref|eqref|autoref|pageref)\{([^}]+)\}',text))
    return dict(member=main,members=list(docs),text=text,
                checks=dict(characters=len(text),sections=re.findall(r'\\(?:sub)*section\*?\{([^}]+)\}',text),
                            missing_inputs=sorted(set(missing)),undefined_references=sorted(refs-labels),
                            unresolved_citations=sorted(cited-keys),bibliography_keys=len(keys),
                            note='静态正文检查，不编译 TeX；宏生成的引用需人工核验。'))
