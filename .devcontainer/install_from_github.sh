#!/bin/sh

# Function to display usage information
usage() {
    echo "Usage: $0 <owner/repo> <archive_name> <package> [version]"
}

# Function to validate input arguments
validate_args() {
    if [ $# -lt 3 ]; then
        usage
        exit 1
    fi

    owner_repo=$1
    archive_name=$2
    package=$3
    version=$4

    # Validate that owner/repo, archive_name, and package are not empty
    if [ -z "$owner_repo" ] || [ -z "$archive_name" ] || [ -z "$package" ]; then
        echo "Error: Owner/repo, archive_name, and package must not be empty."
        exit 1
    fi
}

# Function to fetch the archive from GitHub
fetch_archive() {
    local url="$1"
    local filename="$2"

    echo "Attempting to download $url..."
    # Execute curl command and store the HTTP status code in a variable
    http_status=$(curl -s -w "%{http_code}" -o "$filename" -L "$url")
    
    # Check if the HTTP status code indicates that the file was not found (status code 404)
    if [ "$http_status" -eq 404 ]; then
        echo "File not found $url"
        return 1
    fi

    # Check if curl encountered an error
    if [ "$http_status" -ne 200 ]; then
        echo "Failed to download $url. HTTP status code: $http_status"
        rm "$filename"  # Remove the partially downloaded file
        return 1
    fi

    if [ -f "$filename" ]; then
        return 0
    else
        return 1
    fi
}

# Function to download the archive
download_archive() {
    local owner_repo=$1
    local archive_name=$2
    local version=$3

    local archive_url="https://github.com/$owner_repo/releases/download/v$version/$archive_name"
    if fetch_archive "$archive_url" "$archive_name"; then
        return 0
    fi

    # Try without the 'v' prefix in the version part
    archive_url="https://github.com/$owner_repo/releases/download/$version/$archive_name"
    if fetch_archive "$archive_url" "$archive_name"; then
        return 0
    fi

    echo "Failed to download $archive_name"
    exit 1
}

# Function to install the package
install_package() {
    local package=$1
    local archive_name=$2
    local temp_folder="/tmp/${package}_temp"

    # Check if the file is a tar.gz file
    if [ -f "$archive_name" ] && [[ "$archive_name" == *.tar.gz ]]; then
        # Extract the downloaded tar to a temp folder
        mkdir -p "$temp_folder"
        tar -zxvf "$archive_name" -C "$temp_folder"

        # Remove license and readme files if they exist
        find "$temp_folder" \( -name "LICENSE*" -o -name "README*" \) -exec rm -f {} +

        # Change the permissions of extracted files
        chmod +x "$temp_folder"/*

        # Move the content of the extracted folder to /usr/local/bin
        find "$temp_folder" -maxdepth 1 -mindepth 1 -exec mv -t /usr/local/bin/ {} +
        
        # Clean up
        rm -r "$temp_folder"
        rm $archive_name
    else
        # If it's not an archive, just move the file and rename it ot whatever the package is
        chmod +x $archive_name
        mv "$archive_name" "/usr/local/bin/$package"
    fi
}



# Main function
main() {
    validate_args "$@"

    if [ -z "$version" ]; then
        version=$(curl -sL "https://api.github.com/repos/${owner_repo}/releases/latest" | grep -o '"tag_name": ".*"' | cut -d'"' -f4 | sed 's/^v//')
    fi

    archive_name=$(echo "$archive_name" | sed "s/VERSION/$version/g")

    download_archive "$owner_repo" "$archive_name" "$version"

    install_package "$package" "$archive_name"
}

# Execute main function with provided arguments
main "$@"
