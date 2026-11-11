# cpg-packaging-runway-engine

**Deterministic overseas packaging runway, ocean vs. air-bridge safety-stock solver, MOQ cash commitment calculator, and reusable hardware vessel vs. monthly refill pouch cohort margin model.**

Authored by [**Christian Gallo Delgado**](https://christiangallodelgado.com) — Founder, Structural Packaging Designer & Botanical Formulator at [**Hermetica Superfoods**](https://hermeticasuperfoods.com) ([LifeForce Liquids Corp.](https://lifeforceliquids.com)).

- **Zero external runtime dependencies** (Python 3.9+ standard library only)
- **License:** MIT
- **Reference Hardware Ledger:** [christiangallodelgado.com/craft](https://christiangallodelgado.com/craft)

---

## Why This Exists

Solo CPG founders who engineer custom primary hardware overseas (metal pocket compacts, telescoping rigid paperboard cylinders, barrier refill pouches) face two coupled math problems that generic Shopify inventory apps get wrong:

1. **Multi-Stage Trans-Pacific Lead Times & Air-Bridge Splits:** When Dongguan factory fabrication (`30–35` days), trans-Pacific ocean freight (`28` days), and domestic U.S. co-packer filling/QC (`10–12` days) combine into a `70+` day cash-to-shelf cycle, breaching your ocean reorder point does **not** mean you should air-freight an entire `5,000`-unit PO. You only need to air-bridge the exact carton-rounded deficit between air arrival (`52d`) and ocean arrival (`73d`), routing the remaining balance by sea.
2. **Permanent Hardware Vessel vs. Monthly Refill Cohort Economics:** Investing `$2.70` ex-factory in a permanent gold-plated magnetic metal pocket compact in Month 1 looks expensive on a single-order spreadsheet compared with a `$0.85` disposable plastic jar. Across a 6-month subscriber retention curve where Month 2+ orders ship in lightweight barrier refill pouches (`~$0.28` landed), the permanent vessel pays back its hardware premium by **Month 3**, expands ongoing gross margin by **+540 bps**, and eliminates thousands of single-use rigid containers per 1,000 customers.

---

## Quick Start

```bash
git clone https://github.com/mindexpansive/cpg-packaging-runway-engine.git
cd cpg-packaging-runway-engine

# Run the Hermetica Meru magnetic compact + Month 2+ refill cohort model
python3 runway.py examples/hermetica_meru_refill_model.json

# Emit machine-readable JSON for dashboards or ERP pipelines
python3 runway.py examples/hermetica_meru_refill_model.json --json

# Run the Hush rigid paperboard cylinder runway model
python3 runway.py examples/hermetica_hush_cylinder_runway.json
```

### Sample Output (`examples/hermetica_meru_refill_model.json`)

Demonstrated using public packaging economics from **Hermetica Meru Shilajit** (`$2.70` factory unit cost, `2,500` unit MOQ, `15,000` compacts manufactured across `3 × 5,000` runs in Dongguan; filled with 50 peppermint-finished shilajit tablets in the U.S.):

```text
=== Packaging Runway Report: HERM-MERU-COMPACT-50T (Meru Gold-Plated Magnetic Pocket Compact (50 Tablets)) ===
Daily Velocity:            49.90 units/day
On-Hand / Total Supply:    3,100 units (62.1d) | Total w/ Transit: 3,100 units (62.1d)
Lead Times (Prod+Frt+Fill): Ocean 73d | Air-Bridge 52d
Safety Stock (95%+ SL):    Ocean 393 units | Air 217 units
Ocean Reorder Point (ROP): 4,036 units (BREACHED)
Recommended PO Split:      5,000 total (800 air-bridge / 4,200 ocean)
Factory Cash Commitment:   $13,500.00 ($4,050.00 deposit / $9,450.00 balance)
Blended Landed Unit Cost:  $3.2761 (Air-bridge premium: $768.00)

=== Reusable Hardware vs. Monthly Refill Cohort (1,000 Starters, 6m) ===
Month 1 Hardware Margin:   72.70%
Month 2+ Refill Margin:    78.11%
Blended 6m Gross Margin:  76.55% ($146,238.97 GP on $191,042.50 rev)
vs. Disposable Jar GP:     $142,687.77 (Net Lift: +$3,551.20, Payback Month: 3)
Single-Use Jars Avoided:   2,910 rigid containers
```

---

## Core Formulas

### 1. Weighted Trailing Daily Velocity
Blends 30-, 60-, and 90-day unit movement (`w = 0.50 / 0.30 / 0.20` by default) so recent inflection points register immediately without overreacting to single-weekend spikes:

$$\mu_D = \frac{w_{30}\frac{U_{30}}{30} + w_{60}\frac{U_{60}}{60} + w_{90}\frac{U_{90}}{90}}{w_{30} + w_{60} + w_{90}}$$

### 2. Joint Demand & Overseas Lead-Time Safety Stock
Accounts for both daily demand volatility ($\sigma_D$) and factory/port transit variance ($\sigma_L$) at cycle service level $Z$ (e.g., $Z = 1.6449$ at $95\%$):

$$\text{SS} = \left\lceil Z \cdot \sqrt{L \cdot \sigma_D^2 + \mu_D^2 \cdot \sigma_L^2} \right\rceil, \qquad \text{ROP}_{\text{ocean}} = \lceil \mu_D \cdot L_{\text{ocean}} \rceil + \text{SS}_{\text{ocean}}$$

### 3. Minimum Air-Bridge Split
When effective inventory $I_{\text{eff}}$ drops below $\text{ROP}_{\text{ocean}}$, projected inventory at ocean arrival ($I_{\text{eff}} - \mu_D \cdot L_{\text{ocean}}$) falls below the safety floor $\text{SS}_{\text{air}}$. The solver rounds only that deficit up to the factory master-carton multiple $C$:

$$Q_{\text{air}} = \min\left(Q_{\text{order}},\; C \cdot \left\lceil \frac{\max(0,\; \text{SS}_{\text{air}} - (I_{\text{eff}} - \mu_D \cdot L_{\text{ocean}}))}{C} \right\rceil\right)$$

---

## Python API Usage

```python
from runway import PackagingSpec, VelocityWindow, solve_packaging_runway

spec = PackagingSpec(
    sku_code="HERM-HUSH-CYLINDER-20G",
    vessel_name="Hush Telescoping Rigid Paperboard Cylinder",
    origin_hub="Dongguan, Guangdong, CN",
    ex_factory_unit_usd=0.59,
    moq_units=10000,
    carton_pack_units=200,
    production_days=30,
    ocean_freight_days=28,
    air_freight_days=7,
    co_packer_fill_days=12,
)

velocity = VelocityWindow(units_30d=5700, units_60d=11100, units_90d=16200).daily_velocity()
report = solve_packaging_runway(spec, usable_on_hand_units=18400, daily_velocity=velocity, target_order_units=20000)
print(report.reorder_point_ocean_units, report.recommended_air_bridge_units)
```

---

## Running Tests

```bash
pytest -v
```

---

## Related Open Projects

- [**supplement-coa-jsonld**](https://github.com/mindexpansive/supplement-coa-jsonld) — JSON Schema & validator for ISO/IEC 17025 dietary supplement Certificates of Analysis, label-claim tolerances, and structural vessel specs in `Schema.org` JSON-LD.
- [**hermetica-supplement-encyclopedia**](https://github.com/mindexpansive/hermetica-supplement-encyclopedia) — 15,600+ botanical & dietary supplement ingredient monographs live at [ingredients.hermeticasuperfoods.com](https://ingredients.hermeticasuperfoods.com).

## License

Released under the [MIT License](./LICENSE).
