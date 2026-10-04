import axios from 'axios';
import { PublicKey } from '@solana/web3.js';
import { canonicalJson, sha256Hex, verifyGatewayReceipt, verifyDevnetSettlement } from './protocol.js';
import { hashBytes } from './jobs.js';
import { objectReference, validateStorageUsage } from './storage.js';

export async function ownerRequest({ context, owner, agent, signMessage, action, path, body = {},
  task_id = null, limit = null, cursor = null, signal, ensureCurrent = () => {} }) {
  if (!owner || !signMessage) throw new Error('Connect an owner wallet that can sign messages.');
  if (new PublicKey(agent).toBase58() !== agent) throw new Error('Choose a valid agent public key.');
  const issued_at = Math.floor(Date.now() / 1000), nonce = crypto.randomUUID().replaceAll('-', '');
  const fields = { owner, agent_pubkey: agent, issued_at, nonce };
  const message = 'Aperture owner control v1\naudience:aperture-gateway\n' + canonicalJson({
    action, ...fields, task_id, limit, cursor, program_id: context.program_id,
    gateway_pubkey: context.gateway_pubkey, network: context.network });
  ensureCurrent();
  const signature = await signMessage(new TextEncoder().encode(message));
  ensureCurrent();
  const { data } = await axios.post(context.apiUrl + path, { ...body, ...fields, signature: Array.from(signature) }, { timeout: 30000, signal });
  ensureCurrent();
  return data;
}

export async function assignInputs(options, inputs) {
  const files = inputs.map(objectReference);
  const data = await ownerRequest({ ...options, action: 'assign-inputs', path: '/owners/objects/assign-batch',
    body: { inputs: files }, task_id: await sha256Hex(canonicalJson(files)), limit: files.reduce((sum, file) => sum + file.size_bytes, 0) });
  if (data.owner !== options.owner || data.agent_pubkey !== options.agent || !Array.isArray(data.inputs) || data.inputs.length !== files.length) throw new Error('The handoff changed the selected agent or input count.');
  const references = data.inputs.map(objectReference);
  references.forEach((item, index) => {
    if (['name', 'sha256', 'size_bytes'].some(key => item[key] !== files[index][key])) throw new Error('The assigned file changed its immutable content.');
  });
  return references;
}

export async function openAgentView(options) {
  const view = await ownerRequest({ ...options, action: 'observe-agent', path: '/owners/agents/observe' });
  if (view.owner !== options.owner || view.agent_pubkey !== options.agent
      || view.gateway_pubkey !== options.context.gateway_pubkey || view.program_id !== options.context.program_id
      || view.network !== options.context.network || !Number.isSafeInteger(view.expires_at)
      || view.expires_at * 1000 <= Date.now() || typeof view.view_token !== 'string') throw new Error('The agent view belongs to a different workspace or has expired.');
  return view;
}

export async function submitAssignedPlan(options, plan, requestId) {
  const digest = await sha256Hex(canonicalJson(plan));
  const value = await ownerRequest({ ...options, action: 'submit-workflow', path: '/owners/workflows/submit',
    body: { plan, request_id: requestId }, task_id: digest, limit: plan.max_cost_lamports, cursor: requestId });
  if (value.owner !== options.owner || value.agent_pubkey !== options.agent || value.plan_sha256 !== digest
      || value.max_cost_lamports !== plan.max_cost_lamports || value.request_id !== requestId
      || !/^flow-[0-9a-f]{64}$/.test(value.workflow_id)) throw new Error('The approved workflow changed its plan, agent or total budget.');
  return value;
}

export async function assignedRequestId(options, plan) {
  const key = 'aperture.assigned-intent.' + await sha256Hex(canonicalJson({ owner: options.owner, agent: options.agent,
    context: options.context, plan }));
  try {
    const retained = localStorage.getItem(key);
    if (retained && /^[0-9a-f]{32}$/.test(retained)) return retained;
    const identifier = crypto.randomUUID().replaceAll('-', '');
    localStorage.setItem(key, identifier);
    const keys = Object.keys(localStorage).filter(key => key.startsWith('aperture.assigned-intent.'));
    while (keys.length > 128) { const expired = keys.shift(); if (expired !== key) localStorage.removeItem(expired); }
    return identifier;
  } catch { return crypto.randomUUID().replaceAll('-', ''); }
}

export async function stopAssignedWorkflow(options, identifier) {
  return ownerRequest({ ...options, action: 'stop-assigned-workflow', path: '/owners/workflows/stop',
    body: { workflow_id: identifier }, task_id: identifier });
}

export async function archiveAssignedWorkflow(options, identifier) {
  return ownerRequest({ ...options, action: 'archive-assigned-workflow', path: '/owners/workflows/archive',
    body: { workflow_id: identifier }, task_id: identifier });
}

export async function readAgentView(context, view, signal, cursor = null) {
  const { data } = await axios.get(context.apiUrl + '/owners/agents/' + view.agent_pubkey + '/overview', {
    params: cursor ? { cursor } : undefined, headers: { 'X-Aperture-Owner-View': view.view_token }, timeout: 15000, signal });
  if (data.owner !== view.owner || data.agent_pubkey !== view.agent_pubkey || !Array.isArray(data.tasks)
      || data.tasks.length > 20 || !data.tasks.every(task => /^task-[0-9a-f]{32}$/.test(task.task_id)
        && task.quote?.wallet === view.owner && task.quote?.agent_pubkey === view.agent_pubkey)) throw new Error('The agent task list changed execution identity.');
  const { data: flows } = await axios.get(context.apiUrl + '/owners/agents/' + view.agent_pubkey + '/workflows', {
    headers: { 'X-Aperture-Owner-View': view.view_token }, timeout: 15000, signal });
  if (!Array.isArray(flows.workflows) || flows.workflows.length > 64 || flows.workflows.some(flow => flow.owner !== view.owner
      || flow.agent_pubkey !== view.agent_pubkey || !/^flow-[0-9a-f]{64}$/.test(flow.workflow_id))) throw new Error('The workflow list changed owner or agent.');
  return { ...data, workflows: flows.workflows, storage: validateStorageUsage(data.storage) };
}

export async function readAgentArtifact(context, view, task, file, connection, signal) {
  const item = objectReference(file), quote = task.quote;
  if (quote?.wallet !== view.owner || quote?.agent_pubkey !== view.agent_pubkey
      || quote.gateway_pubkey !== context.gateway_pubkey || quote.program_id !== context.program_id
      || quote.network !== context.network) throw new Error('The task belongs to another owner, agent or deployment.');
  const verification = await verifyGatewayReceipt(task.receipt, quote, task.task_id, task.full_log);
  if (!verification.verified) throw new Error(verification.reason);
  if (task.receipt.settlement_type === 'DEVNET') {
    if (!connection || await connection.getGenesisHash() !== 'GH7ome3EiwEr7tu9JuTh2dpYWBJK3z69Xm1ZE3MEE6JC') throw new Error('Independent Solana Devnet verification is unavailable.');
    await verifyDevnetSettlement(connection, task.receipt, quote, task.task_id);
  }
  if (!task.receipt.artifacts?.some(value => canonicalJson(value) === canonicalJson(item))) throw new Error('The file is absent from the verified receipt.');
  const { data } = await axios.get(context.apiUrl + '/owners/agents/' + view.agent_pubkey + '/tasks/' + task.task_id + '/artifacts/' + item.object_id, {
    headers: { 'X-Aperture-Owner-View': view.view_token }, responseType: 'arraybuffer', timeout: 30000, signal });
  const bytes = new Uint8Array(data);
  if (bytes.byteLength !== item.size_bytes || await hashBytes(bytes) !== item.sha256) throw new Error('Downloaded file differs from its signed size or digest.');
  return bytes;
}
