#!/bin/zsh

# Function to check if a command is available
if ! command -v age-keygen &> /dev/null
then
    echo "age-keygen is not installed. Install it and try again (ex. apt install age)"
    exit 1
fi

public_key_file="age_public.txt"

force_flag=false

# Parse command-line options
while getopts ":f" opt; do
  case $opt in
    f)
      force_flag=true
      ;;
    \?)
      echo "Invalid option: -$OPTARG"
      exit 1
      ;;
  esac
done

# Check if the age key exists and if the force flag is not set
if [ ! -e "$public_key_file" ] || [ "$force_flag" = true ]; then
    echo "Age key does not exist or -f flag is provided. Creating it now"
    rm -f ./secrets/age.agekey $public_key_file
    age-keygen -o ./secrets/age.agekey
    age-keygen -y ./secrets/age.agekey > "$public_key_file"
else
    echo "Public key already exists for the secret. Skipping key generation. Use -f to force new key creation."
fi

echo "Adding key to cluster"
    new_secret_yaml=$( cat ./secrets/age.agekey |
       kubectl create secret generic sops-age \
                    --namespace=flux-system \
                    --from-file=age.agekey=/dev/stdin \
                    --dry-run=client \
                    -o yaml)
    echo "$new_secret_yaml" | kubectl apply -f -