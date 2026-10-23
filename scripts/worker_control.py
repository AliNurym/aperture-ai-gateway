"""Read worker activity or drain/resume admissions without exposing its token."""
import argparse
import ipaddress
import json
import os
import platform
import sys
from pathlib import Path
from urllib.parse import urlsplit

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def secure_gateway(url):
    try:
        parsed = urlsplit(url)
        parsed.port
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        if parsed.scheme == 'https':
            return True
        if parsed.scheme != 'http':
            return False
        return parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'drain', 'resume'])
    parser.add_argument('--credential-file', type=Path, help='Local preview worker-access.json; never a signing key')
    parser.add_argument('--gateway')
    parser.add_argument('--node-id')
    args = parser.parse_args()
    if args.credential_file:
        config = json.loads(args.credential_file.read_text(encoding='utf-8'))
    else:
        env = {**dotenv_values(ROOT / 'backend' / '.worker.env'), **os.environ}
        config = {'gateway_url': env.get('GATEWAY_API_URL', 'http://127.0.0.1:8000'),
                  'worker_id': env.get('APERTURE_NODE_ID', platform.node()),
                  'worker_token': env.get('APERTURE_WORKER_TOKEN', '')}
    url = (args.gateway or config['gateway_url']).rstrip('/')
    if not secure_gateway(url):
        raise ValueError('Use an HTTPS gateway or a loopback HTTP address.')
    token = config.get('worker_token')
    if not isinstance(token, str) or len(token) < 16:
        raise ValueError('Configure this worker credential in backend/.worker.env or use --credential-file.')
    headers = {'X-Aperture-Worker-Id': args.node_id or config['worker_id'], 'X-Aperture-Worker-Token': token}
    if args.action == 'status':
        response = requests.get(url + '/workers/me', headers=headers, timeout=15, allow_redirects=False)
    else:
        response = requests.post(url + '/workers/me/mode', headers=headers,
            json={'accepting_tasks': args.action == 'resume'}, timeout=15, allow_redirects=False)
    if response.status_code >= 300:
        raise ValueError(f'Worker operation rejected (HTTP {response.status_code}). Check the worker ID and configured credential.')
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, requests.RequestException) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
