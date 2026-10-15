"""Native Plotly charts with an optional, independently scrollable category column."""

import plotly.graph_objects as go
import streamlit as st

from luxtrade.viz.html import CATEGORY_LABELS_JS, has_scrollable_categories
from luxtrade.viz.registry import plotly_config

_LABEL_COMPONENT_JS = (
    CATEGORY_LABELS_JS
    + """
export default function(component) {
    const {parentElement, data} = component;
    const container = parentElement.closest(`.st-key-${CSS.escape(data.container)}`);
    if (!container) return;
    let cleanup;
    function attach() {
        const graph = container.querySelector('.js-plotly-plot');
        if (!graph || !graph._fullLayout || !graph.layout?.meta?.category_labels) return;
        cleanup = installCategoryLabels(graph);
        observer.disconnect();
    }
    const observer = new MutationObserver(attach);
    observer.observe(container, {childList: true, subtree: true});
    attach();
    return () => { observer.disconnect(); if (cleanup) cleanup(); };
}
"""
)


def render_chart(figure: go.Figure, key: str) -> None:
    """Preserve Streamlit's theming and animation while enhancing overflowing labels."""
    if has_scrollable_categories(figure):
        # Register in the current app runtime, including fresh AppTest runtimes.
        # Identical definitions are deduplicated by Streamlit's component registry.
        label_component = st.components.v2.component(
            "luxtrade_category_names", js=_LABEL_COMPONENT_JS, isolate_styles=False
        )
        container_key = f"{key}-labels"
        with st.container(key=container_key):
            st.plotly_chart(figure, key=key, config=plotly_config(figure))
            label_component(
                data={"container": container_key},
                key=f"{key}-category-names",
                height=0,
            )
    else:
        st.plotly_chart(figure, key=key, config=plotly_config(figure))
