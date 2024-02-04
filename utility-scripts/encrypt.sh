# Function to check if a command is available
if ! command -v sops &> /dev/null; then
    echo "sops is not installed. Will install assuming a debian system"
    
    #Get latest version
    SOPS_LATEST_VERSION=$(curl -s "https://api.github.com/repos/getsops/sops/releases/latest" | grep -Po '"tag_name": "v\K[0-9.]+')
    SOAPS_URL=https://github.com/mozilla/sops/releases/latest/download/sops_${SOPS_LATEST_VERSION}_amd64.deb
    echo "Will install from $SOAPS_URL"
    curl -Lo sops.deb "$SOAPS_URL"
    
    #Install it
    sudo apt --fix-broken install ./sops.deb
    
    #Cleanup
    rm -rf sops.deb
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