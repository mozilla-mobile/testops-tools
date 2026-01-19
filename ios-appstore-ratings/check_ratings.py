# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import json
import requests
import argparse

def get_app_rating(package_id: str, timeout: int = 15) -> str :
    appstore_lookup_url = f"https://itunes.apple.com/lookup?bundleId={package_id}&country=us"

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
    rating = results[0].get('averageUserRatingForCurrentVersion', None)
    if rating is None:
        print(f"❌ No rating found for app with package ID {package_id}")
        sys.exit(1)

    return rating


def main():
    parser = argparse.ArgumentParser(description='Check iOS app store rating')
    parser.add_argument('package_id', help='Bundle ID of the iOS app (e.g., org.mozilla.ios.Firefox)')
    
    args = parser.parse_args()
    
    rating = get_app_rating(args.package_id) 
    print(rating)

if __name__ == "__main__":
    main()