import os
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import argparse


def generate_box_plots(df, output_dir):
    sns.set_style("whitegrid")
    metrics = [
        "total_page_load_time_ms",
        "ttfb_ms",
        "content_download_time_ms",
        "adjusted_dom_parsing_time_ms",
        "adjusted_rendering_time_ms",
        "first_paint_ms",
        "first_contentful_paint_ms",
    ]
    for metric in metrics:
        df_metric = df.dropna(subset=[metric])
        if df_metric.empty:
            print(f"No data available for {metric}, skipping box plot.")
            continue
        plt.figure(figsize=(12, 6))
        sns.boxplot(data=df_metric, y=metric)
        plt.title(f'Distribution of {metric.replace("_", " ").title()}')
        plt.ylabel(f'{metric.replace("_", " ").title()} (ms)')
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f"{metric}_boxplot.png"))
        plt.close()


def generate_histograms(df, output_dir):
    sns.set_style("whitegrid")
    metrics = [
        "total_page_load_time_ms",
        "ttfb_ms",
        "content_download_time_ms",
        "adjusted_dom_parsing_time_ms",
        "adjusted_rendering_time_ms",
        "first_paint_ms",
        "first_contentful_paint_ms",
    ]
    for metric in metrics:
        df_metric = df.dropna(subset=[metric])
        if df_metric.empty:
            print(f"No data available for {metric}, skipping histogram.")
            continue
        plt.figure(figsize=(12, 6))
        sns.histplot(data=df_metric, x=metric, bins=30, kde=True, element="step")
        plt.title(f'Histogram of {metric.replace("_", " ").title()}')
        plt.xlabel(f'{metric.replace("_", " ").title()} (ms)')
        plt.ylabel("Frequency")
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f"{metric}_histogram.png"))
        plt.close()


def generate_scatter_plots(df, output_dir):
    sns.set_style("whitegrid")
    df_metric = df.dropna(
        subset=["total_transfer_size_bytes", "total_page_load_time_ms"]
    )
    if df_metric.empty:
        print("No data available for scatter plot, skipping.")
        return
    plt.figure(figsize=(12, 6))
    sns.scatterplot(
        data=df_metric, x="total_transfer_size_bytes", y="total_page_load_time_ms"
    )
    plt.title("Total Transfer Size vs. Total Page Load Time")
    plt.xlabel("Total Transfer Size (bytes)")
    plt.ylabel("Total Page Load Time (ms)")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "transfer_size_vs_load_time.png"))
    plt.close()


def generate_cdf_plots(df, output_dir):
    sns.set_style("whitegrid")
    metrics = ["total_page_load_time_ms", "ttfb_ms"]
    for metric in metrics:
        df_metric = df.dropna(subset=[metric])
        if df_metric.empty:
            print(f"No data available for {metric}, skipping CDF plot.")
            continue
        plt.figure(figsize=(12, 6))
        sns.ecdfplot(data=df_metric, x=metric)
        plt.title(f'Cumulative Distribution of {metric.replace("_", " ").title()}')
        plt.xlabel(f'{metric.replace("_", " ").title()} (ms)')
        plt.ylabel("Cumulative Probability")
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f"{metric}_cdf.png"))
        plt.close()


def plot_metrics_by_quartile(df, output_dir):
    sns.set_style("whitegrid")
    metric_to_group = "total_page_load_time_ms"
    df_clean = df.dropna(subset=[metric_to_group])
    if df_clean.empty:
        print(f"No data available for {metric_to_group}, skipping quartile plots.")
        return
    df_clean["quartile"] = pd.qcut(
        df_clean[metric_to_group], 4, labels=["Q1", "Q2", "Q3", "Q4"]
    )
    metrics = ["ttfb_ms", "content_download_time_ms"]
    for metric in metrics:
        df_metric = df_clean.dropna(subset=[metric])
        if df_metric.empty:
            print(f"No data available for {metric}, skipping quartile plot.")
            continue
        plt.figure(figsize=(12, 6))
        sns.boxplot(x="quartile", y=metric, data=df_metric)
        plt.title(
            f'{metric.replace("_", " ").title()} by Quartile of {metric_to_group.replace("_", " ").title()}'
        )
        plt.xlabel(f'Quartile of {metric_to_group.replace("_", " ").title()}')
        plt.ylabel(f'{metric.replace("_", " ").title()} (ms)')
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f"{metric}_by_quartile.png"))
        plt.close()


def generate_grid_plots(df, output_dir):
    sns.set_style("whitegrid")
    metrics = [
        "ttfb_ms",
        "content_download_time_ms",
        "adjusted_dom_parsing_time_ms",
        "adjusted_rendering_time_ms",
    ]
    num_metrics = len(metrics)
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    axes = axes.flatten()
    for i, metric in enumerate(metrics):
        df_metric = df.dropna(subset=[metric])
        if df_metric.empty:
            print(f"No data available for {metric}, skipping in grid plot.")
            continue
        sns.boxplot(data=df_metric, y=metric, ax=axes[i])
        axes[i].set_title(f'{metric.replace("_", " ").title()}')
        axes[i].set_ylabel(f'{metric.replace("_", " ").title()} (ms)')
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "grid_plots.png"))
    plt.close()


def generate_correlation_matrix(df, output_dir):
    sns.set_style("whitegrid")
    numeric_cols = df.select_dtypes(include=["float64", "int64"]).columns
    df_numeric = df[numeric_cols].dropna()
    if df_numeric.empty:
        print("No numeric data available for correlation matrix, skipping.")
        return
    corr_matrix = df_numeric.corr()
    plt.figure(figsize=(12, 10))
    sns.heatmap(corr_matrix, annot=True, fmt=".2f", cmap="coolwarm")
    plt.title("Correlation Matrix of Performance Metrics")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "correlation_matrix.png"))
    plt.close()


def plot_top_n_websites(df, output_dir, metric, n=20):
    sns.set_style("whitegrid")
    df_metric = df.dropna(subset=[metric])
    if df_metric.empty:
        print(f"No data available for {metric}, skipping top {n} websites plot.")
        return
    df_sorted = df_metric.sort_values(by=metric, ascending=False).head(n)
    plt.figure(figsize=(12, 6))
    sns.barplot(data=df_sorted, x="website", y=metric)
    plt.title(f'Top {n} Websites by {metric.replace("_", " ").title()}')
    plt.xlabel("Website")
    plt.ylabel(f'{metric.replace("_", " ").title()} (ms)')
    plt.xticks(rotation=90)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"top_{n}_{metric}.png"))
    plt.close()


def plot_with_log_scale(df, output_dir, metric):
    sns.set_style("whitegrid")
    df_metric = df[df[metric] > 0].dropna(subset=[metric])
    if df_metric.empty:
        print(f"No positive data available for {metric}, skipping log scale plot.")
        return
    plt.figure(figsize=(12, 6))
    sns.histplot(data=df_metric, x=metric, bins=30, kde=True, log_scale=True)
    plt.title(f'Histogram of {metric.replace("_", " ").title()} (Log Scale)')
    plt.xlabel(f'{metric.replace("_", " ").title()} (ms)')
    plt.ylabel("Frequency")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"{metric}_histogram_log_scale.png"))
    plt.close()


def main():
    parser = argparse.ArgumentParser(description="Generate performance graphs.")
    parser.add_argument(
        "--browser",
        type=str,
        required=True,
        choices=["chrome", "firefox"],
        help="Browser type (chrome or firefox)",
    )
    parser.add_argument(
        "--timestamp", type=str, required=True, help="Timestamp of test run"
    )
    args = parser.parse_args()
    browser = args.browser.lower()
    timestamp = args.timestamp
    base_dir = f"./android-performance/data/{browser}/{timestamp}"
    results_dir = f"{base_dir}/results"
    graphs_dir = f"{base_dir}/visualizations"
    os.makedirs(graphs_dir, exist_ok=True)
    # Load the performance data
    df = pd.read_csv(os.path.join(results_dir, "performance_metrics.csv"))
    # If 'browser' column is not in the DataFrame
    if "browser" not in df.columns:
        df["browser"] = browser.capitalize()
    # Drop rows where all relevant metrics are NaN
    df.dropna(
        subset=[
            "total_page_load_time_ms",
            "ttfb_ms",
            "content_download_time_ms",
            "adjusted_dom_parsing_time_ms",
            "adjusted_rendering_time_ms",
            "first_paint_ms",
            "first_contentful_paint_ms",
            "total_transfer_size_bytes",
        ],
        how="all",
        inplace=True,
    )
    # Proceed with plotting functions
    generate_box_plots(df, graphs_dir)
    generate_histograms(df, graphs_dir)
    generate_scatter_plots(df, graphs_dir)
    generate_cdf_plots(df, graphs_dir)
    plot_metrics_by_quartile(df, graphs_dir)
    generate_grid_plots(df, graphs_dir)
    generate_correlation_matrix(df, graphs_dir)
    # For plotting top N websites, you can call the function with specific metrics
    metrics = ["total_page_load_time_ms", "ttfb_ms"]
    for metric in metrics:
        plot_top_n_websites(df, graphs_dir, metric, n=20)
        plot_with_log_scale(df, graphs_dir, metric)
    print(f"Graphs have been generated and saved in {graphs_dir}")


if __name__ == "__main__":
    main()
