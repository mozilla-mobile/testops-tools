import argparse
from get_change_log import get_impacted_components
from get_release_tags import get_tags


def main():
    parser = argparse.ArgumentParser(
        description="Smart release test selection based on changelog diff.",
        epilog="If base_tag and head_tag are omitted, the two latest are fetched from Bitrise.",
    )
    parser.add_argument("base_tag", nargs="?", help="Previous release tag")
    parser.add_argument("head_tag", nargs="?", help="Current release tag")
    parser.add_argument("--milestone_id", type=int, default=6652,
                        help="TestRail milestone ID (default: 6652)")
    args = parser.parse_args()

    if args.base_tag and args.head_tag:
        base_tag, head_tag = args.base_tag, args.head_tag
    elif args.base_tag or args.head_tag:
        parser.error("Provide both base_tag and head_tag, or neither.")
    else:
        print("No tags provided — fetching the two latest from Bitrise...")
        base_tag, head_tag = get_tags()

    print(f"Base tag: {base_tag}")
    print(f"Head tag: {head_tag}")

    impacted_components = get_impacted_components(base_tag, head_tag)
    print("Impacted components:", impacted_components)

    # Uncomment when ready to select and create the TestRail run:
    # from get_cases import get_cases_by_labels, create_test_run
    # cases = get_cases_by_labels(impacted_components)
    # case_ids = [c["id"] for c in cases]
    # print(f"Selected {len(case_ids)} test cases")
    # run = create_test_run(
    #     case_ids=case_ids,
    #     milestone_id=args.milestone_id,
    #     name=f"{head_tag} – Smart Selection",
    #     description=f"Auto-generated from diff {base_tag}...{head_tag}",
    # )
    # print("Created run:", run["id"])
    # print("Run URL:", run.get("url"))


if __name__ == "__main__":
    main()
