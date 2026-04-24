# Smart Test Run Creation — Design

## Goal

Automatically create targeted TestRail test runs based on what code changed between two release versions, added to the same milestone created by the existing iOS release automation.

---

## Current flow (unchanged)

```
Jenkinsfile.check-bitrise-ios-release-tags  (cron, weekdays)
  └── detects new Bitrise tag
  └── triggers ↓

Jenkinsfile.create-milestone  (parameterised: RELEASE_TAG, RELEASE_NAME)
  └── testrail_main_ios.py
        └── creates milestone + standard smoke/functional test runs
        └── sends Slack notification
```

---

## Proposed addition

```
Jenkinsfile.create-milestone  (small addition — see below)
  └── after milestone is created, triggers ↓  (wait: false)

Jenkinsfile.create-smart-test-runs  (new — lives in changelog-analysis/)
  params: RELEASE_TAG, MILESTONE_ID
  └── get_release_tags.py   → fetches two latest firefox-v* tags from Bitrise
  │                            (RELEASE_TAG = head, previous tag = base)
  └── get_change_log.py     → GitHub compare API between base..head
  │                            → filters non-product files
  │                            → maps changed files to component labels (rules.yml)
  └── get_cases.py          → fetches TestRail cases matching those labels
  └── creates test runs in the milestone (MILESTONE_ID)
```

---

## Changes required

### 1. `testrail/testrail_main_ios.py` — expose milestone ID (2 lines)

After the `testrail.create_milestone(...)` call, write the ID to a file so the Jenkinsfile can pass it to the next job:

```python
milestone = testrail.create_milestone(
    testrail_project_id, milestone_name, milestone_description
)
# Add these two lines:
with open("milestone_id.txt", "w") as f:
    f.write(str(milestone["id"]))
```

### 2. `testrail/Jenkinsfile.create-milestone` — trigger new job

Add a new stage after `Create Milestone`, inside the `when { MILESTONE_CREATED == 'true' }` block:

```groovy
stage('Trigger Smart Test Runs') {
    when {
        expression { env.MILESTONE_CREATED == 'true' }
    }
    steps {
        script {
            def milestoneId = readFile('testrail/milestone_id.txt').trim()
            build job: 'create-smart-test-runs',
                  parameters: [
                      string(name: 'RELEASE_TAG',   value: params.RELEASE_TAG),
                      string(name: 'MILESTONE_ID',  value: milestoneId)
                  ],
                  wait: false
        }
    }
}
```

Also add `BITRISE_TOKEN = credentials('bitrise-token')` to the environment block.

### 3. `changelog-analysis/Jenkinsfile.create-smart-test-runs` — new file

New Jenkins job, configured in Jenkins pointing at this Jenkinsfile.

```groovy
pipeline {
    agent any

    parameters {
        string(name: 'RELEASE_TAG',  description: 'e.g. firefox-v150.0')
        string(name: 'MILESTONE_ID', description: 'TestRail milestone ID')
    }

    environment {
        BITRISE_TOKEN  = credentials('bitrise-token')
        GITHUB_TOKEN   = credentials('github-token')
        TESTRAIL_HOST  = credentials('testrail-host')
    }

    stages {
        stage('Checkout') { steps { checkout scm } }

        stage('Install Dependencies') {
            steps {
                dir('changelog-analysis') {
                    sh 'pip3 install --no-cache-dir -r requirements.txt'
                }
            }
        }

        stage('Create Smart Test Runs') {
            steps {
                dir('changelog-analysis') {
                    withCredentials([usernamePassword(
                        credentialsId: 'testrail-credentials',
                        usernameVariable: 'TESTRAIL_USERNAME',
                        passwordVariable: 'TESTRAIL_PASSWORD')]) {
                        sh '''
                            python3 run_release_selection.py \
                                --head_tag   ${RELEASE_TAG} \
                                --milestone_id ${MILESTONE_ID}
                        '''
                    }
                }
            }
        }
    }
}
```

### 4. `changelog-analysis/run_release_selection.py` — add `--head_tag` arg

Currently accepts `base_tag` + `head_tag` as positional args or auto-detects both from Bitrise.  
Add a `--head_tag` option so Jenkins can supply the known head tag while the script derives `base_tag` automatically from Bitrise:

```
python3 run_release_selection.py --head_tag firefox-v150.0 --milestone_id 12345
```

### 5. `changelog-analysis/requirements.txt` — new file

```
requests
pyyaml
```

---

## Credentials needed in Jenkins

| Credential ID      | Used by                        |
|--------------------|--------------------------------|
| `bitrise-token`    | get_release_tags.py (Bitrise API) |
| `github-token`     | get_change_log.py (GitHub API, optional but avoids rate limits) |
| `testrail-credentials` | get_cases.py (TestRail API) |
| `testrail-host`    | get_cases.py                   |

---

## What stays unchanged

- `Jenkinsfile.check-bitrise-ios-release-tags`
- `testrail_main_ios.py` logic (only two lines added)
- All existing test run creation behaviour
