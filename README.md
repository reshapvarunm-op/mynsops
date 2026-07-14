# OmniStream Control Tower

OmniStream Control Tower is a HackerRamp-ready Streamlit prototype for a fashion supply-chain orchestration layer. It proves one focused idea: connect demand, vendor production, warehouse capacity, and returns data to automatically recommend the next best supply-chain action.

## What the Prototype Demonstrates

The prototype is intentionally scoped as a working control tower, not a full supply-chain system. A planner can:

1. Open an executive dashboard with live operational risks.
2. Review risky SKUs across stockout, dead-stock, warehouse gridlock, vendor delay, and return-quality signals.
3. Select a SKU to see the demand, inventory, PO, warehouse, and returns context behind the risk.
4. Click **Generate Action Plan** to receive rule-based next-best actions.
5. Track the selected PO from release through vendor manufacturing, 3PL movement, Myntra warehouse allocation, GRN, and inventory-live status.
6. Upload replacement CSV files or download sample templates from the sidebar.

## Core Screens

- **Executive Control Tower:** KPI cards and a prioritized risk table.
- **SKU Detail View:** Inventory, sales velocity, days of cover, open PO, vendor stage, delay, capacity, return rate, and top return reason.
- **Vendor Production Tracker:** PO milestone visibility from fabric through dispatch.
- **Warehouse Capacity Scheduler:** Planned inwarding versus capacity, utilization status, and capacity recommendations.
- **Returns Intelligence:** Vendor-SKU return linkage with quality escalation actions.
- **PO-to-GRN Lifecycle:** Inbound tracker across PO released, vendor manufacturing, sample inspection, catalogue dispatch, bulk scan and pack, invoice generation, approval, 3PL pickup, 3PL staging, Myntra WH allocation, WH transfer, GRN, and inventory live.

## Recommendation Rules

The orchestration engine uses simple, explainable rules so judges can follow the decision logic:

| Rule | Formula / Trigger | Recommendation Impact |
| --- | --- | --- |
| Days of Cover | `current_inventory / avg_daily_sales < 7` | Flags stockout risk and recommends pulling production forward. |
| Dead Stock | Low sell-through with high inbound quantity | Recommends reducing the next buy or delaying inwarding. |
| Warehouse Gridlock | `planned_inward_units / capacity_units > 100%` | Recommends shifting inwarding to a safer slot. |
| Vendor Delay | `current_delay_days > 0` | Recommends vendor escalation. |
| Quality Loopback | High return rate with quality-related reason | Recommends vendor quality checks or audits. |

## Mock Data

The app ships with five sample CSV files in `data/`:

- `skus.csv`
- `inventory.csv`
- `purchase_orders.csv`
- `warehouse_capacity.csv`
- `returns.csv`
- `inbound_lifecycle.csv`

Each template can also be downloaded from the app sidebar. Uploading a CSV with the same required columns immediately refreshes the dashboard calculations and recommendations.

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Demo Script

1. Start the app with `streamlit run app.py`.
2. Show the KPI cards and explain the live risk table.
3. Select `DRS-102` to highlight stockout risk, vendor delay, warehouse pressure, and return-quality signals.
4. Click **Generate Action Plan**.
5. Show the vendor tracker, warehouse scheduler, and returns intelligence tabs.
6. Download a template from the sidebar, modify it, upload it, and show the dashboard refresh.

## Positioning

OmniStream is not another static dashboard. It is a supply-chain orchestration layer that connects demand, procurement, vendor production, warehouse capacity, and returns so fashion brands can move from reactive spreadsheet planning to autonomous, closed-loop decision-making.
