import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from scipy.stats import pearsonr
import logging
import os
import plotly.express as px

# Configure logging
logging.basicConfig(
    filename="heatmap_generation.log",
    level=logging.INFO,
    format="%(asctime)s:%(levelname)s:%(message)s",
)


def calculate_pvalues(df, row_metrics, col_metrics):
    pvalues = pd.DataFrame(index=row_metrics, columns=col_metrics)
    for row in row_metrics:
        for col in col_metrics:
            if df[row].dropna().shape[0] > 2:  # Ensure enough data points
                corr_coef, p_val = pearsonr(df[row], df[col])
                pvalues.loc[row, col] = p_val
            else:
                pvalues.loc[row, col] = np.nan
    return pvalues.astype(float)


def generate_heatmap(
    corr_matrix, pvalues_matrix, title, xlabel, ylabel, cmap="coolwarm", save_path=None
):
    plt.figure(figsize=(12, 8))
    sns.heatmap(
        corr_matrix,
        annot=True,
        fmt=".2f",
        cmap=cmap,
        vmin=-1,
        vmax=1,
        annot_kws={"size": 10},
        linewidths=0.5,
    )

    # Overlay p-values with asterisks for significance
    for i in range(corr_matrix.shape[0]):
        for j in range(corr_matrix.shape[1]):
            p_val = pvalues_matrix.iloc[i, j]
            if p_val < 0.05:
                plt.text(j + 0.5, i + 0.5, "*", color="black", ha="center", va="center")

    plt.title(f"{title}\n* Indicates p-value < 0.05")
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path)
        logging.info(f"Heatmap saved to {save_path}")
    plt.close()


def generate_interactive_heatmap(
    corr_matrix, title, save_path_html=None, save_path_png=None
):
    fig = px.imshow(
        corr_matrix,
        text_auto=True,
        aspect="auto",
        color_continuous_scale="RdBu_r",
        zmin=-1,
        zmax=1,
        title=title,
    )
    fig.update_layout(xaxis_title="DOM Metrics", yaxis_title="Network Metrics")

    if save_path_html:
        fig.write_html(save_path_html)
        logging.info(f"Interactive heatmap saved to {save_path_html}")

    if save_path_png:
        fig.write_image(save_path_png)
        logging.info(f"Interactive heatmap saved as PNG to {save_path_png}")

    fig.show()


def main():
    try:
        # Load data
        df = pd.read_csv(
            "./android-performance/data/historical/historical_performance_metrics.csv"
        )
        df["measurement_date"] = pd.to_datetime(df["measurement_date"])

        historical_graphs_dir = f"./android-performance/visualizations/historical"
        os.makedirs(historical_graphs_dir, exist_ok=True)

        # Define metrics
        network_metrics = [
            "dns_lookup_time_ms",
            "tcp_handshake_time_ms",
            "ssl_time_ms",
            "ttfb_ms",
            "content_download_time_ms",
            "total_network_time_ms",
            "total_transfer_size_bytes",
        ]

        dom_metrics = [
            "adjusted_dom_parsing_time_ms",
            "adjusted_rendering_time_ms",
            "adjusted_browser_processing_time_ms",
            "total_page_load_time_ms",
            "first_paint_ms",
            "first_contentful_paint_ms",
            "average_resource_processing_time_ms",
        ]

        # Data Cleaning: Handle zero measurements
        df_cleaned = df.replace(
            {metric: {0: np.nan} for metric in network_metrics + dom_metrics}
        )
        # Calculate medians for each metric
        medians = df_cleaned[network_metrics + dom_metrics].median()

        # Impute NaN values with the median of each metric
        df_cleaned[network_metrics + dom_metrics] = df_cleaned[
            network_metrics + dom_metrics
        ].fillna(medians)

        # Inter-Category Correlation
        inter_corr = (
            df_cleaned[network_metrics + dom_metrics]
            .corr()
            .loc[network_metrics, dom_metrics]
        )
        inter_pvalues = calculate_pvalues(df_cleaned, network_metrics, dom_metrics)
        generate_heatmap(
            inter_corr,
            inter_pvalues,
            "Inter-Category Correlation: Network vs DOM Metrics",
            "DOM Metrics",
            "Network Metrics",
            cmap="coolwarm",
            save_path=os.path.join(
                historical_graphs_dir, "inter_network_dom_correlation.png"
            ),
        )

        # Intra-Category Correlation: Network Metrics
        network_corr = df_cleaned[network_metrics].corr()
        network_pvalues = calculate_pvalues(
            df_cleaned, network_metrics, network_metrics
        )
        generate_heatmap(
            network_corr,
            network_pvalues,
            "Intra-Category Correlation: Network Metrics",
            "Network Metrics",
            "Network Metrics",
            cmap="Blues",
            save_path=os.path.join(
                historical_graphs_dir, "intra_network_correlation.png"
            ),
        )

        # Intra-Category Correlation: DOM Metrics
        dom_corr = df_cleaned[dom_metrics].corr()
        dom_pvalues = calculate_pvalues(df_cleaned, dom_metrics, dom_metrics)
        generate_heatmap(
            dom_corr,
            dom_pvalues,
            "Intra-Category Correlation: DOM Metrics",
            "DOM Metrics",
            "DOM Metrics",
            cmap="Greens",
            save_path=os.path.join(historical_graphs_dir, "intra_dom_correlation.png"),
        )

        # Generate Interactive Heatmap and save as HTML and PNG
        interactive_save_path_html = os.path.join(
            historical_graphs_dir, "inter_network_dom_correlation_interactive.html"
        )
        interactive_save_path_png = os.path.join(
            historical_graphs_dir, "inter_network_dom_correlation_interactive.png"
        )
        generate_interactive_heatmap(
            inter_corr,
            "Inter-Category Correlation: Network vs DOM Metrics",
            save_path_html=interactive_save_path_html,
            save_path_png=interactive_save_path_png,  # Optional: Requires kaleido
        )

        logging.info("Successfully generated all heatmaps.")
    except Exception as e:
        logging.error(f"Error generating heatmaps: {e}")


if __name__ == "__main__":
    main()
