"""Single deterministic mutation coordinator; transport and UI hold no powers."""
from __future__ import annotations

from typing import Any, Callable

from abcr.control.store import ControlStore, StoreError


Handler = Callable[[dict[str, Any]], dict[str, Any]]


class Operator:
    def __init__(self, store: ControlStore, handlers: dict[str, Handler], *, worker_id: str = "operator"):
        self.store = store; self.handlers = handlers; self.worker_id = worker_id

    def execute(self, effect_id: str, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.store.claim_action(effect_id, self.worker_id):
            rows = [x for x in self.store.rows("actions") if x["effect_id"] == effect_id]
            if rows and rows[0]["result_json"]:
                import json
                return json.loads(rows[0]["result_json"])
            raise StoreError("action is already claimed or missing")
        handler = self.handlers.get(intent)
        if handler is None:
            result = {"ok": False, "code": "intent_not_supported", "intent": intent}
            self.store.finish_action(effect_id, worker_id=self.worker_id, state="failed", result=result)
            return result
        try:
            result = handler(payload)
        except Exception as exc:
            result = {"ok": False, "code": type(exc).__name__}
            self.store.finish_action(effect_id, worker_id=self.worker_id, state="failed", result=result)
            return result
        final = {"ok": True, "result": result}
        self.store.finish_action(effect_id, worker_id=self.worker_id, state="succeeded", result=final)
        return final


def main(argv: list[str] | None = None) -> int:
    """Fail closed until the trusted intent-handler registry is frozen."""
    from abcr.control.service_runtime import blocked_runtime_main
    return blocked_runtime_main(argv, service="operator-reconciler",
                                required_capability="execute",
                                capabilities={"execute": Operator.execute})


if __name__ == "__main__":
    raise SystemExit(main())
