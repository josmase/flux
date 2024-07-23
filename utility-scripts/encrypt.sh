#!/bin/zsh

# Function to check if a command is available
if ! command -v sops &> /dev/null; then
    echo "sops is not installed"
    exit 1
fi

# Check for --rotate option
ROTATE=false
if [ "$1" = "--rotate" ]; then
    ROTATE=true
    shift
fi

if [ "$#" -eq 0 ]; then
    echo "Usage: $0 [--rotate] <path_to_file1> [<path_to_file2> ...]"
    exit 1
fi

#Get the dir of the script so that keys can be found no matter where the use is running the script from.
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Set the private file location
SOPS_AGE_KEY_FILE="$SCRIPT_DIR/secrets/age.agekey"

# Define common parameters for sops command
AGE_KEY=$(cat "$SCRIPT_DIR/age_public.txt")
ENCRYPTED_REGEX='^(data|stringData)$'
ENCRYPTED_PROPERTY_REGEX='^\s*(data|stringData)\s*:'
SOPS_CMD=("sops" "--age=$AGE_KEY" "--encrypted-regex=$ENCRYPTED_REGEX" "--in-place")

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
        else
            SOPS_AGE_KEY_FILE="$SOPS_AGE_KEY_FILE" "${SOPS_CMD[@]}" --encrypt "$file_path"
            echo "Encryption complete for file: $file_path"
        fi
    else
        echo "File '$file_path' does not match the pattern. Skipping..."
    fi
done
