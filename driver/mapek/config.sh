#!/bin/bash

# ========================
# Cross-platform sed setup
# ========================
if [[ "$OSTYPE" == "darwin"* ]]; then
  SED_INPLACE=(-i '')
else
  SED_INPLACE=(-i)
fi

# ========================
# Flags & defaults
# ========================
DRY_RUN=false
ROLLBACK=false
BACKUP_FILE=""
BACKUP_DIR="./backup"

# ========================
# Argument parsing
# ========================
cpu_requests=""
memory_requests=""
cpu_limits=""
memory_limits=""
replica="1"
mode=""
service=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    rollback) ROLLBACK=true ;;
    backup=*) BACKUP_FILE="${1#backup=}" ;;
    cpu_requests=*) cpu_requests="${1#cpu_requests=}" ;;
    memory_requests=*) memory_requests="${1#memory_requests=}" ;;
    cpu_limits=*) cpu_limits="${1#cpu_limits=}" ;;
    memory_limits=*) memory_limits="${1#memory_limits=}" ;;
    replica=*) replica="${1#replica=}" ;;
    service=*) service="${1#service=}" ;;
    mode=*) mode="${1#mode=}" ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MICRO_DIR="$SCRIPT_DIR/microservices"

echo "----------------------------"
echo "Service: ${service:-ALL}"
echo "Mode: ${mode:-N/A}"
echo "Replica: $replica"
echo "CPU requests: ${cpu_requests:-N/A}"
echo "Memory requests: ${memory_requests:-N/A}"
echo "CPU limits: ${cpu_limits:-N/A}"
echo "Memory limits: ${memory_limits:-N/A}"
echo "----------------------------"

# ========================
# Rollback
# ========================
if [ "$ROLLBACK" = true ]; then
  if [ ! -f "$BACKUP_FILE" ]; then
    echo "[ROLLBACK] Backup file not found: $BACKUP_FILE"
    exit 1
  fi
  echo "[ROLLBACK] Restoring configuration for $service from $BACKUP_FILE"
  oc apply -f "$BACKUP_FILE"
  exit 0
fi

# ========================
# Target YAML files
# ========================
files=("$MICRO_DIR/deploy-acmeair-mainservice-java.yaml"
       "$MICRO_DIR/deploy-acmeair-authservice-java.yaml"
       "$MICRO_DIR/deploy-acmeair-flightservice-java.yaml"
       "$MICRO_DIR/deploy-acmeair-customerservice-java.yaml"
       "$MICRO_DIR/deploy-acmeair-bookingservice-java.yaml")

# ========================
# Backup before change
# ========================
mkdir -p "$BACKUP_DIR"
timestamp=$(date +%Y%m%d_%H%M%S)

for file in "${files[@]}"; do
  svc=$(echo "$file" | grep -oE "acmeair-[a-z]+service" | head -1)
  if [ -z "$service" ] || [ "$service" == "$svc" ]; then
    if [ -f "$file" ]; then
      backup_path="$BACKUP_DIR/${svc}_${timestamp}.yaml"
      cp "$file" "$backup_path"
      echo "[BACKUP] Saved $svc → $backup_path"
    fi
  fi
done

update_resources() {
  local file=$1
  local container_name=$2
  
  echo "[DEBUG] Updating resources for container: $container_name in $file"
  
  sed "${SED_INPLACE[@]}" "
    /- name: $container_name/,/^[[:space:]]*- name:/ {
      /resources:/,/^[[:space:]]*[a-z]*:/ {
        /requests:/,/limits:/ {
          s|cpu: \"[^\"]*\"|cpu: \"${cpu_requests}m\"|
          s|memory: \"[^\"]*\"|memory: \"${memory_requests}Mi\"|
        }
        /limits:/,/^[[:space:]]*[a-z]*:/ {
          s|cpu: \"[^\"]*\"|cpu: \"${cpu_limits}m\"|
          s|memory: \"[^\"]*\"|memory: \"${memory_limits}Mi\"|
        }
      }
    }
  " "$file"
}

# ========================
# Apply actual changes
# ========================
for file in "${files[@]}"; do
  svc=$(echo "$file" | grep -oE "acmeair-[a-z]+service" | head -1)
  if [ -n "$service" ] && [ "$service" != "$svc" ]; then
    continue
  fi

  if [ ! -f "$file" ]; then
    echo "[SKIP] File not found: $file"
    continue
  fi

  echo "[UPDATE] Processing $svc..."
  
  container_name="${svc}-java"

  if [ "$mode" == "warning" ]; then
    sed "${SED_INPLACE[@]}" "
      /- name: $container_name/,/^[[:space:]]*- name:/ {
        /resources:/,/^[[:space:]]*env:/ {
          /limits:/,/^[[:space:]]*env:/ {
            s|cpu: \"[^\"]*\"|cpu: \"${cpu_limits}m\"|
            s|memory: \"[^\"]*\"|memory: \"${memory_limits}Mi\"|
          }
        }
      }
    " "$file"
  fi

  if [ "$mode" == "unhealthy" ]; then
    sed "${SED_INPLACE[@]}" "
      /- name: $container_name/,/^[[:space:]]*- name:/ {
        /resources:/,/^[[:space:]]*env:/ {
          /requests:/,/limits:/ {
            s|cpu: \"[^\"]*\"|cpu: \"${cpu_requests}m\"|
            s|memory: \"[^\"]*\"|memory: \"${memory_requests}Mi\"|
          }
        }
      }
    " "$file"
    
    sed "${SED_INPLACE[@]}" "
      /- name: $container_name/,/^[[:space:]]*- name:/ {
        /resources:/,/^[[:space:]]*env:/ {
          /limits:/,/^[[:space:]]*env:/ {
            s|cpu: \"[^\"]*\"|cpu: \"${cpu_limits}m\"|
            s|memory: \"[^\"]*\"|memory: \"${memory_limits}Mi\"|
          }
        }
      }
    " "$file"
  fi

  sed "${SED_INPLACE[@]}" "0,/kind: Deployment/{
    /kind: Deployment/,/^---/ {
      /name: $svc/,/^spec:/ {
        s/(replicas:[[:space:]]*)[0-9]+/\1${replica}/
      }
    }
  }" "$file"

  echo "[APPLY] Applying $file ..."
  oc apply -f "$file"
done

echo "[SUCCESS] All updates applied successfully."