#!/usr/bin/env python3
"""Install and select the isolated ACT4 toolchain."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'out/deps/act4-tools'
CHECKOUT = ROOT / 'out/deps/riscv-arch-test-4.0.0'
SAIL = ROOT / 'out/deps/sail-riscv-0.10/bin/sail_riscv_sim'


def environment(checkout=CHECKOUT, sail=SAIL):
    lock = json.loads((ROOT/'config/act4.lock').read_text())['tools']
    ruby = TOOLS / f'mise-data/installs/ruby/{lock["ruby"]}/bin'
    uv = TOOLS / f'mise-data/installs/uv/{lock["uv"]}/uv-x86_64-unknown-linux-gnu'
    env = os.environ.copy()
    env.update({
        'PATH': os.pathsep.join(map(str, [TOOLS/'gcc/riscv/bin', ruby, uv, TOOLS/'mise/mise/bin', TOOLS/'bundle/ruby/3.4.0/bin', sail.parent])) + os.pathsep + env['PATH'],
        'MISE_DATA_DIR': str(TOOLS/'mise-data'), 'MISE_CACHE_DIR': str(TOOLS/'mise-cache'),
        'MISE_CONFIG_DIR': str(TOOLS/'mise-config'), 'MISE_RUBY_COMPILE': 'false',
        'BUNDLE_GEMFILE': str(checkout/'framework/src/act/data/Gemfile'),
        'BUNDLE_PATH': str(TOOLS/'bundle'), 'BUNDLE_FROZEN': 'true',
        'BUNDLE_DISABLE_SHARED_GEMS': 'true',
        'UV_PROJECT_ENVIRONMENT': str(TOOLS/'python'), 'UV_CACHE_DIR': str(TOOLS/'uv-cache'),
        'UV_PYTHON_INSTALL_DIR': str(TOOLS/'python-installs'),
        'XDG_DATA_HOME': str(TOOLS/'data'), 'XDG_CACHE_HOME': str(TOOLS/'cache'),
    })
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkout', type=Path, default=CHECKOUT)
    args = parser.parse_args()
    from check_act4 import check_harness, check_upstream
    lock, suite = check_harness()
    checkout = args.checkout.resolve()
    check_upstream(checkout, lock, suite)
    TOOLS.mkdir(parents=True, exist_ok=True)
    for asset in json.loads((ROOT/'config/act4_tools.lock').read_text())['assets']:
        archive = TOOLS / asset['url'].rsplit('/', 1)[1]
        if not archive.exists():
            temporary = archive.with_suffix(archive.suffix+'.part')
            urllib.request.urlretrieve(asset['url'], temporary)
            temporary.rename(archive)
        with archive.open('rb') as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024*1024), b''): digest.update(block)
        if digest.hexdigest() != asset['sha256']: raise ValueError(f'archive checksum mismatch: {archive}')
        destination = TOOLS / asset['name']
        marker = destination / '.archive-sha256'
        if not marker.exists() or marker.read_text().strip() != asset['sha256']:
            with tarfile.open(archive) as contents: contents.extractall(destination, filter='data')
            marker.write_text(asset['sha256']+'\n')
    env = environment(checkout)
    def run(*command): subprocess.run(command, cwd=checkout, env=env, check=True)
    run(str(TOOLS/'mise/mise/bin/mise'), 'trust', str(checkout/'.mise.toml'))
    run(str(TOOLS/'mise/mise/bin/mise'), 'install', f'ruby@{lock["tools"]["ruby"]}', f'uv@{lock["tools"]["uv"]}')
    run('uv', 'sync', '--frozen', '--all-packages', '--no-dev')
    run('bundle', 'install', '--jobs', '2')
    run('bundle', 'exec', 'udb', 'version')
    print('ACT4 tools installed under out/deps/act4-tools')


if __name__ == '__main__':
    main()
