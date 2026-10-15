"""Shared HTML chart rendering, including fixed-width, scrollable category names."""

import plotly.graph_objects as go

from luxtrade.viz.registry import plotly_config

# Names are inserted as textContent, never interpolated into HTML or JavaScript.
# Plotly's coordinate conversion keeps labels aligned after re-ranking and resizing.
CATEGORY_LABELS_JS = """
function installCategoryLabels(graph) {
    graph.style.position = 'relative';
    graph.classList.add('luxtrade-scroll-labels');
    const style = document.createElement('style');
    style.textContent = `
        .luxtrade-scroll-labels .yaxislayer-above .ytick text { visibility: hidden; }
        .luxtrade-category-names { overflow-x: auto; overflow-y: hidden; }
        .luxtrade-category-names:focus-visible { outline: 2px solid #2a78d6; }
    `;
    graph.appendChild(style);
    const pane = document.createElement('div');
    pane.className = 'luxtrade-category-names';
    pane.tabIndex = 0;
    pane.setAttribute('role', 'region');
    pane.setAttribute('aria-label', 'Category names — scroll horizontally for long names');
    pane.style.position = 'absolute';
    const content = document.createElement('div');
    content.style.position = 'relative';
    pane.appendChild(content);
    graph.appendChild(pane);
    const measure = document.createElement('canvas').getContext('2d');
    let pending = false;
    let active = true;
    function update() {
        pending = false;
        if (!active) return;
        const layout = graph._fullLayout;
        if (!layout || !layout.yaxis || !layout._size) return;
        const settings = graph.layout.meta.category_labels;
        const size = layout._size;
        const axis = layout.yaxis;
        const font = axis.tickfont;
        measure.font = `${font.size}px ${font.family}`;
        let contentWidth = settings.width;
        for (const name of settings.names) {
            contentWidth = Math.max(contentWidth, Math.ceil(measure.measureText(name).width) + 12);
        }
        const position = pane.scrollLeft;
        Object.assign(pane.style, {
            left: `${size.l - settings.width - 8}px`, top: `${size.t}px`,
            width: `${settings.width}px`, height: `${size.h + 18}px`,
            fontFamily: font.family, fontSize: `${font.size}px`, color: font.color,
            colorScheme: layout.paper_bgcolor === 'rgba(0,0,0,0)' ? 'inherit' : 'normal',
        });
        content.style.width = `${contentWidth}px`;
        content.style.height = `${size.h}px`;
        content.replaceChildren();
        for (const name of graph.data[0].y) {
            const row = document.createElement('div');
            row.textContent = name;
            row.title = name;
            Object.assign(row.style, {
                position: 'absolute', left: '0', top: `${axis.d2p(name)}px`,
                transform: 'translateY(-50%)', lineHeight: '18px', whiteSpace: 'nowrap',
            });
            content.appendChild(row);
        }
        pane.scrollLeft = position;
    }
    function schedule() {
        if (!pending) { pending = true; requestAnimationFrame(update); }
    }
    graph.on('plotly_afterplot', schedule);
    graph.on('plotly_animated', schedule);
    graph.on('plotly_sliderchange', schedule);
    update();
    return () => {
        active = false;
        for (const event of ['plotly_afterplot', 'plotly_animated', 'plotly_sliderchange']) {
            graph.removeListener(event, schedule);
        }
        graph.classList.remove('luxtrade-scroll-labels');
        pane.remove();
        style.remove();
    };
}
"""


def has_scrollable_categories(figure: go.Figure) -> bool:
    """Whether a chart requests the scrollable category-name presentation."""
    meta = figure.layout.meta
    return isinstance(meta, dict) and "category_labels" in meta


def chart_html(figure: go.Figure) -> str:
    """Render offline-capable HTML, retaining animation and scrollable labels."""
    post_script = None
    if has_scrollable_categories(figure):
        post_script = CATEGORY_LABELS_JS + (
            "\ninstallCategoryLabels(document.getElementById('{plot_id}'));"
        )
    return figure.to_html(
        full_html=True,
        include_plotlyjs=True,
        auto_play=False,
        config=plotly_config(figure),
        post_script=post_script,
    )
