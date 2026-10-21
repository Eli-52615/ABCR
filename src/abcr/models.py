"""Model loading with revision pinning from configs/models.yaml."""

from pathlib import Path
from typing import Any

import torch
import transformers
import yaml


def load(model_key: str, device_backend: str = "auto") -> tuple[Any, Any, dict[str, str]]:
    models_cfg = yaml.safe_load(Path("configs/models.yaml").read_text())["models"]
    if model_key not in models_cfg:
        raise ValueError(f"Unknown model_key: {model_key}")

    info = models_cfg[model_key]
    model_id = info["model_id"]
    revision = info["revision"]

    model_path = Path(model_id)
    is_local = model_path.exists()

    if device_backend == "auto":
        if model_key == "tinyqwen" or model_key == "qwen2.5-0.5b-instruct":
            device_backend = "cpu"
            dtype = torch.float32
        elif model_key == "qwen2.5-3b-instruct":
            if torch.backends.mps.is_available():
                device_backend = "mps"
                dtype = torch.float16
            else:
                device_backend = "cpu"
                dtype = torch.float32
        else:
            device_backend = "cpu"
            dtype = torch.float32
    else:
        dtype = torch.float16 if device_backend == "mps" else torch.float32

    load_kwargs: dict[str, Any] = {"torch_dtype": dtype}
    if is_local:
        load_kwargs["pretrained_model_name_or_path"] = str(model_path)
    else:
        load_kwargs["pretrained_model_name_or_path"] = model_id
        if revision != "PIN-AT-CLOUD-PROVISION":
            load_kwargs["revision"] = revision

    tokenizer = transformers.AutoTokenizer.from_pretrained(
        load_kwargs["pretrained_model_name_or_path"],
        revision=load_kwargs.get("revision"),
    )
    model = transformers.AutoModelForCausalLM.from_pretrained(**load_kwargs)

    if device_backend == "mps":
        model = model.to("mps")
    elif device_backend == "cuda":
        model = model.to("cuda")

    model.eval()

    meta = {
        "model_id": model_id,
        "dtype": str(dtype).replace("torch.", ""),
        "device_backend": device_backend,
        "engine_version": transformers.__version__,
        "torch_version": torch.__version__,
    }

    return model, tokenizer, meta
