import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="AutoCount Summary Tool", layout="wide")

st.title("AutoCount Summary Tool")

uploaded_file = st.file_uploader("Upload AutoCount CSV", type=["csv"])


def format_amount(value):
    try:
        num = round(float(value), 2)
        if num == int(num):
            return f"{int(num):,}"
        return f"{num:,.2f}".rstrip("0").rstrip(".")
    except Exception:
        return "0"


def get_category(row):
    method = str(row.get("Method", "")).strip()
    currency = str(row.get("Payment Currency", "")).strip()

    if method == "Visa/Master" and currency:
        return f"Visa/Master {currency}"

    mapping = {
        "USDT": "TRC",
        "USDT-TRC20": "TRC",
        "USDC-TRC20": "C-TRC",
        "USDT-BEP20": "BEP",
        "USDC-BEP20": "C-BEP",
        "USDT-ERC20": "ERC",
        "USDC-ERC20": "C-ERC",
    }

    if currency in mapping:
        return mapping[currency]

    return currency if currency else "Unknown"


def sort_order(category):
    category = str(category)

    if category.startswith("Visa/Master"):
        return 100

    crypto_sort = {
        "TRC": 200,
        "C-TRC": 201,
        "BEP": 202,
        "C-BEP": 203,
        "ERC": 204,
        "C-ERC": 205,
    }

    return crypto_sort.get(category, 1)


if uploaded_file is not None:
    try:
        df = pd.read_csv(
            uploaded_file,
            dtype={
                "MT Account": str,
                "MT Transaction ID": str,
                "User ID": str,
            },
            keep_default_na=False,
            quotechar='"',
            encoding="utf-8-sig",
        )

        required_columns = [
            "MT Transaction ID",
            "Method",
            "Payment Currency",
            "Credit Amount (USD)",
            "Debit Amount (USD)",
        ]

        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            st.error(f"CSV 缺少这些栏位：{missing_columns}")
            st.stop()

        if "Remarks" in df.columns:
            df["Remarks"] = (
                df["Remarks"]
                .astype(str)
                .str.replace("\n", " ", regex=False)
                .str.replace("\r", " ", regex=False)
            )

        df["Credit Amount (USD)"] = pd.to_numeric(
            df["Credit Amount (USD)"], errors="coerce"
        ).fillna(0)

        df["Debit Amount (USD)"] = pd.to_numeric(
            df["Debit Amount (USD)"], errors="coerce"
        ).fillna(0)

    # BaseID 删除逻辑：
        # 取 MT Transaction ID 中 "_" 前面的内容作为 BaseID
        df["BaseID"] = (
            df["MT Transaction ID"]
            .astype(str)
            .str.strip()
            .str.split("_")
            .str[0]
        )

        # 找出出现超过 1 次的 BaseID
        duplicate_base_ids = (
            df.loc[df["BaseID"].ne(""), "BaseID"]
            .value_counts()
            .loc[lambda counts: counts > 1]
            .index
        )

        # 删除所有 BaseID 重复的记录
        df_clean = df[
            ~df["BaseID"].isin(duplicate_base_ids)
        ].copy()

        # Category
        df_clean["Category"] = df_clean.apply(get_category, axis=1)
        df_clean["SortOrder"] = df_clean["Category"].apply(sort_order)

        result = (
            df_clean.groupby(["Category", "SortOrder"], as_index=False)
            .agg(
                Deposit=("Credit Amount (USD)", "sum"),
                Withdraw=("Debit Amount (USD)", "sum"),
            )
        )

        result["Balance"] = (result["Deposit"] - result["Withdraw"]).clip(lower=0)

        result = result[
            (result["Deposit"] > 0) | (result["Withdraw"] > 0)
        ].copy()

        result = result.sort_values(["SortOrder", "Category"])

        st.subheader("Manual Adjustment")

        if "manual_adjustments" not in st.session_state:
            st.session_state.manual_adjustments = []

        col_a, col_b, col_c, col_d = st.columns([1, 2, 2, 1])

        with col_a:
            adj_type = st.selectbox(
                "Type",
                ["Deposit", "Withdraw"]
            )

        category_options = sorted(
    result["Category"].dropna().unique().tolist()
)

        with col_b:
            adj_category = st.selectbox(
                "Category",
                category_options
            )

        with col_c:
            adj_amount = st.number_input(
                "Amount",
                min_value=0.0,
                step=1.0,
                format="%.2f"
            )

        with col_d:
            st.write("")
            st.write("")
            add_adjustment = st.button("Add")

        if add_adjustment and adj_amount > 0:
            st.session_state.manual_adjustments.append(
                {
                    "Type": adj_type,
                    "Category": adj_category,
                    "Amount": float(adj_amount),
                }
            )

        if st.session_state.manual_adjustments:
            st.write("Manual Adjustments")

            adj_df = pd.DataFrame(st.session_state.manual_adjustments)
            st.dataframe(adj_df, use_container_width=True, hide_index=True)

            if st.button("Clear Manual Adjustments"):
                st.session_state.manual_adjustments = []
                st.rerun()

            for adj in st.session_state.manual_adjustments:
                category = adj["Category"]
                amount = adj["Amount"]
                adj_type_current = adj["Type"]

                if category in result["Category"].values:
                    if adj_type_current == "Deposit":
                        result.loc[result["Category"] == category, "Deposit"] += amount
                    else:
                        result.loc[result["Category"] == category, "Withdraw"] += amount
                else:
                    new_row = {
                        "Category": category,
                        "SortOrder": sort_order(category),
                        "Deposit": amount if adj_type_current == "Deposit" else 0,
                        "Withdraw": amount if adj_type_current == "Withdraw" else 0,
                        "Balance": 0,
                    }
                    result = pd.concat([result, pd.DataFrame([new_row])], ignore_index=True)

            result["Balance"] = (result["Deposit"] - result["Withdraw"]).clip(lower=0)
            result = result.sort_values(["SortOrder", "Category"])

        deposit_text = " + ".join(
            f"{row.Category} {format_amount(row.Deposit)}"
            for row in result.itertuples()
            if row.Deposit > 0
        )

        withdraw_text = " + ".join(
            f"{row.Category} {format_amount(row.Withdraw)}"
            for row in result.itertuples()
            if row.Withdraw > 0
        )

        if deposit_text and withdraw_text:
            summary = f"混合入金 {deposit_text}，已出 {withdraw_text}"
        elif deposit_text:
            summary = f"混合入金 {deposit_text}"
        elif withdraw_text:
            summary = f"已出 {withdraw_text}"
        else:
            summary = "无交易"

        st.subheader("Summary")

        st.text_input(
            "Copy Summary",
            value=summary,
            label_visibility="collapsed"
        )

        st.subheader("Details")

        display = result[["Category", "Deposit", "Withdraw", "Balance"]].copy()

        for col in ["Deposit", "Withdraw", "Balance"]:
            display[col] = display[col].apply(format_amount)

        st.dataframe(display, use_container_width=True, hide_index=True)

        total_deposit = result["Deposit"].sum()
        total_withdraw = result["Withdraw"].sum()
        total_balance = result["Balance"].sum()

        st.subheader("Total")

        total_df = pd.DataFrame(
            {
                "Deposit": [format_amount(total_deposit)],
                "Withdraw": [format_amount(total_withdraw)],
                "Balance": [format_amount(total_balance)],
            }
        )

        st.dataframe(total_df, use_container_width=True, hide_index=True)

        st.subheader("Statistics")

        total_rows = len(df)
        valid_rows = len(df_clean)
        removed_rows = total_rows - valid_rows
        removed_base_ids = len(duplicate_base_ids)

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Original Rows", total_rows)
        col2.metric("Valid Rows", valid_rows)
        col3.metric("Removed Rows", removed_rows)
        col4.metric("Removed BaseID", removed_base_ids)

    except Exception as e:
        st.error("处理 CSV 时发生错误")
        st.exception(e)
