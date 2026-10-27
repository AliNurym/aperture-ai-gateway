import { MAX_WORKFLOW_RATE } from './browserWorkflows.js';

const MAX_PUBLISHED_RATE = 1_000_000_000;
const WORKER_HEARTBEAT_TTL_SECONDS = 45;
const INFERENCE_SOURCE_PREFIX = '# Aperture inference request v1\n';

export function mixedWorkflowWorkerCapacity(workers, runtime, now = Date.now() / 1000) {
  const compatible = (Array.isArray(workers) ? workers : []).filter(worker =>
    typeof worker?.node_id === 'string' && worker.node_id.length > 0
      && typeof worker.worker_pubkey === 'string' && worker.worker_pubkey.length > 0
      && worker.accepting_tasks !== false
      && Array.isArray(worker.runtimes) && worker.runtimes.includes(runtime));
  const heartbeatFresh = worker => Number.isFinite(worker.last_seen)
    && now - worker.last_seen < WORKER_HEARTBEAT_TTL_SECONDS;
  const candidates = compatible.filter(worker => worker.online === true && heartbeatFresh(worker));
  const priced = candidates.filter(worker => Number.isSafeInteger(worker.rate_lamports_sec)
    && worker.rate_lamports_sec >= 1 && worker.rate_lamports_sec <= MAX_PUBLISHED_RATE);
  return {
    eligible: priced.filter(worker => worker.rate_lamports_sec <= MAX_WORKFLOW_RATE),
    rateLimited: priced.filter(worker => worker.rate_lamports_sec > MAX_WORKFLOW_RATE),
    unpricedCount: candidates.length - priced.length,
    staleCount: compatible.filter(worker => !heartbeatFresh(worker)).length,
  };
}

export function canBuildMixedWorkflow({ directoryState, providerCount = 0, modelWorkerCount = 0, pythonWorkerCount = 0 }) {
  return directoryState === 'ready' && providerCount > 0 && modelWorkerCount > 0 && pythonWorkerCount > 0;
}

export function workflowPlanNeedsModelOffer(plan) {
  return Array.isArray(plan?.steps) && plan.steps.some(step =>
    typeof step?.source === 'string' && step.source.startsWith(INFERENCE_SOURCE_PREFIX));
}

export function workflowPlanNeedsPythonWorker(plan) {
  return Array.isArray(plan?.steps) && plan.steps.some(step =>
    typeof step?.source === 'string' && !step.source.startsWith(INFERENCE_SOURCE_PREFIX));
}

export function mixedWorkflowCapacityNotice({
  directoryState,
  providerCount = 0,
  modelWorkerCount = 0,
  pythonWorkerCount = 0,
  needsModel = true,
  needsPython = true,
  modelRateLimitedCount = 0,
  pythonRateLimitedCount = 0,
  pythonUnpricedCount = 0,
  modelStaleCount = 0,
  pythonStaleCount = 0,
}) {
  if (directoryState === 'loading') {
    return {
      state: 'loading',
      title: 'Checking model and worker capacity',
      message: 'Reading public model offers and active workers from this gateway.',
    };
  }
  if (directoryState === 'unavailable') {
    return {
      state: 'unavailable',
      title: 'Capacity directory unavailable',
      message: 'The gateway could not return model offers and worker capacity. Check the connection or refresh capacity.',
    };
  }
  if (needsModel && providerCount === 0) {
    return {
      state: 'empty',
      title: 'No general model offer yet',
      message: 'DeepSeek checks Sentinel source safety only; it is not an inference offer or price source. Add a live model offer, matching inference worker and priced Python worker.',
      action: 'Open model setup',
    };
  }
  if (needsModel && modelWorkerCount === 0) {
    if (modelRateLimitedCount > 0) {
      return {
        state: 'rate-limited',
        title: 'Model worker rate exceeds this workflow limit',
        message: `Compatible model workers are online, but their published rate is above ${MAX_WORKFLOW_RATE.toLocaleString('en-US')} lamports per second. Choose another matching worker or ask a provider owner to publish a supported rate.`,
        action: 'Open capacity setup',
      };
    }
    if (modelStaleCount > 0) {
      return {
        state: 'stale',
        title: 'Model worker heartbeat is stale',
        message: 'A matching model worker was listed, but its heartbeat is no longer fresh. Refresh capacity before changing the worker setup.',
      };
    }
    return {
      state: 'worker-missing',
      title: 'No priced active worker for this model',
      message: 'A public offer exists, but this gateway has no online, priced inference worker that serves it. Start or price a matching worker to use this chain.',
      action: 'Open capacity setup',
    };
  }
  if (needsPython && pythonWorkerCount === 0) {
    if (pythonRateLimitedCount > 0) {
      return {
        state: 'rate-limited',
        title: 'Python worker rate exceeds this workflow limit',
        message: `Python workers are online, but their published rate is above ${MAX_WORKFLOW_RATE.toLocaleString('en-US')} lamports per second. Worker owners set their own rates; this workflow accepts rates up to its protocol limit.`,
        action: 'Open capacity setup',
      };
    }
    if (pythonUnpricedCount > 0) {
      return {
        state: 'worker-unpriced',
        title: 'Python worker has no published rate',
        message: 'A Python worker is online, but its owner has not published a rate. The task budget cannot set that price; the owner publishes it in Provide compute.',
        action: 'Open capacity setup',
      };
    }
    if (pythonStaleCount > 0) {
      return {
        state: 'stale',
        title: 'Python worker heartbeat is stale',
        message: 'A compatible Python worker was listed, but its heartbeat is no longer fresh. Refresh capacity before changing the worker setup.',
      };
    }
    return {
      state: 'python-missing',
      title: 'Python capacity is needed too',
      message: 'This chain also needs an online, priced Python worker to measure the model output before the final model step.',
      action: 'Open capacity setup',
    };
  }
  return null;
}
