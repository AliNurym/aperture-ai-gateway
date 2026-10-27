"""Portable source reviews: fixed prompts, signed evidence and exact-source links."""
from importlib.resources import files
import json
import re

from .client import IntegrityError, canonical, canonical_quote_message, require, sha256, verify_receipt, validate_source
from .jobs import inference_source, workload_manifest

PROMPT_PREFIX = json.loads(files('aperture_client').joinpath('sentinel_review.json').read_text(encoding='utf-8'))['prefix']
CATALOG_FIELDS = {'available_workers', 'lowest_worker_rate_lamports_sec', 'rate_lamports_sec'}


def build_source_review_prompt(source):
    validate_source(source)
    prompt = PROMPT_PREFIX + json.dumps(source, ensure_ascii=False)
    require(len(prompt) <= 16000, 'Source is too long for one AI Sentinel message; review a smaller section')
    return prompt


def model_offer(provider):
    """Directory availability and worker prices are not immutable model terms."""
    return {key: value for key, value in provider.items() if key not in CATALOG_FIELDS}


def parse_source_review_report(output, source):
    require(isinstance(output, str), 'Source review output must be text')
    validate_source(source)
    text = output.replace('\r\n', '\n').rsplit('\n\n[Aperture inference metadata]\n', 1)[0]
    try:
        report = json.loads(text)
    except (ValueError, TypeError) as error:
        raise IntegrityError('Source review returned invalid JSON; inspect the verified model output manually') from error
    require(isinstance(report, dict), 'Source review must return a JSON object')
    security = str(report.get('security', '')).upper()
    require(security in {'SAFE', 'DANGEROUS', 'REVIEW'}, 'Source review has no recognized advisory verdict')
    require(isinstance(report.get('reason'), str), 'Source review has no explanatory reason')
    raw_findings = report.get('findings')
    require(isinstance(raw_findings, list) and len(raw_findings) <= 20, 'Source review findings are malformed or exceed the limit')
    line_count = len(re.split(r'\r\n|\n|\r', source))
    findings = []
    for finding in raw_findings:
        require(isinstance(finding, dict), 'Source review contains a malformed finding')
        severity = finding.get('severity')
        line = finding.get('line')
        issue = finding.get('issue')
        evidence = finding.get('evidence')
        require(isinstance(severity, str) and severity.lower() in {'critical', 'high', 'medium', 'low', 'info'},
                'Source review contains an unknown finding severity')
        require(type(line) is int and 1 <= line <= line_count, 'Source review finding points outside its source')
        require(isinstance(issue, str) and bool(issue.strip()) and isinstance(evidence, str),
                'Source review finding is incomplete')
        findings.append({'severity': severity.lower(), 'line': line,
            'issue': issue[:500], 'evidence': evidence[:1000]})
    # Treat a SAFE verdict paired with a substantive finding as inconclusive.
    if security == 'SAFE' and any(finding['severity'] != 'info' for finding in findings):
        security = 'REVIEW'
    return {'security': security, 'reason': report['reason'][:2000],
            'findings': findings}


def verify_source_review_bundle(bundle, *, owner, program_id, gateway_pubkey, network, treasury=None):
    """Verify browser/SDK exports offline against the caller's pinned deployment.

    This checks signatures and source provenance. Devnet finality is verified
    separately by ApertureClient.wait(), using its independent RPC connection.
    """
    require(isinstance(bundle, dict) and type(bundle.get('version')) is int and bundle['version'] == 1,
            'Unsupported source review bundle')
    source = bundle.get('source')
    prompt = build_source_review_prompt(source)
    evidence = bundle.get('evidence')
    require(isinstance(evidence, dict), 'Missing signed source review evidence')
    quote, receipt, output = (evidence.get(key) for key in ('quote', 'receipt', 'output'))
    require(isinstance(quote, dict) and isinstance(receipt, dict) and isinstance(output, str)
            and len(output.encode('utf-8')) <= 1_000_000, 'Invalid source review evidence')
    require(quote.get('wallet') == owner and quote.get('gateway_pubkey') == gateway_pubkey
            and quote.get('program_id') == program_id and quote.get('network') == network
            and quote.get('treasury') == treasury, 'Source review belongs to another owner or deployment')
    workload = quote.get('workload') or {}
    require(isinstance(workload, dict), 'Invalid source review workload')
    parameters = workload.get('parameters') or {}
    require(isinstance(parameters, dict) and isinstance(parameters.get('offer'), dict)
            and isinstance(parameters.get('inference'), dict), 'Invalid source review parameters')
    require(workload.get('runtime') == 'inference.chat'
            and parameters.get('offer', {}).get('protocol') in {'openai_chat_completions', 'gemini_generate_content'}
            and parameters.get('inference', {}).get('messages') == [{'role': 'user', 'content': prompt}],
            'Source review is not bound to this exact source and fixed prompt')
    spec = workload_manifest(inference_source(parameters), [], parameters)
    require(workload == spec and quote.get('code_sha256') == spec['source_sha256']
            and quote.get('workload_sha256') == sha256(canonical(spec))
            and quote.get('workload_canonical') == canonical(spec)
            and quote.get('message') == canonical_quote_message(quote), 'Source review manifest was changed')
    task_id = receipt.get('task_id')
    require(isinstance(task_id, str) and len(task_id) == 37 and task_id.startswith('task-')
            and all(char in '0123456789abcdef' for char in task_id[5:]), 'Invalid source review task identifier')
    verify_receipt(receipt, quote=quote, task_id=task_id, full_log=output)
    require(receipt.get('execution_status') == 'completed', 'Source review task did not complete successfully')
    return {'verified': True, 'advisory': True, 'task_id': task_id,
            'report': parse_source_review_report(output, source),
            'review_reference': {'task_id': task_id, 'source_sha256': sha256(source),
                                 'receipt_sha256': receipt['receipt_sha256']}}
