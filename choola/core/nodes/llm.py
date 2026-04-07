# Copyright 2026 Ivan Grosny
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
@choola-node: LLM
@category: processing
@description: Sends a prompt to an LLM (Claude or Gemini) and returns the response. Requires a stored credential.
@input-payload:
  - prompt (str, optional): Override prompt text. If absent, uses the configured prompt.
  - Any key can be referenced in the prompt template via {key} placeholders.
@output-payload:
  - llm_response (str): The text response from the LLM
  - llm_model (str): The model that was used
  - llm_provider (str): "claude" or "gemini"
  - (all prior payload keys are preserved)
@config-fields:
  - credential_name (str, required): Name of the stored credential to use for API access
  - provider (select: claude, gemini): Which LLM provider to use
  - model (str): Model identifier (e.g. "claude-sonnet-4-20250514", "gemini-2.0-flash")
  - prompt (str, required): Prompt template — use {key} to interpolate payload values
  - system_prompt (str, optional): System prompt for the LLM
  - max_tokens (number, default=1024): Maximum tokens in the response
  - temperature (number, default=1.0): Sampling temperature (0.0 - 2.0)
@example-input: {"name": "Alice", "question": "What is 2+2?"}
@example-output: {"llm_response": "2+2 equals 4.", "llm_model": "claude-sonnet-4-20250514", "llm_provider": "claude", "name": "Alice", "question": "What is 2+2?"}
@side-effects: Makes an HTTP call to an external LLM API
@errors: Missing credential, invalid provider, API errors
"""

from typing import Any

from choola.core.base_node import BaseNode

# Default models per provider
_DEFAULT_MODELS = {
    "claude": "claude-sonnet-4-20250514",
    "gemini": "gemini-2.0-flash",
}


class LLM(BaseNode):
    name = "LLM"
    category = "processing"
    description = "Sends a prompt to an LLM (Claude or Gemini) and returns the response."
    fields = [
        {
            "name": "credential_name",
            "type": "string",
            "required": True,
            "placeholder": "my-claude-key",
            "description": "Name of the stored credential (set in Settings > Credentials)",
        },
        {
            "name": "provider",
            "type": "select",
            "options": ["claude", "gemini"],
            "default": "claude",
        },
        {
            "name": "model",
            "type": "string",
            "placeholder": "claude-sonnet-4-20250514",
            "description": "Model ID (leave blank for provider default)",
        },
        {
            "name": "prompt",
            "type": "textarea",
            "required": True,
            "placeholder": "Summarize the following: {text}",
            "description": "Prompt template — use {key} to interpolate payload values",
        },
        {
            "name": "system_prompt",
            "type": "textarea",
            "placeholder": "You are a helpful assistant.",
            "description": "Optional system prompt",
        },
        {
            "name": "max_tokens",
            "type": "number",
            "default": 1024,
        },
        {
            "name": "temperature",
            "type": "number",
            "default": 1.0,
        },
    ]

    async def execute(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        credential_name = self.config.get("credential_name", "")
        if not credential_name:
            raise ValueError("credential_name is required — configure it in the node settings")

        cred = await self.get_credential(credential_name)
        if cred is None:
            raise ValueError(
                f"Credential '{credential_name}' not found. "
                "Add it via Settings > Credentials."
            )

        api_key = cred["value"]
        provider = self.config.get("provider", "claude")
        model = self.config.get("model", "").strip() or _DEFAULT_MODELS.get(provider, "")
        max_tokens = int(self.config.get("max_tokens", 1024))
        temperature = float(self.config.get("temperature", 1.0))
        system_prompt = self.config.get("system_prompt", "").strip()

        # Build the prompt by interpolating payload values
        prompt_template = self.config.get("prompt", "") or payload.get("prompt", "")
        if not prompt_template:
            raise ValueError("No prompt configured and none found in payload")

        try:
            prompt = prompt_template.format(**payload)
        except KeyError as exc:
            raise ValueError(f"Prompt template references missing payload key: {exc}") from exc

        if provider == "claude":
            response_text = await self._call_claude(api_key, model, prompt, system_prompt, max_tokens, temperature)
        elif provider == "gemini":
            response_text = await self._call_gemini(api_key, model, prompt, system_prompt, max_tokens, temperature)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        payload["llm_response"] = response_text
        payload["llm_model"] = model
        payload["llm_provider"] = provider
        return payload

    async def _call_claude(
        self, api_key: str, model: str, prompt: str, system_prompt: str,
        max_tokens: int, temperature: float,
    ) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = client.messages.create(**kwargs)
        return response.content[0].text

    async def _call_gemini(
        self, api_key: str, model: str, prompt: str, system_prompt: str,
        max_tokens: int, temperature: float,
    ) -> str:
        from google import genai

        client = genai.Client(api_key=api_key)

        config = genai.types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        if system_prompt:
            config.system_instruction = system_prompt

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        return response.text
