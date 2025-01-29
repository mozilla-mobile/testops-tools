#!/data/data/com.termux/files/usr/bin/bash

set -Eeux # use -E to attempt trapping subshell & subprocess errors

timestamp=$1
pair_ip_port=$2
pair_code=$3
conn_ip_port=$4

# Firebase Test Lab devices preinstalled Chrome Version
# ------------------------------------------------------
# Samsung Galaxy S24 Ultra API 34: Chrome 126.0.6478.182

scripts_dir="$HOME/termux_bundle/scripts"
chromedriver_dir="$HOME/termux_bundle/chromedriver"
geckodriver_dir="$HOME/termux_bundle/geckodriver"
chromedriver_version=131.0.6778.200

# Log function
log_msg() {
    echo "[Setup] $1"
}

# init file to block test's execution until file no longer exists
touch "/sdcard/Download/termux_setup_PENDING_${timestamp}"

# use file name as indicator of script status to avoid needing file read permissions
trap "touch /sdcard/Download/termux_setup_FAILED_${timestamp}; echo Error on line: $LINENO; exit;" ERR
trap "echo TODO: add wait and system test after chrome/geckdriver sessions are created; rm /sdcard/Download/termux_setup_PENDING_${timestamp};" EXIT

log_msg "Moving app assets from /sdcard to $HOME..."
#mv -f /sdcard/termux_setup_$1.sh $HOME
#mv -f /sdcard/termux_bundle_$1.tar $HOME

log_msg "Extracting termux dependencies..."
ls $HOME/termux_*
tar -xf "$HOME/termux_bundle_${timestamp}.tar"

log_msg "Granting file permissions..."
chmod -R 755 $HOME/termux_bundle

log_msg "Verifying new permissions for lib64 dynamic linker/loader..."
ls -la $HOME/termux_bundle/lib64/ld-linux-x86-64.so.2

log_msg "Moving lib64 and termux.properties..."
mv -f $HOME/termux_bundle/lib64 $PREFIX/
mv -f $HOME/termux_bundle/termux.properties $HOME/.termux

log_msg "Reloading Termux to pick up new settings..."
termux-reload-settings

log_msg "Installing required termux packages..."
yes | pkg install android-tools websocat qemu-user-x86-64 wget jq

log_msg "Verifying packages installed correctly"
adb_version=$(adb --version)
websocat_version=$(websocat --version)
qemu_version=$(qemu-x86_64 --version)

echo "ADB Version: $adb_version"
echo "Websocat Version: $websocat_version"
echo "QEMU Version: $qemu_version"

log_msg "Cleaning up temp files..."
#rm -rf $HOME/termux_bundle

log_msg "Pairing and Connecting to device..."
log_msg "Pairing IP and Port: $pair_ip_port"
log_msg "Pairing Code: $pair_code"
log_msg "Connection Info: $conn_ip_port"
bash "$scripts_dir/02_adb_pair_connect.sh" "$pair_ip_port" "$pair_code" "$conn_ip_port" > adb_pairing_connection.log 2>&1
version_info="ADB: $adb_version\nWebsocat: $websocat_version\nQemu: $qemu_version"
echo -e "$version_info"

# TODO: use google api to handle this programatically with https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json
log_msg "Checking chromedriver compatibility with Chrome..."
chrome_version=$(adb shell dumpsys package com.android.chrome |grep versionName | head -1)
log_msg "Device's Chrome version: ${chrome_version}"
available_chromedriver_versions=$(ls "$chromedriver_dir")
log_msg "Available chromedriver versions in termux_bundle: ${available_chromedriver_versions}"

# TODO: add compatibility test with currently available chromedriver versions

log_msg "Verifying chromedriver can be run with qemu..."
export QEMU_LD_PREFIX=$PREFIX
export LD_LIBRARY_PATH=$PREFIX/lib64
chromedriver_output=$(qemu-x86_64 "$chromedriver_dir/chromedriver_${chromedriver_version}" -version)

echo "Chromedriver Version Output: $chromedriver_output"

timeout=30  # seconds to wait
start_time=$(date +%s)

# Start chromedriver in background to avoid input blocking in terminal once setup script completes,
# trap SIGHUP to keep chromedriver alive after this script completes and,
# allow process to persist if terminal session is terminated
echo "init chromedriver.log..." > chromedriver.log && \
nohup setsid bash "$scripts_dir/03_run_chromedriver.sh ${chromedriver_version}" >> chromedriver.log 2>&1 & disown

# Wait for chromedriver to be ready for session creation
while ! tail -n 5 chromedriver.log | grep -q "ChromeDriver was started successfully on port"; do
    current_time=$(date +%s)
    if (( current_time - start_time > timeout )); then
        echo "Timeout waiting for chromedriver to start"
        exit 1
    fi
    sleep 1
done

bash "$scripts_dir/04_create_chromedriver_session.sh" > chromedriver_session.log 2>&1

# TODO: Use as backup if above command fails
# am startservice --user 0 -n com.termux/com.termux.app.RunCommandService \
# -a com.termux.RUN_COMMAND \
# --es com.termux.RUN_COMMAND_PATH '/data/data/com.termux/files/usr/bin/bash' \
# --esa com.termux.RUN_COMMAND_ARGUMENTS 'run_chromedriver.sh' \
# --es com.termux.RUN_COMMAND_WORKDIR '/data/data/com.termux/files/home' \
# --ez com.termux.RUN_COMMAND_BACKGROUND 'false' \
# --es com.termux.RUN_COMMAND_SESSION_ACTION '0'


# Parse the JSON response to get debuggerAddress
# Note: tail -1 assumes single line response
chrome_debugger_address=$(tail -1 chromedriver_session.log | sed 's/~$//' | jq -r '.value.capabilities["goog:chromeOptions"].debuggerAddress')
if [ -z "$chrome_debugger_address" ]; then
    echo "Failed to get debugger address"
    echo "Chromedriver Session Response: $(cat chromedriver_session.log)"
    exit 1
fi

echo "Chrome Debugger address is: $chrome_debugger_address"
# Create file with debugger port in name (replace : with _)
chrome_debug_file_name="chrome_debugger_${chrome_debugger_address//:/_}"
echo "Debug File Name: $chrome_debug_file_name"
# write to accessible location for app to read file name
# writing file name as debugger address to bypass app file read permission requirements
touch "/sdcard/Download/${chrome_debug_file_name}"

# TODO: find workaround for geckodriver not locating binary
# bash 05_setup_geckodriver.sh && \
# nohup setsid bash 06_run_geckodriver.sh > geckodriver.log 2>&1 &
# while ! tail -n 5 geckodriver.log | grep -q "GeckoDriver was started successfully on port"; do
#     current_time=$(date +%s)
#     if (( current_time - start_time > timeout )); then
#         echo "Timeout waiting for chromedriver to start"
#         exit 1
#     fi
#     sleep 1
# done

# firefox_debugger_address=$(tail -1 geckodriver_session.log | sed 's/~$//' | jq -r '.value.capabilities["moz:firefoxOptions"].debuggerAddress')

# echo "Firefox Debugger address is: $firefox_debugger_address"
# firefox_debug_file_name="firefox_debugger_${firefox_debugger_address//:/_}"

# echo "Debug File Name: $firefox_debug_file_name"
# touch "/sdcard/Download/${firefox_debug_file_name}"

touch "/sdcard/Download/termux_setup_SUCCESS_${timestamp}"