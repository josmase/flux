#!/bin/zsh

# Function to check if a command is available
if ! command -v sops &> /dev/null; then
    echo "sops is not installed"
    exit 1
fi

if [ "$#" -eq 0 ]; then
    echo "Usage: $0 <path_to_file1> [<path_to_file2> ...]"
    exit 1
fi

for file_path in "$@"; do
    if [ ! -f "$file_path" ]; then
        echo "Error: File '$file_path' not found."
        exit 1
    fi
    
    SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
    sops --age=$(cat $SCRIPT_DIR/age_public.txt) \
         --encrypt --encrypted-regex '^(data|stringData)$' --in-place "$file_path"

    echo "Encryption complete for file: $file_path"
done