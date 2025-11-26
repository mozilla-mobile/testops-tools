# Jenkins Remote Job Trigger - Quick Guide

## Prerequisites

- Mac with Jenkins installed locally
- SSH access to the Mac
- Java installed on the Mac

### Check/Install Java
```bash
# Check if Java is installed
java -version

# If not, install with Homebrew
brew install openjdk@17
```

## 1. Download Jenkins CLI
```bash
# Connect to the Mac via SSH
ssh user@mac-ip

# Download jenkins-cli.jar
cd ~
wget http://localhost:8080/jnlpJars/jenkins-cli.jar

# Or with curl
curl -O http://localhost:8080/jnlpJars/jenkins-cli.jar
```

## 2. Generate an API Token in Jenkins if you don't have one

# We alredy have one api token in one password

1. Open Jenkins: `http://localhost:8080`
2. Click on your **user** (top right)
3. Click **"Configure"**
4. In the **"API Token"** section → Click **"Add new Token"**
5. Name: "CLI-Access"
6. Click **"Generate"**
7. **Copy the token** (it is only shown once)

## 4. Create the Script
```bash
# Create the script on the Mac
nano ~/jenkins-trigger.sh
```

**Script contents:**
Copy the jenkins-trigger.sh file contained in this repo

**Give it execute permissions:**
```bash
chmod +x ~/jenkins-trigger.sh
```

## 5. Using the Script

### From the Mac (local)
```bash
# Job without parameters
~/jenkins-trigger.sh MyJob

# Job with one parameter
~/jenkins-trigger.sh MyJob BRANCH=main

# Job with several parameters
~/jenkins-trigger.sh MyJob BRANCH=develop PHONE=iPhone VERSION=18.6
```

### From a remote machine (via SSH)
```bash
# Job without parameters
ssh user@mac-ip "~/jenkins-trigger.sh MyJob"

# Job with parameters
ssh user@mac-ip "~/jenkins-trigger.sh MyJob BRANCH=main PHONE=iPhone"

# Multiple parameters
ssh user@mac-ip "~/jenkins-trigger.sh MyJob BRANCH=hotfix ENV=staging VERSION=2.0.1"
```

## 6. View Logs
```bash
# View the entire log
cat ~/jenkins-trigger.log

# View the last 10 executions
tail -10 ~/jenkins-trigger.log

# View only successful ones
grep "SUCCESS" ~/jenkins-trigger.log

# View only failed ones
grep "FAILED" ~/jenkins-trigger.log

# View today's executions
grep "$(date '+%Y-%m-%d')" ~/jenkins-trigger.log

# Search for a specific job
grep "MyJob" ~/jenkins-trigger.log

# View logs remotely
ssh user@mac-ip "tail -20 ~/jenkins-trigger.log"
```

## 7. Useful Jenkins CLI Commands
```bash
# List jobs
java -jar jenkins-cli.jar -s http://localhost:8080/ -http -auth "user:token" list-jobs

# View user information
java -jar jenkins-cli.jar -s http://localhost:8080/ -http -auth "user:token" who-am-i

# Trigger a job manually (without the script)
java -jar jenkins-cli.jar -s http://localhost:8080/ -http -auth "user:token" build "MyJob" -p PARAM1=value1

# View console output of a build
java -jar jenkins-cli.jar -s http://localhost:8080/ -http -auth "user:token" console "MyJob" -n lastBuild
```