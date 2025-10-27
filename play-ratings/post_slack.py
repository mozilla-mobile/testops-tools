# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import sys
import requests


def send_slack_notification():
    """Send notification to Slack about rating drop."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    package_id = os.getenv("PACKAGE_ID")
    package_name = os.getenv("PACKAGE_NAME", package_id)
    app_name = os.getenv("APP_NAME")
    old_rating = os.getenv("OLD_RATING")
    new_rating = os.getenv("NEW_RATING")
    rating_count = os.getenv("RATING_COUNT")
    version = os.getenv("VERSION")

    if not webhook_url:
        print("❌ SLACK_WEBHOOK_URL not set")
        sys.exit(1)

    old_rating_float = float(old_rating)
    new_rating_float = float(new_rating)
    rating_drop = old_rating_float - new_rating_float

    message = {
        "username": "Google Play Store Monitor",
        "icon_emoji": ":firefox:",
        "attachments": [
            {
                "color": "#ff0000",
                "fallback": f"Rating dropped for {app_name}",
                "title": f":google-play: {app_name} - Rating Drop Alert",
                "title_link": f"https://play.google.com/store/apps/details?id={package_id}",
                "fields": [
                    {"title": "App", "value": app_name, "short": True},
                    {"title": "Package", "value": package_name, "short": True},
                    {
                        "title": "Previous Rating",
                        "value": f"⭐ {old_rating_float:.1f}",
                        "short": True,
                    },
                    {
                        "title": "New Rating",
                        "value": f"⭐ {new_rating_float:.1f}",
                        "short": True,
                    },
                    {"title": "Drop", "value": f"-{rating_drop:.1f}", "short": True},
                    {"title": "Total Ratings", "value": rating_count, "short": True},
                    {"title": "Version", "value": version, "short": True},
                    {"title": "Package ID", "value": f"`{package_id}`", "short": True},
                ],
                "footer": "Created by Mobile Test Engineering • Google Play Store Monitor",
                "footer_icon": "https://emoji.slack-edge.com/T07DB2PSS3W/testops-notify/55edcdb3371320b6.png",
            }
        ],
    }

    try:
        response = requests.post(webhook_url, json=message, timeout=10)
        response.raise_for_status()
        print("✅ Slack notification sent successfully")
    except requests.RequestException as e:
        print(f"❌ Error sending Slack notification: {e}")
        sys.exit(1)


if __name__ == "__main__":
    send_slack_notification()
