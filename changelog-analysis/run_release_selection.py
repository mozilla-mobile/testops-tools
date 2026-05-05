import argparse
import json
from pathlib import Path
from get_change_log import get_base_tag, get_changed_files

LATEST_TAGS_FILE = Path(__file__).resolve().parent.parent / "testrail" / "latest_tags.json"
IOS_OWNER = "mozilla-mobile"
IOS_REPO = "firefox-ios"


def read_head_tag(product: str = "firefox") -> str:
    with open(LATEST_TAGS_FILE) as f:
        state = json.load(f)
    entry = state.get(product)
    if not entry or not entry.get("tag"):
        raise ValueError(f"No tag found for '{product}' in {LATEST_TAGS_FILE}")
    return entry["tag"]


def main():
    parser = argparse.ArgumentParser(
        description="Smart release test selection based on changelog diff.",
        epilog="Tags are read from testrail/latest_tags.json when not provided explicitly.",
    )
    parser.add_argument("--base_tag", help="Previous release tag")
    parser.add_argument("--head_tag", help="Current release tag")
    parser.add_argument("--milestone_id", type=int, help="TestRail milestone ID")
    args = parser.parse_args()

    if args.head_tag and not args.base_tag:
        head_tag = args.head_tag
        base_tag = get_base_tag(head_tag, IOS_OWNER, IOS_REPO)
    elif args.base_tag and args.head_tag:
        base_tag, head_tag = args.base_tag, args.head_tag
    elif args.base_tag or args.head_tag:
        parser.error("Provide both --base_tag and --head_tag, or only --head_tag.")
    else:
        head_tag = read_head_tag()
        base_tag = get_base_tag(head_tag, IOS_OWNER, IOS_REPO)

    print(f"Head tag: {head_tag}")
    print(f"Base tag: {base_tag}")

    print(f"\nComparing {base_tag} → {head_tag}")

    changed_files = get_changed_files(IOS_OWNER, IOS_REPO, base_tag, head_tag)

    print(f"\nChanged files ({len(changed_files)}):")
    for f in changed_files[:20]:
        print(f"  {f}")
    if len(changed_files) > 20:
        print(f"  ... and {len(changed_files) - 20} more")

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
