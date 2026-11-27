"""Plot the observed additional-demand distribution in the synthetic train split."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


def plot(dataset: Path, output: Path) -> None:
    train = dataset / "train.csv"
    metadata = json.loads((dataset / "metadata.json").read_text(encoding="utf-8"))
    if hashlib.sha256(train.read_bytes()).hexdigest() != metadata["sha256"][train.name]:
        raise ValueError("train.csv differs from the dataset metadata")
    catalog_path = Path(__file__).resolve().parents[4] / "ml/config/catalog-and-bom-v1.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if hashlib.sha256(catalog_path.read_bytes()).hexdigest() != metadata["fixture_sha256"][catalog_path.name]:
        raise ValueError("BOM catalog differs from the dataset metadata")
    amounts = {row["ingredient_id"]: [] for row in catalog["ingredients"]}
    with train.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            amounts[row["ingredient_id"]].append(float(row["target_native"]))

    fig, axes = plt.subplots(3, 2, figsize=(11, 9), layout="constrained")
    fig.suptitle("Distribusi target kebutuhan tambahan sintetis", fontsize=19, fontweight="bold")
    zero_rates = []
    names = []
    for ax, item in zip(axes.flat[:5], catalog["ingredients"], strict=True):
        name = item["name"]
        unit = item["base_unit"]
        values = amounts[item["ingredient_id"]]
        positive = [value for value in values if value > 0]
        names.append(name)
        zero_rates.append(100 * values.count(0) / len(values))
        ax.hist(positive, bins=16, color="#11645c", edgecolor="white")
        ax.set_title(f"{name} · {len(positive):,} label positif".replace(",", "."), loc="left", pad=8)
        ax.set_xlabel(f"Kebutuhan tambahan ({unit})")
        ax.set_ylabel("Jumlah baris train")
        ax.spines[["top", "right"]].set_visible(False)

    ax = axes.flat[5]
    bars = ax.barh(names, zero_rates, color="#965319")
    ax.bar_label(bars, [f"{rate:.1f}%".replace(".", ",") for rate in zero_rates], padding=3)
    ax.invert_yaxis()
    ax.set_xlim(0, 65)
    ax.set_title("Proporsi label nol", loc="left", pad=8)
    ax.set_xlabel("Persen dari baris train per bahan")
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(output, dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("ml/generated/synthetic-v1"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("07-synthetic-distributions.png"))
    args = parser.parse_args()
    plot(args.dataset, args.output)
