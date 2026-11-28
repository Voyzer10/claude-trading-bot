"""Phase 0 Step 2 integrity patch: price-axis bounds policy (P1-A) and instrument spec-hash integrity (P1-B)."""
from __future__ import annotations

import copy
import dataclasses
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ml_data.charts import (
    AVAILABILITY_EVENT_TIME,
    STATUS_MODEL_READY,
    ChartContractError,
    ChartSnapshotManifest,
    LookaheadError,
    ProvenanceError,
    price_axis_bounds,
    verify_chart_snapshot,
)
from ml_data.instruments.identity import compute_spec_hash

from .test_chart_contract import PNG, SPEC, full_chart, manifest_for, renderer, snapshot, spec_for, spec_version

UTC = timezone.utc
POLICY = "PADDED_RANGE_V1"


def forge(man: ChartSnapshotManifest, **fields) -> ChartSnapshotManifest:
    f = copy.copy(man)
    for k, v in fields.items():
        object.__setattr__(f, k, v)
    return f


# ================================================================================================ P1-A

def test_p1a_policy_bounds_are_derived_and_verify() -> None:
    ds, spec, man = full_chart()
    assert (spec.price_axis_policy, spec.price_axis_padding_ratio) == (POLICY, "0.05")
    assert (ds.visible_low, ds.visible_high) == ("101.09", "103.18")
    # pad = (103.18 - 101.09) * 0.05 = 0.1045 -> [100.9855, 103.2845], exact Decimal
    assert (man.price_axis_min, man.price_axis_max) == ("100.9855", "103.2845")
    assert (man.price_axis_policy, man.price_axis_padding_ratio) == (POLICY, "0.05")
    assert man.render_status == STATUS_MODEL_READY
    verify_chart_snapshot(man, spec=spec, data_snapshot=ds, renderer=renderer())


def test_p1a_reproduced_wider_tampered_bounds_are_rejected() -> None:
    ds, spec, man = full_chart()
    with pytest.raises(ChartContractError):                         # manifest validation
        dataclasses.replace(man, price_axis_min="90", price_axis_max="120")
    with pytest.raises(ChartContractError):                         # verification (validation bypassed)
        verify_chart_snapshot(forge(man, price_axis_min="90", price_axis_max="120"), spec=spec, data_snapshot=ds,
                              renderer=renderer())


@pytest.mark.parametrize("field,value", [("price_axis_min", "100.9854"), ("price_axis_min", "99"),
                                         ("price_axis_max", "103.2846"), ("price_axis_max", "110")])
def test_p1a_tampered_lower_or_upper_bound_is_rejected(field, value) -> None:
    ds, spec, man = full_chart()
    with pytest.raises(ChartContractError):
        dataclasses.replace(man, **{field: value})
    with pytest.raises(ChartContractError):
        verify_chart_snapshot(forge(man, **{field: value}), spec=spec, data_snapshot=ds, renderer=renderer())


def test_p1a_bounds_not_containing_visible_range_are_rejected() -> None:
    ds, spec, man = full_chart()
    for lo, hi in (("101.5", "103.2845"), ("100.9855", "102"), ("103", "101")):
        with pytest.raises(ChartContractError):
            dataclasses.replace(man, price_axis_min=lo, price_axis_max=hi)
        with pytest.raises(ChartContractError):
            verify_chart_snapshot(forge(man, price_axis_min=lo, price_axis_max=hi), spec=spec, data_snapshot=ds,
                                  renderer=renderer())
    with pytest.raises(ChartContractError):                         # renderer-reported bounds must match the policy
        manifest_for(ds, spec, bounds=("101.5", "103.2845"))
    with pytest.raises(ChartContractError):                         # re-labelling the visible range is also caught
        dataclasses.replace(man, visible_low="100")


def test_p1a_different_axis_configuration_changes_identity() -> None:
    ds, spec, man = full_chart()
    wide = spec_for(ds, price_axis_padding_ratio="0.1")
    m2 = manifest_for(ds, wide)
    assert m2.data_snapshot_id == man.data_snapshot_id
    assert wide.spec_hash() != spec.spec_hash() and m2.chart_snapshot_id != man.chart_snapshot_id
    assert (m2.price_axis_min, m2.price_axis_max) == ("100.881", "103.389")
    verify_chart_snapshot(m2, spec=wide, data_snapshot=ds, renderer=renderer())
    with pytest.raises(ChartContractError):                         # a manifest cannot claim another configuration
        verify_chart_snapshot(m2, spec=spec, data_snapshot=ds, renderer=renderer())
    consistent = dataclasses.replace(man, price_axis_padding_ratio="0.1", price_axis_min="100.881",
                                     price_axis_max="103.389")
    with pytest.raises(ChartContractError):                         # self-consistent edit, caught against the spec
        verify_chart_snapshot(consistent, spec=spec, data_snapshot=ds, renderer=renderer())


def test_p1a_axis_configuration_validation_and_decimal_only_math() -> None:
    ds = snapshot()
    for bad in ("0", "-0.05", "0.26", 0.05, "abc", True):
        with pytest.raises(ChartContractError):
            spec_for(ds, price_axis_padding_ratio=bad)
    spec = spec_for(ds)
    with pytest.raises(ChartContractError):                         # the policy itself is profile-locked
        dataclasses.replace(spec, price_axis_policy="AUTO")
    assert spec_for(ds, price_axis_padding_ratio=Decimal("0.050")).price_axis_padding_ratio == "0.05"
    assert price_axis_bounds("100", "100", policy=POLICY, padding_ratio="0.05") == ("95", "105")   # flat window
    assert price_axis_bounds("0", "0", policy=POLICY, padding_ratio="0.05") == ("-0.05", "0.05")
    assert price_axis_bounds("0.000012345678", "0.000012345679", policy=POLICY, padding_ratio="0.25") == \
        ("0.00001234567775", "0.00001234567925")                    # exact, no float rounding
    with pytest.raises(ChartContractError):
        price_axis_bounds(101.09, "103.18", policy=POLICY, padding_ratio="0.05")
    with pytest.raises(ChartContractError):
        price_axis_bounds("101.09", "103.18", policy="AUTO", padding_ratio="0.05")


def test_p1a_png_and_image_verification_remain_green(tmp_path) -> None:
    ds, spec, man = full_chart()
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "aapl.png").write_bytes(PNG)
    verify_chart_snapshot(man, spec=spec, data_snapshot=ds, renderer=renderer(), image_root=str(tmp_path))
    assert ChartSnapshotManifest.from_json(man.to_json()) == man


# ================================================================================================ P1-B

def test_p1b_matching_specification_and_hash_accepted() -> None:
    sv = spec_version()
    assert sv.spec_hash == compute_spec_hash(SPEC) and dict(sv.specification) == SPEC
    ds = snapshot(sv=sv)
    assert ds.instrument_spec_hash == compute_spec_hash(SPEC)


def test_p1b_changed_specification_with_stale_hash_rejected() -> None:
    stale = spec_version(specification={**SPEC, "tick_size": "0.05"}, spec_hash=compute_spec_hash(SPEC))
    with pytest.raises(ProvenanceError):
        snapshot(sv=stale)
    with pytest.raises(ProvenanceError):                            # also in retrospective mode
        snapshot(sv=stale, mode=AVAILABILITY_EVENT_TIME)
    with pytest.raises(ProvenanceError):                            # empty specification with a real hash
        snapshot(sv=spec_version(specification={}, spec_hash=compute_spec_hash(SPEC)))


def test_p1b_changed_specification_with_recomputed_hash_changes_identity() -> None:
    base = snapshot()
    changed = snapshot(sv=spec_version(specification={**SPEC, "tick_size": "0.05"}))
    assert changed.data_snapshot_id != base.data_snapshot_id
    assert changed.instrument_spec_hash == compute_spec_hash({**SPEC, "tick_size": "0.05"})


def test_p1b_mutated_specification_cannot_keep_a_stale_hash() -> None:
    spec = dict(SPEC)
    sv = spec_version(specification=spec)
    snapshot(sv=sv)                                                 # consistent at first
    spec["tick_size"] = "0.10"                                      # caller mutates the dict afterwards
    with pytest.raises(ProvenanceError):
        snapshot(sv=sv)
    with pytest.raises(ProvenanceError):                            # non-mapping / non-canonical specifications
        snapshot(sv=spec_version(specification=["tick_size", "0.01"], spec_hash=compute_spec_hash(SPEC)))
    with pytest.raises(ProvenanceError):
        snapshot(sv=spec_version(specification={"tick_size": Decimal("0.01")}, spec_hash=compute_spec_hash(SPEC)))


def test_p1b_point_in_time_rules_unchanged() -> None:
    with pytest.raises(LookaheadError):
        snapshot(sv=spec_version(recorded_at=datetime(2026, 11, 27, tzinfo=UTC)))
    ds = snapshot(sv=spec_version(recorded_at=datetime(2026, 11, 27, tzinfo=UTC)), mode=AVAILABILITY_EVENT_TIME)
    assert ds.instrument_spec_known_at_decision is False
    with pytest.raises(ProvenanceError):
        snapshot(sv=spec_version(effective_from=datetime(2026, 6, 1, tzinfo=UTC)))
