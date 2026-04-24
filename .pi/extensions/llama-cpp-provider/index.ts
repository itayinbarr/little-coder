import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const LLAMACPP_BASE_URL = process.env.LLAMACPP_BASE_URL || "http://127.0.0.1:8888/v1";
const OLLAMA_BASE_URL = process.env.OLLAMA_BASE_URL || "http://127.0.0.1:11434/v1";

export default function (pi: ExtensionAPI) {
  pi.registerProvider("llamacpp", {
    baseUrl: LLAMACPP_BASE_URL,
    apiKey: "LLAMACPP_API_KEY",
    api: "openai-completions",
    models: [
      {
        id: "qwen3.6-27b",
        name: "Qwen3.6-27B (dense, local llama.cpp)",
        reasoning: true,
        input: ["text"],
        contextWindow: 32768,
        maxTokens: 4096,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      },
      {
        id: "qwen3.6-35b-a3b",
        name: "Qwen3.6-35B-A3B (MoE, local llama.cpp)",
        reasoning: true,
        input: ["text"],
        contextWindow: 32768,
        maxTokens: 4096,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      },
      {
        id: "qwen3.5-9b",
        name: "Qwen3.5-9B (local llama.cpp)",
        reasoning: true,
        input: ["text"],
        contextWindow: 32768,
        maxTokens: 4096,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      },
    ],
  });

  pi.registerProvider("ollama", {
    baseUrl: OLLAMA_BASE_URL,
    apiKey: "OLLAMA_API_KEY",
    api: "openai-completions",
    models: [
      {
        id: "qwen3.5",
        name: "Qwen3.5 (ollama)",
        reasoning: true,
        input: ["text"],
        contextWindow: 32768,
        maxTokens: 4096,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      },
    ],
  });
}
