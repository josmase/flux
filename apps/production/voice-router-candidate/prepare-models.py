"""Download exact model inputs, verify streaming SHA-256, publish atomically."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): value.update(chunk)
    return value.hexdigest()


def prepare_model(model, target, remove_after_verify=None):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for filename, checksum in model['files'].items():
        if Path(filename).name != filename or len(checksum) != 64:
            raise ValueError('Invalid model manifest')
        file = target / filename
        if file.exists() and digest(file) == checksum:
            continue
        temporary = target / (filename + '.partial')
        url = f"https://huggingface.co/{model['repository']}/resolve/{model['revision']}/{filename}"
        with urllib.request.urlopen(url, timeout=60) as source, temporary.open('wb') as output:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                output.write(chunk)
        if digest(temporary) != checksum:
            temporary.unlink()
            raise ValueError(f'Checksum mismatch: {filename}')
        os.replace(temporary, file)

    # Confirm the entire target before retiring any previous model. Restrict
    # cleanup to the known sibling migration path on the shared model volume.
    for filename, checksum in model['files'].items():
        if not (target / filename).is_file() or digest(target / filename) != checksum:
            raise ValueError(f'Model verification failed: {filename}')

    if remove_after_verify is not None:
        previous = Path(remove_after_verify)
        if (target.name != 'large-v3-turbo-pinned'
                or previous.name != 'medium-pinned'
                or target.resolve().parent != previous.resolve().parent):
            raise ValueError('Refusing to remove an unexpected model directory')
        if previous.is_symlink():
            raise ValueError('Refusing to remove a symlinked model directory')
        if previous.exists():
            shutil.rmtree(previous)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',default='models.lock.json')
    parser.add_argument('--model',choices=['qwen','whisper'],required=True)
    parser.add_argument('--directory',required=True)
    parser.add_argument('--remove-after-verify')
    args=parser.parse_args()
    model=json.loads(Path(args.manifest).read_text())[args.model]
    prepare_model(model, args.directory, args.remove_after_verify)
    print('verified',args.model,model['revision'])


if __name__=='__main__': main()
