"""Download exact model inputs, verify streaming SHA-256, publish atomically."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): value.update(chunk)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',default='models.lock.json')
    parser.add_argument('--model',choices=['qwen','whisper'],required=True)
    parser.add_argument('--directory',required=True)
    args=parser.parse_args()
    model=json.loads(Path(args.manifest).read_text())[args.model]
    target=Path(args.directory); target.mkdir(parents=True,exist_ok=True)
    for filename,checksum in model['files'].items():
        if Path(filename).name != filename or len(checksum)!=64:
            raise ValueError('Invalid model manifest')
        file=target/filename
        if file.exists() and digest(file)==checksum: continue
        temporary=target/(filename+'.partial')
        url=f"https://huggingface.co/{model['repository']}/resolve/{model['revision']}/{filename}"
        with urllib.request.urlopen(url,timeout=60) as source, temporary.open('wb') as output:
            for chunk in iter(lambda:source.read(1024*1024),b''): output.write(chunk)
        if digest(temporary)!=checksum:
            temporary.unlink(); raise ValueError(f'Checksum mismatch: {filename}')
        os.replace(temporary,file)
    print('verified',args.model,model['revision'])


if __name__=='__main__': main()
