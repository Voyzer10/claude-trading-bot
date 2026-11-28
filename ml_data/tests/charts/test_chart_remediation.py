"""Phase 0 Step 2 remediation regression tests (P1-A, P1-B, P1-C, P2-A, P2-B)."""
from __future__ import annotations

import copy
import dataclasses
import math
import struct
import zlib
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from ml_data.calendars.india import IndiaNSECalendarAdapter
from ml_data.calendars.us_equity import USEquityCalendarAdapter
from ml_data.charts import (
    AVAILABILITY_AS_KNOWN,
    AVAILABILITY_EVENT_TIME,
    BASIS_AS_KNOWN,
    BASIS_RETROSPECTIVE,
    STATUS_INCOMPLETE,
    STATUS_MODEL_READY,
    STATUS_READY,
    ChartContractError,
    ChartSnapshotManifest,
    ChartSpec,
    ImageValidationError,
    LookaheadError,
    OverlaySpec,
    ProvenanceError,
    build_chart_snapshot_manifest,
    build_data_snapshot,
    compute_font_fingerprint,
    dataset_manifest_identity,
    require_single_availability_mode,
    validate_chart_png,
    verify_chart_snapshot,
)
from ml_data.storage import CanonicalCandle, DatasetManifest

from .test_chart_contract import (
    CREATED,
    PNG,
    SERIES,
    dataset_manifest,
    decision_after,
    full_chart,
    manifest_for,
    renderer,
    snapshot,
    spec_for,
    spec_version,
)

UTC = timezone.utc
VWAP = OverlaySpec.create("VWAP", {"price_source": "HLC3", "reset": "SESSION"}, style_ref="vwap")


def forge(man: ChartSnapshotManifest, **fields) -> ChartSnapshotManifest:
    """A tampered copy that bypasses construction-time validation (simulates an edited manifest file)."""
    f = copy.copy(man)
    for k, v in fields.items():
        object.__setattr__(f, k, v)
    return f


# ================================================================================================ P1-A

TAMPERS = {
    "renderer_name": "other-renderer",
    "renderer_version": "9.9.9",
    "renderer_build_id": "build-x",
    "font_fingerprint": compute_font_fingerprint({"Other.ttf": "9" * 64}),
    "theme_id": "light_v1",
    "theme_version": "1.0.1",
    "theme_hash": "0" * 64,
    "instrument_id": "US:NASDAQ:EQUITY:MSFT#" + "0" * 32,
    "timeframe": "1m",
    "actual_visible_candle_count": 199,
    "warmup_candle_count": 5,
    "required_warmup_candle_count": 7,
    "session_context_candle_count": 3,
    "visible_start_utc": SERIES[-200].timestamp_start_utc - timedelta(minutes=5),
    "visible_end_utc": SERIES[-1].timestamp_end_utc - timedelta(minutes=5),
    "decision_timestamp_utc": SERIES[-1].timestamp_end_utc + timedelta(hours=1),
    "last_visible_received_at_utc": SERIES[-1].timestamp_end_utc,
    "display_timezone": "America/Chicago",
    "visible_start_display": {"utc": "x", "local_iso": "x", "utc_offset_minutes": 0, "tz_abbreviation": "UTC", "label": "x"},
    "display_utc_offsets_minutes": (-240,),
    "calendar_id": "XNYS",
    "calendar_version": "2027.1",
    "adjustment_mode": "SPLIT_ADJUSTED",
    "sessions_present": ("PRE_MARKET", "REGULAR"),
    "dataset_id": "other_dataset",
    "dataset_version": "v2",
    "dataset_manifest_sha256": "1" * 64,
    "dataset_pagination_complete": False,
    "source_snapshot_ids": ("snap-forged",),
    "source_file_sha256s": ("2" * 64,),
    "instrument_spec_version_id": 7,
    "instrument_spec_hash": "3" * 64,
    "instrument_spec_recorded_at_utc": datetime(2020, 1, 1, tzinfo=UTC),
    "overlay_specs": (OverlaySpec.create("SMA", {"period": 5, "source": "CLOSE"}, style_ref="sma").to_dict(),),
    "visible_low": "50",
    "visible_high": "500",
    "price_axis_min": "101.5",
    "all_inputs_quality_verified": False,
    "intra_session_gap_count": 1,
    "missing_bar_count": 2,
    "status_reasons": ("INTRA_SESSION_GAPS",),
    "render_status": STATUS_READY,
    "point_in_time_basis": BASIS_RETROSPECTIVE,
    "availability_mode": AVAILABILITY_EVENT_TIME,
    "chart_spec_hash": "4" * 64,
    "chart_snapshot_id": "5" * 64,
    "data_snapshot_id": "6" * 64,
}


def test_p1a_untampered_manifest_verifies() -> None:
    ds, spec, man = full_chart()
    verify_chart_snapshot(man, spec=spec, data_snapshot=ds, renderer=renderer())
    assert man.render_status == STATUS_MODEL_READY


@pytest.mark.parametrize("field,value", list(TAMPERS.items()), ids=list(TAMPERS))
def test_p1a_each_tampered_derived_field_is_rejected(field, value) -> None:
    ds, spec, man = full_chart()
    with pytest.raises(ChartContractError):
        verify_chart_snapshot(forge(man, **{field: value}), spec=spec, data_snapshot=ds, renderer=renderer())


@pytest.mark.parametrize("field,value", [("image_sha256", "7" * 64), ("image_size_bytes", 1),
                                         ("image_path", "charts/other.png")])
def test_p1a_tampered_image_state_is_rejected_against_the_file(tmp_path, field, value) -> None:
    ds, spec, man = full_chart()
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "aapl.png").write_bytes(PNG)
    verify_chart_snapshot(man, spec=spec, data_snapshot=ds, renderer=renderer(), image_root=str(tmp_path))
    with pytest.raises(ChartContractError):
        verify_chart_snapshot(forge(man, **{field: value}), spec=spec, data_snapshot=ds, renderer=renderer(),
                              image_root=str(tmp_path))


def test_p1a_pagination_incomplete_cannot_be_forged_to_model_ready() -> None:
    ds = snapshot(manifest=dataset_manifest(pagination_complete=False))
    spec = spec_for(ds)
    man = manifest_for(ds, spec)
    assert man.render_status == STATUS_READY and man.status_reasons == ("DATASET_PAGINATION_INCOMPLETE",)
    assert man.dataset_pagination_complete is False
    verify_chart_snapshot(man, spec=spec, data_snapshot=ds, renderer=renderer())
    with pytest.raises(ChartContractError):                         # manifest validation
        dataclasses.replace(man, render_status=STATUS_MODEL_READY, status_reasons=())
    with pytest.raises(ChartContractError):
        ChartSnapshotManifest.from_dict({**man.to_dict(), "render_status": STATUS_MODEL_READY, "status_reasons": []})
    forged = forge(man, render_status=STATUS_MODEL_READY, status_reasons=())
    with pytest.raises(ChartContractError):                         # verify_chart_snapshot
        verify_chart_snapshot(forged, spec=spec, data_snapshot=ds, renderer=renderer())
    # Flipping the recorded flag as well makes the manifest self-consistent, so only verification against the
    # supplied DataSnapshot can catch it, and it does.
    forged2 = dataclasses.replace(man, render_status=STATUS_MODEL_READY, status_reasons=(),
                                  dataset_pagination_complete=True)
    with pytest.raises(ChartContractError):
        verify_chart_snapshot(forged2, spec=spec, data_snapshot=ds, renderer=renderer())


def test_p1a_incomplete_never_verifies_as_model_ready() -> None:
    ds = snapshot(SERIES[-199:])
    spec = spec_for(ds)
    man = manifest_for(ds, spec)
    assert man.render_status == STATUS_INCOMPLETE
    forged = forge(man, render_status=STATUS_MODEL_READY, status_reasons=(), actual_visible_candle_count=200)
    with pytest.raises(ChartContractError):
        verify_chart_snapshot(forged, spec=spec, data_snapshot=ds, renderer=renderer())
    with pytest.raises(ChartContractError):                         # status alone: manifest validation
        dataclasses.replace(man, render_status=STATUS_MODEL_READY, status_reasons=())
    consistent_forgery = dataclasses.replace(man, render_status=STATUS_MODEL_READY, status_reasons=(),
                                             actual_visible_candle_count=200)
    with pytest.raises(ChartContractError):                         # count + status: caught by verification
        verify_chart_snapshot(consistent_forgery, spec=spec, data_snapshot=ds, renderer=renderer())


def test_p1a_verification_uses_the_supplied_renderer_and_theme() -> None:
    ds, spec, man = full_chart()
    with pytest.raises(ProvenanceError):
        verify_chart_snapshot(man, spec=spec, data_snapshot=ds, renderer=renderer(renderer_name="other"))
    light = spec_for(ds, theme_id="light_v1", theme_version="1.0.0")
    with pytest.raises(ProvenanceError):
        verify_chart_snapshot(man, spec=light, data_snapshot=ds, renderer=renderer())
    with pytest.raises(ChartContractError):                         # theme hash must match the registry
        dataclasses.replace(man, theme_hash="0" * 64)


def test_p1a_nested_manifest_mappings_are_immutable() -> None:
    ema = OverlaySpec.create("EMA", {"period": 20, "source": "CLOSE"}, style_ref="ema_fast")
    ds = snapshot(SERIES[-200:], SERIES[-260:-200])
    man = manifest_for(ds, spec_for(ds, overlay_specs=[ema]))
    with pytest.raises(TypeError):
        man.visible_start_display["label"] = "forged"               # type: ignore[index]
    with pytest.raises(TypeError):
        man.overlay_specs[0]["warmup_bars"] = 0                     # type: ignore[index]
    with pytest.raises(TypeError):
        man.overlay_specs[0]["parameters"]["period"] = 5            # type: ignore[index]
    d = man.to_dict()
    d["overlay_specs"][0]["parameters"]["period"] = 5               # to_dict hands out independent copies
    d["visible_start_display"]["label"] = "forged"
    assert man.overlay_specs[0]["parameters"]["period"] == 20 and man.visible_start_display["label"] != "forged"
    src = dict(man.to_dict())
    rebuilt = ChartSnapshotManifest.from_dict(src)
    src["visible_end_display"]["label"] = "forged"                  # caller mutating its input afterwards
    assert rebuilt.visible_end_display["label"] != "forged" and rebuilt == man


# ================================================================================================ P1-B

def test_p1b_spec_recorded_before_decision_is_accepted_as_known() -> None:
    ds = snapshot(sv=spec_version(recorded_at=datetime(2026, 1, 2, tzinfo=UTC)))
    man = manifest_for(ds)
    assert ds.instrument_spec_known_at_decision and ds.point_in_time_basis == BASIS_AS_KNOWN
    assert man.point_in_time_basis == BASIS_AS_KNOWN and man.instrument_spec_known_at_decision


def test_p1b_spec_recorded_after_decision_is_rejected_as_known() -> None:
    with pytest.raises(LookaheadError):
        snapshot(sv=spec_version(recorded_at=datetime(2026, 11, 27, tzinfo=UTC)))
    with pytest.raises(LookaheadError):                             # one second late is still late
        snapshot(sv=spec_version(recorded_at=decision_after(SERIES[-1]) + timedelta(seconds=1)))
    with pytest.raises(ProvenanceError):                            # recorded_at must be timezone-aware
        snapshot(sv=spec_version(recorded_at=datetime(2025, 12, 31)))


def test_p1b_retrospective_spec_only_under_event_time_and_effective_dates() -> None:
    late = spec_version(recorded_at=datetime(2026, 11, 27, tzinfo=UTC))
    ds = snapshot(sv=late, mode=AVAILABILITY_EVENT_TIME)
    assert ds.point_in_time_basis == BASIS_RETROSPECTIVE and ds.instrument_spec_known_at_decision is False
    man = manifest_for(ds, spec_for(ds))
    assert man.point_in_time_basis == BASIS_RETROSPECTIVE and man.instrument_spec_known_at_decision is False
    assert man.instrument_spec_recorded_at_utc == datetime(2026, 11, 27, tzinfo=UTC)
    with pytest.raises(ChartContractError):                         # cannot relabel it as known at decision
        dataclasses.replace(man, instrument_spec_known_at_decision=True)
    with pytest.raises(LookaheadError):                             # nor as an as-known chart
        dataclasses.replace(man, availability_mode=AVAILABILITY_AS_KNOWN, point_in_time_basis=BASIS_AS_KNOWN)
    with pytest.raises(ProvenanceError):                            # effective dating still applies
        snapshot(sv=spec_version(recorded_at=datetime(2026, 11, 27, tzinfo=UTC),
                                 effective_from=datetime(2026, 6, 1, tzinfo=UTC)), mode=AVAILABILITY_EVENT_TIME)


def test_p1b_recorded_at_is_part_of_data_identity_and_modes_do_not_mix() -> None:
    a = snapshot(sv=spec_version(recorded_at=datetime(2025, 12, 31, tzinfo=UTC)))
    b = snapshot(sv=spec_version(recorded_at=datetime(2025, 12, 30, tzinfo=UTC)))
    assert a.data_snapshot_id != b.data_snapshot_id
    assert snapshot(mode=AVAILABILITY_EVENT_TIME).data_snapshot_id != a.data_snapshot_id
    assert require_single_availability_mode([AVAILABILITY_AS_KNOWN] * 2) == AVAILABILITY_AS_KNOWN
    with pytest.raises(ChartContractError):
        require_single_availability_mode([AVAILABILITY_AS_KNOWN, AVAILABILITY_EVENT_TIME])


# ================================================================================================ P1-C

NY, IST = ZoneInfo("America/New_York"), ZoneInfo("Asia/Kolkata")
XNYS = USEquityCalendarAdapter(calendar_id="XNYS")
XNSE = IndiaNSECalendarAdapter()
IN_IID = "IN:NSE:INDEX:NIFTY#" + "1" * 32


def session_candles(days, *, iid, market, asset_class, segment, exchange, cal_id, cal_ver, tz, open_t, bars,
                    sid_prefix, session="REGULAR"):
    out, i = [], 0
    for d in days:
        t = datetime.combine(d, open_t, tz).astimezone(UTC)
        for _ in range(bars):
            o = Decimal("100") + Decimal(i) / Decimal("100")
            c = o + Decimal("0.05")
            end = t + timedelta(minutes=5)
            out.append(CanonicalCandle(
                instrument_id=iid, market=market, asset_class=asset_class, segment=segment, exchange=exchange,
                provider="alpaca" if market == "US" else "kite", provider_symbol="SYM", provider_instrument_id="SYM",
                timestamp_start_utc=t, timestamp_end_utc=end, event_time_utc=end,
                received_at_utc=end + timedelta(seconds=1), timeframe="5m", trading_date=d, trading_session=session,
                session_id=f"{sid_prefix}_{d.isoformat()}", calendar_id=cal_id, calendar_version=cal_ver, open=o,
                high=c + Decimal("0.02"), low=o - Decimal("0.03"), close=c, volume=Decimal("1000") + i,
                provider_feed="iex" if market == "US" else "kite", source_snapshot_id="snap-1",
                source_record_id=f"rec-{i}", dataset_version="v1", adjustment_mode="RAW", retrieval_run_id="run-1",
                quality_status="VERIFIED",
            ))
            t, i = end, i + 1
    return out


def us_series(days, cal_id="XNYS", cal_ver="2026.1"):
    from .test_chart_contract import IID
    return session_candles(days, iid=IID, market="US", asset_class="EQUITY", segment="US_EQUITY", exchange="NASDAQ",
                           cal_id=cal_id, cal_ver=cal_ver, tz=NY, open_t=time(9, 30), bars=78, sid_prefix=cal_id)


def in_series(days):
    return session_candles(days, iid=IN_IID, market="IN", asset_class="INDEX", segment="IN_INDEX", exchange="NSE",
                           cal_id="XNSE", cal_ver="1.0.0", tz=IST, open_t=time(9, 15), bars=75, sid_prefix="XNSE")


def manifest_of(series, **over):
    base = dict(instrument_ids=[series[0].instrument_id], markets=[series[0].market],
                providers=[series[0].provider], feeds=[series[0].provider_feed],
                calendar_versions=[f"{series[0].calendar_id}:{series[0].calendar_version}"],
                actual_start_utc=series[0].timestamp_start_utc.isoformat(),
                actual_end_utc=series[-1].timestamp_end_utc.isoformat(), row_count=len(series))
    base.update(over)
    return dataset_manifest(series, **base)


def vwap_chart(series, visible, context=(), *, calendar=XNYS, tz="America/New_York", sessions=("REGULAR",), sv=None):
    ds = build_data_snapshot(
        instrument_id=series[0].instrument_id, timeframe="5m", decision_timestamp_utc=decision_after(visible[-1]),
        availability_mode=AVAILABILITY_AS_KNOWN, visible_candles=visible, warmup_candles=[],
        dataset_manifest=manifest_of(series), instrument_spec_version=sv or spec_version(instrument_id=series[0].instrument_id),
        session_context_candles=list(context), calendar=calendar,
    )
    spec = ChartSpec.create(instrument_id=series[0].instrument_id, timeframe="5m",
                            decision_timestamp_utc=ds.decision_timestamp_utc, data_snapshot_id=ds.data_snapshot_id,
                            display_timezone=tz, allowed_sessions=sessions, overlay_specs=[VWAP])
    man = build_chart_snapshot_manifest(spec=spec, data_snapshot=ds, renderer=renderer(), created_at_utc=CREATED,
                                        image_bytes=PNG, image_path="charts/v.png")
    verify_chart_snapshot(man, spec=spec, data_snapshot=ds, renderer=renderer())
    return ds, spec, man


US4 = us_series([date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)])   # 312 bars


def test_p1c_vwap_window_beginning_at_session_open() -> None:
    ds, _, man = vwap_chart(US4, US4[:200])                        # starts at the Jan 5 09:30 open
    assert man.render_status == STATUS_MODEL_READY and man.vwap_session_context_complete is True
    assert man.session_context_candle_count == 0
    assert [sid for sid, _ in ds.session_opens_utc] == ["XNYS_2026-01-05", "XNYS_2026-01-06", "XNYS_2026-01-07"]
    assert ds.session_opens_utc[0][1] == "2026-01-05T14:30:00+00:00"


def test_p1c_vwap_mid_session_with_complete_context() -> None:
    visible = US4[-200:]                                            # starts 34 bars into Jan 6
    context = US4[78:112]
    assert context[0].timestamp_start_utc == datetime(2026, 1, 6, 14, 30, tzinfo=UTC)
    ds, _, man = vwap_chart(US4, visible, context)
    assert man.render_status == STATUS_MODEL_READY and man.session_context_candle_count == 34
    assert man.actual_visible_candle_count == 200                   # context is never rendered or counted
    no_ctx = build_data_snapshot(instrument_id=ds.instrument_id, timeframe="5m",
                                 decision_timestamp_utc=ds.decision_timestamp_utc, availability_mode=AVAILABILITY_AS_KNOWN,
                                 visible_candles=visible, warmup_candles=[], dataset_manifest=manifest_of(US4),
                                 instrument_spec_version=spec_version(), calendar=XNYS)
    assert no_ctx.data_snapshot_id != ds.data_snapshot_id          # context records are part of data identity
    changed = context[:10] + [dataclasses.replace(context[10], volume=context[10].volume + 1)] + context[11:]
    ds_changed, _, _ = vwap_chart(US4, visible, changed)
    assert ds_changed.data_snapshot_id != ds.data_snapshot_id      # ... including their values, not just count


def test_p1c_vwap_mid_session_without_context_is_never_model_ready() -> None:
    ds, spec, man = vwap_chart(US4, US4[-200:])
    assert man.render_status == STATUS_INCOMPLETE and man.vwap_session_context_complete is False
    assert man.status_reasons == ("INSUFFICIENT_VWAP_SESSION_CONTEXT",)
    assert "SESSION_OPEN_MISSING:XNYS_2026-01-06" in ds.vwap_session_context_issues
    for st in (STATUS_MODEL_READY, STATUS_READY):
        with pytest.raises(ChartContractError):
            dataclasses.replace(man, render_status=st, status_reasons=())
    flipped = dataclasses.replace(man, render_status=STATUS_MODEL_READY, status_reasons=(),
                                  vwap_session_context_complete=True)
    with pytest.raises(ChartContractError):
        verify_chart_snapshot(flipped, spec=spec, data_snapshot=ds, renderer=renderer())
    _, _, partial = vwap_chart(US4, US4[-200:], US4[79:112])        # context missing the opening bar
    assert partial.render_status == STATUS_INCOMPLETE


def test_p1c_multiple_sessions_reset_at_each_official_open() -> None:
    ds, _, _ = vwap_chart(US4, US4[-200:], US4[78:112])
    opens = dict(ds.session_opens_utc)
    for d in (date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)):
        assert opens[f"XNYS_{d.isoformat()}"] == XNYS.inner.session_bounds(d)[0].astimezone(UTC).isoformat()
    # a later visible session whose opening bar is missing (count kept at 200 by starting one bar earlier)
    jan7_open = 156
    visible = US4[-201:jan7_open] + US4[jan7_open + 1:]
    assert len(visible) == 200
    ds2, _, man2 = vwap_chart(US4, visible, US4[78:111])
    assert "SESSION_OPEN_MISSING:XNYS_2026-01-07" in ds2.vwap_session_context_issues
    assert man2.render_status == STATUS_INCOMPLETE


def test_p1c_missing_opening_or_session_bars_are_explicitly_incomplete() -> None:
    ctx = US4[78:112]
    gapped_ctx = ctx[:10] + ctx[11:]
    with pytest.raises(ChartContractError):                         # a gap at the context/visible join
        vwap_chart(US4, US4[-200:], ctx[:-1])
    ds, _, man = vwap_chart(US4, US4[-200:], gapped_ctx)
    assert "SESSION_BARS_MISSING:XNYS_2026-01-06" in ds.vwap_session_context_issues
    assert man.render_status == STATUS_INCOMPLETE
    ds2, _, man2 = vwap_chart(US4, US4[:200], calendar=None)       # no calendar: cannot be proven
    assert ds2.vwap_session_context_issues == ("NO_EXCHANGE_CALENDAR",) and man2.render_status == STATUS_INCOMPLETE


def test_p1c_context_rules_and_calendar_provenance() -> None:
    with pytest.raises(ProvenanceError):                            # calendar must be the candles' calendar
        vwap_chart(US4, US4[:200], calendar=XNSE)
    xnas = us_series([date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)], cal_id="XNAS", cal_ver="2026.1")
    ds, _, man = vwap_chart(xnas, xnas[:200], calendar=USEquityCalendarAdapter(calendar_id="XNAS"))
    assert ds.vwap_session_context_issues[0].startswith("CALENDAR_NOT_VERIFIED")   # XNAS is partially verified
    assert man.render_status == STATUS_INCOMPLETE
    ctx = US4[78:112]
    changed = ctx[:5] + [dataclasses.replace(ctx[5], volume=ctx[5].volume + 1)] + ctx[6:]
    with pytest.raises(ProvenanceError):                            # context must equal any repeated warm-up record
        build_data_snapshot(instrument_id=ctx[0].instrument_id, timeframe="5m",
                            decision_timestamp_utc=decision_after(US4[-1]), availability_mode=AVAILABILITY_AS_KNOWN,
                            visible_candles=US4[-200:], warmup_candles=ctx, dataset_manifest=manifest_of(US4),
                            instrument_spec_version=spec_version(), session_context_candles=changed, calendar=XNYS)
    with pytest.raises(ChartContractError):                         # context from another session
        vwap_chart(US4, US4[-200:], US4[0:34])
    ds_ctx = build_data_snapshot(instrument_id=ctx[0].instrument_id, timeframe="5m",
                                 decision_timestamp_utc=decision_after(US4[-1]), availability_mode=AVAILABILITY_AS_KNOWN,
                                 visible_candles=US4[-200:], warmup_candles=[], dataset_manifest=manifest_of(US4),
                                 instrument_spec_version=spec_version(), session_context_candles=ctx, calendar=XNYS)
    no_vwap = ChartSpec.create(instrument_id=ctx[0].instrument_id, timeframe="5m",
                               decision_timestamp_utc=ds_ctx.decision_timestamp_utc,
                               data_snapshot_id=ds_ctx.data_snapshot_id, display_timezone="America/New_York")
    with pytest.raises(ChartContractError):                         # context is VWAP-only
        build_chart_snapshot_manifest(spec=no_vwap, data_snapshot=ds_ctx, renderer=renderer(), created_at_utc=CREATED)
    assert spec_for(snapshot()).overlay_specs == ()                 # default overlay list is still empty
    late_ctx = ctx[:-1] + [dataclasses.replace(ctx[-1], received_at_utc=US4[-1].timestamp_end_utc + timedelta(days=1))]
    with pytest.raises(LookaheadError):                             # context obeys the no-lookahead rules
        vwap_chart(US4, US4[-200:], late_ctx)


def test_p1c_us_dst_and_pre_market_sessions() -> None:
    dst = us_series([date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9)])   # 234 bars; window starts in Mar 5
    ds, _, man = vwap_chart(dst, dst[-200:], dst[0:34])
    opens = dict(ds.session_opens_utc)
    assert opens["XNYS_2026-03-06"] == "2026-03-06T14:30:00+00:00"   # EST open
    assert opens["XNYS_2026-03-09"] == "2026-03-09T13:30:00+00:00"   # EDT open
    assert man.render_status == STATUS_MODEL_READY and man.display_utc_offsets_minutes == (-300, -240)
    pre = session_candles([date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)], iid=US4[0].instrument_id,
                          market="US", asset_class="EQUITY", segment="US_EQUITY", exchange="NASDAQ", cal_id="XNYS",
                          cal_ver="2026.1", tz=NY, open_t=time(4, 0), bars=66, sid_prefix="XNYS", session="PRE_MARKET")
    with pytest.raises(ChartContractError):                         # PRE_MARKET needs an explicit allowlist
        vwap_chart(pre, pre[-200:])
    ds_pre, _, man_pre = vwap_chart(pre, pre[:200], sessions=("PRE_MARKET",))
    assert man_pre.sessions_present == ("PRE_MARKET",)              # stays distinguishable from REGULAR
    assert any(i.startswith("SESSION_START_NOT_PROVABLE:PRE_MARKET") for i in ds_pre.vwap_session_context_issues)
    assert man_pre.render_status == STATUS_INCOMPLETE


def test_p1c_india_sessions() -> None:
    ind = in_series([date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)])   # 300 bars
    visible, context = ind[-200:], ind[75:100]
    assert context[0].timestamp_start_utc == datetime(2026, 1, 6, 3, 45, tzinfo=UTC)          # 09:15 IST
    ds, _, man = vwap_chart(ind, visible, context, calendar=XNSE, tz="Asia/Kolkata",
                            sv=spec_version(instrument_id=IN_IID))
    assert man.render_status == STATUS_MODEL_READY and man.display_timezone == "Asia/Kolkata"
    assert all(o.endswith("T03:45:00+00:00") for _, o in ds.session_opens_utc)
    assert man.visible_start_display["local_iso"].endswith("+05:30")
    _, _, bad = vwap_chart(ind, visible, calendar=XNSE, tz="Asia/Kolkata", sv=spec_version(instrument_id=IN_IID))
    assert bad.render_status == STATUS_INCOMPLETE


# ================================================================================================ P2-A

def test_p2a_quality_summary_identity_is_float_free_and_exact() -> None:
    ints = dataset_manifest(quality_summary={"rows": 312, "gaps": 0})
    assert dataset_manifest_identity(ints)[0] == dataset_manifest_identity(dataset_manifest(quality_summary={"gaps": 0, "rows": 312}))[0]
    as_str = dataset_manifest_identity(dataset_manifest(quality_summary={"coverage": "0.5"}))[0]
    as_dec = dataset_manifest_identity(dataset_manifest(quality_summary={"coverage": Decimal("0.50")}))[0]
    as_float = dataset_manifest_identity(dataset_manifest(quality_summary={"coverage": 0.5}))[0]
    assert as_str == as_dec == as_float                             # 0.5 is exactly representable
    tenth = dataset_manifest_identity(dataset_manifest(quality_summary={"coverage": 0.1}))[0]
    assert tenth != dataset_manifest_identity(dataset_manifest(quality_summary={"coverage": "0.1"}))[0]  # exact binary value
    nested = dataset_manifest(quality_summary={"per_day": [{"coverage": 0.25}, {"coverage": Decimal("1")}]})
    assert dataset_manifest_identity(nested)[0] == dataset_manifest_identity(
        dataset_manifest(quality_summary={"per_day": [{"coverage": "0.25"}, {"coverage": "1"}]}))[0]
    for bad in (math.nan, math.inf, -math.inf, Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ProvenanceError):
            dataset_manifest_identity(dataset_manifest(quality_summary={"x": bad}))
    with pytest.raises(ProvenanceError):
        dataset_manifest_identity(dataset_manifest(quality_summary={"x": object()}))
    moved = dataset_manifest(quality_summary={"rows": 312, "gaps": 0}, created_at_utc="2031-01-01T00:00:00+00:00",
                             file_paths=["/x/p.parquet"], file_sha256s={"/x/p.parquet": "a" * 64})
    assert dataset_manifest_identity(moved)[0] == dataset_manifest_identity(ints)[0]
    assert snapshot(manifest=dataset_manifest(quality_summary={"coverage": 0.5})).data_snapshot_id == \
        snapshot(manifest=dataset_manifest(quality_summary={"coverage": "0.5"})).data_snapshot_id


# ================================================================================================ P2-B

def _chunk(t: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)


def make_png(*, w=1280, h=720, raw=None, ihdr=None, srgb=b"\x00", srgb_after=False, extra=(), idat=None,
             split_idat=False, iend=b"") -> bytes:
    raw = raw if raw is not None else b"".join(b"\x00" + b"\x10" * (w * 3) for _ in range(h))
    ihdr = ihdr or struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    data = zlib.compress(raw, 1) if idat is None else idat
    idats = [_chunk(b"IDAT", data)] if not split_idat else [_chunk(b"IDAT", data[:100]), _chunk(b"tEXt", b"k\x00v"),
                                                             _chunk(b"IDAT", data[100:])]
    out = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
    if srgb is not None and not srgb_after:
        out += _chunk(b"sRGB", srgb)
    out += b"".join(extra) + b"".join(idats)
    if srgb is not None and srgb_after:
        out += _chunk(b"sRGB", srgb)
    return out + _chunk(b"IEND", iend)


def test_p2b_valid_png_still_accepted() -> None:
    assert validate_chart_png(make_png(), width_px=1280, height_px=720).has_srgb
    assert validate_chart_png(PNG, width_px=1280, height_px=720).srgb_intent == 0
    rows = b"".join(bytes([r % 5]) + b"\x20" * (1280 * 3) for r in range(720))   # all five filter types
    validate_chart_png(make_png(raw=rows), width_px=1280, height_px=720)


@pytest.mark.parametrize("label,png", [
    ("corrupt-zlib-valid-crc", make_png(idat=b"\x78\x9c" + b"\xff" * 64)),
    ("truncated-zlib-stream", make_png(idat=zlib.compress(b"\x00" * (3841 * 720), 1)[:-10])),
    ("truncated-scanline", make_png(raw=b"".join(b"\x00" + b"\x10" * (1280 * 3) for _ in range(720))[:-1])),
    ("missing-scanline", make_png(raw=b"".join(b"\x00" + b"\x10" * (1280 * 3) for _ in range(719)))),
    ("extra-image-data", make_png(raw=b"".join(b"\x00" + b"\x10" * (1280 * 3) for _ in range(721)))),
    ("trailing-zlib-data", make_png(idat=zlib.compress(b"".join(b"\x00" + b"\x10" * 3840 for _ in range(720)), 1) + b"junk")),
    ("invalid-filter-byte", make_png(raw=b"".join((b"\x05" if r == 300 else b"\x00") + b"\x10" * 3840 for r in range(720)))),
    ("ihdr-compression-1", make_png(ihdr=struct.pack(">IIBBBBB", 1280, 720, 8, 2, 1, 0, 0))),
    ("ihdr-filter-1", make_png(ihdr=struct.pack(">IIBBBBB", 1280, 720, 8, 2, 0, 1, 0))),
    ("ihdr-interlaced", make_png(ihdr=struct.pack(">IIBBBBB", 1280, 720, 8, 2, 0, 0, 1))),
    ("ihdr-rgba", make_png(ihdr=struct.pack(">IIBBBBB", 1280, 720, 8, 6, 0, 0, 0))),
    ("ihdr-16bit", make_png(ihdr=struct.pack(">IIBBBBB", 1280, 720, 16, 2, 0, 0, 0))),
    ("wrong-size", make_png(w=1279)),
    ("missing-srgb", make_png(srgb=None)),
    ("srgb-two-bytes", make_png(srgb=b"\x00\x00")),
    ("srgb-bad-intent", make_png(srgb=b"\x04")),
    ("srgb-after-idat", make_png(srgb_after=True)),
    ("two-srgb", make_png(extra=(_chunk(b"sRGB", b"\x01"),))),
    ("iccp-profile", make_png(extra=(_chunk(b"iCCP", b"p\x00\x00" + zlib.compress(b"icc")),))),
    ("non-consecutive-idat", make_png(split_idat=True)),
    ("iend-with-data", make_png(iend=b"x")),
])
def test_p2b_invalid_png_rejected(label, png) -> None:
    with pytest.raises(ImageValidationError):
        validate_chart_png(png, width_px=1280, height_px=720)


def test_p2b_builder_rejects_crc_valid_corrupt_image() -> None:
    with pytest.raises(ImageValidationError):
        manifest_for(snapshot(), image=make_png(idat=b"\x78\x9c" + b"\xff" * 64))
