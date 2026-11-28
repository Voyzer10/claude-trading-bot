"""Phase 0 Step 2: Chart Contract v1.0.0 validation tests (contract only; no renderer)."""
from __future__ import annotations

import dataclasses
import json
import os
import struct
import zlib
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from ml_data.charts import (
    AVAILABILITY_AS_KNOWN,
    AVAILABILITY_EVENT_TIME,
    CHART_CONTRACT_VERSION,
    DARK_V1,
    INTRADAY_V1_200BAR,
    LIGHT_V1,
    STATUS_FAILED,
    STATUS_INCOMPLETE,
    STATUS_MODEL_READY,
    STATUS_PENDING_RENDER,
    STATUS_READY,
    ChartContractError,
    ChartSnapshotManifest,
    ChartSpec,
    ImageValidationError,
    LookaheadError,
    OverlaySpec,
    ProvenanceError,
    RendererInfo,
    axis_timestamp,
    build_chart_snapshot_manifest,
    build_data_snapshot,
    canonical_overlay_id,
    compute_chart_snapshot_id,
    compute_font_fingerprint,
    get_theme,
    is_sha256_hex,
    require_single_theme,
    sha256_hex,
    validate_chart_png,
    verify_chart_image,
    verify_chart_snapshot,
)
from ml_data.instruments.identity import compute_spec_hash
from ml_data.instruments.schemas import InstrumentSpecVersion
from ml_data.storage import CanonicalCandle, DatasetManifest

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
IID = "US:NASDAQ:EQUITY:AAPL#67004d96eaeaf24f2a7aa16221464a2c"
FILE_SHA = "a" * 64
FONT_SHA = compute_font_fingerprint({"DejaVuSans.ttf": "b" * 64})
CREATED = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)


# ------------------------------------------------------------------------------------------------ fixtures

def regular_session_candles(days, *, start_index: int = 0):
    """US equity 5m regular-session candles (09:30-16:00 New York, 78 per day), deterministic Decimal prices."""
    out, i = [], start_index
    for d in days:
        t = datetime.combine(d, time(9, 30), NY).astimezone(UTC)
        for _ in range(78):
            o = Decimal("100") + Decimal(i) / Decimal("100")
            c = o + Decimal("0.05")
            end = t + timedelta(minutes=5)
            out.append(CanonicalCandle(
                instrument_id=IID, market="US", asset_class="EQUITY", segment="US_EQUITY", exchange="NASDAQ",
                provider="alpaca", provider_symbol="AAPL", provider_instrument_id="AAPL",
                timestamp_start_utc=t, timestamp_end_utc=end, event_time_utc=end,
                received_at_utc=end + timedelta(seconds=1), timeframe="5m", trading_date=d,
                trading_session="REGULAR", session_id=f"XNAS_{d.isoformat()}", calendar_id="XNAS",
                calendar_version="2026.1", open=o, high=c + Decimal("0.02"), low=o - Decimal("0.03"), close=c,
                volume=Decimal("1000") + i, provider_feed="iex", source_snapshot_id="snap-1",
                source_record_id=f"rec-{i}", dataset_version="v1", adjustment_mode="RAW",
                retrieval_run_id="run-1", quality_status="VERIFIED",
            ))
            t, i = end, i + 1
    return out


JAN_DAYS = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)]
SERIES = regular_session_candles(JAN_DAYS)          # 312 candles


def dataset_manifest(candles=SERIES, **over) -> DatasetManifest:
    base = dict(
        dataset_id="us_equity_5m", dataset_version="v1", schema_version="1.0.0", markets=["US"],
        providers=["alpaca"], feeds=["iex"], instrument_ids=[IID],
        requested_start_utc="2026-01-01T00:00:00+00:00", requested_end_utc="2026-12-31T00:00:00+00:00",
        actual_start_utc=candles[0].timestamp_start_utc.isoformat(),
        actual_end_utc=candles[-1].timestamp_end_utc.isoformat(),
        source_snapshot_ids=["snap-1"], adjustment_modes=["RAW"], calendar_versions=["XNAS:2026.1"],
        row_count=len(candles), duplicate_count=0, invalid_count=0, missing_timestamps_count=0,
        pagination_complete=True, quality_summary={"status": "VERIFIED"},
        file_paths=["data/canonical/candles/part-v1-0001.parquet"],
        file_sha256s={"data/canonical/candles/part-v1-0001.parquet": FILE_SHA},
        created_at_utc="2026-11-28T00:00:00+00:00", git_commit=None,
    )
    base.update(over)
    return DatasetManifest(**base)


SPEC = {"tick_size": "0.01", "symbol": "AAPL"}


def spec_version(**over) -> InstrumentSpecVersion:
    """A consistent spec revision: spec_hash is always compute_spec_hash(specification) unless a test overrides it."""
    spec = over.pop("specification", SPEC)
    spec_hash = over.pop("spec_hash") if "spec_hash" in over else compute_spec_hash(spec)
    base = dict(version_id=1, instrument_id=IID, effective_from=datetime(2025, 1, 1, tzinfo=UTC), effective_to=None,
                spec_hash=spec_hash, specification=spec,
                recorded_at=datetime(2025, 12, 31, tzinfo=UTC))   # point-in-time: known before every test decision
    base.update(over)
    return InstrumentSpecVersion(**base)


def renderer(**over) -> RendererInfo:
    base = dict(renderer_name="ml-chart-renderer", renderer_version="1.0.0", renderer_build_id="build-1",
                font_fingerprint=FONT_SHA)
    base.update(over)
    return RendererInfo(**base)


def png_bytes(width=1280, height=720, *, color_type=2, srgb=True, iccp=False) -> bytes:
    def chunk(t: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)
    channels = {2: 3, 6: 4}[color_type]
    raw = b"".join(b"\x00" + b"\x10" * (width * channels) for _ in range(height))
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
    if srgb:
        out += chunk(b"sRGB", b"\x00")
    if iccp:
        out += chunk(b"iCCP", b"x\x00\x00" + zlib.compress(b"profile"))
    return out + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b"")


PNG = png_bytes()


def decision_after(candle, seconds=2):
    return candle.timestamp_end_utc + timedelta(seconds=seconds)


def snapshot(visible=None, warmup=(), *, decision=None, mode=AVAILABILITY_AS_KNOWN, manifest=None, sv=None):
    visible = list(SERIES[-200:] if visible is None else visible)
    return build_data_snapshot(
        instrument_id=IID, timeframe="5m", decision_timestamp_utc=decision or decision_after(visible[-1]),
        availability_mode=mode, visible_candles=visible, warmup_candles=list(warmup),
        dataset_manifest=manifest or dataset_manifest(), instrument_spec_version=sv or spec_version(),
    )


def spec_for(ds, **over) -> ChartSpec:
    kw = dict(instrument_id=IID, timeframe="5m", decision_timestamp_utc=ds.decision_timestamp_utc,
              data_snapshot_id=ds.data_snapshot_id, display_timezone="America/New_York",
              allowed_sessions=("REGULAR",), availability_mode=ds.availability_mode)
    kw.update(over)
    return ChartSpec.create(**kw)


def manifest_for(ds, spec=None, *, rend=None, image=PNG, bounds=None, **over):
    """bounds: optional renderer-reported price-axis bounds (a cross-check; the spec's policy decides them)."""
    spec = spec or spec_for(ds)
    kw = dict(spec=spec, data_snapshot=ds, renderer=rend or renderer(), created_at_utc=CREATED)
    if image is not None:
        kw.update(image_bytes=image, image_path="charts/aapl.png")
    if bounds is not None:
        kw.update(price_axis_min=bounds[0], price_axis_max=bounds[1])
    kw.update(over)
    return build_chart_snapshot_manifest(**kw)


def full_chart(**over):
    ds = snapshot()
    spec = spec_for(ds)
    return ds, spec, manifest_for(ds, spec, **over)


# ------------------------------------------------------------------------------- 1-2: canvas and image format

def test_01_default_profile_is_1280x720_and_spec_is_explicit() -> None:
    p = INTRADAY_V1_200BAR
    assert (p.width_px, p.height_px) == (1280, 720)
    assert Decimal(p.width_px) / Decimal(p.height_px) == Decimal(16) / Decimal(9)
    ds, spec, man = full_chart()
    d = spec.to_dict()
    assert d["width_px"] == 1280 and d["height_px"] == 720 and d["chart_profile_id"] == "intraday_v1_200bar"
    assert (man.width_px, man.height_px) == (1280, 720)
    for name, bad in (("width_px", 1920), ("height_px", 1080)):   # no implicit resizing / unversioned variants
        with pytest.raises(ChartContractError):
            dataclasses.replace(spec, **{name: bad})
    with pytest.raises(ChartContractError):
        dataclasses.replace(spec, chart_profile_id="intraday_v1_300bar")


def test_02_png_rgb_srgb_format_is_required() -> None:
    _, spec, _ = full_chart()
    assert (spec.image_format, spec.color_mode, spec.color_space) == ("PNG", "RGB", "sRGB")
    info = validate_chart_png(PNG, width_px=1280, height_px=720)
    assert info.color_type == 2 and info.bit_depth == 8 and info.has_srgb
    for bad in (png_bytes(color_type=6), png_bytes(srgb=False), png_bytes(iccp=True), png_bytes(1279, 720),
                b"GIF89a" + PNG[6:], PNG[:-5]):
        with pytest.raises(ImageValidationError):
            validate_chart_png(bad, width_px=1280, height_px=720)
    for name, bad in (("image_format", "JPEG"), ("color_mode", "RGBA"), ("color_space", "DisplayP3")):
        with pytest.raises(ChartContractError):
            dataclasses.replace(spec, **{name: bad})
    with pytest.raises(ImageValidationError):                      # the builder validates the image too
        manifest_for(snapshot(), image=png_bytes(srgb=False))


# ------------------------------------------------------------------------------- 3-6: candle counts and gaps

def test_03_exactly_200_visible_candles_for_default_profile() -> None:
    ds, spec, man = full_chart()
    assert spec.visible_candle_count == 200 == ds.visible_count == man.actual_visible_candle_count
    assert man.render_status == STATUS_MODEL_READY and man.status_reasons == ()
    assert man.visible_start_utc == SERIES[-200].timestamp_start_utc
    assert man.visible_end_utc == SERIES[-1].timestamp_end_utc
    with pytest.raises(ChartContractError):                         # more than the profile shows is rejected
        manifest_for(snapshot(SERIES[-201:]))


def test_04_insufficient_visible_candles_are_incomplete_never_model_ready() -> None:
    ds = snapshot(SERIES[-199:])
    man = manifest_for(ds)
    assert man.render_status == STATUS_INCOMPLETE and not man.is_model_ready
    assert "INSUFFICIENT_VISIBLE_CANDLES" in man.status_reasons and man.actual_visible_candle_count == 199
    for st in (STATUS_READY, STATUS_MODEL_READY, STATUS_PENDING_RENDER):
        with pytest.raises(ChartContractError):
            dataclasses.replace(man, render_status=st, status_reasons=())
    with pytest.raises(ChartContractError):
        snapshot([], decision=decision_after(SERIES[-1]))


def test_05_warmup_candles_are_separate_from_visible_candles() -> None:
    ema = OverlaySpec.create("EMA", {"period": 20, "source": "CLOSE"}, style_ref="ema_fast")
    assert ema.warmup_bars == 60
    visible, warm = SERIES[-200:], SERIES[-260:-200]
    ds = snapshot(visible, warm)
    spec = spec_for(ds, overlay_specs=[ema])
    man = manifest_for(ds, spec)
    assert spec.warmup_candle_count == 60 == man.warmup_candle_count == man.required_warmup_candle_count
    assert man.actual_visible_candle_count == 200                    # warm-up is never counted as visible
    assert man.visible_start_utc == visible[0].timestamp_start_utc   # nor rendered: the window starts after it
    assert ds.warmup_start_utc == warm[0].timestamp_start_utc < ds.visible_start_utc
    assert ds.data_snapshot_id != snapshot(visible).data_snapshot_id  # warm-up records are part of data identity
    short = snapshot(visible, warm[-30:])
    m_short = manifest_for(short, spec_for(short, overlay_specs=[ema]))
    assert m_short.render_status == STATUS_INCOMPLETE and "INSUFFICIENT_WARMUP_CANDLES" in m_short.status_reasons
    with pytest.raises(ChartContractError):                         # warm-up must strictly precede the window
        snapshot(visible, [SERIES[-150]])
    with pytest.raises(ChartContractError):                         # spec cannot under-declare overlay warm-up
        spec_for(ds, overlay_specs=[ema], warmup_candle_count=10)


def test_06_missing_candles_are_detected_not_fabricated() -> None:
    gapped = SERIES[-201:-101] + SERIES[-100:]                      # drop one bar inside a session
    assert len(gapped) == 200
    ds = snapshot(gapped)
    assert ds.intra_session_gap_count == 1 and ds.missing_bar_count == 1
    man = manifest_for(ds)
    assert man.actual_visible_candle_count == 200                    # nothing was padded in
    assert man.render_status == STATUS_READY and man.status_reasons == ("INTRA_SESSION_GAPS",)
    with pytest.raises(ChartContractError):
        dataclasses.replace(man, render_status=STATUS_MODEL_READY, status_reasons=())
    assert snapshot().intra_session_gap_count == 0                   # overnight closes are compressed, not gaps
    with pytest.raises(ChartContractError):                          # duplicates rejected
        snapshot(SERIES[-200:-1] + [SERIES[-2]])


# --------------------------------------------------------------------------------------------- 7: overlays

def test_07_overlay_identity_and_parameter_validation() -> None:
    bb = OverlaySpec.create("BOLLINGER", {"period": 20, "source": "CLOSE", "stddev_multiplier": "2.0"}, style_ref="bollinger")
    assert bb.overlay_id == "bollinger_20_close_2" and bb.parameters["stddev_multiplier"] == "2" and bb.warmup_bars == 19
    vw = OverlaySpec.create("VWAP", {"price_source": "HLC3", "reset": "SESSION"}, style_ref="vwap")
    assert vw.overlay_id == "vwap_hlc3_session" and vw.session_anchored and vw.warmup_bars == 0
    sma = OverlaySpec.create("SMA", {"period": 50, "source": "CLOSE"}, style_ref="sma")
    assert sma.overlay_id == "sma_50_close" and sma.calculation_version == "sma_v1"
    assert canonical_overlay_id("EMA", {"period": 50, "source": "CLOSE"}) == "ema_50_close"
    good = OverlaySpec.create("EMA", {"period": 20, "source": "CLOSE"}, style_ref="ema_fast").to_dict()
    assert OverlaySpec.from_dict(good).to_dict() == good
    bad_variants = [
        {"overlay_id": "my_ema"}, {"calculation_version": "ema_v2"}, {"warmup_bars": 20}, {"placement": "VOLUME_PANEL"},
        {"overlay_type": "RSI"}, {"parameters": {"period": 1, "source": "CLOSE"}},
        {"parameters": {"period": 20, "source": "CLOSE", "extra": 1}}, {"parameters": {"period": 20.0, "source": "CLOSE"}},
        {"parameters": {"period": 20, "source": "HIGH"}}, {"visible": "yes"}, {"session_anchored": True},
    ]
    for change in bad_variants:
        with pytest.raises(ChartContractError):
            OverlaySpec.from_dict({**good, **change})
    for m in (2.0, "0", "-1", "abc", True):
        with pytest.raises(ChartContractError):
            OverlaySpec.create("BOLLINGER", {"period": 20, "source": "CLOSE", "stddev_multiplier": m}, style_ref="bollinger")
    ds = snapshot(SERIES[-200:], SERIES[-260:-200])
    ema = OverlaySpec.from_dict(good)
    with pytest.raises(ChartContractError):                         # duplicate overlay ids
        spec_for(ds, overlay_specs=[ema, ema])
    with pytest.raises(ChartContractError):                         # style must resolve through the theme
        spec_for(ds, overlay_specs=[OverlaySpec.create("EMA", {"period": 20, "source": "CLOSE"}, style_ref="neon")])
    assert spec_for(snapshot()).overlay_specs == ()                 # default: no overlays, nothing implicit


# ------------------------------------------------------------------------------------------- 8: themes

def test_08_deterministic_theme_selection() -> None:
    assert get_theme("dark_v1", "1.0.0") is DARK_V1 and get_theme("light_v1", "1.0.0") is LIGHT_V1
    assert (DARK_V1.background, DARK_V1.plot_panel, DARK_V1.grid, DARK_V1.text, DARK_V1.bullish, DARK_V1.bearish,
            DARK_V1.neutral) == ("#0B1220", "#111827", "#273449", "#CBD5E1", "#22C55E", "#EF4444", "#94A3B8")
    assert (LIGHT_V1.background, LIGHT_V1.plot_panel, LIGHT_V1.grid, LIGHT_V1.text, LIGHT_V1.bullish, LIGHT_V1.bearish,
            LIGHT_V1.neutral) == ("#FFFFFF", "#FFFFFF", "#E2E8F0", "#334155", "#15803D", "#B91C1C", "#64748B")
    ds = snapshot()
    spec = spec_for(ds)
    assert (spec.theme_id, spec.theme_version) == ("dark_v1", "1.0.0")
    assert DARK_V1.theme_hash() == get_theme("dark_v1", "1.0.0").theme_hash()
    for tid, ver in (("dark_v1", "1.0.1"), ("dark_v2", "1.0.0"), ("dark", "latest")):
        with pytest.raises(ChartContractError):
            get_theme(tid, ver)
    assert require_single_theme([("dark_v1", "1.0.0")] * 3) == ("dark_v1", "1.0.0")
    with pytest.raises(ChartContractError):
        require_single_theme([("dark_v1", "1.0.0"), ("light_v1", "1.0.0")])


# --------------------------------------------------------------------------------- 9-13: time and lookahead

def test_09_utc_is_authoritative_and_display_timezone_is_explicit() -> None:
    _, spec, man = full_chart()
    d = json.loads(man.to_json())
    assert d["visible_start_utc"].endswith("+00:00") and d["decision_timestamp_utc"].endswith("+00:00")
    assert man.display_timezone == spec.display_timezone == "America/New_York"
    assert man.visible_start_display["local_iso"].endswith("-05:00")
    assert man.visible_start_display["utc"] == d["visible_start_utc"]
    with pytest.raises(ChartContractError):                         # US equity must display in New York time
        manifest_for(snapshot(), spec_for(snapshot(), display_timezone="Asia/Kolkata"))
    with pytest.raises(ChartContractError):
        spec_for(snapshot(), display_timezone="Mars/Base")
    naive = dict(spec.to_dict(), decision_timestamp_utc="2026-01-08T21:00:02")
    with pytest.raises(ChartContractError):
        ChartSpec.from_dict(naive)


def test_10_dst_safe_axis_timestamp_metadata() -> None:
    first = axis_timestamp(datetime(2026, 11, 1, 5, 30, tzinfo=UTC), "America/New_York")
    second = axis_timestamp(datetime(2026, 11, 1, 6, 30, tzinfo=UTC), "America/New_York")
    assert first.local_iso[:19] == second.local_iso[:19] == "2026-11-01T01:30:00"   # same wall clock twice
    assert first.label != second.label and first.local_iso != second.local_iso      # still distinguishable
    assert (first.utc_offset_minutes, second.utc_offset_minutes) == (-240, -300)
    assert (first.tz_abbreviation, second.tz_abbreviation) == ("EDT", "EST")
    dst = regular_session_candles([date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9)])[-200:]
    ds = snapshot(dst, manifest=dataset_manifest(dst))
    man = manifest_for(ds)
    assert man.display_utc_offsets_minutes == (-300, -240)          # window crosses the DST change
    assert man.visible_start_display["local_iso"].endswith("-05:00")
    assert man.visible_end_display["local_iso"].endswith("-04:00")
    assert man.visible_end_display["local_iso"].startswith("2026-03-09T16:00:00")


def test_11_decision_timestamp_cutoff() -> None:
    last = SERIES[-1]
    with pytest.raises(LookaheadError):                             # closed, but not yet received (as-known)
        snapshot(decision=last.timestamp_end_utc)
    ds = snapshot(decision=last.timestamp_end_utc, mode=AVAILABILITY_EVENT_TIME)   # research reconstruction
    assert ds.decision_timestamp_utc == last.timestamp_end_utc
    assert snapshot(decision=last.received_at_utc).last_visible_received_at_utc == last.received_at_utc
    _, _, man = full_chart()
    assert man.visible_end_utc <= man.last_visible_received_at_utc <= man.decision_timestamp_utc
    with pytest.raises(LookaheadError):                             # manifest cannot claim a window after decision
        dataclasses.replace(man, decision_timestamp_utc=man.visible_end_utc - timedelta(minutes=1))
    ds2 = snapshot()
    with pytest.raises(ProvenanceError):                            # spec decision must equal the data decision
        manifest_for(ds2, spec_for(ds2, decision_timestamp_utc=ds2.decision_timestamp_utc + timedelta(minutes=5)))


def test_12_future_candles_are_rejected() -> None:
    visible = SERIES[-200:]
    decision = visible[-2].received_at_utc                         # the last bar is still open/unreceived
    with pytest.raises(LookaheadError):
        snapshot(visible, decision=decision)
    late = dataclasses.replace(visible[-1], received_at_utc=visible[-1].timestamp_end_utc + timedelta(hours=1))
    with pytest.raises(LookaheadError):
        snapshot(visible[:-1] + [late])
    ok = snapshot(visible[:-1] + [late], mode=AVAILABILITY_EVENT_TIME, decision=decision_after(visible[-1]))
    assert ok.visible_count == 200


def test_13_future_overlay_data_is_rejected() -> None:
    visible, warm = SERIES[-200:], list(SERIES[-260:-200])
    warm[-1] = dataclasses.replace(warm[-1], received_at_utc=visible[-1].timestamp_end_utc + timedelta(days=1))
    with pytest.raises(LookaheadError):                             # warm-up feeding an overlay arrived later
        snapshot(visible, warm)
    with pytest.raises(ChartContractError):                         # warm-up taken from inside/after the window
        snapshot(visible[:-1], [visible[-1]])


# ------------------------------------------------------------------------------------ 14-19: identities

def test_14_data_snapshot_id_is_deterministic() -> None:
    a, b = snapshot(), snapshot(list(SERIES[-200:]))
    assert a.data_snapshot_id == b.data_snapshot_id and is_sha256_hex(a.data_snapshot_id)
    rebuilt = [CanonicalCandle.from_json(c.to_json()) for c in SERIES[-200:]]
    assert snapshot(rebuilt).data_snapshot_id == a.data_snapshot_id
    moved = dataset_manifest(file_paths=["/elsewhere/part.parquet"], file_sha256s={"/elsewhere/part.parquet": FILE_SHA},
                             created_at_utc="2030-01-01T00:00:00+00:00")
    assert snapshot(manifest=moved).data_snapshot_id == a.data_snapshot_id   # location/creation time not identity


def test_15_chart_snapshot_id_is_deterministic_and_manifest_round_trips() -> None:
    ds, spec, man = full_chart()
    _, _, man2 = full_chart()
    assert man.chart_snapshot_id == man2.chart_snapshot_id and is_sha256_hex(man.chart_snapshot_id)
    assert ChartSpec.from_dict(json.loads(json.dumps(spec.to_dict()))).spec_hash() == spec.spec_hash()
    assert ChartSnapshotManifest.from_json(man.to_json()) == man
    later = dataclasses.replace(man, created_at_utc=CREATED + timedelta(days=1))
    assert later.chart_snapshot_id == man.chart_snapshot_id and later.semantic_dict() == man.semantic_dict()
    assert len({man.data_snapshot_id, man.chart_snapshot_id, man.image_sha256, man.chart_spec_hash}) == 4
    verify_chart_snapshot(man, spec=spec, data_snapshot=ds, renderer=renderer())


def test_16_image_sha256_validation(tmp_path) -> None:
    _, _, man = full_chart()
    assert man.image_sha256 == sha256_hex(PNG) and man.image_size_bytes == len(PNG)
    (tmp_path / "charts").mkdir()
    path = tmp_path / "charts" / "aapl.png"
    path.write_bytes(PNG)
    verify_chart_image(man, str(tmp_path))
    tampered = bytearray(PNG)
    tampered[-20] ^= 0xFF
    path.write_bytes(bytes(tampered))
    with pytest.raises(ImageValidationError):
        verify_chart_image(man, str(tmp_path))
    os.remove(path)
    with pytest.raises(ImageValidationError):
        verify_chart_image(man, str(tmp_path))
    with pytest.raises(ChartContractError):
        dataclasses.replace(man, image_sha256="A" * 64)
    with pytest.raises(ChartContractError):
        dataclasses.replace(man, image_sha256=man.image_sha256[:32])


def test_17_changing_theme_changes_chart_identity_not_data_identity() -> None:
    ds, spec, dark = full_chart()
    light = manifest_for(ds, spec_for(ds, theme_id="light_v1", theme_version="1.0.0"))
    assert light.data_snapshot_id == dark.data_snapshot_id
    assert light.chart_snapshot_id != dark.chart_snapshot_id and light.chart_spec_hash != dark.chart_spec_hash
    assert (light.theme_id, dark.theme_id) == ("light_v1", "dark_v1")


def test_18_changing_candle_input_changes_data_identity() -> None:
    base = snapshot().data_snapshot_id
    v = list(SERIES[-200:])
    changes = [
        dataclasses.replace(v[100], close=v[100].close + Decimal("0.01"), high=v[100].high + Decimal("0.01")),
        dataclasses.replace(v[100], volume=v[100].volume + 1),
        dataclasses.replace(v[100], quality_flags=("late_arrival",)),
        dataclasses.replace(v[100], received_at_utc=v[100].received_at_utc + timedelta(seconds=1)),
        dataclasses.replace(v[100], source_record_id="rec-other"),
    ]
    ids = {snapshot(v[:100] + [c] + v[101:]).data_snapshot_id for c in changes}
    assert base not in ids and len(ids) == len(changes)
    warm = list(SERIES[-260:-200])
    warm_changed = warm[:10] + [dataclasses.replace(warm[10], volume=warm[10].volume + 1)] + warm[11:]
    assert snapshot(v, warm).data_snapshot_id != snapshot(v, warm_changed).data_snapshot_id  # warm-up values count
    assert snapshot(decision=decision_after(v[-1], 60)).data_snapshot_id != base
    assert snapshot(sv=spec_version(version_id=2, specification={**SPEC, "tick_size": "0.05"})).data_snapshot_id != base
    assert snapshot(manifest=dataset_manifest(quality_summary={"status": "REVIEWED"})).data_snapshot_id != base


def test_19_changing_renderer_changes_chart_identity() -> None:
    ds, spec, man = full_chart()
    for change in ({"renderer_version": "1.0.1"}, {"renderer_build_id": "build-2"},
                   {"font_fingerprint": compute_font_fingerprint({"DejaVuSans.ttf": "d" * 64})}):
        other = manifest_for(ds, spec, rend=renderer(**change))
        assert other.data_snapshot_id == man.data_snapshot_id and other.chart_spec_hash == man.chart_spec_hash
        assert other.chart_snapshot_id != man.chart_snapshot_id
    with pytest.raises(ProvenanceError):
        verify_chart_snapshot(man, spec=spec, data_snapshot=ds, renderer=renderer(renderer_version="2.0.0"))
    assert compute_chart_snapshot_id(data_snapshot_id=ds.data_snapshot_id, chart_spec_hash=spec.spec_hash(),
                                     renderer=renderer(), theme_id="dark_v1", theme_version="1.0.0") == man.chart_snapshot_id


# ------------------------------------------------------------------------------------- 20: provenance

def test_20_dataset_and_source_manifest_provenance_is_preserved() -> None:
    ds, spec, man = full_chart()
    dm = dataset_manifest()
    assert (man.dataset_id, man.dataset_version) == (dm.dataset_id, dm.dataset_version)
    assert man.source_file_sha256s == (FILE_SHA,) and man.source_snapshot_ids == ("snap-1",)
    assert is_sha256_hex(man.dataset_manifest_sha256) and man.instrument_spec_hash == spec_version().spec_hash
    assert (man.calendar_id, man.calendar_version, man.adjustment_mode) == ("XNAS", "2026.1", "RAW")
    other_part = dataset_manifest(file_sha256s={"data/canonical/candles/part-v1-0001.parquet": "e" * 64})
    assert snapshot(manifest=other_part).data_snapshot_id != ds.data_snapshot_id
    v = list(SERIES[-200:])
    bad_inputs = [
        dict(visible=v[:-1] + [dataclasses.replace(v[-1], source_snapshot_id="snap-unknown")]),
        dict(visible=v[:-1] + [dataclasses.replace(v[-1], dataset_version="v2")]),
        dict(visible=v[:-1] + [dataclasses.replace(v[-1], provider_feed="sip")]),
        dict(manifest=dataset_manifest(instrument_ids=["US:NASDAQ:EQUITY:MSFT#" + "0" * 32])),
        dict(manifest=dataset_manifest(calendar_versions=["XNAS:2025.1"])),
        dict(manifest=dataset_manifest(file_sha256s={}, file_paths=[])),
        dict(manifest=dataset_manifest(actual_end_utc=v[-2].timestamp_end_utc.isoformat())),
        dict(sv=spec_version(effective_from=datetime(2026, 6, 1, tzinfo=UTC))),
        dict(sv=spec_version(effective_to=datetime(2025, 6, 1, tzinfo=UTC))),
        dict(sv=spec_version(instrument_id="US:NASDAQ:EQUITY:MSFT#" + "0" * 32)),
    ]
    for kw in bad_inputs:
        with pytest.raises(ProvenanceError):
            snapshot(**kw)
    with pytest.raises(ProvenanceError):                            # spec must point at this exact data snapshot
        manifest_for(ds, dataclasses.replace(spec, data_snapshot_id="f" * 64))


# -------------------------------------------------------------------------------- status rules (extra)

def test_status_rules_never_model_ready_without_verified_inputs() -> None:
    unverified = list(SERIES[-200:])
    unverified[5] = dataclasses.replace(unverified[5], quality_status="UNVERIFIED")
    m1 = manifest_for(snapshot(unverified))
    assert m1.render_status == STATUS_READY and "QUALITY_NOT_VERIFIED" in m1.status_reasons
    m2 = manifest_for(snapshot(manifest=dataset_manifest(pagination_complete=False)))
    assert m2.render_status == STATUS_READY and "DATASET_PAGINATION_INCOMPLETE" in m2.status_reasons
    pending = manifest_for(snapshot(), image=None)
    assert pending.render_status == STATUS_PENDING_RENDER and pending.image_sha256 is None
    failed = manifest_for(snapshot(), image=None, render_error="font missing")
    assert failed.render_status == STATUS_FAILED and "RENDER_FAILED" in failed.status_reasons
    assert (pending.price_axis_min, pending.price_axis_max) == ("100.9855", "103.2845")   # policy-derived
    with pytest.raises(ChartContractError):                         # reported bounds must equal the policy bounds
        manifest_for(snapshot(), bounds=("101.5", "110"))           # visible low is 101.09
    with pytest.raises(ChartContractError):
        manifest_for(snapshot(), bounds=("99", "102"))              # visible high is 103.18
    with pytest.raises(ChartContractError):
        manifest_for(snapshot(), bounds=(100.0, 110.0))
    assert manifest_for(snapshot(), bounds=("100.9855", "103.2845")).render_status == STATUS_MODEL_READY
    with pytest.raises(ChartContractError):                         # a session outside the allowlist
        manifest_for(snapshot(), spec_for(snapshot(), allowed_sessions=("PRE_MARKET",)))
    with pytest.raises(ChartContractError):
        spec_for(snapshot(), allowed_sessions=("CLOSED",))
    _, spec, man = full_chart()
    assert man.chart_contract_version == spec.chart_contract_version == CHART_CONTRACT_VERSION == "1.0.0"
