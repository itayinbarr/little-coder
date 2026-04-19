"""Generate all figures for the little-coder white paper.

Run:
    python docs/figures/make_paper_figures.py

Output:
    docs/figures/figure1_overall_performance.png
    docs/figures/figure2_cross_scaffold_overlap.png
    docs/figures/figure3_per_language_pass_rates.png
    docs/figures/figure4_first_attempt_vs_total.png
    docs/figures/figure5_time_economics.png
"""
from __future__ import annotations
from pathlib import Path
import json
import math
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import rcParams

# ── Style ────────────────────────────────────────────────────────────────────

ACCENT = "#2E5EAA"
ACCENT_LIGHT = "#6B9BD2"
BASELINE = "#D4654A"
GRAY = "#888888"
LIGHT_GRAY = "#C8C8C8"
TEXT = "#222222"
BG = "white"

def setup_style():
    rcParams["font.family"] = "DejaVu Sans"
    rcParams["axes.edgecolor"] = TEXT
    rcParams["axes.labelcolor"] = TEXT
    rcParams["xtick.color"] = TEXT
    rcParams["ytick.color"] = TEXT
    rcParams["text.color"] = TEXT

def clean_ax(ax):
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.spines["left"].set_linewidth(0.8)
    ax.tick_params(axis="both", length=3, width=0.8)
    ax.grid(False)

OUT = Path(__file__).parent
ROOT = Path(__file__).parent.parent.parent
r1 = json.loads((ROOT / "benchmarks/results_full_polyglot_run1.json").read_text())
r2 = json.loads((ROOT / "benchmarks/results_full_polyglot_run2.json").read_text())

LANGS = ["java", "python", "cpp", "javascript", "go", "rust"]
LANG_LABELS = {"java": "Java", "python": "Python", "cpp": "C++",
               "javascript": "JavaScript", "go": "Go", "rust": "Rust"}

AIDER_TOTAL = 43
AIDER_LANG = {"java": 11, "python": 6, "cpp": 7, "javascript": 9, "go": 5, "rust": 5}
AIDER_PASS_TIME = 141
AIDER_FAIL_TIME = 224

LB = {"gpt-4.5-preview": 44.9, "gpt-oss-120b (high)": 41.8}

def lang_pass(rd, lang):
    ld = rd["languages"][lang]
    return ld["pass_1"] + ld["pass_2"]

def lang_p1(rd, lang):
    return rd["languages"][lang]["pass_1"]

def lang_total(rd, lang):
    return rd["languages"][lang]["total"]

def sem(vals):
    if len(vals) < 2:
        return 0
    return np.std(vals, ddof=1) / math.sqrt(len(vals))


# ── Figure 1: Overall performance (mean + baseline only) ────────────────────

def fig1():
    run1_pct = 100 * r1["overall"]["passed"] / 225
    run2_pct = 100 * r2["overall"]["passed"] / 225
    mean_pct = (run1_pct + run2_pct) / 2
    mean_sem = sem([run1_pct, run2_pct])
    aider_pct = 100 * AIDER_TOTAL / 225

    fig, ax = plt.subplots(figsize=(6, 5.5), dpi=300)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    clean_ax(ax)

    # LC bar with SEM whiskers
    bar_lc = ax.bar(0, mean_pct, color=ACCENT, width=0.55, edgecolor="none",
                    yerr=mean_sem, capsize=6, error_kw={"linewidth": 1.8, "color": TEXT})
    # Aider bar — no whiskers (single run)
    bar_ai = ax.bar(1, aider_pct, color=BASELINE, width=0.55, edgecolor="none")

    ax.set_xticks([0, 1])
    ax.set_xticklabels(["little-coder\n(mean ± SEM)", "Aider"])

    ax.text(0, mean_pct + mean_sem + 1.2, f"{mean_pct:.1f}%",
            ha="center", va="bottom", fontsize=13, fontweight="bold", color=ACCENT)
    ax.text(1, aider_pct + 1.2, f"{aider_pct:.1f}%",
            ha="center", va="bottom", fontsize=13, fontweight="bold", color=BASELINE)

    for name, score in sorted(LB.items(), key=lambda x: -x[1]):
        ax.axhline(y=score, color=GRAY, linestyle="--", linewidth=0.9, alpha=0.5)
        ax.text(1.55, score + 0.5, f"{name} ({score}%)", fontsize=7.5,
                color=GRAY, ha="right", va="bottom", alpha=0.8)

    ax.set_ylabel("Aider Polyglot — % exercises solved", fontsize=11)
    ax.set_ylim(0, 55)
    ax.set_title("little-coder + Qwen3.5 9.7B vs. matched-model Aider",
                 fontsize=11, fontweight="bold", loc="left", pad=12)

    fig.tight_layout()
    fig.savefig(OUT / "figure1_overall_performance.png", dpi=300, bbox_inches="tight", facecolor=BG)
    print("wrote figure1")


# ── Figure 2: Cross-scaffold overlap (no title) ─────────────────────────────

def fig2():
    both_pass = 32
    both_fail = 113
    lc_only = 69
    aider_only = 11

    fig, ax = plt.subplots(figsize=(7, 5), dpi=300)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)

    cells = [
        (0, 1, both_pass, "Both pass", "#4CAF50", "white"),
        (1, 1, lc_only, "little-coder\nonly", ACCENT, "white"),
        (0, 0, aider_only, "Aider only", BASELINE, "white"),
        (1, 0, both_fail, "Both fail", LIGHT_GRAY, TEXT),
    ]

    for col, row, count, label, color, tcolor in cells:
        rect = plt.Rectangle((col, row), 0.95, 0.95, facecolor=color, edgecolor="white", linewidth=3)
        ax.add_patch(rect)
        ax.text(col + 0.475, row + 0.55, str(count),
                ha="center", va="center", fontsize=28, fontweight="bold", color=tcolor)
        ax.text(col + 0.475, row + 0.28, label,
                ha="center", va="center", fontsize=10, color=tcolor, alpha=0.9)

    ax.set_xlim(-0.1, 2.1)
    ax.set_ylim(-0.15, 2.15)
    ax.set_aspect("equal")

    ax.text(0.475, 2.08, "Pass", ha="center", fontsize=11, fontweight="bold", color="#4CAF50")
    ax.text(1.475, 2.08, "Fail", ha="center", fontsize=11, fontweight="bold", color=GRAY)
    ax.text(-0.08, 1.475, "P\na\ns\ns", ha="center", va="center", fontsize=10, fontweight="bold", color="#4CAF50", linespacing=0.8)
    ax.text(-0.08, 0.475, "F\na\ni\nl", ha="center", va="center", fontsize=10, fontweight="bold", color=GRAY, linespacing=0.8)

    ax.text(0.975, 2.25, "← Aider outcome →", ha="center", fontsize=9.5, color=GRAY)
    ax.text(-0.18, 0.975, "← little-coder →", ha="center", fontsize=9.5, color=GRAY, rotation=90)

    fig.tight_layout()
    fig.savefig(OUT / "figure2_cross_scaffold_overlap.png", dpi=300, bbox_inches="tight", facecolor=BG)
    print("wrote figure2")


# ── Figure 3: Per-language pass rates ────────────────────────────────────────

def fig3():
    lang_order = sorted(LANGS, key=lambda l: -(lang_pass(r1,l)+lang_pass(r2,l))/2/lang_total(r1,l))

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=300)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    clean_ax(ax)

    x = np.arange(len(lang_order))
    w = 0.35

    lc_means = []
    lc_sems = []
    aider_vals = []
    for lang in lang_order:
        t = lang_total(r1, lang)
        p1 = 100 * lang_pass(r1, lang) / t
        p2 = 100 * lang_pass(r2, lang) / t
        lc_means.append((p1+p2)/2)
        lc_sems.append(sem([p1, p2]))
        aider_vals.append(100 * AIDER_LANG[lang] / t)

    bars1 = ax.bar(x - w/2, lc_means, w, color=ACCENT, edgecolor="none",
                   yerr=lc_sems, capsize=4, error_kw={"linewidth": 1.2, "color": TEXT},
                   label="little-coder (mean ± SEM)")
    bars2 = ax.bar(x + w/2, aider_vals, w, color=BASELINE, edgecolor="none",
                   label="Aider")

    for bar, val in zip(bars1, lc_means):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2.5,
                f"{val:.1f}", ha="center", va="bottom", fontsize=9, color=ACCENT, fontweight="bold")
    for bar, val in zip(bars2, aider_vals):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"{val:.1f}", ha="center", va="bottom", fontsize=8, color=BASELINE)

    ax.set_xticks(x)
    ax.set_xticklabels([LANG_LABELS[l] for l in lang_order], fontsize=10.5)
    ax.set_ylabel("% exercises solved", fontsize=11)
    ax.set_ylim(0, 65)
    ax.legend(fontsize=9.5, loc="upper right", framealpha=0.9)
    ax.set_title("Per-language performance: little-coder vs. Aider",
                 fontsize=12, fontweight="bold", loc="left", pad=12)

    fig.tight_layout()
    fig.savefig(OUT / "figure3_per_language_pass_rates.png", dpi=300, bbox_inches="tight", facecolor=BG)
    print("wrote figure3")


# ── Figure 4: First attempt vs total ─────────────────────────────────────────

def fig4():
    lang_order = sorted(LANGS, key=lambda l: -(lang_pass(r1,l)+lang_pass(r2,l))/2/lang_total(r1,l))

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=300)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    clean_ax(ax)

    x = np.arange(len(lang_order))
    w = 0.35

    p1_means = []
    total_means = []
    p1_sems = []
    total_sems = []
    for lang in lang_order:
        t = lang_total(r1, lang)
        p1_r1 = 100 * lang_p1(r1, lang) / t
        p1_r2 = 100 * lang_p1(r2, lang) / t
        tot_r1 = 100 * lang_pass(r1, lang) / t
        tot_r2 = 100 * lang_pass(r2, lang) / t
        p1_means.append((p1_r1+p1_r2)/2)
        total_means.append((tot_r1+tot_r2)/2)
        p1_sems.append(sem([p1_r1, p1_r2]))
        total_sems.append(sem([tot_r1, tot_r2]))

    bars1 = ax.bar(x - w/2, p1_means, w, color=ACCENT_LIGHT, edgecolor="none",
                   yerr=p1_sems, capsize=4, error_kw={"linewidth": 1.2, "color": TEXT},
                   label="First attempt only")
    bars2 = ax.bar(x + w/2, total_means, w, color=ACCENT, edgecolor="none",
                   yerr=total_sems, capsize=4, error_kw={"linewidth": 1.2, "color": TEXT},
                   label="Total (with retry)")

    for i, (p1, tot) in enumerate(zip(p1_means, total_means)):
        delta = tot - p1
        if delta > 0:
            ax.annotate(f"+{delta:.1f}pp", xy=(x[i] + w/2, tot + 2),
                       fontsize=7.5, ha="center", color=ACCENT, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([LANG_LABELS[l] for l in lang_order], fontsize=10.5)
    ax.set_ylabel("% exercises solved", fontsize=11)
    ax.set_ylim(0, 65)
    ax.legend(fontsize=9.5, loc="upper right", framealpha=0.9)
    ax.set_title("First-attempt vs. total pass rate — the value of test-output-guided retry",
                 fontsize=11.5, fontweight="bold", loc="left", pad=12)

    fig.tight_layout()
    fig.savefig(OUT / "figure4_first_attempt_vs_total.png", dpi=300, bbox_inches="tight", facecolor=BG)
    print("wrote figure4")


# ── Figure 5: Time economics (no ratio annotations) ─────────────────────────

def fig5():
    lc_pass_times = []
    lc_fail_times = []
    for rd in [r1, r2]:
        pt = [e["time"] for l in LANGS for e in rd["languages"][l]["details"] if e["status"].startswith("pass")]
        ft = [e["time"] for l in LANGS for e in rd["languages"][l]["details"] if not e["status"].startswith("pass")]
        lc_pass_times.append(np.mean(pt))
        lc_fail_times.append(np.mean(ft))

    lc_pass = np.mean(lc_pass_times)
    lc_fail = np.mean(lc_fail_times)
    lc_pass_sem = sem(lc_pass_times)
    lc_fail_sem = sem(lc_fail_times)

    fig, ax = plt.subplots(figsize=(8, 5.5), dpi=300)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    clean_ax(ax)

    # LC bars with SEM whiskers
    ax.bar([0, 1], [lc_pass, lc_fail], color=[ACCENT_LIGHT, ACCENT], width=0.7, edgecolor="none",
           yerr=[lc_pass_sem, lc_fail_sem], capsize=5, error_kw={"linewidth": 1.2, "color": TEXT})
    # Aider bars — no whiskers (single run)
    ax.bar([2.5, 3.5], [AIDER_PASS_TIME, AIDER_FAIL_TIME], color=[BASELINE+"99", BASELINE],
           width=0.7, edgecolor="none")

    for pos, val, err, color in zip([0, 1, 2.5, 3.5],
                                     [lc_pass, lc_fail, AIDER_PASS_TIME, AIDER_FAIL_TIME],
                                     [lc_pass_sem, lc_fail_sem, 0, 0],
                                     [ACCENT_LIGHT, ACCENT, BASELINE+"99", BASELINE]):
        ax.text(pos, val + (err if err else 0) + 15, f"{val:.0f}s",
                ha="center", va="bottom", fontsize=10, fontweight="bold",
                color=color[:7] if len(color) > 7 else color)

    ax.set_xticks([0, 1, 2.5, 3.5])
    ax.set_xticklabels(["Pass", "Fail", "Pass", "Fail"], fontsize=10.5)
    ax.set_ylabel("Mean time per exercise (seconds)", fontsize=11)

    ax.text(0.5, -0.12, "little-coder", ha="center", fontsize=11, fontweight="bold",
            color=ACCENT, transform=ax.get_xaxis_transform())
    ax.text(3.0, -0.12, "Aider", ha="center", fontsize=11, fontweight="bold",
            color=BASELINE, transform=ax.get_xaxis_transform())

    ax.set_title("Time economics: little-coder explores longer, especially on failures",
                 fontsize=11.5, fontweight="bold", loc="left", pad=12)
    ax.set_ylim(0, max(lc_pass, lc_fail, AIDER_PASS_TIME, AIDER_FAIL_TIME) * 1.25)

    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(OUT / "figure5_time_economics.png", dpi=300, bbox_inches="tight", facecolor=BG)
    print("wrote figure5")


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    setup_style()
    fig1()
    fig2()
    fig3()
    fig4()
    fig5()
    print(f"\nall figures written to {OUT}/")
