import argparse
from get_change_log import get_impacted_components
from get_cases import get_cases_by_labels, create_test_run

BASE_TAG = "firefox-v147.3"
HEAD_TAG = "firefox-v147.4"
MILESTONE_ID = 6652

import argparse

from get_change_log import get_impacted_components
from get_cases import get_cases_by_labels, create_test_run


def main():
    parser = argparse.ArgumentParser(description="Run smart release test selection.")
    parser.add_argument("base_tag", help="Previous release tag")
    parser.add_argument("head_tag", help="Current release tag")
    parser.add_argument("--milestone_id", type=int, default=6652,
                        help="TestRail milestone ID")

    args = parser.parse_args()

    print(f"Base tag: {args.base_tag}")
    print(f"Head tag: {args.head_tag}")

    # Get impacted components
    impacted_components = get_impacted_components(args.base_tag, args.head_tag)
    print("Impacted components:", impacted_components)

    # Get matching test cases
    cases = get_cases_by_labels(impacted_components)
    case_ids = [c["id"] for c in cases]

    print(f"Selected {len(case_ids)} test cases")

    # Create test run
    '''
    run = create_test_run(
        case_ids=case_ids,
        milestone_id=args.milestone_id,
        name=f"{args.head_tag} – Smart Selection",
        description=f"Auto-generated from diff {args.base_tag}...{args.head_tag}"
    )

    print("Created run:", run["id"])
    print("Run URL:", run.get("url"))
    '''

if __name__ == "__main__":
    main()
