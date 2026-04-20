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
@choola-node: LLML
@category: processing
@description: Cached + locally-inferable LLM for yes/no and small-label classification. Falls through: exact-match cache -> local XGBoost -> real LLM.
@input-payload:
  - Any key listed in `parameter_keys` config (used as the cache key and XGBoost feature input)
  - Any key referenced by {placeholder} in the prompt template
@output-payload:
  - llm_response (str): the returned label / answer
  - llml_source (str): "llm" | "xgboost" (same value echoed on cache hits)
  - llml_confidence (float | null): XGBoost top-class probability when source="xgboost"; null otherwise
  - llml_cached (bool): True when this exact (params, prompt, model, provider) combination was seen before
  - llm_model (str), llm_provider (str): preserved from the LLM call
@config-fields:
  - credential_name (str, required): Name of the stored credential (inherited from LLM)
  - provider (select: claude, gemini): Which LLM provider to use (inherited)
  - model (str): Model identifier (inherited; falls back to provider default)
  - prompt (str, required): Prompt template; {key} interpolates payload values (inherited)
  - system_prompt (str, optional): System prompt (inherited)
  - max_tokens (number, default=1024): Max tokens in the response (inherited)
  - temperature (number, default=1.0): Sampling temperature (inherited)
  - parameter_keys (json, default="[]"): payload keys whose values form the cache key and embedding
  - confidence_threshold (number, default=0.85): min XGBoost top-class probability required to skip the LLM call
@example-input: {"text": "Buy now!!!"}
@example-output: {"llm_response": "spam", "llml_source": "xgboost", "llml_confidence": 0.94, "llml_cached": false, "llm_model": "claude-sonnet-4-20250514", "llm_provider": "claude", "text": "Buy now!!!"}
@side-effects: Creates/writes to the per-workflow SQLite table `llml_<node_id>`; upserts into the per-workflow ChromaDB collection `llml_<node_id>`; may make an HTTP call to a paid LLM API; reports token usage via self.report_tokens
@errors: Missing credential, invalid parameter_keys JSON, node_id not matching ^[a-z0-9_]+$, unsupported provider, provider API errors
@cost: paid-per-call — pays only on cache miss + below-threshold or missing XGBoost model; often free after `choola dream` has trained the node
"""

from __future__ import annotations

import hashlib
import json
import pickle
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from choola.core.nodes.llm import LLM, _DEFAULT_MODELS

_SAFE_ID = re.compile(r"^[a-z0-9_]+$")


def _default_embedder():
    """Return ChromaDB's default embedding function (lazy import)."""
    from chromadb.utils import embedding_functions
    return embedding_functions.DefaultEmbeddingFunction()


def _embed_one(text: str) -> list[float]:
    embedding = _default_embedder()([text])[0]
    if hasattr(embedding, "tolist"):
        embedding = embedding.tolist()
    return list(embedding)


def _hash_params(model: str, provider: str, template: str, params: dict[str, Any]) -> str:
    payload = json.dumps(
        {"model": model, "provider": provider, "template": template, "params": params},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _predict_with_xgboost(
    model_path: Path, labels_path: Path, rendered: str
) -> tuple[str, float]:
    import numpy as np

    with open(model_path, "rb") as f:
        model = pickle.load(f)
    with open(labels_path, "r", encoding="utf-8") as f:
        labels = json.load(f)

    emb = _embed_one(rendered)
    X = np.asarray([emb], dtype=np.float32)
    probs = model.predict_proba(X)[0]
    top_idx = int(np.argmax(probs))
    confidence = float(probs[top_idx])
    if top_idx >= len(labels):
        raise RuntimeError(f"Trained model class index {top_idx} out of range of labels file")
    return labels[top_idx], confidence


class LLML(LLM):
    name: ClassVar[str] = "LLML"
    category: ClassVar[str] = "processing"
    description: ClassVar[str] = (
        "LLM classifier with exact-match cache and local XGBoost fallback."
    )
    fields: ClassVar[list[dict[str, Any]]] = [
        *LLM.fields,
        {
            "name": "parameter_keys",
            "type": "json",
            "default": "[]",
            "description": (
                "JSON list of payload keys. Their values form the cache key "
                "and feature input for the local XGBoost model."
            ),
        },
        {
            "name": "confidence_threshold",
            "type": "number",
            "default": 0.85,
            "description": (
                "Min XGBoost top-class probability (0.0-1.0) required to skip the LLM."
            ),
        },
    ]

    async def execute(
        self, payload: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        node_id = self.node_id
        if not _SAFE_ID.match(node_id):
            raise ValueError(
                f"LLML node_id '{node_id}' must match ^[a-z0-9_]+$ "
                "(used as a SQL table name suffix)"
            )

        provider = self.config.get("provider", "claude")
        model = self.config.get("model", "").strip() or _DEFAULT_MODELS.get(provider, "")
        template = self.config.get("prompt", "") or payload.get("prompt", "")
        if not template:
            raise ValueError("No prompt configured and none found in payload")

        parameter_keys = self._parse_parameter_keys()
        params = {k: payload.get(k) for k in parameter_keys}

        try:
            rendered = template.format(**payload)
        except KeyError as exc:
            raise ValueError(
                f"Prompt template references missing payload key: {exc}"
            ) from exc

        params_hash = _hash_params(model, provider, template, params)
        prompt_hash = _hash_text(rendered)

        await self._ensure_table(node_id)

        cached = await self.db_query(
            f"SELECT result, source, confidence FROM llml_{node_id} "
            "WHERE params_hash = ? LIMIT 1",
            (params_hash,),
        )
        if cached:
            row = cached[0]
            payload["llm_response"] = row["result"]
            payload["llm_model"] = model
            payload["llm_provider"] = provider
            payload["llml_source"] = row["source"]
            payload["llml_confidence"] = row["confidence"]
            payload["llml_cached"] = True
            return payload

        threshold = float(self.config.get("confidence_threshold", 0.85))
        workflow_name = context.get("workflow") or ""
        model_dir = (
            Path.cwd() / "workflows" / workflow_name / "files" / "llml" / node_id
        )
        model_path = model_dir / "model.bin"
        labels_path = model_dir / "labels.json"

        if model_path.exists() and labels_path.exists():
            try:
                result, confidence = _predict_with_xgboost(
                    model_path, labels_path, rendered
                )
            except Exception:
                result, confidence = None, 0.0

            if result is not None and confidence >= threshold:
                await self._store_row(
                    node_id, params_hash, params, prompt_hash, model, provider,
                    result, "xgboost", confidence, rendered,
                )
                payload["llm_response"] = result
                payload["llm_model"] = model
                payload["llm_provider"] = provider
                payload["llml_source"] = "xgboost"
                payload["llml_confidence"] = confidence
                payload["llml_cached"] = False
                return payload

        credential_name = self.config.get("credential_name", "")
        if not credential_name:
            raise ValueError(
                "credential_name is required — configure it in the node settings"
            )
        cred = await self.get_credential(credential_name)
        if cred is None:
            raise ValueError(
                f"Credential '{credential_name}' not found. "
                "Add it via Settings > Credentials."
            )

        api_key = cred["value"]
        max_tokens = int(self.config.get("max_tokens", 1024))
        temperature = float(self.config.get("temperature", 1.0))
        system_prompt = self.config.get("system_prompt", "").strip()

        if provider == "claude":
            response_text = await self._call_claude(
                api_key, model, rendered, system_prompt, max_tokens, temperature
            )
        elif provider == "gemini":
            response_text = await self._call_gemini(
                api_key, model, rendered, system_prompt, max_tokens, temperature
            )
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        result = response_text.strip()
        await self._store_row(
            node_id, params_hash, params, prompt_hash, model, provider,
            result, "llm", None, rendered,
        )
        payload["llm_response"] = result
        payload["llm_model"] = model
        payload["llm_provider"] = provider
        payload["llml_source"] = "llm"
        payload["llml_confidence"] = None
        payload["llml_cached"] = False
        return payload

    def _parse_parameter_keys(self) -> list[str]:
        raw = self.config.get("parameter_keys", [])
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                return []
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"parameter_keys is not valid JSON: {exc}") from exc
        if not isinstance(raw, list) or not all(isinstance(k, str) for k in raw):
            raise ValueError("parameter_keys must be a JSON list of strings")
        return raw

    async def _ensure_table(self, node_id: str) -> None:
        await self.db_execute(
            f"""
            CREATE TABLE IF NOT EXISTS llml_{node_id} (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                params_hash   TEXT    NOT NULL UNIQUE,
                params_json   TEXT    NOT NULL,
                prompt_hash   TEXT    NOT NULL,
                llm_model     TEXT    NOT NULL,
                llm_provider  TEXT    NOT NULL,
                result        TEXT    NOT NULL,
                source        TEXT    NOT NULL,
                confidence    REAL,
                created_at    TEXT    NOT NULL
            )
            """,
            (),
        )
        await self.db_execute(
            f"CREATE INDEX IF NOT EXISTS idx_llml_{node_id}_hash "
            f"ON llml_{node_id}(params_hash)",
            (),
        )

    async def _store_row(
        self,
        node_id: str,
        params_hash: str,
        params: dict[str, Any],
        prompt_hash: str,
        model: str,
        provider: str,
        result: str,
        source: str,
        confidence: float | None,
        rendered: str,
    ) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        params_json = json.dumps(
            params, sort_keys=True, ensure_ascii=False, default=str
        )
        await self.db_execute(
            f"""
            INSERT OR IGNORE INTO llml_{node_id}
                (params_hash, params_json, prompt_hash, llm_model, llm_provider,
                 result, source, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (params_hash, params_json, prompt_hash, model, provider,
             result, source, confidence, created_at),
        )
        if source != "llm":
            return
        try:
            embedding = _embed_one(rendered)
            await self.vector_add(
                collection=f"llml_{node_id}",
                ids=[params_hash],
                embeddings=[embedding],
                metadatas=[{"result": result, "source": source}],
            )
        except Exception:
            pass
