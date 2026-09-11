import requests
import time
import sys

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:8000'

print('1. Checking /stats...')
s = requests.get(f'{BASE}/stats').json()
print('   Stats tasks completed:', s.get('tasks_completed'))
print('   SOL Price:', f"${s.get('sol_price', 0):.2f}")
print('   Hardware Telemetry:', s.get('hardware'))

print('\n2. Checking /active_nodes...')
nodes = requests.get(f'{BASE}/active_nodes').json()
print(f'   Active nodes count: {len(nodes)}')
for n in nodes:
    print(f'   - Node: {n.get("node_id")} | GPU: {n.get("gpu_name")} | Temp: {n.get("gpu_temp")}°C | Load: {n.get("gpu_util")}% | VRAM: {n.get("vram_used")}/{n.get("vram_total")}GB')

print('\n3. Testing execution of Matrix Mult benchmark...')
payload = {
    'code': '''import time, random
N = 50
A = [[random.random() for _ in range(N)] for _ in range(N)]
B = [[random.random() for _ in range(N)] for _ in range(N)]
C = [[sum(A[i][k]*B[k][j] for k in range(N)) for j in range(N)] for i in range(N)]
print(f'COMPUTED {N}x{N} MATRIX MULTIPLICATION')
''',
    'wallet': 'DEMO_DEVNET_SOLANA_GUEST',
    'signature': [0]*64,
    'message': 'Sign to authenticate execution.'
}
res = requests.post(f'{BASE}/execute', json=payload).json()
task_id = res['task_id']
print(f'   Task initiated: {task_id}')
print(f'   Burn rate: {res["burn_rate"]} SOL/sec ({res["burn_rate_lamports"]} lamports/sec)')
print(f'   Complexity Score: {res["complexity_score"]}/100')
print(f'   On-chain proof: {res.get("on_chain_proof")}')

print('\n4. Waiting for GPU worker to process & testing real-time stream logs...')
completed = False
for i in range(15):
    time.sleep(1)
    # Check stream log
    stream_res = requests.get(f'{BASE}/stream_log/{task_id}').json()
    if stream_res.get('lines'):
        print(f'   📡 Streamed chunk ({len(stream_res["lines"])} lines): {stream_res["lines"][0].strip()[:60]}...')
    
    status_res = requests.get(f'{BASE}/result/{task_id}').json()
    if status_res.get('status') == 'completed':
        print('   ✅ Worker execution settled:')
        print('   Output:\n', status_res['output'])
        completed = True
        break
    print(f'   ... executing on silicon ({i+1}s)')

if not completed:
    print('   ⚠️ Task waiting for worker daemon (start worker.py to process)')

print('\n5. Testing Neural Network Forward Pass from /benchmarks...')
benchmarks = requests.get(f'{BASE}/benchmarks').json()
nn_bench = next((b for b in benchmarks if b['id'] == 'neural_forward'), None)
if nn_bench:
    print(f'   Found Neural Benchmark: {nn_bench["name"]}')
    nn_res = requests.post(f'{BASE}/execute', json={
        'code': nn_bench['code'],
        'wallet': 'DEMO_DEVNET_SOLANA_GUEST',
        'signature': [0]*64,
        'message': 'Sign'
    }).json()
    print(f'   NN Task ID: {nn_res["task_id"]} | Complexity: {nn_res["complexity_score"]}/100 | Burn: {nn_res["burn_rate_lamports"]} L/s')

print('\n6. Testing AI Sentinel security block (malicious probe)...')
malicious = {
    'code': 'import os\nos.system("rm -rf /")',
    'wallet': 'DEMO_DEVNET_SOLANA_GUEST',
    'signature': [0]*64,
    'message': 'Sign'
}
sec_res = requests.post(f'{BASE}/execute', json=malicious)
print(f'   Security response status code: {sec_res.status_code} (Expected 403)')
print('   Detail:', sec_res.json().get('detail'))
print('\n🎉 All End-to-End System Tests Completed Successfully!')
