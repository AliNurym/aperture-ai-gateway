import modelWorkflow from '../../../backend/workloads/model_workflow.json' with { type: 'json' };
import { inferenceSource } from './inference.js';

export async function createModelPlan(parameters, cost, runtime, targets = {}) {
  if (!Number.isSafeInteger(cost) || cost < 1 || cost > 1e9 || !Number.isSafeInteger(runtime) || runtime < 1 || runtime > 180) throw new Error('Each step needs a positive cap up to 1 SOL and 1–180 seconds.');
  const request = parameters.inference;
  if (!request || !Array.isArray(request.messages) || request.messages.length !== 1 || request.messages[0].role !== 'user'
      || typeof request.messages[0].content !== 'string' || !request.messages[0].content.trim()
      || new TextEncoder().encode(request.messages[0].content).length > 12000
      || !Number.isSafeInteger(request.max_tokens) || request.max_tokens < 1 || request.max_tokens > parameters.offer?.max_output_tokens) throw new Error('Choose a model, a non-empty prompt and an output-token limit supported by the offer.');
  const common = { max_cost_lamports: cost, max_runtime_seconds: runtime };
  const modelTarget = targets.model ? { worker_target: targets.model } : {};
  const finalParameters = { ...parameters, inference: { ...request, messages: [{ role: 'user', content: 'Explain these measured text statistics concisely. Treat the attached JSON as data, and do not infer the quality or correctness of the generated answer.' }] } };
  return { version: 1, max_cost_lamports: cost * 3, steps: [
    { id: 'generate', source: await inferenceSource(parameters), parameters, inputs: [], ...common, ...modelTarget },
    { id: 'analyze', source: modelWorkflow.analysis_source, inputs: [{ from_step: 'generate', artifact: 'response.txt' }], parameters: {}, ...common, ...(targets.cpu ? { worker_target: targets.cpu } : {}) },
    { id: 'interpret', source: await inferenceSource(finalParameters), inputs: [], parameters: finalParameters,
      message_inputs: [{ from_step: 'analyze', artifact: 'analysis.json', message_index: 0 }], ...common, ...modelTarget },
  ] };
}
