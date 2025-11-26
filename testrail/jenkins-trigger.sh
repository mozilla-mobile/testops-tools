#!/bin/bash

# Configuration
JENKINS_CLI="$HOME/jenkins-cli.jar"
JENKINS_URL="http://localhost:8080/"
JENKINS_USER="jenkins-username"
JENKINS_TOKEN="jenkins-token"
LOG_FILE="$HOME/jenkins-trigger.log"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Validation
if [ $# -lt 1 ]; then
    echo "Uso: $0 <job_name> [PARAM1=value1] [PARAM2=value2]"
    exit 1
fi

JOB_NAME=$1
shift

# Parameters
PARAMS=()
PARAMS_LOG=""
for arg in "$@"; do
    PARAMS+=(-p "$arg")
    PARAMS_LOG="$PARAMS_LOG $arg"
done

# Start Log
if [ -z "$PARAMS_LOG" ]; then
    PARAMS_LOG="none"
fi

log "START | Job: $JOB_NAME | Params: $PARAMS_LOG"

# Execute
java -jar "$JENKINS_CLI" -s "$JENKINS_URL" -http -auth "$JENKINS_USER:$JENKINS_TOKEN" build "$JOB_NAME" $PARAMS

# Verify the result
if [ $? -eq 0 ]; then
    log "SUCCESS | Job: $JOB_NAME | Job executed successfully"
    echo "✓ Job $JOB_NAME started"
else
    log "FAILED | Job: $JOB_NAME | Error running the job"
    echo "✗ Error running the job $JOB_NAME"
    exit 1
fi