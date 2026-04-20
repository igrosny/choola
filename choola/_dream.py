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

"""Training logic for `choola dream` — per-node XGBoost classifiers for LLML.

Kept outside `cli.py` to keep the CLI thin and to let this module be imported
independently in tests. Runs synchronously — everything it touches is local
disk / local SQLite / local ChromaDB.
"""

from __future__ import annotations

import json
import pickle
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from choola.database import (
    _workflow_db_query_sync,
    _workflow_vector_client,
)

_SAFE_ID = re.compile(r"^[a-z0-9_]+$")


def _model_dir(workflow_name: str, node_id: str) -> Path:
    return (
        Path.cwd() / "workflows" / workflow_name / "files" / "llml" / node_id
    )


def train_llml_node(
    workflow_name: str, node_id: str, min_examples: int = 10
) -> dict[str, Any]:
    """Train and persist an XGBoost classifier for one LLML node.

    Returns a status dict with keys:
      - status: "trained" | "skipped_too_few" | "skipped_single_class" | "skipped_no_embeddings"
      - n_examples: int
      - n_classes: int
      - path: str (when status == "trained")
      - train_accuracy: float (when status == "trained")
    """
    if not _SAFE_ID.match(node_id):
        raise ValueError(
            f"LLML node_id '{node_id}' must match ^[a-z0-9_]+$ "
            "(used as a SQL table name suffix)"
        )

    try:
        rows = _workflow_db_query_sync(
            workflow_name,
            f"SELECT params_hash, result FROM llml_{node_id} WHERE source = 'llm'",
            (),
        )
    except Exception as exc:
        return {
            "status": "skipped_no_table",
            "n_examples": 0,
            "n_classes": 0,
            "error": str(exc),
        }

    if len(rows) < min_examples:
        return {
            "status": "skipped_too_few",
            "n_examples": len(rows),
            "n_classes": 0,
        }

    unique_results = sorted({row["result"] for row in rows})
    if len(unique_results) < 2:
        return {
            "status": "skipped_single_class",
            "n_examples": len(rows),
            "n_classes": len(unique_results),
        }

    label_to_idx = {label: i for i, label in enumerate(unique_results)}
    collection_name = f"llml_{node_id}"
    client = _workflow_vector_client(workflow_name)
    try:
        collection = client.get_collection(name=collection_name)
    except Exception as exc:
        return {
            "status": "skipped_no_embeddings",
            "n_examples": len(rows),
            "n_classes": len(unique_results),
            "error": f"collection '{collection_name}' not found: {exc}",
        }

    ids = [row["params_hash"] for row in rows]
    fetched = collection.get(ids=ids, include=["embeddings"])
    fetched_ids = list(fetched.get("ids") or [])
    fetched_embeddings = list(fetched.get("embeddings") or [])
    id_to_embedding = dict(zip(fetched_ids, fetched_embeddings))

    features: list[list[float]] = []
    labels: list[int] = []
    for row in rows:
        emb = id_to_embedding.get(row["params_hash"])
        if emb is None:
            continue
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        features.append(list(emb))
        labels.append(label_to_idx[row["result"]])

    if len(features) < min_examples:
        return {
            "status": "skipped_no_embeddings",
            "n_examples": len(features),
            "n_classes": len(unique_results),
        }

    import numpy as np
    import xgboost as xgb

    X = np.asarray(features, dtype=np.float32)
    y = np.asarray(labels, dtype=np.int32)

    if len(unique_results) == 2:
        model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=5,
            objective="binary:logistic",
            eval_metric="logloss",
            n_jobs=1,
        )
    else:
        model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=5,
            objective="multi:softprob",
            num_class=len(unique_results),
            eval_metric="mlogloss",
            n_jobs=1,
        )
    model.fit(X, y)
    train_accuracy = float((model.predict(X) == y).mean())

    out_dir = _model_dir(workflow_name, node_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "model.bin", "wb") as f:
        pickle.dump(model, f)
    with open(out_dir / "labels.json", "w", encoding="utf-8") as f:
        json.dump(unique_results, f, ensure_ascii=False, indent=2)
    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_examples": len(features),
        "n_classes": len(unique_results),
        "feature_dim": int(X.shape[1]),
        "train_accuracy": train_accuracy,
        "labels": unique_results,
    }
    with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "status": "trained",
        "n_examples": len(features),
        "n_classes": len(unique_results),
        "train_accuracy": train_accuracy,
        "path": str(out_dir / "model.bin"),
    }


def discover_llml_nodes(workflow_name: str) -> list[type]:
    """Return LLML-subclass node classes defined in the given workflow."""
    from choola.cli import load_workflow_classes
    from choola.core.nodes.llml import LLML

    registry = load_workflow_classes(workflow_name)
    out: list[type] = []
    for cls in registry.values():
        if isinstance(cls, type) and issubclass(cls, LLML) and cls is not LLML:
            out.append(cls)
    return out
