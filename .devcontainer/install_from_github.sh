#!/bin/bash

echoerr() { echo "[ERROR] $@" 1>&2; }
echoinfo() { echo "[INFO] $@"; }

usage() {
    echoinfo "[INFO] Usage: $0 <owner/repo> <archive_name> <package> [version]"
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
        echo "[WARN] File not found: $url"
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
    local version_prefix=$3
    local version_without_prefix$4

    local archive_url="https://github.com/$owner_repo/releases/download/${version_prefix}$version/$archive_name"
    if fetch_archive "$archive_url" "$archive_name"; then
        return 0
    fi

    archive_url="https://github.com/$owner_repo/releases/download/$version_without_prefix/$archive_name"
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

    if [ -z "$version" ]; then
            release_data=$(curl -sL "https://api.github.com/repos/${owner_repo}/releases/latest")
            
            if echo "$release_data" | grep -q 'API rate limit exceeded'; then
                echoerr "API rate limit exceeded. Please authenticate to increase the rate limit."
                exit 1
            fi

            echo $release_data

            local version_prefix=$(echo "$release_data" | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4 | sed -E 's/([^0-9]*)[0-9]+\.[0-9]+\.[0-9]+/\1/')
            local version_without_prefix=$(echo "$version" | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+')

            echoinfo "Version Prefix: '${version_prefix}'"
            echoinfo "Version Without Prefix: '${version_without_prefix}'"
    fi

    archive_name=$(echo "$archive_name" | sed "s/VERSION/$version_without_prefix/g")

    download_archive "$owner_repo" "$archive_name" "$version_prefix" "$version_without_prefix"
    install_package "$package" "$archive_name"
}

main "$@"
