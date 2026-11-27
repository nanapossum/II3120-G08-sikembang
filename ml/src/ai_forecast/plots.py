"""Publication figures for the synthetic holdout and validation ablation."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

COLORS = {"xgboost": "#11645C", "historical_median": "#965319", "zero": "#777C84"}
LABELS = {"xgboost": "XGBoost", "historical_median": "Median historis", "zero": "Nol tambahan"}
INK = "#17232B"


def _panels(title, subtitle):
    fig, axes = plt.subplots(3, 2, figsize=(11, 9), layout="constrained")
    fig.suptitle(f"{title}\n{subtitle} · Data sintetis SiKembang", x=0.02, ha="left", fontsize=14)
    axes.flat[-1].set_visible(False)
    return fig, list(axes.flat)


def _style(ax, title, label, horizontal=False):
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
    ax.set_xlabel(label if horizontal else "")
    if not horizontal:
        ax.set_ylabel(label)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x" if horizontal else "y", alpha=0.18)
    ax.set_axisbelow(True)


def _save(fig, directory, filename):
    for ext in ("png", "svg"):
        fig.savefig(directory / f"{filename}.{ext}", dpi=220, facecolor="white")
    plt.close(fig)


def render(directory, rows, predictions, names, units, ingredient_names, metrics, gain, ablation):
    directory.mkdir()
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK,
                         "axes.labelcolor": INK, "svg.fonttype": "none"})

    fig, axes = _panels("Kebutuhan tambahan aktual dan prediksi", "Test · cutoff Senin 00.00 WIB")
    for ax, (ingredient, unit) in zip(axes, sorted(units.items())):
        indices = sorted((i for i, row in enumerate(rows) if row.ingredient == ingredient and row.offset == 0),
                         key=lambda i: rows[i].target)
        dates = [rows[i].target for i in indices]
        ax.plot(dates, [rows[i].actual for i in indices], color=INK, lw=1.2, label="Aktual")
        ax.plot(dates, predictions["xgboost"][indices], color=COLORS["xgboost"], lw=1.4, label="XGBoost")
        ax.plot(dates, predictions["historical_median"][indices], color=COLORS["historical_median"],
                lw=1.1, linestyle="--", label="Median historis")
        _style(ax, ingredient_names[ingredient], unit)
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
        if ax == axes[0]:
            ax.legend(frameon=False, ncols=3, loc="upper left", fontsize=8)
    _save(fig, directory, "01-actual-vs-predicted")

    for filename, name in [("02-mae", "mae"), ("03-rmse", "rmse")]:
        fig, axes = _panels(f"Perbandingan {name.upper()} per bahan", "Test · seluruh origin")
        for ax, (ingredient, unit) in zip(axes, sorted(units.items())):
            methods = ["xgboost", "historical_median", "zero"]
            data = metrics["ingredients"][ingredient]["metrics"]
            bars = ax.barh([LABELS[m] for m in methods], [data[m][name] for m in methods],
                           color=[COLORS[m] for m in methods])
            ax.bar_label(bars, fmt="%.2f", padding=3)
            ax.margins(x=0.22)
            ax.invert_yaxis()
            _style(ax, ingredient_names[ingredient], unit, horizontal=True)
        _save(fig, directory, filename)

    fig, axes = _panels("Distribusi residual XGBoost", "Test · prediksi dikurangi aktual")
    for ax, (ingredient, unit) in zip(axes, sorted(units.items())):
        residual = [predictions["xgboost"][i] - row.actual for i, row in enumerate(rows)
                    if row.ingredient == ingredient]
        ax.hist(residual, bins=28, color=COLORS["xgboost"], edgecolor="white")
        ax.axvline(0, color=INK, linestyle="--", lw=1)
        _style(ax, ingredient_names[ingredient], "Frekuensi")
        ax.set_xlabel(f"Residual ({unit})")
    _save(fig, directory, "04-residuals")

    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    ordered = sorted(names, key=lambda name: (gain.get(name, 0), name))
    ax.barh(ordered, [gain.get(name, 0) for name in ordered],
            color=["#965319" if name in ("prev_error_adj", "feedback_available") else "#11645C"
                   for name in ordered])
    _style(ax, "Feature importance XGBoost · Data sintetis SiKembang", "Gain rata-rata", horizontal=True)
    _save(fig, directory, "05-feature-importance")

    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    groups = ["Seluruh validation", *(f"Blok {i}" for i in range(1, 1 + len(ablation["blocks"])))]
    x = np.arange(len(groups))
    values = [ablation["overall"], *ablation["blocks"]]
    for offset, key, title, color in [(-0.17, "full", "Dengan feedback", "#11645C"),
                                      (0.17, "without_feedback", "Tanpa feedback", "#965319")]:
        bars = ax.bar(x + offset, [v[key] for v in values], width=0.34, label=title, color=color)
        ax.bar_label(bars, fmt="%.5f", padding=3, fontsize=8)
    ax.margins(y=0.22)
    ax.set_xticks(x, groups)
    ax.legend(frameon=False, ncols=2)
    _style(ax, "Ablation feedback minggu lalu · Data sintetis SiKembang", "MAE ternormalisasi")
    _save(fig, directory, "06-feedback-ablation")
