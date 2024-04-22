FROM alpine:3.19.1

# Define default values for tools, empty values means that they lead to the latest available version being used.
ARG K8S_VERSION=""
ARG K9S_VERSION=""
ARG FLUX_VERSION=""
ARG SOPS_VERSION=""
ARG AGE_VERSION=""
ARG YG_VERSION=""
ARG KUSTOMIZE_VERSION=""
ARG KUBECONFORM_VERSION=""

ENV DEFAULT_USER=developer
ENV DEFAULT_USER_HOME=/home/${DEFAULT_USER}

# Install necessary packages
RUN apk add --no-cache \
    openssh-client \
    curl \
    git \
    zsh \
    unzip \
    build-base

# Create default user
RUN adduser -D ${DEFAULT_USER}
USER ${DEFAULT_USER}
WORKDIR ${DEFAULT_USER_HOME}

# Set Zsh as default shell
SHELL ["/bin/zsh", "-c"]

# Install Oh My Zsh
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"

USER root

# Add install_from_github to the image
COPY install_from_github.sh /usr/local/bin/install_from_github.sh
RUN chmod +x /usr/local/bin/install_from_github.sh

# Install Kubernetes CLI
COPY install_kubectl.sh /tmp/install_kubectl.sh
RUN sh /tmp/install_kubectl.sh

# Install k9s
RUN install_from_github.sh derailed/k9s k9s_Linux_amd64.tar.gz k9s $K9S_VERSION

# Install Flux CLI
RUN install_from_github.sh fluxcd/flux2 flux_VERSION_linux_amd64.tar.gz flux $FLUX_VERSION

# Install secret generators and managers
## Install sops
RUN install_from_github.sh getsops/sops  sops-vVERSION.linux.amd64 sops $SOPS_VERSION
RUN apk add --no-cache \
    age${AGE_VERSION:=$AGE_VERSION}

# Install validation requirements
RUN apk add --no-cache \
    yq${YG_VERSION:=$YG_VERSION} \
    kustomize${KUSTOMIZE_VERSION:=$KUSTOMIZE_VERSION} 

## Install kubeconform
RUN install_from_github.sh yannh/kubeconform kubeconform-linux-amd64.tar.gz kubeconform $KUBECONFORM_VERSION

# Switch back to default user
USER ${DEFAULT_USER}
WORKDIR ${DEFAULT_USER_HOME}
