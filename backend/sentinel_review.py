"""Validate optional Gemini review provenance before issuing a compute quote."""
import json
import re
from pathlib import Path

from fastapi import HTTPException

from agent_identity import sha256_text

PROMPT_PREFIX = json.loads((Path(__file__).parent / 'workloads' / 'sentinel_review.json').read_text(encoding='utf-8'))['prefix']


def validate_sentinel_review(store, manifest, owner, source):
    if not manifest or 'aperture_review' not in manifest['parameters']:
        return
    reference = manifest['parameters']['aperture_review']
    if (manifest['runtime'] != 'python' or not isinstance(reference, dict)
            or set(reference) != {'task_id', 'source_sha256', 'receipt_sha256'}
            or not isinstance(reference['task_id'], str)
            or not re.fullmatch(r'task-[0-9a-f]{32}', reference['task_id'])
            or any(not isinstance(reference[key], str) or not re.fullmatch(r'[0-9a-f]{64}', reference[key])
                   for key in ('source_sha256', 'receipt_sha256'))):
        raise HTTPException(422, 'Invalid AI Sentinel review reference.')
    review = store.get('jobs', reference['task_id']) or {}
    workload = review.get('workload') or {}
    parameters = workload.get('parameters') or {}
    receipt = review.get('receipt') or {}
    expected_messages = [{'role': 'user', 'content': PROMPT_PREFIX + json.dumps(source, ensure_ascii=False)}]
    if (reference['source_sha256'] != sha256_text(source)
            or review.get('wallet') != owner or review.get('state') != 'completed'
            or workload.get('runtime') != 'inference.chat'
            or parameters.get('offer', {}).get('protocol') != 'gemini_generate_content'
            or parameters.get('inference', {}).get('messages') != expected_messages
            or receipt.get('execution_status') != 'completed'
            or receipt.get('receipt_sha256') != reference['receipt_sha256']):
        raise HTTPException(409, 'A completed Gemini review matching this owner and source is unavailable. Request a fresh review.')
