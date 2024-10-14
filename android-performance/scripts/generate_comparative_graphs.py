import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from math import pi
import numpy as np
import argparse


def load_combined_data(timestamp):
    # Load data for both browsers
    df_chrome = pd.read_csv(
        f"./android-performance/data/chrome/{timestamp}/results/performance_metrics.csv"
    )
    df_firefox = pd.read_csv(
        f"./android-performance/data/firefox/{timestamp}/results/performance_metrics.csv"
    )

    # Combine DataFrames
    df_combined = pd.concat([df_chrome, df_firefox], ignore_index=True)
    return df_combined


def plot_grouped_bar_chart(df, output_dir, metric, top_n=10):
    sns.set_style("whitegrid")
    # Get top N websites based on the average of the metric, for sites with data from both browsers
    df_metric = df.dropna(subset=[metric])
    sites_with_both_browsers = df_metric.groupby("website")["browser"].nunique()
    valid_sites = sites_with_both_browsers[sites_with_both_browsers == 2].index
    df_metric = df_metric[df_metric["website"].isin(valid_sites)]
    top_sites = (
        df_metric.groupby("website")[metric]
        .mean()
        .sort_values(ascending=False)
        .head(top_n)
        .index
    )
    df_top_sites = df_metric[df_metric["website"].isin(top_sites)]
    if df_top_sites.empty:
        print(f"No data available for {metric}, skipping grouped bar chart.")
        return
    plt.figure(figsize=(12, 8))
    sns.barplot(x=metric, y="website", hue="browser", data=df_top_sites, orient="h")
    plt.title(
        f'Comparison of {metric.replace("_", " ").title()} for Top {top_n} Websites'
    )
    plt.xlabel(f'{metric.replace("_", " ").title()} (ms)')
    plt.ylabel("Website")
    plt.legend(title="Browser")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"grouped_bar_{metric}.png"))
    plt.close()


def plot_comparative_box_plots(df, output_dir, metric):
    sns.set_style("whitegrid")
    plt.figure(figsize=(8, 6))
    sns.boxplot(data=df, x="browser", y=metric)
    plt.title(f'Comparison of {metric.replace("_", " ").title()} Across Browsers')
    plt.xlabel("Browser")
    plt.ylabel(f'{metric.replace("_", " ").title()} (ms)')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"comparative_box_{metric}.png"))
    plt.close()


def plot_comparative_violin_plots(df, output_dir, metric):
    sns.set_style("whitegrid")
    plt.figure(figsize=(8, 6))
    sns.violinplot(data=df, x="browser", y=metric, inner="quartile")
    plt.title(f'Comparison of {metric.replace("_", " ").title()} Across Browsers')
    plt.xlabel("Browser")
    plt.ylabel(f'{metric.replace("_", " ").title()} (ms)')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"comparative_violin_{metric}.png"))
    plt.close()


def plot_correlation_heatmap(df, output_dir):
    sns.set_style("whitegrid")
    numeric_cols = df.select_dtypes(include=["float64", "int64"]).columns
    df_numeric = df[numeric_cols].dropna()
    if df_numeric.empty:
        print("No numeric data available for correlation matrix, skipping.")
        return
    corr = df_numeric.corr()
    plt.figure(figsize=(12, 10))
    sns.heatmap(corr, annot=True, cmap="coolwarm")
    plt.title("Correlation Heatmap of Performance Metrics")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "correlation_heatmap.png"))
    plt.close()


def plot_performance_difference(df, output_dir, metric):
    # Pivot the DataFrame to have browsers as columns
    df_pivot = df.pivot_table(index="website", columns="browser", values=metric)
    df_pivot = df_pivot.dropna()
    if df_pivot.empty:
        print(f"No data available for {metric}, skipping performance difference plot.")
        return
    # Check if both browsers have data for this metric
    browsers = df_pivot.columns.tolist()
    if len(browsers) != 2:
        print(f"Not enough data for both browsers for {metric}, skipping plot.")
        return
    browser_a, browser_b = browsers
    df_pivot["difference"] = df_pivot[browser_a] - df_pivot[browser_b]
    plt.figure(figsize=(12, 8))
    sns.barplot(
        x="difference", y=df_pivot.index, data=df_pivot.reset_index(), orient="h"
    )
    plt.title(
        f'Difference in {metric.replace("_", " ").title()} Between {browser_a} and {browser_b}'
    )
    plt.xlabel(f'Difference in {metric.replace("_", " ").title()} (ms)')
    plt.ylabel("Website")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"performance_difference_{metric}.png"))
    plt.close()


def plot_scatter_with_regression(df, output_dir, x_metric, y_metric):
    sns.set_style("whitegrid")
    sns.lmplot(data=df, x=x_metric, y=y_metric, hue="browser", height=6, aspect=1.5)
    plt.title(
        f'{y_metric.replace("_", " ").title()} vs {x_metric.replace("_", " ").title()}'
    )
    plt.xlabel(f'{x_metric.replace("_", " ").title()}')
    plt.ylabel(f'{y_metric.replace("_", " ").title()}')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"scatter_{x_metric}_vs_{y_metric}.png"))
    plt.close()


def plot_radar_chart(df, output_dir):
    sns.set_style("whitegrid")
    # Calculate average metrics per browser
    metrics = [
        "total_page_load_time_ms",
        "ttfb_ms",
        "content_download_time_ms",
        "adjusted_dom_parsing_time_ms",
        "adjusted_rendering_time_ms",
        "adjusted_browser_processing_time_ms",
        "first_paint_ms",
        "first_contentful_paint_ms",
    ]
    df_avg = df.groupby("browser")[metrics].mean()
    # Normalize the data (0-100 scale)
    df_normalized = df_avg.copy()
    for metric in metrics:
        min_val = df_avg[metric].min()
        max_val = df_avg[metric].max()
        df_normalized[metric] = 100 * (df_avg[metric] - min_val) / (max_val - min_val)
    # Prepare data for radar chart
    categories = metrics
    N = len(categories)
    angles = [n / float(N) * 2 * pi for n in range(N)]
    angles += angles[:1]  # Complete the loop
    plt.figure(figsize=(8, 8))
    ax = plt.subplot(111, polar=True)
    # Draw one axis per variable + add labels
    plt.xticks(
        angles[:-1],
        [c.replace("_", " ").title() for c in categories],
        color="grey",
        size=8,
    )
    # Draw ylabels
    ax.set_rlabel_position(0)
    plt.yticks(
        [20, 40, 60, 80, 100], ["20", "40", "60", "80", "100"], color="grey", size=7
    )
    plt.ylim(0, 100)
    # Plot data
    for index, row in df_normalized.iterrows():
        values = row.tolist()
        values += values[:1]
        ax.plot(angles, values, linewidth=1, linestyle="solid", label=index)
        ax.fill(angles, values, alpha=0.1)
    plt.legend(loc="upper right", bbox_to_anchor=(0.1, 0.1))
    plt.title("Normalized Average Performance Metrics Comparison")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "radar_chart.png"))
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Generate comparative performance graphs."
    )
    parser.add_argument(
        "--timestamp", type=str, required=True, help="Timestamp of the test run"
    )
    args = parser.parse_args()
    timestamp = args.timestamp
    df_combined = load_combined_data(timestamp)
    output_dir = f"./android-performance/visualizations/combined_results/{timestamp}"
    os.makedirs(output_dir, exist_ok=True)

    # Ensure the necessary columns are present
    required_columns = [
        "browser",
        "website",
        "total_page_load_time_ms",
        "ttfb_ms",
        "content_download_time_ms",
        "adjusted_dom_parsing_time_ms",
        "adjusted_rendering_time_ms",
        "adjusted_browser_processing_time_ms",
        "first_paint_ms",
        "first_contentful_paint_ms",
        "total_transfer_size_bytes",
    ]
    missing_columns = [
        col for col in required_columns if col not in df_combined.columns
    ]
    if missing_columns:
        print(f"Missing columns in the data: {missing_columns}")
        return

    # Generate comparative plots
    metrics = [
        "total_page_load_time_ms",
        "ttfb_ms",
        "content_download_time_ms",
        "adjusted_dom_parsing_time_ms",
        "adjusted_rendering_time_ms",
        "adjusted_browser_processing_time_ms",
        "first_paint_ms",
        "first_contentful_paint_ms",
    ]

    # Generate the plots
    for metric in metrics:
        # Check if both browsers have data for the metric
        browsers_with_data = df_combined.dropna(subset=[metric])["browser"].unique()
        if len(browsers_with_data) < 2:
            print(f"Not enough data for both browsers for {metric}, skipping plots.")
            continue
        plot_comparative_box_plots(df_combined, output_dir, metric)
        plot_comparative_violin_plots(df_combined, output_dir, metric)
        plot_grouped_bar_chart(df_combined, output_dir, metric, top_n=10)
        plot_performance_difference(df_combined, output_dir, metric)

    # Generate correlation heatmap
    plot_correlation_heatmap(df_combined, output_dir)

    # Plot scatter with regression for selected metrics
    # For example, plot adjusted browser processing time vs total transfer size
    plot_scatter_with_regression(
        df_combined,
        output_dir,
        "total_transfer_size_bytes",
        "adjusted_browser_processing_time_ms",
    )

    # Plot radar chart
    plot_radar_chart(df_combined, output_dir)

    print(f"Graphs have been generated and saved in {output_dir}")


if __name__ == "__main__":
    main()
