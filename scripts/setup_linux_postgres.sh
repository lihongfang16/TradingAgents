#!/bin/bash
#
# setup_linux_postgres.sh - PostgreSQL 16 setup for Linux (Ubuntu/Debian)
# Usage: sudo bash scripts/setup_linux_postgres.sh
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Logging
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# Error handler
error_exit() {
    log_error "$1"
    exit 1
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error_exit "This script must be run as root (use sudo)"
    fi
}

# Detect distribution
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS_ID="${ID:-}"
        OS_VERSION="${VERSION_ID:-}"
    else
        error_exit "Cannot detect Linux distribution"
    fi

    case "$OS_ID" in
        ubuntu|debian)
            log_info "Detected: $OS_ID $OS_VERSION"
            ;;
        centos|rhel|almalinux|rocky)
            log_info "Detected: $OS_ID $OS_VERSION"
            ;;
        *)
            log_warn "Unsupported distribution: $OS_ID. Attempting to continue..."
            ;;
    esac
}

# Add PostgreSQL APT repository (Ubuntu/Debian)
add_postgres_repo_apt() {
    log_info "Adding PostgreSQL repository..."

    local repo_url="https://apt.postgresql.org/pub/repos/apt"
    local repo_file="/etc/apt/sources.list.d/pgdg.list"

    if [[ ! -f "$repo_file" ]]; then
        # Install gnupg and ca-certificates if needed
        apt-get update -qq
        apt-get install -y -qq gnupg ca-certificates > /dev/null 2>&1

        # Add PostgreSQL repository
        echo "deb $repo_url $(lsb_release -cs)-pgdg main" | tee "$repo_file" > /dev/null

        # Add repository key
        wget -qO- "$repo_url/pubkey.gpg" | apt-key add - > /dev/null 2>&1 || \
        curl -sSf "$repo_url/pubkey.gpg" | apt-key add - > /dev/null 2>&1

        apt-get update -qq
        log_info "PostgreSQL repository added"
    else
        log_info "PostgreSQL repository already configured"
    fi
}

# Install PostgreSQL 16
install_postgres() {
    log_info "Installing PostgreSQL 16..."

    if command -v psql &> /dev/null; then
        local current_version=$(psql --version 2>/dev/null | grep -oP '\d+' | head -1)
        if [[ "$current_version" == "16" ]]; then
            log_info "PostgreSQL 16 already installed"
            return 0
        fi
    fi

    if [[ "$OS_ID" == "ubuntu" || "$OS_ID" == "debian" ]]; then
        add_postgres_repo_apt
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql-16 > /dev/null 2>&1
    elif [[ "$OS_ID" == "centos" || "$OS_ID" == "rhel" || "$OS_ID" == "almalinux" || "$OS_ID" == "rocky" ]]; then
        yum install -y -q https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm > /dev/null 2>&1
        yum install -y -q postgresql16-server > /dev/null 2>&1
    else
        error_exit "Unsupported distribution for automatic PostgreSQL installation"
    fi

    log_info "PostgreSQL 16 installed successfully"
}

# Start and enable PostgreSQL service
start_postgres_service() {
    log_info "Starting PostgreSQL service..."

    if systemctl is-active postgresql &> /dev/null; then
        log_info "PostgreSQL service already running"
    else
        if [[ "$OS_ID" == "centos" || "$OS_ID" == "rhel" || "$OS_ID" == "almalinux" || "$OS_ID" == "rocky" ]]; then
            /usr/pgsql-16/bin/postgresql-16-setup initdb > /dev/null 2>&1
            systemctl enable postgresql-16 > /dev/null 2>&1
            systemctl start postgresql-16 > /dev/null 2>&1
        else
            systemctl enable postgresql > /dev/null 2>&1
            systemctl start postgresql > /dev/null 2>&1
        fi
    fi

    # Wait for PostgreSQL to be ready
    local retries=10
    while [[ $retries -gt 0 ]]; do
        if sudo -u postgres psql -c "SELECT 1" &> /dev/null; then
            log_info "PostgreSQL is ready"
            return 0
        fi
        sleep 1
        ((retries--))
    done

    error_exit "PostgreSQL failed to start"
}

# Create trading user
create_trading_user() {
    log_info "Creating trading user..."

    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='trading'" | grep -q 1; then
        log_info "User 'trading' already exists"
    else
        sudo -u postgres psql -c "CREATE USER trading WITH PASSWORD 'trading_password';" || \
        error_exit "Failed to create trading user"
        log_info "User 'trading' created"
    fi
}

# Create trading_db database
create_trading_database() {
    log_info "Creating trading_db database..."

    if sudo -u postgres psql -lqt | grep -q "trading_db"; then
        log_info "Database 'trading_db' already exists"
    else
        sudo -u postgres psql -c "CREATE DATABASE trading_db OWNER trading;" || \
        error_exit "Failed to create trading_db database"
        log_info "Database 'trading_db' created"
    fi
}

# Grant privileges
grant_privileges() {
    log_info "Granting privileges..."

    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE trading_db TO trading;" || \
    error_exit "Failed to grant privileges"

    # Grant schema privileges
    sudo -u postgres psql -d trading_db -c "GRANT ALL PRIVILEGES ON SCHEMA public TO trading;" || \
    log_warn "Failed to grant schema privileges (continuing)"

    log_info "Privileges granted"
}

# Configure local-only access (pg_hba.conf)
configure_access() {
    log_info "Configuring local access (local-only, no remote)..."

    local hba_conf
    if [[ "$OS_ID" == "centos" || "$OS_ID" == "rhel" || "$OS_ID" == "almalinux" || "$OS_ID" == "rocky" ]]; then
        hba_conf="/var/lib/pgsql/16/data/pg_hba.conf"
    else
        hba_conf="/etc/postgresql/16/main/pg_hba.conf"
    fi

    if [[ -f "$hba_conf" ]]; then
        # Backup original
        cp "$hba_conf" "${hba_conf}.bak" 2>/dev/null || true

        # Ensure only local connections allowed (remove remote entries)
        # Keep existing local entries, ensure trust/md5 for local
        sed -i 's/host\s*all\s*all\s*0\.0\.0\.0\/0\s*/host all all 127.0.0.1/32 /' "$hba_conf" 2>/dev/null || true
        sed -i 's/host\s*all\s*all\s*::1\/128\s*/host all all ::1\/128 md5/' "$hba_conf" 2>/dev/null || true

        # Reload config
        sudo -u postgres pg_ctl reload -D "$(dirname "$hba_conf")" > /dev/null 2>&1 || \
        systemctl reload postgresql > /dev/null 2>&1 || true

        log_info "Access configured (local connections only)"
    else
        log_warn "pg_hba.conf not found at $hba_conf, skipping access configuration"
    fi
}

# Create backup script
create_backup_script() {
    log_info "Creating backup script..."

    local backup_dir="/opt/postgres_backups"
    local backup_script="$backup_dir/backup_trading.sh"

    mkdir -p "$backup_dir"

    cat > "$backup_script" << 'EOF'
#!/bin/bash
#
# backup_trading.sh - Backup trading_db PostgreSQL database
#

set -euo pipefail

BACKUP_DIR="/opt/postgres_backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/trading_db_${DATE}.sql.gz"
RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"

# Perform backup
echo "Backing up trading_db to $BACKUP_FILE..."
sudo -u postgres pg_dump trading_db | gzip > "$BACKUP_FILE"

# Verify backup
if [[ -f "$BACKUP_FILE" && -s "$BACKUP_FILE" ]]; then
    echo "Backup successful: $BACKUP_FILE"
else
    echo "Backup failed!" >&2
    exit 1
fi

# Cleanup old backups
find "$BACKUP_DIR" -name "trading_db_*.sql.gz" -mtime +$RETENTION_DAYS -delete
echo "Old backups cleaned up (retention: $RETENTION_DAYS days)"
EOF

    chmod +x "$backup_script"
    log_info "Backup script created: $backup_script"
}

# Main
main() {
    log_info "=== PostgreSQL 16 Setup Script ==="
    log_info "Distribution detection..."
    detect_distro

    check_root
    install_postgres
    start_postgres_service
    create_trading_user
    create_trading_database
    grant_privileges
    configure_access
    create_backup_script

    log_info ""
    log_info "=== Setup Complete ==="
    log_info "PostgreSQL 16 is running"
    log_info "Database: trading_db"
    log_info "User: trading (password: trading_password)"
    log_info "Backup script: /opt/postgres_backups/backup_trading.sh"
    log_info ""
    log_info "To connect locally:"
    log_info "  sudo -u postgres psql -d trading_db"
    log_info ""
    log_info "To check status:"
    log_info "  sudo systemctl status postgresql"
}

main "$@"
