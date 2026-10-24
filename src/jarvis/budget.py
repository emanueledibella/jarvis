from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from .db import now


class ModelBudget:
    """Reserve each cloud invocation before the SDK can send its request.

    Rates are owner supplied. Unknown usage keeps its reservation, including after
    crashes. This is an estimate guard; the provider invoice remains authoritative.
    """

    def __init__(self, config, db):
        self.config, self.db = config, db
        self.lock = asyncio.Lock()

    async def reserve(
        self, run_id: str, task_id: str, messages, parameters, *, pricing=None, max_tokens=None
    ):
        settings = self.config.settings
        input_rate = pricing["input"] if pricing else settings.model_input_usd_per_million
        output_rate = pricing["output"] if pricing else settings.model_output_usd_per_million
        if not input_rate or not output_rate:
            raise ValueError(
                "Per il cloud configura le tariffe input/output nelle impostazioni: servono a verificare il budget prima delle richieste."
            )
        # UTF-8 bytes are a conservative estimate for ordinary BPE text tokens.
        # Include serialized tool schemas and per-message protocol overhead.
        payload = json.dumps(
            [[m.model_dump() for m in group] for group in messages], ensure_ascii=False, default=str
        )
        prompt_upper = (
            len(payload.encode()) + len(json.dumps(parameters, default=str).encode()) + 2048
        )
        reservation = (
            prompt_upper * input_rate + (max_tokens or settings.max_output_tokens) * output_rate
        ) / 1_000_000
        month = datetime.now(UTC).strftime("%Y-%m")
        async with self.lock:
            row = await self.db.fetchone(
                "SELECT COALESCE(SUM(CASE WHEN state='complete' THEN actual_usd ELSE reservation_usd END),0) AS total FROM model_usage WHERE month=?",
                (month,),
            )
            if row["total"] + reservation > settings.monthly_budget_usd:
                raise ValueError(
                    "Budget mensile insufficiente per la prossima richiesta cloud. Nessuna richiesta inviata."
                )
            await self.db.execute(
                "INSERT INTO model_usage(id,task_id,month,state,reservation_usd,created_at) VALUES(?,?,?,'reserved',?,?)",
                (run_id, task_id, month, reservation, now()),
            )
        return input_rate, output_rate

    async def finish(self, run_id: str, usage: dict, rates: tuple):
        if not usage or not {"input_tokens", "output_tokens"}.issubset(usage):
            await self.db.execute("UPDATE model_usage SET state='unknown' WHERE id=?", (run_id,))
            return
        actual = (usage["input_tokens"] * rates[0] + usage["output_tokens"] * rates[1]) / 1_000_000
        await self.db.execute(
            "UPDATE model_usage SET state='complete',actual_usd=?,input_tokens=?,output_tokens=? WHERE id=?",
            (actual, usage["input_tokens"], usage["output_tokens"], run_id),
        )

    async def status(self):
        month = datetime.now(UTC).strftime("%Y-%m")
        row = await self.db.fetchone(
            "SELECT COALESCE(SUM(CASE WHEN state='complete' THEN actual_usd ELSE reservation_usd END),0) AS committed_usd,COUNT(*) AS requests FROM model_usage WHERE month=?",
            (month,),
        )
        return {
            **row,
            "month": month,
            "limit_usd": self.config.settings.monthly_budget_usd,
            "rates_configured": bool(
                self.config.settings.model_input_usd_per_million
                and self.config.settings.model_output_usd_per_million
            ),
            "basis": "Stima con tariffe configurate; errori e consumi ignoti conservano la prenotazione.",
        }
