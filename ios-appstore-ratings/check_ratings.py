# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import json
import requests
import argparse

ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"

def get_reviews_json(package_id: str, country: str = "us", timeout: int = 15) -> dict :
    appstore_lookup_url = f"{ITUNES_LOOKUP_URL}?bundleId={package_id}&country={country}"

    try:
        response = requests.get(appstore_lookup_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Error fetching app store data: {e}")
        sys.exit(1)
    
    json_data = response.json()
    if json_data is None:
        print(f"❌ No response from REST API")
        sys.exit(1)
    
    results = json_data.get('results', [])
    if results is None or len(results) == 0:
        print(f"❌ No response from REST API")
        sys.exit(1)
    
    return results[0]

def main():
    parser = argparse.ArgumentParser(description='Check iOS app store rating')
    parser.add_argument('--package_id', required=True, help='Bundle ID of the iOS app (e.g., org.mozilla.ios.Firefox)')
    parser.add_argument('--country', default='us', help='Country code for the App Store (default: us)')

    args = parser.parse_args()
    
    app_info = get_reviews_json(args.package_id, country=args.country)
    rating_count = app_info.get('userRatingCount', None)
    rating = app_info.get('averageUserRatingForCurrentVersion', None)
    version = app_info.get('version', None)
    print(f"⭐ Rating: {rating} | 🗳️ Number of Ratings: {rating_count} | 🏷️ Version: {version}")
    
    # Write each value to a separate file
    with open("rating.txt", "w") as f:
        f.write(str(rating))
    with open("rating_count.txt", "w") as f:
        f.write(str(rating_count))
    with open("version.txt", "w") as f:
        f.write(str(version))   

if __name__ == "__main__":
    main()
