#!/bin/zsh

# Function to check if a command is available
if ! command -v sops &> /dev/null; then
    echo "sops is not installed"
    exit 1
fi

#Get the dir of the script so that keys can be found no matter where the use is running the script from.
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Default environment
ENVIRONMENT="production"

# Check for --rotate, --decrypt, and --environment options
ROTATE=false
DECRYPT=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --rotate)
            ROTATE=true
            shift
            ;;
        --decrypt)
            DECRYPT=true
            shift
            ;;
        --environment|-e)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -*)
            echo "Unknown option: $1"
            echo "Usage: $0 [--rotate] [--decrypt] [--environment <env>] <path_to_file1> [<path_to_file2> ...]"
            exit 1
            ;;
        *)
            break
            ;;
    esac
done

if [ "$#" -eq 0 ]; then
    echo "Usage: $0 [--rotate] [--decrypt] [--environment <env>] <path_to_file1> [<path_to_file2> ...]"
    echo ""
    echo "Options:"
    echo "  --rotate           Rotate encryption keys"
    echo "  --decrypt          Decrypt files"
    echo "  --environment, -e  Specify environment (default: production)"
    echo ""
    echo "Examples:"
    echo "  $0 secret.yaml                           # Encrypt with production key"
    echo "  $0 --environment development secret.yaml # Encrypt with development key"
    echo "  $0 -e dev apps/development/secret.yaml   # Short form"
    exit 1
fi

# Environment-specific key files
SOPS_AGE_KEY_FILE="$SCRIPT_DIR/secrets/age_${ENVIRONMENT}.agekey"
AGE_PUBLIC_KEY_FILE="$SCRIPT_DIR/age_public_${ENVIRONMENT}.txt"

# Verify key files exist
if [ ! -f "$SOPS_AGE_KEY_FILE" ]; then
    echo "Error: Age key file not found: $SOPS_AGE_KEY_FILE"
    echo "Run: utility-scripts/setup/create-private-key.sh -e $ENVIRONMENT"
    exit 1
fi

if [ ! -f "$AGE_PUBLIC_KEY_FILE" ]; then
    echo "Error: Age public key file not found: $AGE_PUBLIC_KEY_FILE"
    exit 1
fi

# Set the private file location
AGE_KEY=$(cat "$AGE_PUBLIC_KEY_FILE")
ENCRYPTED_REGEX='^(data|stringData)$'
ENCRYPTED_PROPERTY_REGEX='^\s*(data|stringData)\s*:'
SOPS_CMD=("sops" "--age=$AGE_KEY" "--encrypted-regex=$ENCRYPTED_REGEX" "--in-place")

echo "Environment: $ENVIRONMENT"
echo "Using Age key: $AGE_PUBLIC_KEY_FILE"
echo ""

for file_path in "$@"; do
    if [ ! -f "$file_path" ]; then
        echo "Error: File '$file_path' not found."
        exit 1
    fi

    # Check that the file contains a property that can be encrypted
    if grep -Eq "$ENCRYPTED_PROPERTY_REGEX" "$file_path"; then
        echo "File '$file_path' matches the pattern. Processing..."

        if [ "$ROTATE" = true ]; then
            SOPS_AGE_KEY_FILE="$SOPS_AGE_KEY_FILE" "${SOPS_CMD[@]}" --rotate "$file_path"
            echo "Rotation complete for file: $file_path"
        elif [ "$DECRYPT" = true ]; then
            SOPS_AGE_KEY_FILE="$SOPS_AGE_KEY_FILE" "${SOPS_CMD[@]}" --decrypt "$file_path"
            echo "Decryption complete for file: $file_path"
        else
            SOPS_AGE_KEY_FILE="$SOPS_AGE_KEY_FILE" "${SOPS_CMD[@]}" --encrypt "$file_path"
            echo "Encryption complete for file: $file_path"
        fi
    else
        echo "File '$file_path' does not match the pattern. Skipping..."
    fi
done
