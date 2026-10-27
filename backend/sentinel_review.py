"""Validate optional model review provenance before issuing a compute quote."""
import json
import re
from pathlib import Path

from fastapi import HTTPException

from agent_identity import sha256_text

PROMPT_PREFIX = json.loads((Path(__file__).parent / 'workloads' / 'sentinel_review.json').read_text(encoding='utf-8'))['prefix']
SENTINEL_PROTOCOLS = {'gemini_generate_content', 'openai_chat_completions'}


def source_bound_sentinel_source(request):
    """Return the exact source carried by a fixed Sentinel prompt, if present."""
    messages = getattr(request, 'messages', None)
    if not isinstance(messages, list) or len(messages) != 1:
        return None
    message = messages[0]
    content = getattr(message, 'content', None)
    if getattr(message, 'role', None) != 'user' or not isinstance(content, str) or not content.startswith(PROMPT_PREFIX):
        return None
    try:
        source = json.loads(content[len(PROMPT_PREFIX):])
        encoded_size = len(source.encode('utf-8')) if isinstance(source, str) else 0
    except (ValueError, TypeError, UnicodeEncodeError):
        return None
    if (not isinstance(source, str) or not source.strip() or encoded_size > 32000
            or content != PROMPT_PREFIX + json.dumps(source, ensure_ascii=False)):
        return None
    return source


def valid_sentinel_output(output, source):
    if not isinstance(output, str):
        return False
    normalized = output.replace('\r\n', '\n')
    marker = '\n\n[Aperture inference metadata]\n'
    marker_at = normalized.rfind(marker)
    text = normalized[:marker_at] if marker_at >= 0 else normalized
    try:
        report = json.loads(text.strip())
    except (ValueError, TypeError):
        return False
    if (not isinstance(report, dict) or str(report.get('security', '')).upper() not in {'SAFE', 'DANGEROUS', 'REVIEW'}
            or not isinstance(report.get('reason'), str) or not isinstance(report.get('findings'), list)
            or len(report['findings']) > 20):
        return False
    line_count = len(re.split(r'\r\n|\n|\r', source))
    for finding in report['findings']:
        severity = finding.get('severity') if isinstance(finding, dict) else None
        if (not isinstance(finding, dict) or not isinstance(severity, str)
                or severity.lower() not in {'critical', 'high', 'medium', 'low', 'info'}
                or type(finding.get('line')) is not int or not 1 <= finding['line'] <= line_count
                or not isinstance(finding.get('issue'), str) or not finding['issue'].strip()
                or not isinstance(finding.get('evidence'), str)):
            return False
    return True


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
    result = review.get('result') or {}
    output = result.get('full_log')
    expected_messages = [{'role': 'user', 'content': PROMPT_PREFIX + json.dumps(source, ensure_ascii=False)}]
    if (reference['source_sha256'] != sha256_text(source)
            or review.get('wallet') != owner or review.get('state') != 'completed'
            or workload.get('runtime') != 'inference.chat'
            or parameters.get('offer', {}).get('protocol') not in SENTINEL_PROTOCOLS
            or parameters.get('inference', {}).get('messages') != expected_messages
            or receipt.get('execution_status') != 'completed'
            or receipt.get('execution_backend') != 'inference_proxy' or receipt.get('exit_code') != 0
            or not isinstance(output, str) or receipt.get('output_sha256') != sha256_text(output)
            or not valid_sentinel_output(output, source)
            or receipt.get('receipt_sha256') != reference['receipt_sha256']):
        raise HTTPException(409, 'A completed model review matching this owner and source is unavailable. Request a fresh review.')
