#!/bin/bash

echoerr() { echo "$(/bin/date +%S.%3N) [ERROR] $@" 1>&2; }
echoinfo() { echo "$(/bin/date +%S.%3N) [INFO] $@"; }
echowarn() { echo "$(/bin/date +%S.%3N) [WARN] $@"; }

usage() {
    echoinfo "Usage: $0 <owner/repo> <archive_name> <package> [version]"
}

validate_args() {
    if [ $# -lt 3 ]; then
        usage
        exit 1
    fi

    owner_repo=$1
    archive_name=$2
    package=$3
    version=$4

    echoinfo "Owner/Repo: $owner_repo"
    echoinfo "Archive Name: $archive_name"
    echoinfo "Package: $package"
    echoinfo "Version: ${version:-Latest}"

    if [ -z "$owner_repo" ] || [ -z "$archive_name" ] || [ -z "$package" ]; then
        echoerr "Owner/repo, archive_name, and package must not be empty."
        exit 1
    fi
}

fetch_archive() {
    local url="$1"
    local filename="$2"

    echoinfo "Downloading: $url"

    http_status=$(curl -s -w "%{http_code}" -o "$filename" -L "$url")
    
    if [ "$http_status" -eq 404 ]; then
        echowarn "File not found: $url"
        return 1
    fi

    if [ "$http_status" -ne 200 ]; then
        echoerr "Download failed: $url (HTTP $http_status)"
        rm -f "$filename"
        echoinfo "Removed partial file: $filename"
        return 1
    fi

    if [ -f "$filename" ]; then
        echoinfo "Download successful: $url"
        return 0
    else
        return 1
    fi
}

download_archive() {
    local owner_repo=$1
    local archive_name=$2
    local version_tag=$3

    # First attempt - download with the complete tag
    local archive_url="https://github.com/$owner_repo/releases/download/$version_tag/$archive_name"
    if fetch_archive "$archive_url" "$archive_name"; then
        return 0
    fi

    echoerr "Download failed for $archive_name"
    exit 1
}

install_package() {
    local package=$1
    local archive_name=$2
    local temp_folder="/tmp/${package}_temp"

    echoinfo "Installing package: $package from $archive_name"

    if [ -f "$archive_name" ] && [[ "$archive_name" == *.tar.gz ]]; then
        echoinfo "Extracting $archive_name to $temp_folder"
        mkdir -p "$temp_folder"
        tar -zxvf "$archive_name" -C "$temp_folder"

        echoinfo "Removing unnecessary files"
        find "$temp_folder" \( -name "LICENSE*" -o -name "README*" \) -exec rm -f {} +

        echoinfo "Setting executable permissions"
        chmod +x "$temp_folder"/*

        echoinfo "Moving files to /usr/local/bin/"
        find "$temp_folder" -maxdepth 1 -mindepth 1 -exec mv -t /usr/local/bin/ {} +

        echoinfo "Removing temporary folder: $temp_folder"
        rm -r "$temp_folder"

        echoinfo "Removing archive: $archive_name"
        rm "$archive_name"
    else
        echoinfo "Moving binary to /usr/local/bin/"
        chmod +x "$archive_name"
        mv "$archive_name" "/usr/local/bin/$package"
    fi

    echoinfo "Installation complete: $package"
}

main() {
    validate_args "$@"
    
    owner_repo=$1
    archive_name=$2
    package=$3
    version=$4
    
    if [ -z "$version" ]; then
        echoinfo "No version specified, fetching latest release information"
        release_data=$(curl -sL "https://api.github.com/repos/${owner_repo}/releases/latest")
        
        if echo "$release_data" | grep -q 'API rate limit exceeded'; then
            echoerr "API rate limit exceeded. Please authenticate to increase the rate limit."
            exit 1
        fi

        # Extract the full tag name directly
        tag_name=$(echo "$release_data" | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
        
        if [ -z "$tag_name" ]; then
            echoerr "Could not extract tag_name from GitHub API response"
            exit 1
        fi
        
        echoinfo "Latest release tag: $tag_name"

        # Extract version number for replacement in archive name
        version_number=$(echo "$tag_name" | sed -E 's/^[^0-9]*([0-9]+\.[0-9]+\.[0-9]+).*/\1/')
        echoinfo "Version number: $version_number"
        
        # Replace VERSION in archive name with the extracted version number
        if [ -n "$version_number" ]; then
            archive_name=$(echo "$archive_name" | sed "s/VERSION/$version_number/g")
        fi
        
        # Use the full tag for the download URL
        version_tag=$tag_name
    else
        # If version is manually specified
        version_tag=$version
        
        # Try to extract numeric part if version starts with non-numeric chars (like 'v')
        version_number=$(echo "$version" | sed -E 's/^[^0-9]*([0-9]+\.[0-9]+\.[0-9]+).*/\1/')
        
        # Replace VERSION in archive name if needed
        if [ -n "$version_number" ]; then
            archive_name=$(echo "$archive_name" | sed "s/VERSION/$version_number/g")
        fi
    fi
    
    echoinfo "Using version tag: $version_tag"
    echoinfo "Using archive name: $archive_name"

    download_archive "$owner_repo" "$archive_name" "$version_tag"
    install_package "$package" "$archive_name"
}

main "$@"