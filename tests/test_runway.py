from __future__ import annotations

import json
from pathlib import Path
import pytest

from runway import (
    PackagingSpec,
    RefillEconomicsConfig,
    VelocityWindow,
    compute_safety_stock,
    main,
    round_up_to_multiple,
    run_from_model_dict,
    simulate_refill_cohort,
    solve_packaging_runway,
    z_score_for_service_level,
)


ROOT = Path(__file__).resolve().parent.parent


def _meru_spec() -> PackagingSpec:
    return PackagingSpec(
        sku_code="HERM-MERU-COMPACT-50T",
        vessel_name="Meru Gold-Plated Magnetic Pocket Compact (50 Tablets)",
        origin_hub="Dongguan, Guangdong, CN",
        ex_factory_unit_usd=2.70,
        moq_units=2500,
        carton_pack_units=100,
        production_days=35,
        ocean_freight_days=28,
        air_freight_days=7,
        co_packer_fill_days=10,
        lead_time_std_days=4.5,
        ocean_freight_per_unit_usd=0.22,
        air_freight_per_unit_usd=1.18,
        duty_rate=0.075,
        deposit_share=0.30,
    )


def test_velocity_window_weighted_average() -> None:
    vw = VelocityWindow(units_30d=1500, units_60d=2400, units_90d=2700)
    # 30d=50/day (0.5), 60d=40/day (0.3), 90d=30/day (0.2) => 25 + 12 + 6 = 43.0
    assert vw.daily_velocity() == pytest.approx(43.0)


def test_velocity_window_rejects_negative_units() -> None:
    with pytest.raises(ValueError):
        VelocityWindow(units_30d=-10, units_60d=100, units_90d=200).daily_velocity()


def test_z_score_lookup_and_approximation() -> None:
    assert z_score_for_service_level(0.95) == pytest.approx(1.6449, rel=1e-3)
    assert z_score_for_service_level(0.96) == pytest.approx(1.7507, rel=1e-3)
    with pytest.raises(ValueError):
        z_score_for_service_level(0.40)


def test_safety_stock_scales_with_lead_time_and_service_level() -> None:
    ss_95 = compute_safety_stock(50.0, 8.0, lead_days=73, lead_time_std_days=4.0, service_level=0.95)
    ss_99 = compute_safety_stock(50.0, 8.0, lead_days=73, lead_time_std_days=4.0, service_level=0.99)
    assert ss_99 > ss_95 > 0
    assert compute_safety_stock(0.0, 0.0, lead_days=73, lead_time_std_days=4.0) == 0


def test_round_up_to_multiple() -> None:
    assert round_up_to_multiple(0, 100) == 0
    assert round_up_to_multiple(2501, 100) == 2600
    assert round_up_to_multiple(5000, 100) == 5000


def test_ocean_only_when_healthy_inventory() -> None:
    spec = _meru_spec()
    report = solve_packaging_runway(
        spec=spec,
        usable_on_hand_units=6000,
        daily_velocity=45.0,
        daily_demand_std=8.0,
        target_order_units=5000,
    )
    assert report.ocean_total_lead_days == 73
    assert report.air_total_lead_days == 52
    assert report.ocean_reorder_breached is False
    assert report.recommended_air_bridge_units == 0
    assert report.recommended_ocean_balance_units == 5000
    assert report.po_ex_factory_total_usd == pytest.approx(13500.00)
    assert report.po_deposit_usd == pytest.approx(4050.00)
    assert report.po_balance_usd == pytest.approx(9450.00)


def test_air_bridge_split_triggered_when_below_ocean_rop() -> None:
    spec = _meru_spec()
    report = solve_packaging_runway(
        spec=spec,
        usable_on_hand_units=3100,
        daily_velocity=50.0,
        daily_demand_std=9.5,
        target_order_units=5000,
    )
    assert report.ocean_reorder_breached is True
    assert report.recommended_air_bridge_units > 0
    assert report.recommended_air_bridge_units % spec.carton_pack_units == 0
    assert (
        report.recommended_air_bridge_units + report.recommended_ocean_balance_units
        == report.recommended_order_units
    )
    assert report.air_bridge_premium_usd > 0


def test_moq_enforced_when_target_below_moq() -> None:
    spec = _meru_spec()
    report = solve_packaging_runway(
        spec=spec,
        usable_on_hand_units=5000,
        daily_velocity=30.0,
        target_order_units=1200,
    )
    assert report.recommended_order_units == 2500


def test_meru_reusable_compact_vs_refill_pouch_cohort_economics() -> None:
    example_path = ROOT / "examples" / "hermetica_meru_refill_model.json"
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    out = run_from_model_dict(payload)
    cohort = out["refill_cohort"]

    # Month 2+ barrier refill unit margin must exceed Month 1 permanent compact margin
    assert cohort["month_2_plus_unit_margin_pct"] > cohort["month_1_margin_pct"]
    # Over the 6-month retention horizon, permanent compact + refill pouch outperforms
    # re-shipping a rigid jar every month and pays back the $2.70 hardware investment
    assert cohort["cumulative_margin_lift_usd"] > 0
    assert cohort["hardware_premium_payback_month"] is not None
    assert cohort["hardware_premium_payback_month"] <= 3
    assert cohort["total_rigid_containers_avoided"] > 2500


def test_cli_human_and_json_modes(capsys: pytest.CaptureFixture[str]) -> None:
    example_str = str(ROOT / "examples" / "hermetica_meru_refill_model.json")
    rc = main([example_str, "--json"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["runway"]["sku_code"] == "HERM-MERU-COMPACT-50T"

    rc_human = main([example_str])
    assert rc_human == 0
    human_out = capsys.readouterr().out
    assert "Packaging Runway Report" in human_out
    assert "Reusable Hardware vs. Monthly Refill Cohort" in human_out
