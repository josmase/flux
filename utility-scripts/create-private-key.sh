#!/bin/zsh

#Get the dir of the script so that keys can be found no matter where the use is running the script from.
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Function to check if a command is available
if ! command -v age-keygen &> /dev/null
then
    echo "age-keygen is not installed. Install it and try again (ex. apt install age)"
    exit 1
fi

public_key_file="$SCRIPT_DIR/age_public.txt"
secret_key_file="$SCRIPT_DIR/secrets/age.agekey"
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
    rm -f $secret_key_file $public_key_file
    age-keygen -o $secret_key_file
    age-keygen -y $secret_key_file > "$public_key_file"
else
    echo "Public key already exists for the secret. Skipping key generation. Use -f to force new key creation."
fi

echo "Generating YAML for key"
new_secret_yaml=$( cat $secret_key_file |
    kubectl create secret generic sops-age \
                --namespace=flux-system \
                --from-file=age.agekey=/dev/stdin \
                --dry-run=client \
                -o yaml)

echo "Creating secret in cluster"
echo "$new_secret_yaml" | kubectl apply -f -
echo "Done!"