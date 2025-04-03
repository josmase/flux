#!/bin/bash

usage() {
    echo "[INFO] Usage: $0 <owner/repo> <archive_name> <package> [version]"
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

    echo "[INFO] Owner/Repo: $owner_repo"
    echo "[INFO] Archive Name: $archive_name"
    echo "[INFO] Package: $package"
    echo "[INFO] Version: ${version:-Latest}"

    if [ -z "$owner_repo" ] || [ -z "$archive_name" ] || [ -z "$package" ]; then
        echo "[ERROR] Owner/repo, archive_name, and package must not be empty."
        exit 1
    fi
}

fetch_archive() {
    local url="$1"
    local filename="$2"

    echo "[INFO] Downloading: $url"

    http_status=$(curl -s -w "%{http_code}" -o "$filename" -L "$url")
    
    if [ "$http_status" -eq 404 ]; then
        echo "[WARN] File not found: $url"
        return 1
    fi

    if [ "$http_status" -ne 200 ]; then
        echo "[ERROR] Download failed: $url (HTTP $http_status)"
        rm -f "$filename"
        echo "[INFO] Removed partial file: $filename"
        return 1
    fi

    if [ -f "$filename" ]; then
        echo "[INFO] Download successful: $url"
        return 0
    else
        return 1
    fi
}

download_archive() {
    local owner_repo=$1
    local archive_name=$2
    local version=$3

    echo "[INFO] Resolving download URL for version: $version"

    local version_prefix=$(curl -sL "https://api.github.com/repos/${owner_repo}/releases/latest" | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4 | sed -E 's/([^0-9]*)[0-9]+\.[0-9]+\.[0-9]+/\1/')
    local version_without_prefix=$(echo "$version" | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+')

    echo "[INFO] Version Prefix: '${version_prefix}'"
    echo "[INFO] Version Without Prefix: '${version_without_prefix}'"

    local archive_url="https://github.com/$owner_repo/releases/download/${version_prefix}$version/$archive_name"
    if fetch_archive "$archive_url" "$archive_name"; then
        return 0
    fi

    archive_url="https://github.com/$owner_repo/releases/download/$version_without_prefix/$archive_name"
    if fetch_archive "$archive_url" "$archive_name"; then
        return 0
    fi

    echo "[ERROR] Download failed for $archive_name"
    exit 1
}

install_package() {
    local package=$1
    local archive_name=$2
    local temp_folder="/tmp/${package}_temp"

    echo "[INFO] Installing package: $package from $archive_name"

    if [ -f "$archive_name" ] && [[ "$archive_name" == *.tar.gz ]]; then
        echo "[INFO] Extracting $archive_name to $temp_folder"
        mkdir -p "$temp_folder"
        tar -zxvf "$archive_name" -C "$temp_folder"

        echo "[INFO] Removing unnecessary files"
        find "$temp_folder" \( -name "LICENSE*" -o -name "README*" \) -exec rm -f {} +

        echo "[INFO] Setting executable permissions"
        chmod +x "$temp_folder"/*

        echo "[INFO] Moving files to /usr/local/bin/"
        find "$temp_folder" -maxdepth 1 -mindepth 1 -exec mv -t /usr/local/bin/ {} +

        echo "[INFO] Removing temporary folder: $temp_folder"
        rm -r "$temp_folder"

        echo "[INFO] Removing archive: $archive_name"
        rm "$archive_name"
    else
        echo "[INFO] Moving binary to /usr/local/bin/"
        chmod +x "$archive_name"
        mv "$archive_name" "/usr/local/bin/$package"
    fi

    echo "[INFO] Installation complete: $package"
}

main() {
    validate_args "$@"

    if [ -z "$version" ]; then
        echo "[INFO] Fetching latest version"
        version=$(curl -sL "https://api.github.com/repos/${owner_repo}/releases/latest" | sed -nE 's/.*"tag_name": *"[^0-9]*([0-9]+\.[0-9]+\.[0-9]+)".*/\1/p')
        echo "[INFO] Latest version resolved: $version"
    fi

    archive_name=$(echo "$archive_name" | sed "s/VERSION/$version/g")

    download_archive "$owner_repo" "$archive_name" "$version"
    install_package "$package" "$archive_name"
}

main "$@"
