#!/bin/zsh

#Get the dir of the script so that keys can be found no matter where the use is running the script from.
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
SECURITY_DIR="$(dirname "$SCRIPT_DIR")/security"

# Default environment
ENVIRONMENT="production"
force_flag=false

# Check if required commands are available
if ! command -v age-keygen &> /dev/null
then
    echo "age-keygen is not installed. Install it and try again (ex. apt install age)"
    exit 1
fi

if ! command -v kubectl &> /dev/null
then
    echo "kubectl is not installed. Install it and try again"
    echo "Installation: https://kubernetes.io/docs/tasks/tools/"
    exit 1
fi

# Check Kubernetes cluster connectivity
if ! kubectl cluster-info &> /dev/null
then
    echo "Cannot connect to Kubernetes cluster"
    echo "Please ensure kubectl is configured correctly"
    echo "Current context: $(kubectl config current-context 2>&1 || echo 'none')"
    exit 1
fi

# Parse command-line options
while getopts ":fe:" opt; do
  case $opt in
    f)
      force_flag=true
      ;;
    e)
      ENVIRONMENT="$OPTARG"
      ;;
    \?)
      echo "Invalid option: -$OPTARG"
      echo "Usage: $0 [-f] [-e environment]"
      echo "  -f: Force regeneration of keys"
      echo "  -e: Environment name (default: production)"
      exit 1
      ;;
    :)
      echo "Option -$OPTARG requires an argument"
      exit 1
      ;;
  esac
done

# Environment-specific file paths
public_key_file="$SECURITY_DIR/age_public_${ENVIRONMENT}.txt"
secret_key_file="$SECURITY_DIR/secrets/age_${ENVIRONMENT}.agekey"

echo "Environment: $ENVIRONMENT"
echo "Public key: $public_key_file"
echo "Secret key: $secret_key_file"

# Check if the age key exists and if the force flag is not set
if [ ! -e "$public_key_file" ] || [ "$force_flag" = true ]; then
    echo "Age key does not exist or -f flag is provided. Creating it now"
    mkdir -p "$SECURITY_DIR/secrets"
    rm -f "$secret_key_file" "$public_key_file"
    age-keygen -o "$secret_key_file"
    age-keygen -y "$secret_key_file" > "$public_key_file"
    echo "Generated new Age key for environment: $ENVIRONMENT"
else
    echo "Public key already exists for the $ENVIRONMENT environment. Skipping key generation. Use -f to force new key creation."
fi

echo "Checking for flux-system namespace..."
if ! kubectl get namespace flux-system &> /dev/null; then
    echo "flux-system namespace does not exist. Creating it..."
    kubectl create namespace flux-system
fi

# Create secret with environment-specific name
SECRET_NAME="sops-age"
if [ "$ENVIRONMENT" != "production" ]; then
    SECRET_NAME="sops-age-${ENVIRONMENT}"
fi

echo "Generating YAML for key (secret name: $SECRET_NAME)"
new_secret_yaml=$( cat "$secret_key_file" |
    kubectl create secret generic "$SECRET_NAME" \
                --namespace=flux-system \
                --from-file=age.agekey=/dev/stdin \
                --dry-run=client \
                -o yaml)

echo "Creating secret in cluster"
echo "$new_secret_yaml" | kubectl apply -f -
echo "Done!"
echo ""
echo "Summary:"
echo "  Environment: $ENVIRONMENT"
echo "  Public key: $public_key_file"
echo "  Secret name: $SECRET_NAME (in flux-system namespace)"