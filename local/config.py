"""Model profiles and configuration for small local models."""
from __future__ import annotations

from providers import bare_model


# Per-model configuration profiles tuned for small local models.
# Keys match ollama model names (or prefixes for family matching).
MODEL_PROFILES: dict[str, dict] = {
    "gemma3:1b": {
        "context_limit": 4096,
        "max_tokens": 1024,
        "thinking_budget": 512,
        "skill_token_budget": 200,
        "knowledge_token_budget": 100,
        "system_prompt_budget": 1000,
        "max_retries": 3,
        "temperature": 0.2,
        "deliberation_mode": "on_failure",
        "n_branches": 2,
    },
    "gemma3:4b": {
        "context_limit": 8192,
        "max_tokens": 2048,
        "thinking_budget": 1024,
        "skill_token_budget": 300,
        "knowledge_token_budget": 150,
        "system_prompt_budget": 1500,
        "max_retries": 2,
        "temperature": 0.3,
        "deliberation_mode": "on_failure",
        "n_branches": 2,
    },
    "gemma4:e4b": {
        "context_limit": 32768,
        "max_tokens": 4096,
        "thinking_budget": 2048,
        "skill_token_budget": 300,
        "knowledge_token_budget": 200,
        "system_prompt_budget": 0,  # no compression — 32K context can handle full prompt
        "max_retries": 1,
        "temperature": 0.3,
        "deliberation_mode": "on_failure",
        "n_branches": 2,
        "prefer_text_tools": True,
    },
    "qwen3:8b": {
        "context_limit": 32768,
        "max_tokens": 4096,
        "thinking_budget": 2048,
        "skill_token_budget": 300,
        "knowledge_token_budget": 200,
        "system_prompt_budget": 0,
        "max_retries": 1,
        "temperature": 0.3,
        "deliberation_mode": "on_failure",
        "n_branches": 2,
    },
    "qwen3.5": {
        "context_limit": 32768,  # use 32K even though model supports 262K
        "max_tokens": 4096,
        "thinking_budget": 2048,  # cap thinking tokens; retry without thinking if exceeded
        "skill_token_budget": 300,
        "knowledge_token_budget": 200,
        "system_prompt_budget": 0,  # no compression — plenty of context
        "max_retries": 1,
        "temperature": 0.3,
        "deliberation_mode": "on_failure",
        "n_branches": 2,
    },
    "gemma3:12b": {
        "context_limit": 32768,
        "max_tokens": 4096,
        "thinking_budget": 2048,
        "skill_token_budget": 500,
        "knowledge_token_budget": 200,
        "system_prompt_budget": 3000,
        "max_retries": 1,
        "temperature": 0.4,
        "deliberation_mode": "never",
        "n_branches": 2,
    },
    "qwen2.5:3b": {
        "context_limit": 8192,
        "max_tokens": 2048,
        "thinking_budget": 1024,
        "skill_token_budget": 300,
        "knowledge_token_budget": 150,
        "system_prompt_budget": 1500,
        "max_retries": 2,
        "temperature": 0.3,
        "deliberation_mode": "on_failure",
        "n_branches": 2,
    },
    "llama3.2:1b": {
        "context_limit": 4096,
        "max_tokens": 1024,
        "thinking_budget": 512,
        "skill_token_budget": 200,
        "knowledge_token_budget": 100,
        "system_prompt_budget": 1000,
        "max_retries": 3,
        "temperature": 0.2,
        "deliberation_mode": "on_failure",
        "n_branches": 2,
    },
    "llama3.2:3b": {
        "context_limit": 8192,
        "max_tokens": 2048,
        "thinking_budget": 1024,
        "skill_token_budget": 300,
        "knowledge_token_budget": 150,
        "system_prompt_budget": 1500,
        "max_retries": 2,
        "temperature": 0.3,
        "deliberation_mode": "on_failure",
        "n_branches": 2,
    },
    "phi4-mini": {
        "context_limit": 16384,
        "max_tokens": 2048,
        "thinking_budget": 1024,
        "skill_token_budget": 400,
        "knowledge_token_budget": 200,
        "system_prompt_budget": 2000,
        "max_retries": 2,
        "temperature": 0.3,
        "deliberation_mode": "on_failure",
        "n_branches": 2,
    },
}

DEFAULT_SMALL_MODEL_PROFILE: dict = {
    "context_limit": 8192,
    "max_tokens": 2048,
    "thinking_budget": 1024,
    "skill_token_budget": 300,
    "knowledge_token_budget": 150,
    "system_prompt_budget": 1500,
    "max_retries": 2,
    "temperature": 0.3,
    "deliberation_mode": "on_failure",
    "n_branches": 2,
}

# Profiles for larger / cloud models -- no special optimizations needed
LARGE_MODEL_PROFILE: dict = {
    "context_limit": 128000,
    "max_tokens": 8192,
    "thinking_budget": 10000,
    "skill_token_budget": 0,     # no skill injection needed
    "knowledge_token_budget": 0, # no knowledge injection needed
    "system_prompt_budget": 0,   # no compression needed
    "max_retries": 0,
    "temperature": 0.7,
    "deliberation_mode": "never",
    "n_branches": 0,
}

# Model families that are considered "large" and don't need small-model optimizations
_LARGE_PREFIXES = [
    "claude-", "gpt-4", "o1", "o3", "gemini-", "qwen-max", "qwen-plus",
    "deepseek-chat", "deepseek-reasoner", "glm-4", "moonshot-",
]


def is_small_model(model: str) -> bool:
    """Return True if the model is a small local model needing optimizations."""
    name = bare_model(model).lower()
    for prefix in _LARGE_PREFIXES:
        if name.startswith(prefix):
            return False
    return True


def get_model_profile(model: str) -> dict:
    """Get the configuration profile for a model.

    Matches by exact name first, then by family prefix.
    Returns LARGE_MODEL_PROFILE for cloud/large models.
    """
    if not is_small_model(model):
        return dict(LARGE_MODEL_PROFILE)

    name = bare_model(model).lower()

    # Exact match
    if name in MODEL_PROFILES:
        return dict(MODEL_PROFILES[name])

    # Family prefix match (e.g. "gemma3:4b-instruct" matches "gemma3:4b")
    for pattern, profile in MODEL_PROFILES.items():
        if name.startswith(pattern):
            return dict(profile)

    # Family match without size (e.g. "gemma3:2b-custom" matches any gemma3)
    family = name.split(":")[0] if ":" in name else name.split("-")[0]
    for pattern, profile in MODEL_PROFILES.items():
        if pattern.startswith(family):
            return dict(profile)

    return dict(DEFAULT_SMALL_MODEL_PROFILE)
