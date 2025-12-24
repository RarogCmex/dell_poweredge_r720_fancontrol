#!/bin/bash

set -e

if [[ "$(whoami)" != "root" ]]; then
    echo "You need to run this script as root."
    exit 1
fi

TARGETDIR="/opt/fan_control"
if [ ! -z "$1" ]; then
    TARGETDIR="$1"
fi

# Detect package manager and install dependencies
echo "*** Installing packaged dependencies..."
if [ -x "$(command -v apt-get)" ]; then
    apt-get update
    apt-get install -y build-essential python3-virtualenv python3-dev libsensors4-dev ipmitool
elif [ -x "$(command -v dnf)" ]; then
    dnf groupinstall -y "Development Tools"
    dnf install -y python3-virtualenv python3-devel lm_sensors-devel ipmitool
elif [ -x "$(command -v emerge)" ]; then
    # Gentoo/OpenRC specific dependencies
    echo "*** Installing Gentoo-specific dependencies..."
    echo "emerge --ask sys-apps/lm_sensors dev-python/pysensors app-admin/ipmitool"
    echo "Note: You may need to manually install the above packages and then re-run this script."
    exit 1
fi

# Ensure lm-sensors detects AMD GPUs
configure_sensors_for_amd() {
    echo "Configuring lm-sensors for AMD GPU detection..."
    
    # Check for amdgpu sensors (corrected from original draft)
    if ! sensors | grep -q "amdgpu"; then
        echo "AMD GPU not detected in sensors. Running sensors-detect..."
        yes "" | sensors-detect
        echo "Please reboot for AMD GPU sensor detection to take effect."
        return 1
    else
        echo "AMD GPU already detected in sensors output."
        return 0
    fi
}

# Verify sensors library is accessible to Python
verify_python_sensors() {
    echo "Verifying Python sensors module..."
    if ! python3 -c "import sensors" 2>/dev/null; then
        echo "Python sensors module not found. Installing..."
        if [ -x "$(command -v pip3)" ]; then
            pip3 install git+https://github.com/bastienleonard/pysensors.git@e1ead6b73b2fa14e7baaa855c3e47b078020b4f8
        else
            echo "pip3 not found. Please install Python sensors module manually."
            exit 1
        fi
    fi
}

echo "*** Creating folder '$TARGETDIR'..."
if [ ! -d "$TARGETDIR" ]; then
    mkdir -p "$TARGETDIR"
fi

echo "*** Creating and activating Python3 virtualenv..."
if [ -d "$TARGETDIR/venv" ]; then
    echo "*** Existing venv found, purging it."
    rm -r "$TARGETDIR/venv"
fi
virtualenv -p python3 "$TARGETDIR/venv"
source "$TARGETDIR/venv/bin/activate"

echo "*** Installing Python dependencies..."
pip3 install -r requirements.txt

echo "*** Deactivating Python3 virtualenv..."
deactivate

echo "*** Copying script and configuration in place..."
if [ -f "$TARGETDIR/fan_control.yaml" ]; then
    mv "$TARGETDIR/fan_control.yaml"{,.old}
fi
cp fan_control.yaml "$TARGETDIR/"
cp fan_control.py "$TARGETDIR/"

# Configuration validation helper
validate_gpu_monitoring_config() {
    local config_file="${1:-$TARGETDIR/fan_control.yaml}"
    
    if [ ! -f "$config_file" ]; then
        echo "Configuration file not found: $config_file"
        return 1
    fi
    
    # Check if GPU monitoring section exists
    if ! grep -q "gpu_monitoring:" "$config_file"; then
        echo "Adding GPU monitoring configuration to $config_file"
        cat << EOF >> "$config_file"

# GPU monitoring configuration
gpu_monitoring:
  monitor_amd_gpus: true
  monitor_nvidia_gpus: true
EOF
    fi
}

# Apply configuration validation
validate_gpu_monitoring_config "$TARGETDIR/fan_control.yaml"

# echo "*** Creating, (re)starting and enabling SystemD service..."
# cp fan-control.service /etc/systemd/system/fan-control.service
# sed -i "s#{TARGETDIR}#$TARGETDIR#g" /etc/systemd/system/fan-control.service
# systemctl daemon-reload
# systemctl restart fan-control
# systemctl enable fan-control

# echo "*** Waiting for the service to start..."
# sleep 3

# echo -e "*** All done! Check the service's output below:\n"
# systemctl status fan-control

set +e
