# -*- coding: utf-8 -*-
"""
Streamlit 前端：上传 run_template_trial 导出的 Excel，拆 home_metrics_blob 并导出
与 doc/抖音与拼多多运营看板数据模板.xlsx 同结构的运营看板表。

运行（在项目根目录）:
  streamlit run scripts/streamlit_home_blob_app.py
"""

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import streamlit as st

from postprocess_home_blob_metrics import (
    dataframe_to_excel_bytes,
    default_download_filename,
    process_excel_bytes,
)

st.set_page_config(page_title="抖音店铺指标后处理", layout="wide")
st.title("抖音店铺指标后处理")
st.caption(
    "上传采集结果 Excel（列：店铺名、键、标签、数据值）。"
    " 自动拆分 `home_metrics_blob`，并合并为「抖音与拼多多运营看板」模板列宽表后下载。"
)

uploaded = st.file_uploader(
    "拖拽文件到下方区域，或点击「Browse files」选择",
    type=["xlsx"],
    help="与命令行 postprocess_home_blob_metrics.py 使用相同逻辑",
)

if uploaded is not None:
    raw = uploaded.getvalue()
    try:
        df_long, n, df_kanban = process_excel_bytes(raw)
    except Exception as e:
        st.error(f"处理失败：{e}")
        st.stop()

    st.success(
        f"处理完成：blob 拆分更新 {n} 条；运营看板共 {len(df_kanban)} 个店铺行。"
    )
    st.subheader("运营看板预览（与模板列一致）")
    st.dataframe(df_kanban, use_container_width=True, height=420)

    with st.expander("查看中间长表（拆分后）"):
        st.dataframe(df_long, use_container_width=True, height=320)

    out_bytes = dataframe_to_excel_bytes(df_kanban)
    fname = default_download_filename()
    st.download_button(
        label=f"下载 {fname}",
        data=out_bytes,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    st.info("请先上传 `.xlsx` 文件。")
