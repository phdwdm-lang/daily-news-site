#!/usr/bin/env python3
"""Fetch selected public images, retain provenance, and reuse verified identity assets."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
from urllib.request import Request, urlopen
from daily_site import DEFAULT_ASSETS_ROOT, ValidationError, image_size, source_url, site_lock, write_file, canonical


def fetch_asset(url, identity, source, root=DEFAULT_ASSETS_ROOT, refresh=False):
    source_url(url,'image URL');source_url(source,'source page')
    root=Path(root);index_file=root/'asset-index.json'
    with site_lock(root):
        index=json.loads(index_file.read_text()) if index_file.exists() else {'schema_version':1,'items':{}}
        cached=index['items'].get(identity)
        if cached and not refresh:
            path=root/cached['path']
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==cached['sha256']:
                return {'status':'cached',**cached}
        with tempfile.TemporaryDirectory() as download:
            downloaded=Path(download)/'image.bin'
            result=subprocess.run(['curl','--fail','--location','--silent','--show-error','--max-time','25','--max-filesize','20971520','--proto','=http,https','--proto-redir','=http,https','--output',str(downloaded),'--write-out','%{url_effective}',url],capture_output=True,text=True)
            if result.returncode:raise ValidationError('图片获取失败：'+result.stderr.strip()[:180])
            payload=downloaded.read_bytes()
            if len(payload)>20*1024*1024:raise ValidationError('图片超过20MiB，停止获取')
            final_url=result.stdout
        suffix=('.png' if payload.startswith(b'\x89PNG') else '.jpg' if payload.startswith(b'\xff\xd8') else '.webp' if payload[:4]==b'RIFF' and payload[8:12]==b'WEBP' else None)
        if suffix is None:raise ValidationError('只接收实际PNG/JPEG/WebP图片，拒绝网页或未知文件')
        digest=hashlib.sha256(payload).hexdigest();relative='assets/cache/'+digest[:24]+suffix
        target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent,suffix=suffix,delete=False) as handle:
                temporary=Path(handle.name);handle.write(payload);handle.flush();os.fsync(handle.fileno())
            width,height=image_size(temporary)
            os.replace(temporary,target)
            item={'identity':identity,'source_page':source,'asset_url':url,'resolved_url':final_url,'path':relative,'width':width,'height':height,'sha256':digest,'fetched_at':datetime.now(timezone.utc).isoformat(),'visual_verified':False}
            index['items'][identity]=item
            write_file(index_file,canonical(index))
            return {'status':'fetched',**item}
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url');parser.add_argument('--identity',required=True);parser.add_argument('--source',required=True);parser.add_argument('--assets-root',type=Path,default=DEFAULT_ASSETS_ROOT);parser.add_argument('--refresh',action='store_true')
    args=parser.parse_args()
    try:print(json.dumps(fetch_asset(args.url,args.identity,args.source,args.assets_root,args.refresh),ensure_ascii=False,indent=2))
    except (OSError,ValueError) as exc:parser.exit(1,json.dumps({'status':'error','message':str(exc)},ensure_ascii=False)+'\n')


if __name__=='__main__':main()
