#!/usr/bin/env python3
"""
cpg-packaging-runway-engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Zero-dependency supply-chain runway, ocean vs. air-bridge safety-stock solver,
MOQ working-capital planner, and reusable hardware vessel vs. monthly barrier
refill pouch cohort margin engine for founder-operated CPG brands.

Author: Christian Gallo Delgado — Hermetica Superfoods (LifeForce Liquids Corp.)
License: MIT
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


SERVICE_LEVEL_Z: Dict[float, float] = {
    0.90: 1.2816,
    0.95: 1.6449,
    0.975: 1.9600,
    0.98: 2.0537,
    0.99: 2.3263,
}


def z_score_for_service_level(service_level: float) -> float:
    """Return normal Z-score for a target cycle service level in (0.5, 0.999)."""
    if not (0.50 < service_level < 0.9999):
        raise ValueError(f"service_level must be between 0.50 and 0.9999, got {service_level}")
    rounded = round(service_level, 3)
    if rounded in SERVICE_LEVEL_Z:
        return SERVICE_LEVEL_Z[rounded]
    # Rational approximation (Acklam / Abramowitz-Stegun) for arbitrary tail probabilities
    p = service_level
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    )


@dataclass(frozen=True)
class VelocityWindow:
    """Trailing unit sales across 30/60/90-day windows to derive blended daily velocity."""

    units_30d: int
    units_60d: int
    units_90d: int
    weight_30d: float = 0.50
    weight_60d: float = 0.30
    weight_90d: float = 0.20

    def daily_velocity(self) -> float:
        if any(u < 0 for u in (self.units_30d, self.units_60d, self.units_90d)):
            raise ValueError("Window unit counts must be non-negative")
        total_weight = self.weight_30d + self.weight_60d + self.weight_90d
        if total_weight <= 0:
            raise ValueError("Weights must sum to a positive number")
        r30 = self.units_30d / 30.0
        r60 = self.units_60d / 60.0
        r90 = self.units_90d / 90.0
        return (
            r30 * self.weight_30d + r60 * self.weight_60d + r90 * self.weight_90d
        ) / total_weight


@dataclass(frozen=True)
class PackagingSpec:
    """Overseas structural vessel procurement parameters."""

    sku_code: str
    vessel_name: str
    origin_hub: str
    ex_factory_unit_usd: float
    moq_units: int
    carton_pack_units: int
    production_days: int
    ocean_freight_days: int
    air_freight_days: int
    co_packer_fill_days: int = 10
    lead_time_std_days: float = 4.0
    ocean_freight_per_unit_usd: float = 0.22
    air_freight_per_unit_usd: float = 1.15
    duty_rate: float = 0.075
    deposit_share: float = 0.30


@dataclass(frozen=True)
class RunwayReport:
    """Deterministic inventory runway, reorder point, and air-bridge split summary."""

    sku_code: str
    vessel_name: str
    usable_on_hand_units: int
    in_transit_units: int
    daily_velocity: float
    days_of_supply_on_hand: float
    days_of_supply_total: float
    ocean_total_lead_days: int
    air_total_lead_days: int
    safety_stock_ocean_units: int
    safety_stock_air_units: int
    reorder_point_ocean_units: int
    reorder_point_air_units: int
    days_until_ocean_reorder: float
    ocean_reorder_breached: bool
    recommended_order_units: int
    recommended_air_bridge_units: int
    recommended_ocean_balance_units: int
    po_deposit_usd: float
    po_balance_usd: float
    po_ex_factory_total_usd: float
    blended_landed_unit_usd: float
    air_bridge_premium_usd: float


def compute_safety_stock(
    daily_velocity: float,
    daily_demand_std: float,
    lead_days: int,
    lead_time_std_days: float,
    service_level: float = 0.95,
) -> int:
    """
    Compute integer safety-stock buffer accounting for uncorrelated demand
    variance and overseas production/port lead-time variance:
        SS = ceil(Z * sqrt(L * sigma_D^2 + mu_D^2 * sigma_L^2))
    """
    if daily_velocity < 0 or daily_demand_std < 0 or lead_days < 0 or lead_time_std_days < 0:
        raise ValueError("Velocity, standard deviations, and lead days must be non-negative")
    if daily_velocity == 0 and daily_demand_std == 0:
        return 0
    z = z_score_for_service_level(service_level)
    variance = (lead_days * (daily_demand_std ** 2)) + ((daily_velocity ** 2) * (lead_time_std_days ** 2))
    return int(math.ceil(z * math.sqrt(variance)))


def round_up_to_multiple(units: int, multiple: int) -> int:
    if multiple <= 0:
        raise ValueError("multiple must be positive")
    if units <= 0:
        return 0
    return int(math.ceil(units / multiple) * multiple)


def solve_packaging_runway(
    spec: PackagingSpec,
    usable_on_hand_units: int,
    daily_velocity: float,
    daily_demand_std: Optional[float] = None,
    in_transit_units: int = 0,
    target_order_units: Optional[int] = None,
    service_level: float = 0.95,
) -> RunwayReport:
    """
    Evaluate packaging runway, ocean vs. air reorder points, MOQ cash requirements,
    and minimum air-bridge carton split when an ocean-only PO would stock out.
    """
    if daily_velocity <= 0:
        raise ValueError("daily_velocity must be strictly positive")
    if usable_on_hand_units < 0 or in_transit_units < 0:
        raise ValueError("Inventory counts must be non-negative")

    demand_std = daily_demand_std if daily_demand_std is not None else (0.18 * daily_velocity)

    ocean_lead = spec.production_days + spec.ocean_freight_days + spec.co_packer_fill_days
    air_lead = spec.production_days + spec.air_freight_days + spec.co_packer_fill_days

    ss_ocean = compute_safety_stock(
        daily_velocity=daily_velocity,
        daily_demand_std=demand_std,
        lead_days=ocean_lead,
        lead_time_std_days=spec.lead_time_std_days,
        service_level=service_level,
    )
    ss_air = compute_safety_stock(
        daily_velocity=daily_velocity,
        daily_demand_std=demand_std,
        lead_days=air_lead,
        lead_time_std_days=max(1.0, spec.lead_time_std_days * 0.5),
        service_level=service_level,
    )

    rop_ocean = int(math.ceil(daily_velocity * ocean_lead)) + ss_ocean
    rop_air = int(math.ceil(daily_velocity * air_lead)) + ss_air

    effective_inventory = usable_on_hand_units + in_transit_units
    days_on_hand = usable_on_hand_units / daily_velocity
    days_total = effective_inventory / daily_velocity
    days_until_ocean_rop = (effective_inventory - rop_ocean) / daily_velocity
    ocean_breached = effective_inventory < rop_ocean

    base_order = target_order_units if target_order_units is not None else spec.moq_units
    order_units = max(spec.moq_units, round_up_to_multiple(base_order, spec.carton_pack_units))

    # Determine whether an air-bridge split is needed to cover the window between
    # air arrival (air_lead) and ocean arrival (ocean_lead)
    projected_at_ocean_arrival = effective_inventory - (daily_velocity * ocean_lead)
    target_floor = ss_air
    if projected_at_ocean_arrival < target_floor:
        raw_deficit = int(math.ceil(target_floor - projected_at_ocean_arrival))
        air_bridge_units = min(
            order_units,
            round_up_to_multiple(raw_deficit, spec.carton_pack_units),
        )
    else:
        air_bridge_units = 0

    ocean_balance_units = order_units - air_bridge_units

    ex_factory_total = round(order_units * spec.ex_factory_unit_usd, 2)
    deposit_usd = round(ex_factory_total * spec.deposit_share, 2)
    balance_usd = round(ex_factory_total - deposit_usd, 2)

    duty_per_unit = spec.ex_factory_unit_usd * spec.duty_rate
    ocean_landed_unit = spec.ex_factory_unit_usd + duty_per_unit + spec.ocean_freight_per_unit_usd
    air_landed_unit = spec.ex_factory_unit_usd + duty_per_unit + spec.air_freight_per_unit_usd

    total_landed = (ocean_balance_units * ocean_landed_unit) + (air_bridge_units * air_landed_unit)
    blended_landed_unit = round(total_landed / order_units, 4)
    air_premium = round(
        air_bridge_units * (spec.air_freight_per_unit_usd - spec.ocean_freight_per_unit_usd),
        2,
    )

    return RunwayReport(
        sku_code=spec.sku_code,
        vessel_name=spec.vessel_name,
        usable_on_hand_units=usable_on_hand_units,
        in_transit_units=in_transit_units,
        daily_velocity=round(daily_velocity, 2),
        days_of_supply_on_hand=round(days_on_hand, 1),
        days_of_supply_total=round(days_total, 1),
        ocean_total_lead_days=ocean_lead,
        air_total_lead_days=air_lead,
        safety_stock_ocean_units=ss_ocean,
        safety_stock_air_units=ss_air,
        reorder_point_ocean_units=rop_ocean,
        reorder_point_air_units=rop_air,
        days_until_ocean_reorder=round(days_until_ocean_rop, 1),
        ocean_reorder_breached=ocean_breached,
        recommended_order_units=order_units,
        recommended_air_bridge_units=air_bridge_units,
        recommended_ocean_balance_units=ocean_balance_units,
        po_deposit_usd=deposit_usd,
        po_balance_usd=balance_usd,
        po_ex_factory_total_usd=ex_factory_total,
        blended_landed_unit_usd=blended_landed_unit,
        air_bridge_premium_usd=air_premium,
    )


@dataclass(frozen=True)
class RefillEconomicsConfig:
    """
    Unit-economics inputs comparing a permanent hardware vessel + Month 2+ barrier
    refill pouch model against a single-use disposable jar shipped every month.
    """

    cohort_initial_customers: int
    starter_price_usd: float
    refill_price_usd: float
    permanent_vessel_landed_usd: float
    refill_pouch_landed_usd: float
    formulation_fill_cogs_usd: float
    starter_pick_pack_ship_usd: float
    refill_pick_pack_ship_usd: float
    payment_processing_rate: float = 0.029
    payment_fixed_fee_usd: float = 0.30
    disposable_jar_landed_usd: float = 0.85
    disposable_ship_usd: float = 5.40
    monthly_retention_curve: Sequence[float] = (1.0, 0.72, 0.61, 0.54, 0.49, 0.45)


@dataclass(frozen=True)
class CohortMonthRow:
    month: int
    active_subscribers: int
    refill_system_revenue_usd: float
    refill_system_cogs_usd: float
    refill_system_gross_profit_usd: float
    refill_system_margin_pct: float
    disposable_baseline_gross_profit_usd: float
    disposable_baseline_margin_pct: float
    rigid_containers_avoided: int


@dataclass(frozen=True)
class RefillCohortSummary:
    cohort_initial_customers: int
    horizon_months: int
    month_1_margin_pct: float
    month_2_plus_unit_margin_pct: float
    cumulative_revenue_usd: float
    cumulative_refill_gross_profit_usd: float
    cumulative_refill_blended_margin_pct: float
    cumulative_disposable_gross_profit_usd: float
    cumulative_margin_lift_usd: float
    hardware_premium_payback_month: Optional[int]
    total_rigid_containers_avoided: int
    monthly_schedule: List[CohortMonthRow]


def simulate_refill_cohort(cfg: RefillEconomicsConfig) -> RefillCohortSummary:
    """
    Simulate Month 1 permanent vessel investment followed by Month 2..N barrier
    refill pouches across a subscriber retention curve.
    """
    if cfg.cohort_initial_customers <= 0:
        raise ValueError("cohort_initial_customers must be positive")
    if not cfg.monthly_retention_curve or cfg.monthly_retention_curve[0] <= 0:
        raise ValueError("monthly_retention_curve must start with Month 1 > 0")

    rows: List[CohortMonthRow] = []
    cum_rev = 0.0
    cum_refill_gp = 0.0
    cum_disp_gp = 0.0
    total_avoided = 0
    payback_month: Optional[int] = None

    # Unit-level Month 2+ margin % for reporting
    m2_fee = (cfg.refill_price_usd * cfg.payment_processing_rate) + cfg.payment_fixed_fee_usd
    m2_unit_cost = (
        cfg.refill_pouch_landed_usd
        + cfg.formulation_fill_cogs_usd
        + cfg.refill_pick_pack_ship_usd
        + m2_fee
    )
    m2_unit_margin_pct = ((cfg.refill_price_usd - m2_unit_cost) / cfg.refill_price_usd) * 100.0

    for idx, retention in enumerate(cfg.monthly_retention_curve):
        month = idx + 1
        active = int(round(cfg.cohort_initial_customers * retention))
        price = cfg.starter_price_usd if month == 1 else cfg.refill_price_usd
        rev = active * price

        proc_fee = (price * cfg.payment_processing_rate) + cfg.payment_fixed_fee_usd

        if month == 1:
            unit_cogs = (
                cfg.permanent_vessel_landed_usd
                + cfg.formulation_fill_cogs_usd
                + cfg.starter_pick_pack_ship_usd
                + proc_fee
            )
            avoided = 0
        else:
            unit_cogs = (
                cfg.refill_pouch_landed_usd
                + cfg.formulation_fill_cogs_usd
                + cfg.refill_pick_pack_ship_usd
                + proc_fee
            )
            avoided = active

        # Comparable disposable baseline charges the same customer price per cycle
        # while re-shipping a new rigid jar + full-weight parcel every month
        disp_unit_cogs = (
            cfg.disposable_jar_landed_usd
            + cfg.formulation_fill_cogs_usd
            + cfg.disposable_ship_usd
            + proc_fee
        )

        refill_cogs_total = active * unit_cogs
        refill_gp = rev - refill_cogs_total
        refill_margin = (refill_gp / rev * 100.0) if rev > 0 else 0.0

        disp_gp = rev - (active * disp_unit_cogs)
        disp_margin = (disp_gp / rev * 100.0) if rev > 0 else 0.0

        cum_rev += rev
        cum_refill_gp += refill_gp
        cum_disp_gp += disp_gp
        total_avoided += avoided

        if payback_month is None and month > 1 and cum_refill_gp >= cum_disp_gp:
            payback_month = month

        rows.append(
            CohortMonthRow(
                month=month,
                active_subscribers=active,
                refill_system_revenue_usd=round(rev, 2),
                refill_system_cogs_usd=round(refill_cogs_total, 2),
                refill_system_gross_profit_usd=round(refill_gp, 2),
                refill_system_margin_pct=round(refill_margin, 2),
                disposable_baseline_gross_profit_usd=round(disp_gp, 2),
                disposable_baseline_margin_pct=round(disp_margin, 2),
                rigid_containers_avoided=avoided,
            )
        )

    blended_margin = (cum_refill_gp / cum_rev * 100.0) if cum_rev > 0 else 0.0
    return RefillCohortSummary(
        cohort_initial_customers=cfg.cohort_initial_customers,
        horizon_months=len(rows),
        month_1_margin_pct=rows[0].refill_system_margin_pct,
        month_2_plus_unit_margin_pct=round(m2_unit_margin_pct, 2),
        cumulative_revenue_usd=round(cum_rev, 2),
        cumulative_refill_gross_profit_usd=round(cum_refill_gp, 2),
        cumulative_refill_blended_margin_pct=round(blended_margin, 2),
        cumulative_disposable_gross_profit_usd=round(cum_disp_gp, 2),
        cumulative_margin_lift_usd=round(cum_refill_gp - cum_disp_gp, 2),
        hardware_premium_payback_month=payback_month,
        total_rigid_containers_avoided=total_avoided,
        monthly_schedule=rows,
    )


def run_from_model_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute both packaging runway and refill cohort models from a JSON config."""
    spec = PackagingSpec(**payload["packaging_spec"])
    inv = payload["inventory_state"]

    if "velocity_window" in inv:
        daily_vel = VelocityWindow(**inv["velocity_window"]).daily_velocity()
    else:
        daily_vel = float(inv["daily_velocity"])

    runway_report = solve_packaging_runway(
        spec=spec,
        usable_on_hand_units=int(inv["usable_on_hand_units"]),
        in_transit_units=int(inv.get("in_transit_units", 0)),
        daily_velocity=daily_vel,
        daily_demand_std=inv.get("daily_demand_std"),
        target_order_units=inv.get("target_order_units"),
        service_level=float(inv.get("service_level", 0.95)),
    )

    result: Dict[str, Any] = {"runway": asdict(runway_report)}
    if "refill_cohort_model" in payload:
        cohort_cfg = RefillEconomicsConfig(**payload["refill_cohort_model"])
        cohort_summary = simulate_refill_cohort(cohort_cfg)
        result["refill_cohort"] = asdict(cohort_summary)
    return result


def _format_human_summary(result: Dict[str, Any]) -> str:
    r = result["runway"]
    rop_status = (
        "BREACHED"
        if r["ocean_reorder_breached"]
        else f"{r['days_until_ocean_reorder']}d buffer remaining"
    )
    lines = [
        f"=== Packaging Runway Report: {r['sku_code']} ({r['vessel_name']}) ===",
        f"Daily Velocity:            {r['daily_velocity']:.2f} units/day",
        f"On-Hand / Total Supply:    {r['usable_on_hand_units']:,} units ({r['days_of_supply_on_hand']}d) | "
        f"Total w/ Transit: {r['usable_on_hand_units'] + r['in_transit_units']:,} units ({r['days_of_supply_total']}d)",
        f"Lead Times (Prod+Frt+Fill): Ocean {r['ocean_total_lead_days']}d | Air-Bridge {r['air_total_lead_days']}d",
        f"Safety Stock (95%+ SL):    Ocean {r['safety_stock_ocean_units']:,} units | Air {r['safety_stock_air_units']:,} units",
        f"Ocean Reorder Point (ROP): {r['reorder_point_ocean_units']:,} units ({rop_status})",
        f"Recommended PO Split:      {r['recommended_order_units']:,} total "
        f"({r['recommended_air_bridge_units']:,} air-bridge / {r['recommended_ocean_balance_units']:,} ocean)",
        f"Factory Cash Commitment:   ${r['po_ex_factory_total_usd']:,.2f} "
        f"(${r['po_deposit_usd']:,.2f} deposit / ${r['po_balance_usd']:,.2f} balance)",
        f"Blended Landed Unit Cost:  ${r['blended_landed_unit_usd']:.4f} "
        f"(Air-bridge premium: ${r['air_bridge_premium_usd']:,.2f})",
    ]
    if "refill_cohort" in result:
        c = result["refill_cohort"]
        lines.extend(
            [
                "",
                f"=== Reusable Hardware vs. Monthly Refill Cohort ({c['cohort_initial_customers']:,} Starters, {c['horizon_months']}m) ===",
                f"Month 1 Hardware Margin:   {c['month_1_margin_pct']:.2f}%",
                f"Month 2+ Refill Margin:    {c['month_2_plus_unit_margin_pct']:.2f}%",
                f"Blended {c['horizon_months']}m Gross Margin:  {c['cumulative_refill_blended_margin_pct']:.2f}% "
                f"(${c['cumulative_refill_gross_profit_usd']:,.2f} GP on ${c['cumulative_revenue_usd']:,.2f} rev)",
                f"vs. Disposable Jar GP:     ${c['cumulative_disposable_gross_profit_usd']:,.2f} "
                f"(Net Lift: +${c['cumulative_margin_lift_usd']:,.2f}, Payback Month: {c['hardware_premium_payback_month']})",
                f"Single-Use Jars Avoided:   {c['total_rigid_containers_avoided']:,} rigid containers",
            ]
        )
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cpg-runway",
        description="Compute CPG overseas packaging runway, air/ocean split, and refill cohort margins.",
    )
    parser.add_argument(
        "model_json",
        type=Path,
        help="Path to model configuration JSON (e.g., examples/hermetica_meru_refill_model.json)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON instead of human-readable summary",
    )
    args = parser.parse_args(argv)

    payload = json.loads(args.model_json.read_text(encoding="utf-8"))
    result = run_from_model_dict(payload)
    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(_format_human_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
