#!/usr/bin/env python3
"""Remote CLI: invoke the authoritative paper command on the ledger server through SSH.

No HTTP token or Python dependency needed. Use an existing SSH alias/key.
  export PAPER_SSH_HOST=my-ledger-server            # SSH 别名（或每次 --host）
  export PAPER_REMOTE_CMD=/srv/paper-desk/ledger/bin/paper   # 远端 paper 命令；默认 paper（需在远端 PATH 里）
  python paper_remote.py --help
  python paper_remote.py --json watch --days 30
  python paper_remote.py upload P02 ./source.zip --kind latex --seq 3
  python paper_remote.py download P02 --latest --kind latex --out ./latest.zip
  python paper_remote.py credentials set P02 --from-json ./private.json
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

REMOTE_CMD = os.environ.get('PAPER_REMOTE_CMD', 'paper')


def ssh(host,args,input_data=None):
    r=subprocess.run(['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=15',host,shlex.join(args)],
                     input=input_data,stdin=subprocess.DEVNULL if input_data is None else None,
                     stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=360)
    if r.returncode:
        sys.stderr.buffer.write(r.stderr)
        raise RuntimeError(f'SSH/远端命令失败，退出码 {r.returncode}')
    return r.stdout


def scp(source,target):
    r=subprocess.run(['scp','-B','-o','ConnectTimeout=15',source,target],stdin=subprocess.DEVNULL,timeout=360)
    if r.returncode:raise RuntimeError(f'SCP 失败，退出码 {r.returncode}')


def read(path):return sys.stdin.buffer.read() if path=='-' else Path(path).read_bytes()


def run(host,args):
    command=next((x for x in args if x!='--json'),None)
    if not command:raise ValueError('缺少 paper 子命令')
    argv=list(args);payload=None
    secrets_body={};body_seen=False
    for flag,field in [('--from-json',None),('--password-file','sys_password'),('--cookie-file','sys_cookie'),('--extra-file','extra')]:
        if flag in argv:
            i=argv.index(flag);path=argv[i+1]
            raw=read(path)
            if field is None:
                value=json.loads(raw)
                if not isinstance(value,dict):raise ValueError('JSON 必须为对象')
                secrets_body.update(value)
            elif field=='extra':secrets_body[field]=json.loads(raw)
            else:secrets_body[field]=raw.decode('utf-8-sig').rstrip('\r\n')
            del argv[i:i+2];body_seen=True
    if body_seen:
        payload=json.dumps(secrets_body,ensure_ascii=False).encode('utf-8');argv.extend(['--from-json','-'])
    if '--text-file' in argv:
        if payload is not None:raise ValueError('正文和凭证不能同时占用 stdin')
        i=argv.index('--text-file');payload=read(argv[i+1]);argv[i+1]='-'
    if command=='upload':
        i=argv.index('upload');source=Path(argv[i+2]).resolve()
        if not source.is_file():raise ValueError('本地上传文件不存在')
        folder=ssh(host,['mktemp','-d','/tmp/paper-remote-XXXXXXXX']).decode().strip()
        remote=folder+'/'+source.name
        try:
            scp(str(source),host+':'+remote)
            argv[i+2]=remote
            sys.stdout.buffer.write(ssh(host,[REMOTE_CMD]+argv,payload))
        finally:ssh(host,['rm','-rf','--',folder])
        return
    output=None
    if '--out' in argv:
        i=argv.index('--out');output=Path(argv[i+1]).resolve()
        if output.exists() and '--force' not in argv:raise FileExistsError('本地目标已存在')
        if command=='download':
            folder=ssh(host,['mktemp','-d','/tmp/paper-remote-XXXXXXXX']).decode().strip()
            remote=folder+'/download'
            argv[i+1]=remote
            fd,tmp=tempfile.mkstemp(prefix='.paper-remote-',dir=output.parent);os.close(fd)
            try:
                result=json.loads(ssh(host,[REMOTE_CMD]+argv,payload))
                scp(host+':'+remote,tmp)
                if '--force' in argv:os.replace(tmp,output)
                else:os.link(tmp,output);os.unlink(tmp)
                result['saved_to']=str(output);print(json.dumps(result,ensure_ascii=False))
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
                ssh(host,['rm','-rf','--',folder])
            return
        del argv[i:i+2]
    raw=ssh(host,[REMOTE_CMD]+argv,payload)
    if output:
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw)
        print(json.dumps({'ok':True,'saved_to':str(output)},ensure_ascii=False))
    else:sys.stdout.buffer.write(raw)


def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--host',default=os.environ.get('PAPER_SSH_HOST'),help='SSH 别名；默认取 PAPER_SSH_HOST')
    p.add_argument('paper_args',nargs=argparse.REMAINDER)
    # Keep --json and all paper-specific flags untouched.
    args=sys.argv[1:];host=os.environ.get('PAPER_SSH_HOST','')
    if args[:1]==['--host']:
        if len(args)<2:p.error('--host 需要 SSH 别名')
        host=args[1];args=args[2:]
    if not args or args==['--help']:p.print_help();return
    if not host:p.error('没有 SSH 主机：用 --host 或环境变量 PAPER_SSH_HOST')
    try:run(host,args)
    except (OSError,ValueError,RuntimeError,IndexError,subprocess.TimeoutExpired) as e:
        print('paper-remote: '+str(e),file=sys.stderr);sys.exit(1)

if __name__=='__main__':main()
