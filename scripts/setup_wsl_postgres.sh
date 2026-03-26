#!/bin/bash
# =============================================================================
# WSL2 PostgreSQL Setup Script
# =============================================================================
# Installs and configures PostgreSQL on WSL2 Ubuntu for the tradingagents project
# =============================================================================

set -e

# --- Configuration ---
readonly POSTGRES_VERSION="16"
readonly DB_USER="trading"
readonly DB_NAME="trading_db"
readonly DB_PASSWORD="${TRADING_DB_PASSWORD:-trading123}"
readonly SERVICE_PORT="5432"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly LOG_FILE="${SCRIPT_DIR}/setup_wsl_postgres.log"

# --- Colors ---
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

# --- Logging ---
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" | tee -a "$LOG_FILE"
}

info()    { log "INFO"    "${GREEN}$*${NC}"; }
warn()    { log "WARN"    "${YELLOW}$*${NC}"; }
error()   { log "ERROR"   "${RED}$*${NC}"; }
success() { log "SUCCESS" "${GREEN}$*${NC}"; }

# --- Error handler ---
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        error "Script failed with exit code $exit_code"
        error "Check log file: $LOG_FILE"
    fi
}
trap cleanup EXIT

# --- Pre-flight checks ---
check_running_in_wsl() {
    if ! grep -qi 'microsoft\|wsl' /proc/version 2>/dev/null; then
        warn "This script is designed for WSL2. Continuing anyway..."
    else
        info "WSL2 environment detected"
    fi
}

detect_ubuntu_version() {
    info "Detecting Ubuntu version..."
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        UBUNTU_VERSION="${VERSION_ID}"
        info "Ubuntu ${UBUNTU_VERSION} detected"
    else
        error "Cannot detect Ubuntu version"
        exit 1
    fi
}

# --- Main installation ---
update_packages() {
    info "Updating package lists..."
    sudo apt-get update -qq
    info "Package lists updated"
}

install_postgres() {
    info "Installing PostgreSQL ${POSTGRES_VERSION}..."

    # Check if already installed
    if command -v psql &>/dev/null; then
        local installed_version=$(psql --version | grep -oP '\d+' | head -1)
        if [ "$installed_version" -eq "$POSTGRES_VERSION" ]; then
            info "PostgreSQL ${POSTGRES_VERSION} is already installed"
            return 0
        else
            warn "Different PostgreSQL version installed (${installed_version}), upgrading..."
        fi
    fi

    # Install prerequisites
    sudo apt-get install -y gnupg2 wget

    # Add PostgreSQL APT repository
    sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
    wget -qO- https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo tee /etc/apt/trusted.gpg.d/pgdg.asc &>/dev/null

    # Install PostgreSQL
    sudo apt-get update -qq
    sudo apt-get install -y postgresql-${POSTGRES_VERSION} postgresql-client-${POSTGRES_VERSION}

    info "PostgreSQL ${POSTGRES_VERSION} installed successfully"
}

configure_postgresql() {
    info "Configuring PostgreSQL..."

    # Ensure service is available
    local pg_service="postgresql"
    local pg_version_dir="/etc/postgresql/${POSTGRES_VERSION}/main"

    if [ ! -d "$pg_version_dir" ]; then
        # For newer PostgreSQL installations using PGDG
        pg_version_dir=$(find /etc/postgresql -type d -name "${POSTGRES_VERSION}" 2>/dev/null | head -1 || true)
        if [ -z "$pg_version_dir" ]; then
            pg_service="postgresql@${POSTGRES_VERSION}-main"
            pg_version_dir="/var/lib/postgresql/${POSTGRES_VERSION}/main"
        fi
    fi

    info "PostgreSQL config directory: $pg_version_dir"

    # Configure postgresql.conf for remote access
    local conf_file="${pg_version_dir}/postgresql.conf"
    if [ -f "$conf_file" ]; then
        info "Configuring postgresql.conf..."
        sudo sed -i "s/^#listen_addresses = 'localhost'/listen_addresses = '*'/" "$conf_file"
        sudo sed -i "s/^listen_addresses = 'localhost'/listen_addresses = '*'/" "$conf_file"

        # Ensure port is set correctly
        if grep -q "^#port = " "$conf_file"; then
            sudo sed -i "s/^#port = .*/port = ${SERVICE_PORT}/" "$conf_file"
        fi
    fi

    # Configure pg_hba.conf for password authentication
    local hba_file="${pg_version_dir}/pg_hba.conf"
    if [ -f "$hba_file" ]; then
        info "Configuring pg_hba.conf..."
        # Add IPv4 local connections with md5 password auth
        if ! grep -q "host.*all.*all.*0.0.0.0/0.*md5" "$hba_file"; then
            echo "host    all             all             0.0.0.0/0               md5" | sudo tee -a "$hba_file" > /dev/null
        fi
        # Add IPv6 local connections
        if ! grep -q "host.*all.*all.*::/0.*md5" "$hba_file"; then
            echo "host    all             all             ::/0                    md5" | sudo tee -a "$hba_file" > /dev/null
        fi
    fi

    info "PostgreSQL configuration completed"
}

start_postgresql_service() {
    info "Starting PostgreSQL service..."

    # Try different service names
    local service_names=("postgresql" "postgresql@${POSTGRES_VERSION}-main" "postgresql-${POSTGRES_VERSION}")

    for svc in "${service_names[@]}"; do
        if systemctl list-units --full -all | grep -q "${svc}"; then
            sudo systemctl enable "${svc}" 2>/dev/null || true
            sudo systemctl restart "${svc}" 2>/dev/null || true
            info "Service ${svc} started"
            return 0
        fi
    done

    # Fallback: start manually
    warn "Systemd not available, starting PostgreSQL directly..."
    sudo pg_ctlcluster ${POSTGRES_VERSION} main start 2>/dev/null || \
    sudo service postgresql start 2>/dev/null || \
    sudo pg_ctl start -D /var/lib/postgresql/${POSTGRES_VERSION}/main 2>/dev/null || true

    sleep 2

    # Verify PostgreSQL is running
    if sudo -u postgres pg_isready &>/dev/null; then
        info "PostgreSQL is running"
    else
        error "Failed to start PostgreSQL"
        exit 1
    fi
}

create_user_and_database() {
    info "Creating user '${DB_USER}' and database '${DB_NAME}'..."

    # Check if user exists
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
        info "User '${DB_USER}' already exists"
    else
        sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}' CREATEDB;" 2>/dev/null
        info "User '${DB_USER}' created"
    fi

    # Check if database exists
    if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
        info "Database '${DB_NAME}' already exists"
    else
        sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" 2>/dev/null
        info "Database '${DB_NAME}' created"
    fi

    # Grant all privileges
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" 2>/dev/null
    sudo -u postgres psql -d "${DB_NAME}" -c "GRANT ALL ON SCHEMA public TO ${DB_USER};" 2>/dev/null

    success "User and database configured"
}

verify_installation() {
    info "Verifying installation..."

    # Check service status
    info "PostgreSQL service status:"
    sudo service postgresql status 2>/dev/null || sudo pg_isready -h localhost -p ${SERVICE_PORT} 2>/dev/null || true

    # Test connection
    info "Testing database connection..."
    if sudo -u postgres pg_isready -h localhost -p ${SERVICE_PORT} &>/dev/null; then
        success "PostgreSQL is accepting connections on port ${SERVICE_PORT}"
    else
        warn "Could not verify connection, but installation may have succeeded"
    fi

    # Show user info
    info "Database users:"
    sudo -u postgres psql -c "\du" 2>/dev/null | grep -E "(${DB_USER}|Role name)" || true
}

print_connection_info() {
    echo ""
    echo "============================================================================="
    success "PostgreSQL setup completed successfully!"
    echo "============================================================================="
    echo ""
    echo "  Connection Details:"
    echo "  -------------------"
    echo "  Host:     localhost"
    echo "  Port:     ${SERVICE_PORT}"
    echo "  Database: ${DB_NAME}"
    echo "  User:     ${DB_USER}"
    echo "  Password: ${DB_PASSWORD}"
    echo ""
    echo "  Windows Connection String:"
    echo "  --------------------------"
    echo "  postgresql://${DB_USER}:${DB_PASSWORD}@localhost:${SERVICE_PORT}/${DB_NAME}"
    echo ""
    echo "  Useful Commands:"
    echo "  ----------------"
    echo "  sudo service postgresql status    # Check status"
    echo "  sudo service postgresql restart   # Restart service"
    echo "  sudo -u postgres psql             # Connect as postgres"
    echo "  psql -h localhost -U ${DB_USER} -d ${DB_NAME}  # Connect as trading user"
    echo ""
    echo "  Log file: ${LOG_FILE}"
    echo "============================================================================="
}

# --- Main ---
main() {
    echo ""
    info "========================================"
    info "WSL2 PostgreSQL Setup Script"
    info "========================================"
    echo ""

    check_running_in_wsl
    detect_ubuntu_version
    update_packages
    install_postgres
    configure_postgresql
    start_postgresql_service
    create_user_and_database
    verify_installation
    print_connection_info
}

main "$@"
