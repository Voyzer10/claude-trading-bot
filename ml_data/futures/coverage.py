"""Non-billable US futures coverage and entitlement preflight."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .client import DatabentoHistoricalClient
from .config import DATABENTO_DATASET, inspect_databento_credentials
from .exceptions import (
    FuturesAdapterError,
    FuturesAuthError,
    FuturesLicensingError,
    FuturesSubscriptionError,
)


class FuturesCoveragePreflight:
    """Read-only non-billable preflight for Databento US equity-index futures."""

    def __init__(self, *, client: Optional[DatabentoHistoricalClient] = None, dataset: str = DATABENTO_DATASET) -> None:
        self.client = client or DatabentoHistoricalClient()
        self.dataset = dataset

    def run_preflight(self) -> Dict[str, Any]:
        cred_status = inspect_databento_credentials()
        if cred_status.get("DATABENTO_API_KEY") != "PRESENT" and self.client._transport is None:
            return {
                "provider": "databento",
                "dataset": self.dataset,
                "credentials": cred_status,
                "dataset_available": False,
                "schemas": [],
                "status": "BLOCKED_BY_AUTH",
                "notes": "DATABENTO_API_KEY is absent/invalid; live preflight skipped without purchasing or consuming credits.",
            }
        try:
            ds_resp = self.client.request("/v0/metadata.list_datasets")
            datasets = list(ds_resp.body) if isinstance(ds_resp.body, list) else []
            ds_ok = self.dataset in datasets
            if not ds_ok:
                return {
                    "provider": "databento",
                    "dataset": self.dataset,
                    "credentials": cred_status,
                    "dataset_available": False,
                    "schemas": [],
                    "status": "UNSUPPORTED",
                }
            sc_resp = self.client.request("/v0/metadata.list_schemas", params={"dataset": self.dataset})
            schemas = list(sc_resp.body) if isinstance(sc_resp.body, list) else []
            rng_resp = self.client.request("/v0/metadata.get_dataset_range", params={"dataset": self.dataset})
            return {
                "provider": "databento",
                "dataset": self.dataset,
                "credentials": cred_status,
                "dataset_available": True,
                "schemas": schemas,
                "dataset_range": rng_resp.body,
                "status": "VERIFIED",
            }
        except FuturesAuthError as e:
            return {"provider": "databento", "dataset": self.dataset, "status": "BLOCKED_BY_AUTH", "error": str(e)}
        except FuturesSubscriptionError as e:
            return {"provider": "databento", "dataset": self.dataset, "status": "BLOCKED_BY_SUBSCRIPTION", "error": str(e)}
        except FuturesLicensingError as e:
            return {"provider": "databento", "dataset": self.dataset, "status": "BLOCKED_BY_LICENSING", "error": str(e)}
        except FuturesAdapterError as e:
            return {"provider": "databento", "dataset": self.dataset, "status": "UNAVAILABLE", "error": str(e)}
