#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import random
import sys


from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def get_non_bot_members(channel):
    try:
        members = []
        result = client.conversations_members(channel=channel)
        user_ids = result["members"]

        for uid in user_ids:
            user_info = client.users_info(user=uid)
            user = user_info["user"]
            if not user.get("is_bot") and not user.get("deleted"):
                members.append(user["id"])

        return members

    except SlackApiError as e:
        print(f"Error fetching users: {e.response['error']}", file=sys.stderr)
        sys.exit(1)


def send_selection_message(channel, user_id):
    try:
        message = f":loudspeaker: <@{user_id}> has been selected for monitoring this month! :loudspeaker:"
        client.chat_postMessage(channel=channel, text=message)
        print(f"✅ Message sent: {message}")
    except SlackApiError as e:
        print(f"Error sending message: {e.response['error']}", file=sys.stderr)
        sys.exit(1)


def main():
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    channel_id = os.environ.get("SLACK_MOBILE_TOOLING_CHANNEL_ID")

    if not slack_token or not channel_id:
        print("❌ Required environment variables SLACK_BOT_TOKEN or SLACK_MOBILE_TOOLING_CHANNEL_ID are missing.", file=sys.stderr)
        sys.exit(1)

    global client
    client = WebClient(token=slack_token)

    members = get_non_bot_members(channel_id)

    if not members:
        print("⚠️ No eligible members found.")
        return

    selected_user = random.choice(members)
    send_selection_message(channel_id, selected_user)


if __name__ == "__main__":
    main()
