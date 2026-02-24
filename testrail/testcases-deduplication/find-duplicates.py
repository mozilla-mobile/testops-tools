import pandas as pd
import re
import unicodedata
from difflib import SequenceMatcher

from sentence_transformers import SentenceTransformer
from sklearn.neighbors import NearestNeighbors


# ---------- Configuration ----------
INPUT_XLSX = "/Users/mbarone/Downloads/firefox_for_ios4.xlsx"  # File exported from testrail
EXACT_OUTPUT = "duplicates_exact.csv"
SIMILAR_OUTPUT = "similar_pairs.csv"

# Thresholds
SEMANTIC_DUP_THRESHOLD = 0.90   # >= this is considered a strong duplicate
SEMANTIC_SIM_THRESHOLD = 0.80   # >= this is considered very similar
STEP_OVERLAP_THRESHOLD = 0.80   # % of common steps to mark "shares most steps"


# ---------- Text utilities ----------

HTML_TAG_RE = re.compile(r"<.*?>", re.DOTALL)

def strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    text = HTML_TAG_RE.sub(" ", text)
    return text

def normalize_text(text: str) -> str:
    """
    Normalize text by:
    - Stripping HTML tags
    - Converting to lowercase
    - Normalizing Unicode
    - Removing numbering (1. 2) etc.) from beginning of lines
    - Collapsing whitespace
    """
    if not isinstance(text, str):
        return ""

    # Step 1: Strip whitespace and HTML first (before expensive operations)
    text = text.strip()
    text = strip_html(text)

    # Step 2: Normalize Unicode and lowercase
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()

    # Step 3: Remove numbering like "1. ", "2) ", "- ", etc. at the beginning of lines
    # This also handles double numbering like "1. 1. text"
    lines = []
    for line in text.splitlines():
        # Remove one or more number patterns at the start (handles "1. 1. text")
        line = re.sub(r"^(\s*\d+\s*[\.\)]\s*)+", " ", line)
        # Remove bullet points
        line = re.sub(r"^\s*[-•]\s*", " ", line)
        lines.append(line.strip())
    text = " ".join(l for l in lines if l)

    # Step 4: Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_numbered_items(text: str):
    """
    Converts something like:
    '1. step one\n2. step two' -> ['step one', 'step two']
    Also handles formats like '1. <p>step one</p>\n2. <p>step two</p>'
    """
    if not isinstance(text, str):
        return []

    # First remove HTML
    text = strip_html(text)

    # Split by patterns "n. " or "n) " at the beginning of line
    # Add a fictitious newline at the beginning to simplify the split
    text = "\n" + text
    pieces = re.split(r"\n\s*\d+\s*[\.\)]\s*", text)
    # pieces[0] will be what's before the first numbering, we ignore it
    steps = [normalize_text(p) for p in pieces[1:]]
    return [s for s in steps if s]


def parse_notes_steps_and_expected(notes: str):
    """
    From a Notes block with:
        Step Description:
        ...
        Expected Result:
        ...
    extracts two lists: [desc1, desc2,...], [exp1, exp2,...]
    """
    if not isinstance(notes, str):
        return [], []

    # Normalize line breaks
    text = notes.replace("\r\n", "\n").replace("\r", "\n")

    # Split by 'Step Description:'
    chunks = text.split("Step Description:")
    descs = []
    exps = []

    for chunk in chunks[1:]:  # the first piece is before the first description
        parts = chunk.split("Expected Result:", 1)
        desc = parts[0]
        exp = parts[1] if len(parts) > 1 else ""
        descs.append(normalize_text(desc))
        exps.append(normalize_text(exp))

    return descs, exps


def parse_testrail_steps(steps_text: str, expected_text: str):
    """
    Parse TestRail's 'Steps (Step)' and 'Steps (Expected Result)' columns.
    These come in format:
        Steps: "1. step one\n2. step two\n..."
        Expected: "1. expected one\n2. expected two\n..."
    Returns: ([step1, step2, ...], [expected1, expected2, ...])
    """
    steps = split_numbered_items(steps_text) if isinstance(steps_text, str) else []
    expected = split_numbered_items(expected_text) if isinstance(expected_text, str) else []
    return steps, expected


def step_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def compute_step_overlap(steps1, steps2, min_ratio=0.85):
    """
    Calculates the % of common steps by pairing each step from steps1
    with the most similar one from steps2 that exceeds min_ratio.
    Uses min() to detect when shorter tests are contained in longer ones.
    """
    if not steps1 or not steps2:
        return 0.0

    used_j = set()
    matches = 0

    for s1 in steps1:
        best_ratio = 0.0
        best_j = None
        for j, s2 in enumerate(steps2):
            if j in used_j:
                continue
            ratio = step_similarity(s1, s2)
            if ratio > best_ratio:
                best_ratio = ratio
                best_j = j
        if best_ratio >= min_ratio:
            matches += 1
            used_j.add(best_j)

    overlap = matches / min(len(steps1), len(steps2))
    return overlap


# ---------- Data loading and normalization ----------

def load_and_normalize(path: str) -> pd.DataFrame:
    # Try different header rows to find the right format
    raw = None
    for header_row in [0, 2]:
        try:
            test_df = pd.read_excel(path, header=header_row, nrows=1)
            # Check if we have ID or Unnamed: 1 column with case ID pattern
            if "ID" in test_df.columns or "Unnamed: 1" in test_df.columns:
                raw = pd.read_excel(path, header=header_row)
                break
        except Exception:
            continue

    if raw is None:
        raise ValueError("Could not determine Excel file structure")

    # Rename key columns for readability (only if they don't already exist)
    rename_map = {}
    if "Unnamed: 1" in raw.columns and "CaseID" not in raw.columns:
        rename_map["Unnamed: 1"] = "CaseID"
    if "Unnamed: 2" in raw.columns and "Title" not in raw.columns:
        rename_map["Unnamed: 2"] = "TestTitle"

    if rename_map:
        raw = raw.rename(columns=rename_map)

    # Determine which column has the Case ID
    if "ID" in raw.columns:
        case_id_col = "ID"
    elif "CaseID" in raw.columns:
        case_id_col = "CaseID"
    elif "Unnamed: 1" in raw.columns:
        case_id_col = "Unnamed: 1"
    else:
        raise ValueError("Could not find Case ID column")

    if "Title" in raw.columns:
        title_col = "Title"
    elif "TestTitle" in raw.columns:
        title_col = "TestTitle"
    elif "Unnamed: 2" in raw.columns:
        title_col = "Unnamed: 2"
    else:
        raise ValueError("Could not find Title column")

    # Keep only rows that have a CaseID
    raw = raw[raw[case_id_col].notna()].copy()

    # Extract lists of steps and expected results
    step_lists = []
    expected_lists = []

    # Store CaseID and Title for later use
    raw["_case_id"] = raw[case_id_col]
    raw["_title"] = raw[title_col]

    for _, row in raw.iterrows():
        # Try different sources for steps in priority order:
        # 1) TestRail's standard 'Steps (Step)' and 'Steps (Expected Result)' columns
        steps_col = row.get("Steps (Step)")
        expected_col = row.get("Steps (Expected Result)")

        if pd.notna(steps_col):
            steps, expected = parse_testrail_steps(steps_col, expected_col)
        else:
            # 2) Try to parse Notes (Step Description / Expected Result format)
            notes = row.get("Notes")
            descs, exps = parse_notes_steps_and_expected(notes)
            if descs:
                steps = descs
                expected = exps
            else:
                # 3) Fallback to Section Description
                section_desc = row.get("Section Description")
                steps = split_numbered_items(str(section_desc)) if pd.notna(section_desc) else []
                expected = []

        # 4) If still no expected results, try the global Expected Result column
        if not expected:
            expected_global = row.get("Expected Result")
            if pd.notna(expected_global) and isinstance(expected_global, str):
                expected = [normalize_text(expected_global)]

        step_lists.append(steps)
        expected_lists.append(expected)

    raw["steps_list"] = step_lists
    raw["expected_list"] = expected_lists

    # Canonical text fields
    raw["canonical_title"] = raw["_title"].fillna("").apply(lambda x: normalize_text(str(x)))
    raw["canonical_steps"] = raw["steps_list"].apply(
        lambda lst: " | ".join(normalize_text(s) for s in lst)
    )
    raw["canonical_expected"] = raw["expected_list"].apply(
        lambda lst: " | ".join(normalize_text(s) for s in lst)
    )

    def build_full(row):
        return (
            f"title: {row['canonical_title']}\n"
            f"steps: {row['canonical_steps']}\n"
            f"expected: {row['canonical_expected']}"
        )

    raw["canonical_full_text"] = raw.apply(build_full, axis=1)

    return raw


# ---------- Exact duplicates ----------

def find_exact_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    df["exact_key"] = df["canonical_full_text"]
    dup_groups = df.groupby("exact_key").filter(lambda g: len(g) > 1).copy()
    # Assign a group ID for each set of duplicates
    dup_groups["duplicate_group_id"] = dup_groups.groupby("exact_key").ngroup()
    return dup_groups


# ---------- Semantic similarity ----------

def compute_semantic_pairs(df: pd.DataFrame) -> pd.DataFrame:
    texts = df["canonical_full_text"].tolist()
    case_ids = df["_case_id"].tolist()
    titles = df["_title"].fillna("").tolist()

    # Local sentence-transformers model
    print("Loading embeddings model...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print("Generating embeddings...")
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=True)

    # Nearest neighbors
    print("Searching for similar neighbors...")
    nn = NearestNeighbors(metric="cosine", algorithm="brute")
    nn.fit(embeddings)

    # Include the point itself (n_neighbors=21 -> 1 self + 20 neighbors for medium datasets)
    distances, indices = nn.kneighbors(embeddings, n_neighbors=min(21, len(embeddings)))

    rows = []
    n = len(df)

    for i in range(n):
        for k in range(1, indices.shape[1]):  # skip neighbor 0 (itself)
            j = indices[i, k]
            if i >= j:
                continue  # avoid duplicating pairs (i,j) and (j,i)

            dist = distances[i, k]
            sim = 1.0 - dist

            if sim < SEMANTIC_SIM_THRESHOLD:
                continue

            steps1 = df.iloc[i]["steps_list"]
            steps2 = df.iloc[j]["steps_list"]
            overlap = compute_step_overlap(steps1, steps2)

            label = "similar"
            if sim >= SEMANTIC_DUP_THRESHOLD:
                label = "semantic_duplicate"

            shares_most_steps = overlap >= STEP_OVERLAP_THRESHOLD

            rows.append({
                "case_id_1": case_ids[i],
                "title_1": titles[i],
                "case_id_2": case_ids[j],
                "title_2": titles[j],
                "similarity": round(float(sim), 4),
                "step_overlap": round(float(overlap), 4),
                "relation": label,
                "shares_most_steps": shares_most_steps,
            })

    return pd.DataFrame(rows)


# ---------- Main ----------

def main():
    try:
        print("Loading and normalizing data...")
        df = load_and_normalize(INPUT_XLSX)

        print(f"Total test cases loaded: {len(df)}")

        if len(df) == 0:
            print("Warning: No test cases found in the input file.")
            return

        print("Searching for exact duplicates...")
        exact_dups = find_exact_duplicates(df)
        if not exact_dups.empty:
            exact_dups[["_case_id", "_title", "duplicate_group_id"]].to_csv(EXACT_OUTPUT, index=False)
            print(f"Exact duplicates saved to {EXACT_OUTPUT}")
        else:
            print("No exact duplicates found.")

        print("Searching for similar tests (semantic + steps)...")
        similar_pairs = compute_semantic_pairs(df)
        if not similar_pairs.empty:
            similar_pairs.to_csv(SIMILAR_OUTPUT, index=False)
            print(f"Similar pairs saved to {SIMILAR_OUTPUT}")
        else:
            print("No similar pairs found with the defined thresholds.")

    except FileNotFoundError:
        print(f"Error: Input file '{INPUT_XLSX}' not found.")
    except KeyError as e:
        print(f"Error: Required column not found in Excel file: {e}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
