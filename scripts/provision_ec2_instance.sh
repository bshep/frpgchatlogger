#!/bin/bash
set -euo pipefail

# --- Configuration ---
REGION="us-east-1"
INSTANCE_TYPE="t4g.small"
KEY_PAIR_NAME="frpgchatlogger-key-pair"
SECURITY_GROUP_NAME="frpgchatlogger-sg"
EC2_USER="ec2-user" # Default user for Amazon Linux 2023

# --- User Data Script (adapted for Amazon Linux 2023) ---
# This script will be executed on the EC2 instance's first boot.
USER_DATA_SCRIPT=$(cat << 'EOF'
#!/bin/bash
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
echo "Starting User Data script for Amazon Linux 2023..."

# 1. Update System
sudo dnf update -y

# 2. Install Dependencies
echo "Installing dependencies: python, pip, nodejs, nginx, sqlite..."
sudo dnf install -y python3 python3-pip nodejs nginx sqlite

# 3. Install Gunicorn/Uvicorn globally for initial setup
# This allows the systemd service to find them before venv is fully set up by GitHub Actions.
pip3 install gunicorn uvicorn

# 4. Create Project Directory
# The GitHub Action will transfer code here.
mkdir -p /var/www/frpgchatlogger/html

# Set appropriate permissions for the web directory.
# The EC2_USER (ec2-user) will own the files, Nginx needs read access.
# This avoids the insecure 'chmod 777'.
sudo chown -R ec2-user:ec2-user /var/www/frpgchatlogger
sudo chmod -R 755 /var/www/frpgchatlogger

# 5. Configure Nginx
cat << 'NGINX_CONF' | sudo tee /etc/nginx/conf.d/frpgchatlogger.conf
server {
    listen 80;
    server_name _; # Listen on all hostnames or specify YOUR_EC2_PUBLIC_IP_OR_DOMAIN;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        root /var/www/frpgchatlogger/html;
        index index.html index.htm;
        try_files $uri $uri/ /index.html;
    }

    error_log /var/log/nginx/frpgchatlogger_error.log;
    access_log /var/log/nginx/frpgchatlogger_access.log;
}
NGINX_CONF

# Enable and start Nginx
sudo systemctl enable nginx
sudo systemctl start nginx

# 6. Create Systemd Service for Backend
cat << 'SYSTEMD_SERVICE' | sudo tee /etc/systemd/system/frpgchatlogger_backend.service
[Unit]
Description=Gunicorn/Uvicorn instance for frpgchatlogger
After=network.target

[Service]
User=ec2-user
Group=nginx
WorkingDirectory=/var/www/frpgchatlogger/backend
ExecStart=/var/www/frpgchatlogger/backend/venv_backend/bin/python3 -m gunicorn -k uvicorn.workers.UvicornWorker --workers 4 --bind 127.0.0.1:8000 main:app
# If using FastAPI with uvicorn directly:
# ExecStart=/var/www/frpgchatlogger/backend/venv_backend/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SYSTEMD_SERVICE

# Enable systemd service. It will start successfully once the application code is deployed.
sudo systemctl enable frpgchatlogger_backend.service

# 7. Set up Cron Job for Backups
echo "Setting up cron job for backups..."
cat << 'CRON_JOB' | sudo tee /etc/cron.d/frpgchatlogger-backup
# Run database backup every 12 hours at midnight and noon
0 0,12 * * * ec2-user /usr/local/bin/backup_db.sh >> /var/log/cron.log 2>&1
CRON_JOB

echo "User Data script finished."
EOF
)

# --- Check for AWS CLI and JQ ---

if ! command -v aws &> /dev/null; then

    echo "AWS CLI is not installed. Please install it to continue."

    exit 1

fi

if ! command -v jq &> /dev/null; then

    echo "JQ is not installed. Please install it to continue (e.g., sudo dnf install -y jq or sudo apt-get install -y jq)."

    exit 1

fi

echo "--- Starting EC2 Instance Provisioning ---"

# --- 1. Create/Retrieve Key Pair ---
echo "Checking for key pair: $KEY_PAIR_NAME"
if ! aws ec2 describe-key-pairs --key-names "$KEY_PAIR_NAME" --region "$REGION" &> /dev/null;
then
    echo "Creating new key pair: $KEY_PAIR_NAME"
    aws ec2 create-key-pair --key-name "$KEY_PAIR_NAME" --query 'KeyMaterial' --output text > "$KEY_PAIR_NAME.pem"
    chmod 400 "$KEY_PAIR_NAME.pem"
    echo "Key pair '$KEY_PAIR_NAME.pem' created. Keep this file secure and add its content to GitHub Secrets (EC2_SSH_PRIVATE_KEY)."
else
    echo "Key pair '$KEY_PAIR_NAME' already exists. Ensure you have the corresponding .pem file."
fi

# --- 2. Create/Retrieve Security Group ---
echo "Checking for security group: $SECURITY_GROUP_NAME"
SECURITY_GROUP_ID=$(aws ec2 describe-security-groups --group-names "$SECURITY_GROUP_NAME" --region "$REGION" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)

if [ "$SECURITY_GROUP_ID" == "None" ] || [ -z "$SECURITY_GROUP_ID" ]; then
    echo "Creating new security group: $SECURITY_GROUP_NAME"
    SECURITY_GROUP_ID=$(aws ec2 create-security-group --group-name "$SECURITY_GROUP_NAME" --description "Security group for frpgchatlogger" --region "$REGION" --query 'GroupId' --output text)
    echo "Security Group ID: $SECURITY_GROUP_ID"

    echo "Adding SSH rule (port 22)"
    aws ec2 authorize-security-group-ingress --group-id "$SECURITY_GROUP_ID" --protocol tcp --port 22 --cidr 0.0.0.0/0 --region "$REGION"
    echo "Adding HTTP rule (port 80)"
    aws ec2 authorize-security-group-ingress --group-id "$SECURITY_GROUP_ID" --protocol tcp --port 80 --cidr 0.0.0.0/0 --region "$REGION"
    echo "Adding HTTPS rule (port 443)"
    aws ec2 authorize-security-group-ingress --group-id "$SECURITY_GROUP_ID" --protocol tcp --port 443 --cidr 0.0.0.0/0 --region "$REGION"
else
    echo "Security group '$SECURITY_GROUP_NAME' with ID '$SECURITY_GROUP_ID' already exists."
fi

# --- 3. Find Latest Amazon Linux 2023 ARM64 AMI ---
echo "Finding latest Amazon Linux 2023 (ARM64) AMI in $REGION..."
AMI_JSON=$(aws ec2 describe-images \
    --region "$REGION" \
    --owners amazon \
    --filters \
        'Name=name,Values=al2023-ami-*-arm64' \
        'Name=state,Values=available' \
    --output json)

# Check if any images were returned and extract the latest ImageId
if echo "$AMI_JSON" | jq -e '.Images | length > 0' > /dev/null; then
    AMI_ID=$(echo "$AMI_JSON" | jq -r '.Images | sort_by(.CreationDate)[-1].ImageId')
else
    # No images found, set AMI_ID to empty so the next check handles it
    AMI_ID=""
fi

if [ -z "$AMI_ID" ]; then # Removed "None" check as jq ensures empty if no match
    echo "Could not find a suitable Amazon Linux 2023 AMI. Exiting."
    exit 1
fi
echo "Using AMI ID: $AMI_ID"

# --- 4. Launch EC2 Instance with User Data ---
echo "Launching EC2 instance of type $INSTANCE_TYPE..."
RUN_INSTANCES_OUTPUT=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_PAIR_NAME" \
    --security-group-ids "$SECURITY_GROUP_ID" \
    --user-data "$USER_DATA_SCRIPT" \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=frpgchatlogger-instance}]' \
    --region "$REGION" \
    --query 'Instances[0].[InstanceId,PrivateIpAddress]' \
    --output text)

INSTANCE_ID=$(echo "$RUN_INSTANCES_OUTPUT" | awk '{print $1}')
PRIVATE_IP=$(echo "$RUN_INSTANCES_OUTPUT" | awk '{print $2}')

echo "Instance ID: $INSTANCE_ID"
echo "Private IP: $PRIVATE_IP"
echo "Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"

# --- 5. Get Public IP Address ---
PUBLIC_IP=""
ATTEMPTS=0
MAX_ATTEMPTS=10
while [ -z "$PUBLIC_IP" ] && [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
    echo "Attempt $((ATTEMPTS+1)): Retrieving public IP..."
    PUBLIC_IP=$(aws ec2 describe-instances \
        --instance-ids "$INSTANCE_ID" \
        --region "$REGION" \
        --query 'Reservations[0].Instances[0].PublicIpAddress' \
        --output text)
    if [ "$PUBLIC_IP" == "None" ]; then
        PUBLIC_IP=""
        sleep 10 # Wait before retrying
    fi
    ATTEMPTS=$((ATTEMPTS+1))
done

if [ -z "$PUBLIC_IP" ]; then
    echo "Failed to retrieve public IP address after multiple attempts. Exiting."
    exit 1
fi

echo "--- EC2 Instance Provisioned Successfully ---"
echo "Instance ID: $INSTANCE_ID"
echo "Public IP Address: $PUBLIC_IP"
echo "SSH Command: ssh -i $KEY_PAIR_NAME.pem $EC2_USER@$PUBLIC_IP"
echo ""
echo "Add the following to your GitHub Secrets:"
echo "  EC2_HOST: $PUBLIC_IP"
echo "  EC2_SSH_PRIVATE_KEY: (Content of $KEY_PAIR_NAME.pem)"
echo ""
echo "It may take a few minutes for the user data script to complete and services to start."
