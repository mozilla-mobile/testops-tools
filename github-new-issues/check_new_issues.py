# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import json
import requests
import argparse
from datetime import datetime, timedelta, UTC

def get_new_issues_json(repo_owner: str, repo_name: str, timeout: int = 15) -> list:
    # Get timestamp for 24 hours ago
    yesterday = datetime.now(UTC) - timedelta(days=1)
    since_timestamp = yesterday.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    github_issues_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues?state=open&since={since_timestamp}"

    try:
        response = requests.get(github_issues_url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Error fetching GitHub issues: {e}")
        sys.exit(1)
    
    json_data = response.json()
    if json_data is None:
        print(f"❌ No response from REST API")
        sys.exit(1)
    
    return extract_title_and_url(json_data)

def extract_title_and_url(issues_json: list) -> list:
    issues_list = []
    for issue in issues_json:
        # Skip pull requests (they have a 'pull_request' field)
        if 'pull_request' in issue:
            continue
            
        title = issue.get('title', 'No Title')
        url = issue.get('html_url', 'No URL')
        issues_list.append({'title': title, 'url': url})
    return issues_list

def create_slack_json_message(issues: list) -> dict:
    current_date = datetime.now(UTC).strftime('%Y-%m-%d')
    
    if not issues:
        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f":white_check_mark: No New GitHub Issues ({current_date})",
                        "emoji": True
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ":testops-notify: created by <https://mozilla-hub.atlassian.net/wiki/spaces/MTE/overview|Mobile Test Engineering>"
                        }
                    ]
                }
            ]
        }
    
    # Create blocks with each issue as a section
    current_date = datetime.now(UTC).strftime('%Y-%m-%d')
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f":github: New GitHub Issues ({current_date})",
                "emoji": True
            }
        }
    ]
    
    # Add each issue as a separate section
    for issue in issues:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"<{issue['url']}|{issue['title']}>"
            }
        })
    
    # Add footer
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": ":testops-notify: created by <https://mozilla-hub.atlassian.net/wiki/spaces/MTE/overview|Mobile Test Engineering>"
            }
        ]
    })
    
    return {
        "blocks": blocks
    }

def main():
    new_github_issues = get_new_issues_json('mozilla', 'firefox-ios')

    # Prepare output text
    output_text = f"📊 Found {len(new_github_issues)} new issues in the last 24 hours\n\n"
    
    for issue in new_github_issues:
        output_text += f"Title: {issue['title']}\n"
        output_text += f"Link: {issue['url']}\n"
        output_text += "-" * 80 + "\n"
    
    # Print to console
    print(output_text)
    
    # Write to text file
    with open('github-new-issues-report.txt', 'w', encoding='utf-8') as f:
        f.write(output_text)
    
    # Generate Slack message
    slack_message = create_slack_json_message(new_github_issues)
    
    with open('github-new-issues-slack.json', 'w') as f:
        json.dump(slack_message, f, indent=2)
    
    print(f"✅ Report written to github-new-issues-report.txt")
    print(f"✅ Slack message written to github-new-issues-slack.json")

if __name__ == "__main__":
    main()