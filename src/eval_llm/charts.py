"""Comparison charts for benchmark metrics.

Palette and chart rules follow a validated design system:
categorical hues are assigned to models in fixed slot order (never re-ranked),
magnitude grids use a single sequential hue, grid/axes stay recessive, and the
HTML report always ships the score tables alongside the charts.
"""

import base64
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from jinja2 import Template
from matplotlib.colors import LinearSegmentedColormap

# --- Design tokens (light mode) -------------------------------------------
SURFACE = '#fcfcfb'
INK = '#0b0b0b'
INK_SECONDARY = '#52514e'
MUTED = '#898781'
GRIDLINE = '#e1e0d9'
BASELINE = '#c3c2b7'

# Categorical slots 1-5, fixed order; slot i always belongs to model i
CATEGORICAL = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4',
               '#008300', '#4a3aa7', '#e34948']

# Sequential blue ramp, steps 100 -> 700
SEQUENTIAL = ['#cde2fb', '#b7d3f6', '#9ec5f4', '#86b6ef', '#6da7ec', '#5598e7',
              '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281',
              '#0d366b']
SEQ_CMAP = LinearSegmentedColormap.from_list('seq_blue', SEQUENTIAL)

plt.rcParams.update({
    'font.family': ['Segoe UI', 'DejaVu Sans', 'sans-serif'],
    'text.color': INK,
    'axes.edgecolor': BASELINE,
    'axes.labelcolor': INK_SECONDARY,
    'xtick.color': MUTED,
    'ytick.color': MUTED,
    'figure.facecolor': SURFACE,
    'axes.facecolor': SURFACE,
    'savefig.facecolor': SURFACE,
    'savefig.dpi': 150,
})


def _style_axis(ax):
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=GRIDLINE, linewidth=0.8)
    ax.xaxis.grid(False)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(BASELINE)
    ax.tick_params(length=0)


def _cell(metrics, model, benchmark):
    return metrics['cells'][f"{model}||{benchmark}"]


def chart_overall_by_benchmark(metrics, path):
    models = metrics['models']
    benchmarks = metrics['benchmarks']
    x = np.arange(len(benchmarks))
    group_width = 0.78
    bar_width = group_width / len(models)

    fig, ax = plt.subplots(figsize=(10, 5))
    for i, model in enumerate(models):
        values = [_cell(metrics, model, b)['overall'] for b in benchmarks]
        offset = (i - (len(models) - 1) / 2) * bar_width
        ax.bar(x + offset, values, width=bar_width, color=CATEGORICAL[i],
               edgecolor=SURFACE, linewidth=1.2, label=model)

    _style_axis(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(benchmarks, color=INK_SECONDARY)
    ax.set_ylim(0, 10)
    ax.set_yticks(range(0, 11, 2))
    ax.set_ylabel('Average score (1-10)')
    ax.set_title('Overall score by benchmark', color=INK, loc='left',
                 fontsize=13, fontweight='bold', pad=14)
    ax.legend(frameon=False, ncol=min(len(models), 5), loc='upper center',
              bbox_to_anchor=(0.5, -0.10), labelcolor=INK_SECONDARY, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)


def chart_heatmap(metrics, path):
    models = metrics['models']
    benchmarks = metrics['benchmarks']
    grid = np.array([[_cell(metrics, m, b)['overall'] for b in benchmarks]
                     for m in models])

    fig, ax = plt.subplots(figsize=(9, 0.9 * len(models) + 1.6))
    vmin, vmax = 0, 10
    ax.imshow(grid, cmap=SEQ_CMAP, vmin=vmin, vmax=vmax, aspect='auto')

    for r in range(len(models)):
        for c in range(len(benchmarks)):
            value = grid[r, c]
            frac = (value - vmin) / (vmax - vmin)
            ax.text(c, r, f'{value:.1f}', ha='center', va='center', fontsize=10,
                    color='#ffffff' if frac > 0.55 else INK)

    ax.set_xticks(range(len(benchmarks)))
    ax.set_xticklabels(benchmarks, color=INK_SECONDARY, fontsize=9)
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models, color=INK_SECONDARY, fontsize=9)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    # White gaps between cells
    ax.set_xticks(np.arange(-0.5, len(benchmarks)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(models)), minor=True)
    ax.grid(which='minor', color=SURFACE, linewidth=2)
    ax.tick_params(which='minor', length=0)
    ax.set_title('Model x benchmark — average score (1-10)', color=INK,
                 loc='left', fontsize=13, fontweight='bold', pad=14)
    fig.tight_layout()
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)


def chart_criteria_small_multiples(metrics, path):
    models = metrics['models']
    benchmarks = metrics['benchmarks']
    ncols = 3
    nrows = int(np.ceil(len(benchmarks) / ncols))

    fig, axes = plt.subplots(nrows, ncols, figsize=(13, 3.6 * nrows))
    axes = np.atleast_1d(axes).ravel()

    for ax_index, benchmark in enumerate(benchmarks):
        ax = axes[ax_index]
        criteria = metrics['criteria'][benchmark]
        x = np.arange(len(criteria))
        group_width = 0.78
        bar_width = group_width / len(models)
        for i, model in enumerate(models):
            per_criterion = _cell(metrics, model, benchmark)['per_criterion']
            values = [per_criterion.get(c, 0.0) for c in criteria]
            offset = (i - (len(models) - 1) / 2) * bar_width
            ax.bar(x + offset, values, width=bar_width, color=CATEGORICAL[i],
                   edgecolor=SURFACE, linewidth=1.0,
                   label=model if ax_index == 0 else None)
        _style_axis(ax)
        ax.set_xticks(x)
        ax.set_xticklabels(criteria, color=INK_SECONDARY, fontsize=8)
        ax.set_ylim(0, 10)
        ax.set_yticks(range(0, 11, 2))
        ax.set_title(benchmark, color=INK, loc='left', fontsize=11,
                     fontweight='bold')

    for ax in axes[len(benchmarks):]:
        ax.axis('off')

    fig.suptitle('Per-criterion scores by benchmark', color=INK, x=0.01,
                 ha='left', fontsize=13, fontweight='bold')
    fig.legend(frameon=False, ncol=min(len(models), 5), loc='upper center',
               bbox_to_anchor=(0.5, 0.965), labelcolor=INK_SECONDARY, fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)


def chart_overall_ranking(metrics, path):
    ranked = sorted(metrics['model_overall'].items(), key=lambda kv: kv[1])
    names = [name for name, _ in ranked]
    values = [value for _, value in ranked]

    fig, ax = plt.subplots(figsize=(9, 0.65 * len(names) + 1.4))
    # Magnitude ranking: one hue for all bars; color never encodes rank
    ax.barh(names, values, height=0.6, color=CATEGORICAL[0],
            edgecolor=SURFACE, linewidth=1.2)
    for i, value in enumerate(values):
        ax.text(value + 0.12, i, f'{value:.2f}', va='center', fontsize=9,
                color=INK_SECONDARY)

    ax.set_axisbelow(True)
    ax.xaxis.grid(True, color=GRIDLINE, linewidth=0.8)
    for side in ('top', 'right', 'bottom'):
        ax.spines[side].set_visible(False)
    ax.spines['left'].set_color(BASELINE)
    ax.tick_params(length=0)
    ax.set_xlim(0, 10)
    ax.tick_params(axis='y', labelcolor=INK_SECONDARY)
    ax.set_xlabel('Average score across all benchmarks (1-10)')
    ax.set_title('Overall ranking', color=INK, loc='left', fontsize=13,
                 fontweight='bold', pad=14)
    fig.tight_layout()
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)


def generate_charts(metrics, charts_dir):
    os.makedirs(charts_dir, exist_ok=True)
    paths = {}
    jobs = [
        ('overall_by_benchmark', chart_overall_by_benchmark),
        ('heatmap_model_benchmark', chart_heatmap),
        ('criteria_by_benchmark', chart_criteria_small_multiples),
        ('overall_ranking', chart_overall_ranking),
    ]
    for name, fn in jobs:
        path = os.path.join(charts_dir, f'{name}.png')
        fn(metrics, path)
        paths[name] = path
    return paths


# ---------------------------------------------------------------------------
# HTML report (charts + score tables — the tables are the accessibility view)
# ---------------------------------------------------------------------------

REPORT_TEMPLATE = Template("""
<html>
<head>
<meta charset="utf-8">
<title>LLM Benchmark Comparison</title>
<style>
    body { font-family: 'Segoe UI', system-ui, sans-serif; background: #f9f9f7;
           color: #0b0b0b; margin: 0; padding: 32px; }
    .wrap { max-width: 1100px; margin: 0 auto; }
    h1 { font-size: 22px; } h2 { font-size: 16px; margin-top: 32px; }
    .card { background: #fcfcfb; border: 1px solid rgba(11,11,11,0.10);
            border-radius: 8px; padding: 20px; margin: 16px 0; overflow-x: auto; }
    img { max-width: 100%; height: auto; display: block; }
    table { border-collapse: collapse; font-size: 13px; width: 100%; }
    th, td { padding: 6px 12px; text-align: left; border-bottom: 1px solid #e1e0d9; }
    th { color: #52514e; font-weight: 600; }
    td.num { text-align: right; font-variant-numeric: tabular-nums; }
    .muted { color: #898781; font-size: 12px; }
</style>
</head>
<body>
<div class="wrap">
    <h1>LLM Benchmark Comparison</h1>
    <p class="muted">{{ metrics['models']|length }} models &times;
       {{ metrics['benchmarks']|length }} benchmarks &mdash; scores are 1&ndash;10,
       averaged over questions. Score 0 rows were excluded (errors).</p>

    {% for name, b64 in charts %}
    <div class="card"><img src="data:image/png;base64,{{ b64 }}" alt="{{ name }}"></div>
    {% endfor %}

    <h2>Overall scores (table)</h2>
    <div class="card">
    <table>
        <tr><th>Model</th>
        {% for b in metrics['benchmarks'] %}<th>{{ b }}</th>{% endfor %}
        <th>Overall</th></tr>
        {% for m in metrics['models'] %}
        <tr><td>{{ m }}</td>
        {% for b in metrics['benchmarks'] %}
            <td class="num">{{ '%.2f' % metrics['cells'][m ~ '||' ~ b]['overall'] }}</td>
        {% endfor %}
        <td class="num"><strong>{{ '%.2f' % metrics['model_overall'][m] }}</strong></td></tr>
        {% endfor %}
    </table>
    </div>

    {% for b in metrics['benchmarks'] %}
    <h2>{{ b }} — per criterion</h2>
    <div class="card">
    <table>
        <tr><th>Model</th>
        {% for c in metrics['criteria'][b] %}<th>{{ c }}</th>{% endfor %}</tr>
        {% for m in metrics['models'] %}
        <tr><td>{{ m }}</td>
        {% for c in metrics['criteria'][b] %}
            <td class="num">{{ '%.2f' % metrics['cells'][m ~ '||' ~ b]['per_criterion'].get(c, 0) }}</td>
        {% endfor %}</tr>
        {% endfor %}
    </table>
    </div>
    {% endfor %}
</div>
</body>
</html>
""")


def generate_html_report(metrics, chart_paths, output_path):
    charts = []
    for name in ('overall_ranking', 'overall_by_benchmark',
                 'heatmap_model_benchmark', 'criteria_by_benchmark'):
        with open(chart_paths[name], 'rb') as f:
            charts.append((name, base64.b64encode(f.read()).decode('ascii')))
    html = REPORT_TEMPLATE.render(metrics=metrics, charts=charts)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return output_path
