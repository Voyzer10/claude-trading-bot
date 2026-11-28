"""PyArrow Parquet storage for canonical LabelRecord datasets."""
from __future__ import annotations

import os
import threading
from datetime import timezone
from decimal import Decimal
from typing import List, Optional, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..storage.manifests import compute_file_sha256
from ..storage.parquet import PARQUET_DECIMAL_TYPE, _check_decimal_scale
from .models import LabelRecord

_UTC = timezone.utc

LABEL_ARROW_SCHEMA = pa.schema([
    ("instrument_id", pa.string()),
    ("market", pa.string()),
    ("exchange", pa.string()),
    ("asset_class", pa.string()),
    ("timeframe", pa.string()),
    ("horizon_bars", pa.int32()),
    ("label_method", pa.string()),
    ("config_version", pa.string()),
    ("decision_ts_utc", pa.timestamp("us", tz="UTC")),
    ("feature_cutoff_utc", pa.timestamp("us", tz="UTC")),
    ("earliest_executable_utc", pa.timestamp("us", tz="UTC")),
    ("label_start_ts_utc", pa.timestamp("us", tz="UTC")),
    ("label_end_ts_utc", pa.timestamp("us", tz="UTC")),
    ("label_available_ts_utc", pa.timestamp("us", tz="UTC")),
    ("gross_return", PARQUET_DECIMAL_TYPE),
    ("net_return", PARQUET_DECIMAL_TYPE),
    ("direction", pa.int8()),
    ("mfe", PARQUET_DECIMAL_TYPE),
    ("mae", PARQUET_DECIMAL_TYPE),
    ("bars_to_exit", pa.int32()),
    ("completion_status", pa.string()),
    ("dataset_id", pa.string()),
    ("dataset_version", pa.string()),
    ("manifest_sha256", pa.string()),
    ("spec_version_id", pa.int64()),
    ("quality_flags", pa.list_(pa.string())),
])


def write_labels_parquet(labels: Sequence[LabelRecord], path: str) -> str:
    ordered = sorted(labels, key=lambda x: (x.instrument_id, x.decision_ts_utc, x.horizon_bars))
    rows = {f.name: [] for f in LABEL_ARROW_SCHEMA}
    for r in ordered:
        rows["instrument_id"].append(r.instrument_id)
        rows["market"].append(r.market)
        rows["exchange"].append(r.exchange)
        rows["asset_class"].append(r.asset_class)
        rows["timeframe"].append(r.timeframe)
        rows["horizon_bars"].append(r.horizon_bars)
        rows["label_method"].append(r.label_method)
        rows["config_version"].append(r.config_version)
        rows["decision_ts_utc"].append(r.decision_ts_utc)
        rows["feature_cutoff_utc"].append(r.feature_cutoff_utc)
        rows["earliest_executable_utc"].append(r.earliest_executable_utc)
        rows["label_start_ts_utc"].append(r.label_start_ts_utc)
        rows["label_end_ts_utc"].append(r.label_end_ts_utc)
        rows["label_available_ts_utc"].append(r.label_available_ts_utc)
        rows["gross_return"].append(_check_decimal_scale(r.gross_return.quantize(Decimal("1e-12")) if r.gross_return is not None else None, "gross_return"))
        rows["net_return"].append(_check_decimal_scale(r.net_return.quantize(Decimal("1e-12")) if r.net_return is not None else None, "net_return"))
        rows["direction"].append(r.direction)
        rows["mfe"].append(_check_decimal_scale(r.mfe.quantize(Decimal("1e-12")) if r.mfe is not None else None, "mfe"))
        rows["mae"].append(_check_decimal_scale(r.mae.quantize(Decimal("1e-12")) if r.mae is not None else None, "mae"))
        rows["bars_to_exit"].append(r.bars_to_exit)
        rows["completion_status"].append(r.completion_status)
        rows["dataset_id"].append(r.dataset_id)
        rows["dataset_version"].append(r.dataset_version)
        rows["manifest_sha256"].append(r.manifest_sha256)
        rows["spec_version_id"].append(r.spec_version_id)
        rows["quality_flags"].append(list(r.quality_flags))

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    table = pa.Table.from_pydict(rows, schema=LABEL_ARROW_SCHEMA)
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path)
    return compute_file_sha256(path)


def read_labels_parquet(path: str) -> List[LabelRecord]:
    table = pq.read_table(path)
    cols = table.to_pydict()
    out: List[LabelRecord] = []
    for i in range(table.num_rows):
        def _opt_dt(k: str):
            v = cols[k][i]
            return v.astimezone(_UTC) if v is not None else None
        def _opt_dec(k: str) -> Optional[Decimal]:
            v = cols[k][i]
            return v.normalize() if isinstance(v, Decimal) else None
        out.append(
            LabelRecord(
                instrument_id=cols["instrument_id"][i],
                market=cols["market"][i],
                exchange=cols["exchange"][i],
                asset_class=cols["asset_class"][i],
                timeframe=cols["timeframe"][i],
                horizon_bars=int(cols["horizon_bars"][i]),
                label_method=cols["label_method"][i],
                config_version=cols["config_version"][i],
                decision_ts_utc=cols["decision_ts_utc"][i].astimezone(_UTC),
                feature_cutoff_utc=cols["feature_cutoff_utc"][i].astimezone(_UTC),
                earliest_executable_utc=_opt_dt("earliest_executable_utc"),
                label_start_ts_utc=_opt_dt("label_start_ts_utc"),
                label_end_ts_utc=_opt_dt("label_end_ts_utc"),
                label_available_ts_utc=_opt_dt("label_available_ts_utc"),
                gross_return=_opt_dec("gross_return"),
                net_return=_opt_dec("net_return"),
                direction=cols["direction"][i],
                mfe=_opt_dec("mfe"),
                mae=_opt_dec("mae"),
                bars_to_exit=cols["bars_to_exit"][i],
                completion_status=cols["completion_status"][i],
                dataset_id=cols["dataset_id"][i],
                dataset_version=cols["dataset_version"][i],
                manifest_sha256=cols["manifest_sha256"][i],
                spec_version_id=cols["spec_version_id"][i],
                quality_flags=tuple(cols["quality_flags"][i] or ()),
            )
        )
    return out
