from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import plotly.express as px
import streamlit as st

DATA_DIR = Path(__file__).parent / "data"
QUALITY_REASONS = ("defect", "tear", "stitch", "damage", "broken", "quality")
REQUIRED_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "skus": ("sku", "product_name", "category", "vendor", "price"),
    "inventory": ("sku", "current_inventory", "avg_daily_sales", "inbound_qty"),
    "purchase_orders": ("po_id", "sku", "vendor", "qty", "stage", "planned_dispatch_date", "current_delay_days"),
    "warehouse_capacity": ("date", "planned_inward_units", "capacity_units"),
    "returns": ("sku", "vendor", "sold_units", "returned_units", "top_return_reason"),
    "inbound_lifecycle": (
        "po_id",
        "sku",
        "vendor",
        "po_released",
        "vendor_manufacturing",
        "sample_inspection",
        "catalogue_goods_dispatch",
        "bulk_scan_pack",
        "invoice_generation",
        "approval",
        "three_pl_pickup",
        "three_pl_staging_warehouse",
        "myntra_wh_allocation",
        "wh_transfer",
        "grn",
        "inventory_live",
        "current_step",
        "blocked_reason",
    ),
}


@dataclass(frozen=True)
class SupplyChainData:
    skus: pd.DataFrame
    inventory: pd.DataFrame
    purchase_orders: pd.DataFrame
    warehouse_capacity: pd.DataFrame
    returns: pd.DataFrame
    inbound_lifecycle: pd.DataFrame


def read_csv(path_or_file) -> pd.DataFrame:
    return pd.read_csv(path_or_file)


@st.cache_data
def load_sample_data() -> SupplyChainData:
    return SupplyChainData(
        skus=read_csv(DATA_DIR / "skus.csv"),
        inventory=read_csv(DATA_DIR / "inventory.csv"),
        purchase_orders=read_csv(DATA_DIR / "purchase_orders.csv"),
        warehouse_capacity=read_csv(DATA_DIR / "warehouse_capacity.csv"),
        returns=read_csv(DATA_DIR / "returns.csv"),
        inbound_lifecycle=read_csv(DATA_DIR / "inbound_lifecycle.csv"),
    )


def template_bytes(name: str) -> bytes:
    return (DATA_DIR / f"{name}.csv").read_bytes()


def validate_columns(name: str, frame: pd.DataFrame) -> List[str]:
    missing = [column for column in REQUIRED_COLUMNS[name] if column not in frame.columns]
    return missing


def load_data_from_uploads() -> SupplyChainData:
    st.sidebar.header("Load supply-chain data")
    st.sidebar.caption("Download the sample templates, fill them, then upload CSVs to refresh the prototype.")

    uploaded_frames = {}
    for name in REQUIRED_COLUMNS:
        label = name.replace("_", " ").title()
        st.sidebar.download_button(
            label=f"Download {label} Template",
            data=template_bytes(name),
            file_name=f"{name}.csv",
            mime="text/csv",
            key=f"download-{name}",
        )
        upload = st.sidebar.file_uploader(f"Upload {label}", type="csv", key=f"upload-{name}")
        if upload is not None:
            frame = read_csv(upload)
            missing = validate_columns(name, frame)
            if missing:
                st.sidebar.error(f"{label} missing columns: {', '.join(missing)}")
            else:
                uploaded_frames[name] = frame

    sample = load_sample_data()
    return SupplyChainData(
        skus=uploaded_frames.get("skus", sample.skus),
        inventory=uploaded_frames.get("inventory", sample.inventory),
        purchase_orders=uploaded_frames.get("purchase_orders", sample.purchase_orders),
        warehouse_capacity=uploaded_frames.get("warehouse_capacity", sample.warehouse_capacity),
        returns=uploaded_frames.get("returns", sample.returns),
        inbound_lifecycle=uploaded_frames.get("inbound_lifecycle", sample.inbound_lifecycle),
    )


def enrich_data(data: SupplyChainData) -> Tuple[pd.DataFrame, pd.DataFrame]:
    sku_base = data.skus.merge(data.inventory, on="sku", how="left", suffixes=("", "_inventory"))
    po_latest = data.purchase_orders.sort_values(["sku", "current_delay_days"], ascending=[True, False]).drop_duplicates("sku")
    sku_base = sku_base.merge(
        po_latest[["sku", "po_id", "qty", "stage", "planned_dispatch_date", "current_delay_days"]],
        on="sku",
        how="left",
    )
    sku_base = sku_base.merge(
        data.returns[["sku", "sold_units", "returned_units", "top_return_reason"]],
        on="sku",
        how="left",
    )

    sku_base["days_of_cover"] = sku_base["current_inventory"] / sku_base["avg_daily_sales"].replace(0, pd.NA)
    sku_base["total_available_units"] = sku_base["current_inventory"] + sku_base["inbound_qty"]
    sku_base["sell_through_rate"] = sku_base["sold_units"] / sku_base["total_available_units"].replace(0, pd.NA)
    sku_base["return_rate"] = sku_base["returned_units"] / sku_base["sold_units"].replace(0, pd.NA)
    sku_base["inventory_value"] = sku_base["current_inventory"] * sku_base["price"]
    sku_base["inbound_value"] = sku_base["inbound_qty"] * sku_base["price"]

    warehouse = data.warehouse_capacity.copy()
    warehouse["date"] = pd.to_datetime(warehouse["date"]).dt.date
    warehouse["utilization"] = warehouse["planned_inward_units"] / warehouse["capacity_units"]
    warehouse["status"] = warehouse["utilization"].apply(lambda value: "Overload" if value > 1 else "Tight" if value >= 0.9 else "Safe")
    return sku_base, warehouse


def is_quality_reason(reason: str) -> bool:
    lower_reason = str(reason).lower()
    return any(token in lower_reason for token in QUALITY_REASONS)


def severity_score(row: pd.Series, warehouse_overloaded: bool) -> Tuple[int, List[str]]:
    risks: List[str] = []
    score = 0
    if row["days_of_cover"] < 7:
        risks.append("Stockout")
        score += 3
    if row["sell_through_rate"] < 0.35 and row["inbound_qty"] > row["current_inventory"] * 0.5:
        risks.append("Dead-stock")
        score += 2
    if warehouse_overloaded:
        risks.append("Warehouse Gridlock")
        score += 2
    if row.get("current_delay_days", 0) > 0:
        risks.append("Vendor Delay")
        score += min(int(row["current_delay_days"]), 3)
    if row["return_rate"] > 0.04 and is_quality_reason(row["top_return_reason"]):
        risks.append("Return Quality")
        score += 3
    return score, risks


def severity_label(score: int) -> str:
    if score >= 6:
        return "High"
    if score >= 3:
        return "Medium"
    return "Low"


def primary_action(risks: Iterable[str], row: pd.Series) -> str:
    risk_set = set(risks)
    if "Stockout" in risk_set and "Vendor Delay" in risk_set:
        return "Expedite production and prioritize receiving"
    if "Dead-stock" in risk_set:
        return "Reduce next buy and delay inwarding"
    if "Warehouse Gridlock" in risk_set:
        return "Shift inwarding slot"
    if "Return Quality" in risk_set:
        return f"Escalate {row['top_return_reason']}"
    if "Vendor Delay" in risk_set:
        return "Escalate vendor delay"
    return "Monitor"


def risk_reason(risks: Iterable[str], row: pd.Series) -> str:
    reasons = []
    risk_set = set(risks)
    if "Stockout" in risk_set:
        reasons.append(f"only {row['days_of_cover']:.1f} days of cover")
    if "Dead-stock" in risk_set:
        reasons.append(f"{row['sell_through_rate']:.1%} sell-through with {int(row['inbound_qty']):,} inbound units")
    if "Warehouse Gridlock" in risk_set:
        reasons.append("one or more receiving days is above warehouse capacity")
    if "Vendor Delay" in risk_set:
        reasons.append(f"PO {row['po_id']} delayed by {int(row['current_delay_days'])} days at {row['stage']}")
    if "Return Quality" in risk_set:
        reasons.append(f"{row['return_rate']:.1%} returns linked to {row['top_return_reason']}")
    return "; ".join(reasons)


def expected_impact(risks: Iterable[str]) -> str:
    risk_set = set(risks)
    impacts = []
    if "Stockout" in risk_set:
        impacts.append("protect high-velocity revenue")
    if "Dead-stock" in risk_set:
        impacts.append("reduce working-capital lockup")
    if "Warehouse Gridlock" in risk_set:
        impacts.append("avoid receiving overload")
    if "Vendor Delay" in risk_set:
        impacts.append("recover delayed production")
    if "Return Quality" in risk_set:
        impacts.append("prevent repeat quality failures")
    return ", ".join(impacts).capitalize() + "."


def build_risk_table(skus: pd.DataFrame, warehouse: pd.DataFrame) -> pd.DataFrame:
    warehouse_overloaded = bool((warehouse["utilization"] > 1).any())
    records = []
    for _, row in skus.iterrows():
        score, risks = severity_score(row, warehouse_overloaded)
        if not risks:
            continue
        records.append(
            {
                "SKU": row["sku"],
                "Product": row["product_name"],
                "Category": row["category"],
                "Vendor": row["vendor"],
                "Risk Type": ", ".join(risks),
                "Severity": severity_label(score),
                "Risk Reason": risk_reason(risks, row),
                "Recommended Action": primary_action(risks, row),
                "Expected Business Impact": expected_impact(risks),
                "Score": score,
            }
        )
    return pd.DataFrame(records).sort_values(["Score", "SKU"], ascending=[False, True])


def action_plan(row: pd.Series, warehouse: pd.DataFrame, skus: pd.DataFrame, lifecycle_row: pd.Series | None = None) -> str:
    overloaded_days = warehouse[warehouse["utilization"] > 1].sort_values("utilization", ascending=False)
    overloaded_line = "No overloaded receiving days."
    if not overloaded_days.empty:
        top_day = overloaded_days.iloc[0]
        overload_units = int(top_day["planned_inward_units"] - top_day["capacity_units"])
        overloaded_line = f"{top_day['date']} is overloaded at {top_day['utilization']:.0%}; move about {overload_units:,} units to a safer day."

    lower_priority = skus.sort_values(["sell_through_rate", "days_of_cover"], ascending=[True, False]).iloc[0]
    buy_action = "Increase or maintain buy quantity because demand is strong."
    if row["sell_through_rate"] < 0.35:
        buy_action = "Reduce next buy quantity because sell-through is weak and inbound stock is high."
    elif row["days_of_cover"] < 7:
        buy_action = "Maintain buy quantity and pull production forward because stockout risk is high."

    quality_action = "Monitor return reasons; no quality escalation needed yet."
    if row["return_rate"] > 0.04 and is_quality_reason(row["top_return_reason"]):
        quality_action = f"Trigger quality check for {row['vendor']} because returns cite {row['top_return_reason']}."

    lifecycle_status = "No lifecycle record uploaded for this PO."
    if lifecycle_row is not None:
        lifecycle_status = f"PO-to-GRN is currently at **{lifecycle_row['current_step']}**; blocker: {lifecycle_row['blocked_reason']}."

    return f"""
### Recommended Action Plan for SKU {row['sku']}

**Risk Detected:** {row['product_name']} has {row['days_of_cover']:.1f} days of cover, {row['sell_through_rate']:.1%} sell-through, and a {row['return_rate']:.1%} return rate.

**Vendor Status:** Current PO `{row['po_id']}` is at **{row['stage']}** with a dispatch delay of **{int(row['current_delay_days'])} days**.

**Warehouse Status:** {overloaded_line}

**PO-to-GRN Lifecycle:** {lifecycle_status}

**Recommended Actions:**
1. {buy_action}
2. Escalate {row['vendor']} if the production delay remains above zero days.
3. Prioritize {row['sku']} for the next available warehouse slot when stockout risk is active.
4. Shift lower-priority {lower_priority['sku']} inwarding if capacity is overloaded.
5. {quality_action}

**Expected Business Impact:** Prevent stockouts on high-velocity SKUs, avoid warehouse gridlock, and close the loop between customer returns and vendor quality.
"""


def production_milestones(purchase_orders: pd.DataFrame) -> pd.DataFrame:
    milestones = ["Fabric", "Cutting", "Stitching", "Finishing", "Packing", "Dispatch"]
    stage_order = {"Fabric Ready": 0, "Cutting": 1, "Stitching": 2, "Finishing": 3, "Packing": 4, "Dispatch": 5}
    rows = []
    for _, po in purchase_orders.iterrows():
        current_index = stage_order.get(po["stage"], 0)
        row = {"PO": po["po_id"], "Vendor": po["vendor"], "SKU": po["sku"]}
        for index, milestone in enumerate(milestones):
            if index < current_index:
                row[milestone] = "Done"
            elif index == current_index and po["current_delay_days"] > 0:
                row[milestone] = "Delayed"
            elif index == current_index:
                row[milestone] = "In Progress"
            else:
                row[milestone] = "Pending"
        rows.append(row)
    return pd.DataFrame(rows)


def render_kpis(skus: pd.DataFrame, warehouse: pd.DataFrame) -> None:
    stockout_count = int((skus["days_of_cover"] < 7).sum())
    dead_stock_value = skus.loc[(skus["sell_through_rate"] < 0.35) & (skus["inbound_qty"] > skus["current_inventory"] * 0.5), "inbound_value"].sum()
    overload_days = int((warehouse["utilization"] > 1).sum())
    delayed_pos = int((skus["current_delay_days"] > 0).sum())
    high_return_pairs = int(((skus["return_rate"] > 0.04) & skus["top_return_reason"].apply(is_quality_reason)).sum())
    columns = st.columns(5)
    columns[0].metric("Stockout Risk SKUs", stockout_count)
    columns[1].metric("Dead Stock Risk Value", f"₹{dead_stock_value / 100000:.1f}L")
    columns[2].metric("Warehouse Overload Days", overload_days)
    columns[3].metric("Delayed Vendor POs", delayed_pos)
    columns[4].metric("High Return Vendor-SKU Pairs", high_return_pairs)


def render_dashboard() -> None:
    st.set_page_config(page_title="OmniStream Control Tower", page_icon="🧭", layout="wide")
    st.title("OmniStream Control Tower")
    st.caption("Hackathon prototype: connects demand, vendor production, warehouse capacity, and returns to recommend the next best supply-chain action.")

    data = load_data_from_uploads()
    skus, warehouse = enrich_data(data)
    risk_table = build_risk_table(skus, warehouse)

    render_kpis(skus, warehouse)
    st.subheader("Executive Risk Table")
    st.dataframe(risk_table.drop(columns=["Score"]), use_container_width=True, hide_index=True)

    st.subheader("SKU Detail View")
    selected_sku = st.selectbox("Select a risky SKU", risk_table["SKU"].tolist() if not risk_table.empty else skus["sku"].tolist())
    sku_pos = data.purchase_orders[data.purchase_orders["sku"] == selected_sku]["po_id"].tolist()
    selected_po = st.selectbox("Select PO for action plan", sku_pos, key="selected-po")
    selected = skus.loc[(skus["sku"] == selected_sku) & (skus["po_id"] == selected_po)].iloc[0]
    lifecycle_match = data.inbound_lifecycle[data.inbound_lifecycle["po_id"] == selected_po]
    lifecycle_row = lifecycle_match.iloc[0] if not lifecycle_match.empty else None
    detail_cols = st.columns(4)
    detail_cols[0].metric("Current Inventory", f"{int(selected['current_inventory']):,} units")
    detail_cols[1].metric("Avg Daily Sales", f"{selected['avg_daily_sales']:.0f} units")
    detail_cols[2].metric("Days of Cover", f"{selected['days_of_cover']:.1f} days")
    detail_cols[3].metric("Return Rate", f"{selected['return_rate']:.1%}")
    st.write(
        {
            "Category": selected["category"],
            "Vendor": selected["vendor"],
            "Selected PO": selected_po,
            "Open PO Quantity": int(selected["qty"]),
            "Production Stage": selected["stage"],
            "Expected Dispatch Date": selected["planned_dispatch_date"],
            "Dispatch Delay Days": int(selected["current_delay_days"]),
            "Top Return Reason": selected["top_return_reason"],
        }
    )
    if st.button("Generate Action Plan", type="primary"):
        st.markdown(action_plan(selected, warehouse, skus, lifecycle_row))

    tab_vendor, tab_capacity, tab_returns, tab_lifecycle = st.tabs(
        ["Vendor Production Tracker", "Warehouse Capacity Scheduler", "Returns Intelligence", "PO-to-GRN Lifecycle"]
    )
    with tab_vendor:
        st.dataframe(production_milestones(data.purchase_orders), use_container_width=True, hide_index=True)
    with tab_capacity:
        st.dataframe(
            warehouse.assign(Utilization=lambda frame: (frame["utilization"] * 100).round(1).astype(str) + "%")
            [["date", "planned_inward_units", "capacity_units", "Utilization", "status"]]
            .rename(columns={"date": "Date", "planned_inward_units": "Planned Inward Units", "capacity_units": "Capacity", "status": "Status"}),
            use_container_width=True,
            hide_index=True,
        )
        st.plotly_chart(px.bar(warehouse, x="date", y=["planned_inward_units", "capacity_units"], barmode="group", title="Planned Inward vs Capacity"), use_container_width=True)
        st.info("Move 2,500 units from overloaded days to safe days, prioritize stockout-risk SKUs, and delay weak sell-through inbounding.")
    with tab_returns:
        returns_view = skus[["sku", "vendor", "return_rate", "top_return_reason"]].copy()
        returns_view["Action"] = returns_view.apply(
            lambda row: "Escalate vendor" if row["return_rate"] > 0.04 and is_quality_reason(row["top_return_reason"]) else "Monitor",
            axis=1,
        )
        returns_view["return_rate"] = (returns_view["return_rate"] * 100).round(1).astype(str) + "%"
        st.dataframe(
            returns_view.rename(columns={"sku": "SKU", "vendor": "Vendor", "return_rate": "Return Rate", "top_return_reason": "Main Reason"}),
            use_container_width=True,
            hide_index=True,
        )
    with tab_lifecycle:
        lifecycle_columns = {
            "po_id": "PO",
            "sku": "SKU",
            "vendor": "Vendor",
            "po_released": "PO Released",
            "vendor_manufacturing": "Vendor Manufacturing",
            "sample_inspection": "Sample Inspection",
            "catalogue_goods_dispatch": "Catalogue Goods Dispatch",
            "bulk_scan_pack": "Bulk Scan & Pack",
            "invoice_generation": "Invoice Generation",
            "approval": "Approval",
            "three_pl_pickup": "3PL Pickup",
            "three_pl_staging_warehouse": "3PL Staging Warehouse",
            "myntra_wh_allocation": "Myntra WH Allocation",
            "wh_transfer": "WH Transfer",
            "grn": "GRN",
            "inventory_live": "Inventory Live",
            "current_step": "Current Step",
            "blocked_reason": "Blocked Reason",
        }
        lifecycle_view = data.inbound_lifecycle.rename(columns=lifecycle_columns)
        st.dataframe(lifecycle_view, use_container_width=True, hide_index=True)
        if lifecycle_row is not None:
            st.warning(f"{selected_po} is at {lifecycle_row['current_step']}: {lifecycle_row['blocked_reason']}")


if __name__ == "__main__":
    render_dashboard()
